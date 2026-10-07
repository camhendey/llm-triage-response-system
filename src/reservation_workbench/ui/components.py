"""Small presentational helpers. Guest text is always HTML-escaped."""

from __future__ import annotations

import hashlib
import html
from datetime import datetime

import streamlit as st

CSS = """
<style>
:root {
  --rw-bg: #FAF8F4; --rw-panel: #FFFFFF; --rw-muted: #6B655C; --rw-line: #E4DED3; --rw-text: #1E1C19;
  --rw-cobalt: #2747C9; --rw-cobalt-bg: #E8ECFB; --rw-amber: #8A5A00; --rw-amber-bg: #FFF1D6;
  --rw-red: #A4161A; --rw-red-bg: #FDE7E7; --rw-green: #1F6B3A; --rw-green-bg: #E5F3E8; --rw-gray-bg: #EFEBE4;
}
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1600px; }
h1, h2, h3 { letter-spacing: -0.01em; }
h1 { font-size: 1.35rem !important; margin-bottom: 0.2rem !important; }
h2 { font-size: 1.12rem !important; }
h3 { font-size: 1.0rem !important; }
.rw-chip { display:inline-block; padding: 2px 8px; margin: 0 6px 4px 0; border-radius: 4px; font-size: 0.78rem;
  font-weight: 600; border: 1px solid var(--rw-line); background: var(--rw-gray-bg); color: var(--rw-text);
  white-space: nowrap; }
.rw-chip.cobalt { background: var(--rw-cobalt-bg); color: var(--rw-cobalt); border-color: #C5CEF4; }
.rw-chip.amber { background: var(--rw-amber-bg); color: var(--rw-amber); border-color: #F0D9A6; }
.rw-chip.red { background: var(--rw-red-bg); color: var(--rw-red); border-color: #F3C2C2; }
.rw-chip.green { background: var(--rw-green-bg); color: var(--rw-green); border-color: #BFDDC8; }
.rw-card { border: 1px solid var(--rw-line); background: var(--rw-panel); border-radius: 6px; padding: 10px 14px;
  margin-bottom: 10px; }
.rw-next { border-left: 4px solid var(--rw-cobalt); }
.rw-next .rw-label { font-size: 0.72rem; text-transform: uppercase; color: var(--rw-muted); letter-spacing: .04em; }
.rw-next .rw-action { font-size: 1.05rem; font-weight: 650; color: var(--rw-text); }
.rw-item { font-size: 0.86rem; margin: 3px 0; line-height: 1.35; }
.rw-item code { font-size: 0.74rem; }
.rw-tag { display:inline-block; min-width: 64px; font-size: 0.68rem; font-weight: 700; padding: 1px 5px;
  border-radius: 3px; margin-right: 6px; text-align:center; }
.rw-tag.blocker { background: var(--rw-red); color: #fff; }
.rw-tag.review { background: #B97800; color: #fff; }
.rw-tag.advisory { background: #8F887C; color: #fff; }
.rw-msg { border: 1px solid var(--rw-line); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px;
  background: #fff; }
.rw-msg .meta { font-size: 0.74rem; color: var(--rw-muted); margin-bottom: 4px; }
.rw-msg .body { white-space: pre-wrap; font-size: 0.9rem; color: var(--rw-text); }
.rw-msg mark { background: #FFF1D6; padding: 0 1px; }
.rw-muted { color: var(--rw-muted); font-size: 0.8rem; }
.rw-banner { font-size: 0.8rem; color: var(--rw-muted); border-bottom: 1px solid var(--rw-line); padding-bottom: 4px;
  margin-bottom: 8px; }
.rw-q { border: 1px solid var(--rw-line); border-radius: 6px; padding: 6px 8px; margin-bottom: 6px; background:#fff; }
.rw-q.sel { border-color: var(--rw-cobalt); box-shadow: inset 3px 0 0 var(--rw-cobalt); }
.rw-q .t { font-weight: 600; font-size: 0.86rem; }
.rw-q .s { font-size: 0.76rem; color: var(--rw-muted); }
table.rw-grid { border-collapse: collapse; font-size: 0.72rem; width: 100%; table-layout: fixed; }
table.rw-grid th, table.rw-grid td { border: 1px solid var(--rw-line); padding: 2px 3px; text-align: center;
  overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
table.rw-grid th.tbl { text-align: left; width: 110px; }
table.rw-grid td.conf { background: #D9E0FA; color: #1B2F86; font-weight: 600; }
table.rw-grid td.held { background: #FFE7B3; color: #6B4500; font-weight: 600; }
table.rw-grid td.cand { outline: 2px dashed var(--rw-cobalt); outline-offset: -2px; }
table.rw-facts { border-collapse: collapse; width: 100%; table-layout: fixed; font-size: 0.82rem; background: #fff; }
table.rw-facts th { text-align: left; font-size: 0.72rem; color: var(--rw-muted); font-weight: 600;
  border-bottom: 1px solid var(--rw-line); padding: 4px 6px; }
table.rw-facts td { border-bottom: 1px solid var(--rw-line); padding: 4px 6px; vertical-align: top; }
table.rw-facts td.f { font-weight: 600; }
table.rw-facts td.src { color: var(--rw-muted); font-size: 0.76rem; overflow-wrap: anywhere; }
table.rw-facts td { overflow-wrap: anywhere; }
table.rw-facts col.c1 { width: 24%; } table.rw-facts col.c2 { width: 22%; } table.rw-facts col.c3 { width: 18%; }
table.rw-facts .rw-chip { margin: 0; font-size: 0.7rem; }
div[data-testid="stExpander"] details summary p { font-size: 0.9rem; }
section[data-testid="stSidebar"][aria-expanded="true"] { width: 285px !important; min-width: 285px !important; }
.rw-summary { margin-bottom: 18px; display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.rw-summary span { font-size: .9rem; }
.rw-factcards { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin:16px 0; }
.rw-factcards div { border:1px solid #E4DED3; border-radius:8px; padding:10px; background:white; }
.rw-factcards small { display:block; color:#6B655C; font-size:.76rem; }
.rw-factcards strong { display:block; font-size:.92rem; margin-top:3px; overflow-wrap:anywhere; }
.rw-msg.outbound { border-left:3px solid #2747C9; background:#f3f5ff; }
.rw-msg .body { line-height:1.55; }
button p { white-space:normal !important; overflow:visible !important; text-overflow:clip !important; }
.rw-next { padding:16px 18px; }
h1 { font-size:1.8rem !important; line-height:1.2; }
h2 { font-size:1.45rem !important; }
h3 { font-size:1.05rem !important; margin-top:12px !important; }
@media (max-width: 1000px) {
  div[data-testid="stHorizontalBlock"] { flex-wrap:wrap !important; }
  div[data-testid="stColumn"] { flex:1 1 340px !important; min-width:min(340px,100%) !important; }
}
</style>
"""

