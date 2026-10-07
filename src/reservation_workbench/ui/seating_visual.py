"""Configuration-derived schematic; no claim about real restaurant geometry."""

from datetime import timedelta
import streamlit as st
from .components import esc, html_block, fmt_local
from ..rules.availability import blocking_occupancies


def option_label(wb, o):
    style = (
        "Adjacent tables"
        if o.split
        else ("Booth" if wb.cfg.table(o.table_ids[0]).style == "booth" else "Table")
    )
    return f"{o.area.title()} · {style.lower()} {' + '.join(o.table_ids)} · up to {o.capacity}"


def seating_svg(wb, v, option):
    req = option or v.assessment.request
    selected = set(option.table_ids) if option else set()
    occupied = {}
    for b in blocking_occupancies(wb.repo.list_bookings(), wb.now()):
        if v.booking and b.booking_id == v.booking.id:
            continue
        if (
            req
            and b.start < req.end
            and req.start
            < b.end + timedelta(minutes=wb.cfg.policies.turnover_buffer_minutes)
        ):
            for tid in b.table_ids:
                occupied[tid] = b.booking_id
    needs = v.facts.value("accessibility") == "step_free_required"
    s = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 450" role="img" aria-label="Seating schematic"><rect width="520" height="450" fill="#faf8f4"/>'
    ]
    for ai, area in enumerate(wb.cfg.areas):
        x, y = 8, 8 + 146 * ai
        s.append(
            f'<rect x="{x}" y="{y}" width="504" height="138" rx="12" fill="white" stroke="#dedbd4"/>'
        )
        label = area.title() + (
            " · stairs" if not wb.cfg.areas[area].step_free else " · step-free"
        )
        s.append(
            f'<text x="{x + 14}" y="{y + 26}" font-family="sans-serif" font-size="15" font-weight="600">{esc(label)}</text>'
        )
        for ti, t in enumerate(t for t in wb.cfg.tables if t.area == area):
            tx, ty = x + 12 + (ti % 4) * 122, y + 38 + (ti // 4) * 90
            blocked = needs and not t.step_free
            fill = (
                "#e8ecfb"
                if t.id in selected
                else "#fde7e7"
                if t.id in occupied or blocked
                else "#f5f4f0"
            )
            status = (
                "Preview"
                if t.id in selected
                else "Busy: " + occupied[t.id]
                if t.id in occupied
                else "Stairs conflict"
                if blocked
                else "Unoccupied"
            )
            s.append(
                f'<rect x="{tx}" y="{ty}" width="114" height="88" rx="9" fill="{fill}" stroke="#dedbd4"/>'
            )
            for dy, txt, size in [
                (24, t.id, 17),
                (47, f"{t.capacity} seats", 12),
                (70, status, 11),
            ]:
                s.append(
                    f'<text x="{tx + 9}" y="{ty + dy}" font-family="sans-serif" font-size="{size}" fill="#242421">{esc(txt)}</text>'
                )
    return "".join(s) + "</svg>"


def render_seating_visual(wb, v, option):
    html_block(seating_svg(wb, v, option))
    st.caption(
        "Demonstration schematic. Unoccupied tables must still satisfy capacity, access and grouping rules."
    )
    if option:
        st.caption(
            f"Preview interval: {fmt_local(option.start, wb.cfg.tz)}–{fmt_local(option.end, wb.cfg.tz, False)}"
        )
