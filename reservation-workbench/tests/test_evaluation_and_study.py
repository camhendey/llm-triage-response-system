"""Evaluation runner, dataset freeze and study harness (no live calls)."""

from __future__ import annotations

import json

import pytest

from reservation_workbench.domain.config import load_config
from reservation_workbench.evaluation import dataset, runner
from reservation_workbench.providers.offline import OfflineRulesProvider
from reservation_workbench.study import harness


def test_dataset_shape_and_freeze():
    for split in dataset.SPLIT_FILES:
        sc = dataset.load_split(split)
        assert dataset.validate(sc, split) == []
        ok, msg = dataset.check_frozen(split)
        assert ok, msg


def test_freeze_refuses_to_overwrite():
    with pytest.raises(dataset.DatasetError):
        dataset.freeze()


@pytest.mark.parametrize("exp,state,value,ok", [
    (12, "known", 12, True), (12, "needs_review", 12, False), ("unknown", "unknown", None, True),
    ("unknown", "known", "x", False), ("review", "conflict", 3, True), ("contains:nut", "known", "tree nut", True),
    ("one_bill", "known", "ONE_BILL", True),
])
def test_field_matching(exp, state, value, ok):
    assert runner.field_matches(exp, state, value) is ok


def test_guessing_a_critical_unknown_is_flagged():
    assert runner.is_silent_guess("unknown", "known", 5)
    assert not runner.is_silent_guess("unknown", "needs_review", 5)


def test_case_scoring_end_to_end():
    cfg = load_config()
    sc = {s.id: s for s in dataset.load_split("development")}
    r = runner.run_case(sc["DEV-04"], OfflineRulesProvider(), "offline", cfg)
    assert r.status == "ok" and r.next_ok
    assert r.booking_checks[0]["ok"]  # original booking untouched
    r5 = runner.run_case(sc["DEV-05"], OfflineRulesProvider(), "offline", cfg)
    assert r5.event_checks == [{"event": "hold_expired", "expected": 1, "actual": 1, "ok": True}]


def test_budget_guard_stops_before_calling():
    cfg = load_config()
    sc = dataset.load_split("heldout")[0]
    r = runner.run_case(sc, OfflineRulesProvider(), "live", cfg, call_guard=lambda: False)
    assert r.status == "not_run_budget" and r.provider_calls == 0


def test_a28_live_without_credentials_is_not_run(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    why = runner.live_preconditions(10, 1.0, 1.0, 1.0)
    assert why and "ANTHROPIC_API_KEY" in why
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder-for-test")
    assert "spend limits" in runner.live_preconditions(None, None, None, None)
    p = runner.write_not_run(tmp_path, why, {"split": "heldout"})
    rec = json.loads(p.read_text())
    assert rec["status"] == "not_run" and "scores" not in rec


def test_study_plan_is_counterbalanced():
    plan = harness.build_plan()
    assert len(plan) == 36
    orders = {}
    for r in plan:
        orders.setdefault(r["case_id"], r["order"])
    from collections import Counter
    assert sorted(Counter(orders.values()).values()) == [2] * 6
    assert all(a["case_id"] != b["case_id"] for a, b in zip(plan, plan[1:]))


def test_study_timer_uses_only_recorded_events():
    t = iter([100.0, 160.0, 220.0, 230.0, 250.0, 400.0])
    s = harness.StudyStore(":memory:", clock=lambda: next(t))
    assert s.durations(1)["active_s"] is None  # nothing recorded -> no time
    for kind in ("start", "pause", "resume", "wait_start", "wait_end", "finish"):
        s.record(1, kind)
    d = s.durations(1)
    assert d == {"elapsed_s": 300.0, "active_s": 240.0, "paused_s": 60.0, "model_wait_s": 20.0}
    with pytest.raises(ValueError):
        s.record(1, "start")
    csv_text = harness.sessions_csv(s)
    assert csv_text.splitlines()[1].split(",")[9] == "240.0"
    assert harness.status(s)["sessions_completed"] == 1
