"""Deterministic seating and availability engine.

Conventions (documented in docs/DOMAIN_AND_POLICIES.md):

* A booking occupies the half-open interval ``[start, end + buffer)`` where
  ``buffer`` is ``policies.turnover_buffer_minutes``. Two bookings collide when
  ``a.start < b.end + buffer`` and ``b.start < a.end + buffer``. With a zero
  buffer a booking may start exactly when the previous one ends.
* All arithmetic happens on UTC instants, so intervals crossing noon, a staff
  shift or a DST change are a single continuous span.
* Groupings consume their constituent physical tables; a grouping is never a
  resource in its own right.
* A hold blocks availability only while ``now < hold_expires_at``.
* Ranking of feasible options (no scoring model):
    1. options that respect an explicit "keep us together" request first,
    2. smallest sufficient capacity,
    3. requested-area / requested-table match,
    4. single table before separate adjacent tables,
    5. step-free before stairs-only while accessibility is still unknown,
    6. unit id (stable tie-breaker).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from ..domain.config import RestaurantConfig
from ..domain.models import Booking, BookingStatus, SeatingOption

ALTERNATIVE_STEP_MINUTES = 30
MAX_ALTERNATIVES = 3


@dataclass(frozen=True)
class Occupancy:
    booking_id: str
    table_ids: tuple[str, ...]
    start: datetime
    end: datetime
    status: str
    party_size: int
    guest_label: str


@dataclass(frozen=True)
class Unit:
    id: str
    table_ids: tuple[str, ...]
    capacity: int
    area: str
    step_free: bool
    split: bool
    arrangement: str


@dataclass
class SeatingRequest:
    party_size: int
    start: datetime
    end: datetime
    step_free_required: bool = False
    accessibility_known: bool = True
    preferred_area: str | None = None
    preferred_table: str | None = None
    split_ok: bool | None = None  # None = not stated
    exclude_booking_id: str | None = None  # booking being modified
    current_table_ids: tuple[str, ...] = ()  # its tables: kept when they still fit and nothing else was asked


@dataclass
class AvailabilityResult:
    request: SeatingRequest
    interval_errors: list[str] = field(default_factory=list)
    options: list[SeatingOption] = field(default_factory=list)  # feasible, ranked
    rejected: list[SeatingOption] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return bool(self.options)

    def best(self) -> SeatingOption | None:
        return self.options[0] if self.options else None


# ---------------------------------------------------------------- helpers

def local_interval(cfg: RestaurantConfig, d: date, t: time, minutes: int) -> tuple[datetime, datetime]:
    """Return aware (start, end) for a local wall-clock start and a duration.

    The duration is added in UTC so DST transitions never stretch or shrink it.
    """
    start_local = datetime.combine(d, t, tzinfo=cfg.tz)
    start = start_local.astimezone(UTC)
    return start, start + timedelta(minutes=minutes)


def hold_is_active(b: Booking, now: datetime) -> bool:
    return b.status == BookingStatus.HELD and b.hold_expires_at is not None and now < b.hold_expires_at


def blocking_occupancies(bookings: list[Booking], now: datetime) -> list[Occupancy]:
    out = []
    for b in bookings:
        if b.status == BookingStatus.CONFIRMED or hold_is_active(b, now):
            out.append(Occupancy(b.id, tuple(b.table_ids), b.start, b.end, b.status.value, b.party_size,
                                 b.guest_label))
    return out


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime, buffer_minutes: int) -> bool:
    buf = timedelta(minutes=buffer_minutes)
    return a_start < b_end + buf and b_start < a_end + buf


def units(cfg: RestaurantConfig) -> list[Unit]:
    out = [Unit(t.id, (t.id,), t.capacity, t.area, t.step_free, False, t.style) for t in cfg.tables]
    for g in cfg.groupings:
        tables = [cfg.table(x) for x in g.tables]
        areas = sorted({t.area for t in tables})
        out.append(Unit(g.id, tuple(g.tables), g.capacity, "+".join(areas), all(t.step_free for t in tables), True,
                        g.arrangement))
    return out


def interval_errors(cfg: RestaurantConfig, start: datetime, end: datetime, now: datetime | None) -> list[str]:
    errs = []
    tz = cfg.tz
    ls, le = start.astimezone(tz), end.astimezone(tz)
    opening = cfg.restaurant.opening_time
    closing = cfg.restaurant.closing_time
    if end <= start:
        errs.append("R-INTERVAL: end must be after start")
    if ls.time() < opening:
        errs.append(f"R-HOURS: starts {ls:%H:%M}, before opening {opening:%H:%M}")
    if le.date() != ls.date() or le.time() > closing:
        errs.append(f"R-HOURS: ends {le:%H:%M}, after closing {closing:%H:%M}")
    if now is not None and start <= now:
        errs.append("R-PAST: requested start is not in the future at the current clock")
    return errs


# ---------------------------------------------------------------- engine

def evaluate(cfg: RestaurantConfig, req: SeatingRequest, bookings: list[Booking], now: datetime | None,
             check_past: bool = True) -> AvailabilityResult:
    res = AvailabilityResult(request=req)
    res.interval_errors = interval_errors(cfg, req.start, req.end, now if check_past else None)
    occ = [o for o in blocking_occupancies(bookings, now or req.start) if o.booking_id != req.exclude_booking_id]
    buffer = cfg.policies.turnover_buffer_minutes
    tz = cfg.tz
    for u in units(cfg):
        reasons: list[str] = []
        notes: list[str] = []
        if u.capacity < req.party_size:
            reasons.append(f"R-CAP: capacity {u.capacity} < party {req.party_size}")
        if req.step_free_required and not u.step_free:
            reasons.append("R-ACCESS: stairs-only seating; guest needs step-free access")
        for o in occ:
            shared = sorted(set(u.table_ids) & set(o.table_ids))
            if shared and overlaps(req.start, req.end, o.start, o.end, buffer):
                reasons.append(
                    f"R-OVERLAP: table {', '.join(shared)} {o.status} by {o.booking_id} "
                    f"{o.start.astimezone(tz):%H:%M}-{o.end.astimezone(tz):%H:%M}"
                )
        if res.interval_errors:
            reasons.extend(res.interval_errors)
        if u.split:
            notes.append(f"Separate tables ({u.arrangement.replace('_', ' ')}): {' + '.join(u.table_ids)}; "
                         "not one joined table and not a private space")
        if not u.step_free:
            notes.append("Stairs-only area")
        if req.preferred_area and req.preferred_area != "no_preference" and req.preferred_area not in u.area:
            notes.append(f"Preference not satisfied: guest asked for {req.preferred_area}")
        if req.preferred_table and list(u.table_ids) != [req.preferred_table]:
            # Only the requested table on its own satisfies a table request; a grouping that merely
            # contains it (for example a 25-seat pair for 7 guests because the asked-for table is too small)
            # is a different seating and is flagged for review like any other substitute.
            extra = " (this grouping includes it)" if req.preferred_table in u.table_ids else ""
            notes.append(f"Preference not satisfied: guest asked for table {req.preferred_table}{extra}")
        if req.split_ok is False and u.split:
            notes.append("Preference not satisfied: guest asked to sit together")
        opt = SeatingOption(
            unit_id=u.id, table_ids=list(u.table_ids), capacity=u.capacity, area=u.area, step_free=u.step_free,
            split=u.split, arrangement=u.arrangement, start=req.start, end=req.end, feasible=not reasons,
            reasons=reasons, notes=notes,
        )
        (res.options if opt.feasible else res.rejected).append(opt)

    def key(o: SeatingOption):
        together_violation = req.split_ok is False and o.split
        area_miss = bool(req.preferred_area and req.preferred_area != "no_preference"
                         and req.preferred_area not in o.area)
        table_miss = bool(req.preferred_table and list(o.table_ids) != [req.preferred_table])
        stairs_unknown = (not req.accessibility_known) and not o.step_free
        moves_table = bool(req.current_table_ids) and tuple(sorted(o.table_ids)) != tuple(sorted(req.current_table_ids))
        # Explicit guest requests first, then keeping an existing booking where it is, then the smallest
        # sufficient capacity (keeps large tables free), then single tables before groupings.
        return (together_violation, table_miss, area_miss, moves_table, o.capacity, o.split, stairs_unknown,
                o.unit_id)

    res.options.sort(key=key)
    for i, o in enumerate(res.options, start=1):
        o.rank = i
    res.rejected.sort(key=lambda o: o.unit_id)
    return res


def satisfies_explicit_request(o: SeatingOption, req: SeatingRequest) -> bool:
    """True when an option meets every *explicit* guest request (table, area, together)."""
    if req.preferred_table and list(o.table_ids) != [req.preferred_table]:
        return False
    if req.preferred_area and req.preferred_area != "no_preference" and req.preferred_area not in o.area:
        return False
    if req.split_ok is False and o.split:
        return False
    return True


def find_alternatives(cfg: RestaurantConfig, req: SeatingRequest, bookings: list[Booking], now: datetime,
                      limit: int = MAX_ALTERNATIVES) -> list[tuple[datetime, SeatingOption]]:
    """Other start times on the same local date, checked by the same engine.

    Candidates step every ``ALTERNATIVE_STEP_MINUTES`` from opening; each must fit
    opening hours. Returned nearest-first to the requested start (earlier first
    on ties), with the best-ranked option at each time.
    """
    tz = cfg.tz
    duration = req.end - req.start
    day = req.start.astimezone(tz).date()
    t = datetime.combine(day, cfg.restaurant.opening_time, tzinfo=tz).astimezone(UTC)
    last = datetime.combine(day, cfg.restaurant.closing_time, tzinfo=tz).astimezone(UTC) - duration
    found: list[tuple[datetime, SeatingOption]] = []
    while t <= last:
        if t != req.start:
            alt = SeatingRequest(**{**req.__dict__, "start": t, "end": t + duration})
            r = evaluate(cfg, alt, bookings, now)
            if r.feasible:
                found.append((t, r.options[0]))
        t += timedelta(minutes=ALTERNATIVE_STEP_MINUTES)
    found.sort(key=lambda x: (abs((x[0] - req.start).total_seconds()), x[0]))
    return found[:limit]


# ---------------------------------------------------------------- service flow

@dataclass
class ArrivalBucket:
    bucket_start: datetime  # local
    large_parties: list[tuple[str, int]]  # (label, size)

    @property
    def count(self) -> int:
        return len(self.large_parties)


def arrival_buckets(cfg: RestaurantConfig, bookings: list[Booking], now: datetime, day: date,
                    candidate: tuple[str, int, datetime] | None = None,
                    exclude_booking_id: str | None = None) -> list[ArrivalBucket]:
    """Group large-party arrivals into local clock-hour buckets (heuristic only)."""
    pol = cfg.policies
    tz = cfg.tz
    items: list[tuple[str, int, datetime]] = []
    for o in blocking_occupancies(bookings, now):
        if o.booking_id == exclude_booking_id:
            continue
        if o.party_size >= pol.large_party_min_size and o.start.astimezone(tz).date() == day:
            items.append((o.booking_id, o.party_size, o.start))
    if candidate and candidate[1] >= pol.large_party_min_size and candidate[2].astimezone(tz).date() == day:
        items.append(candidate)
    buckets: dict[datetime, ArrivalBucket] = {}
    for label, size, start in items:
        local = start.astimezone(tz)
        minutes = local.hour * 60 + local.minute
        floored = minutes - (minutes % pol.arrival_bucket_minutes)
        b_start = datetime.combine(day, time(floored // 60, floored % 60), tzinfo=tz)
        buckets.setdefault(b_start, ArrivalBucket(b_start, [])).large_parties.append((label, size))
    return [buckets[k] for k in sorted(buckets)]


def arrival_warning(cfg: RestaurantConfig, bookings: list[Booking], now: datetime, label: str, size: int,
                    start: datetime, exclude_booking_id: str | None = None) -> ArrivalBucket | None:
    day = start.astimezone(cfg.tz).date()
    for b in arrival_buckets(cfg, bookings, now, day, (label, size, start), exclude_booking_id):
        if any(x[0] == label for x in b.large_parties) and b.count >= cfg.policies.arrival_warning_party_count:
            return b
    return None
