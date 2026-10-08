"""Transactional JSON records, revision checks and bounded report retention."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(UTC)


def stamp():
    return now().isoformat()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


class Store:
    def __init__(self, path=None):
        self.path = Path(
            path
            or os.getenv("RW_COORDINATOR_DB")
            or "data/coordinator/workbench.sqlite"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, case_id TEXT NOT NULL, at TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reports(kind TEXT PRIMARY KEY, data TEXT NOT NULL, expires TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY, name TEXT NOT NULL, caption TEXT NOT NULL, data BLOB NOT NULL, mime TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS buffers(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, text TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def setting(self, key, default=None):
        with self.connect() as db:
            r = db.execute("SELECT data FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value))
            )

    def get(self, cid):
        with self.connect() as db:
            row = db.execute("SELECT data FROM cases WHERE id=?", (cid,)).fetchone()
        if not row:
            raise ValueError("Inquiry no longer exists. Return to the queue.")
        return json.loads(row[0])

    def cases(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM cases")]

    def create(self, case, actor):
        with self.connect() as db:
            db.execute(
                "INSERT INTO cases VALUES (?,?,?)",
                (case["id"], case["revision"], json.dumps(case)),
            )
            self._event(
                db, case["id"], actor, "Inquiry received", {"source": case["source"]}
            )
        return case

    def _event(self, db, cid, actor, kind, data):
        db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?)",
            (uuid4().hex, cid, stamp(), actor, kind, json.dumps(data, default=str)),
        )

    def mutate(self, cid, revision, actor, kind, fn):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            shift = db.execute("SELECT data FROM settings WHERE key='shift'").fetchone()
            if (
                not shift
                or json.loads(shift[0]).get("operator") != actor
                or json.loads(shift[0]).get("ended")
            ):
                raise ValueError(
                    "The active shift changed. Refresh and identify the current operator."
                )
            row = db.execute("SELECT data FROM cases WHERE id=?", (cid,)).fetchone()
            if not row:
                raise ValueError("Inquiry no longer exists.")
            c = json.loads(row[0])
            if c["revision"] != revision:
                raise ValueError(
                    "This inquiry changed in another tab. Refresh and review before saving."
                )
            before = json.loads(row[0])
            fn(c, db)
            c["revision"] += 1
            c["updated_at"] = stamp()
            db.execute(
                "UPDATE cases SET revision=?, data=? WHERE id=?",
                (c["revision"], json.dumps(c), cid),
            )
            changes = {
                k: {"before": before.get(k), "after": c.get(k)}
                for k in before.keys() | c.keys()
                if k not in ("revision", "updated_at") and before.get(k) != c.get(k)
            }
            self._event(
                db, cid, actor, kind, {"revision": c["revision"], "changes": changes}
            )
        return c

    def events(self, cid):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT at,actor,kind,data FROM events WHERE case_id=? ORDER BY at",
                    (cid,),
                )
            ]

    def save_report(self, value):
        ids = {r.get("restaurant_id") for r in value["rows"] if r.get("restaurant_id")}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pin = db.execute(
                "SELECT data FROM settings WHERE key='restaurant_id'"
            ).fetchone()
            if ids and pin and ids != {json.loads(pin[0])}:
                raise ValueError(
                    "Restaurant ID differs from this workspace. Use a separate database for another restaurant."
                )
            if ids:
                db.execute(
                    "INSERT OR REPLACE INTO settings VALUES (?,?)",
                    ("restaurant_id", json.dumps(next(iter(ids)))),
                )
            db.execute(
                "INSERT OR REPLACE INTO reports VALUES (?,?,?)",
                (
                    value["kind"],
                    json.dumps(value, default=str),
                    (now() + timedelta(hours=24)).isoformat(),
                ),
            )

    def reports(self):
        with self.connect() as db:
            db.execute("DELETE FROM reports WHERE expires<=?", (stamp(),))
            return {
                r["kind"]: json.loads(r["data"])
                for r in db.execute("SELECT * FROM reports")
            }

    def clear_reports(self):
        with self.connect() as db:
            db.execute("DELETE FROM reports")

    def buffer(self, key, revision=None, text=None):
        with self.connect() as db:
            if revision is not None:
                db.execute(
                    "INSERT OR REPLACE INTO buffers VALUES (?,?,?)",
                    (key, revision, text),
                )
            row = db.execute(
                "SELECT revision,text FROM buffers WHERE id=?", (key,)
            ).fetchone()
            return dict(row) if row else None

    def add_photo(self, name, caption, data):
        from io import BytesIO

        from PIL import Image

        if not caption.strip() or len(data) > 3_000_000:
            raise ValueError(
                "Add an approved caption and an image no larger than 3 MB."
            )
        try:
            with Image.open(BytesIO(data)) as image:
                if (
                    image.format not in ("PNG", "JPEG")
                    or image.width * image.height > 20_000_000
                ):
                    raise ValueError("Use PNG or JPEG, at most 20 megapixels.")
                mime = Image.MIME[image.format]
                image.verify()
        except Exception as exc:
            raise ValueError("Choose a valid PNG or JPEG image.") from exc
        pid = hashlib.sha256(data).hexdigest()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO photos VALUES (?,?,?,?,?)",
                (pid, Path(name).name, caption.strip(), data, mime),
            )
        return pid

    def photos(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,name,caption FROM photos")]

    def photo(self, pid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
            return dict(row) if row else None

    def delete_closed(self, cid, revision):
        """Explicit local retention action; does not affect any external booking."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM cases WHERE id=?", (cid,)).fetchone()
            if not row:
                raise ValueError("Inquiry no longer exists.")
            c = json.loads(row[0])
            if not c.get("closed_reason") or c["revision"] != revision:
                raise ValueError(
                    "Only a closed, unchanged inquiry can be removed. Refresh first."
                )
            db.execute("DELETE FROM events WHERE case_id=?", (cid,))
            db.execute("DELETE FROM buffers WHERE id LIKE ?", (cid + ":%",))
            db.execute("DELETE FROM cases WHERE id=?", (cid,))
