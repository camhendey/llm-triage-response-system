"""Headless Streamlit script run (streamlit.testing AppTest): every view renders without an exception.

This checks the Python side of the UI, not pixels; docs/screenshots come from scripts/capture_screenshots.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setenv("RW_DEMO_DB", str(tmp_path / "demo.sqlite"))
    monkeypatch.setenv("RW_SESSION_DB", str(tmp_path / "session.sqlite"))
    monkeypatch.setenv("RW_STUDY_DB", str(tmp_path / "study.sqlite"))
    monkeypatch.setenv("RW_PROVIDER", "offline")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    t = AppTest.from_file(APP, default_timeout=60)
    t.run()
    return t


def _text(t) -> str:
    return " ".join(m.value for m in t.markdown) + " ".join(c.value for c in t.caption)


@pytest.mark.ui
def test_every_view_renders_without_exception(at):
    assert not at.exception
    assert "Nothing here is sent" in _text(at)
    for view in ("Service", "Project", "Settings", "Inquiries"):
        at.sidebar.radio[0].set_value(view).run()
        assert not at.exception, view


@pytest.mark.ui
def test_opening_an_inquiry_shows_next_action_without_send_claims(at):
    at.button(key="open_INQ-0103").click().run()
    assert not at.exception
    txt = _text(at)
    assert "Offer checked alternative times" in txt
    assert "OpenTable" not in txt


@pytest.mark.ui
def test_confirmation_reply_handoff_and_unsaved_navigation(at):
    at.button(key="open_INQ-0101").click().run()
    at.button(key="suggest_INQ-0101").click().run()
    assert not at.exception
    at.button(key="confirm_INQ-0101").click().run()
    assert not at.exception
    assert "Confirmed" in _text(at)
    at.button(key="gen_INQ-0101").click().run()
    reply = next(x for x in at.text_area if x.label == "Reply")
    original = reply.value
    edited = original + "\nWe look forward to welcoming you."
    draft_id = reply.key.removeprefix("draft_text_")
    reply.set_value(edited).run()
    at.button(key="open_INQ-0103").click().run()
    # A confirmed inquiry is still reachable through All after handoff.
    at.selectbox(key="q_filter").set_value("All").run()
    at.button(key="open_INQ-0101").click().run()
    assert at.text_area(key="draft_text_" + draft_id).value == edited
    at.button(key="save_" + draft_id).click().run()
    at.button(key="approve_" + draft_id).click().run()
    assert not at.button(key="sent_" + draft_id).disabled
    at.button(key="sent_" + draft_id).click().run()
    assert not at.exception
    assert "Team reply · reported sent" in _text(at)
    assert "welcoming you" in _text(at)


@pytest.mark.ui
def test_typed_edit_invalidates_selected_plan(at):
    at.button(key="open_INQ-0101").click().run()
    at.button(key="suggest_INQ-0101").click().run()
    # Streamlit AppTest does not submit dialog fragments. The real Chromium
    # journey in capture_clean.py checks the modal form; here verify invalidation UI.
    from reservation_workbench.ui.main import demo_db_path
    wb = at.session_state['workbench_resource:demo:' + str(demo_db_path())]
    assert wb.set_facts('INQ-0101', {'party_size': 10}, 'Guest phoned', 'ui-test-change').ok
    at.run()
    assert not at.exception
    assert any('earlier arrangement is stale' in x.value for x in at.warning)
    assert '10 guests' in _text(at)
