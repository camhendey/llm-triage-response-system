"""Focused coordinator workspace: source context beside one active task."""

from __future__ import annotations
from datetime import date, datetime, time, timedelta
import json
import re
import uuid
import streamlit as st
import streamlit.components.v1 as components
from ..domain.models import (
    Direction,
    ENUM_VALUES,
    FIELD_LABELS,
    FieldName,
    BookingStatus,
    ProposalStatus,
    ProposalKind,
)
from ..services.workbench import Workbench, InquiryView
from ..services.presentation import (
    response_status,
    work_status,
    next_step,
    sent_event,
    unread,
    hold_urgency,
    referral_done,
)
from ..services.drafting import (
    PURPOSES,
    allowed_purposes,
    resolve_purpose,
    selected_option,
)
from ..rules.availability import hold_is_active
from .components import chip, esc, html_block, fmt_local, stable_hash
from .seating_visual import option_label, render_seating_visual

LABELS = {
    "none": "None reported",
    "step_free_required": "Step-free required",
    "other_needs": "Other access needs",
    "present": "Minors attending",
    "one_bill": "One bill",
    "separate_bills": "Separate bills",
    "no_preference": "No preference",
    "yes": "Yes",
    "no": "No",
}
GROUPS = {
    "Reservation": [
        "party_size",
        "requested_date",
        "requested_time",
        "requested_duration_minutes",
    ],
    "Requirements": ["accessibility", "allergies", "minors", "billing"],
    "Guest & preferences": [
        "guest_name",
        "contact_email",
        "contact_phone",
        "occasion",
        "preferred_area",
        "preferred_table",
        "split_seating_ok",
    ],
}


def pretty(value):
    return (
        "Not provided"
        if value is None
        else LABELS.get(str(value), str(value).replace("_", " "))
    )


def guest(v):
    return v.facts.value("guest_name") or v.inquiry.guest_label.replace(
        "Synthetic Guest ", "Guest "
    )


def k(v, action, *extra):
    return f"ui:{action}:{v.inquiry.id}:v{v.inquiry.record_version}:e{len(v.events)}:{stable_hash(*extra)}"


def finish(r, iid=None, stage=None):
    if r.ok and iid and stage:
        st.session_state["stage_request"] = (iid, stage)
    st.session_state["flash"] = (r.ok, r.message, False)
    st.rerun()


def show_flash():
    f = st.session_state.pop("flash", None)
    if f:
        if f[0]:
            st.toast("Saved", duration="short")
        else:
            st.error(f[1])


def select_inquiry(wb, iid):
    v = wb.load(iid)
    if unread(v):
        wb.mark_conversation_reviewed(iid, k(v, "read", max(m.seq for m in v.messages)))
    st.session_state["selected"] = iid
    st.session_state["nav_request"] = "Inquiries"
    st.rerun()


@st.dialog("New inquiry", width="large")
def new_inquiry(wb):
    st.caption("Paste the guest’s message. Missing details stay unknown.")
    with st.form("new_inquiry_form"):
        name = st.text_input("Guest name", max_chars=80, key="new_name")
        txt = st.text_area(
            "Guest message", height=220, max_chars=5000, key="new_message"
        )
        submit = st.form_submit_button("Create inquiry", type="primary")
    if submit:
        r = wb.create_inquiry(name, txt, wb.now(), key="ui:create:" + uuid.uuid4().hex)
        if not r.ok:
            st.error(r.message)
            return
        iid = r.data["inquiry_id"]
        if wb.provider.mode == "offline_rules":
            wb.interpret(iid)
        select_inquiry(wb, iid)


