"""Coordinator invariants use only fictional records and disposable databases."""

from copy import deepcopy
from datetime import timedelta

import pytest

from reservation_workbench.coordinator.availability import assess, compare
from reservation_workbench.coordinator.store import Store, digest, now, stamp
from reservation_workbench.coordinator.workflow import (
    CHECKS,
    STATES,
    Workflow,
    accepted,
    compose,
    external_current,
    final_gaps,
    next_action,
    profile,
    save_profile,
    sent_current,
    service_record,
)


@pytest.fixture
def setup(tmp_path):
    s = Store(tmp_path / "empty.sqlite")
    s.set_setting("shift", {"operator": "Test coordinator", "started_at": stamp()})
    p = profile()
    p.update(
        name="Illustrative venue",
        timezone="UTC",
        duration_minutes=120,
        verified_by="Test manager",
        tables=[
            {
                "id": "A",
                "capacity": 8,
                "area": "Main",
                "style": "Booth",
                "step_free": True,
            },
            {
                "id": "B",
                "capacity": 10,
                "area": "Main",
                "style": "Table",
                "step_free": False,
            },
        ],
    )
    p = save_profile(s, p, 1)
    f = Workflow(s, "Test coordinator")
    c = f.create(
        "Morgan",
        "morgan@example.com",
        "",
        "Email",
        stamp(),
        "Table for 6 people. I accept the booth, time and two-hour duration.",
    )
    return s, p, f, c


def planned(setup):
    s, p, f, c = setup
    q = {
        "date": (now() + timedelta(days=10)).date().isoformat(),
        "time": "18:00",
        "party": 6,
        "duration": 120,
        "tables": ["A"],
        "arrangement": "One booth for two hours.",
        "photo_id": "",
        "photo_exception": "Guest inspected the booth in person",
        "amount": None,
        "currency": "CAD",
        "basis": "Total",
        "includes": "",
        "waiver": "",
    }
    c = f.run(c, "plan", plan=q)
    details = {
        k: {
            "value": "None" if k != "billing" else "One bill",
            "state": STATES[-1],
            "evidence": "Guest call, confirmed for this visit",
        }
        for k in c["details"]
    }
    c = f.run(
        c,
        "details",
        details=details,
        email=c["email"],
        phone="",
        owner=c["owner"],
        promises="",
    )
    return s, p, f, c


def verified(setup):
    s, p, f, c = planned(setup)
    c = f.run(
        c,
        "availability",
        result="Available externally",
        evidence="Checked current OpenTable and service flow",
    )
    c = f.run(
        c,
        "external",
        reference="REF-1",
        status="Confirmed",
        checks=list(CHECKS),
        note="Saved and double checked",
        hold_until="",
    )
    return s, p, f, c


def complete(setup):
    s, p, f, c = verified(setup)
    c = f.run(
        c,
        "accept",
        source_id=c["messages"][0]["id"],
        quote="I accept the booth, time and two-hour duration.",
    )
    c = f.run(
        c,
        "draft",
        purpose="Final confirmation",
        text=compose(c, p, "Final confirmation"),
    )
    c = f.run(c, "review")
    c = f.run(c, "sent", attachment_checked=False)
    return s, p, f, c


def report(c):
    date = c["plan"]["date"]
    return {
        "kind": "reservations",
        "complete": True,
        "timezone": "UTC",
        "exported_at": stamp(),
        "coverage_start": date,
        "coverage_end": date,
        "rows": [
            {
                "reservation_id": "OTHER",
                "restaurant_id": "V1",
                "status": "Confirmed",
                "tables": "B",
                "_start": date + "T18:00:00+00:00",
            }
        ],
    }


def test_empty_store_has_no_synthetic_records(tmp_path):
    assert Store(tmp_path / "empty.sqlite").cases() == []


def test_completion_requires_three_independent_gates(setup):
    _s, p, f, c = verified(setup)
    assert external_current(c, p) and not accepted(c)
    with pytest.raises(ValueError, match="acceptance"):
        compose(c, p, "Final confirmation")
    c = f.run(
        c,
        "accept",
        source_id=c["messages"][0]["id"],
        quote="I accept the booth, time and two-hour duration.",
    )
    assert final_gaps(c, p) == []
    c = f.run(
        c,
        "draft",
        purpose="Final confirmation",
        text=compose(c, p, "Final confirmation"),
    )
    with pytest.raises(ValueError, match="Review"):
        f.run(c, "sent")
    c = f.run(c, "review")
    c = f.run(c, "sent")
    assert next_action(c, p) == "Complete"


