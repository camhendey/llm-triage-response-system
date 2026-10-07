"""Day-level occupancy grid and the large-party arrival heuristic."""

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from ..rules.availability import arrival_buckets, blocking_occupancies
from ..services.workbench import Workbench
from .components import esc, html_block


def render_service_view(wb: Workbench) -> None:
    cfg = wb.cfg
    tz = cfg.tz
    now = wb.now()
    bookings = wb.repo.list_bookings()
    occ = blocking_occupancies(bookings, now)
    days = sorted({o.start.astimezone(tz).date() for o in occ}) or [
        now.astimezone(tz).date()
    ]
    st.markdown("# Service view")
    st.caption(
        "Confirmed bookings and unexpired demo holds as recorded in this workbench. Released, cancelled and "
        "expired holds do not block tables. This is not an external booking system."
    )
    default_day = next((d for d in days if d >= now.astimezone(tz).date()), days[0])
    day = st.date_input("Service date", value=default_day, key="svc_day")
    open_t, close_t = cfg.restaurant.opening_time, cfg.restaurant.closing_time
    step = 30
    slots = []
    cur = datetime.combine(day, open_t, tzinfo=tz)
    end = datetime.combine(day, close_t, tzinfo=tz)
    while cur < end:
        slots.append(cur)
        cur = (
            cur.astimezone(tz).replace(tzinfo=None) + timedelta(minutes=step)
        ).replace(tzinfo=tz)
    day_occ = [o for o in occ if o.start.astimezone(tz).date() == day]
    head = "".join(
        f"<th>{s.strftime('%H:%M') if s.minute == 0 else ''}</th>" for s in slots
    )
    rows = []
    for t in cfg.tables:
        cells = []
        i = 0
        while i < len(slots):
            s0 = slots[i]
            hit = next(
                (
                    o
                    for o in day_occ
                    if t.id in o.table_ids
                    and o.start < s0 + timedelta(minutes=step)
                    and s0 < o.end
                ),
                None,
            )
            if not hit:
                cells.append("<td></td>")
                i += 1
                continue
            span = 1
            while i + span < len(slots) and slots[i + span] < hit.end:
                span += 1
            cls = "conf" if hit.status == "confirmed" else "held"
            label = f"{hit.booking_id} · {hit.party_size}"
            cells.append(
                f'<td class="{cls}" colspan="{span}" title="{esc(hit.booking_id)} {esc(hit.status)} '
                f'{esc(hit.guest_label)}">{esc(label)}</td>'
            )
            i += span
        access = "" if t.step_free else " ⚠ stairs"
        rows.append(
            f'<tr><th class="tbl">{esc(t.id)} · {t.capacity}{access}</th>{"".join(cells)}</tr>'
        )
    html_block(
        f'<div style="overflow-x:auto"><table class="rw-grid"><tr><th class="tbl">Table · seats</th>'
        f"{head}</tr>{''.join(rows)}</table></div>"
    )
    html_block(
        '<div class="rw-muted" style="margin-top:4px">Legend: <span class="rw-chip" '
        'style="background:#D9E0FA;color:#1B2F86">confirmed</span><span class="rw-chip" '
        'style="background:#FFE7B3;color:#6B4500">demo hold</span> Cells are 30-minute slots; '
        '"stairs" marks tables without step-free access.</div>'
    )
    st.markdown("### Large-party arrivals (heuristic)")
    st.caption(
        f"Counts parties of {cfg.policies.large_party_min_size}+ by local clock-hour start. "
        f"{cfg.policies.arrival_warning_party_count} or more in one bucket raises an advisory only; it is "
        "not a kitchen-capacity model."
    )
    buckets = arrival_buckets(cfg, bookings, now, day)
    if not buckets:
        st.info("No large parties start on this date.")
    else:
        st.dataframe(
            [
                {
                    "Bucket start": b.bucket_start.strftime("%H:%M"),
                    "Large parties": b.count,
                    "Bookings": ", ".join(f"{lbl} ({n})" for lbl, n in b.large_parties),
                    "Heuristic": "WARNING"
                    if b.count >= cfg.policies.arrival_warning_party_count
                    else "ok",
                }
                for b in buckets
            ],
            hide_index=True,
            width="stretch",
        )
    if not day_occ:
        st.caption("No blocking bookings on this date.")

    from ..services.handoff import daily_handoff, handoff_csv

    st.markdown("### Service handoff")
    rows = daily_handoff(wb, day)
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
        st.download_button(
            "Export service handoff",
            handoff_csv(rows),
            file_name=f"service-handoff-{day}.csv",
            mime="text/csv",
        )
    else:
        st.caption("No active bookings to hand over on this date.")
