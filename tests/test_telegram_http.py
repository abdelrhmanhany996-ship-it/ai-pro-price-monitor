"""Exercises the real HTTP code path against a local fake Telegram API (no real token/network)."""
import dataclasses
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import aipro.app as appmod
from aipro.telegram import Telegram
from conftest import T0, feed

CALLS, UPDATES = [], []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = self.path.rsplit("/", 1)[1]
        CALLS.append((method, body))
        result = UPDATES.copy() if method == "getUpdates" else {"message_id": 1}
        if method == "getUpdates":
            UPDATES.clear()
        out = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)


def test_alert_delivery_and_command_roundtrip(cfg, tmp_path):
    CALLS.clear()
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = dataclasses.replace(cfg, db_path=str(tmp_path / "h.db"))
    a = appmod.App(cfg)
    a.tg = Telegram("123:fake", "42", base=f"http://127.0.0.1:{srv.server_address[1]}")
    try:
        feed(a.engine, "maads", 199)                       # fake price -> alert queued
        a.flush(); a.flush()                                # second flush must not resend
        sends = [b for m, b in CALLS if m == "sendMessage"]
        assert len(sends) == 1 and sends[0]["chat_id"] == "42" and sends[0]["parse_mode"] == "HTML"
        url = sends[0]["reply_markup"]["inline_keyboard"][0][0]["url"]
        assert url.startswith("https://trk.test/track/maads?c=")
        UPDATES.append({"update_id": 5, "message": {"chat": {"id": 42}, "text": "/prices"}})
        for u in a.tg.updates(None, wait=0):
            a.handle_update(u)
        replies = [b for m, b in CALLS if m == "sendMessage"]
        assert len(replies) == 2 and "199 EGP" in replies[1]["text"]
    finally:
        srv.shutdown()