def test_material_change_keeps_external_allocation(setup):
    _s, p, f, c = complete(setup)
    q = deepcopy(c["plan"])
    q["time"] = "19:00"
    c = f.run(c, "plan", plan=q)
    assert not accepted(c) and not external_current(c, p) and not sent_current(c, p)
    assert c["external"]["plan"]["time"] == "18:00"
    assert service_record(c, p)["pending_change"]


def test_contact_change_preserves_acceptance_invalidates_verification(setup):
    _s, p, f, c = complete(setup)
    c = f.run(
        c,
        "details",
        details=c["details"],
        email="new@example.com",
        phone="",
        owner=c["owner"],
        promises="",
    )
    assert accepted(c) and not external_current(c, p)


def test_stale_tab_cannot_write(setup):
    s, _p, f, c = setup
    fresh = f.run(
        c, "task", title="Call", owner="Coordinator", waiting_on="Guest", due=stamp()
    )
    with pytest.raises(ValueError, match="another tab"):
        f.run(c, "timer")
    assert s.get(c["id"]) == fresh


def test_failed_command_rolls_back(setup):
    s, _p, f, c = setup
    with pytest.raises(ValueError):
        f.run(c, "accept", source_id="fake", quote="yes")
    assert s.get(c["id"]) == c and len(s.events(c["id"])) == 1


def test_shift_switch_blocks_old_operator(setup):
    s, _p, f, c = setup
    s.set_setting("shift", {"operator": "Other"})
    with pytest.raises(ValueError, match="shift changed"):
        f.run(c, "timer")


def test_confirmation_requires_evidence_for_none(setup):
    _s, _p, f, c = setup
    details = deepcopy(c["details"])
    details["allergies"].update(state=STATES[-1], value="None")
    with pytest.raises(ValueError, match="evidence"):
        f.run(
            c,
            "details",
            details=details,
            email=c["email"],
            phone="",
            owner=c["owner"],
            promises="",
        )


def test_acknowledgement_does_not_stale_response(setup):
    _s, p, f, c = complete(setup)
    c = f.run(c, "message", text="Thank you!", source="Email", ack=True)
    assert sent_current(c, p)
    c = f.run(c, "message", text="Please change to 19:00", source="Email", ack=False)
    assert not sent_current(c, p) and c["unreviewed"]


def test_no_answer_creates_task_not_acceptance(setup):
    _s, _p, f, c = planned(setup)
    c = f.run(c, "call", outcome="No answer", summary="No answer")
    assert c["tasks"] and not accepted(c)
    with pytest.raises(ValueError, match="quote"):
        f.run(c, "accept", source_id=c["calls"][0]["id"], quote="No answer")


def test_exact_guest_acceptance_quote_required(setup):
    _s, _p, f, c = planned(setup)
    with pytest.raises(ValueError, match="quote"):
        f.run(
            c, "accept", source_id=c["messages"][0]["id"], quote="An invented agreement"
        )


def test_approval_after_feasibility(setup):
    _s, _p, f, c = planned(setup)
    with pytest.raises(ValueError, match="feasibility"):
        f.run(c, "approval", approver="Manager", note="Approved")
    c = f.run(c, "availability", result="Unavailable", evidence="No tables")
    with pytest.raises(ValueError, match="feasibility"):
        f.run(c, "approval", approver="Manager", note="Approved")


def test_separate_policy_thresholds(setup):
    s, p, _f, c = planned(setup)
    p.update(min_spend_threshold=5, manager_threshold=10)
    p = save_profile(s, p, p["version"])
    assert "Minimum-spend terms or approved waiver" in final_gaps(c, p)
    assert "Manager approval" not in final_gaps(c, p)


def test_policy_change_invalidates_external_verification(setup):
    s, p, _f, c = verified(setup)
    p["buffer_minutes"] = 10
    p = save_profile(s, p, p["version"])
    assert not external_current(c, p)


def test_table_changes_require_new_review(setup):
    s, p, _f, _c = setup
    p["tables"][0]["capacity"] = 0
    with pytest.raises(ValueError, match="capacities"):
        save_profile(s, p, p["version"])


def test_photo_or_exception_required(setup):
    _s, p, f, c = complete(setup)
    q = deepcopy(c["plan"])
    q["photo_exception"] = ""
    c = f.run(c, "plan", plan=q)
    assert "Approved seating photo or documented exception" in final_gaps(c, p)


def test_external_checklist_is_required(setup):
    _s, _p, f, c = planned(setup)
    with pytest.raises(ValueError, match="every"):
        f.run(
            c,
            "external",
            reference="REF",
            status="Confirmed",
            checks=[],
            note="Saved",
            hold_until="",
        )