def render_queue(wb):
    if st.button("New inquiry", key="new_inquiry", type="primary", width="stretch"):
        st.session_state["new_name"] = ""
        st.session_state["new_message"] = ""
        new_inquiry(wb)
    views = wb.queue()
    filters = [
        "Active",
        "Needs attention",
        "New replies",
        "Holds expiring",
        "Reply pending",
        "Ready to finalize",
        "Waiting for guest",
        "Referral pending",
        "Completed",
        "All",
    ]

    def matches(v, f):
        status = work_status(v)
        if f == "All":
            return True
        if f == "Active":
            return status not in ("Closed", "Completed", "Referral recorded") or (
                status == "Referral recorded" and not sent_event(v)
            )
        if f == "New replies":
            return unread(v)
        if f == "Holds expiring":
            return bool(hold_urgency(v))
        if f == "Needs attention":
            return status in ("Needs attention", "Change requested", "Referral pending")
        if f == "Completed":
            return status in ("Completed", "Closed") or (
                status == "Referral recorded" and bool(sent_event(v))
            )
        return status == f

    counts = {f: sum(matches(v, f) for v in views) for f in filters}
    flt = st.selectbox(
        "Show inquiries",
        filters,
        format_func=lambda x: f"{x} ({counts[x]})",
        key="q_filter",
        label_visibility="collapsed",
    )
    q = st.text_input(
        "Search inquiries",
        placeholder="Search guest or message",
        key="q_search",
        label_visibility="collapsed",
    )
    with st.expander("Sort"):
        order = st.radio(
            "Order",
            ["Priority", "Reservation date", "Guest name"],
            key="q_sort",
            label_visibility="collapsed",
        )
    shown = [
        v
        for v in views
        if matches(v, flt)
        and (
            not q
            or q.casefold()
            in " ".join(
                [
                    guest(v),
                    v.inquiry.guest_label,
                    str(v.facts.value("contact_email") or ""),
                    str(v.facts.value("contact_phone") or ""),
                    *(m.text for m in v.messages),
                ]
            ).casefold()
        )
    ]
    if order == "Guest name":
        shown.sort(key=lambda v: guest(v).casefold())
    elif order == "Reservation date":
        shown.sort(
            key=lambda v: v.facts.dining_start or datetime.max.replace(tzinfo=wb.cfg.tz)
        )
    st.caption(f"{len(shown)} inquiries · {order.lower()}")
    if not shown:
        st.info("No matching inquiries. Change the filter or search.")
    for v in shown:
        when = (
            fmt_local(v.facts.dining_start, wb.cfg.tz)
            if v.facts.dining_start
            else "Date / time needed"
        )
        status = work_status(v)
        extra = status + ((" · " + hold_urgency(v)) if hold_urgency(v) else "")
        label = f"{guest(v)} · {v.facts.value('party_size') or '?'} guests\n\n{when} · {extra}"
        if st.button(
            label,
            key="open_" + v.inquiry.id,
            width="stretch",
            type="primary"
            if st.session_state.get("selected") == v.inquiry.id
            else "secondary",
        ):
            select_inquiry(wb, v.inquiry.id)


def render_home(wb):
    show_flash()
    st.markdown("# Inquiries")
    st.write("Review guest requests, choose seating and complete the reply.")
    views = wb.queue()
    active = [
        v
        for v in views
        if work_status(v) not in ("Completed", "Closed")
        and not (work_status(v) == "Referral recorded" and sent_event(v))
    ]
    counts = [
        ("Active", len(active)),
        (
            "Needs attention",
            sum(
                work_status(v)
                in ("Needs attention", "Change requested", "Referral pending")
                for v in views
            ),
        ),
        ("Replies pending", sum(work_status(v) == "Reply pending" for v in views)),
    ]
    html_block(
        '<div class="rw-counts">'
        + "".join(
            f"<div><strong>{n}</strong><span>{label}</span></div>"
            for label, n in counts
        )
        + "</div>"
    )
    st.markdown("### Next to review")
    for v in active[:3]:
        with st.container(border=True):
            st.markdown(f"**{guest(v)} · {v.facts.value('party_size') or '?'} guests**")
            st.caption(next_step(v)[0])
            if st.button("Open inquiry", key="home_" + v.inquiry.id):
                select_inquiry(wb, v.inquiry.id)
    if not active:
        st.success("No active inquiries. Create a new inquiry to begin.")
    st.caption("New to this project? Guided examples and evaluation are under Project.")


def human_issue(text):
    text = re.sub(r"R-[A-Z-]+:\s*", "", text)
    text = re.sub(
        r"capacity (\d+) < party (\d+)", r"Seats \1; this party needs \2", text
    )
    return (
        text.replace("G_L3_L4", "Lounge booths L3 + L4")
        .replace("stale", "out of date")
        .replace("operator-confirmed", "reviewed")
    )


def render_workspace(wb, iid):
    v = wb.load(iid)
    show_flash()
    request = st.session_state.pop("stage_request", None)
    if request:
        st.session_state["stage_" + request[0]] = request[1]
    top, back = st.columns([5, 1])
    with top:
        st.markdown("## " + esc(guest(v)))
    if back.button("Inbox", key="back_overview", width="stretch"):
        st.session_state.pop("selected", None)
        st.rerun()
    status = v.booking.status.value.title() if v.booking else "Not booked"
    when = (
        fmt_local(v.facts.dining_start, wb.cfg.tz)
        if v.facts.dining_start
        else "Date or time needed"
    )
    html_block(
        f'<div class="rw-summary"><span>{esc(v.facts.value("party_size") or "?")} guests · {esc(when)}</span>{chip(status, "green" if status == "Confirmed" else "")}{chip("Reply: " + response_status(v), "amber" if response_status(v) in ("Needs review", "Update needed") else "")}</div>'
    )
    title, detail = next_step(v)
    html_block(
        f'<div class="rw-next"><strong>{esc(title)}</strong><div>{esc(detail)}</div></div>'
    )
    if hold_urgency(v):
        st.warning(
            hold_urgency(v) + " · " + fmt_local(v.booking.hold_expires_at, wb.cfg.tz)
        )
    html_block('<a class="rw-context-link" href="#guest-request">Read guest message and details ↓</a>')
    with st.container(key="workbody"):
        left, right = st.columns([1, 1.05], gap="large")
        with left:
            html_block('<div id="guest-request"></div>')
            st.markdown("### Conversation")
            render_conversation(wb, v)
            st.markdown("### Guest details")
            render_facts(wb, v)
        with right:
            default = (
                "Reply"
                if work_status(v)
                in ("Reply pending", "Waiting for guest", "Completed", "Referral recorded")
                else "Plan"
            )
            sk = "stage_" + iid
            if sk not in st.session_state:
                st.session_state[sk] = default
            stage = st.radio(
                "Working on",
                ["Plan", "Reply"],
                key=sk,
                horizontal=True,
                label_visibility="collapsed",
            )
            if stage == "Plan":
                render_plan(wb, v)
            else:
                render_draft(wb, v)
    with st.expander("Activity & evidence"):
        render_history(wb, v)
        with st.expander("Technical details"):
            render_diagnostics(wb, v)


