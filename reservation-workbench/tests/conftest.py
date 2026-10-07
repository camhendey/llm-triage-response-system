from __future__ import annotations

import itertools
from datetime import datetime

import pytest

from reservation_workbench.domain.clock import FixedClock
from reservation_workbench.domain.config import load_config
from reservation_workbench.persistence.db import Database
from reservation_workbench.providers.offline import OfflineRulesProvider
from reservation_workbench.services.bootstrap import seed_bookings_only
from reservation_workbench.services.workbench import Workbench

T0 = datetime.fromisoformat("2026-11-10T10:00:00-05:00")
_counter = itertools.count()


def key(prefix: str = "t") -> str:
    return f"{prefix}:{next(_counter)}"


@pytest.fixture
def cfg():
    return load_config()


def make_wb(cfg, path=":memory:", clock=None, provider=None, seed=True) -> Workbench:
    db = Database.open(path)
    wb = Workbench(db, cfg, clock or FixedClock(T0), provider or OfflineRulesProvider(), mode="test")
    if seed:
        seed_bookings_only(wb)
    return wb


@pytest.fixture
def wb(cfg):
    return make_wb(cfg)


def new_inquiry(wb: Workbench, text: str, at: datetime = T0, label: str = "Synthetic Test Guest",
                interpret: bool = True) -> str:
    r = wb.create_inquiry(label, text, at, key=key("create"))
    assert r.ok, r.message
    iid = r.data["inquiry_id"]
    if interpret:
        ri = wb.interpret(iid)
        assert ri.ok, ri.message
    return iid


def add(wb: Workbench, iid: str, text: str, at: datetime = T0) -> None:
    assert wb.add_message(iid, text, at, key=key("msg")).ok
    wb.interpret(iid)


def approve_best(wb: Workbench, iid: str, unit: str | None = None, start=None) -> str:
    r = wb.propose(iid, key=key("prop"), unit_id=unit, start_override=start)
    assert r.ok, r.message
    pid = r.data["proposal_id"]
    a = wb.approve_proposal(pid, key=key("appr"))
    assert a.ok, a.message
    return pid


FULL = ("We are {n} guests on November 14, 2026 at {t}. No accessibility needs, no minors, no allergies. "
        "One bill, anniversary. Contact: test.guest@example.com")
