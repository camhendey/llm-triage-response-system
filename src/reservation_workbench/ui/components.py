"""Small presentational helpers. Guest text is always HTML-escaped."""

from __future__ import annotations

import hashlib
import html
from datetime import datetime

import streamlit as st

CSS = """
<style>
:root{--ink:#202734;--muted:#626b78;--line:#e2e5e9;--blue:#2747c9;--surface:#fff;--wash:#f7f8fa}
.block-container{padding-top:1.2rem;padding-bottom:2rem;max-width:1540px}
h1{font-size:1.85rem!important;letter-spacing:-.035em;line-height:1.2}
h2{font-size:1.5rem!important;letter-spacing:-.025em}
h3{font-size:1.06rem!important;letter-spacing:-.015em;margin-top:4px!important}
p,li{line-height:1.5}
button{min-height:38px}
button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid #2747c9!important;outline-offset:3px!important}
button p{white-space:normal!important;text-align:left}
section[data-testid="stSidebar"][aria-expanded="true"]{width:290px!important;min-width:290px!important}
[data-testid="stSidebar"] .block-container{padding-top:1rem}
[data-testid="stSidebar"] h3{font-size:1.05rem!important}
div[class*="st-key-open_"] button{justify-content:flex-start;text-align:left;background:transparent;border:1px solid transparent;border-radius:8px;padding:8px 10px;min-height:64px}
div[class*="st-key-open_"] button p{font-size:13px!important;line-height:1.35;margin:0!important}
div[class*="st-key-open_"] button[kind="primary"]{background:#e9edff;color:#203ca8;border-color:#c9d3fa;box-shadow:inset 3px 0 #2747c9}
div[class*="st-key-open_"] button:hover{background:#eef0f5;border-color:#dce1eb}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.65rem}
.rw-banner{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12px;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:20px}
.rw-banner strong{color:#414b5b;font-weight:600}
.rw-summary{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px;font-size:14px;font-variant-numeric:tabular-nums}
.rw-chip{display:inline-block;padding:3px 8px;border-radius:5px;font-size:12px;font-weight:600;line-height:1.4;color:#536071;background:#edf0f4}
.rw-chip.green{background:#e7f2ea;color:#205a37}.rw-chip.amber{background:#fff0d4;color:#79500b}.rw-chip.cobalt{background:#e9edff;color:#203ca8}.rw-chip.red{background:#fce9e9;color:#942a2a}
.rw-next{border:1px solid #d8dff3;border-left:3px solid var(--blue);background:#f4f6fe;border-radius:8px;padding:12px 16px;margin:6px 0 24px}
.rw-next strong{font-size:16px;color:var(--ink)}.rw-next div{font-size:13px;color:#526078;margin-top:3px}
.rw-msg{padding:14px 16px;background:white;border:1px solid var(--line);border-radius:9px;margin-bottom:10px}
.rw-msg.outbound{background:#f1f4fc;border-left:3px solid #879bdc}
.rw-msg .meta{font-size:12px;color:var(--muted);margin-bottom:8px}.rw-msg .body{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.6;color:var(--ink)}
.rw-detailgroup{margin-top:8px;padding:6px 0}.rw-label{text-transform:uppercase;letter-spacing:.055em;font-size:11px;font-weight:650;color:var(--muted);margin-bottom:8px}
.rw-detail{display:flex;gap:8px;align-items:baseline;border-bottom:1px solid #edf0f3;padding:7px 0;font-size:13px;flex-wrap:wrap}
.rw-detail>span:first-child{min-width:104px;color:var(--muted)}.rw-detail strong{font-weight:500;overflow-wrap:anywhere;flex:1}
.rw-booking{padding:14px 16px;background:#fff;border:1px solid var(--line);border-radius:8px;margin-bottom:16px;font-size:14px;line-height:1.6}
.rw-counts{display:flex;gap:32px;margin:24px 0 30px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:18px 0}
.rw-counts strong{display:block;font-size:28px;font-weight:600;line-height:1.2;color:var(--ink)}.rw-counts span{font-size:13px;color:var(--muted)}
table.rw-grid{border-collapse:collapse;font-size:12px;width:100%;min-width:900px;table-layout:fixed;font-variant-numeric:tabular-nums}
table.rw-grid th,table.rw-grid td{border:1px solid var(--line);padding:8px 4px;text-align:center;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
table.rw-grid th.tbl{text-align:left;width:112px;position:sticky;left:0;background:#f7f8fa;z-index:1}
table.rw-grid td.conf{background:#e4eafa;color:#253c82}table.rw-grid td.held{background:#fff0d4;color:#79500b}
.rw-muted{font-size:13px;color:var(--muted)}
@media(max-width:1100px){.block-container{padding-left:1.2rem;padding-right:1.2rem}section[data-testid="stSidebar"][aria-expanded="true"]{width:250px!important;min-width:250px!important}}
.rw-context-link{display:none}
@media(max-width:600px){.block-container{padding-top:3.8rem!important}}
@media(max-width:900px){.rw-context-link{display:block;margin:0 0 16px;font-size:14px}.st-key-workbody [data-testid="stHorizontalBlock"]{flex-direction:column!important;gap:24px!important}.st-key-workbody [data-testid="stColumn"]{width:100%!important;flex:1 1 100%!important;min-width:0!important}.st-key-workbody [data-testid="stColumn"]:nth-child(1){order:2}.st-key-workbody [data-testid="stColumn"]:nth-child(2){order:1}[data-testid="stMain"] .block-container>[data-testid="stVerticalBlock"]>[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}[data-testid="stMain"] .block-container>[data-testid="stVerticalBlock"]>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{flex:1 1 100%!important;min-width:0!important}.rw-banner{font-size:11px}.rw-counts{gap:20px}}
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
