"""Deterministic assessment: blockers, reviews, advisories and the next action.

Nothing here calls a model. The assessment is recomputed from stored facts,
bookings and events whenever the workbench renders or a command runs, so the
UI, CLI, tests and evaluation all see identical results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..domain.config import RestaurantConfig
from ..domain.models import (
    NEXT_ACTION_LABELS,
    Booking,
    BookingStatus,
    Event,
    FieldName,
    Inquiry,
    InquiryState,
    Intent,
    Interpretation,
    NextAction,
    Proposal,
    ProposalStatus,
    RuleResult,
    SeatingOption,
    Severity,
)
from .availability import (
    AvailabilityResult,
    SeatingRequest,
    arrival_warning,
    evaluate,
    find_alternatives,
    hold_is_active,
    satisfies_explicit_request,
)
from .facts import Facts

STICKY_STATES = (InquiryState.AWAITING_GUEST, InquiryState.ESCALATED, InquiryState.CLOSED)


@dataclass
class Assessment:
    blockers: list[RuleResult] = field(default_factory=list)
    reviews: list[RuleResult] = field(default_factory=list)
    advisories: list[RuleResult] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    next_action: NextAction = NextAction.NO_ACTION
    next_action_detail: str = ""
    deadline: datetime | None = None
    deadline_label: str | None = None
    urgency: str = "normal"
    availability: AvailabilityResult | None = None
    request: SeatingRequest | None = None
    alternatives: list[tuple[datetime, SeatingOption]] = field(default_factory=list)
    requested_change: dict | None = None
    hold_ready: bool = False
    confirm_ready: bool = False
    confirm_gaps: list[str] = field(default_factory=list)
    hold_expiry_default: datetime | None = None
    hold_needs_operator_deadline: bool = False
    open_intents: list[str] = field(default_factory=list)
    action_status: str = "none"
    derived_state: InquiryState = InquiryState.NEW

    def add(self, severity: Severity, rule_id: str, message: str, **values) -> None:
        r = RuleResult(rule_id=rule_id, severity=severity, message=message, values=values)
        {Severity.BLOCKER: self.blockers, Severity.REVIEW: self.reviews, Severity.ADVISORY: self.advisories}[
            severity].append(r)

    @property
    def rule_ids(self) -> list[str]:
        return [r.rule_id for r in self.blockers + self.reviews + self.advisories]

    @property
    def label(self) -> str:
        return NEXT_ACTION_LABELS[self.next_action]


@dataclass
class AssessmentInput:
    cfg: RestaurantConfig
    inquiry: Inquiry
    facts: Facts
    booking: Booking | None
    all_bookings: list[Booking]
    interpretations: list[Interpretation]
    open_intents: set[str]
    proposals: list[Proposal]
    events: list[Event]
    now: datetime
    latest_inbound_seq: int
    open_material_change: bool = False


def _step_free(facts: Facts) -> tuple[bool, bool]:
    fv = facts.get(FieldName.ACCESSIBILITY)
    if not fv.known:
        return False, False
    return fv.value == "step_free_required", True


def build_request(cfg: RestaurantConfig, facts: Facts, exclude_booking_id: str | None = None,
                  current_table_ids: tuple[str, ...] = ()) -> SeatingRequest | None:
    if not facts.interval_known:
        return None
    step_free, known = _step_free(facts)
    split = facts.value(FieldName.SPLIT_SEATING_OK)
    return SeatingRequest(
        party_size=int(facts.value(FieldName.PARTY_SIZE)),
        start=facts.dining_start,
        end=facts.dining_end,
        step_free_required=step_free,
        accessibility_known=known,
        preferred_area=facts.value(FieldName.PREFERRED_AREA),
        preferred_table=facts.value(FieldName.PREFERRED_TABLE),
        split_ok=None if split is None else split == "yes",
        exclude_booking_id=exclude_booking_id,
        current_table_ids=tuple(current_table_ids),
    )


def allergy_acknowledged(events: list[Event], value) -> bool:
    for e in reversed(events):
        if e.event_type == "allergy_acknowledged":
            return (e.after or {}).get("value") == value
    return False


def assess(inp: AssessmentInput) -> Assessment:
    cfg, facts, now = inp.cfg, inp.facts, inp.now
    pol = cfg.policies
    a = Assessment()
    a.open_intents = sorted(inp.open_intents)
    booking = inp.booking
    active_booking = booking if booking and (
        booking.status == BookingStatus.CONFIRMED or hold_is_active(booking, now)) else None

    # ---- interpretation coverage ------------------------------------
    latest_interp = inp.interpretations[-1] if inp.interpretations else None
    unsupported = latest_interp is not None and latest_interp.status in ("unsupported", "failed")
    if latest_interp is not None:
        for seg in latest_interp.uninterpreted:
            a.add(Severity.REVIEW, "R-UNINTERPRETED", f"Text not interpreted ({latest_interp.provider_mode}): \"{seg}\"",
                  provider=latest_interp.provider_mode)
        for amb in latest_interp.ambiguities:
            if amb.startswith("GUEST-INSTRUCTION:"):
                a.add(Severity.ADVISORY, "R-GUEST-INSTRUCTION",
                      "Guest text contains instructions to the restaurant/system; treated as guest content only, "
                      "no rule bypass or status change: " + amb.split(":", 1)[1].strip())
        if latest_interp.status == "failed":
            a.add(Severity.REVIEW, "R-PROVIDER-FAILED",
                  f"Interpretation failed ({latest_interp.error or 'unknown error'}); review the message manually.")

    # ---- field review items -----------------------------------------
    for f, fv in facts.fields.items():
        if fv.state == "conflict":
            vals = ", ".join(repr(o.value) for o in fv.conflicts)
            a.add(Severity.REVIEW, f"R-CONFLICT-{f.value}",
                  f"{f.value}: current {fv.value!r} conflicts with {vals}; coordinator must decide", field=f.value)
        elif fv.state == "needs_review":
            note = fv.current.note if fv.current else None
            a.add(Severity.REVIEW, f"R-AMBIGUOUS-{f.value}",
                  f"{f.value}: candidate {fv.value!r} needs review" + (f" ({note})" if note else ""), field=f.value)

    party = facts.value(FieldName.PARTY_SIZE)
    acc = facts.get(FieldName.ACCESSIBILITY)
    if acc.known and acc.value == "other_needs":
        a.add(Severity.REVIEW, "R-ACCESS-DETAIL",
              "Accessibility need recorded that the seating engine does not model; review the detail with the guest.",
              note=acc.current.note if acc.current else None)
    allergies = facts.get(FieldName.ALLERGIES)
    allergy_ok = True
    if allergies.known and allergies.value not in (None, "none"):
        allergy_ok = allergy_acknowledged(inp.events, allergies.value)
        if not allergy_ok:
            a.add(Severity.REVIEW, "R-ALLERGY",
                  f"Allergy noted ({allergies.value}). Coordinator acknowledgment required; recording it is not a "
                  "guarantee the kitchen can accommodate it.", value=allergies.value)
    req_dur = facts.value(FieldName.REQUESTED_DURATION)
    if party is not None and req_dur is not None and int(req_dur) > pol.duration_for(int(party)):
        a.add(Severity.REVIEW, "R-DUR-EXT",
              f"Guest asked for {req_dur} min; demo policy allows {pol.duration_for(int(party))} min and no extensions.",
              requested=req_dur, policy=pol.duration_for(int(party)))

    minspend_ok = True
    if party is not None and int(party) >= pol.minimum_spend_review_min_party and int(party) <= cfg.restaurant.max_main_restaurant_party:
        amount = facts.value(FieldName.MIN_SPEND_AMOUNT)
        ack = facts.value(FieldName.MIN_SPEND_ACKNOWLEDGED)
        minspend_ok = amount is not None and ack == "yes"
        if not minspend_ok:
            a.add(Severity.REVIEW, "R-MINSPEND",
                  f"Party of {party} needs a minimum-spend decision: operator enters the amount "
                  f"({'not yet entered' if amount is None else f'CAD {amount}'}) and records guest acknowledgment "
                  f"({'recorded' if ack == 'yes' else 'not yet recorded'}). No contract or payment is handled here.",
                  amount=amount, acknowledged=ack)

    if party is not None and int(party) >= pol.auto_gratuity_min_party:
        a.add(Severity.ADVISORY, "R-GRATUITY",
              f"Auto-gratuity {pol.auto_gratuity_percent:g}% applies to parties of {pol.auto_gratuity_min_party}+ "
              "(must be disclosed in the response).")

    # ---- required fields --------------------------------------------
    missing = []
    for name in pol.confirmation_required_fields:
        if name in ("dining_start", "dining_end"):
            if not facts.interval_known:
                missing.append(name)
            continue
        fv = facts.get(FieldName(name))
        if not fv.known:
            missing.append(name)
    a.missing_required = missing

    # ---- seating -----------------------------------------------------
    oversized = party is not None and int(party) > cfg.restaurant.max_main_restaurant_party
    if oversized:
        a.add(Severity.BLOCKER, "R-MAXPARTY",
              f"Party of {party} exceeds the main-restaurant maximum of {cfg.restaurant.max_main_restaurant_party}; "
              "route to private-events review. Private-room availability is unknown to this system.",
              party=party, max=cfg.restaurant.max_main_restaurant_party)

    req = None
    if not oversized:
        req = build_request(cfg, facts, exclude_booking_id=active_booking.id if active_booking else None,
                            current_table_ids=tuple(active_booking.table_ids) if active_booking else ())
    a.request = req
    if req is None and not oversized and not unsupported:
        gaps = [n for n, f in (("party size", FieldName.PARTY_SIZE), ("date", FieldName.REQUESTED_DATE),
                               ("start time", FieldName.REQUESTED_TIME)) if not facts.get(f).known]
        if gaps and not active_booking:
            a.add(Severity.BLOCKER, "R-INTERVAL", "Cannot check seating: " + ", ".join(gaps) + " unknown or unresolved.")

    if req is not None:
        av = evaluate(cfg, req, inp.all_bookings, now)
        a.availability = av
        for err in av.interval_errors:
            rid = err.split(":", 1)[0]
            a.add(Severity.BLOCKER, rid, err.split(":", 1)[1].strip())
        if av.interval_errors and all(e.startswith("R-HOURS") for e in av.interval_errors):
            # Outside opening hours: the same engine can still suggest same-day times that fit.
            a.alternatives = find_alternatives(cfg, req, inp.all_bookings, now)
        if not av.interval_errors and not av.feasible:
            a.add(Severity.BLOCKER, "R-NO-OPTION", "No feasible seating at the requested time "
                  f"({len(av.rejected)} options checked; see rejected options).")
            a.alternatives = find_alternatives(cfg, req, inp.all_bookings, now)
        best = av.best()
        if best is not None:
            if best.split:
                a.add(Severity.ADVISORY, "R-SPLIT", f"Best option {best.unit_id} is separate tables "
                      f"({' + '.join(best.table_ids)}); disclose that they are not one joined table.")
            for n in best.notes:
                if n.startswith("Preference not satisfied"):
                    a.add(Severity.ADVISORY, "R-PREF", n)
            if not req.accessibility_known and not best.step_free:
                a.add(Severity.REVIEW, "R-ACCESS-UNKNOWN",
                      f"Best option {best.unit_id} is stairs-only and accessibility is unknown; ask before holding.")
            label = active_booking.id if active_booking else inp.inquiry.id
            bucket = arrival_warning(cfg, inp.all_bookings, now, label, req.party_size, req.start,
                                     exclude_booking_id=active_booking.id if active_booking else None)
            if bucket is not None:
                a.add(Severity.ADVISORY, "R-ARRIVAL",
                      f"Heuristic: {bucket.count} large parties ({pol.large_party_min_size}+) arrive in the "
                      f"{bucket.bucket_start:%H:%M} bucket (warning threshold {pol.arrival_warning_party_count}). "
                      "Not a kitchen-capacity prediction.",
                      bucket=bucket.bucket_start.isoformat(), parties=bucket.large_parties)

    # accessibility vs the guest's own seating preference
    if acc.known and acc.value == "step_free_required":
        area = facts.get(FieldName.PREFERRED_AREA)
        table = facts.get(FieldName.PREFERRED_TABLE)
        stairs_pref = []
        if area.known and area.value in cfg.areas and not cfg.areas[area.value].step_free:
            stairs_pref.append(f"the {area.value}")
        if table.known and any(t.id == str(table.value).upper() and not t.step_free for t in cfg.tables):
            stairs_pref.append(f"table {str(table.value).upper()}")
        if stairs_pref:
            a.add(Severity.REVIEW, "R-ACCESS-CONFLICT",
                  f"Guest asked for {' and '.join(stairs_pref)}, which has stairs only, and needs step-free access. "
                  "Offer step-free seating and record the guest's agreement (set the preference to no_preference) "
                  "before confirming.")

    # accessibility vs existing allocation
    if active_booking and acc.known and acc.value == "step_free_required":
        if any(not cfg.table(t).step_free for t in active_booking.table_ids):
            a.add(Severity.BLOCKER, "R-ACCESS-CONFLICT",
                  f"Booking {active_booking.id} uses stairs-only tables but the guest needs step-free access; "
                  "move the booking before confirming.")

    # ---- holds and deadlines -----------------------------------------
    if req is not None and not oversized:
        default_expiry = now + timedelta(hours=pol.hold_hours)
        a.hold_expiry_default = default_expiry
        if pol.hold_expiry_must_precede_dining_start and default_expiry >= req.start:
            a.hold_needs_operator_deadline = pol.short_notice_hold_requires_operator_deadline
            a.hold_expiry_default = None if a.hold_needs_operator_deadline else req.start
    if active_booking and active_booking.status == BookingStatus.HELD and active_booking.hold_expires_at:
        a.deadline, a.deadline_label = active_booking.hold_expires_at, f"Hold {active_booking.id} expires"
    elif facts.interval_known and facts.dining_start > now:
        a.deadline, a.deadline_label = facts.dining_start, "Dining start"
    if a.deadline is not None:
        hrs = (a.deadline - now).total_seconds() / 3600
        limit = (pol.urgency.hold_deadline_high_within_hours if a.deadline_label.startswith("Hold")
                 else pol.urgency.dining_high_within_hours)
        if 0 <= hrs <= limit:
            a.add(Severity.ADVISORY, "R-DEADLINE", f"{a.deadline_label} within {hrs:.1f} h (threshold {limit:g} h).")

    # stale approvals
    stale = [p for p in inp.proposals if p.status == ProposalStatus.STALE]
    approved = [p for p in inp.proposals if p.status == ProposalStatus.APPROVED]
    if stale and not approved and inp.proposals and inp.proposals[-1].status == ProposalStatus.STALE:
        a.add(Severity.BLOCKER, "R-STALE",
              f"Proposal {stale[-1].id} is stale ({stale[-1].status_reason}); recheck before any commit.")

    # ---- readiness ---------------------------------------------------
    blocking_reviews = [r for r in a.reviews if r.rule_id != "R-UNINTERPRETED" or unsupported]
    material_unresolved = any(
        facts.get(f).state in ("conflict", "needs_review")
        for f in (FieldName.PARTY_SIZE, FieldName.REQUESTED_DATE, FieldName.REQUESTED_TIME, FieldName.ACCESSIBILITY)
    )
    seat_ok = a.availability is not None and a.availability.feasible and not a.blockers
    a.hold_ready = (seat_ok and not material_unresolved and not oversized
                    and not (acc.known and acc.value == "step_free_required"
                             and a.availability.best() and not a.availability.best().step_free))
    gaps = list(f"missing {m}" for m in missing)
    gaps += [r.rule_id for r in blocking_reviews if r.rule_id not in ("R-ACCESS-UNKNOWN",)]
    if not allergy_ok:
        gaps.append("allergy acknowledgment")
    if not minspend_ok:
        gaps.append("minimum-spend decision")
    a.confirm_gaps = sorted(set(gaps))
    a.confirm_ready = not a.confirm_gaps and not a.blockers and (
        seat_ok or (active_booking is not None and not _open_change(inp, active_booking)))

    # ---- next action -------------------------------------------------
    _decide(a, inp, active_booking, oversized, unsupported, req)
    a.urgency = _urgency(a, inp, now)
    return a


def _open_change(inp: AssessmentInput, booking: Booking) -> dict:
    """The requested change, but only while it is an *open* request.

    After the coordinator handles a request (commit, decline, or reports a reply
    as sent), differing facts remain visible as an advisory rather than driving
    the next action again.
    """
    change = _requested_change(inp.facts, booking, inp.cfg)
    if change and (inp.open_material_change or Intent.MODIFY_BOOKING.value in inp.open_intents):
        return change
    return {}


def _requested_change(facts: Facts, booking: Booking, cfg: RestaurantConfig) -> dict:
    change = {}
    if facts.value(FieldName.PARTY_SIZE) is not None and int(facts.value(FieldName.PARTY_SIZE)) != booking.party_size:
        change["party_size"] = (booking.party_size, int(facts.value(FieldName.PARTY_SIZE)))
    if facts.interval_known and (facts.dining_start != booking.start or facts.dining_end != booking.end):
        tz = cfg.tz
        change["interval"] = (
            f"{booking.start.astimezone(tz):%Y-%m-%d %H:%M}-{booking.end.astimezone(tz):%H:%M}",
            f"{facts.dining_start.astimezone(tz):%Y-%m-%d %H:%M}-{facts.dining_end.astimezone(tz):%H:%M}",
        )
    pt = facts.value(FieldName.PREFERRED_TABLE)
    if pt and pt not in booking.table_ids:
        change["table"] = (", ".join(booking.table_ids), pt)
    pa = facts.value(FieldName.PREFERRED_AREA)
    if pa and pa != "no_preference" and not all(cfg.table(t).area == pa for t in booking.table_ids):
        change["area"] = (",".join(sorted({cfg.table(t).area for t in booking.table_ids})), pa)
    acc = facts.get(FieldName.ACCESSIBILITY)
    if acc.known and acc.value == "step_free_required" and any(not cfg.table(t).step_free for t in booking.table_ids):
        change["accessibility"] = ("stairs-only allocation", "step-free required")
    return change


def _decide(a: Assessment, inp: AssessmentInput, active_booking: Booking | None, oversized: bool,
            unsupported: bool, req: SeatingRequest | None) -> None:
    inq = inp.inquiry
    intents = inp.open_intents
    facts = inp.facts
    cfg = inp.cfg
    new_inbound = inp.latest_inbound_seq > inq.handled_seq

    def set_(na: NextAction, detail: str = "") -> None:
        a.next_action, a.next_action_detail = na, detail

    # Sticky coordinator states persist until a new guest message arrives.
    if inq.state in STICKY_STATES and not new_inbound:
        if inq.state == InquiryState.AWAITING_GUEST:
            set_(NextAction.AWAIT_GUEST, "Response reported sent by operator; waiting for guest reply.")
        elif inq.state == InquiryState.ESCALATED:
            set_(NextAction.NO_ACTION, "Escalated to private-events review (outside this system).")
        else:
            set_(NextAction.NO_ACTION, "Closed by coordinator.")
        a.derived_state = inq.state
        a.action_status = "waiting" if inq.state == InquiryState.AWAITING_GUEST else "none"
        return

    if not inp.interpretations and inp.latest_inbound_seq > 0 and not any(
            o.current for o in facts.fields.values()):
        set_(NextAction.MANUAL_INTERPRETATION, "No interpretation has run yet.")
        a.derived_state = InquiryState.NEW
        return

    if unsupported and not any(fv.current for fv in facts.fields.values()):
        set_(NextAction.MANUAL_INTERPRETATION,
             "The provider could not interpret this message; read it and enter facts manually.")
        a.derived_state = InquiryState.NEEDS_REVIEW
        a.action_status = "manual"
        return

    if oversized:
        set_(NextAction.ESCALATE_PRIVATE_EVENTS,
             "Over the main-restaurant maximum. No main-restaurant booking can be made; private-room availability is unknown.")
        a.derived_state = InquiryState.NEEDS_REVIEW
        a.action_status = "pending"
        return

    # ---- existing booking -------------------------------------------
    if active_booking is not None:
        change = _open_change(inp, active_booking)
        a.requested_change = change or None
        stale_diff = _requested_change(facts, active_booking, cfg)
        if stale_diff and not change:
            a.add(Severity.ADVISORY, "R-FACTS-DIFFER",
                  f"Current facts differ from booking {active_booking.id} ({', '.join(stale_diff)}); no open change "
                  "request. Revert facts to the booking or record a new request.")
        if Intent.CANCEL_BOOKING.value in intents:
            set_(NextAction.PROCESS_CANCELLATION,
                 f"Guest asked to cancel. Booking {active_booking.id} stays {active_booking.status.value} until "
                 "the coordinator records the cancellation.")
            a.action_status = "cancellation requested - pending commit"
            a.derived_state = InquiryState.NEEDS_REVIEW
            return
        if change:
            av = a.availability
            ok = av is not None and av.feasible and req is not None and any(
                satisfies_explicit_request(o, req) for o in av.options)
            if ok:
                set_(NextAction.PROCESS_MODIFICATION,
                     "Requested change is available. Approve and commit; the original allocation is released only "
                     "when the new one is committed.")
                a.action_status = "change requested - available"
                a.derived_state = InquiryState.READY_FOR_ACTION if not a.reviews else InquiryState.NEEDS_REVIEW
            elif av is None and not facts.interval_known:
                set_(NextAction.OPERATOR_REVIEW, "Change requested but new details are unresolved.")
                a.action_status = "change requested - unresolved"
                a.derived_state = InquiryState.NEEDS_REVIEW
            else:
                why = "; ".join(sorted({r for o in (av.rejected if av else []) for r in o.reasons
                                        if req and req.preferred_table and req.preferred_table in o.table_ids}))
                set_(NextAction.EXPLAIN_CHANGE_UNAVAILABLE,
                     f"Requested change is not available{(': ' + why) if why else ''}. Booking {active_booking.id} "
                     "remains unchanged.")
                a.action_status = "change requested - unavailable"
                a.derived_state = InquiryState.NEEDS_REVIEW
                if av is not None and not av.feasible and req is not None:
                    a.alternatives = a.alternatives or find_alternatives(cfg, req, inp.all_bookings, inp.now)
            return
        if active_booking.status == BookingStatus.HELD:
            if a.confirm_ready:
                set_(NextAction.CONFIRM_BOOKING, "All required details and reviews are recorded.")
                a.derived_state = InquiryState.READY_FOR_ACTION
            elif a.missing_required:
                set_(NextAction.CLARIFY, "Hold in place; request: " + ", ".join(a.missing_required))
                a.derived_state = InquiryState.NEEDS_REVIEW
            else:
                set_(NextAction.OPERATOR_REVIEW, "Hold in place; resolve: " + ", ".join(a.confirm_gaps))
                a.derived_state = InquiryState.NEEDS_REVIEW
            a.action_status = "hold active"
            return
        # confirmed, nothing open
        if a.reviews or a.blockers:
            set_(NextAction.OPERATOR_REVIEW, "Booking confirmed; new information needs review.")
            a.derived_state = InquiryState.NEEDS_REVIEW
        else:
            set_(NextAction.NO_ACTION, f"Booking {active_booking.id} confirmed.")
            a.derived_state = InquiryState.RESOLVED
        return

    # ---- booking ended / declined -----------------------------------
    booking = inp.booking
    if booking is not None and booking.status in (BookingStatus.CANCELLED,) and not new_inbound:
        set_(NextAction.NO_ACTION, f"Booking {booking.id} cancelled.")
        a.derived_state = InquiryState.RESOLVED
        return
    if inq.state == InquiryState.RESOLVED and not new_inbound:
        set_(NextAction.NO_ACTION, "Resolved.")
        a.derived_state = InquiryState.RESOLVED
        return
    if Intent.CANCEL_BOOKING.value in intents and booking is None:
        set_(NextAction.OPERATOR_REVIEW, "Guest mentions cancelling but no booking is linked to this inquiry.")
        a.derived_state = InquiryState.NEEDS_REVIEW
        return

    # ---- new allocation ----------------------------------------------
    if req is None:
        core = (FieldName.PARTY_SIZE, FieldName.REQUESTED_DATE, FieldName.REQUESTED_TIME)
        unresolved = [f.value for f in core if facts.get(f).state in ("needs_review", "conflict")]
        if unresolved:
            set_(NextAction.OPERATOR_REVIEW, "Resolve or clarify: " + ", ".join(unresolved))
        else:
            set_(NextAction.CLARIFY, "Ask for: " + ", ".join(
                f.value for f in core if facts.get(f).state == "unknown"))
        a.derived_state = InquiryState.NEEDS_REVIEW
        return
    av = a.availability
    if av.interval_errors:
        set_(NextAction.OFFER_ALTERNATIVE if a.alternatives else NextAction.CLARIFY,
             "; ".join(av.interval_errors))
        a.derived_state = InquiryState.NEEDS_REVIEW
        return
    if not av.feasible:
        if a.alternatives:
            set_(NextAction.OFFER_ALTERNATIVE, "Requested time unavailable; offer checked times: " + ", ".join(
                f"{t.astimezone(cfg.tz):%H:%M} ({o.unit_id})" for t, o in a.alternatives))
        else:
            set_(NextAction.DECLINE, "No checked option fits on the requested date.")
        a.derived_state = InquiryState.NEEDS_REVIEW
        return
    latest = inp.proposals[-1] if inp.proposals else None
    if latest is not None and latest.status == ProposalStatus.STALE:
        set_(NextAction.RECHECK_PROPOSAL, f"Proposal {latest.id} is stale: {latest.status_reason}")
        a.derived_state = InquiryState.NEEDS_REVIEW
        return
    if a.confirm_ready:
        set_(NextAction.CONFIRM_BOOKING, "All required details present; approve a proposal and record confirmation.")
        a.derived_state = InquiryState.READY_FOR_ACTION
        a.action_status = "proposal approved" if latest and latest.status == ProposalStatus.APPROVED else "ready"
        return
    access_conflict = [r for r in a.reviews if r.rule_id == "R-ACCESS-CONFLICT"]
    if access_conflict:
        # Holding a different (step-free) area before the guest agrees would quietly replace their request.
        set_(NextAction.OPERATOR_REVIEW, access_conflict[0].message)
        a.derived_state = InquiryState.NEEDS_REVIEW
        return
    if a.hold_ready and not any(r.rule_id == "R-ACCESS-UNKNOWN" for r in a.reviews):
        missing = ", ".join(a.missing_required) or "remaining reviews"
        set_(NextAction.CREATE_HOLD, f"Seating available; hold it and request: {missing}")
        a.derived_state = InquiryState.READY_FOR_ACTION
        a.action_status = "proposal approved" if latest and latest.status == ProposalStatus.APPROVED else "ready"
        return
    if any(facts.get(f).state in ("conflict", "needs_review") for f in FieldName):
        set_(NextAction.OPERATOR_REVIEW, "Resolve review items: " + ", ".join(r.rule_id for r in a.reviews))
    else:
        set_(NextAction.CLARIFY, "Ask for: " + ", ".join(a.missing_required or ["accessibility"]))
    a.derived_state = InquiryState.NEEDS_REVIEW


def _urgency(a: Assessment, inp: AssessmentInput, now: datetime) -> str:
    if a.derived_state in (InquiryState.RESOLVED, InquiryState.CLOSED, InquiryState.ESCALATED):
        return "low"
    if a.next_action == NextAction.AWAIT_GUEST:
        # still high when a hold is about to lapse
        pass
    pol = inp.cfg.policies
    if a.deadline is not None:
        hrs = (a.deadline - now).total_seconds() / 3600
        limit = (pol.urgency.hold_deadline_high_within_hours if (a.deadline_label or "").startswith("Hold")
                 else pol.urgency.dining_high_within_hours)
        if hrs <= limit:
            return "high"
    if a.next_action == NextAction.AWAIT_GUEST:
        return "low"
    return "normal"


URGENCY_RANK = {"high": 0, "normal": 1, "low": 2}
