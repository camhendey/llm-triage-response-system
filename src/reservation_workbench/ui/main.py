"""Streamlit entry point: sidebar, navigation and the shared Workbench instance."""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from ..domain.config import config_hash
from ..services.bootstrap import (
    ResetRefused,
    demo_db_path,
    open_workbench,
    reset_demo,
    session_db_path,
)
from ..services.csv_import import import_csv
from ..services.workbench import Workbench
from .components import CSS, esc, fmt_local, html_block, stable_hash

BANNER = "DEMO ENVIRONMENT · Synthetic restaurant and guests. Nothing here is sent to guests or synced to a booking system."


def _workbench(kind: str, path: str) -> Workbench:
    # One connection per browser session. SQLite coordinates writes across tabs.
    key = f"workbench_resource:{kind}:{path}"
    if key not in st.session_state:
        st.session_state[key] = open_workbench(kind, path)
    return st.session_state[key]


def _current_wb() -> Workbench:
    kind = st.session_state.get("db_kind", "demo")
    path = str(demo_db_path() if kind == "demo" else session_db_path())
    return _workbench(kind, path)


def sidebar(wb: Workbench) -> str:
    with st.sidebar:
        st.markdown("**Reservation Workbench**")
        st.caption("Sole developer · Cameron Hendey")
        view = st.radio(
            "View",
            ["Workbench", "Service view", "Operator study", "Policies & about"],
            key="view",
            label_visibility="collapsed",
        )
        st.divider()
        if view == "Workbench":
            from .workbench_view import render_queue

            render_queue(wb)
        with st.expander("Environment & settings"):
            kind = st.radio(
                "Database",
                ["demo", "session"],
                key="db_kind_pick",
                horizontal=True,
                index=0 if st.session_state.get("db_kind", "demo") == "demo" else 1,
                help="demo: fixed clock, resettable synthetic data. session: real clock, persistent.",
            )
            if kind != st.session_state.get("db_kind", "demo"):
                st.session_state["db_kind"] = kind
                st.session_state.pop("selected", None)
                st.rerun()
            tz = wb.cfg.tz
            st.caption(
                f"Clock ({'fixed demo' if wb.mode == 'demo' else 'system'}): "
                f"{fmt_local(wb.now(), tz)} {tz.key}"
            )
            if wb.mode == "demo":
                c1, c2 = st.columns(2)
                for col, label, delta in (
                    (c1, "+1 hour", timedelta(hours=1)),
                    (c2, "+1 day", timedelta(days=1)),
                ):
                    if col.button(label, key=f"clk_{label}", width="stretch"):
                        target = wb.now() + delta
                        res = wb.set_demo_clock(
                            target, key=f"ui:clock:{target.isoformat()}"
                        )
                        st.session_state["flash"] = (res.ok, res.message, False)
                        st.rerun()
            prov = wb.provider
            mode = getattr(prov, "mode", "?")
            if mode == "live_anthropic":
                ok = getattr(prov, "configured", False)
                st.caption(
                    f"Interpreter: live model ({prov.settings.model}) · API key "
                    f"{'present' if ok else 'MISSING - calls will fail and be shown as failed'}"
                )
            else:
                st.caption(
                    "Interpreter: offline pattern rules (not a language model). Set RW_PROVIDER=live and "
                    "ANTHROPIC_API_KEY to use the live model."
                )
            st.caption(f"Policy {wb.cfg.policy_version} · config {config_hash()[:10]}")
            with st.expander("Import messages (CSV)"):
                st.caption(
                    "Columns: guest_label, message, received_at (ISO, optional), inquiry_id (optional). "
                    "Rows are validated one by one; bad rows are reported, not guessed."
                )
                up = st.file_uploader(
                    "CSV file", type=["csv"], key="csv_up", label_visibility="collapsed"
                )
                if up is not None and st.button("Import rows", key="csv_go"):
                    content = up.getvalue()
                    rep = import_csv(
                        wb,
                        content,
                        batch_key=f"ui:csv:{stable_hash(content)}",
                        interpret=True,
                    )
                    if rep.fatal:
                        st.error(rep.fatal)
                    else:
                        st.success(
                            f"Imported {rep.imported} row(s); {rep.failed} rejected."
                        )
                        for r in rep.rows:
                            if not r.ok:
                                st.caption(f"Row {r.row}: {r.message}")
            if wb.mode == "demo":
                with st.expander("Reset demo data"):
                    st.caption(
                        f"Deletes and re-seeds only the designated demo database: {demo_db_path().name}"
                    )
                    if st.button("Reset demo database", key="reset_demo"):
                        try:
                            wb.db.close()
                            reset_demo()
                            for resource_key in list(st.session_state):
                                if str(resource_key).startswith("workbench_resource:"):
                                    del st.session_state[resource_key]
                            st.session_state.pop("selected", None)
                            st.session_state["flash"] = (
                                True,
                                "Demo database reset to its seeded state.",
                                False,
                            )
                        except ResetRefused as exc:
                            st.session_state["flash"] = (False, str(exc), False)
                        st.rerun()
    return view


