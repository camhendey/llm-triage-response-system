"""Grounded drafting and draft validation.

Critical content (dates, times, party size, seating, hold deadlines, amounts,
policy lines and the *status* of any action) is produced by deterministic
templates from canonical facts. A live model may only contribute an opening and
closing sentence, and that prose is validated before use; on any failure the
deterministic prose is used instead and the failure is recorded.

Validators catch common contradictions (claims of confirmation/cancellation
that did not happen, unverified numbers, guarantees). Regex checks are not
proof of factual grounding; a human still reviews every draft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from ..domain.config import RestaurantConfig
from ..domain.models import BookingStatus, FieldName, NextAction, ProposalStatus
from ..providers.base import ProseRequest
from ..rules.availability import hold_is_active

if TYPE_CHECKING:  # pragma: no cover
    from ..providers.base import Provider
    from .workbench import InquiryView

PURPOSES = {
    "clarification": "Ask for missing or unclear details",
    "availability_offer": "Describe a checked option (no hold yet)",
    "hold_offer": "Describe the demo hold and request remaining details",
    "confirmation": "Confirm a recorded demo confirmation",
    "alternative_offer": "Offer checked alternative times",
    "change_unavailable": "Explain a requested change is unavailable",
    "change_available": "Describe an available change (not yet committed)",
    "change_confirmed": "Confirm a committed change",
    "cancellation_received": "Acknowledge a cancellation request (not yet processed)",
    "cancellation_confirmed": "Confirm a recorded cancellation",
    "decline": "Decline - no checked option fits",
    "private_events_referral": "Refer an oversized group to private-events review",
    "hold_released": "Tell the guest an expired hold was released",
}

QUESTION_TEXT = {
    "party_size": "How many guests will be in your party?",
    "dining_start": "What date and start time would you like?",
    "dining_end": None,
    "requested_date": "Which date would you like? (Please include the month and day.)",
    "requested_time": "What start time would you like?",
    "contact_email": "What is the best email address for your reservation?",
    "contact_phone": "What is the best phone number for your reservation?",
    "accessibility": "Does anyone in your group have accessibility needs (for example, step-free access)?",
    "minors": "Will there be any guests under 19 in your party?",
    "billing": "Would you prefer one bill or separate bills?",
    "occasion": "Are you celebrating a special occasion?",
    "allergies": "Does anyone in your group have food allergies we should note?",
    "guest_name": "Could you share a name for the reservation?",
}


@dataclass
class ComposedDraft:
    purpose: str
    text: str
    validation: list[dict]
    prose_source: str
    prose_error: str | None = None


def _fmt_day(dt: datetime, cfg: RestaurantConfig) -> str:
    local = dt.astimezone(cfg.tz)
    return f"{local:%A, %B} {local.day}, {local.year}"


def _fmt_time(dt: datetime, cfg: RestaurantConfig) -> str:
    local = dt.astimezone(cfg.tz)
    h = local.hour % 12 or 12
    return f"{h}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"


def _seating_sentence(cfg: RestaurantConfig, table_ids: list[str]) -> str:
    tables = [cfg.table(t) for t in table_ids]
    areas = sorted({t.area for t in tables})
    area_txt = " and ".join({"dining": "dining room", "lounge": "lounge", "mezzanine": "mezzanine"}.get(a, a)
                            for a in areas)
    if len(tables) == 1:
        t = tables[0]
        s = f"Your group would be seated at one {t.style.replace('_', ' ')} for up to {t.capacity} in our {area_txt}."
    else:
        caps = " and ".join(f"{t.capacity}" for t in tables)
        s = (f"Your group would be seated in our {area_txt} at {len(tables)} separate tables (seating {caps}). "
             "Please note these are separate tables, not one joined table, and not a private space.")
    if any(not t.step_free for t in tables):
        s += " This area is only accessible by stairs."
    return s


def selected_option(view: "InquiryView"):
    """One selected plan for the operator and guest; ranking is only a pre-selection fallback."""
    p = view.active_proposal
    if p is not None and p.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED):
        if p.source_record_version == view.inquiry.record_version:
            return p.option
    return view.assessment.availability.best() if view.assessment.availability else None


def resolve_purpose(view: "InquiryView") -> str | None:
    a = view.assessment
    b = view.booking
    now = view.now
    held = b is not None and b.status == BookingStatus.HELD and hold_is_active(b, now)
    confirmed = b is not None and b.status == BookingStatus.CONFIRMED
    last_commit = next((e.event_type for e in reversed(view.events) if e.event_type in (
        "booking_modified", "booking_confirmed", "booking_cancelled", "hold_expired", "hold_released",
        "hold_created")), None)
    na = a.next_action
    if na == NextAction.MANUAL_INTERPRETATION:
        return None
    if na == NextAction.ESCALATE_PRIVATE_EVENTS:
        return "private_events_referral"
    if na == NextAction.PROCESS_CANCELLATION:
        return "cancellation_received"
    if na == NextAction.EXPLAIN_CHANGE_UNAVAILABLE:
        return "change_unavailable"
    if na == NextAction.PROCESS_MODIFICATION:
        return "change_available"
    if na == NextAction.OFFER_ALTERNATIVE:
        p = view.active_proposal
        return "availability_offer" if p and p.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED) else "alternative_offer"
    if na == NextAction.DECLINE:
        return "decline"
    if b is not None and b.status == BookingStatus.CANCELLED and last_commit == "booking_cancelled":
        return "cancellation_confirmed"
    if b is not None and b.status == BookingStatus.RELEASED:
        return "hold_released"
    if confirmed and last_commit == "booking_modified":
        return "change_confirmed"
    if confirmed:
        return "confirmation"
    if held:
        return "hold_offer"
    if na in (NextAction.CREATE_HOLD, NextAction.CONFIRM_BOOKING) and a.availability and a.availability.feasible:
        return "availability_offer"
    return "clarification"


def allowed_purposes(view: "InquiryView") -> list[str]:
    """Purposes whose action-status wording is true right now."""
    b = view.booking
    held = b is not None and b.status == BookingStatus.HELD and hold_is_active(b, view.now)
    confirmed = b is not None and b.status == BookingStatus.CONFIRMED
    out = ["clarification"]
    a = view.assessment
    if selected_option(view) is not None:
        out.append("availability_offer")
    if held:
        out.append("hold_offer")
    if confirmed:
        out.append("confirmation")
        if any(e.event_type == "booking_modified" for e in view.events):
            out.append("change_confirmed")
    if a.alternatives:
        out.append("alternative_offer")
    if a.next_action == NextAction.EXPLAIN_CHANGE_UNAVAILABLE:
        out.append("change_unavailable")
    if a.next_action == NextAction.PROCESS_MODIFICATION:
        out.append("change_available")
    if b is not None and b.status in (BookingStatus.HELD, BookingStatus.CONFIRMED):
        out.append("cancellation_received")
    if b is not None and b.status == BookingStatus.CANCELLED:
        out.append("cancellation_confirmed")
    if b is not None and b.status == BookingStatus.RELEASED:
        out.append("hold_released")
    if not (held or confirmed):
        out.append("decline")
    if a.next_action == NextAction.ESCALATE_PRIVATE_EVENTS or any(r.rule_id == "R-MAXPARTY" for r in a.blockers):
        out.append("private_events_referral")
    return list(dict.fromkeys(out))


def _policy_lines(cfg: RestaurantConfig, party: int | None, minutes: int | None) -> list[str]:
    pol = cfg.policies
    lines = []
    if party is not None and party >= pol.auto_gratuity_min_party:
        lines.append(f"An automatic gratuity of {pol.auto_gratuity_percent:g}% applies to parties of "
                     f"{pol.auto_gratuity_min_party} or more.")
    if minutes:
        hrs = minutes / 60
        lines.append(f"Seating is for {hrs:g} hours, and we ask that your group arrive within "
                     f"{pol.arrival_grace_minutes} minutes of the start time.")
    return lines


def _questions(view: "InquiryView", cfg: RestaurantConfig) -> list[str]:
    qs = []
    rules = {r.rule_id for r in view.assessment.blockers}
    if "R-PAST" in rules:
        qs.append("The date and time you mentioned have already passed. Which date did you mean?")
    if "R-HOURS" in rules:
        r = cfg.restaurant
        qs.append(f"We are open from {_clock(r.opening_time)} and seating must finish by {_clock(r.closing_time)}. "
                  "Would a time within those hours work for you?")
    facts = view.facts
    for f in view.assessment.missing_required:
        if f == "dining_end":
            continue
        if f == "dining_start":
            for sub in ("requested_date", "requested_time"):
                if facts.get(FieldName(sub)).state == "unknown":
                    qs.append(QUESTION_TEXT[sub])
            if facts.get(FieldName.PARTY_SIZE).state == "unknown":
                qs.append(QUESTION_TEXT["party_size"])
            continue
        q = QUESTION_TEXT.get(f)
        if q:
            qs.append(q)
    for name in ("requested_date", "requested_time", "party_size"):
        fv = facts.get(FieldName(name))
        if fv.state in ("needs_review", "conflict"):
            q = {"requested_date": "Could you confirm the exact date you have in mind?",
                 "requested_time": "Could you confirm the start time?",
                 "party_size": "Could you confirm the final number of guests?"}[name]
            if q not in qs:
                qs.append(q)
    return list(dict.fromkeys(qs))


def _clock(t) -> str:
    return datetime.combine(date(2000, 1, 1), t).strftime("%I:%M %p").lstrip("0")


def _allergy_line(view: "InquiryView") -> str | None:
    al = view.facts.get(FieldName.ALLERGIES)
    if al.known and al.value not in ("none", None):
        return (f"We have noted the allergy you mentioned ({al.value}). Our team will review it with you before your "
                "visit; we cannot guarantee that every allergy can be accommodated until the kitchen has confirmed.")
    return None


def build_body(cfg: RestaurantConfig, view: "InquiryView", purpose: str) -> str:
    facts = view.facts
    a = view.assessment
    b = view.booking
    party = facts.value(FieldName.PARTY_SIZE)
    paras: list[str] = []
    name = cfg.restaurant.name
    if purpose == "clarification":
        paras.append(f"Thank you for your reservation request at {name}.")
        if b is not None and b.status == BookingStatus.HELD and b.hold_expires_at:
            paras.append(f"We are holding space for {b.party_size} guests on {_fmt_day(b.start, cfg)} from "
                         f"{_fmt_time(b.start, cfg)} to {_fmt_time(b.end, cfg)} until "
                         f"{_fmt_day(b.hold_expires_at, cfg)} at {_fmt_time(b.hold_expires_at, cfg)}.")
        else:
            paras.append("Before we can check and reserve seating, could you please confirm a few details?")
        qs = _questions(view, cfg)
        if qs:
            paras.append("\n".join(f"- {q}" for q in qs))
        else:
            paras.append("- Could you confirm the details of your request?")
    elif purpose in ("availability_offer", "hold_offer"):
        opt = selected_option(view)
        if purpose == "hold_offer":
            start, end, tables, size = b.start, b.end, b.table_ids, b.party_size
        else:
            start, end, tables, size = opt.start, opt.end, opt.table_ids, party
        paras.append(f"Thank you for your reservation request at {name}. We have space for your group of {size} on "
                     f"{_fmt_day(start, cfg)} from {_fmt_time(start, cfg)} to {_fmt_time(end, cfg)}.")
        paras.append(_seating_sentence(cfg, tables))
        if purpose == "hold_offer":
            paras.append(f"We are holding this space until {_fmt_day(b.hold_expires_at, cfg)} at "
                         f"{_fmt_time(b.hold_expires_at, cfg)}. If we have not heard from you by then, the hold "
                         "will be released.")
        else:
            paras.append("This space is not reserved yet; please reply to let us know you would like it.")
        qs = _questions(view, cfg)
        if qs:
            paras.append("To finalize the booking, could you please let us know:\n" + "\n".join(f"- {q}" for q in qs))
        paras += _policy_lines(cfg, size, int((end - start).total_seconds() // 60))
    elif purpose in ("confirmation", "change_confirmed"):
        lead = "Your reservation has been updated." if purpose == "change_confirmed" else \
            "Your reservation is confirmed."
        paras.append(f"{lead} We look forward to welcoming {b.party_size} guests on {_fmt_day(b.start, cfg)} from "
                     f"{_fmt_time(b.start, cfg)} to {_fmt_time(b.end, cfg)}.")
        paras.append(_seating_sentence(cfg, b.table_ids).replace("would be", "will be"))
        paras += _policy_lines(cfg, b.party_size, int((b.end - b.start).total_seconds() // 60))
    elif purpose == "alternative_offer":
        req = a.request
        paras.append(f"Thank you for your reservation request at {name}. Unfortunately we do not have suitable "
                     f"seating for {req.party_size} guests at {_fmt_time(req.start, cfg)} on "
                     f"{_fmt_day(req.start, cfg)}.")
        if a.alternatives:
            opts = "\n".join(f"- {_fmt_time(t, cfg)} to {_fmt_time(t + (req.end - req.start), cfg)}"
                             for t, _o in a.alternatives)
            paras.append("We would be happy to host your group at one of these times on the same day "
                         "(not yet reserved):\n" + opts)
            paras.append("Please let us know if one of these works and we will check it again before reserving.")
    elif purpose == "change_unavailable":
        paras.append(f"Thank you for letting us know. Unfortunately we are not able to make the requested change.")
        paras.append(f"Your existing reservation for {b.party_size} guests on {_fmt_day(b.start, cfg)} from "
                     f"{_fmt_time(b.start, cfg)} to {_fmt_time(b.end, cfg)} remains in place and unchanged.")
        if a.availability and a.availability.feasible:
            o = a.availability.best()
            paras.append(f"At the time you asked for, we could offer a different table instead: "
                         + _seating_sentence(cfg, o.table_ids) + " Let us know if you would like that.")
        elif a.alternatives:
            paras.append("Other times we could check for you on the same day: " + ", ".join(
                _fmt_time(t, cfg) for t, _ in a.alternatives) + ".")
    elif purpose == "change_available":
        o = selected_option(view)
        paras.append("Thank you for letting us know. We can make the change you asked for: "
                     f"{o.start and _fmt_day(o.start, cfg)} from {_fmt_time(o.start, cfg)} to "
                     f"{_fmt_time(o.end, cfg)} for {a.request.party_size} guests.")
        paras.append(_seating_sentence(cfg, o.table_ids))
        paras.append("Your current reservation stays in place until we update it; we will send a note once the "
                     "change is made.")
    elif purpose == "cancellation_received":
        paras.append(f"Thank you for letting us know. We have received your request to cancel the reservation for "
                     f"{b.party_size} guests on {_fmt_day(b.start, cfg)} at {_fmt_time(b.start, cfg)}. We will "
                     "follow up once it has been processed.")
    elif purpose == "cancellation_confirmed":
        paras.append(f"Thank you for letting us know. Your reservation for {b.party_size} guests on "
                     f"{_fmt_day(b.start, cfg)} at {_fmt_time(b.start, cfg)} has been cancelled. We hope to host you "
                     "another time.")
    elif purpose == "decline":
        when = f" on {_fmt_day(a.request.start, cfg)}" if a.request else ""
        paras.append(f"Thank you for considering {name}. Unfortunately we are unable to accommodate your group{when}. "
                     "If another date or time could work, please let us know and we will be happy to check.")
    elif purpose == "private_events_referral":
        paras.append(f"Thank you for your reservation request at {name}. Our main restaurant can accommodate groups "
                     f"of up to {cfg.restaurant.max_main_restaurant_party} guests"
                     + (f", so a group of {party} would need our private-events team." if party else "."))
        if any(e.event_type == "referral_reported" for e in view.events):
            paras.append("We have passed your request to our private-events team for review. "
                         "Private-room availability still needs to be checked with that team.")
        else:
            paras.append("Our private-events team would need to review this request. "
                         "We have not confirmed private-room availability or completed a referral yet.")
        paras.append(f"If your group can be {cfg.restaurant.max_main_restaurant_party} guests or fewer, we would be "
                     "glad to check main-restaurant seating for you.")
    elif purpose == "hold_released":
        paras.append(f"We have not heard back about the reservation we were holding, so the hold has been released. "
                     "If you would still like to visit, please reply and we will check availability again.")
    else:
        raise ValueError(f"unknown purpose {purpose}")
    al = _allergy_line(view)
    if al and purpose in ("hold_offer", "availability_offer", "confirmation", "change_confirmed", "clarification"):
        paras.append(al)
    return "\n\n".join(paras)


def _greeting(view: "InquiryView") -> str:
    n = view.facts.value(FieldName.GUEST_NAME)
    return f"Hi {n}," if n else "Hello,"


SIGNOFF = "Best regards,\nReservations Team"


def compose_draft(cfg: RestaurantConfig, view: "InquiryView", provider: "Provider", purpose: str | None) -> ComposedDraft:
    p = purpose or resolve_purpose(view)
    if p is None:
        raise ValueError("No draft is suggested until the message has been interpreted or facts entered manually.")
    if p not in allowed_purposes(view):
        raise ValueError(f"'{p}' does not match the current booking/action status; allowed: "
                         f"{', '.join(allowed_purposes(view))}")
    body = build_body(cfg, view, p)
    opening, closing = "", ""
    prose_source, prose_error = "deterministic", None
    if provider.mode != "offline_rules":
        occ = view.facts.value(FieldName.OCCASION)
        res = provider.draft_prose(ProseRequest(purpose=p, guest_name=view.facts.value(FieldName.GUEST_NAME),
                                                occasion=occ if occ != "none" else None, fixed_body=body,
                                                conversation=[{"direction": m.direction.value, "text": m.text} for m in view.messages[-8:]]))
        if res.ok:
            checks = validate_prose(res.opening + "\n" + res.closing)
            if checks:
                prose_error = "model prose rejected: " + "; ".join(checks)
            else:
                opening, closing, prose_source = res.opening.strip(), res.closing.strip(), f"live:{res.model}"
        else:
            prose_error = res.error
    parts = [_greeting(view)]
    if opening:
        parts.append(opening)
    parts.append(body)
    if closing:
        parts.append(closing)
    parts.append(SIGNOFF)
    text = "\n\n".join(parts)
    return ComposedDraft(purpose=p, text=text, validation=validate_text(cfg, view, p, text),
                         prose_source=prose_source, prose_error=prose_error)


# ------------------------------------------------------------------ validation

PROSE_FORBIDDEN = [
    (r"\d", "connecting prose may not contain digits (dates, times, sizes and amounts are fixed by the template)"),
    (r"\b(confirm\w*|cancel\w*|book(ed|ing)?|reserv\w*|hold\w*|held|guarantee\w*|available|availability|table|"
     r"private|allerg\w*|refund|deposit|minimum|gratuity|free|discount|upgrade)\b",
     "connecting prose may not discuss bookings, status, policy, money or allergies"),
    (r"https?://|www\.", "links are not allowed"),
]


def validate_prose(text: str) -> list[str]:
    errs = []
    if len(text) > 600:
        errs.append("prose too long")
    for pat, msg in PROSE_FORBIDDEN:
        if re.search(pat, text, re.I):
            errs.append(msg)
    return errs


def _allowed_numbers(cfg: RestaurantConfig, view: "InquiryView") -> set[str]:
    nums: set[str] = set()

    def add_dt(dt: datetime | None):
        if dt is None:
            return
        local = dt.astimezone(cfg.tz)
        nums.update({str(local.day), str(local.year), str(local.hour % 12 or 12), local.strftime("%M"),
                     str(local.hour), local.strftime("%H")})

    facts = view.facts
    b = view.booking
    for v in (facts.value(FieldName.PARTY_SIZE), cfg.restaurant.max_main_restaurant_party,
              cfg.policies.auto_gratuity_min_party, cfg.policies.arrival_grace_minutes,
              f"{cfg.policies.auto_gratuity_percent:g}", facts.value(FieldName.MIN_SPEND_AMOUNT)):
        if v is not None:
            nums.add(str(v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
    opt = selected_option(view)
    if opt:
        add_dt(opt.start)
        add_dt(opt.end)
        nums.add(str(opt.capacity))
    add_dt(facts.dining_start)
    add_dt(facts.dining_end)
    if facts.duration_minutes:
        nums.add(f"{facts.duration_minutes / 60:g}")
    a = view.assessment
    if a.availability:
        for o in a.availability.options[:3]:
            add_dt(o.start)
            add_dt(o.end)
            nums.update(str(cfg.table(t).capacity) for t in o.table_ids)
            nums.add(str(len(o.table_ids)))
    if a.request:
        add_dt(a.request.start)
        add_dt(a.request.end)
        nums.add(str(a.request.party_size))
    for t, o in a.alternatives:
        add_dt(t)
        add_dt(t + (a.request.end - a.request.start) if a.request else t)
    if b is not None:
        nums.add(str(b.party_size))
        add_dt(b.start)
        add_dt(b.end)
        add_dt(b.hold_expires_at)
        nums.update(str(cfg.table(t).capacity) for t in b.table_ids)
        nums.add(str(len(b.table_ids)))
        nums.add(f"{(b.end - b.start).total_seconds() / 3600:g}")
    phone = facts.value(FieldName.CONTACT_PHONE)
    if phone:
        nums.update(re.findall(r"\d+", str(phone)))
    nums.add("19")  # age threshold used in the minors question
    return nums


STATUS_CLAIMS = [
    (r"\b(is|are|has been|have been|now)\s+(confirmed|finali[sz]ed)\b|\breservation is confirmed\b|\bI'?ve (booked|confirmed)\b",
     "confirmed", "claims a confirmation"),
    (r"\b(has been|have been|is|was)\s+cancell?ed\b|\bI'?ve cancell?ed\b|\bwe(?:'ve| have) cancell?ed\b",
     "cancelled", "claims a cancellation"),
    (r"\b(we are|we're|we have been|we've been)\s+holding\b|\bon hold for you\b|\bwe will hold\b|\bhold(ing)? this (space|table|booking)\b",
     "held", "claims a hold"),
    (r"\b(has been|have been)\s+(updated|changed|moved)\b|\breservation has been updated\b|\bwe(?:'ve| have) (moved|changed|updated)\b",
     "modified", "claims a completed change"),
    (r"\bhold has been released\b|\breleased the hold\b", "released", "claims a hold release"),
]


def validate_text(cfg: RestaurantConfig, view: "InquiryView", purpose: str, text: str) -> list[dict]:
    out: list[dict] = []
    b = view.booking
    now = view.now
    status = None
    if b is not None:
        status = "held" if (b.status == BookingStatus.HELD and hold_is_active(b, now)) else b.status.value
    modified = any(e.event_type == "booking_modified" for e in view.events)
    for pat, needed, label in STATUS_CLAIMS:
        if re.search(pat, text, re.I):
            ok = (needed == status) or (needed == "modified" and modified and status == "confirmed")
            if not ok:
                out.append({"check": "action_status", "severity": "error",
                            "message": f"Text {label}, but the recorded booking status is {status or 'none'}."})
    for pat, label in [
        (r"\bguarantee", "guarantees something"),
        (r"\bprivate (dining )?room (is )?(available|reserved|booked)\b|\bprivate room for you\b",
         "claims private-room availability"),
        (r"\b(can|will) (safely )?accommodate (the|your|any|all)? ?(allerg\w*|dietary)", "promises allergy accommodation"),
        (r"\bopentable\b", "mentions an external booking system"),
        (r"\b(sent|emailed) (you|it)\b", "claims a message was sent"),
    ]:
        # Negation is local to the matched clause. A disclaimer elsewhere cannot suppress a claim.
        for sentence in re.split(r"[.!?;\n]+|\bbut\b|\bhowever\b", text, flags=re.I):
            for match in re.finditer(pat, sentence, re.I):
                prefix = sentence[max(0, match.start()-24):match.start()]
                negated = bool(re.search(r"(?:cannot|can't|do not|does not|not able to)\s*$", prefix, re.I))
                if not negated:
                    out.append({"check": "prohibited_claim", "severity": "error", "message": f"Text {label}."})
                    break
    if re.search(r"(?:have|has) (?:passed|forwarded|referred)|referral (?:is|was) (?:complete|sent)", text, re.I) and not any(
            e.event_type == "referral_reported" for e in view.events):
        out.append({"check": "action_status", "severity": "error", "message": "Referral has not been reported completed."})
    if purpose in ("availability_offer", "change_available"):
        opt = selected_option(view)
        if opt:
            # Preserve the exact selected arrangement even when the operator edits surrounding prose.
            for required in (_fmt_day(opt.start, cfg), _fmt_time(opt.start, cfg), _fmt_time(opt.end, cfg),
                             _seating_sentence(cfg, opt.table_ids)):
                if required not in text:
                    out.append({"check": "selected_plan", "severity": "error",
                                "message": "Reply must preserve the selected time and seating description. Regenerate after changing the plan."})
                    break
    allowed = _allowed_numbers(cfg, view)
    unknown = []
    for mm in re.finditer(r"(?<![\w@.-])(\d+(?:\.\d+)?)(?![\w@])", text):
        tok = mm.group(1)
        if tok not in allowed and tok.lstrip("0") not in allowed:
            unknown.append(tok)
    if unknown:
        out.append({"check": "unverified_number", "severity": "error",
                    "message": "Numbers not found in canonical facts/policy: " + ", ".join(sorted(set(unknown)))})
    facts = view.facts
    party = facts.value(FieldName.PARTY_SIZE)
    if purpose in ("hold_offer", "confirmation", "change_confirmed") and b is not None:
        for needle, what in ((str(b.party_size), "party size"), (_fmt_time(b.start, cfg), "start time"),
                             (_fmt_day(b.start, cfg), "date")):
            if needle not in text:
                out.append({"check": "required_detail", "severity": "error", "message": f"Missing {what} ({needle})."})
        if purpose == "hold_offer" and b.hold_expires_at and _fmt_time(b.hold_expires_at, cfg) not in text:
            out.append({"check": "required_detail", "severity": "error", "message": "Missing hold deadline."})
    if party is not None and party >= cfg.policies.auto_gratuity_min_party and purpose in (
            "hold_offer", "availability_offer", "confirmation") and "gratuity" not in text.lower():
        out.append({"check": "required_detail", "severity": "warning", "message": "Auto-gratuity disclosure missing."})
    if b is not None and len(b.table_ids) > 1 and purpose in ("hold_offer", "confirmation", "change_confirmed") and \
            "separate tables" not in text.lower():
        out.append({"check": "required_detail", "severity": "error",
                    "message": "Split seating must be disclosed as separate tables."})
    if b is not None and any(not cfg.table(t).step_free for t in b.table_ids) and purpose in (
            "hold_offer", "confirmation", "change_confirmed") and "stairs" not in text.lower():
        out.append({"check": "required_detail", "severity": "error", "message": "Stairs-only access must be disclosed."})
    if not out:
        out.append({"check": "all", "severity": "ok", "message": "No deterministic issues found. Human review still required."})
    return out


# ------------------------------------------------------------------ booking notes

def booking_notes(cfg: RestaurantConfig, view: "InquiryView") -> str:
    """Copyable notes in the shape of the coordinator's structured note template."""
    f = view.facts
    b = view.booking
    tz = cfg.tz

    def val(name: str) -> str:
        fv = f.get(FieldName(name))
        if fv.state == "unknown":
            return "UNKNOWN - ask guest"
        if fv.state != "known":
            return f"{fv.value} (NEEDS REVIEW)"
        return str(fv.value)

    lines = ["DEMO RECORD - simulated restaurant; not synced to any external booking system", ""]
    if b is not None:
        lines.append(f"Table: {', '.join(b.table_ids)}" + (" (separate tables)" if len(b.table_ids) > 1 else ""))
        lines.append(f"Dine time: {b.start.astimezone(tz):%a %b %d %Y %H:%M}-{b.end.astimezone(tz):%H:%M}")
        if b.status == BookingStatus.HELD and b.hold_expires_at:
            lines.append(f"Status: HELD - awaiting confirmation by {b.hold_expires_at.astimezone(tz):%a %b %d %H:%M}")
        else:
            lines.append(f"Status: {b.status.value.upper()} (booking {b.id})")
        party = b.party_size
    else:
        lines.append("Table: not allocated")
        lines.append("Dine time: " + (f"{f.dining_start.astimezone(tz):%a %b %d %Y %H:%M}" if f.dining_start else "UNKNOWN"))
        lines.append("Status: no booking")
        party = f.value(FieldName.PARTY_SIZE)
    lines.append(f"Party: {party if party is not None else 'UNKNOWN'}")
    lines.append("-" * 30)
    grat = party is not None and party >= cfg.policies.auto_gratuity_min_party
    lines.append(f"Auto gratuity: {'applies (' + format(cfg.policies.auto_gratuity_percent, 'g') + '%) - disclose' if grat else 'n/a'}")
    lines.append(f"Minors: {val('minors')}")
    lines.append(f"Accessibility: {val('accessibility')}")
    lines.append(f"Payment: {val('billing')}")
    lines.append("-" * 30)
    lines.append(f"Occasion: {val('occasion')}")
    lines.append(f"Allergies: {val('allergies')}" + (" (acknowledged for follow-up; not a guarantee)"
                                                     if any(e.event_type == 'allergy_acknowledged' for e in view.events)
                                                     else ""))
    ms = f.value(FieldName.MIN_SPEND_AMOUNT)
    if ms is not None:
        lines.append(f"Minimum spend (operator-entered): CAD {ms:g}; guest acknowledged: "
                     f"{f.value(FieldName.MIN_SPEND_ACKNOWLEDGED) or 'not recorded'}")
    lines.append("-" * 30)
    lines.append(f"Guest: {view.inquiry.guest_label}" + (f" / {val('guest_name')}" if f.value(FieldName.GUEST_NAME) else ""))
    lines.append(f"Email: {val('contact_email')}")
    lines.append(f"Tel: {val('contact_phone')}")
    lines.append("-" * 30)
    lines.append(f"Inquiry: {view.inquiry.id}  record v{view.inquiry.record_version}  policy {cfg.policy_version}")
    return "\n".join(lines)
