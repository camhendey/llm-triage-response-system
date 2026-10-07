"""Cross-component regression tests from the product review, not headline test counts."""

from datetime import timedelta
from .conftest import FULL, make_wb, new_inquiry, approve_best, key, add
from reservation_workbench.domain.models import Direction, FieldName
from reservation_workbench.services.drafting import validate_text
from reservation_workbench.providers.offline import OfflineRulesProvider
from reservation_workbench.services.handoff import daily_handoff, handoff_csv


def draft(w, i, purpose=None):
    r = w.generate_draft(i, key(), purpose=purpose)
    assert r.ok, r.message
    return w.load(i).latest_draft


def test_selected_arrangement_is_used_in_reply_and_changes_stale_it(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    approve_best(wb, i, "D1")
    d = draft(wb, i, "availability_offer")
    assert "dining" in d.text and "booth" not in d.text
    assert wb.approve_draft(d.id, key()).ok
    wb.propose(i, key(), unit_id="L3")
    assert wb.load(i).draft_is_stale(d)
    assert not wb.approve_draft(d.id, key()).ok


def test_referral_claim_requires_report_not_just_escalation(wb):
    i = new_inquiry(wb, "We need space for 30 guests on November 14, 2026 at 7 pm.")
    assert "We have passed" not in draft(wb, i).text
    wb.escalate(i, "Needs private space", key())
    assert "We have passed" not in draft(wb, i, "private_events_referral").text
    assert wb.report_referral(i, "Forwarded externally by coordinator", key()).ok
    assert "We have passed" in draft(wb, i, "private_events_referral").text


def test_disclaimer_cannot_neutralize_other_claim(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    v = wb.load(i)
    for bad in [
        "We guarantee we can accommodate your allergies. We cannot guarantee the weather.",
        "We cannot guarantee the weather, but we guarantee your allergies are accommodated.",
    ]:
        assert any(
            x["severity"] == "error"
            for x in validate_text(wb.cfg, v, "clarification", bad)
        )
    assert not any(
        x["severity"] == "error"
        for x in validate_text(
            wb.cfg, v, "clarification", "We cannot guarantee accommodation."
        )
    )


def test_selected_seating_cannot_be_silently_edited(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    approve_best(wb, i, "D1")
    d = draft(wb, i, "availability_offer")
    wb.save_draft_edit(d.id, d.text.replace("dining", "lounge"), key())
    assert not wb.approve_draft(d.id, key()).ok


def test_contact_and_allergy_changes_stale_response(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    d = draft(wb, i)
    wb.approve_draft(d.id, key())
    wb.set_fact(i, "allergies", "sesame", "Guest phoned", key())
    assert wb.load(i).draft_is_stale(d)


def test_changed_amount_requires_fresh_agreement(wb):
    i = new_inquiry(wb, FULL.format(n=25, t="7 pm"))
    wb.set_fact(i, "min_spend_amount", 1000, "Manager decision", key())
    wb.set_fact(i, "min_spend_acknowledged", "yes", "Guest agreed", key())
    wb.set_fact(i, "min_spend_amount", 1500, "Revised amount", key())
    assert wb.load(i).facts.value("min_spend_acknowledged") == "no"
    assert "minimum-spend decision" in wb.load(i).assessment.confirm_gaps


def test_optional_occasion_does_not_block(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm").replace("anniversary.", ""))
    assert "occasion" not in wb.load(i).assessment.missing_required


def test_form_save_is_atomic_and_stale_safe(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    v = wb.load(i)
    r = wb.set_facts(
        i,
        {"party_size": 9, "requested_date": "not-a-date"},
        "review",
        key(),
        v.inquiry.record_version,
    )
    assert not r.ok and wb.load(i).facts.value("party_size") == 6
    wb.set_fact(i, "party_size", 7, "phone", key())
    assert not wb.set_facts(
        i, {"party_size": 8}, "review", key(), v.inquiry.record_version
    ).ok


def test_single_review_commit_keeps_guards_and_idempotency(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    p = wb.propose(i, key(), unit_id="D1").data["proposal_id"]
    token = key()
    assert wb.review_and_commit(p, "confirm", token).ok
    assert wb.review_and_commit(p, "confirm", token).duplicate
    assert wb.load(i).booking.table_ids == ["D1"]


def test_reported_reply_context_is_persistent_and_not_guest_evidence(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    d = draft(wb, i)
    assert not wb.report_reply_sent(i, d.id, key()).ok
    assert wb.approve_draft(d.id, key()).ok
    assert wb.report_reply_sent(i, d.id, key()).ok
    assert wb.report_reply_sent(i, d.id, key()).duplicate
    outs = [
        m for m in wb.load(i).messages if m.direction == Direction.OUTBOUND_REPORTED
    ]
    assert len(outs) == 1 and outs[0].text == d.text
    add(wb, i, "That time works.", wb.now() + timedelta(minutes=1))
    v = wb.load(i)
    assert v.facts.get(FieldName.REQUESTED_TIME).state == "needs_review"
    assert "reported reply" in v.facts.get(FieldName.REQUESTED_TIME).current.note


def test_live_provider_receives_outgoing_context(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    d = draft(wb, i)
    wb.approve_draft(d.id, key())
    wb.report_reply_sent(i, d.id, key())

    class Spy(OfflineRulesProvider):
        seen = None

        def interpret(self, messages, ctx):
            self.seen = messages
            return super().interpret(messages, ctx)

    spy = Spy()
    wb.provider = spy
    add(wb, i, "Could we have 7 guests instead?", wb.now() + timedelta(minutes=1))
    assert any(m.direction == "outbound_reported" and not m.is_new for m in spy.seen)


def test_handoff_uses_actual_allocations_and_excludes_cancelled(wb):
    i = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    p = approve_best(wb, i, "D1")
    wb.confirm(i, key(), proposal_id=p)
    b = wb.load(i).booking
    day = b.start.astimezone(wb.cfg.tz).date()
    assert any(
        r["Booking"] == b.id and r["Tables"] == "D1" for r in daily_handoff(wb, day)
    )
    wb.cancel_booking(i, "Guest request", key())
    assert not any(r["Booking"] == b.id for r in daily_handoff(wb, day))
    assert "'=SUM" in handoff_csv([{"Guest": "=SUM(1,2)"}])


def test_separate_database_connections_reject_stale_edit(cfg, tmp_path):
    path = tmp_path / "shared.sqlite"
    w1 = make_wb(cfg, path)
    w2 = make_wb(cfg, path, seed=False)
    i = new_inquiry(w1, FULL.format(n=6, t="7 pm"))
    version = w2.load(i).inquiry.record_version
    w1.set_fact(i, "party_size", 8, "phone", key())
    assert not w2.set_fact(i, "party_size", 9, "stale browser", key(), version).ok