TAG_LABEL = {"blocker": "BLOCKER", "review": "REVIEW", "advisory": "INFO"}


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s))


def chip(text: str, tone: str = "") -> str:
    return f'<span class="rw-chip {tone}">{esc(text)}</span>'


def html_block(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def fmt_local(dt: datetime | None, tz, with_date: bool = True) -> str:
    if dt is None:
        return "-"
    loc = dt.astimezone(tz)
    return loc.strftime("%a %b %d %H:%M") if with_date else loc.strftime("%H:%M")


def state_tone(state: str) -> str:
    return {"needs_review": "amber", "ready_for_action": "cobalt", "resolved": "green", "escalated": "amber",
            "awaiting_guest": "", "closed": "", "new": "cobalt"}.get(state, "")


def booking_tone(status: str) -> str:
    return {"confirmed": "green", "held": "amber", "cancelled": "", "released": "", "none": ""}.get(status, "")


def urgency_tone(u: str) -> str:
    return {"high": "red", "normal": "", "low": ""}.get(u, "")


def stable_hash(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def highlight(text: str, spans: list[tuple[int, int]]) -> str:
    """Escape guest text and wrap cited evidence spans in <mark>."""
    spans = sorted({(s, e) for s, e in spans if s is not None and e is not None and 0 <= s < e <= len(text)})
    out, pos = [], 0
    for s, e in spans:
        if s < pos:
            continue
        out.append(esc(text[pos:s]))
        out.append(f"<mark>{esc(text[s:e])}</mark>")
        pos = e
    out.append(esc(text[pos:]))
    return "".join(out)
