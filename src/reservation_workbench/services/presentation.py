"""Operator-facing progress. Booking state does not imply the reply is finished."""

from ..domain.models import Direction, InquiryState, BookingStatus
from ..rules.availability import hold_is_active


def sent_event(v):
    d = v.latest_draft
    if not d or v.draft_is_stale(d) or not v.draft_approval_current(d):
        return None
    return next(
        (
            e
            for e in reversed(v.events)
            if e.event_type == "reply_reported_sent"
            and (e.after or {}).get("draft_id") == d.id
        ),
        None,
    )


def response_status(v):
    d = v.latest_draft
    if not d:
        return "Not prepared"
    if v.draft_is_stale(d):
        return "Update needed"
    if sent_event(v):
        return "Reported sent"
    return "Ready to copy" if v.draft_approval_current(d) else "Needs review"


def unread(v):
    seen = max(
        (
            (e.after or {}).get("message_seq", 0)
            for e in v.events
            if e.event_type == "conversation_reviewed"
        ),
        default=0,
    )
    return any(m.direction == Direction.INBOUND and m.seq > seen for m in v.messages)


def referral_done(v):
    return any(e.event_type == "referral_reported" for e in v.events)


def work_status(v):
    if v.inquiry.state == InquiryState.CLOSED:
        return "Closed"
    if v.inquiry.state == InquiryState.ESCALATED:
        return "Referral recorded" if referral_done(v) else "Referral pending"
    if v.assessment.requested_change:
        return "Change requested"
    if v.inquiry.state == InquiryState.AWAITING_GUEST and sent_event(v):
        return "Waiting for guest"
    if v.assessment.blockers or v.assessment.reviews:
        return "Needs attention"
    if sent_event(v):
        return "Completed"
    if v.booking and v.booking.status in (
        BookingStatus.CONFIRMED,
        BookingStatus.CANCELLED,
        BookingStatus.RELEASED,
    ):
        return "Reply pending"
    if v.assessment.next_action.value == "no_action":
        return "Reply pending"
    if v.assessment.confirm_ready:
        return "Ready to finalize"
    return "Needs attention"


def hold_urgency(v):
    if v.booking and hold_is_active(v.booking, v.now):
        hours = (v.booking.hold_expires_at - v.now).total_seconds() / 3600
        if hours <= 6:
            return (
                f"Hold expires in {max(1, round(hours * 60))} min"
                if hours < 1
                else f"Hold expires in {hours:.0f}h"
            )
    return ""


def next_step(v):
    status = work_status(v)
    response = response_status(v)
    if status == "Referral pending":
        return (
            "Arrange the private-events referral",
            "Record completion only after you have referred the request elsewhere.",
        )
    if status == "Referral recorded" and not sent_event(v):
        return (
            "Prepare the referral reply",
            "The referral is recorded. Let the guest know what happens next.",
        )
    if status in ("Completed", "Closed"):
        return (
            "All current work is complete",
            "The recorded booking and response are up to date.",
        )
    if status == "Waiting for guest":
        return "Waiting for the guest", "Add their next reply when it arrives."
    if status == "Reply pending":
        return (
            "Record the reply handoff"
            if response == "Ready to copy"
            else "Review the guest reply"
            if response == "Needs review"
            else "Prepare the guest reply"
        ), "The booking is recorded. The response still needs to be completed."
    labels = {
        "confirm_booking": "Choose seating and confirm",
        "create_hold": "Choose seating for a hold",
        "offer_alternative": "Offer checked alternative times",
        "recheck_proposal": "Check seating after the change",
        "process_modification": "Review the requested change",
        "process_cancellation": "Review the cancellation",
        "escalate_private_events": "Refer to private events",
        "operator_review": "Review the highlighted details",
        "clarify": "Request the missing details",
        "manual_interpretation": "Review the guest message",
        "explain_change_unavailable": "Offer another arrangement",
    }
    return labels.get(
        v.assessment.next_action.value, "Review this inquiry"
    ), "Resolve the items below, then prepare the appropriate reply."
