import dataclasses
from decimal import Decimal

from aipro import fx as fxmod
from aipro.db import DB
from aipro.engine import Engine
from aipro.fetchers import FetchError
from aipro.outbox import Outbox
from conftest import T0, feed, make_products, msgs

M = 60


# --- threshold (tests 1-4) ---
def test_199_triggers_alert(env):
    feed(env, "maads", 199)
    a = msgs(env, "alert")
    assert len(a) == 1 and "199 EGP" in a[0]["text"] and "أقل من 200 جنيه" in a[0]["text"]
    assert "https://trk.test/track/maads?c=" in a[0]["text"]


def test_200_does_not_trigger(env):
    feed(env, "maads", 200)
    assert msgs(env, "alert") == [] and env.open_cycle("maads") is None


def test_201_does_not_trigger(env):
    feed(env, "maads", 201)
    assert msgs(env, "alert") == []


def test_usd_converted_below_threshold_triggers(env):  # rate 50 -> 3.80 USD = 190 EGP
    feed(env, "z2u", "3.80")
    a = msgs(env, "alert")
    assert len(a) == 1 and "3.80 USD" in a[0]["text"] and "190 EGP" in a[0]["text"]


def test_usd_converted_exactly_200_does_not_trigger(env):
    feed(env, "z2u", "4")  # 4 * 50 = 200
    assert msgs(env, "alert") == []


def test_usd_without_fx_is_not_judged(env):
    env.db.x("DELETE FROM fx")
    feed(env, "z2u", "1.00")
    assert msgs(env, "alert") == [] and env.open_cycle("z2u") is None


# --- failures (5, 15) ---
def test_failure_creates_no_price_no_alert_no_change(env):
    feed(env, "maads", 250, now=T0)
    for i in range(1, 5):
        env.record_failure("maads", FetchError("parse", "boom"), T0 + i * 300)
    st = env.state("maads")
    assert st["price"] == "250" and st["status"] == "review" and st["consecutive_failures"] == 4
    assert msgs(env, "alert") == [] and msgs(env, "change") == []
    assert len(msgs(env, "error")) == 1                       # one error notice per outage
    assert "250 EGP" in msgs(env, "error")[0]["text"]          # last known price kept


def test_failure_before_any_price_stores_nothing(env):
    env.record_failure("maads", FetchError("network", "x"), T0)
    assert env.state("maads")["price"] is None
    assert "—" in env.prices_text(T0) and "🔴" in env.prices_text(T0)


def test_wrong_currency_is_rejected_as_review(env):
    from aipro.fetchers import PriceResult
    env.record_success("maads", PriceResult(Decimal("5"), "USD"), T0)
    st = env.state("maads")
    assert st["price"] is None and st["status"] == "review" and msgs(env, "alert") == []


def test_recovery_notice_after_alerted_outage(env):
    feed(env, "maads", 250)
    for i in range(3):
        env.record_failure("maads", FetchError("network", "x"), T0 + i)
    feed(env, "maads", 250, now=T0 + 10)
    assert len(msgs(env, "recovery")) == 1


# --- change reports (6, 7) ---
def test_change_produces_exactly_one_report(env):
    feed(env, "maads", 250)
    feed(env, "maads", 240, now=T0 + 300)
    feed(env, "maads", 240, now=T0 + 600)
    feed(env, "maads", 240, now=T0 + 900)
    ch = msgs(env, "change")
    assert len(ch) == 1
    t = ch[0]["text"]
    assert "250 EGP" in t and "240 EGP" in t and "-10.00 EGP" in t and "-4.00%" in t and "Site" in t


def test_no_change_no_report(env):
    for i in range(4):
        feed(env, "maads", 250, now=T0 + i * 300)
    assert msgs(env, "change") == []


def test_first_reading_is_baseline_not_a_change(env):
    feed(env, "driffle", 250)
    assert msgs(env, "change") == []


