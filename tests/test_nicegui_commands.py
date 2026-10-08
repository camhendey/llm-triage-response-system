"""Safety at the new UI boundary, independent of rendering details."""

import pytest
from reservation_workbench.web.common import connection, execute, key


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("RW_DEMO_DB", str(tmp_path / "demo.sqlite"))
    monkeypatch.setenv("RW_SESSION_DB", str(tmp_path / "session.sqlite"))
    monkeypatch.setenv("RW_PROVIDER", "offline")
    with connection("demo") as wb:
        yield wb.load("INQ-0101")


def snapshot(v):
    return v.inquiry.id, v.inquiry.record_version, v.events[-1].id if v.events else None


def test_stale_screen_rejects_mutation(workspace):
    v = workspace
    with connection("demo") as wb:
        assert wb.set_fact(v.inquiry.id, "party_size", 10, "Corrected count", key()).ok
    r = execute(
        "demo",
        lambda wb: wb.set_fact(v.inquiry.id, "party_size", 12, "Old screen", key()),
        snapshot(v),
    )
    assert not r.ok
    with connection("demo") as wb:
        assert wb.load(v.inquiry.id).facts.value("party_size") == 10


def test_failed_grouped_edit_rolls_back_through_ui_boundary(workspace):
    v = workspace
    old = v.facts.value("contact_email")
    r = execute(
        "demo",
        lambda wb: wb.set_facts(
            v.inquiry.id,
            {"contact_email": None, "requested_date": "invalid"},
            "Correction",
            key(),
        ),
        snapshot(v),
    )
    assert not r.ok
    with connection("demo") as wb:
        assert wb.load(v.inquiry.id).facts.value("contact_email") == old


def test_repeated_command_key_creates_one_inquiry(workspace):
    k = key()
    fn = lambda wb: wb.create_inquiry("Retry guest", "Table for six please", None, k)
    a = execute("demo", fn)
    b = execute("demo", fn)
    assert a.ok and b.ok and b.duplicate
    with connection("demo") as wb:
        assert sum(v.inquiry.guest_label == "Retry guest" for v in wb.queue()) == 1


def test_draft_edit_without_record_version_bump_rejects_old_review(workspace):
    with connection("demo") as wb:
        assert wb.generate_draft(workspace.inquiry.id, key()).ok
        v = wb.load(workspace.inquiry.id)
        d = v.latest_draft
        assert wb.save_draft_edit(d.id, d.text + "\nThank you.", key()).ok
        assert wb.load(v.inquiry.id).inquiry.record_version == v.inquiry.record_version
    r = execute("demo", lambda wb: wb.approve_draft(d.id, key()), snapshot(v))
    assert not r.ok and r.code == "stale_screen"
    with connection("demo") as wb:
        assert wb.load(v.inquiry.id).latest_draft.status != "approved"


def test_connections_and_databases_are_separate(workspace):
    with connection("demo") as a, connection("demo") as b, connection("session") as c:
        assert a.db.conn is not b.db.conn
        assert a.db.path != c.db.path
        assert c.repo.get_inquiry("INQ-0101") is None


def test_empty_optional_database_paths_use_defaults(monkeypatch):
    from reservation_workbench.services.bootstrap import (
        demo_db_path,
        session_db_path,
        DEMO_DB_PATH,
        SESSION_DB_PATH,
    )

    monkeypatch.setenv("RW_DEMO_DB", "")
    monkeypatch.setenv("RW_SESSION_DB", "")
    assert demo_db_path() == DEMO_DB_PATH.resolve()
    assert session_db_path() == SESSION_DB_PATH.resolve()