def message_card(wb, m):
    outgoing = m.direction == Direction.OUTBOUND_REPORTED
    label = "Team reply · reported sent" if outgoing else "Guest"
    html_block(
        f'<div class="rw-msg {"outbound" if outgoing else ""}"><div class="meta">{label} · {esc(fmt_local(m.received_at, wb.cfg.tz))}</div><div class="body">{esc(m.text)}</div></div>'
    )


def render_conversation(wb, v):
    old = v.messages[:-2]
    recent = v.messages[-2:]
    if old:
        with st.expander(f"{len(old)} earlier messages"):
            for m in old:
                message_card(wb, m)
    for m in recent:
        message_card(wb, m)
    changed = [
        f"{FIELD_LABELS[f.field.value]}: {pretty(f.changed_from[-1])} → {pretty(f.value)}"
        for f in v.facts.fields.values()
        if f.changed_from
    ]
    if changed:
        with st.expander("Recorded changes"):
            for text in changed:
                st.write(text)
    if wb.pending_message_ids(v.inquiry.id):
        if st.button(
            "Interpret new message", key="interp_" + v.inquiry.id, type="primary"
        ):
            with st.spinner("Reading the message…"):
                r = wb.interpret(v.inquiry.id)
            finish(r, v.inquiry.id, "Plan")
    with st.expander("Add guest reply"):
        # Do not clear submitted text until successful; rejected input remains editable.
        with st.form("addmsg_" + v.inquiry.id):
            txt = st.text_area(
                "Guest reply",
                height=120,
                max_chars=5000,
                key=f"newmsg_{v.inquiry.id}_{len(v.messages)}",
            )
            submitted = st.form_submit_button("Add reply")
        if submitted:
            r = wb.add_message(v.inquiry.id, txt, wb.now(), key=k(v, "msg", txt))
            if not r.ok:
                st.error(r.message)
            else:
                if wb.provider.mode == "offline_rules":
                    wb.interpret(v.inquiry.id)
                fresh = wb.load(v.inquiry.id)
                wb.mark_conversation_reviewed(
                    v.inquiry.id, k(fresh, "read", len(fresh.messages))
                )
                finish(r, v.inquiry.id, "Plan")


@st.dialog("Edit guest details", width="large")
def edit_details(wb, iid, group):
    v = wb.load(iid)
    fields = GROUPS[group]
    st.markdown("**" + group + "**")
    st.caption(
        "Save only the details you intend to change. Clearing a value marks it unknown and keeps its history."
    )
    with st.form("edit_" + iid + "_" + group):
        values = {}
        cols = st.columns(2)
        for index, n in enumerate(fields):
            old = v.facts.get(n).value
            label = FIELD_LABELS[n]
            key = f"edit_{iid}_{group}_{n}_{v.inquiry.record_version}"
            with cols[index % 2]:
                if n in ENUM_VALUES:
                    opts = [None, *ENUM_VALUES[n]]
                    values[n] = st.selectbox(
                        label,
                        opts,
                        index=opts.index(old) if old in opts else 0,
                        format_func=pretty,
                        key=key,
                    )
                elif n == "requested_date":
                    values[n] = st.date_input(
                        label, value=date.fromisoformat(old) if old else None, key=key
                    )
                elif n == "requested_time":
                    values[n] = st.text_input(label + " (24-hour)", value=str(old or ""), placeholder="19:30", key=key)
                elif n in ("party_size", "requested_duration_minutes"):
                    values[n] = st.number_input(
                        label,
                        min_value=1,
                        max_value=500,
                        value=int(old) if old else None,
                        key=key,
                    )
                else:
                    values[n] = st.text_input(label, value=str(old or ""), key=key)
        clear = st.multiselect(
            "Mark unknown",
            fields,
            format_func=lambda n: FIELD_LABELS[n],
            help="Explicitly remove a current value without deleting its history.",
        )
        reason = st.text_input("Source or reason", value="Coordinator review")
        submitted = st.form_submit_button("Save details", type="primary")
    if submitted:
        changes = {}
        for n, val in values.items():
            if isinstance(val, time):
                val = val.strftime("%H:%M")
            elif isinstance(val, date):
                val = val.isoformat()
            if n in clear or val == "":
                val = None
            if val != v.facts.get(n).value:
                changes[n] = val
        if not changes:
            st.info("No changes to save.")
            return
        r = wb.set_facts(
            iid, changes, reason, k(v, "details", changes), v.inquiry.record_version
        )
        if r.ok:
            finish(r, iid, "Plan")
        else:
            st.error(r.message)