def test_cancellation_must_match_linked_reference(setup):
    _s, _p, f, c = verified(setup)
    with pytest.raises(ValueError, match="linked"):
        f.run(
            c,
            "external",
            reference="WRONG",
            status="Cancelled",
            checks=list(CHECKS),
            note="Cancelled",
            hold_until="",
        )


def test_hold_deadline_before_visit(setup):
    _s, _p, f, c = verified(setup)
    with pytest.raises(ValueError, match="before the visit"):
        f.run(
            c,
            "external",
            reference="REF-1",
            status="Held",
            checks=list(CHECKS),
            note="Held",
            hold_until=(now() + timedelta(days=11)).isoformat(),
        )


def test_duplicate_reference_blocked(setup):
    _s, _p, f, c = verified(setup)
    other = f.create("Other", "other@example.com", "", "Email", stamp(), "Please book.")
    other = f.run(other, "plan", plan=c["plan"])
    other = f.run(
        other, "availability", result="Available externally", evidence="Checked"
    )
    with pytest.raises(ValueError, match="already linked"):
        f.run(
            other,
            "external",
            reference="REF-1",
            status="Confirmed",
            checks=list(CHECKS),
            note="Saved",
            hold_until="",
        )


def test_offer_sent_creates_acceptance_task(setup):
    _s, p, f, c = verified(setup)
    c = f.run(
        c, "draft", purpose="Arrangement offer", text=compose(c, p, "Arrangement offer")
    )
    c = f.run(c, "review")
    c = f.run(c, "sent")
    assert c["tasks"][0]["kind"] == "acceptance"
    c = f.run(
        c,
        "accept",
        source_id=c["messages"][0]["id"],
        quote="I accept the booth, time and two-hour duration.",
    )
    assert c["tasks"][0]["done_at"]


def test_premature_confirmation_wording_blocked(setup):
    _s, _p, f, c = setup
    with pytest.raises(ValueError, match="guarded"):
        f.run(
            c, "draft", purpose="Clarification", text="Your reservation is confirmed."
        )


def test_handoff_changes_when_task_added(setup):
    _s, p, f, c = complete(setup)
    c = f.run(c, "handoff", recipient="Front door")
    assert c["handoff"]["hash"] == digest(service_record(c, p))
    c = f.run(
        c,
        "task",
        title="Call kitchen",
        owner="Coordinator",
        waiting_on="Chef",
        due=stamp(),
    )
    assert c["handoff"]["hash"] != digest(service_record(c, p))


def test_reports_persist_and_expire(setup):
    s, _p, _f, c = planned(setup)
    r = report(c)
    s.save_report(r)
    assert Store(s.path).reports()["reservations"] == r
    with s.connect() as db:
        db.execute(
            "UPDATE reports SET expires=?",
            ((now() - timedelta(seconds=1)).isoformat(),),
        )
    assert s.reports() == {}


def test_venue_pin_survives_clear(setup):
    s, _p, _f, c = planned(setup)
    r = report(c)
    s.save_report(r)
    s.clear_reports()
    r["rows"][0]["restaurant_id"] = "OTHER"
    with pytest.raises(ValueError, match="Restaurant ID"):
        s.save_report(r)


def test_missing_rows_not_cancellation(setup):
    _s, _p, _f, c = planned(setup)
    a = report(c)
    b = deepcopy(a)
    b["rows"] = []
    assert "1 absent" in compare(a, b) and "does not mean cancellation" in compare(a, b)


@pytest.mark.parametrize(
    "change",
    [
        {"complete": False},
        {"exported_at": (now() - timedelta(hours=5)).isoformat()},
        {"timezone": "America/Toronto"},
    ],
)
def test_unsafe_snapshot_cannot_assess(setup, change):
    _s, p, _f, c = planned(setup)
    r = report(c)
    r.update(change)
    assert assess(c, p, r)["status"] == "Cannot assess"


def test_unknown_tables_cannot_assess(setup):
    _s, p, _f, c = planned(setup)
    r = report(c)
    r["rows"][0]["tables"] = "UNKNOWN"
    assert assess(c, p, r)["status"] == "Cannot assess"


def test_potential_and_conflict(setup):
    _s, p, _f, c = planned(setup)
    r = report(c)
    assert assess(c, p, r)["status"] == "Potentially feasible"
    r["rows"][0]["tables"] = "A"
    assert assess(c, p, r)["status"] == "Conflict detected"


def test_linked_reservation_not_double_counted(setup):
    _s, p, _f, c = verified(setup)
    r = report(c)
    r["rows"][0].update(reservation_id="REF-1", tables="A")
    assert assess(c, p, r, [c])["status"] == "Potentially feasible"


