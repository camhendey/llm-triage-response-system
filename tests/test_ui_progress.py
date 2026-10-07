from reservation_workbench.services.presentation import (
    work_status,
    response_status,
    next_step,
    unread,
)
from reservation_workbench.domain.models import FieldName
from .conftest import new_inquiry, FULL, key, add


def confirm(wb):
    iid = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    p = wb.propose(iid, key()).data["proposal_id"]
    assert wb.review_and_commit(p, "confirm", key()).ok
    return iid


def test_confirmed_booking_stays_active_until_reviewed_reply_reported(wb):
    iid = confirm(wb)
    v = wb.load(iid)
    assert work_status(v) == "Reply pending"
    assert response_status(v) == "Not prepared"
    assert "reply" in next_step(v)[0]
    wb.generate_draft(iid, key())
    v = wb.load(iid)
    d = v.latest_draft
    assert response_status(v) == "Needs review"
    wb.approve_draft(d.id, key())
    v = wb.load(iid)
    assert work_status(v) == "Reply pending" and response_status(v) == "Ready to copy"
    wb.report_reply_sent(iid, d.id, key())
    v = wb.load(iid)
    assert work_status(v) == "Completed" and response_status(v) == "Reported sent"
    add(wb, iid, "Correction: there will be 10 of us, not 6.")
    assert work_status(wb.load(iid)) != "Completed"


def test_internal_escalation_is_not_a_completed_referral(wb):
    iid = new_inquiry(wb, FULL.format(n=30, t="7 pm"))
    wb.escalate(iid, "Needs private dining", key())
    assert work_status(wb.load(iid)) == "Referral pending"
    wb.report_referral(iid, "Forwarded to events coordinator", key())
    v = wb.load(iid)
    assert work_status(v) == "Referral recorded"
    assert "reply" in next_step(v)[0]


def test_clear_preserves_history_unknown_and_invalidates_draft(wb):
    iid = confirm(wb)
    wb.generate_draft(iid, key())
    d = wb.load(iid).latest_draft
    old = wb.load(iid).facts.value("contact_email")
    version = wb.load(iid).inquiry.record_version
    assert wb.clear_fact(
        iid, "contact_email", "Guest withdrew address", key(), version
    ).ok
    v = wb.load(iid)
    f = v.facts.get(FieldName.CONTACT_EMAIL)
    assert f.state == "unknown" and f.value is None
    assert any(o.value == old for o, _ in f.history)
    assert v.draft_is_stale(d)
    assert not wb.clear_fact(iid, "party_size", "stale update", key(), version).ok


def test_clear_and_set_form_is_atomic(wb):
    iid = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    old = wb.load(iid).facts.value("contact_email")
    r = wb.set_facts(
        iid, {"contact_email": None, "requested_date": "not-a-date"}, "review", key()
    )
    assert not r.ok and wb.load(iid).facts.value("contact_email") == old


def test_read_receipt_is_separate_from_interpretation(wb):
    iid = new_inquiry(wb, FULL.format(n=6, t="7 pm"))
    assert not wb.pending_message_ids(iid)
    assert unread(wb.load(iid))
    wb.mark_conversation_reviewed(iid, key())
    assert not unread(wb.load(iid))
    add(wb, iid, "Thank you for checking.")
    assert unread(wb.load(iid))


def test_new_message_requires_fresh_reply_review_even_without_fact_changes(wb):
    iid = confirm(wb)
    wb.generate_draft(iid, key())
    d = wb.load(iid).latest_draft
    wb.approve_draft(d.id, key())
    wb.report_reply_sent(iid, d.id, key())
    add(wb, iid, "Thank you. Could you explain the policy?")
    v = wb.load(iid)
    assert response_status(v) == "Update needed"
    assert work_status(v) != "Completed"
    assert not wb.report_reply_sent(iid, d.id, key()).ok
