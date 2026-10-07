"""Restaurant configuration: schema, loading and startup validation.

The YAML file is a *demonstration* policy for a synthetic restaurant. Every value
shown in the UI is read from the validated object returned by ``load_config`` so
displayed numbers always match applied settings.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "restaurant_demo.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RestaurantInfo(_Strict):
    id: str
    name: str
    timezone: str
    opening_time: time
    closing_time: time
    max_main_restaurant_party: int = Field(gt=0)

    @field_validator("timezone")
    @classmethod
    def _tz_exists(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:  # pragma: no cover - defensive
            raise ValueError(f"unknown timezone {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _hours(self) -> "RestaurantInfo":
        if self.closing_time <= self.opening_time:
            raise ValueError("closing_time must be after opening_time (overnight service is not modelled)")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class UrgencyPolicy(_Strict):
    hold_deadline_high_within_hours: float = Field(gt=0)
    dining_high_within_hours: float = Field(gt=0)


class Policies(_Strict):
    default_duration_minutes: int = Field(gt=0)
    small_party_duration_minutes: int = Field(gt=0)
    small_party_max: int = Field(gt=0)
    turnover_buffer_minutes: int = Field(ge=0)
    hold_hours: float = Field(gt=0)
    hold_expiry_must_precede_dining_start: bool
    short_notice_hold_requires_operator_deadline: bool
    auto_gratuity_percent: float = Field(ge=0)
    auto_gratuity_min_party: int = Field(gt=0)
    arrival_grace_minutes: int = Field(ge=0)
    minimum_spend_review_min_party: int = Field(gt=0)
    minimum_spend_amount: float | None = None
    confirmation_required_fields: list[str]
    large_party_min_size: int = Field(gt=0)
    arrival_bucket_minutes: int = Field(gt=0)
    arrival_warning_party_count: int = Field(gt=0)
    arrival_bucket_alignment: Literal["local_clock_hour"]
    urgency: UrgencyPolicy

    def duration_for(self, party_size: int) -> int:
        if party_size <= self.small_party_max:
            return self.small_party_duration_minutes
        return self.default_duration_minutes


class Area(_Strict):
    step_free: bool


class Table(_Strict):
    id: str
    area: str
    capacity: int = Field(gt=0)
    step_free: bool
    style: str


class Grouping(_Strict):
    id: str
    tables: list[str] = Field(min_length=2)
    capacity: int = Field(gt=0)
    arrangement: str


class SeedBooking(_Strict):
    id: str
    guest: str
    table_ids: list[str] = Field(min_length=1)
    party_size: int = Field(gt=0)
    start: datetime
    end: datetime
    status: Literal["held", "confirmed"]
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _aware(self) -> "SeedBooking":
        for name in ("start", "end", "expires_at"):
            v = getattr(self, name)
            if v is not None and v.tzinfo is None:
                raise ValueError(f"seed booking {self.id}: {name} must include a UTC offset")
        if self.end <= self.start:
            raise ValueError(f"seed booking {self.id}: end must be after start")
        if self.status == "held" and self.expires_at is None:
            raise ValueError(f"seed booking {self.id}: held bookings need expires_at")
        return self


class RestaurantConfig(_Strict):
    schema_version: Literal[1]
    policy_version: str
    restaurant: RestaurantInfo
    demo_clock: datetime
    policies: Policies
    areas: dict[str, Area]
    tables: list[Table]
    groupings: list[Grouping]
    bookings: list[SeedBooking] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistency(self) -> "RestaurantConfig":
        ids = [t.id for t in self.tables]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate table id")
        table_map = {t.id: t for t in self.tables}
        for t in self.tables:
            if t.area not in self.areas:
                raise ValueError(f"table {t.id} references unknown area {t.area}")
            if self.areas[t.area].step_free is False and t.step_free:
                raise ValueError(f"table {t.id} claims step-free access inside a stairs-only area")
        gids = [g.id for g in self.groupings]
        if len(gids) != len(set(gids)) or set(gids) & set(ids):
            raise ValueError("grouping ids must be unique and distinct from table ids")
        for g in self.groupings:
            missing = [x for x in g.tables if x not in table_map]
            if missing:
                raise ValueError(f"grouping {g.id} references unknown tables {missing}")
            total = sum(table_map[x].capacity for x in g.tables)
            if g.capacity > total:
                raise ValueError(f"grouping {g.id} capacity {g.capacity} exceeds constituent total {total}")
        if self.demo_clock.tzinfo is None:
            raise ValueError("demo_clock must include a UTC offset")
        known_fields = set(REQUIRED_FIELD_NAMES)
        unknown = [f for f in self.policies.confirmation_required_fields if f not in known_fields]
        if unknown:
            raise ValueError(f"confirmation_required_fields contains unknown fields {unknown}")
        for b in self.bookings:
            for tid in b.table_ids:
                if tid not in table_map:
                    raise ValueError(f"seed booking {b.id} references unknown table {tid}")
        return self

    # ---- convenience -------------------------------------------------
    @property
    def tz(self) -> ZoneInfo:
        return self.restaurant.tz

    def table(self, table_id: str) -> Table:
        for t in self.tables:
            if t.id == table_id:
                return t
        raise KeyError(table_id)

    def grouping(self, gid: str) -> Grouping:
        for g in self.groupings:
            if g.id == gid:
                return g
        raise KeyError(gid)


# Field names a confirmation policy may require. dining_start/dining_end are
# derived from requested_date + requested_time + policy duration.
REQUIRED_FIELD_NAMES = (
    "party_size",
    "dining_start",
    "dining_end",
    "contact_email",
    "contact_phone",
    "accessibility",
    "minors",
    "billing",
    "occasion",
    "allergies",
    "guest_name",
)


def load_config(path: str | Path | None = None) -> RestaurantConfig:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return RestaurantConfig.model_validate(raw)


def config_hash(path: str | Path | None = None) -> str:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    return hashlib.sha256(p.read_bytes()).hexdigest()
