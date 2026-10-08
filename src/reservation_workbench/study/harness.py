"""Operator handling-time study: 12 cases x 3 methods = 36 sessions.

No times are generated here. A session's durations are computed only from timer events an operator
records (start, pause, resume, model-wait start/stop, finish). Until sessions exist, every report
says so.

Order: the six permutations of the three methods are each assigned to two cases. Sessions run in
three rounds; round r uses each case's r-th method, and cases are shuffled within a round with a
fixed seed, so the same case is never handled twice in a row.
"""

from __future__ import annotations

import csv
import io
import itertools
import json
import os
import random
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import yaml

ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = ROOT / "data" / "study" / "cases.yaml"
DB_PATH = Path(os.getenv("RW_STUDY_DB") or str(ROOT / "data" / "study" / "study_sessions.sqlite"))
OUT_DIR = ROOT / "results" / "study"
METHODS = ("template_only", "structured_llm", "workbench")
METHOD_LABELS = {"template_only": "1. Template-only + manual availability check",
                 "structured_llm": "2. Reconstructed structured-LLM workflow",
                 "workbench": "3. Reservation Operations Workbench"}
CHECKLIST = [
    ("facts_recorded", "All guest facts captured, unknowns marked unknown (not guessed)"),
    ("availability_checked", "Simulated availability checked for the requested time (or alternatives)"),
    ("policy_checked", "Applicable policies checked (gratuity, accessibility, minimum spend, allergies)"),
    ("booking_action_recorded", "Required simulated booking action recorded (hold/confirm/change/none) with notes"),
    ("notes_updated", "Booking notes updated in the standard format"),
    ("response_reviewed", "Initial guest response drafted and reviewed (not sent)"),
]
SEED = 20261110


@dataclass
class StudyCase:
    id: str
    title: str
    source: str
    brief: str
    expected_outcome: str


def load_cases(path: Path = CASES_PATH) -> list[StudyCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = [StudyCase(**c) for c in raw["cases"]]
    if len(cases) != 12:
        raise ValueError(f"expected 12 study cases, found {len(cases)}")
    return cases


def build_plan(cases: list[StudyCase] | None = None) -> list[dict]:
    cases = cases or load_cases()
    perms = list(itertools.permutations(METHODS))  # 6 orders
    order = {c.id: perms[i % 6] for i, c in enumerate(cases)}  # each order used exactly twice
    rng = random.Random(SEED)
    plan, seq = [], 0
    for rnd in range(3):
        ids = [c.id for c in cases]
        rng.shuffle(ids)
        for cid in ids:
            seq += 1
            plan.append({"seq": seq, "round": rnd + 1, "case_id": cid, "method": order[cid][rnd],
                         "order": "-".join(m.split("_")[0] for m in order[cid])})
    return plan


def write_plan(out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "study_plan.csv"
    plan = build_plan()
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(plan[0]))
        w.writeheader()
        w.writerows(plan)
    return p


# ---------------------------------------------------------------------------- store
SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  seq INTEGER PRIMARY KEY, case_id TEXT NOT NULL, method TEXT NOT NULL, round INTEGER NOT NULL,
  operator TEXT, familiarity TEXT, status TEXT NOT NULL DEFAULT 'pending',
  corrections INTEGER DEFAULT 0, errors INTEGER DEFAULT 0, incomplete_requirements INTEGER DEFAULT 0,
  checklist TEXT DEFAULT '{}', notes TEXT DEFAULT '', artifact_path TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS timer_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, seq INTEGER NOT NULL, kind TEXT NOT NULL, at REAL NOT NULL);
