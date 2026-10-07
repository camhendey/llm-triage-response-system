"""Database locations, demo seeding and the guarded demo reset."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from ..domain.clock import FixedClock, SystemClock
from ..domain.config import RestaurantConfig, load_config
from ..domain.models import (
    Booking,
    BookingStatus,
    Direction,
    FieldName,
    FieldStatus,
    Inquiry,
    InquiryState,
    Message,
    MessageSource,
    Observation,
)
from ..persistence.db import Database
from ..persistence.repo import Repo
from ..providers.factory import make_provider
from ..providers.offline import OfflineRulesProvider
from .workbench import Workbench

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEMO_DIR = PROJECT_ROOT / "data" / "demo"
DEMO_DB_PATH = DEMO_DIR / "workbench_demo.sqlite"
SESSION_DB_PATH = PROJECT_ROOT / "data" / "sessions" / "workbench.sqlite"
DEMO_SEED_PATH = PROJECT_ROOT / "data" / "synthetic" / "demo_inquiries.json"


class ResetRefused(RuntimeError):
    pass


def demo_db_path() -> Path:
    return Path(os.getenv("RW_DEMO_DB", str(DEMO_DB_PATH))).resolve()


def session_db_path() -> Path:
    return Path(os.getenv("RW_SESSION_DB", str(SESSION_DB_PATH))).resolve()


def open_workbench(kind: str = "demo", path: str | Path | None = None, provider=None,
                   cfg: RestaurantConfig | None = None) -> Workbench:
    """Open (and, for an empty demo database, seed) a workbench.

    kind="demo": fixed clock persisted in the database; resettable.
    kind="session": real clock; persistent; never reset by the tool.
    """
    cfg = cfg or load_config()
    p = Path(path) if path else (demo_db_path() if kind == "demo" else session_db_path())
    fresh = not p.exists()
    db = Database.open(p)
    stored_kind = db.get_meta("db_kind")
    if stored_kind is None:
        db.set_meta("db_kind", kind)
        stored_kind = kind
    if stored_kind != kind:
        raise RuntimeError(f"{p} is a {stored_kind} database, not {kind}")
    provider = provider or make_provider()
    if kind == "demo":
        stored = db.get_meta("fixed_clock")
        clock = FixedClock(datetime.fromisoformat(stored) if stored else cfg.demo_clock)
        if not stored:
            db.set_meta("fixed_clock", cfg.demo_clock.isoformat())
        wb = Workbench(db, cfg, clock, provider, mode="demo")
        if fresh or db.get_meta("seeded") is None:
            seed_demo(wb)
    else:
        wb = Workbench(db, cfg, SystemClock(), provider, mode="session")
        if db.get_meta("seeded") is None:
            seed_bookings_only(wb)
    wb.reconcile()
    return wb


def _seed_obs(repo: Repo, inquiry_id: str, values: dict, at: datetime, start_seq: int = 1) -> int:
    seq = start_seq
    for k, v in values.items():
        repo.insert_observation(Observation(
            id=f"OBS-SEED-{inquiry_id}-{seq}", inquiry_id=inquiry_id, seq=seq, field=FieldName(k), value=v,
            source_type="seed", message_id=f"{inquiry_id}-M1", status=FieldStatus.EXTRACTED,
            note="seeded record (synthetic history)", observed_at=at))
        seq += 1
    return seq


def seed_bookings_only(wb: Workbench) -> None:
    """Load fixture bookings (with their synthetic inquiries) into a database."""
    cfg = wb.cfg
    repo = wb.repo
    seed_path = DEMO_SEED_PATH
    extra = json.loads(seed_path.read_text(encoding="utf-8"))["seed_booking_facts"] if seed_path.exists() else {}
    with wb.db.transaction():
        for sb in cfg.bookings:
            iid = f"INQ-{sb.id}"
            at = (sb.start.astimezone(UTC) if False else cfg.demo_clock)
            facts = extra.get(sb.id, {})
            inq = Inquiry(id=iid, guest_label=sb.guest, title=f"Existing booking {sb.id}",
                          state=InquiryState.RESOLVED if sb.status == "confirmed" else InquiryState.NEEDS_REVIEW,
                          booking_id=sb.id, created_at=at, updated_at=at)
            repo.insert_inquiry(inq)
            repo.insert_message(Message(id=f"{iid}-M1", inquiry_id=iid, seq=1, direction=Direction.INBOUND,
                                        text=facts.get("history", f"Seeded history for {sb.id}."),
                                        received_at=cfg.demo_clock.replace(hour=8, minute=0), source=MessageSource.SEED))
            local = sb.start.astimezone(cfg.tz)
            values = {"party_size": sb.party_size, "requested_date": local.date().isoformat(),
                      "requested_time": local.strftime("%H:%M")}
            values.update({k: v for k, v in facts.items() if k != "history"})
            last = _seed_obs(repo, iid, values, at) - 1
            repo.update_inquiry(inq.model_copy(update={"handled_seq": 1, "handled_obs_seq": last, "state_set_seq": 1}))
            repo.insert_booking(Booking(
                id=sb.id, inquiry_id=iid, guest_label=sb.guest, status=BookingStatus(sb.status),
                table_ids=sb.table_ids, party_size=sb.party_size, start=sb.start.astimezone(UTC),
                end=sb.end.astimezone(UTC), hold_expires_at=sb.expires_at.astimezone(UTC) if sb.expires_at else None,
                source="seed", created_at=at, updated_at=at))
            wb._event(f"seed:{sb.id}", "seed_booking_loaded", iid, actor="system", booking_id=sb.id,
                      after={"status": sb.status, "tables": sb.table_ids})
        wb.db.set_meta("seeded", "bookings")


def seed_demo(wb: Workbench, interpret: bool = True) -> None:
    seed_bookings_only(wb)
    data = json.loads(DEMO_SEED_PATH.read_text(encoding="utf-8"))
    original = wb.provider
    wb.provider = OfflineRulesProvider()  # demo seed is always interpreted offline and labelled as such
    try:
        for item in data["inquiries"]:
            first, *rest = item["messages"]
            wb.create_inquiry(item["guest_label"], first["text"], datetime.fromisoformat(first["received_at"]),
                              key=f"seed:create:{item['id']}", source=MessageSource.SEED, title=item.get("title", ""),
                              inquiry_id=item["id"])
            for i, m in enumerate(rest):
                wb.add_message(item["id"], m["text"], datetime.fromisoformat(m["received_at"]),
                               key=f"seed:msg:{item['id']}:{i}", source=MessageSource.SEED)
            if interpret:
                wb.interpret(item["id"], key=f"seed:interpret:{item['id']}")
        for i, f in enumerate(data.get("followups", [])):
            wb.add_message(f["inquiry_id"], f["text"], datetime.fromisoformat(f["received_at"]),
                           key=f"seed:followup:{i}", source=MessageSource.SEED)
            if interpret:
                wb.interpret(f["inquiry_id"], key=f"seed:interpret:followup:{i}")
    finally:
        wb.provider = original
    wb.db.set_meta("seeded", "demo")


def reset_demo(path: str | Path | None = None) -> Path:
    """Delete and re-seed the designated demo database only.

    Refuses any path other than the configured demo path, and any existing
    database whose stored kind is not "demo".
    """
    target = Path(path).resolve() if path else demo_db_path()
    designated = demo_db_path()
    if target != designated:
        raise ResetRefused(f"Refusing to reset {target}: only the designated demo database ({designated}) can be reset.")
    if target.exists():
        db = Database.open(target)
        kind = db.get_meta("db_kind")
        db.close()
        if kind != "demo":
            raise ResetRefused(f"Refusing to reset {target}: stored db_kind is {kind!r}, not 'demo'.")
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(target) + suffix)
            if p.exists():
                p.unlink()
    open_workbench("demo", target).db.close()
    return target