def render_facts(wb, v):
    for group, fields in GROUPS.items():
        # Preferences remain available without occupying the primary reading area.
        shown = (
            fields if group != "Guest & preferences" else ["contact_email", "occasion"]
        )
        rows = []
        for n in shown:
            f = v.facts.get(n)
            if n == "requested_duration_minutes" and f.value is None:
                rows.append(f'<div class="rw-detail"><span>Duration</span><strong>{v.facts.duration_minutes or "—"} minutes · policy default</strong></div>')
                continue
            badge = (
                "Review needed"
                if f.state in ("conflict", "needs_review")
                else "Unknown"
                if f.state == "unknown"
                else ""
            )
            rows.append(
                f'<div class="rw-detail"><span>{esc(FIELD_LABELS[n])}</span><strong>{esc(pretty(f.value))}</strong>{chip(badge, "amber") if badge else ""}</div>'
            )
        html_block(
            '<div class="rw-detailgroup"><div class="rw-label">'
            + group
            + "</div>"
            + "".join(rows)
            + "</div>"
        )
        if st.button(
            "Edit " + group.lower(), key="editgroup_" + group + "_" + v.inquiry.id
        ):
            edit_details(wb, v.inquiry.id, group)
    reviews = [
        f for f in v.facts.fields.values() if f.state in ("conflict", "needs_review")
    ]
    if reviews:
        with st.container(border=True):
            st.markdown("**Details needing review**")
            for f in reviews:
                st.markdown(f"**{FIELD_LABELS[f.field.value]} · {pretty(f.value)}**")
                if f.current:
                    st.caption(
                        f.current.quote or f.current.note or "Recorded by coordinator"
                    )
                if f.value is not None and st.button(
                    "Keep / confirm " + pretty(f.value),
                    key=f"keep_{v.inquiry.id}_{f.field.value}",
                ):
                    finish(
                        wb.confirm_fact(
                            v.inquiry.id,
                            f.field.value,
                            k(v, "confirmfield", f.field.value),
                            v.inquiry.record_version,
                        )
                    )
                for index, o in enumerate(f.conflicts):
                    st.caption("Guest: " + str(o.quote or o.note or ""))
                    if st.button(
                        "Use " + pretty(o.value),
                        key=f"use_{v.inquiry.id}_{f.field.value}_{index}",
                    ):
                        finish(
                            wb.set_fact(
                                v.inquiry.id,
                                f.field.value,
                                o.value,
                                "Resolved guest correction",
                                k(v, "resolve", f.field.value, o.value),
                                v.inquiry.record_version,
                            )
                        )
    with st.expander("Sources for these details"):
        for f in v.facts.fields.values():
            if f.current:
                st.markdown(
                    "**" + FIELD_LABELS[f.field.value] + "** · " + pretty(f.value)
                )
                st.caption(f.current.quote or f.current.note or "Coordinator record")


@st.dialog("Review booking action")
def booking_action(wb, iid, action):
    v = wb.load(iid)
    labels = {
        "cancel": "Cancel booking",
        "release": "Release hold",
        "decline": "Decline request",
        "close": "Close inquiry",
        "reopen": "Reopen inquiry",
        "referral": "Record referral completed",
        "escalate": "Flag for private-events review",
    }
    st.markdown("**" + labels[action] + " · " + guest(v) + "**")
    if v.booking and action in ("cancel", "release"):
        st.write(
            f"{v.booking.party_size} guests · {fmt_local(v.booking.start, wb.cfg.tz)} · "
            + " + ".join(v.booking.table_ids)
        )
        st.warning(
            "This releases the allocated tables in the local booking record. It does not notify the guest."
        )
    elif action == "close":
        st.warning(
            "This removes the inquiry from active work. It does not cancel a booking or send a reply."
        )
    elif action == "referral":
        st.caption("Only record this after completing the referral outside the app.")
    with st.form("action_" + iid + "_" + action):
        reason = st.text_input("Reason / reference")
        confirm = st.form_submit_button(labels[action], type="primary")
    if confirm:
        commands = {
            "cancel": wb.cancel_booking,
            "release": wb.release_hold,
            "decline": wb.decline,
            "close": wb.close,
            "reopen": wb.reopen,
            "referral": wb.report_referral,
            "escalate": wb.escalate,
        }
        r = commands[action](iid, reason, k(v, action, reason))
        if r.ok:
            finish(
                r,
                iid,
                "Reply"
                if action in ("cancel", "release", "decline", "referral")
                else "Plan",
            )
        else:
            st.error(r.message)


