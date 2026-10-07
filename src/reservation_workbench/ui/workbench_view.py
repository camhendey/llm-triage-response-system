"""Queue and inquiry workspace."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import streamlit as st

from ..domain.models import (
    ENUM_VALUES,
    FIELD_LABELS,
    NEXT_ACTION_LABELS,
    BookingStatus,
    FieldName,
    InquiryState,
    ProposalKind,
    ProposalStatus,
)
from ..rules.availability import hold_is_active
from ..services.drafting import PURPOSES, allowed_purposes
from ..services.workbench import InquiryView, Workbench
from .components import (
    TAG_LABEL,
    booking_tone,
    chip,
    esc,
    fmt_local,
    highlight,
    html_block,
    stable_hash,
    state_tone,
    urgency_tone,
)

FILTERS = {"Actionable": ("new", "needs_review", "ready_for_action"), "Waiting": ("awaiting_guest", "escalated"),
           "Resolved": ("resolved", "closed"), "All": None}


def flash(res) -> None:
    st.session_state["flash"] = (res.ok, res.message, getattr(res, "duplicate", False))


def show_flash() -> None:
    f = st.session_state.pop("flash", None)
    if f:
        ok, msg, dup = f
        if dup:
            st.info(f"Duplicate request ignored: {msg}")
        elif ok:
            st.success(msg)
        else:
            st.error(msg)


def k(v: InquiryView, action: str, *extra) -> str:
    """Idempotency key: same view + same action + same inputs = same key."""
    return f"ui:{action}:{v.inquiry.id}:v{v.inquiry.record_version}:e{len(v.events)}:{stable_hash(*extra)}"


# ====================================================================== queue
def render_queue(wb: Workbench) -> None:
    tz = wb.cfg.tz
    views = wb.queue()
    st.markdown("### Queue")
    flt = st.selectbox("Show", list(FILTERS), key="q_filter")
    q = st.text_input("Search", key="q_search", placeholder="Search guest or message text",
                      label_visibility="collapsed")
    shown = []
    for v in views:
        states = FILTERS[flt]
        if states and v.inquiry.state.value not in states:
            continue
        if q:
            hay = (v.inquiry.guest_label + " " + v.inquiry.title + " " + v.inquiry.id + " " +
                   " ".join(m.text for m in v.messages)).lower()
            if q.lower() not in hay:
                continue
        shown.append(v)
    st.caption(f"{len(shown)} of {len(views)} inquiries · sorted by urgency, then nearest deadline")
    if not shown:
        st.info("No inquiries match this filter.")
    sel = st.session_state.get("selected")
    box = st.container(height=760, border=False)
    for v in shown:
        a = v.assessment
        f = v.facts
        party = f.get(FieldName.PARTY_SIZE).value
        day = f.get(FieldName.REQUESTED_DATE).value
        when = (fmt_local(f.dining_start, tz) if f.dining_start else
                (f"{day}?" if day else "date ?"))
        dl = f"{a.deadline_label}: {fmt_local(a.deadline, tz)}" if a.deadline else "no deadline"
        booking = v.booking.status.value if v.booking else "none"
        is_sel = sel == v.inquiry.id
        box.markdown(
            f'<div class="rw-q {"sel" if is_sel else ""}"><div class="t">{esc(v.inquiry.guest_label)}</div>'
            f'<div class="s">{esc(v.inquiry.id)} · {esc(when)} · party {esc(party if party is not None else "?")}</div>'
            f'<div>{chip(a.urgency.upper(), urgency_tone(a.urgency)) if a.urgency == "high" else ""}'
            f'{chip(v.inquiry.state.value.replace("_", " "), state_tone(v.inquiry.state.value))}'
            f'{chip("booking " + booking, booking_tone(booking))}</div>'
            f'<div class="s">Next: {esc(NEXT_ACTION_LABELS[a.next_action])}</div>'
            f'<div class="s">{esc(dl)}</div></div>'
            , unsafe_allow_html=True)
        if box.button("Open" if not is_sel else "Opened", key=f"open_{v.inquiry.id}", disabled=is_sel,
                     width="stretch"):
            st.session_state["selected"] = v.inquiry.id
            st.rerun()
    with st.expander("New inquiry"):
        with st.form("new_inq", clear_on_submit=True):
            label = st.text_input("Guest label (synthetic or initials)", max_chars=80)
            text = st.text_area("First guest message", height=120, max_chars=5000)
            now = wb.now().astimezone(tz)
            c1, c2 = st.columns(2)
            d = c1.date_input("Received date", value=now.date())
            t = c2.time_input("Received time", value=now.time().replace(second=0, microsecond=0))
            go = st.form_submit_button("Create inquiry")
        if go:
            at = datetime.combine(d, t, tzinfo=tz)
            res = wb.create_inquiry(label, text, at, key=f"ui:create:{stable_hash(label, text, at)}")
            if res.ok and res.data.get("inquiry_id"):
                st.session_state["selected"] = res.data["inquiry_id"]
            flash(res)
            st.rerun()


# ====================================================================== workspace
def render_workspace(wb: Workbench, inquiry_id: str) -> None:
    try:
        v = wb.load(inquiry_id)
    except Exception as exc:  # pragma: no cover - defensive UI
        st.error(f"Could not load {inquiry_id}: {exc}")
        return
    tz = wb.cfg.tz
    a = v.assessment
    inq = v.inquiry
    booking = v.booking
    bstatus = booking.status.value if booking else "none"
    if booking and booking.status == BookingStatus.HELD and not hold_is_active(booking, wb.now()):
        bstatus = "held (expired - pending release)"
    st.markdown(f"# {esc(inq.guest_label)}")
    html_block(
        f'<div>{chip(inq.id)}{chip("Inquiry: " + inq.state.value.replace("_", " "), state_tone(inq.state.value))}'
        f'{chip("Booking: " + bstatus, booking_tone(bstatus))}'
        f'{chip("Action: " + a.action_status) if a.action_status not in ("none", "") else ""}'
        f'{chip("Urgency: " + a.urgency, urgency_tone(a.urgency))}'
        f'{chip("record v" + str(inq.record_version))}'
        f'<span class="rw-muted">{esc(inq.title)}</span></div>'
    )
    # ---- next action summary -------------------------------------------
    items = []
    for sev, rows in (("blocker", a.blockers), ("review", a.reviews), ("advisory", a.advisories)):
        for r in rows:
            items.append(f'<div class="rw-item"><span class="rw-tag {sev}">{TAG_LABEL[sev]}</span>'
                         f'{esc(r.message)} <code>{esc(r.rule_id)}</code></div>')
    dl = (f'<div class="rw-item"><b>{esc(a.deadline_label)}:</b> {esc(fmt_local(a.deadline, tz))}</div>'
          if a.deadline else "")
    missing = (f'<div class="rw-item"><b>Missing for confirmation:</b> {esc(", ".join(a.missing_required))}</div>'
               if a.missing_required else "")
    html_block(
        f'<div class="rw-card rw-next"><div class="rw-label">Next action</div>'
        f'<div class="rw-action">{esc(a.label)}</div><div class="rw-item">{esc(a.next_action_detail)}</div>'
        f'{dl}{missing}{"".join(items) if items else "<div class=rw-item>No blockers or review items.</div>"}</div>'
    )
    show_flash()
    tabs = st.tabs(["Conversation & facts", "Seating & actions", "Draft & notes", "History", "Diagnostics"])
    with tabs[0]:
        render_conversation_and_facts(wb, v)
    with tabs[1]:
        render_seating_and_actions(wb, v)
    with tabs[2]:
        render_draft(wb, v)
    with tabs[3]:
        render_history(wb, v)
    with tabs[4]:
        render_diagnostics(wb, v)


# ---------------------------------------------------------------------- conversation + facts
def render_conversation_and_facts(wb: Workbench, v: InquiryView) -> None:
    tz = wb.cfg.tz
    left, right = st.columns([0.8, 1.45], gap="medium")
    with left:
        st.markdown("### Conversation")
        spans: dict[str, list[tuple[int, int]]] = {}
        for o in v.observations:
            if o.message_id and o.span_start is not None:
                spans.setdefault(o.message_id, []).append((o.span_start, o.span_end))
        pending = set(wb.pending_message_ids(v.inquiry.id))
        with st.container(height=420):
            for m in v.messages:
                src = {"seed": "synthetic seed", "pasted": "pasted by operator", "csv_import": "CSV import"}[
                    m.source.value]
                tag = " · <b>not yet interpreted</b>" if m.id in pending else ""
                html_block(f'<div class="rw-msg"><div class="meta">{esc(m.id)} · guest · '
                           f'{esc(fmt_local(m.received_at, tz))} · {esc(src)}{tag}</div>'
                           f'<div class="body">{highlight(m.text, spans.get(m.id, []))}</div></div>')
        st.caption("Highlighted text = evidence cited for a fact. Guest text is data; it is never treated as "
                   "instructions.")
        if pending:
            label = ("Interpret with offline pattern interpreter" if wb.provider.mode == "offline_rules"
                     else "Interpret with live model")
            if st.button(label, type="primary", key=f"interp_{v.inquiry.id}"):
                with st.spinner("Interpreting new messages..."):
                    res = wb.interpret(v.inquiry.id)
                flash(res)
                st.rerun()
        with st.form(f"addmsg_{v.inquiry.id}", clear_on_submit=True):
            txt = st.text_area("Paste a later guest message", height=90, max_chars=5000)
            now = wb.now().astimezone(tz)
            c1, c2 = st.columns(2)
            d = c1.date_input("Received date", value=now.date(), key=f"amd_{v.inquiry.id}")
            t = c2.time_input("Received time", value=now.time().replace(second=0, microsecond=0),
                              key=f"amt_{v.inquiry.id}")
            add = st.form_submit_button("Add message")
        if add:
            at = datetime.combine(d, t, tzinfo=tz)
            flash(wb.add_message(v.inquiry.id, txt, at, key=k(v, "addmsg", txt, at)))
            st.rerun()
    with right:
        st.markdown("### Structured facts")
        rows = []
        f = v.facts
        for name in FieldName:
            fv = f.get(name)
            if name in (FieldName.MIN_SPEND_AMOUNT, FieldName.MIN_SPEND_ACKNOWLEDGED) and fv.state == "unknown" \
                    and not any(r.rule_id == "R-MINSPEND" for r in v.assessment.reviews):
                continue
            cur = fv.current
            if fv.state == "unknown":
                src = ""
            elif cur.source_type == "operator":
                src = "operator" + (f": {cur.note}" if cur.note else "")
            elif cur.source_type == "seed":
                src = "seeded record"
            else:
                src = f'{cur.message_id}: "{cur.quote}"'
            state = {"known": "known", "unknown": "UNKNOWN", "needs_review": "NEEDS REVIEW",
                     "conflict": "CONFLICT"}[fv.state]
            if fv.state == "known" and cur and cur.source_type == "operator":
                state = "operator-confirmed"
            changed = f" (was {', '.join(map(str, fv.changed_from))})" if fv.changed_from else ""
            rows.append({"Field": FIELD_LABELS.get(name.value, name.value),
                         "Value": ("-" if fv.value is None else str(fv.value)) + changed,
                         "Status": state, "Source": src[:90],
                         "Note": (cur.note or "") if cur is not None and cur.source_type != "operator" else ""})
        dur = f.duration_minutes
        rows.append({"Field": "Dining interval", "Value": (f"{fmt_local(f.dining_start, tz)}-"
                                                           f"{fmt_local(f.dining_end, tz, False)}"
                                                           if f.dining_start else "-"),
                     "Status": "derived" if f.dining_start else "UNKNOWN", "Source": f.duration_source or "",
                     "Note": f"{dur} min" if dur else ""})
        tone = {"UNKNOWN": "", "NEEDS REVIEW": "amber", "CONFLICT": "red", "known": "cobalt",
                "operator-confirmed": "green", "derived": "cobalt"}
        body = "".join(
            f'<tr><td class="f">{esc(r["Field"])}</td><td>{esc(r["Value"])}</td>'
            f'<td>{chip(r["Status"], tone.get(r["Status"], ""))}</td>'
            f'<td class="src">{esc(r["Source"])}{("<br>" + esc(r["Note"])) if r["Note"] else ""}</td></tr>'
            for r in rows)
        html_block(f'<table class="rw-facts"><colgroup><col class="c1"><col class="c2"><col class="c3"><col></colgroup><tr><th>Field</th><th>Value</th><th>Status</th>'
                   f'<th>Evidence / source</th></tr>{body}</table>')
        review = [fv for fv in f.fields.values() if fv.state in ("needs_review", "conflict")]
        for fv in review:
            with st.container(border=True):
                st.markdown(f"**{FIELD_LABELS.get(fv.field.value)}** - {fv.state.replace('_', ' ')}")
                if fv.state == "conflict":
                    for o in fv.conflicts:
                        st.markdown(f"- Current `{fv.value}` vs `{o.value}` from {o.message_id}: \"{o.quote}\"")
                    c1, c2 = st.columns(2)
                    if c1.button(f"Keep {fv.value}", key=f"keep_{fv.field.value}_{v.inquiry.record_version}"):
                        flash(wb.set_fact(v.inquiry.id, fv.field.value, fv.value, "kept after conflict review",
                                          k(v, "keep", fv.field.value), v.inquiry.record_version))
                        st.rerun()
                    newest = fv.conflicts[-1].value
                    if c2.button(f"Use {newest}", key=f"use_{fv.field.value}_{v.inquiry.record_version}"):
                        flash(wb.set_fact(v.inquiry.id, fv.field.value, newest, "accepted newer guest value",
                                          k(v, "use", fv.field.value, newest), v.inquiry.record_version))
                        st.rerun()
                else:
                    st.caption(fv.current.note or "")
                    if st.button(f"Confirm {fv.value}", key=f"conf_{fv.field.value}_{v.inquiry.record_version}"):
                        flash(wb.confirm_fact(v.inquiry.id, fv.field.value, k(v, "confirm", fv.field.value),
                                              v.inquiry.record_version))
                        st.rerun()
        with st.expander("Edit a fact (operator)"):
            with st.form(f"edit_{v.inquiry.id}"):
                fields = [x.value for x in FieldName]
                fld = st.selectbox("Field", fields, format_func=lambda x: FIELD_LABELS.get(x, x))
                hint = ENUM_VALUES.get(fld)
                val = st.text_input("Value", help=("Allowed: " + ", ".join(hint)) if hint else
                                    "Dates YYYY-MM-DD, times HH:MM (24h)")
                reason = st.text_input("Reason / source (e.g. 'guest phoned')")
                ok = st.form_submit_button("Save operator value")
            if ok:
                flash(wb.set_fact(v.inquiry.id, fld, val, reason, k(v, "set", fld, val, reason),
                                  v.inquiry.record_version))
                st.rerun()
            st.caption("Operator values stay authoritative until you change them; later guest messages that "
                       "disagree are shown as conflicts.")


# ---------------------------------------------------------------------- seating + actions
def _opt_rows(opts, tz):
    out = []
    for o in opts:
        out.append({"Rank": o.rank, "Unit": o.unit_id, "Tables": " + ".join(o.table_ids), "Cap": o.capacity,
                    "Area": o.area, "Access": "step-free" if o.step_free else "STAIRS ONLY",
                    "Seating": "separate tables" if o.split else "single table",
                    "Time": f"{fmt_local(o.start, tz, False)}-{fmt_local(o.end, tz, False)}",
                    "Notes": "; ".join(n for n in o.notes if not n.startswith("Separate tables"))})
    return out


def render_seating_and_actions(wb: Workbench, v: InquiryView) -> None:
    tz = wb.cfg.tz
    a = v.assessment
    inq = v.inquiry
    left, right = st.columns([1.35, 1], gap="medium")
    with left:
        st.markdown("### Seating check")
        if v.booking:
            b = v.booking
            exp = f" · hold until {fmt_local(b.hold_expires_at, tz)}" if b.hold_expires_at else ""
            st.markdown(f"**Current booking {b.id}:** {b.status.value} · {', '.join(b.table_ids)} · "
                        f"{fmt_local(b.start, tz)}-{fmt_local(b.end, tz, False)} · party {b.party_size}{exp}")
            if a.requested_change:
                st.markdown("**Requested change:** " + "; ".join(
                    f"{k_}: {x} → {y}" for k_, (x, y) in a.requested_change.items()))
        if a.request is None:
            st.info("Seating cannot be checked until party size, date and start time are known and unambiguous.")
        else:
            rq = a.request
            st.markdown(f"Checked: **{rq.party_size} guests**, {fmt_local(rq.start, tz)}-"
                        f"{fmt_local(rq.end, tz, False)} · step-free required: "
                        f"{'yes' if rq.step_free_required else ('no' if rq.accessibility_known else 'UNKNOWN')}"
                        f" · buffer {wb.cfg.policies.turnover_buffer_minutes} min")
            av = a.availability
            if av and av.options:
                st.dataframe(_opt_rows(av.options, tz), hide_index=True, width="stretch")
            elif av:
                st.warning("No feasible seating at the requested time.")
            if av and av.rejected:
                with st.expander(f"Rejected options ({len(av.rejected)}) and reasons"):
                    st.dataframe([{"Unit": o.unit_id, "Tables": " + ".join(o.table_ids), "Cap": o.capacity,
                                   "Why rejected": "; ".join(o.reasons)} for o in av.rejected],
                                 hide_index=True, width="stretch")
            if a.alternatives:
                st.markdown("**Checked alternatives (same engine, same day):**")
                for t, o in a.alternatives:
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"{fmt_local(t, tz, False)} - {o.unit_id} ({' + '.join(o.table_ids)}, "
                                f"{'step-free' if o.step_free else 'stairs'})")
                    if c2.button("Propose", key=f"alt_{t.isoformat()}_{inq.record_version}"):
                        flash(wb.propose(inq.id, k(v, "propose_alt", t.isoformat()), start_override=t))
                        st.rerun()
        # proposals
        st.markdown("### Proposal")
        p = v.active_proposal
        if p is None:
            st.caption("No current proposal.")
        else:
            tone = {"proposed": "", "approved": "cobalt", "stale": "red"}[p.status.value]
            html_block(f'{chip(p.id)}{chip(p.status.value.upper(), tone)}{chip(p.kind.value.replace("_", " "))}'
                       f'{chip("for record v" + str(p.source_record_version))}{chip("policy " + p.policy_version)}')
            st.markdown(f"{p.option.unit_id} ({' + '.join(p.option.table_ids)}) · "
                        f"{fmt_local(p.option.start, tz)}-{fmt_local(p.option.end, tz, False)} · party {p.party_size}")
            if p.status == ProposalStatus.STALE:
                st.error(f"Stale: {p.status_reason}. It cannot be committed; recheck availability.")
            if p.required_decisions:
                st.caption("Still required before confirmation: " + ", ".join(p.required_decisions))
        if a.request is not None and a.availability and a.availability.options:
            opts = [o.unit_id for o in a.availability.options]
            c1, c2 = st.columns([2, 1])
            unit = c1.selectbox("Option", opts, key=f"unit_{inq.id}_{inq.record_version}")
            if c2.button("Check & propose", key=f"prop_{inq.id}", width="stretch"):
                flash(wb.propose(inq.id, k(v, "propose", unit), unit_id=unit))
                st.rerun()
        if p is not None and p.status == ProposalStatus.PROPOSED:
            if st.button(f"Approve proposal {p.id} for record v{inq.record_version}", type="primary",
                         key=f"appr_{p.id}"):
                flash(wb.approve_proposal(p.id, k(v, "approve", p.id)))
                st.rerun()
    with right:
        st.markdown("### Record decisions")
        st.caption("All actions change the simulated demo database only. Nothing is sent to guests or written to "
                   "any external booking system.")
        p = v.active_proposal
        approved = p is not None and p.status == ProposalStatus.APPROVED
        b = v.booking
        held = b is not None and b.status == BookingStatus.HELD and hold_is_active(b, wb.now())
        with st.container(border=True):
            st.markdown("**Booking actions**")
            if approved and p.kind == ProposalKind.NEW_ALLOCATION:
                deadline = None
                if a.hold_needs_operator_deadline:
                    st.warning("Short-notice request: enter a hold deadline before the dining start.")
                    c1, c2 = st.columns(2)
                    loc = wb.now().astimezone(tz) + timedelta(hours=2)
                    dd = c1.date_input("Hold until (date)", value=loc.date(), key=f"hd_{p.id}")
                    tt = c2.time_input("Hold until (time)", value=time(loc.hour, 0), key=f"ht_{p.id}")
                    deadline = datetime.combine(dd, tt, tzinfo=tz)
                else:
                    st.caption(f"Default hold: {wb.cfg.policies.hold_hours:g} h → "
                               f"{fmt_local(a.hold_expiry_default, tz) if a.hold_expiry_default else '-'}")
                if st.button("Create demo hold", key=f"hold_{p.id}", type="primary"):
                    flash(wb.create_hold(p.id, k(v, "hold", p.id, deadline), expires_at=deadline))
                    st.rerun()
            if approved and p.kind == ProposalKind.MODIFICATION:
                if st.button("Commit demo change (atomic)", key=f"mod_{p.id}", type="primary"):
                    flash(wb.commit_modification(p.id, k(v, "modify", p.id)))
                    st.rerun()
            can_confirm = (held and not a.requested_change) or (approved and p.kind == ProposalKind.NEW_ALLOCATION)
            if can_confirm:
                dis = bool(a.confirm_gaps) or bool([r for r in a.blockers if r.rule_id != "R-STALE"])
                if st.button("Record demo confirmation", key=f"confirm_{inq.id}", disabled=dis):
                    flash(wb.confirm(inq.id, k(v, "confirm"), proposal_id=None if held else p.id,
                                     expected_record_version=inq.record_version))
                    st.rerun()
                if dis:
                    st.caption("Confirmation needs: " + ", ".join(a.confirm_gaps + [
                        r.rule_id for r in a.blockers if r.rule_id != "R-STALE"]))
            if not (approved or can_confirm):
                st.caption("Approve a proposal to create a hold, confirm, or commit a change.")
        with st.container(border=True):
            st.markdown("**Other decisions** (reason required)")
            reason = st.text_input("Reason / note", key=f"reason_{inq.id}_{inq.record_version}_{len(v.events)}",
                                   placeholder="e.g. guest asked by email")
            c1, c2 = st.columns(2)
            if b is not None and b.status in (BookingStatus.HELD, BookingStatus.CONFIRMED):
                if c1.button("Record demo cancellation", key=f"cancel_{inq.id}"):
                    flash(wb.cancel_booking(inq.id, reason, k(v, "cancel", reason), inq.record_version))
                    st.rerun()
            if held and c2.button("Release hold", key=f"release_{inq.id}"):
                flash(wb.release_hold(inq.id, reason, k(v, "release", reason)))
                st.rerun()
            if not (b is not None and b.status in (BookingStatus.HELD, BookingStatus.CONFIRMED)):
                if c1.button("Decline request", key=f"decline_{inq.id}"):
                    flash(wb.decline(inq.id, reason, k(v, "decline", reason)))
                    st.rerun()
            if c2.button("Escalate to private events", key=f"esc_{inq.id}"):
                flash(wb.escalate(inq.id, reason, k(v, "escalate", reason)))
                st.rerun()
            if any(r.rule_id == "R-ALLERGY" for r in a.reviews):
                if st.button("Acknowledge allergy for follow-up (no guarantee)", key=f"allergy_{inq.id}"):
                    flash(wb.acknowledge_allergy(inq.id, reason, k(v, "allergy", reason)))
                    st.rerun()
            if any(r.rule_id == "R-FACTS-DIFFER" for r in a.advisories) or (
                    a.requested_change and b is not None):
                if st.button("Revert facts to current booking", key=f"revert_{inq.id}"):
                    flash(wb.revert_facts_to_booking(inq.id, reason, k(v, "revert", reason)))
                    st.rerun()
            if inq.state in (InquiryState.CLOSED, InquiryState.ESCALATED, InquiryState.RESOLVED,
                             InquiryState.AWAITING_GUEST):
                if st.button("Reopen inquiry", key=f"reopen_{inq.id}"):
                    flash(wb.reopen(inq.id, reason, k(v, "reopen", reason)))
                    st.rerun()
            else:
                if st.button("Close inquiry", key=f"close_{inq.id}"):
                    flash(wb.close(inq.id, reason, k(v, "close", reason)))
                    st.rerun()
        if any(r.rule_id == "R-MINSPEND" for r in a.reviews):
            with st.container(border=True):
                st.markdown("**Minimum spend (operator decision)**")
                st.caption("No amount is suggested by the system; no contract or payment is handled here.")
                amt = st.number_input("Amount (CAD, before tax and gratuity)", min_value=0.0, step=50.0,
                                      key=f"ms_{inq.id}")
                c1, c2 = st.columns(2)
                if c1.button("Record amount", key=f"msamt_{inq.id}"):
                    flash(wb.set_fact(inq.id, "min_spend_amount", amt, "operator-entered minimum spend",
                                      k(v, "msamt", amt)))
                    st.rerun()
                if c2.button("Record guest acknowledgment", key=f"msack_{inq.id}"):
                    flash(wb.set_fact(inq.id, "min_spend_acknowledged", "yes", reason or "guest acknowledged",
                                      k(v, "msack")))
                    st.rerun()
        with st.container(border=True):
            st.markdown("**Operator-reported (unverified)**")
            note = st.text_input("What was done outside this app?", key=f"ext_{inq.id}_{len(v.events)}")
            c1, c2 = st.columns(2)
            if c1.button("Record external action reported by operator", key=f"extb_{inq.id}"):
                flash(wb.record_external_action(inq.id, note, k(v, "external", note)))
                st.rerun()
            if c2.button("Mark reply sent (reported) - awaiting guest", key=f"await_{inq.id}"):
                flash(wb.mark_awaiting_guest(inq.id, note or None, k(v, "await", note)))
                st.rerun()
            st.caption("These are operator assertions. The app does not send email or update any external "
                       "system and cannot verify them.")


# ---------------------------------------------------------------------- draft + notes
def render_draft(wb: Workbench, v: InquiryView) -> None:
    inq = v.inquiry
    left, right = st.columns([1.4, 1], gap="medium")
    with left:
        st.markdown("### Response draft")
        allowed = allowed_purposes(v)
        from ..services.drafting import resolve_purpose

        suggested = resolve_purpose(v)
        if suggested is None:
            st.info("No draft suggested: interpret the message or enter facts manually first.")
        else:
            idx = allowed.index(suggested) if suggested in allowed else 0
            c1, c2 = st.columns([2, 1])
            purpose = c1.selectbox("Purpose", allowed, index=idx, format_func=lambda x: f"{x} - {PURPOSES[x]}",
                                   key=f"purpose_{inq.id}_{inq.record_version}")
            if c2.button("Generate draft", key=f"gen_{inq.id}", width="stretch"):
                with st.spinner("Drafting from canonical facts..."):
                    flash(wb.generate_draft(inq.id, k(v, "draft", purpose), purpose=purpose))
                st.rerun()
        d = v.latest_draft
        if d is None:
            st.caption("No draft yet.")
            return
        stale = v.draft_is_stale(d)
        approved_now = v.draft_approval_current(d)
        tone = "red" if stale else ("green" if approved_now else "")
        status = "STALE - facts or booking changed" if stale else (
            "REVIEWED (not sent)" if approved_now else d.status.upper())
        html_block(f'{chip(d.id)}{chip(status, tone)}{chip(d.purpose)}{chip("prose: " + d.prose_source)}'
                   f'{chip("for record v" + str(d.source_record_version))}')
        key_txt = f"dtext_{d.id}_{d.updated_at.isoformat()}"
        txt = st.text_area("Draft text (editable)", value=d.text, height=360, key=key_txt)
        dirty = txt != d.text
        if dirty:
            st.warning("Unsaved edits - save to revalidate before review.")
        c1, c2, c3 = st.columns(3)
        if c1.button("Save edit", disabled=not dirty, key=f"save_{d.id}"):
            flash(wb.save_draft_edit(d.id, txt, k(v, "save", d.id, txt)))
            st.rerun()
        errors = [x for x in d.validation if x["severity"] == "error"]
        if c2.button("Mark reviewed", disabled=dirty or stale or bool(errors) or approved_now,
                     key=f"approve_{d.id}"):
            flash(wb.approve_draft(d.id, k(v, "approve_draft", d.id)))
            st.rerun()
        c3.download_button("Export .txt", data=d.text, file_name=f"{d.id}.txt", key=f"dl_{d.id}",
                           on_click=lambda: wb.record_copy(inq.id, "draft export", k(v, "export", d.id), d.id))
        for x in d.validation:
            sev = x["severity"]
            fn = {"error": st.error, "warning": st.warning}.get(sev, st.caption)
            fn(f"{x['check']}: {x['message']}")
    with right:
        if v.latest_draft:
            d = v.latest_draft
            st.markdown("### Copy")
            st.code(d.text, language=None, wrap_lines=True)
            if st.button("Record that I copied the draft", key=f"copied_{d.id}"):
                flash(wb.record_copy(inq.id, "draft", k(v, "copy", d.id), d.id))
                st.rerun()
            st.caption("Copying or reviewing is not sending. Use 'Mark reply sent (reported)' only after you "
                       "actually send it elsewhere.")
        st.markdown("### Booking notes")
        notes = wb.booking_notes(inq.id)
        st.code(notes, language=None, wrap_lines=True)
        if st.button("Record that I copied booking notes", key=f"notes_{inq.id}"):
            flash(wb.record_copy(inq.id, "booking notes", k(v, "copy_notes")))
            st.rerun()


# ---------------------------------------------------------------------- history + diagnostics
def render_history(wb: Workbench, v: InquiryView) -> None:
    tz = wb.cfg.tz
    rows = []
    for e in reversed(v.events):
        if e.event_type == "inquiry_state_changed":
            change = f"{e.before} → {(e.after or {}).get('state')}"
        else:
            change = "" if e.after is None else str(e.after)[:160]
        rows.append({"Time": fmt_local(e.created_at, tz), "Actor": e.actor, "Event": e.event_type,
                     "Reason": e.reason or "", "Change": change, "Rec v": str(e.record_version or ""),
                     "Mode": e.mode})
    st.dataframe(rows, hide_index=True, width="stretch", height=min(36 * (len(rows) + 1), 560))
    st.caption("Times shown on the demo clock in restaurant local time. Events are append-only.")


def render_diagnostics(wb: Workbench, v: InquiryView) -> None:
    for it in reversed(v.interpretations):
        with st.expander(f"{it.id} · {it.provider_mode} · {it.status} · messages {', '.join(it.message_ids)}"):
            st.write({"model": it.model, "latency_ms": it.latency_ms, "intents": it.intents,
                      "ambiguities": it.ambiguities, "uninterpreted": it.uninterpreted, "error": it.error,
                      "usage": it.usage})
            if it.raw_output:
                st.code(it.raw_output[:5000], language="json")
    with st.expander("Assessment rule results (raw)"):
        a = v.assessment
        st.write({"next_action": a.next_action.value, "rule_ids": a.rule_ids, "confirm_gaps": a.confirm_gaps,
                  "open_intents": a.open_intents, "hold_ready": a.hold_ready, "confirm_ready": a.confirm_ready})
