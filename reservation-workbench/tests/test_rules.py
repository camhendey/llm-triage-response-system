"""Deterministic rule tests (A05-A08, A16, A17, config validation, ranking, alternatives)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
import yaml
from pydantic import ValidationError

from reservation_workbench.domain.config import DEFAULT_CONFIG_PATH, RestaurantConfig
from reservation_workbench.domain.models import Booking, BookingStatus
from reservation_workbench.rules.availability import (
    SeatingRequest,
    arrival_warning,
    evaluate,
    find_alternatives,
    local_interval,
    overlaps,
)

from .conftest import T0


def bk(id, tables, start, end, status="confirmed", party=8, expires=None):
    return Booking(id=id, inquiry_id=None, guest_label=id, status=BookingStatus(status), table_ids=tables,
                   party_size=party, start=start, end=end, hold_expires_at=expires, created_at=T0, updated_at=T0)


def seed(cfg):
    out = []
    for b in cfg.bookings:
        out.append(bk(b.id, b.table_ids, b.start.astimezone(UTC), b.end.astimezone(UTC), b.status, b.party_size,
                      b.expires_at.astimezone(UTC) if b.expires_at else None))
    return out


def req(cfg, party, d, t, minutes=None, **kw):
    s, e = local_interval(cfg, d, t, minutes or cfg.policies.duration_for(party))
    return SeatingRequest(party_size=party, start=s, end=e, **kw)


NOV13 = date(2026, 11, 13)


# ---------------------------------------------------------------- config

def test_config_validates_and_values_are_applied(cfg):
    assert cfg.policies.duration_for(7) == 120 and cfg.policies.duration_for(8) == 150
    assert cfg.restaurant.max_main_restaurant_party == 25


@pytest.mark.parametrize("mutate,msg", [
    (lambda r: r["groupings"].append({"id": "G_BAD", "tables": ["L1", "ZZ"], "capacity": 5, "arrangement": "x"}),
     "unknown tables"),
    (lambda r: r["tables"].append({"id": "M9", "area": "mezzanine", "capacity": 4, "step_free": True, "style": "t"}),
     "step-free"),
    (lambda r: r["groupings"].append({"id": "G_BIG", "tables": ["L2", "L3"], "capacity": 99, "arrangement": "x"}),
     "exceeds"),
    (lambda r: r["policies"]["confirmation_required_fields"].append("shoe_size"), "unknown fields"),
])
def test_invalid_config_rejected(mutate, msg):
    raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text())
    mutate(raw)
    with pytest.raises(ValidationError, match=msg):
        RestaurantConfig.model_validate(raw)


# ---------------------------------------------------------------- A05 accessibility

def test_A05_stairs_only_option_rejected_for_wheelchair(cfg):
    r = evaluate(cfg, req(cfg, 12, date(2026, 11, 14), time(18), step_free_required=True), seed(cfg), T0)
    m1 = next(o for o in r.rejected if o.unit_id == "M1")
    assert any(x.startswith("R-ACCESS") for x in m1.reasons)
    assert all(o.step_free for o in r.options)
    assert {o.unit_id for o in r.options} >= {"L1", "G_L3_L4", "G_D1_D2"}


def test_seed2_no_step_free_option_at_6pm_and_checked_alternatives(cfg):
    rq = req(cfg, 12, NOV13, time(18), step_free_required=True, split_ok=True)
    r = evaluate(cfg, rq, seed(cfg), T0)
    assert not r.feasible
    reasons = {o.unit_id: o.reasons for o in r.rejected}
    assert any("R-OVERLAP" in x and "B001" in x for x in reasons["L1"])
    assert any("R-OVERLAP" in x for x in reasons["G_L3_L4"])  # H001 hold still active at 10:00
    assert any("R-CAP" in x for x in reasons["D2"])
    assert any("R-ACCESS" in x for x in reasons["M1"])
    alts = find_alternatives(cfg, rq, seed(cfg), T0)
    times = [t.astimezone(cfg.tz).strftime("%H:%M") for t, _ in alts]
    assert "20:30" in times and "15:30" in times  # both sides of the occupied 18:00-20:30 block
    for t, o in alts:  # every alternative re-checked by the same engine
        again = evaluate(cfg, SeatingRequest(**{**rq.__dict__, "start": t, "end": t + (rq.end - rq.start)}),
                         seed(cfg), T0)
        assert o.unit_id in {x.unit_id for x in again.options}


# ---------------------------------------------------------------- A06 groupings consume tables

def test_A06_grouping_rejected_when_constituent_table_booked(cfg):
    r = evaluate(cfg, req(cfg, 22, NOV13, time(18)), seed(cfg), T0)
    g = next(o for o in r.rejected if o.unit_id == "G_L1_L2")
    assert any("table L1" in x and "B001" in x for x in g.reasons)


# ---------------------------------------------------------------- A07 half-open + buffer

def test_A07_adjacent_booking_allowed_with_zero_buffer_and_blocked_with_buffer(cfg):
    prior = [bk("X", ["D2"], *local_interval(cfg, date(2026, 11, 20), time(15, 30), 150))]
    rq = req(cfg, 8, date(2026, 11, 20), time(18))
    assert "D2" in {o.unit_id for o in evaluate(cfg, rq, prior, T0).options}
    raw = cfg.model_dump()
    raw["policies"]["turnover_buffer_minutes"] = 15
    cfg15 = RestaurantConfig.model_validate(raw)
    r15 = evaluate(cfg15, rq, prior, T0)
    assert "D2" not in {o.unit_id for o in r15.options}
    assert any("R-OVERLAP" in x for x in next(o for o in r15.rejected if o.unit_id == "D2").reasons)


def test_overlap_is_half_open():
    a = datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert not overlaps(a, a + timedelta(hours=1), a + timedelta(hours=1), a + timedelta(hours=2), 0)
    assert overlaps(a, a + timedelta(hours=1), a + timedelta(minutes=59), a + timedelta(hours=2), 0)
    assert overlaps(a, a + timedelta(hours=1), a + timedelta(hours=1), a + timedelta(hours=2), 1)


# ---------------------------------------------------------------- A08 continuous intervals

def test_A08_interval_crossing_noon_detects_collision(cfg):
    lunch = [bk("LUNCH", ["D2"], *local_interval(cfg, date(2026, 11, 20), time(11, 30), 150))]  # 11:30-14:00
    r = evaluate(cfg, req(cfg, 9, date(2026, 11, 20), time(13)), lunch, T0)  # 13:00 (1 PM) overlaps
    assert any("LUNCH" in x for x in next(o for o in r.rejected if o.unit_id == "D2").reasons)
    r2 = evaluate(cfg, req(cfg, 9, date(2026, 11, 20), time(14)), lunch, T0)  # 2 PM starts at end
    assert "D2" in {o.unit_id for o in r2.options}


def test_A08_dst_change_keeps_true_duration(cfg):
    # America/Toronto falls back on 2026-11-01. A booking that day still lasts exactly 150 minutes.
    s, e = local_interval(cfg, date(2026, 11, 1), time(18), 150)
    assert (e - s) == timedelta(minutes=150)
    assert s.astimezone(cfg.tz).utcoffset() == timedelta(hours=-5)
    s2, _ = local_interval(cfg, date(2026, 10, 31), time(18), 150)
    assert s2.astimezone(cfg.tz).utcoffset() == timedelta(hours=-4)


def test_opening_hours_enforced(cfg):
    r = evaluate(cfg, req(cfg, 4, date(2026, 11, 20), time(21, 30)), [], T0)  # ends 23:30
    assert not r.feasible and any("R-HOURS" in e for e in r.interval_errors)
    r = evaluate(cfg, req(cfg, 4, date(2026, 11, 20), time(10, 30)), [], T0)
    assert any("before opening" in e for e in r.interval_errors)


def test_expired_hold_does_not_block(cfg):
    later = T0 + timedelta(hours=2)  # H001 expires at 12:00
    r = evaluate(cfg, req(cfg, 14, NOV13, time(18)), seed(cfg), later)
    assert "G_L3_L4" in {o.unit_id for o in r.options}
    r_before = evaluate(cfg, req(cfg, 14, NOV13, time(18)), seed(cfg), later - timedelta(seconds=1))
    assert "G_L3_L4" not in {o.unit_id for o in r_before.options}


# ---------------------------------------------------------------- A16 split disclosure + ranking

def test_A16_split_options_disclosed_and_ranked_after_single_tables(cfg):
    r = evaluate(cfg, req(cfg, 16, date(2026, 11, 20), time(19)), [], T0)
    ranked = [o.unit_id for o in r.options]
    assert ranked[0] == "M1"  # smallest sufficient single table
    g = next(o for o in r.options if o.unit_id == "G_L3_L4")
    assert g.split and any("not one joined table" in n for n in g.notes)


def test_ranking_prefers_requested_area_then_step_free_when_unknown(cfg):
    r = evaluate(cfg, req(cfg, 16, date(2026, 11, 20), time(19), preferred_area="lounge"), [], T0)
    assert r.options[0].unit_id == "G_L3_L4"
    r = evaluate(cfg, req(cfg, 16, date(2026, 11, 20), time(19), accessibility_known=False), [], T0)
    assert r.options[0].unit_id == "M1"  # capacity first ...
    r = evaluate(cfg, req(cfg, 16, date(2026, 11, 20), time(19), split_ok=False), [], T0)
    assert not r.options[0].split


# ---------------------------------------------------------------- A17 arrival heuristic

def test_A17_three_large_parties_in_bucket_warns(cfg):
    s, e = local_interval(cfg, NOV13, time(18, 15), 150)
    w = arrival_warning(cfg, seed(cfg), T0, "NEW", 10, s)
    assert w is not None and w.count == 4
    # one bucket later: no warning
    s2, _ = local_interval(cfg, NOV13, time(19, 0), 150)
    assert arrival_warning(cfg, seed(cfg), T0, "NEW", 10, s2) is None
    # two existing + one new = 3 -> warns at threshold
    two = [b for b in seed(cfg) if b.id != "H001"]
    w3 = arrival_warning(cfg, two, T0, "NEW", 9, s)
    assert w3 is not None and w3.count == 3
    assert arrival_warning(cfg, two, T0, "NEW", 4, s) is None  # small party not counted


def test_stairs_only_preference_with_step_free_need_is_reviewed(cfg):
    """A wheelchair user asking for the mezzanine gets an explicit review, never a stairs-only seat."""
    from .conftest import make_wb, new_inquiry
    wb = make_wb(cfg)
    iid = new_inquiry(wb, "We'd love the mezzanine for 8 on November 20, 2026 at 7 pm. One guest uses a wheelchair. "
                          "No minors, no allergies, one bill, birthday. lee@example.com")
    a = wb.load(iid).assessment
    assert any(r.rule_id == "R-ACCESS-CONFLICT" for r in a.reviews)
    assert a.availability.best().step_free
    assert not a.confirm_ready
    # no hold on a different area until the guest agrees (retest 4, HO-CAP-04)
    assert a.next_action.value == "operator_review"


def test_explicit_table_request_outranks_smallest_capacity(cfg):
    """Found while replaying worked example 3: 'D1 is fine' must not be proposed as stairs-only M2."""
    from .conftest import add, make_wb
    wb = make_wb(cfg)
    add(wb, "INQ-B002", "Please move our 8-person booking on November 13 from 6 pm to 7 pm, specifically to L1.")
    add(wb, "INQ-B002", "OK, D1 is fine then, still 7 pm.")
    best = wb.load("INQ-B002").assessment.availability.best()
    assert best.unit_id == "D1"


def test_modification_keeps_current_table_when_nothing_else_asked(cfg):
    from .conftest import add, make_wb
    wb = make_wb(cfg)
    add(wb, "INQ-B002", "Could we move our booking on November 13 to 8 pm instead? Same group of 8.")
    assert wb.load("INQ-B002").assessment.availability.best().table_ids == ["D1"]


def test_refusal_names_the_requested_units_reason(cfg):
    from .conftest import make_wb, new_inquiry, key
    wb = make_wb(cfg)
    iid = new_inquiry(wb, "We are 12 guests for November 13, 2026 at 6 pm. One guest uses a wheelchair.")
    r = wb.propose(iid, key(), unit_id="M1")
    assert not r.ok and "R-ACCESS" in r.message


def test_too_small_requested_table_is_not_satisfied_by_an_oversized_grouping(cfg):
    """Found by held-out retest 3 (HO-CAP-05): L2 seats 5, so 7 guests must not get L1+L2 (25 seats, split)
    just because the grouping contains L2. The substitute is ranked by capacity and flagged R-PREF."""
    r = evaluate(cfg, req(cfg, 7, date(2026, 11, 21), time(19, 0), preferred_table="L2"), [], T0)
    best = r.best()
    assert best.table_ids != ["L1", "L2"] and not best.split
    assert any(n.startswith("Preference not satisfied: guest asked for table L2") for n in best.notes)
