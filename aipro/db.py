import sqlite3
import threading
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks(
  id INTEGER PRIMARY KEY, product_id TEXT NOT NULL, ts INTEGER NOT NULL, ok INTEGER NOT NULL,
  price TEXT, currency TEXT, error_kind TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS ix_checks ON checks(product_id, ts);
CREATE TABLE IF NOT EXISTS product_state(
  product_id TEXT PRIMARY KEY, price TEXT, currency TEXT, price_since INTEGER, last_ok_ts INTEGER,
  pending_price TEXT, pending_count INTEGER NOT NULL DEFAULT 0,
  consecutive_failures INTEGER NOT NULL DEFAULT 0, last_error TEXT, last_error_ts INTEGER,
  outage_id INTEGER, status TEXT NOT NULL DEFAULT 'unknown');
CREATE TABLE IF NOT EXISTS price_changes(
  id INTEGER PRIMARY KEY, product_id TEXT NOT NULL, ts INTEGER NOT NULL,
  old_price TEXT NOT NULL, new_price TEXT NOT NULL, currency TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fx(
  id INTEGER PRIMARY KEY CHECK (id=1), rate TEXT NOT NULL, source TEXT NOT NULL,
  source_ts INTEGER, fetched_ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS alert_cycles(
  id INTEGER PRIMARY KEY, product_id TEXT NOT NULL, started_ts INTEGER NOT NULL, start_price TEXT NOT NULL,
  start_egp TEXT NOT NULL, ended_ts INTEGER, clicked_ts INTEGER, last_reminder_ts INTEGER,
  reminders_sent INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_cycles ON alert_cycles(product_id, ended_ts);
CREATE TABLE IF NOT EXISTS clicks(
  id INTEGER PRIMARY KEY, product_id TEXT NOT NULL, cycle_id INTEGER, ts INTEGER NOT NULL, stopped INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY, dedupe_key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, text TEXT NOT NULL,
  buttons TEXT, created_ts INTEGER NOT NULL, sent_ts INTEGER, status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT);
CREATE TABLE IF NOT EXISTS errors(id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, source TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
"""


class DB:
    """One shared SQLite connection guarded by an RLock (WAL mode, durable)."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            if path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(SCHEMA)

    def q(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def x(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args)

    @contextmanager
    def tx(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def get(self, k, default=None):
        r = self.one("SELECT v FROM kv WHERE k=?", (k,))
        return r["v"] if r else default

    def set(self, k, v):
        self.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

    def log_error(self, ts, source, message):
        self.x("INSERT INTO errors(ts,source,message) VALUES(?,?,?)", (ts, source, str(message)[:500]))