def policies_page(wb: Workbench) -> None:
    st.caption(
        "Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025."
    )
    cfg = wb.cfg
    pol = cfg.policies
    st.markdown("# Policies & about")
    st.markdown(
        "This is a portfolio demonstration of a human-reviewed reservation workflow. The restaurant, guests and "
        "policies are **synthetic**. The policy values below are demo configuration, not the operating policy of "
        "any real restaurant. The workbench never sends messages and never reads or writes an external booking "
        "system; copying text or recording an action only writes to this local demo record."
    )
    tmap = {t.id: t for t in cfg.tables}
    rows = [
        ("Timezone", cfg.restaurant.timezone),
        (
            "Opening hours",
            f"{cfg.restaurant.opening_time:%H:%M}-{cfg.restaurant.closing_time:%H:%M} "
            "(seating must end by close)",
        ),
        (
            "Duration",
            f"{pol.default_duration_minutes} min; parties up to {pol.small_party_max}: "
            f"{pol.small_party_duration_minutes} min",
        ),
        ("Turnover buffer", f"{pol.turnover_buffer_minutes} min"),
        (
            "Hold expiry",
            f"{pol.hold_hours:g} h; short-notice holds need an operator-set deadline",
        ),
        (
            "Gratuity disclosure",
            f"{pol.auto_gratuity_percent:g}% for parties of {pol.auto_gratuity_min_party}+",
        ),
        (
            "Minimum-spend review",
            f"parties of {pol.minimum_spend_review_min_party}+ need human judgement",
        ),
        (
            "Maximum main-restaurant party",
            f"{cfg.restaurant.max_main_restaurant_party}; larger parties route to "
            "private events",
        ),
        (
            "Arrival heuristic",
            f"{pol.arrival_warning_party_count}+ parties of {pol.large_party_min_size}+ starting "
            f"in one {pol.arrival_bucket_minutes}-min clock bucket gives an advisory warning",
        ),
        ("Required for confirmation", ", ".join(pol.confirmation_required_fields)),
    ]
    st.table({"Policy": [r[0] for r in rows], "Demo value": [r[1] for r in rows]})
    st.markdown("**Tables and groupings**")
    st.dataframe(
        [
            {
                "Unit": t.id,
                "Kind": "table",
                "Area": t.area,
                "Seats": t.capacity,
                "Step-free": "yes" if t.step_free else "no (stairs)",
            }
            for t in cfg.tables
        ]
        + [
            {
                "Unit": g.id,
                "Kind": "grouping of " + "+".join(g.tables),
                "Area": tmap[g.tables[0]].area,
                "Seats": g.capacity,
                "Step-free": "yes"
                if all(tmap[t].step_free for t in g.tables)
                else "no (stairs)",
            }
            for g in cfg.groupings
        ],
        hide_index=True,
        width="stretch",
    )
    st.markdown("**Interpreter**")
    st.code(wb.provider.describe(), language=None, wrap_lines=True)


def run() -> None:
    from dotenv import load_dotenv

    load_dotenv()  # reads .env if present; existing environment variables win
    st.set_page_config(
        page_title="Reservation Operations Workbench",
        layout="wide",
        initial_sidebar_state="auto",
    )
    html_block(CSS)
    try:
        wb = _current_wb()
    except Exception as exc:
        st.error(f"Could not open the database: {exc}")
        st.stop()
    view = sidebar(wb)
    html_block(f'<div class="rw-banner">{esc(BANNER)}</div>')
    if view == "Workbench":
        from .workbench_view import render_workspace, show_flash

        sel = st.session_state.get("selected")
        if sel:
            if st.button("Back to overview", key="back_overview"):
                st.session_state.pop("selected", None)
                st.rerun()
            render_workspace(wb, sel)
        else:
            show_flash()
            st.markdown("# From guest request to a clear booking decision")
            st.markdown(
                "Review the conversation, compare suitable seating and prepare an accurate reply. Every booking action stays under your control."
            )
            cols = st.columns(3)
            for col, iid, title, body in zip(
                cols,
                ["INQ-0101", "INQ-0103", "INQ-0104"],
                [
                    "A straightforward booking",
                    "An accessibility conflict",
                    "A changing party size",
                ],
                [
                    "Review a complete request and confirm the arrangement.",
                    "Find step-free seating when the requested time is unavailable.",
                    "See how revised guest details change the plan.",
                ],
            ):
                with col:
                    st.markdown("### " + title)
                    st.write(body)
                    if st.button("Explore scenario", key="scenario_" + iid):
                        if wb.repo.get_inquiry(iid):
                            st.session_state["selected"] = iid
                            st.rerun()
                        else:
                            st.info(
                                "These examples are available in the demo environment. Create an inquiry from the sidebar."
                            )
            st.caption(
                "Original workflow developed at JOEY in 2024; refined in 2025. Sole developer: Cameron Hendey."
            )
    elif view == "Service view":
        from .service_view import render_service_view

        render_service_view(wb)
    elif view == "Operator study":
        from .study_view import render_study_view

        render_study_view()
    else:
        policies_page(wb)