def test_return_to_previous_price_is_a_normal_change(env):
    feed(env, "maads", 250)
    feed(env, "maads", 240, now=T0 + 1)
    feed(env, "maads", 250, now=T0 + 2)
    assert len(msgs(env, "change")) == 2
    assert "🔺" in msgs(env, "change")[1]["text"] and "+10.00 EGP" in msgs(env, "change")[1]["text"]


def test_change_needs_confirmation_when_configured(cfg, tmp_path):
    eng = Engine(dataclasses.replace(cfg, confirm_checks=2), DB(str(tmp_path / "c.db")), make_products(),
                 Outbox(DB(str(tmp_path / "c2.db"))))
    eng.outbox = Outbox(eng.db)
    feed(eng, "maads", 250)
    feed(eng, "maads", 240, now=T0 + 1)            # first sighting: not confirmed
    assert msgs(eng, "change") == [] and eng.state("maads")["price"] == "250"
    feed(eng, "maads", 245, now=T0 + 2)            # flapping value resets confirmation
    feed(eng, "maads", 240, now=T0 + 3)
    assert msgs(eng, "change") == []
    feed(eng, "maads", 240, now=T0 + 4)            # confirmed
    assert len(msgs(eng, "change")) == 1 and eng.state("maads")["price"] == "240"


def test_fx_change_alone_is_not_a_product_price_change(env):
    feed(env, "z2u", "7.00")
    fxmod.save(env.db, fxmod.Rate(Decimal("55"), "test-fx", T0 + 10, T0 + 10))
    feed(env, "z2u", "7.00", now=T0 + 20)
    assert msgs(env, "change") == []


def test_z2u_report_shows_usd_and_egp(env):
    feed(env, "z2u", "7.00")
    feed(env, "z2u", "6.00", now=T0 + 1)
    t = msgs(env, "change")[0]["text"]
    assert "7.00 USD" in t and "6.00 USD" in t
    assert "350" in t and "300" in t and "1 USD = 50.00" in t


def test_z2u_report_without_fx_says_unavailable(env):
    env.db.x("DELETE FROM fx")
    feed(env, "z2u", "7.00")
    feed(env, "z2u", "6.00", now=T0 + 1)
    t = msgs(env, "change")[0]["text"]
    assert "6.00 USD" in t and "n/a" in t and "غير متاح" in t


def test_maads_and_driffle_reports_in_egp(env):
    feed(env, "maads", 250)
    feed(env, "driffle", 260)
    feed(env, "maads", 240, now=T0 + 1)
    feed(env, "driffle", 270, now=T0 + 1)
    for m in msgs(env, "change"):
        assert "EGP" in m["text"] and "USD" not in m["text"].split("Site")[0]


# --- cycles, reminders, clicks (8-12) ---
def test_reminders_every_interval_until_click(env):
    feed(env, "maads", 199)
    feed(env, "maads", 199, now=T0 + 9 * M)
    assert env.due_reminders(T0 + 9 * M) == 0
    feed(env, "maads", 199, now=T0 + 10 * M)
    assert env.due_reminders(T0 + 10 * M) == 1
    feed(env, "maads", 199, now=T0 + 20 * M)
    assert env.due_reminders(T0 + 20 * M) == 1
    assert len(msgs(env, "reminder")) == 2


def test_click_stops_only_this_product(env):
    feed(env, "maads", 199)
    feed(env, "driffle", 150)
    cid = env.open_cycle("maads")["id"]
    assert env.register_click("maads", cid, T0 + 60) is True
    for pid in ("maads", "driffle"):
        feed(env, pid, 199 if pid == "maads" else 150, now=T0 + 10 * M)
    assert env.due_reminders(T0 + 10 * M) == 1
    r = msgs(env, "reminder")
    assert len(r) == 1 and "Driffle" in r[0]["text"]
    assert env.open_cycle("maads")["clicked_ts"] == T0 + 60
    assert env.db.one("SELECT COUNT(*) c FROM clicks WHERE product_id='maads'")["c"] == 1


def test_click_does_not_stop_change_reports_or_monitoring(env):
    feed(env, "maads", 199)
    env.register_click("maads", env.open_cycle("maads")["id"], T0 + 1)
    feed(env, "maads", 190, now=T0 + 300)
    assert len(msgs(env, "change")) == 1
    assert env.state("maads")["price"] == "190"


