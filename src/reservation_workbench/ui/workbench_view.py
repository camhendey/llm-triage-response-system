"""Coordinator workflow: request, selected arrangement, response and handoff."""

from __future__ import annotations
from datetime import date, datetime, time, timedelta
import uuid
import streamlit as st
from ..domain.models import (
    Direction,
    ENUM_VALUES,
    FIELD_LABELS,
    FieldName,
    BookingStatus,
    ProposalStatus,
    ProposalKind,
    InquiryState,
)
from ..services.workbench import Workbench, InquiryView
from ..rules.availability import hold_is_active
from ..services.drafting import (
    PURPOSES,
    allowed_purposes,
    resolve_purpose,
    selected_option,
)
from .components import chip, esc, html_block, fmt_local, stable_hash
from .seating_visual import option_label, render_seating_visual

LABELS = {
    "none": "None reported",
    "step_free_required": "Step-free access required",
    "other_needs": "Other access needs",
    "present": "Minors attending",
    "one_bill": "One bill",
    "separate_bills": "Separate bills",
    "no_preference": "No preference",
    "yes": "Yes",
    "no": "No",
}


def pretty(v):
    return (
        "Not yet known" if v is None else LABELS.get(str(v), str(v).replace("_", " "))
    )


def guest(v):
    return v.facts.value("guest_name") or v.inquiry.guest_label.replace(
        "Synthetic Guest ", "Guest "
    )


def k(v, a, *extra):
    return f"ui:{a}:{v.inquiry.id}:v{v.inquiry.record_version}:e{len(v.events)}:{stable_hash(*extra)}"


def flash(r):
    message = r.message
    if r.ok and message.startswith("Proposal "):
        message = (
            "Arrangement selected. Review the details, then create a hold or confirm."
        )
    elif r.ok and message.startswith("Draft ") and "generated" in message:
        message = "Reply prepared from the current record. Review it before handoff."
    st.session_state["flash"] = (r.ok, message, False)


def finish(r):
    flash(r)
    st.rerun()


def show_flash():
    f = st.session_state.pop("flash", None)
    if f:
        (st.success if f[0] else st.error)(f[1])


def queue_category(wb, v):
    if wb.pending_message_ids(v.inquiry.id):
        return "New replies"
    if (
        v.booking
        and hold_is_active(v.booking, wb.now())
        and v.booking.hold_expires_at - wb.now() <= timedelta(hours=6)
    ):
        return "Holds expiring"
    if v.inquiry.state == InquiryState.AWAITING_GUEST:
        return "Waiting for guest"
    if v.inquiry.state in (InquiryState.CLOSED, InquiryState.RESOLVED):
        return "Completed"
    if v.inquiry.state == InquiryState.ESCALATED:
        return "Referred"
    return "Ready to finalize" if v.assessment.confirm_ready else "Needs attention"


def render_queue(wb):
    st.markdown("### Inquiries")
    views = wb.queue()
    flt = st.selectbox(
        "Show",
        [
            "Active",
            "New replies",
            "Holds expiring",
            "Ready to finalize",
            "Waiting for guest",
            "Completed",
            "Referred",
            "All",
        ],
        key="q_filter",
    )
    q = st.text_input(
        "Search inquiries",
        key="q_search",
        placeholder="Guest or message",
        label_visibility="collapsed",
    )
    shown = [
        v
        for v in views
        if (
            flt == "All"
            or (
                flt == "Active"
                and queue_category(wb, v) not in ("Completed", "Referred")
            )
            or queue_category(wb, v) == flt
        )
        and (
            not q
            or q.lower()
            in (
                v.inquiry.guest_label + " " + " ".join(m.text for m in v.messages)
            ).lower()
        )
    ]
    st.caption(f"{len(shown)} inquiries · priority order")
    for v in shown:
        when = (
            fmt_local(v.facts.dining_start, wb.cfg.tz)
            if v.facts.dining_start
            else "Time to confirm"
        )
        label = f"{guest(v)} · {v.facts.value('party_size') or '?'} guests\n\n{when} · {queue_category(wb, v)}"
        if st.button(
            label,
            key="open_" + v.inquiry.id,
            width="stretch",
            type="primary"
            if st.session_state.get("selected") == v.inquiry.id
            else "secondary",
        ):
            st.session_state["selected"] = v.inquiry.id
            st.rerun()
    with st.expander("New inquiry"):
        with st.form("new_inq", clear_on_submit=True):
            name = st.text_input("Guest name", max_chars=80)
            txt = st.text_area("Guest message", max_chars=5000)
            go = st.form_submit_button("Create inquiry")
        if go:
            r = wb.create_inquiry(
                name, txt, wb.now(), key="ui:create:" + uuid.uuid4().hex
            )
            if r.ok:
                st.session_state["selected"] = r.data["inquiry_id"]
                if wb.provider.mode == "offline_rules":
                    wb.interpret(r.data["inquiry_id"])
            finish(r)


