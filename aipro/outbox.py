"""Durable, de-duplicated message queue: a dedupe_key can be queued (and sent) only once."""
import json
import logging
import time

from .db import DB

log = logging.getLogger("aipro.outbox")
MAX_ATTEMPTS = 30


class Outbox:
    def __init__(self, db: DB):
        self.db = db

    def enqueue(self, key: str, kind: str, text: str, buttons=None, now: int | None = None) -> bool:
        cur = self.db.x(
            "INSERT OR IGNORE INTO messages(dedupe_key,kind,text,buttons,created_ts) VALUES(?,?,?,?,?)",
            (key, kind, text, json.dumps(buttons) if buttons else None, now or int(time.time())))
        return cur.rowcount == 1

    def flush(self, send) -> int:
        """send(text, buttons) -> None, raises on failure. Returns number sent."""
        sent = 0
        rows = self.db.q("SELECT * FROM messages WHERE status IN ('pending','failed') "
                         "AND attempts<? ORDER BY id", (MAX_ATTEMPTS,))
        for m in rows:
            # claim first so a second instance/thread cannot send the same row
            claimed = self.db.x("UPDATE messages SET status='sending',attempts=attempts+1 "
                                "WHERE id=? AND status IN ('pending','failed')", (m["id"],))
            if claimed.rowcount != 1:
                continue
            try:
                send(m["text"], json.loads(m["buttons"]) if m["buttons"] else None)
            except Exception as e:
                status = "dead" if getattr(e, "permanent", False) else "failed"
                self.db.x("UPDATE messages SET status=?,last_error=? WHERE id=?", (status, str(e)[:200], m["id"]))
                log.warning("send failed (%s): %s", m["dedupe_key"], e)
                break  # preserve order; retry on next flush
            self.db.x("UPDATE messages SET status='sent',sent_ts=? WHERE id=?", (int(time.time()), m["id"]))
            sent += 1
        return sent

    def recover_stuck(self) -> None:
        """On startup: rows left in 'sending' by a crash are retried once."""
        self.db.x("UPDATE messages SET status='failed' WHERE status='sending'")