def policy_reviews(wb, v):
    a = v.assessment
    if any(x.rule_id == "R-ALLERGY" for x in a.reviews):
        with st.container(border=True):
            st.markdown("**Allergy follow-up**")
            st.write(pretty(v.facts.get("allergies").value))
            note = st.text_input("Follow-up note", key="allergy_note_" + v.inquiry.id)
            st.caption("Record the review without promising accommodation.")
            if st.button("Record follow-up review", key="allergy_" + v.inquiry.id):
                finish(
                    wb.acknowledge_allergy(v.inquiry.id, note, k(v, "allergy", note))
                )
    if any(x.rule_id == "R-MINSPEND" for x in a.reviews):
        with st.container(border=True):
            st.markdown("**Minimum spend**")
            amount = st.number_input(
                "Amount (CAD)",
                min_value=0.0,
                value=float(v.facts.value("min_spend_amount") or 0),
                step=50.0,
                key="amount_" + v.inquiry.id,
            )
            note = st.text_input(
                "Decision / guest agreement reference", key="spendnote_" + v.inquiry.id
            )
            if st.button("Save amount", key="setamount_" + v.inquiry.id):
                finish(
                    wb.set_fact(
                        v.inquiry.id,
                        "min_spend_amount",
                        amount,
                        note,
                        k(v, "amount", amount),
                    )
                )
            current = v.facts.value("min_spend_amount")
            if current is not None:
                st.caption(
                    f"Current recorded amount: CAD {current:g}. Changing it requires renewed agreement."
                )
                if st.button(
                    "Record guest agreement",
                    key="ackamount_" + v.inquiry.id,
                    disabled=amount != current,
                ):
                    finish(
                        wb.set_fact(
                            v.inquiry.id,
                            "min_spend_acknowledged",
                            "yes",
                            note,
                            k(v, "agreement", current),
                        )
                    )


