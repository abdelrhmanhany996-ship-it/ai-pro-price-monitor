import argparse
import fcntl
import logging
import os
import sys
import threading
import time

from . import bot, config, fx as fxmod, logsetup, web
from .db import DB
from .engine import Engine
from .fetchers import FetchError
from .outbox import Outbox
from .products import PRODUCTS
from .telegram import Telegram, TelegramError

log = logging.getLogger("aipro")
BACKOFF_KINDS = ("blocked", "rate_limited")


class App:
    def __init__(self, cfg: config.Settings):
        self.cfg = cfg
        self.db = DB(cfg.db_path)
        self.outbox = Outbox(self.db)
        self.engine = Engine(cfg, self.db, PRODUCTS, self.outbox)
        self.tg = Telegram(cfg.token, cfg.chat_id) if cfg.telegram_ready else None
        self.stop = threading.Event()
        self.kick = {pid: threading.Event() for pid in PRODUCTS}
        self.fx_kick = threading.Event()
        self.started = time.time()

    # --- per-product loop: failure of one site never affects another ---
    def check_once(self, pid: str) -> None:
        now = int(time.time())
        try:
            res = PRODUCTS[pid].fetch()
        except FetchError as e:
            self.engine.record_failure(pid, e, now)
            raise
        except Exception as e:                                  # parser bug etc.
            err = FetchError("parse", f"{type(e).__name__}")
            self.engine.record_failure(pid, err, now)
            raise err from None
        self.engine.record_success(pid, res, now)

    def product_loop(self, pid: str) -> None:
        fails = 0
        self.stop.wait(list(PRODUCTS).index(pid) * min(3, self.cfg.check_interval / 3))           # stagger sites
        while not self.stop.is_set():
            delay = self.cfg.check_interval
            if not self.engine.paused:
                try:
                    self.check_once(pid)
                    fails = 0
                except FetchError as e:
                    fails += 1
                    log.warning("%s check failed: %s: %s", pid, e.kind, e)
                    if e.kind in BACKOFF_KINDS:                 # be polite to sites that push back
                        delay = min(self.cfg.check_interval * 2 ** min(fails, 4), 3600)
                except Exception:
                    log.exception("%s loop error", pid)
            self.kick[pid].wait(delay)
            self.kick[pid].clear()

    def refresh_fx(self) -> None:
        now = int(time.time())
        try:
            fxmod.save(self.db, fxmod.fetch_rate(now))
        except Exception as e:
            log.warning("fx refresh failed: %s", type(e).__name__)
            self.db.log_error(now, "fx", type(e).__name__)

    def maintenance_loop(self) -> None:
        last_fx = 0.0
        while not self.stop.is_set():
            now = int(time.time())
            try:
                if now - last_fx >= self.cfg.fx_refresh or self.fx_kick.is_set():
                    self.refresh_fx()
                    last_fx = now
                    self.fx_kick.clear()
                if not self.engine.paused:
                    for pid in PRODUCTS:                         # fx change may move a USD price across the limit
                        self.engine.evaluate_threshold(pid, now)
                    self.engine.due_reminders(now)
                if now - self.started >= 90:        # let the first checks finish before the daily report
                    self.engine.send_daily_if_due(now)
                self.flush()
            except Exception:
                log.exception("maintenance error")
            self.stop.wait(15)

    def flush(self) -> None:
        if self.tg:
            self.outbox.flush(lambda text, buttons: self.tg.send(text, buttons))

    # --- Telegram polling ---
    def poll_loop(self) -> None:
        offset = int(self.db.get("tg_offset", 0)) or None
        while not self.stop.is_set():
            try:
                for u in self.tg.updates(offset):
                    offset = u["update_id"] + 1
                    self.db.set("tg_offset", offset)
                    self.handle_update(u)
            except TelegramError as e:
                log.warning("polling error: %s", e)
                self.stop.wait(10)

    def handle_update(self, u: dict) -> None:
        now = int(time.time())
        if "callback_query" in u:
            cb = u["callback_query"]
            chat = (cb.get("message") or {}).get("chat", {}).get("id")
            if not bot.is_authorized(chat, self.cfg.chat_id):
                return
            if cb.get("data", "").startswith("stop:"):
                _, pid, cid = cb["data"].split(":")
                if pid in PRODUCTS:
                    self.engine.register_click(pid, int(cid), now)
                self.tg.answer_callback(cb["id"], "تم إيقاف التذكير لهذا المنتج")
            return
        m = u.get("message") or {}
        if not bot.is_authorized(m.get("chat", {}).get("id"), self.cfg.chat_id):
            log.warning("ignored message from unauthorized chat")
            return
        if not bot.is_command_text(str(m.get("text", ""))):
            return
        reply = bot.handle_command(self.engine, m["text"], now, on_resume=self.kick_all)
        if reply:
            self.tg.send(reply, keyboard=bot.KEYBOARD)

    def kick_all(self) -> None:
        for e in self.kick.values():
            e.set()

    def run(self) -> None:
        self.outbox.recover_stuck()
        srv = web.serve(self.engine, self.cfg.web_host, self.cfg.web_port)
        threads = [threading.Thread(target=srv.serve_forever, name="web", daemon=True),
                   threading.Thread(target=self.maintenance_loop, name="maint", daemon=True)]
        threads += [threading.Thread(target=self.product_loop, args=(pid,), name=f"chk-{pid}", daemon=True)
                    for pid in PRODUCTS]
        if self.tg:
            try:
                self.tg.set_commands(bot.COMMANDS)          # the "/" menu with descriptions
            except Exception as e:
                log.warning("setMyCommands failed: %s", e)
            threads.append(threading.Thread(target=self.poll_loop, name="tg", daemon=True))
        else:
            log.warning("Telegram غير مفعّل: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID غير مضبوطين — الرسائل تُحفظ فقط")
        if not self.cfg.track_base_url:
            log.warning("TRACK_BASE_URL غير مضبوط: سيُرسل رابط المنتج مباشرة مع زر «أوقف التذكير» داخل Telegram")
        for t in threads:
            t.start()
        log.info("started: web %s:%s, products=%s", self.cfg.web_host, self.cfg.web_port, list(PRODUCTS))
        try:
            while not self.stop.wait(1):
                pass
        except KeyboardInterrupt:
            self.stop.set()


