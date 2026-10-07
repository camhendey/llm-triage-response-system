"""Provider interface shared by the offline interpreter and the live model.

Providers *suggest* facts, intents and prose. They never write to the database
and never decide availability. Every suggested fact must cite a real message
and an exact text span; ``validate_evidence`` enforces that before anything is
persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import ENUM_VALUES, FieldName, Intent


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    received_at: datetime  # aware
    is_new: bool = True  # False = context only; facts must not cite it
    direction: str = "inbound"


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: FieldName
    value: Any
    message_id: str
    quote: str
    span_start: int | None = None
    span_end: int | None = None
    status: Literal["extracted", "needs_review"] = "extracted"
    note: str | None = None


class InterpretationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_mode: str
    model: str | None = None
    status: Literal["ok", "partial", "unsupported", "failed"]
    facts: list[ExtractedFact] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    uninterpreted: list[str] = Field(default_factory=list)
    rejected_facts: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    raw_output: str | None = None
    latency_ms: int | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 1


@dataclass
class InterpretContext:
    timezone: str
    restaurant_name: str
    table_ids: list[str]
    now: datetime


@dataclass
class ProseRequest:
    """Inputs for optional model-written connecting prose around fixed facts."""

    purpose: str
    guest_name: str | None
    occasion: str | None
    fixed_body: str  # deterministic text the prose must not contradict
    allowed_numbers: set[str] = field(default_factory=set)
    conversation: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ProseResult:
    ok: bool
    opening: str = ""
    closing: str = ""
    error: str | None = None
    provider_mode: str = ""
    model: str | None = None
    latency_ms: int | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    raw_output: str | None = None


class Provider(Protocol):
    mode: str

    def interpret(self, messages: list[MessageInput], ctx: InterpretContext) -> InterpretationResult: ...

    def draft_prose(self, req: ProseRequest) -> ProseResult: ...

    def describe(self) -> str: ...


# ------------------------------------------------------------------ validation

def normalize_value(name: FieldName, value: Any) -> Any:
    """Coerce a suggested value to its canonical type or raise ValueError."""
    if value is None:
        raise ValueError("null value")
    if name in (FieldName.PARTY_SIZE, FieldName.REQUESTED_DURATION):
        if isinstance(value, bool):
            raise ValueError("boolean is not a number")
        if isinstance(value, str):
            value = value.strip()
            if not value.isdigit():
                raise ValueError(f"not an integer: {value!r}")
        iv = int(value)
        if iv <= 0 or iv > 500:
            raise ValueError(f"out of range: {iv}")
        if isinstance(value, float) and value != iv:
            raise ValueError("non-integer")
        return iv
    if name == FieldName.REQUESTED_DATE:
        return date.fromisoformat(str(value)).isoformat()
    if name == FieldName.REQUESTED_TIME:
        t = time.fromisoformat(str(value))
        return t.strftime("%H:%M")
    if name == FieldName.MIN_SPEND_AMOUNT:
        v = float(value)
        if v < 0:
            raise ValueError("negative amount")
        return v
    if name.value in ENUM_VALUES:
        v = str(value).strip().lower()
        if v not in ENUM_VALUES[name.value]:
            raise ValueError(f"{v!r} not in {ENUM_VALUES[name.value]}")
        return v
    if name == FieldName.CONTACT_EMAIL:
        v = str(value).strip()
        if "@" not in v or " " in v:
            raise ValueError("invalid email")
        return v.lower()
    v = str(value).strip()
    if not v:
        raise ValueError("empty")
    if len(v) > 300:
        raise ValueError("too long")
    return v


def validate_evidence(result: InterpretationResult, messages: list[MessageInput]) -> InterpretationResult:
    """Keep only facts whose quote occurs in the cited *new* message.

    Rejected facts are retained in ``rejected_facts`` for diagnostics; they are
    never stored as observations.
    """
    by_id = {m.id: m for m in messages}
    kept: list[ExtractedFact] = []
    for f in result.facts:
        m = by_id.get(f.message_id)
        reason = None
        if m is None:
            reason = "evidence cites an unknown message id"
        elif m.direction != "inbound":
            reason = "restaurant reply is context, not guest evidence"
        elif not m.is_new:
            reason = "evidence cites an earlier message that was context only"
        elif not f.quote or not f.quote.strip():
            reason = "empty evidence quote"
        else:
            if f.span_start is not None and f.span_end is not None and m.text[f.span_start:f.span_end] == f.quote:
                pass
            else:
                idx = m.text.find(f.quote)
                if idx < 0:
                    idx = m.text.lower().find(f.quote.lower())
                if idx < 0:
                    reason = "quote not found in cited message"
                else:
                    f.span_start, f.span_end = idx, idx + len(f.quote)
        if reason is None:
            try:
                f.value = normalize_value(f.field, f.value)
            except (ValueError, TypeError) as exc:
                reason = f"invalid value: {exc}"
        if reason:
            result.rejected_facts.append({"field": f.field.value, "value": f.value, "message_id": f.message_id,
                                          "quote": f.quote, "reason": reason})
        else:
            kept.append(f)
    result.facts = kept
    result.intents = [i for i in result.intents if i in {x.value for x in Intent}]
    return result
