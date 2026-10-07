"""SQLite connection, schema and transactions.

The schema is created idempotently by ``Database.open``. ``SCHEMA_VERSION`` is
stored in ``meta``; a mismatching version raises instead of silently migrating
(the demo can be reset, and ordinary sessions are expected to be re-created
for a new major version - see docs/OPERATOR_GUIDE.md).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = "3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (
  name TEXT PRIMARY KEY,
  next INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS inquiries (
  id TEXT PRIMARY KEY,
  guest_label TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL,
  booking_id TEXT,
  record_version INTEGER NOT NULL DEFAULT 1,
  handled_seq INTEGER NOT NULL DEFAULT 0,
  handled_obs_seq INTEGER NOT NULL DEFAULT 0,
  state_set_seq INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  inquiry_id TEXT NOT NULL REFERENCES inquiries(id),
  seq INTEGER NOT NULL,
  direction TEXT NOT NULL,
  text TEXT NOT NULL,
  received_at TEXT NOT NULL,
  source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_inquiry ON messages(inquiry_id, seq);
CREATE TABLE IF NOT EXISTS interpretations (
  id TEXT PRIMARY KEY,
  inquiry_id TEXT NOT NULL REFERENCES inquiries(id),
  message_ids TEXT NOT NULL,
  provider_mode TEXT NOT NULL,
  model TEXT,
  status TEXT NOT NULL,
  intents TEXT NOT NULL,
  ambiguities TEXT NOT NULL,
  uninterpreted TEXT NOT NULL,
  error TEXT,
  raw_output TEXT,
  latency_ms INTEGER,
  usage TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
  id TEXT PRIMARY KEY,
  inquiry_id TEXT NOT NULL REFERENCES inquiries(id),
  seq INTEGER NOT NULL,
  field TEXT NOT NULL,
  value TEXT NOT NULL,
  source_type TEXT NOT NULL,
  message_id TEXT,
  span_start INTEGER,
  span_end INTEGER,
  quote TEXT,
  status TEXT NOT NULL,
  note TEXT,
  provider_mode TEXT,
  interpretation_id TEXT,
  observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obs_inquiry ON observations(inquiry_id, field, seq);
CREATE TABLE IF NOT EXISTS bookings (
  id TEXT PRIMARY KEY,
  inquiry_id TEXT,
  guest_label TEXT NOT NULL,
  status TEXT NOT NULL,
  party_size INTEGER NOT NULL,
  start_utc TEXT NOT NULL,
  end_utc TEXT NOT NULL,
  hold_expires_at TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS booking_tables (
  booking_id TEXT NOT NULL REFERENCES bookings(id),
  table_id TEXT NOT NULL,
  PRIMARY KEY (booking_id, table_id)
);
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY,
  inquiry_id TEXT NOT NULL REFERENCES inquiries(id),
  kind TEXT NOT NULL,
  source_record_version INTEGER NOT NULL,
  policy_version TEXT NOT NULL,
  booking_id TEXT,
  booking_version INTEGER,
  option TEXT NOT NULL,
  party_size INTEGER NOT NULL,
  rule_results TEXT NOT NULL,
  required_decisions TEXT NOT NULL,
  status TEXT NOT NULL,
  approved_at TEXT,
  approval_reason TEXT,
  created_at TEXT NOT NULL,
  status_reason TEXT
);
CREATE TABLE IF NOT EXISTS drafts (
  id TEXT PRIMARY KEY,
  inquiry_id TEXT NOT NULL REFERENCES inquiries(id),
  purpose TEXT NOT NULL,
  text TEXT NOT NULL,
  generated_text TEXT NOT NULL,
  source_record_version INTEGER NOT NULL,
  facts_hash TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  proposal_id TEXT,
  booking_version INTEGER,
  validation TEXT NOT NULL,
  status TEXT NOT NULL,
  approved_at TEXT,
  approved_record_version INTEGER,
  provider_mode TEXT NOT NULL,
  prose_source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  inquiry_id TEXT,
  booking_id TEXT,
  actor TEXT NOT NULL,
  event_type TEXT NOT NULL,
  before TEXT,
  after TEXT,
  reason TEXT,
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  proposal_id TEXT,
  record_version INTEGER,
  booking_version INTEGER
);
CREATE INDEX IF NOT EXISTS ix_events_inquiry ON events(inquiry_id, seq);
"""


class SchemaMismatch(RuntimeError):
    pass


class Database:
    def __init__(self, conn: sqlite3.Connection, path: str):
        self.conn = conn
        self.path = path

    # ---- lifecycle ----------------------------------------------------
    @classmethod
    def open(cls, path: str | Path) -> "Database":
        p = str(path)
        if p != ":memory:":
            Path(p).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p, isolation_level=None, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if p != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        db = cls(conn, p)
        existing = db.get_meta("schema_version")
        if existing is None:
            db.set_meta("schema_version", SCHEMA_VERSION)
        elif existing != SCHEMA_VERSION:
            raise SchemaMismatch(
                f"database {p} has schema {existing}; this build expects {SCHEMA_VERSION}. "
                "Reset the demo database or start a new session database."
            )
        return db

    def close(self) -> None:
        self.conn.close()

    # ---- transactions -------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE ... COMMIT, rolling back on any exception.

        Nested use joins the outer transaction.
        """
        if self.conn.in_transaction:
            yield self.conn
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # ---- helpers ------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else row["value"]

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def next_id(self, name: str, prefix: str, width: int = 4) -> str:
        with self.transaction() as c:
            row = c.execute("SELECT next FROM counters WHERE name=?", (name,)).fetchone()
            n = 1 if row is None else row["next"]
            c.execute(
                "INSERT INTO counters(name,next) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET next=excluded.next",
                (name, n + 1),
            )
        return f"{prefix}{n:0{width}d}"

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()


def dumps(v: Any) -> str:
    return json.dumps(v, default=str, sort_keys=True)


def loads(s: str | None) -> Any:
    return None if s is None else json.loads(s)
