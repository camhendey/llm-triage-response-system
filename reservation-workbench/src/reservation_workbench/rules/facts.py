"""Resolve observations into current field values with provenance.

Rules:

* The most recent operator observation for a field is authoritative until the
  operator revises it. A *later* guest/model observation with a different
  value is surfaced as a conflict; it is never applied silently.
* Without an operator observation, the latest guest-sourced observation is
  current and earlier ones become ``superseded`` (they are kept and shown).
* Two different values from the same message are a conflict.
* ``needs_review`` observations carry a candidate value that does not count as
  known until the operator confirms it.
* A field with no observation is ``unknown``. ``"none"`` is a value, not unknown.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from ..domain.config import RestaurantConfig
from ..domain.models import FieldName, FieldStatus, Observation
from .availability import local_interval


@dataclass
class FieldView:
    field: FieldName
    value: Any = None
    state: str = "unknown"  # known | needs_review | conflict | unknown
    current: Observation | None = None
    history: list[tuple[Observation, FieldStatus]] = field(default_factory=list)
    conflicts: list[Observation] = field(default_factory=list)
    changed_from: list[Any] = field(default_factory=list)

    @property
    def known(self) -> bool:
        return self.state == "known"


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    return a == b


def resolve_field(name: FieldName, obs: list[Observation]) -> FieldView:
    fv = FieldView(field=name)
    items = sorted([o for o in obs if o.field == name], key=lambda o: o.seq)
    if not items:
        return fv
    operator = [o for o in items if o.source_type == "operator"]
    if operator:
        anchor = operator[-1]
        later = [o for o in items if o.seq > anchor.seq and o.source_type != "operator"]
        fv.current = anchor
        fv.value = anchor.value
        fv.conflicts = [o for o in later if not _same(o.value, anchor.value)]
        fv.state = "conflict" if fv.conflicts else "known"
        for o in items:
            if o is anchor:
                st = FieldStatus.OPERATOR_CONFIRMED
            elif o.seq > anchor.seq:
                st = o.status
            else:
                st = FieldStatus.SUPERSEDED
            fv.history.append((o, st))
    else:
        latest = items[-1]
        same_msg = [o for o in items if o.message_id is not None and o.message_id == latest.message_id]
        distinct = []
        for o in same_msg:
            if not any(_same(o.value, d.value) for d in distinct):
                distinct.append(o)
        fv.current = latest
        fv.value = latest.value
        if len(distinct) > 1:
            fv.state = "conflict"
            fv.conflicts = distinct[:-1]
        elif latest.status == FieldStatus.NEEDS_REVIEW:
            fv.state = "needs_review"
        else:
            fv.state = "known"
        for o in items:
            fv.history.append((o, o.status if (o is latest or o in same_msg) else FieldStatus.SUPERSEDED))
    seen: list[Any] = []
    for o, st in fv.history:
        if st == FieldStatus.SUPERSEDED and not _same(o.value, fv.value) and not any(_same(o.value, s) for s in seen):
            seen.append(o.value)
    fv.changed_from = seen
    return fv


@dataclass
class Facts:
    fields: dict[FieldName, FieldView]
    duration_minutes: int | None = None
    duration_source: str | None = None
    dining_start: datetime | None = None
    dining_end: datetime | None = None

    def get(self, name: FieldName) -> FieldView:
        return self.fields[name]

    def value(self, name: FieldName) -> Any:
        fv = self.fields[name]
        return fv.value if fv.known else None

    @property
    def interval_known(self) -> bool:
        return self.dining_start is not None

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, fv in self.fields.items():
            out[k.value] = {"value": fv.value, "state": fv.state}
        out["dining_start"] = self.dining_start.isoformat() if self.dining_start else None
        out["dining_end"] = self.dining_end.isoformat() if self.dining_end else None
        return out

    def hash(self) -> str:
        return hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True, default=str).encode()).hexdigest()[:16]


def resolve(cfg: RestaurantConfig, obs: list[Observation]) -> Facts:
    fields = {f: resolve_field(f, obs) for f in FieldName}
    facts = Facts(fields=fields)
    party = facts.value(FieldName.PARTY_SIZE)
    d = facts.value(FieldName.REQUESTED_DATE)
    t = facts.value(FieldName.REQUESTED_TIME)
    if party is not None:
        policy_minutes = cfg.policies.duration_for(int(party))
        facts.duration_minutes = policy_minutes
        facts.duration_source = (
            f"policy: {policy_minutes} min for parties "
            + (f"<= {cfg.policies.small_party_max}" if int(party) <= cfg.policies.small_party_max
               else f"> {cfg.policies.small_party_max}")
        )
        req = facts.value(FieldName.REQUESTED_DURATION)
        if req is not None and int(req) < policy_minutes:
            facts.duration_minutes = int(req)
            facts.duration_source = f"guest requested {int(req)} min (shorter than policy {policy_minutes})"
    if party is not None and d is not None and t is not None and facts.duration_minutes:
        dd = date.fromisoformat(d) if isinstance(d, str) else d
        tt = time.fromisoformat(t) if isinstance(t, str) else t
        facts.dining_start, facts.dining_end = local_interval(cfg, dd, tt, facts.duration_minutes)
    return facts
