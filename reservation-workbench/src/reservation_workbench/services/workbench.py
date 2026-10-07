"""Application service layer: every state change goes through here.

The Streamlit UI, the CLI, the evaluation runner and the tests all call these
methods, so the same deterministic rules and transaction boundaries apply
everywhere.

Command conventions
-------------------
* Every mutating command takes an ``idempotency_key``. If an event with that key
  already exists the command returns the original result and writes nothing.
* Commands that depend on what the operator was looking at take
  ``expected_record_version``; if the inquiry moved on, the command is rejected
  as stale instead of overwriting newer facts.
* Booking writes re-run the availability engine *inside* the same
  ``BEGIN IMMEDIATE`` transaction that performs the write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..domain.clock import Clock, FixedClock
from ..domain.config import RestaurantConfig
from ..domain.models import (
    ACTIVE_BOOKING_STATUSES,
    MATERIAL_FIELDS,
    Booking,
    BookingStatus,
    Direction,
    Draft,
    Event,
    FieldName,
    FieldStatus,
    Inquiry,
    InquiryState,
    Interpretation,
    Message,
    MessageSource,
    NextAction,
    Observation,
    Proposal,
    ProposalKind,
    ProposalStatus,
)
from ..persistence.db import Database
from ..persistence.repo import Repo
from ..providers.base import InterpretContext, MessageInput, Provider, normalize_value, validate_evidence
from ..rules.assessment import STICKY_STATES, Assessment, AssessmentInput, assess, build_request
from ..rules.availability import evaluate, hold_is_active
from ..rules.facts import Facts, resolve

MAX_MESSAGE_CHARS = 5000
MAX_REASON_CHARS = 1000

# Booking status transitions the service will perform.
ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.NONE: {BookingStatus.HELD, BookingStatus.CONFIRMED},
    BookingStatus.HELD: {BookingStatus.CONFIRMED, BookingStatus.RELEASED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED},
    BookingStatus.CANCELLED: set(),
    BookingStatus.RELEASED: set(),
}


class DomainError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CommandResult:
    ok: bool
    message: str = ""
    code: str | None = None
    duplicate: bool = False
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class InquiryView:
    inquiry: Inquiry
    messages: list[Message]
    observations: list[Observation]
    facts: Facts
    booking: Booking | None
    assessment: Assessment
    proposals: list[Proposal]
    drafts: list[Draft]
    events: list[Event]
    interpretations: list[Interpretation]
    now: datetime

    @property
    def latest_draft(self) -> Draft | None:
        return self.drafts[-1] if self.drafts else None

    @property
    def active_proposal(self) -> Proposal | None:
        for p in reversed(self.proposals):
            if p.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED, ProposalStatus.STALE):
                return p
        return None

    def draft_is_stale(self, d: Draft) -> bool:
        return d.source_record_version != self.inquiry.record_version

    def draft_approval_current(self, d: Draft) -> bool:
        return d.status == "approved" and d.approved_record_version == self.inquiry.record_version


COMMIT_EVENTS = {
    "hold_created", "booking_confirmed", "booking_modified", "booking_cancelled", "hold_released",
    "inquiry_declined", "inquiry_escalated", "awaiting_guest_marked", "inquiry_closed", "facts_reverted_to_booking",
}


class Workbench:
    def __init__(self, db: Database, cfg: RestaurantConfig, clock: Clock, provider: Provider, mode: str = "demo"):
        self.db = db
        self.repo = Repo(db)
        self.cfg = cfg
        self.clock = clock
        self.provider = provider
        self.mode = mode  # demo | session | eval

    # ================================================================ helpers
    def now(self) -> datetime:
        return self.clock.now()

    def _event(self, key: str, event_type: str, inquiry_id: str | None, actor: str = "operator", *,
               booking_id: str | None = None, before: Any = None, after: Any = None, reason: str | None = None,
               proposal_id: str | None = None, record_version: int | None = None,
               booking_version: int | None = None) -> Event:
        e = Event(
            id="E-" + uuid.uuid4().hex[:12], idempotency_key=key, inquiry_id=inquiry_id, booking_id=booking_id,
            actor=actor, event_type=event_type, before=before, after=after, reason=reason, created_at=self.now(),
            mode=f"{self.mode}/{self.provider.mode}", proposal_id=proposal_id, record_version=record_version,
            booking_version=booking_version,
        )
        self.repo.insert_event(e)
        return e

    def _run(self, key: str, fn) -> CommandResult:
        if not key:
            raise ValueError("idempotency key required")
        prior = self.repo.find_event(key)
        if prior is not None:
            return CommandResult(ok=True, duplicate=True, message="Already recorded (duplicate request ignored).",
                                 data={"event_id": prior.id, **(prior.after if isinstance(prior.after, dict) else {})})
        try:
            with self.db.transaction():
                if self.repo.find_event(key) is not None:  # lost race
                    return CommandResult(ok=True, duplicate=True, message="Already recorded.")
                self._reconcile_in_tx()
                return fn()
        except DomainError as exc:
            return CommandResult(ok=False, code=exc.code, message=exc.message)

    def _inq(self, inquiry_id: str) -> Inquiry:
        inq = self.repo.get_inquiry(inquiry_id)
        if inq is None:
            raise DomainError("not_found", f"inquiry {inquiry_id} not found")
        return inq

    def _check_version(self, inq: Inquiry, expected: int | None) -> None:
        if expected is not None and expected != inq.record_version:
            raise DomainError("stale_view", f"{inq.id} changed (version {inq.record_version}, you were viewing "
                              f"{expected}). Reload and recheck before acting.")

    @staticmethod
    def _reason(reason: str | None, required: bool = True) -> str | None:
        r = (reason or "").strip()
        if required and not r:
            raise DomainError("reason_required", "A reason is required for this action.")
        if len(r) > MAX_REASON_CHARS:
            raise DomainError("too_long", f"Reason exceeds {MAX_REASON_CHARS} characters.")
        return r or None

    # ================================================================ clock
    def set_demo_clock(self, instant: datetime, key: str) -> CommandResult:
        if not isinstance(self.clock, FixedClock):
            return CommandResult(ok=False, code="not_fixed", message="Clock is the real system clock in this session.")
        before = self.clock.now()

        def fn():
            if instant < before:
                raise DomainError("clock_backwards", "The demo clock only moves forward (holds may already have expired).")
            self.clock.set(instant)
            self.db.set_meta("fixed_clock", instant.isoformat())
            self._event(key, "demo_clock_changed", None, before=before.isoformat(), after={"clock": instant.isoformat()})
            self._reconcile_in_tx()
            return CommandResult(ok=True, message=f"Demo clock set to {instant.astimezone(self.cfg.tz):%Y-%m-%d %H:%M %Z}")

        return self._run(key, fn)

    # ================================================================ reconciliation
    def reconcile(self) -> int:
        with self.db.transaction():
            return self._reconcile_in_tx()

    def _reconcile_in_tx(self) -> int:
        """Release expired holds exactly once (idempotent per booking)."""
        n = 0
        now = self.now()
        for b in self.repo.list_bookings((BookingStatus.HELD,)):
            if b.hold_expires_at is not None and now >= b.hold_expires_at:
                key = f"expire:{b.id}:v{b.version}"
                if self.repo.find_event(key):
                    continue
                before = b.status.value
                nb = b.model_copy(update={"status": BookingStatus.RELEASED, "version": b.version + 1, "updated_at": now})
                self.repo.update_booking(nb, b.version)
                self._event(key, "hold_expired", b.inquiry_id, actor="system", booking_id=b.id, before=before,
                            after={"status": "released", "tables_released": b.table_ids},
                            reason=f"hold expired at {b.hold_expires_at.isoformat()}", booking_version=nb.version)
                if b.inquiry_id:
                    inq = self.repo.get_inquiry(b.inquiry_id)
                    if inq:
                        inq = inq.model_copy(update={"record_version": inq.record_version + 1, "updated_at": now})
                        self.repo.update_inquiry(inq)
                        self._refresh_state(inq.id)
                n += 1
        return n

    # ================================================================ loading
    def _assessment_input(self, inq: Inquiry, facts: Facts, booking: Booking | None, obs: list[Observation],
                          msgs: list[Message], interps: list[Interpretation], proposals: list[Proposal],
                          events: list[Event]) -> AssessmentInput:
        inbound = [m for m in msgs if m.direction == Direction.INBOUND]
        latest_seq = max((m.seq for m in inbound), default=0)
        open_ids = {m.id for m in inbound if m.seq > inq.handled_seq}
        intents: set[str] = set()
        for it in interps:
            if set(it.message_ids) & open_ids:
                intents |= set(it.intents)
        open_change = any(o.field in MATERIAL_FIELDS and o.seq > inq.handled_obs_seq for o in obs)
        return AssessmentInput(
            cfg=self.cfg, inquiry=inq, facts=facts, booking=booking, all_bookings=self.repo.list_bookings(),
            interpretations=[i for i in interps if set(i.message_ids) & open_ids] or interps[-1:],
            open_intents=intents, proposals=proposals, events=events, now=self.now(),
            latest_inbound_seq=latest_seq, open_material_change=open_change,
        )

    def load(self, inquiry_id: str) -> InquiryView:
        inq = self._inq(inquiry_id)
        msgs = self.repo.messages(inquiry_id)
        obs = self.repo.observations(inquiry_id)
        facts = resolve(self.cfg, obs)
        booking = self.repo.get_booking(inq.booking_id) if inq.booking_id else None
        interps = self.repo.interpretations(inquiry_id)
        proposals = self.repo.proposals(inquiry_id)
        events = self.repo.events(inquiry_id)
        a = assess(self._assessment_input(inq, facts, booking, obs, msgs, interps, proposals, events))
        return InquiryView(inq, msgs, obs, facts, booking, a, proposals, self.repo.drafts(inquiry_id), events,
                           interps, self.now())

    def queue(self) -> list[InquiryView]:
        from ..rules.assessment import URGENCY_RANK

        views = [self.load(i.id) for i in self.repo.list_inquiries()]
        far = datetime.max.replace(tzinfo=self.now().tzinfo)
        views.sort(key=lambda v: (URGENCY_RANK[v.assessment.urgency], v.assessment.deadline or far,
                                  v.inquiry.created_at, v.inquiry.id))
        return views

    def _refresh_state(self, inquiry_id: str) -> InquiryState:
        v = self.load(inquiry_id)
        inq = v.inquiry
        new_state = v.assessment.derived_state
        if inq.state in STICKY_STATES and new_state == inq.state:
            return inq.state
        if new_state != inq.state:
            self._event("state:" + uuid.uuid4().hex, "inquiry_state_changed", inq.id, actor="system",
                        before=inq.state.value, after={"state": new_state.value},
                        reason=v.assessment.next_action.value, record_version=inq.record_version)
            self.repo.update_inquiry(inq.model_copy(update={"state": new_state, "updated_at": self.now()}))
        return new_state

    # ================================================================ inquiries & messages
    def create_inquiry(self, guest_label: str, text: str, received_at: datetime | None, key: str,
                       source: MessageSource = MessageSource.PASTED, title: str = "",
                       inquiry_id: str | None = None) -> CommandResult:
        label = (guest_label or "").strip()
        if not label:
            return CommandResult(ok=False, code="validation", message="Guest label is required (synthetic or initials).")

        def fn():
            iid = inquiry_id or self.db.next_id("inquiry", "INQ-")
            now = self.now()
            inq = Inquiry(id=iid, guest_label=label[:80], title=title[:120], state=InquiryState.NEW, created_at=now,
                          updated_at=now)
            self.repo.insert_inquiry(inq)
            self._event(key, "inquiry_created", iid, after={"inquiry_id": iid, "guest_label": label})
            if text and text.strip():
                self._add_message_tx(iid, text, received_at or now, source, key + ":m")
            return CommandResult(ok=True, message=f"Created {iid}", data={"inquiry_id": iid})

        return self._run(key, fn)

    def add_message(self, inquiry_id: str, text: str, received_at: datetime | None, key: str,
                    source: MessageSource = MessageSource.PASTED) -> CommandResult:
        return self._run(key, lambda: self._add_message_tx(inquiry_id, text, received_at or self.now(), source, key))

    def _add_message_tx(self, inquiry_id: str, text: str, received_at: datetime, source: MessageSource,
                        key: str) -> CommandResult:
        if not isinstance(text, str) or not text.strip():
            raise DomainError("validation", "Message text is empty.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise DomainError("validation", f"Message exceeds {MAX_MESSAGE_CHARS} characters; paste a shorter excerpt.")
        if received_at.tzinfo is None:
            raise DomainError("validation", "Message timestamp must include a timezone.")
        inq = self._inq(inquiry_id)
        seq = self.repo.message_count(inquiry_id) + 1
        mid = f"{inquiry_id}-M{seq}"
        m = Message(id=mid, inquiry_id=inquiry_id, seq=seq, direction=Direction.INBOUND, text=text,
                    received_at=received_at, source=source)
        self.repo.insert_message(m)
        self.repo.update_inquiry(inq.model_copy(update={"updated_at": self.now()}))
        if self.repo.find_event(key) is None:
            self._event(key, "message_received", inquiry_id, actor="guest",
                        after={"message_id": mid, "source": source.value, "chars": len(text)})
        self._refresh_state(inquiry_id)
        return CommandResult(ok=True, message=f"Added message {mid}", data={"message_id": mid})

    # ================================================================ interpretation
    def pending_message_ids(self, inquiry_id: str) -> list[str]:
        done = {mid for it in self.repo.interpretations(inquiry_id) if it.status != "failed" for mid in it.message_ids}
        return [m.id for m in self.repo.messages(inquiry_id) if m.direction == Direction.INBOUND and m.id not in done]

    def interpret(self, inquiry_id: str, key: str | None = None) -> CommandResult:
        """Run the provider over messages not yet interpreted.

        The provider call happens *outside* the database transaction; nothing is
        written unless the output validates, so a model failure cannot corrupt
        facts or bookings.
        """
        pending = self.pending_message_ids(inquiry_id)
        if not pending:
            return CommandResult(ok=True, message="No new messages to interpret.")
        key = key or f"interpret:{inquiry_id}:{','.join(pending)}:{self.provider.mode}"
        prior = self.repo.find_event(key)
        if prior is not None:
            return CommandResult(ok=True, duplicate=True, message="Interpretation already recorded.")
        msgs = self.repo.messages(inquiry_id)
        inputs = [MessageInput(id=m.id, text=m.text, received_at=m.received_at, is_new=m.id in pending)
                  for m in msgs if m.direction == Direction.INBOUND]
        ctx = InterpretContext(timezone=self.cfg.restaurant.timezone, restaurant_name=self.cfg.restaurant.name,
                               table_ids=[t.id for t in self.cfg.tables], now=self.now())
        try:
            result = self.provider.interpret(inputs, ctx)
        except Exception as exc:  # provider bugs must never break the workbench
            from ..providers.base import InterpretationResult

            result = InterpretationResult(provider_mode=self.provider.mode, status="failed",
                                          error=f"{type(exc).__name__}: {str(exc)[:200]}")
        if result.status != "failed":
            result = validate_evidence(result, inputs)

        def fn():
            inq = self._inq(inquiry_id)
            before = resolve(self.cfg, self.repo.observations(inquiry_id))
            iid = "INT-" + uuid.uuid4().hex[:10]
            it = Interpretation(
                id=iid, inquiry_id=inquiry_id, message_ids=pending, provider_mode=result.provider_mode,
                model=result.model, status=result.status, intents=result.intents, ambiguities=result.ambiguities,
                uninterpreted=result.uninterpreted, error=result.error, raw_output=result.raw_output,
                latency_ms=result.latency_ms, usage={**result.usage, "attempts": result.attempts,
                                                     "rejected_facts": result.rejected_facts},
                created_at=self.now(),
            )
            self.repo.insert_interpretation(it)
            seq = self.repo.next_obs_seq(inquiry_id)
            received = {m.id: m.received_at for m in msgs}
            for f in result.facts:
                self.repo.insert_observation(Observation(
                    id="OBS-" + uuid.uuid4().hex[:10], inquiry_id=inquiry_id, seq=seq, field=f.field, value=f.value,
                    source_type="message", message_id=f.message_id, span_start=f.span_start, span_end=f.span_end,
                    quote=f.quote, status=FieldStatus(f.status), note=f.note, provider_mode=result.provider_mode,
                    interpretation_id=iid, observed_at=received.get(f.message_id, self.now()),
                ))
                seq += 1
            etype = "interpretation_failed" if result.status == "failed" else "interpretation_recorded"
            self._event(key, etype, inquiry_id, actor="provider",
                        after={"interpretation_id": iid, "status": result.status, "facts": len(result.facts),
                               "rejected": len(result.rejected_facts), "provider": result.provider_mode},
                        reason=result.error, record_version=inq.record_version)
            self._after_fact_change(inq, before, "new guest message")
            self._refresh_state(inquiry_id)
            return CommandResult(ok=result.status != "failed",
                                 message=(f"Interpretation {result.status}: {len(result.facts)} facts"
                                          + (f", {len(result.rejected_facts)} rejected" if result.rejected_facts else "")
                                          + (f" - {result.error}" if result.error else "")),
                                 code=None if result.status != "failed" else "provider_failed",
                                 data={"interpretation_id": iid, "status": result.status})

        return self._run(key, fn)

    # ================================================================ facts
    def set_fact(self, inquiry_id: str, field_name: str, value: Any, reason: str | None, key: str,
                 expected_record_version: int | None = None) -> CommandResult:
        def fn():
            inq = self._inq(inquiry_id)
            self._check_version(inq, expected_record_version)
            try:
                fname = FieldName(field_name)
                v = normalize_value(fname, value)
            except ValueError as exc:
                raise DomainError("validation", f"{field_name}: {exc}") from exc
            before = resolve(self.cfg, self.repo.observations(inquiry_id))
            old = before.get(fname)
            self.repo.insert_observation(Observation(
                id="OBS-" + uuid.uuid4().hex[:10], inquiry_id=inquiry_id, seq=self.repo.next_obs_seq(inquiry_id),
                field=fname, value=v, source_type="operator", status=FieldStatus.OPERATOR_CONFIRMED,
                note=self._reason(reason, required=False), observed_at=self.now(),
            ))
            self._event(key, "fact_set_by_operator", inquiry_id, before={"value": old.value, "state": old.state},
                        after={"field": fname.value, "value": v}, reason=reason, record_version=inq.record_version)
            self._after_fact_change(inq, before, f"operator set {fname.value}")
            self._refresh_state(inquiry_id)
            return CommandResult(ok=True, message=f"{fname.value} set to {v!r} (operator-confirmed)")

        return self._run(key, fn)

    def confirm_fact(self, inquiry_id: str, field_name: str, key: str, expected_record_version: int | None = None,
                     reason: str | None = None) -> CommandResult:
        v = self.load(inquiry_id)
        fv = v.facts.get(FieldName(field_name))
        if fv.value is None:
            return CommandResult(ok=False, code="validation", message="No candidate value to confirm.")
        return self.set_fact(inquiry_id, field_name, fv.value, reason or "operator confirmed candidate", key,
                             expected_record_version)

    def revert_facts_to_booking(self, inquiry_id: str, reason: str, key: str) -> CommandResult:
        def fn():
            inq = self._inq(inquiry_id)
            b = self.repo.get_booking(inq.booking_id) if inq.booking_id else None
            if b is None or b.status not in ACTIVE_BOOKING_STATUSES:
                raise DomainError("no_booking", "No active booking to revert to.")
            r = self._reason(reason)
            before = resolve(self.cfg, self.repo.observations(inquiry_id))
            local = b.start.astimezone(self.cfg.tz)
            vals = {FieldName.PARTY_SIZE: b.party_size, FieldName.REQUESTED_DATE: local.date().isoformat(),
                    FieldName.REQUESTED_TIME: local.strftime("%H:%M")}
            seq = self.repo.next_obs_seq(inquiry_id)
            for f, val in vals.items():
                self.repo.insert_observation(Observation(
                    id="OBS-" + uuid.uuid4().hex[:10], inquiry_id=inquiry_id, seq=seq, field=f, value=val,
                    source_type="operator", status=FieldStatus.OPERATOR_CONFIRMED,
                    note=f"reverted to booking {b.id}: {r}", observed_at=self.now()))
                seq += 1
            for f in (FieldName.PREFERRED_TABLE, FieldName.PREFERRED_AREA):
                if before.get(f).value is not None:
                    self.repo.insert_observation(Observation(
                        id="OBS-" + uuid.uuid4().hex[:10], inquiry_id=inquiry_id, seq=seq, field=f,
                        value=b.table_ids[0] if f == FieldName.PREFERRED_TABLE else self.cfg.table(b.table_ids[0]).area,
                        source_type="operator", status=FieldStatus.OPERATOR_CONFIRMED,
                        note=f"reverted to booking {b.id}: {r}", observed_at=self.now()))
                    seq += 1
            self._event(key, "facts_reverted_to_booking", inquiry_id, booking_id=b.id, reason=r)
            inq = self._after_fact_change(inq, before, "facts reverted to booking")
            self._mark_handled(inq)
            self._refresh_state(inquiry_id)
            return CommandResult(ok=True, message=f"Facts reverted to booking {b.id}.")

        return self._run(key, fn)

    def _after_fact_change(self, inq: Inquiry, before: Facts, why: str) -> Inquiry:
        after = resolve(self.cfg, self.repo.observations(inq.id))
        changed = [f.value for f in MATERIAL_FIELDS
                   if (before.get(f).value, before.get(f).state) != (after.get(f).value, after.get(f).state)]
        if before.dining_start != after.dining_start or before.dining_end != after.dining_end:
            changed.append("interval")
        if not changed:
            return inq
        inq = inq.model_copy(update={"record_version": inq.record_version + 1, "updated_at": self.now()})
        self.repo.update_inquiry(inq)
        self._invalidate(inq, f"{why}: changed {', '.join(sorted(set(changed)))}")
        return inq

    def _invalidate(self, inq: Inquiry, reason: str) -> None:
        for p in self.repo.proposals(inq.id):
            if p.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED):
                self.repo.set_proposal_status(p.id, ProposalStatus.STALE.value, reason)
                self._event("stale:" + uuid.uuid4().hex, "proposal_stale", inq.id, actor="system", proposal_id=p.id,
                            before=p.status.value, after={"status": "stale"}, reason=reason,
                            record_version=inq.record_version)
        for d in self.repo.drafts(inq.id):
            if d.status == "approved" and d.approved_record_version != inq.record_version:
                self._event("draftstale:" + uuid.uuid4().hex, "draft_approval_stale", inq.id, actor="system",
                            before="approved", after={"draft_id": d.id}, reason=reason,
                            record_version=inq.record_version)

    def _mark_handled(self, inq: Inquiry) -> Inquiry:
        msgs = self.repo.messages(inq.id)
        obs_seq = self.repo.next_obs_seq(inq.id) - 1
        inq = inq.model_copy(update={"handled_seq": max((m.seq for m in msgs), default=0),
                                     "handled_obs_seq": obs_seq, "updated_at": self.now()})
        self.repo.update_inquiry(inq)
        return inq

    def _bump(self, inq: Inquiry, reason: str) -> Inquiry:
        inq = inq.model_copy(update={"record_version": inq.record_version + 1, "updated_at": self.now()})
        self.repo.update_inquiry(inq)
        self._invalidate(inq, reason)
        return inq

    # ================================================================ proposals
    def propose(self, inquiry_id: str, key: str, unit_id: str | None = None,
                start_override: datetime | None = None) -> CommandResult:
        """Create a proposal for the current facts (or a checked alternative time)."""

        def fn():
            v = self.load(inquiry_id)
            inq = v.inquiry
            a = v.assessment
            active = v.booking if v.booking and v.booking.status in ACTIVE_BOOKING_STATUSES and (
                v.booking.status == BookingStatus.CONFIRMED or hold_is_active(v.booking, self.now())) else None
            req = build_request(self.cfg, v.facts, exclude_booking_id=active.id if active else None,
                                current_table_ids=tuple(active.table_ids) if active else ())
            if req is None:
                raise DomainError("insufficient", "Party size, date and start time must be known before proposing.")
            if any(r.rule_id == "R-MAXPARTY" for r in a.blockers):
                raise DomainError("blocked", "Party exceeds the main-restaurant maximum; escalate instead.")
            if start_override is not None:
                dur = req.end - req.start
                req.start, req.end = start_override, start_override + dur
            av = evaluate(self.cfg, req, self.repo.list_bookings(), self.now())
            if unit_id is not None:
                rej = next((o for o in av.rejected if o.unit_id == unit_id), None)
                if rej is not None:
                    raise DomainError("unavailable", f"{unit_id} cannot be used: " + "; ".join(rej.reasons))
            if not av.feasible:
                raise DomainError("unavailable", "No feasible option at that time: " + "; ".join(
                    av.interval_errors or [f"{o.unit_id}: {o.reasons[0]}" for o in av.rejected[:3]]))
            opt = av.best() if unit_id is None else next((o for o in av.options if o.unit_id == unit_id), None)
            if opt is None:
                raise DomainError("unavailable", f"Unknown table or grouping {unit_id}.")
            for p in v.proposals:  # one live proposal at a time
                if p.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED, ProposalStatus.STALE):
                    self.repo.set_proposal_status(p.id, ProposalStatus.REJECTED.value, "superseded by new proposal")
            required = []
            if a.hold_needs_operator_deadline:
                required.append("operator hold deadline (short notice)")
            required += a.confirm_gaps
            pid = self.db.next_id("proposal", "P-")
            p = Proposal(
                id=pid, inquiry_id=inquiry_id,
                kind=ProposalKind.MODIFICATION if active else ProposalKind.NEW_ALLOCATION,
                source_record_version=inq.record_version, policy_version=self.cfg.policy_version,
                booking_id=active.id if active else None, booking_version=active.version if active else None,
                option=opt, party_size=req.party_size, rule_results=a.blockers + a.reviews + a.advisories,
                required_decisions=required, status=ProposalStatus.PROPOSED, created_at=self.now(),
            )
            self.repo.insert_proposal(p)
            self._event(key, "proposal_created", inquiry_id, proposal_id=pid,
                        after={"proposal_id": pid, "unit": opt.unit_id, "tables": opt.table_ids,
                               "start": opt.start.isoformat(), "end": opt.end.isoformat(), "kind": p.kind.value},
                        record_version=inq.record_version)
            return CommandResult(ok=True, message=(f"Proposal {pid}: {opt.unit_id}"
                                          + (f" (tables {'+'.join(opt.table_ids)})" if len(opt.table_ids) > 1 else "")
                                          + f", {opt.start.astimezone(self.cfg.tz):%a %b %d %H:%M}. Approve it "
                                          "before creating a hold or confirmation."),
                                 data={"proposal_id": pid})

        return self._run(key, fn)

    def approve_proposal(self, proposal_id: str, key: str, reason: str | None = None) -> CommandResult:
        def fn():
            p = self.repo.get_proposal(proposal_id)
            if p is None:
                raise DomainError("not_found", f"proposal {proposal_id} not found")
            inq = self._inq(p.inquiry_id)
            if p.status != ProposalStatus.PROPOSED:
                raise DomainError("invalid_state", f"Proposal {p.id} is {p.status.value}; only proposed can be approved.")
            if p.source_record_version != inq.record_version or p.policy_version != self.cfg.policy_version:
                self.repo.set_proposal_status(p.id, ProposalStatus.STALE.value, "facts or policy changed")
                raise DomainError("stale", "Proposal is stale; recheck availability.")
            self.repo.set_proposal_status(p.id, ProposalStatus.APPROVED.value, None, approved_at=self.now(),
                                          approval_reason=self._reason(reason, required=False))
            self._event(key, "proposal_approved", inq.id, proposal_id=p.id, before="proposed",
                        after={"status": "approved", "record_version": inq.record_version}, reason=reason,
                        record_version=inq.record_version)
            self._refresh_state(inq.id)
            return CommandResult(ok=True, message=f"Proposal {p.id} approved for record version {inq.record_version}.")

        return self._run(key, fn)

    def _require_current_approved(self, proposal_id: str) -> tuple[Proposal, Inquiry]:
        p = self.repo.get_proposal(proposal_id)
        if p is None:
            raise DomainError("not_found", f"proposal {proposal_id} not found")
        inq = self._inq(p.inquiry_id)
        if p.status == ProposalStatus.COMMITTED:
            raise DomainError("already_committed", f"Proposal {p.id} was already committed.")
        if p.status != ProposalStatus.APPROVED:
            raise DomainError("not_approved", f"Proposal {p.id} is {p.status.value}; approve a current proposal first.")
        if p.source_record_version != inq.record_version:
            raise _Reject(p, inq, "stale", "facts changed since approval")
        if p.policy_version != self.cfg.policy_version:
            raise _Reject(p, inq, "stale", "policy version changed since approval")
        return p, inq

    def _recheck_option(self, p: Proposal, exclude_booking_id: str | None) -> list[str]:
        from ..rules.availability import SeatingRequest

        facts = resolve(self.cfg, self.repo.observations(p.inquiry_id))
        step_free = facts.value(FieldName.ACCESSIBILITY) == "step_free_required"
        req = SeatingRequest(party_size=p.party_size, start=p.option.start, end=p.option.end,
                             step_free_required=step_free, exclude_booking_id=exclude_booking_id)
        av = evaluate(self.cfg, req, self.repo.list_bookings(), self.now())
        match = next((o for o in av.options if o.unit_id == p.option.unit_id), None)
        if match is not None:
            return []
        rej = next((o for o in av.rejected if o.unit_id == p.option.unit_id), None)
        return rej.reasons if rej else ["option no longer evaluated"]

    def _commit_guard(self, key: str, fn) -> CommandResult:
        """Like _run, but a _Reject records the rejection (and commits it) instead of rolling back."""
        try:
            return self._run(key, fn)
        except _Reject as rj:
            with self.db.transaction():
                if self.repo.find_event(key) is None:
                    self.repo.set_proposal_status(rj.proposal.id, ProposalStatus.STALE.value
                                                  if rj.kind == "stale" else ProposalStatus.REJECTED.value, rj.reason)
                    self._event(key, "proposal_rejected_at_commit", rj.inquiry.id, actor="system",
                                proposal_id=rj.proposal.id, after={"why": rj.reason}, reason=rj.reason,
                                record_version=rj.inquiry.record_version)
                    self._refresh_state(rj.inquiry.id)
            return CommandResult(ok=False, code=f"rejected_{rj.kind}",
                                 message=f"Not committed: {rj.reason}. Nothing was changed; recheck availability.")

    def create_hold(self, proposal_id: str, key: str, expires_at: datetime | None = None) -> CommandResult:
        def fn():
            p, inq = self._require_current_approved(proposal_id)
            if p.kind != ProposalKind.NEW_ALLOCATION:
                raise DomainError("invalid_state", "Use the modification commit for an existing booking.")
            existing = self.repo.get_booking(inq.booking_id) if inq.booking_id else None
            if existing and existing.status in ACTIVE_BOOKING_STATUSES and (
                    existing.status == BookingStatus.CONFIRMED or hold_is_active(existing, self.now())):
                raise DomainError("duplicate", f"{inq.id} already has active booking {existing.id}.")
            reasons = self._recheck_option(p, None)
            if reasons:
                raise _Reject(p, inq, "unavailable", "; ".join(reasons))
            now = self.now()
            pol = self.cfg.policies
            default = now + timedelta(hours=pol.hold_hours)
            exp = expires_at
            if exp is None:
                if pol.hold_expiry_must_precede_dining_start and default >= p.option.start:
                    raise DomainError("deadline_required", "Short-notice hold: enter a hold deadline before the "
                                      "dining start.")
                exp = default
            if exp <= now:
                raise DomainError("validation", "Hold deadline must be in the future.")
            if pol.hold_expiry_must_precede_dining_start and exp >= p.option.start:
                raise DomainError("validation", "Hold deadline must precede the dining start.")
            facts = resolve(self.cfg, self.repo.observations(inq.id))
            acc = facts.get(FieldName.ACCESSIBILITY)
            if acc.known and acc.value == "step_free_required" and not p.option.step_free:
                raise DomainError("blocked", "Stairs-only allocation conflicts with the step-free requirement.")
            bid = self.db.next_id("booking", "B-A")
            b = Booking(id=bid, inquiry_id=inq.id, guest_label=inq.guest_label, status=BookingStatus.HELD,
                        table_ids=p.option.table_ids, party_size=p.party_size, start=p.option.start, end=p.option.end,
                        hold_expires_at=exp, created_at=now, updated_at=now)
            self._transition(BookingStatus.NONE, BookingStatus.HELD)
            self.repo.insert_booking(b)
            self.repo.set_proposal_status(p.id, ProposalStatus.COMMITTED.value, "hold created")
            inq = inq.model_copy(update={"booking_id": bid})
            inq = self._bump(inq, "hold created")
            self._event(key, "hold_created", inq.id, booking_id=bid, proposal_id=p.id, before="none",
                        after={"booking_id": bid, "status": "held", "tables": b.table_ids,
                               "expires_at": exp.isoformat()},
                        record_version=inq.record_version, booking_version=b.version)
            self._mark_handled(inq)
            self._refresh_state(inq.id)
            return CommandResult(ok=True, message=f"Demo hold {bid} created on {', '.join(b.table_ids)} until "
                                 f"{exp.astimezone(self.cfg.tz):%Y-%m-%d %H:%M}.", data={"booking_id": bid})

        return self._commit_guard(key, fn)

    def confirm(self, inquiry_id: str, key: str, proposal_id: str | None = None,
                expected_record_version: int | None = None) -> CommandResult:
        """Record demo confirmation of a held booking, or of an approved new proposal."""

        def fn():
            v = self.load(inquiry_id)
            inq = v.inquiry
            self._check_version(inq, expected_record_version)
            a = v.assessment
            gaps = list(a.confirm_gaps)
            blockers = [r for r in a.blockers if r.rule_id not in ("R-STALE",)]
            b = v.booking
            if b is not None and b.status == BookingStatus.HELD and hold_is_active(b, self.now()):
                if a.requested_change:
                    raise DomainError("change_pending", "A change is pending; commit or resolve it before confirming.")
                if gaps or blockers:
                    raise DomainError("not_ready", "Cannot confirm yet: " + ", ".join(
                        gaps + [r.rule_id for r in blockers]))
                reasons = self._recheck_held(b)
                if reasons:
                    raise DomainError("unavailable", "; ".join(reasons))
                self._transition(b.status, BookingStatus.CONFIRMED)
                nb = b.model_copy(update={"status": BookingStatus.CONFIRMED, "hold_expires_at": None,
                                          "version": b.version + 1, "updated_at": self.now()})
                self.repo.update_booking(nb, b.version)
                inq = self._bump(inq, "booking confirmed")
                self._event(key, "booking_confirmed", inq.id, booking_id=b.id, before="held",
                            after={"booking_id": b.id, "status": "confirmed"}, record_version=inq.record_version,
                            booking_version=nb.version)
                self._mark_handled(inq)
                self._refresh_state(inq.id)
                return CommandResult(ok=True, message=f"Demo confirmation recorded for {b.id}.",
                                     data={"booking_id": b.id})
            if b is not None and b.status == BookingStatus.CONFIRMED:
                raise DomainError("duplicate", f"{b.id} is already confirmed.")
            if proposal_id is None:
                raise DomainError("not_approved", "Approve a proposal first.")
            p, inq2 = self._require_current_approved(proposal_id)
            if gaps or blockers:
                raise DomainError("not_ready", "Cannot confirm yet: " + ", ".join(gaps + [r.rule_id for r in blockers]))
            reasons = self._recheck_option(p, None)
            if reasons:
                raise _Reject(p, inq2, "unavailable", "; ".join(reasons))
            now = self.now()
            bid = self.db.next_id("booking", "B-A")
            nb = Booking(id=bid, inquiry_id=inq.id, guest_label=inq.guest_label, status=BookingStatus.CONFIRMED,
                         table_ids=p.option.table_ids, party_size=p.party_size, start=p.option.start,
                         end=p.option.end, created_at=now, updated_at=now)
            self._transition(BookingStatus.NONE, BookingStatus.CONFIRMED)
            self.repo.insert_booking(nb)
            self.repo.set_proposal_status(p.id, ProposalStatus.COMMITTED.value, "confirmed")
            inq = self._bump(inq.model_copy(update={"booking_id": bid}), "booking confirmed")
            self._event(key, "booking_confirmed", inq.id, booking_id=bid, proposal_id=p.id, before="none",
                        after={"booking_id": bid, "status": "confirmed", "tables": nb.table_ids},
                        record_version=inq.record_version, booking_version=1)
            self._mark_handled(inq)
            self._refresh_state(inq.id)
            return CommandResult(ok=True, message=f"Demo confirmation recorded: {bid}.", data={"booking_id": bid})

        return self._commit_guard(key, fn)

    def _recheck_held(self, b: Booking) -> list[str]:
        from ..rules.availability import SeatingRequest

        facts = resolve(self.cfg, self.repo.observations(b.inquiry_id)) if b.inquiry_id else None
        step_free = bool(facts and facts.value(FieldName.ACCESSIBILITY) == "step_free_required")
        req = SeatingRequest(party_size=b.party_size, start=b.start, end=b.end, step_free_required=step_free,
                             exclude_booking_id=b.id)
        av = evaluate(self.cfg, req, self.repo.list_bookings(), self.now(), check_past=False)
        unit = next((o for o in av.options + av.rejected if sorted(o.table_ids) == sorted(b.table_ids)), None)
        if unit is None:
            return ["allocation no longer valid"]
        return unit.reasons

    def commit_modification(self, proposal_id: str, key: str) -> CommandResult:
        """Atomically move an existing booking to the approved allocation.

        The original allocation stays untouched unless the new one validates in
        the same transaction.
        """

        def fn():
            p, inq = self._require_current_approved(proposal_id)
            if p.kind != ProposalKind.MODIFICATION or not p.booking_id:
                raise DomainError("invalid_state", "Not a modification proposal.")
            b = self.repo.get_booking(p.booking_id)
            if b is None or b.status not in ACTIVE_BOOKING_STATUSES:
                raise DomainError("invalid_state", "Booking is no longer active.")
            if b.version != p.booking_version:
                raise _Reject(p, inq, "stale", f"booking {b.id} changed since the proposal")
            reasons = self._recheck_option(p, b.id)
            if reasons:
                raise _Reject(p, inq, "unavailable", "; ".join(reasons))
            before = {"tables": b.table_ids, "start": b.start.isoformat(), "end": b.end.isoformat(),
                      "party_size": b.party_size}
            nb = b.model_copy(update={"table_ids": p.option.table_ids, "start": p.option.start, "end": p.option.end,
                                      "party_size": p.party_size, "version": b.version + 1, "updated_at": self.now()})
            self.repo.update_booking(nb, b.version)
            self.repo.set_proposal_status(p.id, ProposalStatus.COMMITTED.value, "modification committed")
            inq = self._bump(inq, "booking modified")
            self._event(key, "booking_modified", inq.id, booking_id=b.id, proposal_id=p.id, before=before,
                        after={"tables": nb.table_ids, "start": nb.start.isoformat(), "end": nb.end.isoformat(),
                               "party_size": nb.party_size, "status": nb.status.value},
                        record_version=inq.record_version, booking_version=nb.version)
            self._mark_handled(inq)
            self._refresh_state(inq.id)
            return CommandResult(ok=True, message=f"{b.id} moved to {', '.join(nb.table_ids)} "
                                 f"{nb.start.astimezone(self.cfg.tz):%Y-%m-%d %H:%M}.")

        return self._commit_guard(key, fn)

    # ================================================================ direct decisions
    def _transition(self, frm: BookingStatus, to: BookingStatus) -> None:
        if to not in ALLOWED_TRANSITIONS[frm]:
            raise DomainError("illegal_transition", f"Booking cannot move from {frm.value} to {to.value}.")

    def cancel_booking(self, inquiry_id: str, reason: str, key: str,
                       expected_record_version: int | None = None) -> CommandResult:
        def fn():
            inq = self._inq(inquiry_id)
            self._check_version(inq, expected_record_version)
            r = self._reason(reason)
            b = self.repo.get_booking(inq.booking_id) if inq.booking_id else None
            if b is None:
                raise DomainError("no_booking", "No booking linked to this inquiry.")
            self._transition(b.status, BookingStatus.CANCELLED)
            nb = b.model_copy(update={"status": BookingStatus.CANCELLED, "version": b.version + 1,
                                      "updated_at": self.now()})
            self.repo.update_booking(nb, b.version)
            inq = self._bump(inq, "booking cancelled")
            self._event(key, "booking_cancelled", inq.id, booking_id=b.id, before=b.status.value,
                        after={"status": "cancelled", "tables_released": b.table_ids}, reason=r,
                        record_version=inq.record_version, booking_version=nb.version)
            self._mark_handled(inq)
            self._refresh_state(inq.id)
            return CommandResult(ok=True, message=f"Demo cancellation recorded for {b.id}; tables released.")

        return self._run(key, fn)

    def release_hold(self, inquiry_id: str, reason: str, key: str) -> CommandResult:
        def fn():
            inq = self._inq(inquiry_id)
            r = self._reason(reason)
            b = self.repo.get_booking(inq.booking_id) if inq.booking_id else None
            if b is None or b.status != BookingStatus.HELD:
                raise DomainError("invalid_state", "No active hold to release.")
            self._transition(b.status, BookingStatus.RELEASED)
            nb = b.model_copy(update={"status": BookingStatus.RELEASED, "version": b.version + 1,
                                      "updated_at": self.now()})
            self.repo.update_booking(nb, b.version)
            inq = self._bump(inq, "hold released")
            self._event(key, "hold_released", inq.id, booking_id=b.id, before="held",
                        after={"status": "released"}, reason=r, record_version=inq.record_version,
                        booking_version=nb.version)
            self._mark_handled(inq)
            self._refresh_state(inq.id)
            return CommandResult(ok=True, message=f"Hold {b.id} released.")

        return self._run(key, fn)

    def _sticky(self, inquiry_id: str, state: InquiryState, event_type: str, reason: str | None, key: str,
                require_reason: bool = True, extra: dict | None = None) -> CommandResult:
        def fn():
            inq = self._inq(inquiry_id)
            r = self._reason(reason, required=require_reason)
            msgs = self.repo.messages(inquiry_id)
            latest = max((m.seq for m in msgs), default=0)
            before = inq.state.value
            inq = inq.model_copy(update={"state": state, "state_set_seq": latest, "updated_at": self.now()})
            self.repo.update_inquiry(inq)
            inq = self._mark_handled(inq)
            self._event(key, event_type, inq.id, before=before, after={"state": state.value, **(extra or {})},
                        reason=r, record_version=inq.record_version)
            return CommandResult(ok=True, message=f"{inq.id}: {event_type.replace('_', ' ')}.")

        return self._run(key, fn)

    def decline(self, inquiry_id: str, reason: str, key: str) -> CommandResult:
        v = self.load(inquiry_id)
        if v.booking and v.booking.status in ACTIVE_BOOKING_STATUSES:
            return CommandResult(ok=False, code="invalid_state",
                                 message="This inquiry has an active booking; cancel or release it instead of declining.")

        def fn():
            inq = self._inq(inquiry_id)
            r = self._reason(reason)
            msgs = self.repo.messages(inquiry_id)
            inq = inq.model_copy(update={"state": InquiryState.RESOLVED,
                                         "state_set_seq": max((m.seq for m in msgs), default=0)})
            self.repo.update_inquiry(inq)
            inq = self._bump(inq, "declined")
            self._event(key, "inquiry_declined", inq.id, before=v.inquiry.state.value, after={"state": "resolved"},
                        reason=r, record_version=inq.record_version)
            self._mark_handled(inq)
            return CommandResult(ok=True, message=f"{inq.id} declined (no booking made).")

        return self._run(key, fn)

    def escalate(self, inquiry_id: str, reason: str, key: str) -> CommandResult:
        return self._sticky(inquiry_id, InquiryState.ESCALATED, "inquiry_escalated", reason, key,
                            extra={"note": "private-events review; availability not checked by this system"})

    def mark_awaiting_guest(self, inquiry_id: str, note: str | None, key: str) -> CommandResult:
        """Operator reports that a reply was sent outside this app (not verified)."""
        return self._sticky(inquiry_id, InquiryState.AWAITING_GUEST, "awaiting_guest_marked", note, key,
                            require_reason=False, extra={"assertion": "operator-reported; not verified"})

    def close(self, inquiry_id: str, reason: str, key: str) -> CommandResult:
        return self._sticky(inquiry_id, InquiryState.CLOSED, "inquiry_closed", reason, key)

    def reopen(self, inquiry_id: str, reason: str, key: str) -> CommandResult:
        def fn():
            inq = self._inq(inquiry_id)
            r = self._reason(reason)
            before = inq.state.value
            inq = inq.model_copy(update={"state": InquiryState.NEEDS_REVIEW, "state_set_seq": -1,
                                         "handled_seq": 0, "updated_at": self.now()})
            self.repo.update_inquiry(inq)
            self._event(key, "inquiry_reopened", inq.id, before=before, after={"state": "needs_review"}, reason=r)
            self._refresh_state(inq.id)
            return CommandResult(ok=True, message=f"{inq.id} reopened.")

        return self._run(key, fn)

    def record_external_action(self, inquiry_id: str, description: str, key: str) -> CommandResult:
        """An operator assertion about something done outside the app. Changes no booking."""

        def fn():
            inq = self._inq(inquiry_id)
            d = self._reason(description)
            self._event(key, "external_action_reported", inq.id, after={
                "description": d, "verification": "operator assertion only; not synchronized or verified"})
            return CommandResult(ok=True, message="Recorded as an operator-reported external action (unverified).")

        return self._run(key, fn)

    def acknowledge_allergy(self, inquiry_id: str, note: str, key: str) -> CommandResult:
        def fn():
            inq = self._inq(inquiry_id)
            facts = resolve(self.cfg, self.repo.observations(inquiry_id))
            fv = facts.get(FieldName.ALLERGIES)
            if not fv.known or fv.value == "none":
                raise DomainError("validation", "No allergy recorded to acknowledge.")
            r = self._reason(note)
            self._event(key, "allergy_acknowledged", inq.id, after={
                "value": fv.value, "note": "acknowledged for follow-up; not a guarantee of accommodation"}, reason=r)
            self._refresh_state(inq.id)
            return CommandResult(ok=True, message="Allergy acknowledgment recorded (no accommodation guarantee).")

        return self._run(key, fn)

    def approve_exception(self, inquiry_id: str, rule_id: str, reason: str, key: str) -> CommandResult:
        """Record a coordinator exception for a *review-level* item only.

        Hard constraints (capacity, accessibility conflicts, overlaps, stale
        proposals, hours) are not overridable by design.
        """
        hard = ("R-CAP", "R-ACCESS", "R-OVERLAP", "R-NO-OPTION", "R-MAXPARTY", "R-STALE", "R-HOURS", "R-PAST",
                "R-INTERVAL", "R-ACCESS-CONFLICT")
        if rule_id.startswith(hard):
            return CommandResult(ok=False, code="not_overridable",
                                 message=f"{rule_id} is a hard constraint and cannot be overridden.")
        if rule_id not in ("R-DUR-EXT",):
            return CommandResult(ok=False, code="not_overridable",
                                 message=f"{rule_id} must be resolved by recording the missing decision, not overridden.")

        def fn():
            inq = self._inq(inquiry_id)
            r = self._reason(reason)
            self._event(key, "exception_approved", inq.id, after={"rule_id": rule_id}, reason=r,
                        record_version=inq.record_version)
            return CommandResult(ok=True, message=f"Exception for {rule_id} recorded with reason.")

        return self._run(key, fn)

    # ================================================================ drafts
    def generate_draft(self, inquiry_id: str, key: str, purpose: str | None = None) -> CommandResult:
        from .drafting import compose_draft

        v = self.load(inquiry_id)
        try:
            composed = compose_draft(self.cfg, v, self.provider, purpose)
        except ValueError as exc:
            return CommandResult(ok=False, code="validation", message=str(exc))

        def fn():
            inq = self._inq(inquiry_id)
            if inq.record_version != v.inquiry.record_version:
                raise DomainError("stale_view", "Inquiry changed while drafting; generate again.")
            did = self.db.next_id("draft", "DR-")
            now = self.now()
            d = Draft(
                id=did, inquiry_id=inquiry_id, purpose=composed.purpose, text=composed.text,
                generated_text=composed.text, source_record_version=inq.record_version, facts_hash=v.facts.hash(),
                policy_version=self.cfg.policy_version,
                proposal_id=v.active_proposal.id if v.active_proposal else None,
                booking_version=v.booking.version if v.booking else None, validation=composed.validation,
                status="generated", provider_mode=self.provider.mode, prose_source=composed.prose_source,
                created_at=now, updated_at=now,
            )
            self.repo.upsert_draft(d)
            self._event(key, "draft_generated", inquiry_id, after={
                "draft_id": did, "purpose": composed.purpose, "prose_source": composed.prose_source,
                "errors": sum(1 for x in composed.validation if x["severity"] == "error"),
                "prose_error": composed.prose_error}, record_version=inq.record_version)
            return CommandResult(ok=True, message=f"Draft {did} generated ({composed.purpose}, prose: "
                                 f"{composed.prose_source}).", data={"draft_id": did})

        return self._run(key, fn)

    def save_draft_edit(self, draft_id: str, text: str, key: str) -> CommandResult:
        from .drafting import validate_text

        def fn():
            d = self.repo.get_draft(draft_id)
            if d is None:
                raise DomainError("not_found", "draft not found")
            if not text.strip():
                raise DomainError("validation", "Draft text is empty.")
            if len(text) > 8000:
                raise DomainError("validation", "Draft is too long.")
            v = self.load(d.inquiry_id)
            validation = validate_text(self.cfg, v, d.purpose, text)
            nd = d.model_copy(update={"text": text, "validation": validation, "status": "edited", "approved_at": None,
                                      "approved_record_version": None, "updated_at": self.now()})
            self.repo.upsert_draft(nd)
            self._event(key, "draft_edited", d.inquiry_id, before={"chars": len(d.text)},
                        after={"draft_id": d.id, "chars": len(text)})
            return CommandResult(ok=True, message="Draft edit saved and revalidated.")

        return self._run(key, fn)

    def approve_draft(self, draft_id: str, key: str) -> CommandResult:
        from .drafting import validate_text

        def fn():
            d = self.repo.get_draft(draft_id)
            if d is None:
                raise DomainError("not_found", "draft not found")
            v = self.load(d.inquiry_id)
            if d.source_record_version != v.inquiry.record_version:
                raise DomainError("stale", "Draft is stale (facts or booking changed after it was generated). "
                                  "Generate a new draft.")
            validation = validate_text(self.cfg, v, d.purpose, d.text)
            errors = [x for x in validation if x["severity"] == "error"]
            if errors:
                raise DomainError("invalid_draft", "Fix validation errors first: " + "; ".join(e["message"] for e in errors))
            nd = d.model_copy(update={"status": "approved", "validation": validation, "approved_at": self.now(),
                                      "approved_record_version": v.inquiry.record_version, "updated_at": self.now()})
            self.repo.upsert_draft(nd)
            self._event(key, "draft_approved", d.inquiry_id, after={"draft_id": d.id, "purpose": d.purpose,
                                                                    "note": "approved text; NOT sent"},
                        record_version=v.inquiry.record_version)
            return CommandResult(ok=True, message="Draft marked reviewed. It has not been sent anywhere.")

        return self._run(key, fn)

    def record_copy(self, inquiry_id: str, what: str, key: str, draft_id: str | None = None) -> CommandResult:
        """Copy/export is logged as its own event; it never implies sending or booking externally."""

        def fn():
            self._inq(inquiry_id)
            self._event(key, "copied_or_exported", inquiry_id, after={
                "what": what, "draft_id": draft_id, "note": "copied/exported only; not sent, not synced"})
            return CommandResult(ok=True, message=f"{what} copy/export recorded (not a send).")

        return self._run(key, fn)

    # ================================================================ notes
    def booking_notes(self, inquiry_id: str) -> str:
        from .drafting import booking_notes

        return booking_notes(self.cfg, self.load(inquiry_id))


class _Reject(Exception):
    def __init__(self, proposal: Proposal, inquiry: Inquiry, kind: str, reason: str):
        super().__init__(reason)
        self.proposal, self.inquiry, self.kind, self.reason = proposal, inquiry, kind, reason


def new_key(prefix: str = "op") -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


__all__ = ["Workbench", "CommandResult", "DomainError", "InquiryView", "new_key", "NextAction"]