def test_rise_to_200_ends_cycle_and_stops_reminders(env):
    feed(env, "maads", 199)
    feed(env, "maads", 200, now=T0 + 300)
    assert env.open_cycle("maads") is None
    assert env.db.one("SELECT ended_ts FROM alert_cycles")["ended_ts"] == T0 + 300
    assert env.due_reminders(T0 + 30 * M) == 0


def test_dropping_again_starts_new_cycle_ignoring_old_click(env):
    feed(env, "maads", 199)
    c1 = env.open_cycle("maads")["id"]
    env.register_click("maads", c1, T0 + 1)
    feed(env, "maads", 205, now=T0 + 300)
    feed(env, "maads", 190, now=T0 + 600)
    c2 = env.open_cycle("maads")
    assert c2["id"] != c1 and c2["clicked_ts"] is None
    assert len(msgs(env, "alert")) == 2
    feed(env, "maads", 190, now=T0 + 600 + 10 * M)
    assert env.due_reminders(T0 + 600 + 10 * M) == 1


def test_stale_click_on_old_cycle_does_not_stop_new_cycle(env):
    feed(env, "maads", 199)
    c1 = env.open_cycle("maads")["id"]
    feed(env, "maads", 210, now=T0 + 300)
    feed(env, "maads", 190, now=T0 + 600)
    assert env.register_click("maads", c1, T0 + 700) is False
    assert env.open_cycle("maads")["clicked_ts"] is None


def test_staying_below_does_not_create_new_cycles(env):
    for i in range(5):
        feed(env, "maads", 199, now=T0 + i * 300)
    assert env.db.one("SELECT COUNT(*) c FROM alert_cycles")["c"] == 1
    assert len(msgs(env, "alert")) == 1


def test_failure_does_not_end_cycle_and_stale_price_stops_reminders(env):
    feed(env, "maads", 199)
    env.record_failure("maads", FetchError("network", "x"), T0 + 300)
    assert env.open_cycle("maads") is not None
    assert env.due_reminders(T0 + 40 * M) == 0     # last good price older than MAX_STALE


# --- pause / resume ---
def test_pause_keeps_data_and_resume_requires_fresh_check(env):
    feed(env, "maads", 199)
    env.set_paused(True, T0 + 100)
    assert env.due_reminders(T0 + 20 * M) == 0
    assert env.state("maads")["price"] == "199" and env.open_cycle("maads")
    env.set_paused(False, T0 + 25 * M)
    assert env.due_reminders(T0 + 25 * M) == 0     # no fresh check yet
    feed(env, "maads", 199, now=T0 + 26 * M)
    assert env.due_reminders(T0 + 26 * M) == 1


# --- restart / duplicates (13) ---
def test_restart_does_not_repeat_old_messages(cfg, tmp_path):
    path = str(tmp_path / "r.db")
    e1 = Engine(cfg, DB(path), make_products(), None)
    e1.outbox = Outbox(e1.db)
    fxmod.save(e1.db, fxmod.Rate(Decimal("50"), "t", T0, T0))
    feed(e1, "maads", 250)
    feed(e1, "maads", 199, now=T0 + 300)
    sent = []
    e1.outbox.flush(lambda t, b: sent.append(t))
    n = len(sent)
    assert n == 2                                   # change report + alert

    db2 = DB(path)                                  # "restart"
    e2 = Engine(cfg, db2, make_products(), Outbox(db2))
    e2.outbox.recover_stuck()
    feed(e2, "maads", 199, now=T0 + 600)            # same price re-read after restart
    e2.send_daily_if_due(T0)  # (no-op: before daily time in Cairo? just ensure no crash)
    e2.outbox.flush(lambda t, b: sent.append(t))
    assert len([s for s in sent if "فرصة سعرية" in s]) == 1
    assert len([s for s in sent if "تغيّر سعر" in s]) == 1


def test_enqueue_same_key_twice_is_one_message(env):
    assert env.outbox.enqueue("k", "x", "a") is True
    assert env.outbox.enqueue("k", "x", "a") is False


