import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("aipro.web")


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        server_version = "aipro"

        def log_message(self, *a):   # no access logs (they would contain query strings)
            pass

        def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/health":
                body = json.dumps({"ok": True, "paused": engine.paused}).encode()
                return self._send(200, body, "application/json")
            parts = u.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "track" and parts[1] in engine.products:
                pid = parts[1]
                ua = (self.headers.get("User-Agent") or "").lower()
                is_bot = self.command == "HEAD" or any(w in ua for w in ("bot", "crawler", "spider", "preview", "curl"))
                try:
                    if is_bot:       # link-preview crawlers must not count as a user click
                        return self._send(302, headers={"Location": engine.products[pid].url})
                    c = parse_qs(u.query).get("c", [""])[0]
                    engine.register_click(pid, int(c) if c.isdigit() else None, int(time.time()))
                except Exception:
                    log.exception("click registration failed")   # never block the redirect
                # Redirect only to the configured product URL (no open redirect).
                return self._send(302, headers={"Location": engine.products[pid].url})
            self._send(404, b"not found")

        do_HEAD = do_GET
    return Handler


def serve(engine, host: str, port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), make_handler(engine))
    srv.daemon_threads = True
    return srv
