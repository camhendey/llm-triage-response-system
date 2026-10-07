"""Headless Streamlit script run (streamlit.testing AppTest): every view renders without an exception.

This checks the Python side of the UI, not pixels; docs/screenshots come from scripts/capture_screenshots.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).resolve().parents[1] / "app.py")


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
    for view in ("Service view", "Operator study", "Policies & about", "Workbench"):
        at.sidebar.radio[0].set_value(view).run()
        assert not at.exception, view


@pytest.mark.ui
def test_opening_an_inquiry_shows_next_action_without_send_claims(at):
    at.button(key="open_INQ-0103").click().run()
    assert not at.exception
    txt = _text(at)
    assert "Offer checked alternative times" in txt
    assert "OpenTable" not in txt