def render_workspace(wb, iid):
    v = wb.load(iid)
    a = v.assessment
    show_flash()
    st.markdown("## " + esc(guest(v)))
    when = (
        fmt_local(v.facts.dining_start, wb.cfg.tz)
        if v.facts.dining_start
        else "Date or time to confirm"
    )
    status = v.booking.status.value.title() if v.booking else "Not booked"
    html_block(
        f'<div class="rw-summary">{chip(status, "cobalt")}{chip(queue_category(wb, v))}<span>{esc(when)} · {esc(v.facts.value("party_size") or "?")} guests</span></div>'
    )
    html_block(
        f'<div class="rw-card rw-next"><div class="rw-label">Next action</div><div class="rw-action">{esc(a.label)}</div><div class="rw-item">{esc(a.next_action_detail)}</div></div>'
    )
    issues = a.blockers + a.reviews
    if issues:
        with st.expander(f"{len(issues)} items to resolve", expanded=len(issues) <= 2):
            for x in issues:
                (st.error if x in a.blockers else st.warning)(x.message)
    if a.advisories:
        with st.expander("Policy and service notes"):
            for x in a.advisories:
                st.caption(x.message)
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        st.markdown("### 1 · Understand the request")
        render_conversation(wb, v)
        render_facts(wb, v)
    with right:
        st.markdown("### 2 · Choose the arrangement")
        render_plan(wb, v)
        st.markdown("### 3 · Review the reply")
        render_draft(wb, v)
    with st.expander("Decision history and technical details"):
        render_history(wb, v)
        render_diagnostics(wb, v)


def render_conversation(wb, v):
    for m in v.messages:
        outgoing = m.direction == Direction.OUTBOUND_REPORTED
        label = "Team reply · reported sent" if outgoing else "Guest"
        html_block(
            f'<div class="rw-msg {"outbound" if outgoing else ""}"><div class="meta">{label} · {esc(fmt_local(m.received_at, wb.cfg.tz))}</div><div class="body">{esc(m.text)}</div></div>'
        )
    if wb.pending_message_ids(v.inquiry.id) and st.button(
        "Interpret new reply", key="interp_" + v.inquiry.id, type="primary"
    ):
        with st.spinner("Reading the conversation…"):
            r = wb.interpret(v.inquiry.id)
        finish(r)
    with st.expander("Add a guest reply"):
        with st.form("addmsg_" + v.inquiry.id, clear_on_submit=True):
            txt = st.text_area("New message", max_chars=5000, height=110)
            go = st.form_submit_button("Add reply")
        if go:
            r = wb.add_message(v.inquiry.id, txt, wb.now(), key=k(v, "addmsg", txt))
            if r.ok and wb.provider.mode == "offline_rules":
                wb.interpret(v.inquiry.id)
            finish(r)


EDIT_FIELDS = [
    "party_size",
    "requested_date",
    "requested_time",
    "contact_email",
    "accessibility",
    "minors",
    "allergies",
    "billing",
    "occasion",
    "guest_name",
    "contact_phone",
    "preferred_area",
    "preferred_table",
    "split_seating_ok",
    "requested_duration_minutes",
]


