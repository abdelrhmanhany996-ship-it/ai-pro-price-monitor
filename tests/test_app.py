import dataclasses
import json
import threading
import time
import urllib.request
from decimal import Decimal

import pytest

import aipro.app as appmod
from aipro import bot, logsetup, web
from aipro.fetchers import FetchError, PriceResult
from aipro.products import Product
from conftest import T0, feed, make_products, msgs


def test_one_site_down_does_not_stop_the_others(cfg, tmp_path):
    cfg = dataclasses.replace(cfg, db_path=str(tmp_path / "a.db"), check_interval=0.05, track_base_url="")

    def down():
        raise FetchError("network", "timeout")
    prods = {
        "maads": Product("maads", "MAADS", "u1", "EGP", lambda: PriceResult(Decimal("250"), "EGP")),
        "z2u": Product("z2u", "Z2U", "u2", "USD", down),
        "driffle": Product("driffle", "Driffle", "u3", "EGP", lambda: PriceResult(Decimal("260"), "EGP")),
    }
    old = appmod.PRODUCTS.copy()
    appmod.PRODUCTS.clear(); appmod.PRODUCTS.update(prods)
    try:
        a = appmod.App(cfg)
        a.engine.products = prods
        ts = [threading.Thread(target=a.product_loop, args=(p,), daemon=True) for p in prods]
        [t.start() for t in ts]
        time.sleep(1.5)
        a.stop.set(); a.kick_all()
        for p, n in (("maads", 3), ("driffle", 3)):
            assert a.db.one("SELECT COUNT(*) c FROM checks WHERE product_id=? AND ok=1", (p,))["c"] >= 3
        assert a.db.one("SELECT COUNT(*) c FROM checks WHERE product_id='z2u' AND ok=0")["c"] >= 3
        assert a.engine.state("z2u")["price"] is None       # no fake price for the failing site
        assert a.engine.state("maads")["price"] == "250"
    finally:
        appmod.PRODUCTS.clear(); appmod.PRODUCTS.update(old)


def test_commands(env):
    now = T0
    feed(env, "maads", 250)
    assert "/status" in bot.handle_command(env, "/help", now)
    assert "250 EGP" in bot.handle_command(env, "/prices@mybot", now)
    assert "250 EGP" in bot.handle_command(env, "/status", now)
    resumed = []
    assert "إيقاف" in bot.handle_command(env, "/pause", now) and env.paused
    assert env.state("maads")["price"] == "250"                    # pause keeps data
    assert "الاستئناف" in bot.handle_command(env, "/resume", now, on_resume=lambda: resumed.append(1))
    assert not env.paused and resumed
    assert "غير معروف" in bot.handle_command(env, "/nope", now)
    assert "أهلًا" in bot.handle_command(env, "/start", now)


def test_only_configured_chat_is_authorized():
    assert bot.is_authorized(42, "42") and bot.is_authorized("42", "42")
    assert not bot.is_authorized(7, "42") and not bot.is_authorized(42, "")


def test_unauthorized_update_gets_no_reply_and_no_state_change(cfg, tmp_path):
    cfg = dataclasses.replace(cfg, db_path=str(tmp_path / "u.db"))
    a = appmod.App(cfg)
    sent = []
    a.tg.send = lambda text, buttons=None, chat_id=None: sent.append(text)
    a.handle_update({"update_id": 1, "message": {"chat": {"id": 999}, "text": "/pause"}})
    assert sent == [] and not a.engine.paused
    a.handle_update({"update_id": 2, "message": {"chat": {"id": 42}, "text": "/pause"}})
    assert a.engine.paused and len(sent) == 1


def test_tracking_endpoint_redirects_and_stops_only_that_product(env):
    feed(env, "maads", 199); feed(env, "driffle", 150)
    cid = env.open_cycle("maads")["id"]
    srv = web.serve(env, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    op = urllib.request.build_opener(NoRedirect)

    def get(path, ua="Mozilla/5.0"):
        try:
            return op.open(urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"User-Agent": ua}))
        except urllib.error.HTTPError as e:
            return e
    try:
        r = get(f"/track/maads?c={cid}", ua="TelegramBot (like TwitterBot)")      # preview crawler
        assert r.code == 302 and env.open_cycle("maads")["clicked_ts"] is None
        r = get(f"/track/maads?c={cid}")
        assert r.code == 302 and r.headers["Location"] == "https://example.test/maads"
        assert env.open_cycle("maads")["clicked_ts"] is not None
        assert env.open_cycle("driffle")["clicked_ts"] is None
        assert get("/track/unknown").code == 404
        assert json.load(get("/health"))["ok"] is True
    finally:
        srv.shutdown()


def test_token_never_logged(monkeypatch):
    tok = "123456789:AAExampleExampleExampleExampleExample12"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", tok)
    import logging
    r = logging.LogRecord("x", 20, "", 0, f"POST https://api.telegram.org/bot{tok}/sendMessage failed", (), None)
    logsetup.RedactFilter().filter(r)
    assert tok not in r.msg and "AAExample" not in r.msg


def test_telegram_error_does_not_leak_token(monkeypatch):
    from aipro.telegram import Telegram, TelegramError
    tok = "123456789:AAExampleExampleExampleExampleExample12"

    def boom(*a, **k):
        raise urllib.error.URLError(f"https://api.telegram.org/bot{tok}/x")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(TelegramError) as e:
        Telegram(tok, "1").send("hi")
    assert tok not in str(e.value)
