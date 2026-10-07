"""Arrival briefing first; precise time grid and complete export on demand."""

from datetime import datetime, timedelta
import streamlit as st
from ..rules.availability import arrival_buckets, blocking_occupancies
from ..services.handoff import daily_handoff, handoff_csv
from .components import esc, html_block, chip


def render_service_view(wb):
    st.markdown("# Service")
    st.caption("Confirmed bookings and active holds in this workspace.")
    bookings = wb.repo.list_bookings()
    occ = blocking_occupancies(bookings, wb.now())
    days = sorted({o.start.astimezone(wb.cfg.tz).date() for o in occ}) or [
        wb.now().astimezone(wb.cfg.tz).date()
    ]
    c1, c2 = st.columns([1, 2])
    with c1:
        day = st.date_input("Service date", value=days[0], key="svc_day")
    with c2:
        view = st.radio(
            "View", ["Arrivals", "Timeline"], horizontal=True, key="service_layout"
        )
    rows = daily_handoff(wb, day)
    total = sum(r["Guests"] for r in rows)
    html_block(
        '<div class="rw-counts">'
        + f"<div><strong>{len(rows)}</strong><span>Active bookings</span></div><div><strong>{total}</strong><span>Guests, including holds</span></div><div><strong>{sum(bool(r['Outstanding']) for r in rows)}</strong><span>Need attention</span></div></div>"
    )
    buckets = arrival_buckets(wb.cfg, bookings, wb.now(), day)
    for bucket in buckets:
        if bucket.count >= wb.cfg.policies.arrival_warning_party_count:
            st.warning(
                f"{bucket.count} large parties arrive around {bucket.bucket_start:%H:%M}. Review service pacing."
            )
    if buckets:
        st.caption(
            "Arrival counts are a simple pacing prompt, not a kitchen-capacity prediction."
        )
    if not rows:
        st.info("No active bookings for this date. Choose another date.")
        return
    if view == "Timeline":
        render_timeline(wb, day, occ)
    else:
        for r in rows:
            with st.container(border=True):
                html_block(
                    f'<div class="rw-summary"><strong>{esc(r["Start"])} · {esc(r["Guest"])} · {r["Guests"]} guests</strong>{chip(r["Status"], "green" if r["Status"] == "Confirmed" else "amber")}</div>'
                )
                st.caption(f"{r['Tables']} · until {r['End']} · {r['Billing']}")
                important = []
                for key in ["Accessibility", "Allergies"]:
                    value = r[key]
                    if value not in ("none", "None reported"):
                        important.append(f"{key}: {value}")
                if important:
                    st.write(" · ".join(important))
                if r["Occasion"] not in ("Not recorded", "none"):
                    st.caption("Occasion: " + r["Occasion"])
                if r["Outstanding"]:
                    st.warning(r["Outstanding"])
                if r["Status"] == "Held":
                    st.caption("Hold expires: " + r["Hold expires"])
                booking = wb.repo.get_booking(r["Booking"])
                if (
                    booking
                    and booking.inquiry_id
                    and st.button("Open inquiry", key="service_" + r["Booking"])
                ):
                    from .workbench_view import select_inquiry

                    select_inquiry(wb, booking.inquiry_id)
    st.download_button(
        "Export service handoff",
        handoff_csv(rows),
        file_name=f"service-handoff-{day}.csv",
        mime="text/csv",
    )
    with st.expander("Complete handoff table"):
        st.dataframe(rows, hide_index=True, width="stretch")


def render_timeline(wb, day, occ):
    period = st.radio(
        "Time range", ["Dinner", "All day"], horizontal=True, key="service_period"
    )
    cfg = wb.cfg
    tz = cfg.tz
    start = datetime.combine(day, cfg.restaurant.opening_time, tzinfo=tz)
    end = datetime.combine(day, cfg.restaurant.closing_time, tzinfo=tz)
    if period == "Dinner":
        start = max(start, start.replace(hour=16, minute=0))
    slots = []
    t = start
    while t < end:
        slots.append(t)
        t += timedelta(minutes=15)
    head = "".join(
        f"<th>{s:%H:%M}</th>" if s.minute == 0 else "<th></th>" for s in slots
    )
    rows = []
    for table in cfg.tables:
        cells = []
        i = 0
        while i < len(slots):
            slot = slots[i]
            hit = next(
                (
                    b
                    for b in occ
                    if table.id in b.table_ids
                    and b.start < slot + timedelta(minutes=15)
                    and slot < b.end
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
            label = f"{hit.guest_label.replace('Synthetic Guest ', 'Guest ')} · {hit.party_size}"
            detail = f"{label} · {hit.start.astimezone(tz):%H:%M}–{hit.end.astimezone(tz):%H:%M} · {hit.status}"
            cells.append(
                f'<td class="{"conf" if hit.status == "confirmed" else "held"}" colspan="{span}" title="{esc(detail)}">{esc(label)}</td>'
            )
            i += span
        rows.append(
            f'<tr><th class="tbl">{table.id} · {table.capacity}{" · stairs" if not table.step_free else ""}</th>{"".join(cells)}</tr>'
        )
    html_block(
        f'<div style="overflow-x:auto" tabindex="0" role="region" aria-label="Service occupancy timeline"><table class="rw-grid"><tr><th class="tbl">Table · seats</th>{head}</tr>{"".join(rows)}</table></div>'
    )
    st.caption(
        "15-minute grid. Blue: confirmed. Amber: hold. Use the arrival list for exact times and guest requirements."
    )
    day_bookings = [b for b in occ if b.start.astimezone(tz).date() == day]
    if day_bookings:
        ids = [b.booking_id for b in day_bookings]
        chosen = st.selectbox(
            "Open a booking",
            ids,
            format_func=lambda x: next(
                f"{b.guest_label} · {b.start.astimezone(tz):%H:%M}"
                for b in day_bookings
                if b.booking_id == x
            ),
        )
        if st.button("View booking details", key="timeline_open"):
            b = wb.repo.get_booking(chosen)
            if b and b.inquiry_id:
                from .workbench_view import select_inquiry

                select_inquiry(wb, b.inquiry_id)