def render_facts(wb, v):
    ns = [
        "party_size",
        "requested_date",
        "requested_time",
        "accessibility",
        "allergies",
        "billing",
        "occasion",
    ]
    html_block(
        '<div class="rw-factcards">'
        + "".join(
            f"<div><small>{esc(FIELD_LABELS[n])}</small><strong>{esc(pretty(v.facts.value(n)))}</strong></div>"
            for n in ns
        )
        + "</div>"
    )
    with st.expander("Edit guest details"):
        st.caption("Unknown remains unknown. Occasion is optional context.")
        with st.form("facts_" + v.inquiry.id):
            edits = {}
            for n in EDIT_FIELDS:
                old = v.facts.value(n)
                label = FIELD_LABELS[n]
                wk = f"fact_{v.inquiry.id}_{n}_{v.inquiry.record_version}"
                if n in ENUM_VALUES:
                    opts = [None, *ENUM_VALUES[n]]
                    edits[n] = st.selectbox(
                        label,
                        opts,
                        index=opts.index(old) if old in opts else 0,
                        format_func=pretty,
                        key=wk,
                    )
                elif n == "requested_date":
                    edits[n] = st.date_input(
                        label, value=date.fromisoformat(old) if old else None, key=wk
                    )
                elif n == "requested_time":
                    edits[n] = st.time_input(
                        label,
                        value=time.fromisoformat(old) if old else None,
                        key=wk,
                        step=900,
                    )
                elif n in ("party_size", "requested_duration_minutes"):
                    edits[n] = st.number_input(
                        label,
                        min_value=1,
                        max_value=500,
                        value=int(old) if old else None,
                        step=1,
                        key=wk,
                    )
                else:
                    edits[n] = st.text_input(label, value=str(old or ""), key=wk)
            reason = st.text_input(
                "Source or reason for changes",
                value="Coordinator review",
                key="reasonfacts_" + v.inquiry.id,
            )
            go = st.form_submit_button("Save details")
        if go:
            changes = {}
            for n, val in edits.items():
                if isinstance(val, time):
                    val = val.strftime("%H:%M")
                elif isinstance(val, date):
                    val = val.isoformat()
                if val not in (None, "") and val != v.facts.value(n):
                    changes[n] = val
            if changes:
                finish(
                    wb.set_facts(
                        v.inquiry.id,
                        changes,
                        reason,
                        k(v, "facts", changes),
                        v.inquiry.record_version,
                    )
                )
            else:
                st.info(
                    "No changes. Confirm an ambiguous existing value under Sources and conflicts."
                )
    with st.expander("Sources and conflicts"):
        for n in FieldName:
            f = v.facts.get(n)
            if f.value is None:
                continue
            st.markdown(f"**{FIELD_LABELS[n.value]}:** {pretty(f.value)}")
            if f.current:
                st.caption(f.current.quote or f.current.note or "Coordinator record")
            if f.state in ("conflict", "needs_review"):
                st.warning(
                    "Needs review: "
                    + str(
                        [o.value for o in f.conflicts] or f.current.note or "Ambiguous"
                    )
                )
                if st.button(
                    "Keep / confirm " + pretty(f.value),
                    key=f"keep_{v.inquiry.id}_{n.value}",
                ):
                    finish(
                        wb.confirm_fact(
                            v.inquiry.id,
                            n.value,
                            k(v, "keep", n.value),
                            v.inquiry.record_version,
                        )
                    )
                for idx, o in enumerate(f.conflicts):
                    if st.button(
                        "Use " + pretty(o.value),
                        key=f"use_{v.inquiry.id}_{n.value}_{idx}",
                    ):
                        finish(
                            wb.set_fact(
                                v.inquiry.id,
                                n.value,
                                o.value,
                                "Resolved guest correction",
                                k(v, "resolve", n.value, o.value),
                                v.inquiry.record_version,
                            )
                        )