def render_plan(wb, v):
    a = v.assessment
    b = v.booking
    p = v.active_proposal
    o = selected_option(v)
    if b:
        html_block(
            f'<div class="rw-booking"><div class="rw-label">Current booking · {esc(b.status.value)}</div><strong>{b.party_size} guests · {esc(fmt_local(b.start, wb.cfg.tz))}</strong><div>{esc(" + ".join(b.table_ids))} · until {esc(fmt_local(b.end, wb.cfg.tz, False))}</div></div>'
        )
    if a.requested_change:
        st.warning(
            "Requested change pending. The current booking stays in place until you apply the change."
        )
    if a.blockers or a.reviews:
        for x in (a.blockers + a.reviews)[:3]:
            st.warning(human_issue(x.message))
        if len(a.blockers + a.reviews) > 3:
            with st.expander("Other items to resolve"):
                for x in (a.blockers + a.reviews)[3:]:
                    st.write(human_issue(x.message))
    policy_reviews(wb, v)
    if (
        work_status(v) in ("Referral pending", "Referral recorded")
        or a.next_action.value == "escalate_private_events"
    ):
        st.markdown("### Private-events referral")
        st.caption("Private-room availability is not checked here.")
        if not referral_done(v):
            if st.button(
                "Record referral completed elsewhere", key="referral_" + v.inquiry.id
            ):
                booking_action(wb, v.inquiry.id, "referral")
        else:
            st.success("Referral recorded as completed elsewhere.")
    elif not b or a.requested_change or b.status == BookingStatus.HELD:
        if p and p.status == ProposalStatus.STALE:
            st.warning(
                "Guest details changed. The earlier arrangement is stale. Select again after reviewing the changes."
            )
        selected = bool(
            p and p.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED)
        )
        if o and (not b or a.requested_change):
            st.markdown(
                "### "
                + ("Selected arrangement" if selected else "Suggested arrangement")
            )
            st.markdown("**" + option_label(wb, o) + "**")
            st.caption(
                f"{fmt_local(o.start, wb.cfg.tz)}–{fmt_local(o.end, wb.cfg.tz, False)} · "
                + ("Separate tables; not joined" if o.split else "One table")
            )
            if not selected and (not b or a.requested_change):
                if st.button(
                    "Select suggested arrangement",
                    type="primary",
                    key="suggest_" + v.inquiry.id,
                    width="stretch",
                ):
                    finish(
                        wb.propose(
                            v.inquiry.id,
                            k(v, "plan", o.unit_id, o.start),
                            unit_id=o.unit_id,
                            start_override=o.start,
                        )
                    )
        # Main decision comes BEFORE optional comparison content.
        if selected:
            expiry = None
            if a.hold_needs_operator_deadline:
                st.caption("This short-notice hold needs an expiry time.")
                dd = st.date_input(
                    "Hold expires on",
                    value=wb.now().astimezone(wb.cfg.tz).date(),
                    key="hold_date_" + v.inquiry.id,
                )
                times = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]
                target = wb.now() + timedelta(hours=2)
                raw = st.selectbox("Expiry time", times, index=target.hour*4 + target.minute//15, key="hold_time_" + v.inquiry.id)
                tt = time.fromisoformat(raw)
                expiry = datetime.combine(dd, tt, tzinfo=wb.cfg.tz)
            if p.kind == ProposalKind.MODIFICATION:
                if st.button(
                    "Apply booking change",
                    type="primary",
                    key="commit_" + v.inquiry.id,
                    width="stretch",
                ):
                    finish(
                        wb.review_and_commit(p.id, "modify", k(v, "commit", p.id)),
                        v.inquiry.id,
                        "Reply",
                    )
            else:
                if st.button(
                    "Confirm booking",
                    type="primary",
                    key="confirm_" + v.inquiry.id,
                    width="stretch",
                    disabled=bool(a.confirm_gaps),
                ):
                    finish(
                        wb.review_and_commit(p.id, "confirm", k(v, "confirm", p.id)),
                        v.inquiry.id,
                        "Reply",
                    )
                if a.confirm_gaps:
                    st.caption("Before confirmation: " + ", ".join(a.confirm_gaps))
                if st.button("Create hold instead", key="hold_" + v.inquiry.id):
                    finish(
                        wb.review_and_commit(p.id, "hold", k(v, "hold", p.id), expiry),
                        v.inquiry.id,
                        "Reply",
                    )
            st.caption("Checks current availability before recording the booking.")
        elif b and hold_is_active(b, wb.now()) and not a.requested_change:
            if st.button(
                "Confirm held booking",
                key="confirmheld_" + v.inquiry.id,
                type="primary",
                disabled=bool(a.confirm_gaps),
            ):
                finish(
                    wb.confirm(
                        v.inquiry.id,
                        k(v, "confirmheld"),
                        expected_record_version=v.inquiry.record_version,
                    ),
                    v.inquiry.id,
                    "Reply",
                )
            if a.confirm_gaps:
                st.caption("Before confirmation: " + ", ".join(a.confirm_gaps))
        with st.expander("Compare seating & other times", expanded=not o):
            render_options(wb, v)
    if a.next_action.value == "process_cancellation":
        if st.button(
            "Review cancellation",
            key="cancel_requested_" + v.inquiry.id,
            type="primary",
        ):
            booking_action(wb, v.inquiry.id, "cancel")
    if st.button("Continue to reply", key="to_reply_" + v.inquiry.id, width="stretch"):
        st.session_state["stage_request"] = (v.inquiry.id, "Reply")
        st.rerun()
    if a.advisories:
        with st.expander("Service & policy notes"):
            for x in a.advisories:
                st.write(human_issue(x.message))
    with st.expander("Other booking actions"):
        actions = []
        if b and b.status in (BookingStatus.HELD, BookingStatus.CONFIRMED):
            actions.append(("cancel", "Cancel booking"))
        if b and hold_is_active(b, wb.now()):
            actions.append(("release", "Release hold"))
        if not b:
            actions.append(("decline", "Decline request"))
        if not referral_done(v):
            actions.append(("escalate", "Flag for private-events review"))
        actions.append(
            ("reopen", "Reopen inquiry")
            if work_status(v)
            in (
                "Closed",
                "Completed",
                "Waiting for guest",
                "Referral recorded",
                "Referral pending",
            )
            else ("close", "Close inquiry")
        )
        for action, label in actions:
            if st.button(label, key=action + "_" + v.inquiry.id):
                booking_action(wb, v.inquiry.id, action)
        if a.requested_change and st.button(
            "Keep original booking details", key="revert_" + v.inquiry.id
        ):
            finish(
                wb.revert_facts_to_booking(
                    v.inquiry.id, "Coordinator kept original booking", k(v, "revert")
                )
            )


def render_options(wb, v):
    a = v.assessment
    opts = list(a.availability.options) if a.availability else []
    alts = [o for _, o in a.alternatives]
    kind = st.radio(
        "Compare",
        ["Requested time", "Other times"],
        horizontal=True,
        key="optionkind_" + v.inquiry.id,
        index=0 if opts else 1,
    )
    choices = opts if kind == "Requested time" else alts
    unique = {(o.unit_id, o.start): o for o in choices}
    choices = list(unique.values())
    if not choices:
        st.info(
            "No suitable options in this group. Check other times or revise the request."
        )
        return
    limit = 3
    if len(choices) > 3 and st.checkbox(
        f"Show all {len(choices)} options", key="all_options_" + v.inquiry.id
    ):
        limit = len(choices)
    for index, o in enumerate(choices[:limit]):
        with st.container(border=True):
            st.markdown("**" + option_label(wb, o) + "**")
            st.caption(
                f"{fmt_local(o.start, wb.cfg.tz, False)}–{fmt_local(o.end, wb.cfg.tz, False)} · "
                + ("Step-free" if o.step_free else "Stairs")
                + " · "
                + ("Separate tables" if o.split else "One table")
            )
            st.caption(
                "Fits the current party size, access requirements and availability rules."
            )
            if st.button(
                "Select this arrangement",
                key=f"choose_{v.inquiry.id}_{kind}_{index}",
                width="stretch",
            ):
                finish(
                    wb.propose(
                        v.inquiry.id,
                        k(v, "plan", o.unit_id, o.start),
                        unit_id=o.unit_id,
                        start_override=o.start,
                    )
                )
            with st.expander("View tables"):
                render_seating_visual(wb, v, o)
    if kind == "Other times":
        st.caption(
            "Selecting an alternative prepares an offer. Confirm the accepted date/time from the guest before finalizing."
        )
    if a.availability and a.availability.rejected:
        with st.expander("Why other tables are unavailable"):
            for x in a.availability.rejected:
                st.write(
                    x.unit_id.replace("G_", "").replace("_", " + ")
                    + " · "
                    + "; ".join(human_issue(r) for r in x.reasons)
                )


def clipboard(text):
    """Actual clipboard write; reports success only after browser confirmation."""
    payload = json.dumps(text).replace("<", "\\u003c")
    components.html(
        """<style>body{margin:0;font:14px system-ui;color:#232a36}button{font:inherit;background:white;border:1px solid #cbd2de;border-radius:7px;padding:10px 18px;cursor:pointer}button:focus-visible{outline:3px solid #2747c9;outline-offset:2px}textarea{width:95%;height:95px}span{margin-left:10px}</style><button id="copy">Copy reply</button><span id="status" role="status"></span><textarea id="fallback" aria-label="Select and copy reply" hidden></textarea><script>const text="""
        + payload
        + """;document.getElementById('copy').onclick=async()=>{try{await navigator.clipboard.writeText(text);document.getElementById('status').textContent='Copied';}catch(e){document.getElementById('status').textContent='Select the reply above and press Ctrl+C / Cmd+C.';}};</script>""",
        height=62,
        scrolling=False,
    )


@st.dialog("Prepare a new reply?")
def regenerate(wb, iid, purpose):
    st.write(
        "Your saved and in-session versions are retained. A new reply uses the current booking details."
    )
    if st.button("Prepare new version", type="primary", key="confirm_regenerate"):
        v = wb.load(iid)
        finish(
            wb.generate_draft(iid, k(v, "draft", purpose), purpose=purpose),
            iid,
            "Reply",
        )


def render_draft(wb, v):
    status = response_status(v)
    d = v.latest_draft
    sent = sent_event(v)
    st.markdown("### Guest reply")
    if sent:
        st.success("Reply recorded as sent elsewhere")
        st.caption(
            fmt_local(sent.created_at, wb.cfg.tz)
            + " · Operator reported; delivery is not verified."
        )
        with st.expander("View recorded reply"):
            st.write(d.text)
        if st.button("Prepare follow-up", key="followup_" + v.inquiry.id):
            regenerate(wb, v.inquiry.id, "clarification")
        render_notes(wb, v)
        return
    purpose = resolve_purpose(v)
    if purpose:
        allowed = allowed_purposes(v)
        purpose = st.selectbox(
            "Reply type",
            allowed,
            index=allowed.index(purpose) if purpose in allowed else 0,
            format_func=lambda x: PURPOSES[x],
            key=f"purpose_{v.inquiry.id}_{v.inquiry.record_version}",
        )
        if not d:
            st.caption(
                "Prepare a reply from the current record, then review its wording."
            )
            if st.button(
                "Prepare reply",
                key="gen_" + v.inquiry.id,
                type="primary",
                width="stretch",
            ):
                with st.spinner("Preparing reply…"):
                    r = wb.generate_draft(
                        v.inquiry.id, k(v, "draft", purpose), purpose=purpose
                    )
                finish(r, v.inquiry.id, "Reply")
        elif st.button("Prepare new version", key="gen_" + v.inquiry.id):
            regenerate(wb, v.inquiry.id, purpose)
    if not d:
        return
    stale = v.draft_is_stale(d)
    if stale:
        st.warning(
            "Details or seating changed. Prepare a new version and review it before handoff."
        )
    if v.booking:
        b = v.booking
        st.caption(
            f"Record: {b.party_size} guests · {fmt_local(b.start, wb.cfg.tz)} · "
            + " + ".join(b.table_ids)
        )
    buffers = st.session_state.setdefault("draft_buffers", {})
    textkey = "draft_text_" + d.id

    def remember():
        buffers[d.id] = st.session_state[textkey]

    if textkey not in st.session_state:
        st.session_state[textkey] = buffers.get(d.id, d.text)
    txt = st.text_area("Reply", height=360, key=textkey, on_change=remember)
    dirty = txt != d.text
    if dirty:
        st.caption(
            "Unsaved edits · retained in this browser session. Save before review."
        )
    errors = [x for x in d.validation if x["severity"] == "error"]
    for item in errors:
        st.error(item["message"])
    for item in d.validation:
        if item["severity"] == "warning":
            st.warning(item["message"])
    if dirty:
        if st.button("Save reply", key="save_" + d.id, type="primary", width="stretch"):
            finish(
                wb.save_draft_edit(d.id, txt, k(v, "save", d.id, txt)),
                v.inquiry.id,
                "Reply",
            )
    elif not stale and not v.draft_approval_current(d):
        if st.button(
            "Mark reviewed",
            key="approve_" + d.id,
            type="primary",
            width="stretch",
            disabled=bool(errors),
        ):
            finish(wb.approve_draft(d.id, k(v, "review", d.id)), v.inquiry.id, "Reply")
    reviewed = v.draft_approval_current(d) and not dirty and not stale
    if reviewed:
        st.caption("Reviewed · ready to copy. Nothing is sent by this application.")
        clipboard(d.text)
        st.download_button(
            "Download reply",
            d.text,
            file_name=f"{v.inquiry.id}-reply.txt",
            key="export_" + d.id,
        )
        if st.button(
            "Record sent elsewhere", key="sent_" + d.id, type="primary", width="stretch"
        ):
            finish(
                wb.report_reply_sent(v.inquiry.id, d.id, k(v, "sent", d.id)),
                v.inquiry.id,
                "Reply",
            )
    else:
        st.download_button(
            "Download unreviewed draft",
            d.text,
            file_name=f"{v.inquiry.id}-UNREVIEWED.txt",
            key="export_" + d.id,
            disabled=dirty or stale,
        )
    render_notes(wb, v)
    if len(v.drafts) > 1:
        with st.expander("Previous versions"):
            for prev in reversed(v.drafts[:-1]):
                st.caption(prev.id + " · " + PURPOSES.get(prev.purpose, prev.purpose))
                st.text_area(
                    "Previous reply",
                    value=buffers.get(prev.id, prev.text),
                    disabled=True,
                    key="previous_" + prev.id,
                    height=140,
                )


def render_notes(wb, v):
    with st.expander("Booking notes for handoff"):
        notes = wb.booking_notes(v.inquiry.id)
        st.code(notes, language=None, wrap_lines=True)
        st.download_button(
            "Download booking notes",
            notes,
            file_name=f"{v.inquiry.id}-notes.txt",
            key="notes_" + v.inquiry.id,
        )


def render_history(wb: Workbench, v: InquiryView) -> None:
    tz = wb.cfg.tz
    rows = []
    for e in reversed(v.events):
        if e.event_type == "inquiry_state_changed":
            change = f"{e.before} → {(e.after or {}).get('state')}"
        else:
            change = "" if e.after is None else str(e.after)[:160]
        rows.append(
            {
                "Time": fmt_local(e.created_at, tz),
                "Actor": e.actor,
                "Event": e.event_type,
                "Reason": e.reason or "",
                "Change": change,
                "Rec v": str(e.record_version or ""),
                "Mode": e.mode,
            }
        )
    st.dataframe(
        rows, hide_index=True, width="stretch", height=min(36 * (len(rows) + 1), 560)
    )
    st.caption(
        "Times shown on the demo clock in restaurant local time. Events are append-only."
    )


def render_diagnostics(wb: Workbench, v: InquiryView) -> None:
    for it in reversed(v.interpretations):
        with st.expander(
            f"{it.id} · {it.provider_mode} · {it.status} · messages {', '.join(it.message_ids)}"
        ):
            st.write(
                {
                    "model": it.model,
                    "latency_ms": it.latency_ms,
                    "intents": it.intents,
                    "ambiguities": it.ambiguities,
                    "uninterpreted": it.uninterpreted,
                    "error": it.error,
                    "usage": it.usage,
                }
            )
            if it.raw_output:
                st.code(it.raw_output[:5000], language="json")
    with st.expander("Assessment rule results (raw)"):
        a = v.assessment
        st.write(
            {
                "next_action": a.next_action.value,
                "rule_ids": a.rule_ids,
                "confirm_gaps": a.confirm_gaps,
                "open_intents": a.open_intents,
                "hold_ready": a.hold_ready,
                "confirm_ready": a.confirm_ready,
            }
        )