def acquire_lock(db_path: str):
    """Single-instance guard: a second copy exits instead of double-sending."""
    path = os.path.abspath(db_path) + ".lock"
    f = open(path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("نسخة أخرى من الخدمة تعمل بالفعل على نفس قاعدة البيانات — إيقاف.")
    return f


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="aipro")
    ap.add_argument("cmd", choices=["run", "check", "test-telegram", "chat-id"])
    a = ap.parse_args(argv)
    cfg = config.load()
    logsetup.setup(cfg.log_level)
    os.makedirs(os.path.dirname(os.path.abspath(cfg.db_path)), exist_ok=True)
    if a.cmd == "chat-id":     # prints chat ids of people who messaged the bot (to fill TELEGRAM_CHAT_ID)
        tg = Telegram(cfg.token, "")
        seen = {}
        for u in tg.updates(None, wait=0):
            m = u.get("message") or {}
            if m.get("chat"):
                seen[m["chat"]["id"]] = m["chat"].get("first_name") or m["chat"].get("title") or "?"
        print(seen or "لا توجد رسائل — أرسل /start للبوت أولًا ثم أعد التشغيل")
        return
    lock = acquire_lock(cfg.db_path)  # noqa: F841 (kept open for process lifetime)
    app = App(cfg)
    if a.cmd == "check":
        for pid in PRODUCTS:
            try:
                app.check_once(pid)
            except FetchError as e:
                print(f"{pid}: ✗ {e.kind}: {e}")
        print(app.engine.prices_text(int(time.time())))
    elif a.cmd == "test-telegram":
        if not app.tg:
            sys.exit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID غير مضبوطين")
        print("bot:", "@" + app.tg.get_me().get("username", "?"))
        app.tg.send("✅ اختبار الاتصال: نظام مراقبة أسعار Google AI Pro متصل.")
        print("تم إرسال الرسالة التجريبية")
    else:
        app.refresh_fx()
        app.run()


if __name__ == "__main__":
    main()