def render_plan(wb, v):
    a = v.assessment
    p = v.active_proposal
    b = v.booking
    o = selected_option(v)
    if b:
        st.info(
            f"Current booking: {b.status.value.title()} · {' + '.join(b.table_ids)} · {fmt_local(b.start, wb.cfg.tz)}–{fmt_local(b.end, wb.cfg.tz, False)}"
        )
    if o and (not b or a.requested_change):
        chosen = bool(
            p and p.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED)
        )
        st.markdown(
            ("**Selected arrangement**" if chosen else "**Suggested arrangement**")
            + "  \n"
            + option_label(wb, o)
        )
        st.caption(
            f"{fmt_local(o.start, wb.cfg.tz)}–{fmt_local(o.end, wb.cfg.tz, False)} · "
            + ("Separate tables; not joined." if o.split else "One table.")
        )
    if (
        o
        and not (p and p.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED))
        and (not b or a.requested_change)
    ):
        if st.button(
            "Select suggested arrangement",
            key="suggest_" + v.inquiry.id,
            type="primary",
            width="stretch",
        ):
            finish(
                wb.propose(
                    v.inquiry.id,
                    k(v, "select", o.unit_id, o.start),
                    unit_id=o.unit_id,
                    start_override=o.start,
                )
            )
    with st.expander("Compare seating and times", expanded=not o):
        options = list(a.availability.options) if a.availability else []
        for _, alt in a.alternatives:
            if not any(
                x.unit_id == alt.unit_id and x.start == alt.start for x in options
            ):
                options.append(alt)
        if options:
            idx = next(
                (
                    i
                    for i, x in enumerate(options)
                    if o and x.unit_id == o.unit_id and x.start == o.start
                ),
                0,
            )
            chosen = st.selectbox(
                "Arrangement",
                list(range(len(options))),
                index=idx,
                format_func=lambda i: (
                    f"{fmt_local(options[i].start, wb.cfg.tz, False)} · {option_label(wb, options[i])}"
                ),
                key=f"option_{v.inquiry.id}_{v.inquiry.record_version}",
            )
            candidate = options[chosen]
            render_seating_visual(wb, v, candidate)
            if st.button(
                "Select arrangement", key="selectplan_" + v.inquiry.id, width="stretch"
            ):
                finish(
                    wb.propose(
                        v.inquiry.id,
                        k(v, "select", candidate.unit_id, candidate.start),
                        unit_id=candidate.unit_id,
                        start_override=candidate.start,
                    )
                )
            if len(options) > 1:
                other = st.selectbox(
                    "Compare with",
                    list(range(len(options))),
                    index=(chosen + 1) % len(options),
                    format_func=lambda i: (
                        f"{fmt_local(options[i].start, wb.cfg.tz, False)} · {option_label(wb, options[i])}"
                    ),
                    key=f"compare_{v.inquiry.id}_{v.inquiry.record_version}",
                )
                st.dataframe(
                    [
                        {
                            "Option": option_label(wb, x),
                            "Time": fmt_local(x.start, wb.cfg.tz, False),
                            "Access": "Step-free" if x.step_free else "Stairs",
                            "Seating": "Separate tables" if x.split else "One table",
                            "Spare seats": x.capacity
                            - (v.facts.value("party_size") or 0),
                        }
                        for x in (candidate, options[other])
                    ],
                    hide_index=True,
                    width="stretch",
                )
        else:
            render_seating_visual(wb, v, None)
        if a.availability and a.availability.rejected:
            st.dataframe(
                [
                    {"Option": x.unit_id, "Why unavailable": "; ".join(x.reasons)}
                    for x in a.availability.rejected
                ],
                hide_index=True,
                width="stretch",
            )
    if p and p.status == ProposalStatus.STALE:
        st.warning(
            "The earlier arrangement is stale. Select again after reviewing changes."
        )
    if p and p.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED):
        expiry = None
        if a.hold_needs_operator_deadline:
            dd = st.date_input(
                "Hold deadline date",
                value=wb.now().astimezone(wb.cfg.tz).date(),
                key="hold_date_" + v.inquiry.id,
            )
            tt = st.time_input(
                "Hold deadline time",
                value=(wb.now() + timedelta(hours=2)).astimezone(wb.cfg.tz).time(),
                key="hold_time_" + v.inquiry.id,
            )
            expiry = datetime.combine(dd, tt, tzinfo=wb.cfg.tz)
        if p.kind == ProposalKind.MODIFICATION:
            if st.button(
                "Review and commit change", type="primary", key="commit_" + v.inquiry.id
            ):
                finish(wb.review_and_commit(p.id, "modify", k(v, "commit", p.id)))
        else:
            c1, c2 = st.columns(2)
            if c1.button("Create hold", key="hold_" + v.inquiry.id):
                finish(wb.review_and_commit(p.id, "hold", k(v, "hold", p.id), expiry))
            if c2.button(
                "Confirm booking",
                type="primary",
                key="confirm_" + v.inquiry.id,
                disabled=bool(a.confirm_gaps),
            ):
                finish(wb.review_and_commit(p.id, "confirm", k(v, "confirm", p.id)))
        st.caption("Rechecks availability before updating the simulated booking.")
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
                )
            )
    with st.expander("Exceptions and other actions"):
        reason = st.text_input("Decision note", key="decisionnote_" + v.inquiry.id)
        if b and b.status in (BookingStatus.HELD, BookingStatus.CONFIRMED):
            if st.button("Cancel booking", key="cancel_" + v.inquiry.id):
                finish(
                    wb.cancel_booking(
                        v.inquiry.id,
                        reason,
                        k(v, "cancel", reason),
                        v.inquiry.record_version,
                    )
                )
            if hold_is_active(b, wb.now()) and st.button(
                "Release hold", key="release_" + v.inquiry.id
            ):
                finish(wb.release_hold(v.inquiry.id, reason, k(v, "release", reason)))
        elif st.button("Decline request", key="decline_" + v.inquiry.id):
            finish(wb.decline(v.inquiry.id, reason, k(v, "decline", reason)))
        if st.button("Flag for private-events review", key="escalate_" + v.inquiry.id):
            finish(wb.escalate(v.inquiry.id, reason, k(v, "escalate", reason)))
        if st.button(
            "Record referral completed elsewhere", key="referral_" + v.inquiry.id
        ):
            finish(wb.report_referral(v.inquiry.id, reason, k(v, "referral", reason)))
        if any(x.rule_id == "R-ALLERGY" for x in a.reviews) and st.button(
            "Record allergy follow-up review", key="allergy_" + v.inquiry.id
        ):
            finish(
                wb.acknowledge_allergy(v.inquiry.id, reason, k(v, "allergy", reason))
            )
        if any(x.rule_id == "R-MINSPEND" for x in a.reviews):
            amount = st.number_input(
                "Minimum spend (CAD)",
                min_value=0.0,
                step=50.0,
                key="amount_" + v.inquiry.id,
            )
            if st.button("Set minimum spend", key="setamount_" + v.inquiry.id):
                finish(
                    wb.set_fact(
                        v.inquiry.id,
                        "min_spend_amount",
                        amount,
                        reason,
                        k(v, "amount", amount),
                    )
                )
            if st.button(
                "Record guest agreement to current amount",
                key="ackamount_" + v.inquiry.id,
            ):
                finish(
                    wb.set_fact(
                        v.inquiry.id,
                        "min_spend_acknowledged",
                        "yes",
                        reason,
                        k(v, "ackamount"),
                    )
                )
        if st.button("Reopen inquiry", key="reopen_" + v.inquiry.id):
            finish(wb.reopen(v.inquiry.id, reason, k(v, "reopen", reason)))
        if st.button("Close inquiry", key="close_" + v.inquiry.id):
            finish(wb.close(v.inquiry.id, reason, k(v, "close", reason)))
        if a.requested_change and st.button(
            "Keep original booking details", key="revert_" + v.inquiry.id
        ):
            finish(
                wb.revert_facts_to_booking(v.inquiry.id, reason, k(v, "revert", reason))
            )


