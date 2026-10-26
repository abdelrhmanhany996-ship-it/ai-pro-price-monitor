"""Business logic: price validation, change detection, alert cycles, reminders, reports.
No network or Telegram code here; time is always passed in so it is fully testable."""
import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from . import fx as fxmod
from . import messages as M
from .config import Settings
from .db import DB
from .fetchers import FetchError, PriceResult
from .outbox import Outbox

log = logging.getLogger("aipro.engine")


class Engine:
    def __init__(self, cfg: Settings, db: DB, products: dict, outbox: Outbox):
        self.cfg, self.db, self.products, self.outbox = cfg, db, products, outbox
        self.tz = cfg.timezone

    # ---------- helpers ----------
    def state(self, pid):
        return self.db.one("SELECT * FROM product_state WHERE product_id=?", (pid,))

    def states(self):
        return {r["product_id"]: r for r in self.db.q("SELECT * FROM product_state")}

    def fx(self, now):
        return fxmod.current(self.db, now, self.cfg.fx_max_age)

    @property
    def paused(self) -> bool:
        return self.db.get("paused") == "1"

    def set_paused(self, value: bool, now: int) -> None:
        self.db.set("paused", "1" if value else "0")
        if not value:
            self.db.set("resume_ts", now)   # reminders wait for a fresh successful check

    def track_link(self, pid, cycle_id):
        p = self.products[pid]
        if self.cfg.track_base_url:
            return f"{self.cfg.track_base_url}/track/{pid}?c={cycle_id}"
        return p.url

    def buttons(self, pid, cycle_id):
        rows = [[{"text": "🔗 افتح المنتج", "url": self.track_link(pid, cycle_id)}]]
        if not self.cfg.track_base_url:   # no public tracking domain: allow stopping from Telegram
            rows.append([{"text": "🔕 أوقف التذكير", "callback_data": f"stop:{pid}:{cycle_id}"}])
        return rows

    # ---------- checks ----------
    def record_failure(self, pid: str, err: FetchError, now: int) -> None:
        review = err.kind in ("parse", "currency")
        with self.db.tx():
            self.db.x("INSERT INTO checks(product_id,ts,ok,error_kind,error) VALUES(?,?,0,?,?)",
                      (pid, now, err.kind, str(err)))
            if not self.state(pid):
                self.db.x("INSERT INTO product_state(product_id) VALUES(?)", (pid,))
            self.db.x("UPDATE product_state SET consecutive_failures=consecutive_failures+1,last_error=?,"
                      "last_error_ts=?,status=?,pending_price=NULL,pending_count=0,"
                      "outage_id=COALESCE(outage_id,?) WHERE product_id=?",
                      (str(err), now, "review" if review else "error", now, pid))
            st = self.state(pid)
            if st["consecutive_failures"] == self.cfg.error_alert_after:
                self.outbox.enqueue(f"err:{pid}:{st['outage_id']}", "error",
                                    M.error_text(self.products[pid], st, self.tz), now=now)
        self.db.log_error(now, pid, f"{err.kind}: {err}")

    def record_success(self, pid: str, res: PriceResult, now: int) -> None:
        p = self.products[pid]
        if res.currency != p.currency or res.price <= 0:
            return self.record_failure(pid, FetchError("currency", f"العملة {res.currency} غير متوقعة"), now)
        price = res.price
        with self.db.tx():
            self.db.x("INSERT INTO checks(product_id,ts,ok,price,currency) VALUES(?,?,1,?,?)",
                      (pid, now, str(price), res.currency))
            st = self.state(pid)
            if not st:
                self.db.x("INSERT INTO product_state(product_id) VALUES(?)", (pid,))
                st = self.state(pid)
            was_outage = st["outage_id"]
            alerted_outage = st["consecutive_failures"] >= self.cfg.error_alert_after
            self.db.x("UPDATE product_state SET consecutive_failures=0,outage_id=NULL,status='ok',"
                      "last_error=NULL,last_ok_ts=? WHERE product_id=?", (now, pid))
            old = Decimal(st["price"]) if st["price"] is not None else None
            if old is None:                                   # first reading = baseline, no report
                self._accept(pid, price, res.currency, now)
            elif old == price:
                self.db.x("UPDATE product_state SET pending_price=NULL,pending_count=0 WHERE product_id=?", (pid,))
            else:
                count = (st["pending_count"] + 1) if st["pending_price"] == str(price) else 1
                if count >= self.cfg.confirm_checks:
                    self._accept(pid, price, res.currency, now, old=old)
                else:
                    self.db.x("UPDATE product_state SET pending_price=?,pending_count=? WHERE product_id=?",
                              (str(price), count, pid))
            if alerted_outage:
                self.outbox.enqueue(f"recover:{pid}:{was_outage}", "recovery",
                                    M.recovered_text(p, self.state(pid), self.tz), now=now)
        self.evaluate_threshold(pid, now)

    def _accept(self, pid, price, cur, now, old=None):
        self.db.x("UPDATE product_state SET price=?,currency=?,price_since=?,pending_price=NULL,"
                  "pending_count=0 WHERE product_id=?", (str(price), cur, now, pid))
        if old is None:
            return
        cid = self.db.x("INSERT INTO price_changes(product_id,ts,old_price,new_price,currency) VALUES(?,?,?,?,?)",
                        (pid, now, str(old), str(price), cur)).lastrowid
        text = M.change_report(self.products[pid], old, price, cur, self.fx(now), now,
                               list(self.products.values()), self.states(), self.tz, self.cfg.threshold_egp)
        self.outbox.enqueue(f"change:{cid}", "change", text, now=now)

    # ---------- threshold cycles ----------
    def open_cycle(self, pid):
        return self.db.one("SELECT * FROM alert_cycles WHERE product_id=? AND ended_ts IS NULL", (pid,))

    def evaluate_threshold(self, pid: str, now: int) -> None:
        st = self.state(pid)
        if not st or st["price"] is None:
            return
        fx = self.fx(now)
        egp = M.to_egp(Decimal(st["price"]), st["currency"], fx)
        if egp is None:      # USD without a trusted rate: cannot judge, change nothing
            return
        below = egp < self.cfg.threshold_egp          # strict: 200 is NOT below 200
        with self.db.tx():
            cyc = self.open_cycle(pid)
            if below and not cyc:
                cid = self.db.x("INSERT INTO alert_cycles(product_id,started_ts,start_price,start_egp) "
                                "VALUES(?,?,?,?)", (pid, now, st["price"], str(egp))).lastrowid
                text = M.alert_text(self.products[pid], Decimal(st["price"]), st["currency"], egp,
                                    self.cfg.threshold_egp, fx, now, self.track_link(pid, cid), self.tz)
                self.outbox.enqueue(f"alert:{cid}", "alert", text, self.buttons(pid, cid), now=now)
            elif not below and cyc:
                self.db.x("UPDATE alert_cycles SET ended_ts=? WHERE id=?", (now, cyc["id"]))

    def due_reminders(self, now: int) -> int:
        if self.paused:
            return 0
        resume_ts = int(self.db.get("resume_ts", 0))
        n = 0
        for cyc in self.db.q("SELECT * FROM alert_cycles WHERE ended_ts IS NULL AND clicked_ts IS NULL"):
            pid, st = cyc["product_id"], self.state(cyc["product_id"])
            if not st or st["last_ok_ts"] is None or st["last_ok_ts"] < resume_ts:
                continue
            if now - st["last_ok_ts"] > self.cfg.max_stale:
                continue                              # price is stale; don't nag with old data
            if now - (cyc["last_reminder_ts"] or cyc["started_ts"]) < self.cfg.reminder_interval:
                continue
            k = cyc["reminders_sent"] + 1
            fx = self.fx(now)
            price = Decimal(st["price"])
            text = M.alert_text(self.products[pid], price, st["currency"], M.to_egp(price, st["currency"], fx),
                                self.cfg.threshold_egp, fx, st["last_ok_ts"], self.track_link(pid, cyc["id"]),
                                self.tz, reminder_n=k)
            with self.db.tx():
                if self.outbox.enqueue(f"remind:{cyc['id']}:{k}", "reminder", text,
                                       self.buttons(pid, cyc["id"]), now=now):
                    n += 1
                self.db.x("UPDATE alert_cycles SET reminders_sent=?,last_reminder_ts=? WHERE id=?",
                          (k, now, cyc["id"]))
        return n

    def register_click(self, pid: str, cycle_id: int | None, now: int) -> bool:
        """Record a tracking click. Stops reminders only for this product's *open* cycle."""
        with self.db.tx():
            cyc = (self.db.one("SELECT * FROM alert_cycles WHERE id=? AND product_id=?", (cycle_id, pid))
                   if cycle_id else self.open_cycle(pid))
            stopped = bool(cyc and cyc["ended_ts"] is None and cyc["clicked_ts"] is None)
            self.db.x("INSERT INTO clicks(product_id,cycle_id,ts,stopped) VALUES(?,?,?,?)",
                      (pid, cyc["id"] if cyc else None, now, int(stopped)))
            if stopped:
                self.db.x("UPDATE alert_cycles SET clicked_ts=? WHERE id=?", (now, cyc["id"]))
        return stopped

    # ---------- reports ----------
    def _table(self, now):
        return M.prices_table(list(self.products.values()), self.states(), self.fx(now), self.tz,
                              self.cfg.threshold_egp)

    def prices_text(self, now: int) -> str:
        head = M.PAUSE_BANNER if self.paused else ""
        return f"{head}💰 <b>الأسعار الحالية</b>\n{self._table(now)}\n🕒 {M.when(now, self.tz)}"

    def status_text(self, now: int) -> str:
        cycles = self.db.q("SELECT * FROM alert_cycles WHERE ended_ts IS NULL")
        below = [self.products[c["product_id"]].name for c in cycles]
        active = [self.products[c["product_id"]].name for c in cycles if c["clicked_ts"] is None]
        state = "⏸ متوقفة مؤقتًا" if self.paused else "▶️ تعمل"
        out = [f"🖥 <b>حالة النظام</b> — {state}",
               f"فحص كل {self.cfg.check_interval // 60} د · تذكير كل {self.cfg.reminder_interval // 60} د", "",
               self._table(now), "",
               "📉 تحت الحد: " + ("، ".join(below) or "لا يوجد"),
               "🔔 تذكيرات نشطة: " + ("، ".join(active) or "لا يوجد")]
        errs = self.db.q("SELECT ts,source,message FROM errors ORDER BY id DESC LIMIT 3")
        if errs:
            out.append("⚠️ آخر الأخطاء:")
            out += [f"• {M.when(e['ts'], self.tz, True)} {e['source']}: {e['message']}" for e in errs]
        else:
            out.append("⚠️ آخر الأخطاء: لا يوجد")
        return "\n".join(out)

    def daily_report_text(self, now: int) -> str:
        dt = datetime.fromtimestamp(now, ZoneInfo(self.tz))
        start = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        fx, sts = self.fx(now), self.states()
        rows, notes = [], []
        for p in self.products.values():
            st = sts.get(p.id)
            mark, price, egp, _ = M._row_state(p, st, fx, self.cfg.threshold_egp)
            vals = [Decimal(r["price"]) for r in self.db.q(
                "SELECT price FROM checks WHERE product_id=? AND ts>=? AND ok=1", (p.id, start))]
            fails = self.db.one("SELECT COUNT(*) c FROM checks WHERE product_id=? AND ts>=? AND ok=0", (p.id, start))["c"]
            changes = self.db.one("SELECT COUNT(*) c FROM price_changes WHERE product_id=? AND ts>=?", (p.id, start))["c"]
            lo, hi = (f"{min(vals):g}", f"{max(vals):g}") if vals else ("—", "—")
            if not vals:
                notes.append(f"• {p.name}: لا توجد بيانات كافية اليوم")
            rows.append([p.name, price, egp, lo, hi, changes, fails, mark])
        out = [M.PAUSE_BANNER.strip()] if self.paused else []
        out += [f"🗓 <b>التقرير اليومي</b> — {dt:%Y-%m-%d}", M.daily_table(rows),
                f"Min/Max = أقل/أعلى اليوم · Chg = مرات التغيّر · Fail = فشل الفحص\n"
                f"🟢 أقل من {self.cfg.threshold_egp:f} جنيه · 🔴 فشل/لا بيانات\n{M.fx_footer(fx, self.tz)}"]
        out += notes
        out.append("")
        cycles = self.db.q("SELECT * FROM alert_cycles WHERE ended_ts IS NULL")
        if cycles:
            out.append("🔔 <b>التنبيهات النشطة:</b>")
            for c in cycles:
                out.append(f"• {self.products[c['product_id']].name}: " +
                           ("تم الضغط على الرابط — التذكير متوقف" if c["clicked_ts"] else "التذكير مستمر"))
        else:
            out.append(f"🔔 التنبيهات النشطة: لا يوجد (لا سعر أقل من {self.cfg.threshold_egp:f} جنيه)")
        return "\n".join(out)

    def send_daily_if_due(self, now: int) -> bool:
        dt = datetime.fromtimestamp(now, ZoneInfo(self.tz))
        h, m = map(int, self.cfg.daily_time.split(":"))
        if (dt.hour, dt.minute) < (h, m):
            return False
        return self.outbox.enqueue(f"daily:{dt:%Y-%m-%d}", "daily", self.daily_report_text(now), now=now)