def test_outbox_failed_send_is_retried_then_sent_once(env):
    env.outbox.enqueue("k", "x", "hello")
    calls = []

    def flaky(t, b):
        calls.append(t)
        if len(calls) == 1:
            raise RuntimeError("net")
    env.outbox.flush(flaky)
    env.outbox.flush(flaky)
    env.outbox.flush(flaky)
    assert len(calls) == 2 and msgs(env)[0]["status"] == "sent"


# --- daily (14) ---
def test_daily_report_sent_without_changes_once_per_day(env):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Africa/Cairo")
    t = int(datetime(2026, 3, 3, 21, 5, tzinfo=tz).timestamp())
    feed(env, "maads", 250, now=t - 3600)
    feed(env, "maads", 250, now=t - 1800)
    feed(env, "z2u", "7.00", now=t - 1800)
    env.record_failure("driffle", FetchError("blocked", "403"), t - 900)
    assert env.send_daily_if_due(t - 3600 * 3) is False          # too early
    assert env.send_daily_if_due(t) is True
    assert env.send_daily_if_due(t + 60) is False                # no duplicate same day
    txt = msgs(env, "daily")[0]["text"]
    assert "التقرير اليومي" in txt and "2026-03-03" in txt
    assert "250 EGP" in txt and "Min" in txt and "7.00 USD" in txt and "350" in txt
    assert "Driffle" in txt and "—" in txt and "Fail" in txt
    assert "لا توجد بيانات كافية اليوم" in txt                    # driffle: explicit lack of data
    assert "التنبيهات النشطة: لا يوجد" in txt
    assert env.send_daily_if_due(t + 24 * 3600) is True          # next day


def test_status_text_lists_alerts_errors_and_state(env):
    feed(env, "maads", 199)
    env.record_failure("driffle", FetchError("blocked", "HTTP 403"), T0 + 5)
    t = env.status_text(T0 + 10)
    assert "تعمل" in t and "MAADS" in t and "199 EGP" in t and "تذكيرات نشطة: MAADS" in t and "🟢" in t
    assert "HTTP 403" in t
    env.set_paused(True, T0 + 11)
    assert "متوقفة" in env.status_text(T0 + 12)


def test_default_reminder_is_hourly():
    from aipro.config import Settings
    assert Settings().reminder_interval == 3600


def test_each_reminder_is_followed_by_a_prices_table(env):
    feed(env, "maads", 199)
    feed(env, "maads", 199, now=T0 + 10 * M)
    assert env.due_reminders(T0 + 10 * M) == 1
    rows = msgs(env)
    kinds = [r["kind"] for r in rows]
    assert kinds[-2:] == ["reminder", "reminder-table"]
    assert "Site" in rows[-1]["text"] and "MAADS" in rows[-1]["text"] and "199 EGP" in rows[-1]["text"]
    assert env.due_reminders(T0 + 10 * M) == 0 and len(msgs(env, "reminder-table")) == 1


def _fill(env, pid, hours_prices, days=3):
    """Insert fake readings: price depends on hour of day (Cairo)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Africa/Cairo")
    for d in range(1, days + 1):
        for h, price in hours_prices.items():
            for k in range(3):
                t = int(datetime(2026, 3, d, h, k * 10, tzinfo=tz).timestamp())
                env.db.x("INSERT INTO checks(product_id,ts,ok,price,currency) VALUES(?,?,1,?,?)",
                         (pid, t, str(price), env.products[pid].currency))


def test_best_time_report_finds_cheapest_and_dearest_hour(env):
    _fill(env, "maads", {3: 190, 9: 220, 15: 240})
    t = env.best_times_text(T0)
    assert "03:00 190.00" in t and "15:00 240.00" in t and "21%" in t      # (240-190)/240
    assert "Z2U: بيانات غير كافية" in t and "Driffle: بيانات غير كافية" in t   # no invented numbers


def test_best_time_needs_enough_data(env):
    feed(env, "maads", 200)
    assert "بيانات غير كافية" in env.best_times_text(T0)