def render_draft(wb, v):
    purpose = resolve_purpose(v)
    if purpose:
        allowed = allowed_purposes(v)
        with st.expander("Response type"):
            purpose = st.selectbox(
                "Purpose",
                allowed,
                index=allowed.index(purpose) if purpose in allowed else 0,
                format_func=lambda x: PURPOSES[x],
                key=f"purpose_{v.inquiry.id}_{v.inquiry.record_version}",
            )
        if st.button("Prepare reply", key="gen_" + v.inquiry.id, width="stretch"):
            with st.spinner("Preparing a reply from the current plan…"):
                r = wb.generate_draft(
                    v.inquiry.id, k(v, "draft", purpose), purpose=purpose
                )
            finish(r)
    d = v.latest_draft
    if not d:
        st.caption(
            "Prepare a reply here for review. Nothing is sent by this application."
        )
        return
    stale = v.draft_is_stale(d)
    if stale:
        st.warning("Guest details or the plan changed. Prepare a new reply.")
    buffers = st.session_state.setdefault("draft_buffers", {})
    textkey = "draft_text_" + d.id

    def remember():
        buffers[d.id] = st.session_state[textkey]

    if textkey not in st.session_state:
        st.session_state[textkey] = buffers.get(d.id, d.text)
    txt = st.text_area("Reply", height=330, key=textkey, on_change=remember)
    dirty = txt != d.text
    if dirty:
        st.caption("Unsaved edits are retained when navigating. Save before review.")
    c1, c2 = st.columns(2)
    if c1.button("Save reply", key="save_" + d.id, disabled=not dirty):
        finish(wb.save_draft_edit(d.id, txt, k(v, "save", d.id, txt)))
    errors = [x for x in d.validation if x["severity"] == "error"]
    if c2.button(
        "Mark reviewed",
        key="approve_" + d.id,
        disabled=dirty or stale or bool(errors) or v.draft_approval_current(d),
    ):
        finish(wb.approve_draft(d.id, k(v, "approve", d.id)))
    for x in errors:
        st.error(x["message"])
    for x in [x for x in d.validation if x["severity"] == "warning"]:
        st.warning(x["message"])
    st.download_button(
        "Export reply",
        data=d.text,
        file_name=f"{v.inquiry.id}-reply.txt",
        key="export_" + d.id,
        disabled=dirty or stale,
    )
    st.caption("Select text to copy or export. Neither sends the reply.")
    reviewed = v.draft_approval_current(d) and not stale and not dirty
    if reviewed:
        st.success("Reviewed and ready for handoff.")
    if st.button(
        "I sent this reply elsewhere", key="sent_" + d.id, disabled=not reviewed
    ):
        finish(wb.report_reply_sent(v.inquiry.id, d.id, k(v, "sent", d.id)))
    with st.expander("Booking notes for handoff"):
        notes = wb.booking_notes(v.inquiry.id)
        st.code(notes, language=None, wrap_lines=True)
        st.download_button(
            "Export booking notes",
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