def test_later_local_booking_overlays_snapshot(setup):
    _s, p, _f, c = planned(setup)
    r = report(c)
    other = deepcopy(c)
    other["id"] = "OTHER"
    other["external"] = {
        "reference": "NEW",
        "status": "Confirmed",
        "plan": c["plan"],
        "checked_at": (now() + timedelta(seconds=1)).isoformat(),
    }
    assert assess(c, p, r, [other])["status"] == "Conflict detected"


def test_tab_buffers_separate(setup):
    s, _p, _f, c = setup
    s.buffer(c["id"] + ":tab1", 1, "Draft one")
    s.buffer(c["id"] + ":tab2", 1, "Draft two")
    assert Store(s.path).buffer(c["id"] + ":tab1")["text"] == "Draft one"


def test_invalid_photo_rejected(setup):
    s, _p, _f, _c = setup
    with pytest.raises(ValueError, match="PNG or JPEG"):
        s.add_photo("fake.jpg", "Approved", b"not an image")


def test_extraction_has_real_quotes(setup):
    _s, _p, f, c = setup
    c = f.run(c, "interpret")
    for fact in c["interpretation"]["facts"]:
        assert fact["quote"] in c["messages"][0]["text"]


def test_cannot_decline_active_external_booking(setup):
    _s, _p, f, c = verified(setup)
    with pytest.raises(ValueError, match="active external"):
        f.run(c, "disposition", value="Decline", reason="No longer feasible")


def test_incomplete_inquiry_cannot_close(setup):
    _s, _p, f, c = setup
    with pytest.raises(ValueError, match="Finish"):
        f.run(c, "close", reason="Done")


def test_closed_case_removal_is_scoped(setup):
    s, _p, f, c = complete(setup)
    c = f.run(c, "close", reason="Fully complete")
    s.buffer(c["id"] + ":tab", c["revision"], "Text")
    s.delete_closed(c["id"], c["revision"])
    assert (
        s.cases() == []
        and s.events(c["id"]) == []
        and s.buffer(c["id"] + ":tab") is None
    )


def test_arbitrary_table_combination_not_allowed(setup):
    _s, _p, f, c = planned(setup)
    q = deepcopy(c["plan"])
    q["tables"] = ["A", "B"]
    with pytest.raises(ValueError, match="allowed grouping"):
        f.run(c, "plan", plan=q)


def test_photo_requires_attachment_attestation(setup):
    from io import BytesIO

    from PIL import Image

    s, p, f, c = planned(setup)
    out = BytesIO()
    Image.new("RGB", (8, 8), "white").save(out, format="PNG")
    pid = s.add_photo("synthetic.png", "Synthetic test fixture only", out.getvalue())
    q = deepcopy(c["plan"])
    q["photo_id"] = pid
    c = f.run(c, "plan", plan=q)
    c = f.run(c, "availability", result="Available externally", evidence="Checked")
    c = f.run(
        c, "draft", purpose="Arrangement offer", text=compose(c, p, "Arrangement offer")
    )
    c = f.run(c, "review")
    with pytest.raises(ValueError, match="photo"):
        f.run(c, "sent", attachment_checked=False)
    c = f.run(c, "sent", attachment_checked=True)
    assert sent_current(c, p)


def test_clarification_cannot_complete_decline(setup):
    _s, p, f, c = setup
    c = f.run(c, "disposition", value="Decline", reason="Not feasible")
    c = f.run(
        c,
        "draft",
        purpose="Clarification",
        text="Could you confirm your contact details?",
    )
    c = f.run(c, "review")
    c = f.run(c, "sent")
    assert next_action(c, p) != "Complete"


def test_expired_hold_does_not_release_external_record(setup):
    _s, p, _f, c = verified(setup)
    c["external"]["status"] = "Held"
    c["hold_until"] = (now() - timedelta(minutes=1)).isoformat()
    assert next_action(c, p) == "Hold expired: check and release externally"
    assert c["external"]["status"] == "Held"


def test_overnight_coverage_requires_previous_day(setup):
    _s, p, _f, c = planned(setup)
    c["plan"]["time"] = "00:30"
    r = report(c)
    assert assess(c, p, r)["status"] == "Cannot assess"


def test_audit_preserves_before_after_decisions(setup):
    s, _p, f, c = setup
    c = f.run(c, "disposition", value="Decline", reason="Not feasible")
    import json

    change = json.loads(s.events(c["id"])[-1]["data"])["changes"]["disposition"]
    assert change == {"before": "Book", "after": "Decline"}
