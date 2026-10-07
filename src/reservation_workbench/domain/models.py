"""Validated domain records and enums.

Three status axes are deliberately kept apart:

* ``InquiryState``  - where the conversation is in the coordinator's workflow.
* ``BookingStatus`` - the simulated allocation held in the demo database.
* ``ProposalStatus`` / pending requests - the status of the *next action*.

A confirmed booking can therefore sit beside an inquiry that is ``needs_review``
because the guest has just asked to cancel; the cancellation request does not
change the booking until the coordinator commits it.
"""

from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InquiryState(StrEnum):
    NEW = "new"
    NEEDS_REVIEW = "needs_review"
    AWAITING_GUEST = "awaiting_guest"
    READY_FOR_ACTION = "ready_for_action"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    CLOSED = "closed"


class BookingStatus(StrEnum):
    NONE = "none"
    HELD = "held"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    RELEASED = "released"


ACTIVE_BOOKING_STATUSES = (BookingStatus.HELD, BookingStatus.CONFIRMED)


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    STALE = "stale"
    COMMITTED = "committed"
    REJECTED = "rejected"


class ProposalKind(StrEnum):
    NEW_ALLOCATION = "new_allocation"  # hold or confirm a new booking
    MODIFICATION = "modification"  # move an existing booking


class FieldStatus(StrEnum):
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    OPERATOR_CONFIRMED = "operator_confirmed"
    SUPERSEDED = "superseded"


class Direction(StrEnum):
    INBOUND = "inbound"  # guest -> restaurant (pasted or seeded)
    OUTBOUND_REPORTED = "outbound_reported"  # operator says they sent something externally


class MessageSource(StrEnum):
    SEED = "seed"  # synthetic demo data
    PASTED = "pasted"  # operator pasted guest text
    CSV_IMPORT = "csv_import"


class Intent(StrEnum):
    NEW_BOOKING = "new_booking"
    MODIFY_BOOKING = "modify_booking"
    CANCEL_BOOKING = "cancel_booking"
    PROVIDE_DETAILS = "provide_details"
    QUESTION = "question"
    OTHER = "other"


class NextAction(StrEnum):
    CLARIFY = "clarify"
    OPERATOR_REVIEW = "operator_review"
    CHECK_AVAILABILITY = "check_availability"
    RECHECK_PROPOSAL = "recheck_proposal"
    CREATE_HOLD = "create_hold"
    CONFIRM_BOOKING = "confirm_booking"
    OFFER_ALTERNATIVE = "offer_alternative"
    DECLINE = "decline"
    ESCALATE_PRIVATE_EVENTS = "escalate_private_events"
    PROCESS_CANCELLATION = "process_cancellation"
    PROCESS_MODIFICATION = "process_modification"
    EXPLAIN_CHANGE_UNAVAILABLE = "explain_change_unavailable"
    AWAIT_GUEST = "await_guest"
    MANUAL_INTERPRETATION = "manual_interpretation"
    NO_ACTION = "no_action"


NEXT_ACTION_LABELS: dict[NextAction, str] = {
    NextAction.CLARIFY: "Ask the guest for missing or unclear details",
    NextAction.OPERATOR_REVIEW: "Resolve review items before acting",
    NextAction.CHECK_AVAILABILITY: "Check seating availability",
    NextAction.RECHECK_PROPOSAL: "Facts changed - recheck the proposal",
    NextAction.CREATE_HOLD: "Create a demo hold and request remaining details",
    NextAction.CONFIRM_BOOKING: "Record demo confirmation",
    NextAction.OFFER_ALTERNATIVE: "Offer checked alternative times",
    NextAction.DECLINE: "Decline - no checked option fits",
    NextAction.ESCALATE_PRIVATE_EVENTS: "Escalate to private-events review",
    NextAction.PROCESS_CANCELLATION: "Review and commit the cancellation request",
    NextAction.PROCESS_MODIFICATION: "Review and commit the requested change",
    NextAction.EXPLAIN_CHANGE_UNAVAILABLE: "Explain the requested change is unavailable; original booking stays",
    NextAction.AWAIT_GUEST: "Waiting for the guest's reply",
    NextAction.MANUAL_INTERPRETATION: "Interpret the message manually (outside offline scope)",
    NextAction.NO_ACTION: "No action pending",
}


class Severity(StrEnum):
    BLOCKER = "blocker"
    REVIEW = "review"
    ADVISORY = "advisory"


class FieldName(StrEnum):
    GUEST_NAME = "guest_name"
    PARTY_SIZE = "party_size"
    REQUESTED_DATE = "requested_date"
    REQUESTED_TIME = "requested_time"
    REQUESTED_DURATION = "requested_duration_minutes"
    CONTACT_EMAIL = "contact_email"
    CONTACT_PHONE = "contact_phone"
    ACCESSIBILITY = "accessibility"
    MINORS = "minors"
    ALLERGIES = "allergies"
    BILLING = "billing"
    OCCASION = "occasion"
    PREFERRED_AREA = "preferred_area"
    PREFERRED_TABLE = "preferred_table"
    SPLIT_SEATING_OK = "split_seating_ok"
    MIN_SPEND_AMOUNT = "min_spend_amount"
    MIN_SPEND_ACKNOWLEDGED = "min_spend_acknowledged"


# Facts whose change invalidates dependent proposals/approvals/drafts.
MATERIAL_FIELDS = frozenset(
    {
        FieldName.PARTY_SIZE,
        FieldName.REQUESTED_DATE,
        FieldName.REQUESTED_TIME,
        FieldName.REQUESTED_DURATION,
        FieldName.ACCESSIBILITY,
        FieldName.SPLIT_SEATING_OK,
        FieldName.PREFERRED_AREA,
        FieldName.PREFERRED_TABLE,
    }
)