"""
TRANSITIONS = {  # current timer state -> allowed event kinds
    "pending": {"start"}, "running": {"pause", "wait_start", "finish"}, "paused": {"resume", "finish"},
    "waiting": {"wait_end"}, "finished": set(),
}
NEXT_STATE = {"start": "running", "pause": "paused", "resume": "running", "wait_start": "waiting",
              "wait_end": "running", "finish": "finished"}


class StudyStore:
    """Sessions and timer events. ``clock`` returns epoch seconds and is injectable for tests."""

    def __init__(self, path: Path | str = DB_PATH, clock: Callable[[], float] = time.time):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.clock = clock
        if self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0:
            with self.conn:
                for r in build_plan():
                    self.conn.execute("INSERT INTO sessions(seq, case_id, method, round) VALUES (?,?,?,?)",
                                      (r["seq"], r["case_id"], r["method"], r["round"]))

    def sessions(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM sessions ORDER BY seq").fetchall()

    def events(self, seq: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM timer_events WHERE seq=? ORDER BY id", (seq,)).fetchall()

    def state(self, seq: int) -> str:
        st = "pending"
        for e in self.events(seq):
            st = NEXT_STATE[e["kind"]]
        return st

    def record(self, seq: int, kind: str) -> str:
        cur = self.state(seq)
        if kind not in TRANSITIONS[cur]:
            raise ValueError(f"cannot '{kind}' while session {seq} is {cur}")
        with self.conn:
            self.conn.execute("INSERT INTO timer_events(seq, kind, at) VALUES (?,?,?)", (seq, kind, self.clock()))
            self.conn.execute("UPDATE sessions SET status=? WHERE seq=?",
                              ("completed" if kind == "finish" else "in_progress", seq))
        return NEXT_STATE[kind]

    def update(self, seq: int, **fields) -> None:
        allowed = {"operator", "familiarity", "corrections", "errors", "incomplete_requirements", "notes",
                   "artifact_path"}
        if "checklist" in fields:
            fields["checklist"] = json.dumps(fields["checklist"])
            allowed.add("checklist")
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            with self.conn:
                self.conn.execute(f"UPDATE sessions SET {', '.join(f'{k}=?' for k in sets)} WHERE seq=?",
                                  (*sets.values(), seq))

    def durations(self, seq: int) -> dict:
        """Active = start..finish minus pauses; model wait counted separately (and inside active)."""
        ev = self.events(seq)
        if not ev or ev[0]["kind"] != "start":
            return {"elapsed_s": None, "active_s": None, "paused_s": None, "model_wait_s": None}
        paused = wait = 0.0
        mark: dict[str, float] = {}
        end = None
        for e in ev:
            k, at = e["kind"], e["at"]
            if k in ("pause", "wait_start"):
                mark[k] = at
            elif k == "resume":
                paused += at - mark.pop("pause")
            elif k == "wait_end":
                wait += at - mark.pop("wait_start")
            elif k == "finish":
                end = at
        if end is None:
            return {"elapsed_s": None, "active_s": None, "paused_s": round(paused, 1), "model_wait_s": round(wait, 1)}
        elapsed = end - ev[0]["at"]
        return {"elapsed_s": round(elapsed, 1), "active_s": round(elapsed - paused, 1), "paused_s": round(paused, 1),
                "model_wait_s": round(wait, 1)}


def export_csv(store: StudyStore | None = None, out_dir: Path = OUT_DIR) -> Path:
    store = store or StudyStore()
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "study_sessions.csv"
    p.write_text(sessions_csv(store), encoding="utf-8")
    return p


def sessions_csv(store: StudyStore) -> str:
    buf = io.StringIO()
    cols = ["seq", "round", "case_id", "method", "status", "operator", "familiarity", "started_at_utc",
            "elapsed_s", "active_s", "paused_s", "model_wait_s", "corrections", "errors",
            "incomplete_requirements"] + [c for c, _ in CHECKLIST] + ["notes", "artifact_path"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for s in store.sessions():
        ev = store.events(s["seq"])
        d = store.durations(s["seq"])
        chk = json.loads(s["checklist"] or "{}")
        row = {k: s[k] for k in ("seq", "round", "case_id", "method", "status", "operator", "familiarity",
                                 "corrections", "errors", "incomplete_requirements", "notes", "artifact_path")}
        row["started_at_utc"] = (datetime.fromtimestamp(ev[0]["at"], UTC).isoformat(timespec="seconds")
                                 if ev else "")
        row.update({k: ("" if v is None else v) for k, v in d.items()})
        row.update({c: ("yes" if chk.get(c) else "no") if s["status"] == "completed" else "" for c, _ in CHECKLIST})
        w.writerow(row)
    return buf.getvalue()


def status(store: StudyStore | None = None) -> dict:
    store = store or StudyStore()
    rows = store.sessions()
    done = [r for r in rows if r["status"] == "completed"]
    return {"sessions_planned": len(rows), "sessions_completed": len(done),
            "by_method": {m: sum(1 for r in done if r["method"] == m) for m in METHODS},
            "status": "pending - no real sessions recorded" if not done else
            ("complete" if len(done) == len(rows) else "in progress"),
            "note": "Durations exist only for sessions an operator actually timed. None are generated."}
