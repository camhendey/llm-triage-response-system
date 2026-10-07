"""Replay the three worked examples and save inputs, decisions, records and drafts.

    python scripts/run_worked_examples.py [--out examples]

Each example runs on a fresh in-memory database with the synthetic fixture, the fixed demo clock and
the offline interpreter, so the output is reproducible. Operator decisions are scripted here exactly as
a coordinator would make them in the UI; every one goes through the shared service layer.
"""

from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime, timedelta
from pathlib import Path

from reservation_workbench.domain.clock import FixedClock
from reservation_workbench.domain.config import load_config
from reservation_workbench.persistence.db import Database
from reservation_workbench.providers.offline import OfflineRulesProvider
from reservation_workbench.services.bootstrap import seed_bookings_only
from reservation_workbench.services.workbench import Workbench

CLOCK = datetime.fromisoformat("2026-11-10T10:00:00-05:00")


class Recorder:
    def __init__(self, name: str, title: str):
        self.cfg = load_config()
        self.clock = FixedClock(CLOCK)
        self.wb = Workbench(Database.open(":memory:"), self.cfg, self.clock, OfflineRulesProvider(), mode="demo")
        seed_bookings_only(self.wb)
        self.name, self.title = name, title
        self.inputs: list[dict] = []
        self.steps: list[dict] = []
        self.snapshots: list[dict] = []
        self._k = itertools.count()

    def key(self, tag: str) -> str:
        return f"example:{self.name}:{tag}:{next(self._k)}"

    def tick(self, minutes: int) -> None:
        self.clock.set(self.clock.now() + timedelta(minutes=minutes))

    def step(self, actor: str, action: str, result, **detail) -> dict:
        rec = {"at": self.wb.now().isoformat(), "actor": actor, "action": action, "ok": result.ok,
               "message": result.message, **detail}
        self.steps.append(rec)
        print(f"  [{actor}] {action}: {'ok' if result.ok else 'REFUSED'} - {result.message}")
        return result.data or {}

    def guest(self, iid: str | None, text: str, label: str = "") -> str:
        self.inputs.append({"received_at": self.wb.now().isoformat(), "inquiry": iid or "(new)", "text": text})
        if iid is None:
            r = self.wb.create_inquiry(label, text, self.wb.now(), key=self.key("create"))
            iid = self.step("guest", "message received (new inquiry)", r)["inquiry_id"]
        else:
            self.step("guest", "message received", self.wb.add_message(iid, text, self.wb.now(), key=self.key("msg")))
        self.step("operator", "Interpret new messages (offline rules)", self.wb.interpret(iid, key=self.key("interp")))
        return iid

    def snapshot(self, iid: str, label: str) -> dict:
        v = self.wb.load(iid)
        a = v.assessment
        snap = {
            "label": label, "at": self.wb.now().isoformat(), "inquiry_state": v.inquiry.state.value,
            "record_version": v.inquiry.record_version,
            "booking": None if v.booking is None else {
                "id": v.booking.id, "status": v.booking.status.value, "tables": v.booking.table_ids,
                "start": v.booking.start.astimezone(self.cfg.tz).isoformat(),
                "end": v.booking.end.astimezone(self.cfg.tz).isoformat(), "version": v.booking.version},
            "next_action": a.next_action.value, "next_action_detail": a.next_action_detail,
            "rules": [{"id": r.rule_id, "severity": r.severity.value, "message": r.message}
                      for r in a.blockers + a.reviews + a.advisories],
            "facts": {f.field.value: {"state": f.state, "value": f.value,
                                      "source": None if f.current is None else (f.current.quote or f.current.source_type),
                                      "changed_from": f.changed_from}
                      for f in v.facts.fields.values() if f.state != "unknown"},
            "missing_required": a.missing_required,
        }
        if a.availability is not None:
            snap["availability"] = {
                "options": [{"unit": o.unit_id, "tables": o.table_ids, "step_free": o.step_free, "split": o.split}
                            for o in a.availability.options[:5]],
                "rejected": [{"unit": o.unit_id, "tables": o.table_ids, "reasons": o.reasons}
                             for o in a.availability.rejected],
            }
        snap["alternatives"] = [{"start": t.astimezone(self.cfg.tz).strftime("%H:%M"), "unit": o.unit_id}
                                for t, o in a.alternatives]
        self.snapshots.append(snap)
        return snap

    def draft(self, iid: str, purpose: str | None = None, approve: bool = True) -> str:
        d = self.step("operator", "Generate draft", self.wb.generate_draft(iid, self.key("draft"), purpose=purpose))
        did = d.get("draft_id")
        if approve and did:
            self.step("operator", "Mark draft reviewed", self.wb.approve_draft(did, self.key("approve_draft")))
            self.step("operator", "Record that I copied the draft (not sent)",
                      self.wb.record_copy(iid, "draft", self.key("copy"), draft_id=did))
        return did

    def save(self, out: Path, iid: str, extra_drafts: list[str] | None = None) -> None:
        d = out / self.name
        d.mkdir(parents=True, exist_ok=True)
        v = self.wb.load(iid)
        (d / "inputs.json").write_text(json.dumps({"clock_start": CLOCK.isoformat(), "messages": self.inputs},
                                                  indent=2) + "\n", encoding="utf-8")
        (d / "decisions.json").write_text(json.dumps(self.steps, indent=2, default=str) + "\n", encoding="utf-8")
        (d / "snapshots.json").write_text(json.dumps(self.snapshots, indent=2, default=str) + "\n", encoding="utf-8")
        events = [{"at": e.created_at.isoformat(), "type": e.event_type, "actor": e.actor, "booking": e.booking_id,
                   "reason": e.reason, "after": e.after} for e in v.events]
        record = {"inquiry": v.inquiry.model_dump(mode="json"),
                  "booking": v.booking.model_dump(mode="json") if v.booking else None,
                  "events": events}
        (d / "final_record.json").write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
        drafts = v.drafts
        (d / "drafts.md").write_text("\n\n".join(
            f"## {x.id} ({x.purpose}, status {x.status}, record v{x.source_record_version})\n\n```\n{x.text}\n```"
            for x in drafts) + "\n", encoding="utf-8")
        (d / "booking_notes.txt").write_text(self.wb.booking_notes(iid) + "\n", encoding="utf-8")
        lines = [f"# {self.title}", "", "Replay: `python scripts/run_worked_examples.py`. Synthetic data, fixed demo "
                 "clock, offline interpreter. Nothing is sent and no external system is read or updated.", "",
                 f"| Demo clock ({self.cfg.tz.key}) | Who | Action | Result |", "|---|---|---|---|"]
        for s in self.steps:
            local = datetime.fromisoformat(s['at']).astimezone(self.cfg.tz)
            lines.append(f"| {local:%a %b %d %H:%M} | {s['actor']} | {s['action']} | "
                         f"{'ok' if s['ok'] else 'refused'}: {s['message'].replace('|', '/')} |")
        lines += ["", "Files: `inputs.json` (guest messages), `decisions.json` (every action), `snapshots.json` "
                  "(facts, rules and next action at each checkpoint), `final_record.json` (inquiry, booking, events), "
                  "`drafts.md`, `booking_notes.txt`."]
        (d / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def example_normal(out: Path) -> None:
    print("1. Normal booking")
    r = Recorder("01_normal_booking", "Worked example 1: a normal booking")
    iid = r.guest(None, "Hello, I'd like a table for 6 on Saturday, November 14, 2026 at 7:30 pm. No accessibility "
                        "needs, no minors and no allergies. One bill please, it's my partner's birthday. "
                        "Email: morgan.example@example.com. Thanks, Morgan", label="Synthetic Guest (Morgan)")
    r.snapshot(iid, "after interpretation")
    pid = r.step("operator", "Check & propose", r.wb.propose(iid, r.key("propose")))["proposal_id"]
    r.step("operator", "Approve proposal", r.wb.approve_proposal(pid, r.key("approve")))
    r.step("operator", "Approve proposal again (double click)", r.wb.approve_proposal(pid, r.key("approve2")))
    r.step("operator", "Create demo hold", r.wb.create_hold(pid, r.key("hold")))
    r.draft(iid)
    r.tick(45)
    r.guest(iid, "That sounds perfect, please go ahead and book it.")
    r.step("operator", "Record demo confirmation", r.wb.confirm(iid, r.key("confirm")))
    r.snapshot(iid, "after demo confirmation")
    r.draft(iid)
    r.step("operator", "Record that I copied booking notes", r.wb.record_copy(iid, "booking_notes", r.key("notes")))
    r.save(out, iid)


def example_accessibility(out: Path) -> None:
    print("2. Accessibility / availability conflict")
    r = Recorder("02_accessibility_conflict", "Worked example 2: accessibility and availability conflict")
    iid = r.guest(None, "We are 12 guests for November 13, 2026 at 6 pm. One guest uses a wheelchair. No minors or "
                        "allergies; one bill, birthday. Contact: taylor@example.com. Separate tables are fine.",
                  label="Synthetic Guest (Taylor)")
    snap = r.snapshot(iid, "requested time checked")
    # The operator tries the stairs-only mezzanine anyway: the engine refuses (no generic bypass).
    r.step("operator", "Try proposing stairs-only M1 (should be refused)",
           r.wb.propose(iid, r.key("bad"), unit_id="M1"))
    alt = next(a for a in snap["alternatives"] if a["start"] == "20:30")
    start = datetime.combine(datetime(2026, 11, 13).date(), datetime.strptime(alt["start"], "%H:%M").time(),
                             tzinfo=r.cfg.tz)
    pid = r.step("operator", f"Propose checked alternative {alt['start']} on {alt['unit']}",
                 r.wb.propose(iid, r.key("alt"), unit_id=alt["unit"], start_override=start))["proposal_id"]
    r.step("operator", "Approve proposal", r.wb.approve_proposal(pid, r.key("approve")))
    r.draft(iid, purpose="alternative_offer")
    r.step("operator", "Mark reply sent (reported) - awaiting guest",
           r.wb.mark_awaiting_guest(iid, "operator reports reply sent from their own mail client", r.key("await")))
    r.tick(90)
    r.guest(iid, "8:30 pm works for us. Thank you!")
    r.snapshot(iid, "guest accepted 20:30")
    pid2 = r.step("operator", "Check & propose", r.wb.propose(iid, r.key("propose2")))["proposal_id"]
    r.step("operator", "Approve proposal", r.wb.approve_proposal(pid2, r.key("approve2")))
    r.step("operator", "Create demo hold", r.wb.create_hold(pid2, r.key("hold")))
    r.step("operator", "Record demo confirmation", r.wb.confirm(iid, r.key("confirm")))
    r.snapshot(iid, "confirmed at 20:30")
    r.draft(iid)
    r.save(out, iid)


def example_change(out: Path) -> None:
    print("3. Existing booking changes, then a cancellation")
    r = Recorder("03_booking_change_and_cancel", "Worked example 3: an existing booking changes (and a cancellation)")
    iid = "INQ-B002"
    r.guest(iid, "Please move our 8-person booking on November 13 from 6 pm to 7 pm, specifically to L1.")
    r.snapshot(iid, "change to L1 requested")
    p = r.step("operator", "Check & propose (L1 at 19:00)", r.wb.propose(iid, r.key("p1"), unit_id="L1"))
    r.draft(iid)
    r.tick(30)
    r.guest(iid, "OK, D1 is fine then, still 7 pm.")
    r.snapshot(iid, "change to D1 at 19:00 requested")
    pid = r.step("operator", "Check & propose", r.wb.propose(iid, r.key("p2")))["proposal_id"]
    r.step("operator", "Approve proposal", r.wb.approve_proposal(pid, r.key("a2")))
    r.step("operator", "Commit demo change", r.wb.commit_modification(pid, r.key("commit")))
    r.step("operator", "Commit demo change again (rerun)", r.wb.commit_modification(pid, r.key("commit")))
    r.snapshot(iid, "change committed")
    r.draft(iid)
    r.tick(60)
    r.guest(iid, "So sorry - we now need to cancel the booking entirely.")
    r.snapshot(iid, "cancellation requested (booking still confirmed)")
    r.draft(iid, approve=False)
    r.step("operator", "Record demo cancellation",
           r.wb.cancel_booking(iid, "guest asked to cancel by email", r.key("cancel")))
    r.snapshot(iid, "cancellation recorded")
    r.draft(iid)
    r.save(out, iid)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "examples"))
    out = Path(ap.parse_args().out)
    example_normal(out)
    example_accessibility(out)
    example_change(out)
    print(f"saved to {out}")


if __name__ == "__main__":
    main()