# Values extracted from guest text; operator-only fields are excluded.
GUEST_FIELDS = tuple(f for f in FieldName if f not in (FieldName.MIN_SPEND_AMOUNT,))

FIELD_LABELS: dict[str, str] = {
    "guest_name": "Guest name",
    "party_size": "Party size",
    "requested_date": "Date",
    "requested_time": "Start time",
    "requested_duration_minutes": "Requested duration (min)",
    "contact_email": "Email",
    "contact_phone": "Phone",
    "accessibility": "Accessibility",
    "minors": "Minors",
    "allergies": "Allergies",
    "billing": "Billing",
    "occasion": "Occasion",
    "preferred_area": "Preferred area",
    "preferred_table": "Requested table",
    "split_seating_ok": "Separate tables OK",
    "min_spend_amount": "Minimum spend (operator)",
    "min_spend_acknowledged": "Minimum spend acknowledged",
    "dining_start": "Dining start",
    "dining_end": "Dining end",
}

ENUM_VALUES: dict[str, tuple[str, ...]] = {
    "accessibility": ("none", "step_free_required", "other_needs"),
    "minors": ("none", "present"),
    "billing": ("one_bill", "separate_bills"),
    "preferred_area": ("lounge", "dining", "mezzanine", "no_preference"),
    "split_seating_ok": ("yes", "no"),
    "min_spend_acknowledged": ("yes", "no"),
}


class _Rec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(_Rec):
    id: str
    inquiry_id: str
    direction: Direction
    text: str
    received_at: datetime
    source: MessageSource
    seq: int = 0


class Inquiry(_Rec):
    id: str
    guest_label: str
    state: InquiryState
    booking_id: str | None = None
    record_version: int = 1
    created_at: datetime
    updated_at: datetime
    title: str = ""
    # Highest message seq covered by the last committed decision; inbound
    # messages after it carry "open" requests.
    handled_seq: int = 0
    # Highest observation seq covered by the last committed decision; later
    # material observations are an open change request.
    handled_obs_seq: int = 0
    # Message seq at which a sticky state (awaiting_guest/escalated/closed) was set.
    state_set_seq: int = 0


class Observation(_Rec):
    id: str
    inquiry_id: str
    field: FieldName
    value: Any
    source_type: str  # message | operator | seed
    message_id: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    quote: str | None = None
    status: FieldStatus
    note: str | None = None
    provider_mode: str | None = None
    interpretation_id: str | None = None
    observed_at: datetime
    seq: int = 0


class Booking(_Rec):
    id: str
    inquiry_id: str | None
    guest_label: str
    status: BookingStatus
    table_ids: list[str]
    party_size: int
    start: datetime  # aware, UTC in storage
    end: datetime
    hold_expires_at: datetime | None = None
    version: int = 1
    source: str = "app"
    created_at: datetime
    updated_at: datetime


class RuleResult(_Rec):
    rule_id: str
    severity: Severity
    message: str
    values: dict[str, Any] = Field(default_factory=dict)


class SeatingOption(_Rec):
    unit_id: str  # table id or grouping id
    table_ids: list[str]
    capacity: int
    area: str
    step_free: bool
    split: bool  # True when the unit is separate tables
    arrangement: str
    start: datetime
    end: datetime
    feasible: bool
    rank: int | None = None
    reasons: list[str] = Field(default_factory=list)  # rejection reasons
    notes: list[str] = Field(default_factory=list)  # disclosures/preferences


class Proposal(_Rec):
    id: str
    inquiry_id: str
    kind: ProposalKind
    source_record_version: int
    policy_version: str
    booking_id: str | None = None
    booking_version: int | None = None
    option: SeatingOption
    party_size: int
    rule_results: list[RuleResult] = Field(default_factory=list)
    required_decisions: list[str] = Field(default_factory=list)
    status: ProposalStatus
    approved_at: datetime | None = None
    approval_reason: str | None = None
    created_at: datetime
    status_reason: str | None = None


class Draft(_Rec):
    id: str
    inquiry_id: str
    purpose: str
    text: str
    generated_text: str
    source_record_version: int
    facts_hash: str
    policy_version: str
    proposal_id: str | None = None
    booking_version: int | None = None
    validation: list[dict[str, Any]] = Field(default_factory=list)
    status: str  # generated | edited | approved
    approved_at: datetime | None = None
    approved_record_version: int | None = None
    provider_mode: str
    prose_source: str
    created_at: datetime
    updated_at: datetime


class Event(_Rec):
    id: str
    idempotency_key: str
    inquiry_id: str | None
    booking_id: str | None = None
    actor: str
    event_type: str
    before: Any = None
    after: Any = None
    reason: str | None = None
    created_at: datetime
    mode: str
    proposal_id: str | None = None
    record_version: int | None = None
    booking_version: int | None = None


class Interpretation(_Rec):
    id: str
    inquiry_id: str
    message_ids: list[str]
    provider_mode: str
    model: str | None = None
    status: str  # ok | partial | unsupported | failed
    intents: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    uninterpreted: list[str] = Field(default_factory=list)
    error: str | None = None
    raw_output: str | None = None
    latency_ms: int | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ParsedDate(_Rec):
    value: date | None
    assumption: str | None = None
    ambiguous: bool = False


class ParsedTime(_Rec):
    value: time | None
    assumption: str | None = None
    ambiguous: bool = False
