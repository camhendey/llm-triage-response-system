"""Client-scoped NiceGUI reservation desk; all mutations use existing services."""

from __future__ import annotations

import html
import json
import os
from datetime import date, datetime, timedelta
from nicegui import ui, run
from ..domain.models import (
    ENUM_VALUES,
    FIELD_LABELS,
    BookingStatus,
    ProposalKind,
    ProposalStatus,
    Direction,
)
from ..services.presentation import (
    work_status,
    response_status,
    next_step,
    unread,
    hold_urgency,
    sent_event,
    referral_done,
)
from ..services.drafting import allowed_purposes, resolve_purpose, selected_option
from ..rules.availability import blocking_occupancies, hold_is_active, arrival_buckets
from ..services.handoff import daily_handoff, handoff_csv
from .common import (
    GROUPS,
    PURPOSE_LABELS,
    connection,
    execute,
    guest,
    pretty,
    when,
    key,
)
from .theme import CSS


def notify(message, **kwargs):
    kwargs.setdefault("position", "top-right")
    kwargs.setdefault("timeout", 2200)
    ui.notify(message, **kwargs)


def label(text, cls=""):
    element = ui.label(str(text)).classes(cls)
    if "page-title" in cls:
        element.props("role=heading aria-level=1")
    elif "section-title" in cls:
        element.props("role=heading aria-level=2")
    return element


def button(text, callback, *, primary=False, icon=None, test=None):
    b = ui.button(text, on_click=callback, icon=icon).props(
        "no-caps unelevated" if primary else "no-caps flat"
    )
    if not primary:
        b.classes("text-primary")
    if test:
        b.props(f"data-testid={test}")
    return b


def badge(text, tone=""):
    return label(text, "badge " + tone)


def notice(text, tone=""):
    return label(text, "notice " + tone).props("role=status")


class Desk:
    """One instance per browser page. No global connection, draft buffer or selection."""

    def __init__(self):
        self.kind = "demo"
        self.view = "Inquiries"
        self.iid = None
        self.stage = "Plan"
        self.query = ""
        self.filter = "Active"
        self.sort = "Priority"
        self.buffers = {}
        self.draft_bases = {}
        self.busy = False
        self.service_day = None
        self.service_mode = "Arrivals"
        self.study_seq = 1
        self.client = ui.context.client
        ui.colors(
            primary="#3458d4",
            secondary="#64748b",
            positive="#247354",
            negative="#a83f4c",
        )
        ui.add_css(CSS)
        with ui.header().classes("app-header items-center"):
            button("", lambda: self.drawer.toggle(), icon="menu", test="menu").props(
                'aria-label="Toggle navigation"'
            ).classes("lg:hidden")
            label("R", "brand-mark")
            label("Reservation desk", "brand")
            ui.space()
            badge("SYNTHETIC WORKSPACE").classes("environment-badge")
            badge("Synthetic").classes("mobile-environment")
            label("Nothing is sent or synced", "muted small header-note")
        with (
            ui.left_drawer(value=None, top_corner=False, bottom_corner=True)
            .props("width=218 breakpoint=1023")
            .classes("app-drawer") as self.drawer
        ):
            self.nav = ui.column().classes("drawer-inner w-full")
        self.root = ui.column().classes("page")
        self.overlay = ui.row().classes("busy-screen")
        with self.overlay:
            ui.spinner(size="28px")
            label("Working…")
        self.overlay.set_visibility(False)
        self.refresh()

    def refresh(self):
        with connection(self.kind) as wb:
            self.cfg = wb.cfg
            self.now = wb.now()
            self.views = wb.queue()
            self.v = (
                wb.load(self.iid)
                if self.iid and wb.repo.get_inquiry(self.iid)
                else None
            )
        if self.iid and not self.v:
            self.iid = None
            notify(
                "This inquiry is no longer available. The workspace may have been reset.",
                type="warning",
            )
        self.nav.clear()
        with self.nav:
            label("WORKSPACE", "eyebrow px-3 mb-3")
            for name, icon in [
                ("Inquiries", "inbox"),
                ("Service", "calendar_today"),
                ("Project", "layers"),
                ("Settings", "settings"),
            ]:
                button(name, lambda name=name: self.navigate(name), icon=icon).classes(
                    "nav-button " + ("selected" if self.view == name else "")
                )
            if self.iid and self.view == "Inquiries":
                ui.separator().classes("my-4")
                label("UP NEXT", "eyebrow px-3")
                for v in [
                    x
                    for x in self.views
                    if work_status(x) not in ("Closed", "Completed")
                ][:6]:
                    with (
                        ui.button(on_click=lambda v=v: self.open_inquiry(v.inquiry.id))
                        .props("flat no-caps")
                        .classes(
                            "queue-mini "
                            + ("selected" if v.inquiry.id == self.iid else "")
                        )
                    ):
                        with ui.column().classes("gap-1 w-full"):
                            label(guest(v), "text-xs font-semibold")
                            label(
                                f"{v.facts.value('party_size') or '?'} guests · {work_status(v)}",
                                "drawer-caption",
                            )
            ui.space()
            label(
                "Cameron Hendey\nSole developer",
                "drawer-caption px-3 whitespace-pre-line mt-8",
            )
        self.root.clear()
        with self.root:
            if self.view == "Inquiries":
                self.workspace() if self.v else self.inbox()
            elif self.view == "Service":
                self.service()
            elif self.view == "Settings":
                self.settings()
            else:
                self.project()

    def navigate(self, name):
        if self.busy:
            return
        self.view = name
        if name == "Inquiries":
            self.iid = None
        self.refresh()

    def open_inquiry(self, iid):
        if self.busy:
            return
        with connection(self.kind) as wb:
            v = wb.load(iid)
            if unread(v):
                wb.mark_conversation_reviewed(iid, key())
        self.iid, self.view = iid, "Inquiries"
        self.stage = (
            "Reply"
            if work_status(v)
            in ("Reply pending", "Completed", "Waiting for guest", "Referral recorded")
            else "Plan"
        )
        self.refresh()

    def switch_stage(self, stage):
        self.stage = stage
        self.refresh()

    async def command(
        self, fn, *, expected=None, stage=None, dialog=None, success="Saved", after=None
    ):
        if self.busy:
            return False
        self.busy = True
        self.overlay.set_visibility(True)
        try:
            result = await run.io_bound(execute, self.kind, fn, expected)
            if not result.ok:
                notify(result.message, type="negative", timeout=9000, close_button=True)
                return False
            if dialog:
                dialog.close()
            if stage:
                self.stage = stage
            if after:
                after(result)
            notify(success, type="positive", timeout=2500)
            self.refresh()
            return True
        except Exception as exc:
            # The UI retains values and exposes failures; no success is invented.
            notify(
                f"Action failed: {exc}", type="negative", timeout=0, close_button=True
            )
            return False
        finally:
            self.busy = False
            self.overlay.set_visibility(False)

    def action(self, fn, v=None, **kwargs):
        command_key = key()

        async def callback():
            return await self.command(
                lambda wb: fn(wb, command_key),
                expected=(
                    v.inquiry.id,
                    v.inquiry.record_version,
                    v.events[-1].id if v.events else None,
                )
                if v
                else None,
                **kwargs,
            )

        return callback

    def heading(self, title, subtitle):
        with ui.column().classes("gap-2"):
            label(title, "page-title")
            label(subtitle, "subtitle")

    def stats(self, entries):
        with ui.row().classes("stats"):
            for number, text in entries:
                with ui.column().classes("gap-0"):
                    label(number, "stat-number")
                    label(text, "stat-label")

    def inbox(self):
        with ui.row().classes("heading-row"):
            self.heading("Inquiries", "A clear next step for every guest request.")
            button(
                "New inquiry",
                self.new_inquiry,
                primary=True,
                icon="add",
                test="new-inquiry",
            )
        active = [
            v for v in self.views if work_status(v) not in ("Closed", "Completed")
        ]
        self.stats(
            [
                (len(active), "Active inquiries"),
                (
                    sum(work_status(v) == "Needs attention" for v in active),
                    "Need attention",
                ),
                (
                    sum(work_status(v) == "Reply pending" for v in active),
                    "Replies pending",
                ),
            ]
        )
        with ui.column().classes("panel flush-panel"):
            with ui.row().classes("toolbar p-5"):
                search = (
                    ui.input(
                        placeholder="Search guest, email or message", value=self.query
                    )
                    .props('outlined dense clearable aria-label="Search inquiries"')
                    .classes("grow")
                )
                search.on_value_change(
                    lambda e: self.update_filter(query=e.value or "")
                )
                ui.select(
                    [
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
                    ],
                    value=self.filter,
                    on_change=lambda e: self.update_filter(filter=e.value),
                ).props('outlined dense aria-label="Inquiry filter"').classes("w-44")
                ui.select(
                    ["Priority", "Newest", "Reservation date"],
                    value=self.sort,
                    on_change=lambda e: self.update_filter(sort=e.value),
                ).props('outlined dense aria-label="Sort inquiries"').classes("w-40")
            self.list_area = ui.column().classes("w-full gap-0")
            self.inbox_rows()
        label(
            f"{when(self.now, self.cfg)} · {'Fixed demo clock' if self.kind == 'demo' else 'Real clock'} · {self.cfg.restaurant.timezone}",
            "muted small",
        )

    def update_filter(self, **values):
        for k, v in values.items():
            setattr(self, k, v)
        self.inbox_rows()

    def inbox_rows(self):
        self.list_area.clear()
        rows = list(self.views)
        if self.filter == "Active":
            rows = [v for v in rows if work_status(v) not in ("Completed", "Closed")]
        elif self.filter == "New replies":
            rows = [v for v in rows if unread(v)]
        elif self.filter == "Holds expiring":
            rows = [v for v in rows if hold_urgency(v)]
        elif self.filter != "All":
            rows = [v for v in rows if work_status(v) == self.filter]
        if self.query:
            q = self.query.casefold()
            rows = [
                v
                for v in rows
                if q
                in " ".join(
                    [
                        guest(v),
                        v.inquiry.id,
                        *[str(f.value or "") for f in v.facts.fields.values()],
                        *[m.text for m in v.messages],
                    ]
                ).casefold()
            ]
        if self.sort == "Newest":
            rows.sort(key=lambda v: v.inquiry.updated_at, reverse=True)
        elif self.sort == "Reservation date":
            rows.sort(
                key=lambda v: (
                    v.facts.dining_start or datetime.max.replace(tzinfo=self.cfg.tz)
                )
            )
        with self.list_area:
            with ui.element("div").classes("inbox-head"):
                for t in ["Guest", "Reservation", "Next step", ""]:
                    label(t)
            if not rows:
                with ui.column().classes("p-8 gap-2"):
                    label("No inquiries match this view", "section-title")
                    label(
                        "Change the filter or search, or start a new inquiry.", "muted"
                    )
            for v in rows:
                with (
                    ui.element("div")
                    .classes("inbox-row")
                    .props(f"data-testid=row-{v.inquiry.id}")
                ):
                    with ui.column().classes("gap-1"):
                        with ui.row().classes("items-center gap-2"):
                            label(guest(v), "guest-name")
                            if unread(v):
                                label("New", "badge blue")
                        label(f"{v.facts.value('party_size') or '?'} guests", "muted")
                    with ui.column().classes("gap-1"):
                        label(when(v.facts.dining_start, self.cfg), "text-sm")
                        badge(
                            work_status(v),
                            "green" if work_status(v) == "Completed" else "",
                        )
                    with ui.column().classes("gap-1"):
                        label(next_step(v)[0], "text-sm")
                        if hold_urgency(v):
                            label(hold_urgency(v), "text-xs text-amber-800")
                    button(
                        "Open",
                        lambda v=v: self.open_inquiry(v.inquiry.id),
                        icon="arrow_forward",
                        test="open-" + v.inquiry.id,
                    )

    def new_inquiry(self):
        with ui.dialog() as dialog, ui.card().classes("dialog-card"):
            label("New inquiry", "section-title")
            label(
                "Paste the guest’s message. Missing information will remain unknown.",
                "muted",
            )
            name = ui.input("Guest name / label").props("outlined").classes("w-full")
            message = (
                ui.textarea("Guest message").props("outlined rows=7").classes("w-full")
            )
            err = label("", "text-negative text-sm")

            async def submit():
                if not (name.value or "").strip() or not (message.value or "").strip():
                    err.set_text("Enter a guest label and message.")
                    return

                def create(wb, k):
                    r = wb.create_inquiry(name.value, message.value, None, k)
                    if r.ok and wb.provider.mode == "offline_rules":
                        wb.interpret(r.data["inquiry_id"], k + ":interpret")
                    return r

                def opened(r):
                    self.iid = r.data["inquiry_id"]
                    self.stage = "Plan"
                    self.view = "Inquiries"

                await self.action(
                    create, dialog=dialog, success="Inquiry created", after=opened
                )()

            with ui.row().classes("w-full justify-end"):
                button("Cancel", dialog.close)
                button("Create inquiry", submit, primary=True, test="create-inquiry")
        dialog.open()

    def workspace(self):
        v = self.v
        with ui.row().classes("heading-row"):
            with ui.column().classes("gap-2"):
                with ui.row().classes("items-center gap-3"):
                    button(
                        "", lambda: self.navigate("Inquiries"), icon="arrow_back"
                    ).props('aria-label="Back to inbox"')
                    label(guest(v), "page-title")
                with ui.row().classes("items-center gap-2"):
                    label(
                        f"{v.facts.value('party_size') or '?'} guests · {when(v.facts.dining_start, self.cfg)}",
                        "subtitle",
                    )
                    badge(
                        v.booking.status.value.title() if v.booking else "Not booked",
                        "green"
                        if v.booking and v.booking.status == BookingStatus.CONFIRMED
                        else "",
                    )
                    badge(
                        "Reply: " + response_status(v),
                        "amber"
                        if response_status(v) in ("Needs review", "Update needed")
                        else "",
                    )
            button("Refresh", self.refresh, icon="refresh").props(
                'aria-label="Refresh current record"'
            )
        title, desc = next_step(v)
        with ui.element("div").classes("next-action"):
            with ui.column().classes("grow gap-1"):
                label(title, "next-title")
                missing = v.assessment.confirm_gaps
                label(
                    "Before confirmation: " + ", ".join(missing) if missing else desc,
                    "text-xs text-slate-600",
                )
                if hold_urgency(v):
                    label(hold_urgency(v), "text-xs text-amber-800 font-semibold")
            target = (
                "Reply"
                if missing
                or response_status(v) != "Not prepared"
                or v.assessment.next_action.value in ("no_action", "clarify")
                else "Plan"
            )
            button(
                "Review reply" if target == "Reply" else "Review plan",
                lambda: self.switch_stage(target),
                primary=True,
                icon="arrow_forward",
            )
        with ui.row().classes("segmented mobile-context"):
            for name in ["Request", "Plan", "Reply"]:
                button(name, lambda name=name: self.switch_stage(name)).classes(
                    "active" if self.stage == name else ""
                )
        with ui.element("div").classes(
            "workspace-grid " + ("request-mode" if self.stage == "Request" else "")
        ):
            with ui.column().classes("context-column"):
                self.conversation(v)
                self.details(v)
            with ui.column().classes("action-column"):
                with ui.row().classes("segmented desktop-stages"):
                    for name in ["Plan", "Reply"]:
                        button(
                            name,
                            lambda name=name: self.switch_stage(name),
                            test="stage-" + name.lower(),
                        ).classes("active" if self.stage == name else "")
                with ui.column().classes("panel"):
                    self.reply(v) if self.stage == "Reply" else self.plan(v)
        with ui.expansion("Activity & evidence", icon="history").classes("panel"):
            for event in reversed(v.events):
                with ui.column().classes("history-entry gap-1"):
                    label(
                        event.event_type.replace("_", " ").capitalize(),
                        "text-sm font-semibold",
                    )
                    label(
                        when(event.created_at, self.cfg) + " · " + event.actor,
                        "message-meta",
                    )
                    if event.reason:
                        label(event.reason, "muted")
                    with ui.expansion("Recorded values"):
                        ui.code(
                            json.dumps(
                                {
                                    "before": event.before,
                                    "after": event.after,
                                    "record_version": event.record_version,
                                },
                                indent=2,
                                default=str,
                            ),
                            language="json",
                        ).classes("w-full")
            with ui.expansion("Interpreter & rule diagnostics"):
                for it in reversed(v.interpretations):
                    label(f"{it.provider_mode} · {it.status}", "font-semibold text-sm")
                    ui.code(it.model_dump_json(indent=2), language="json").classes(
                        "w-full"
                    )
                ui.code(
                    json.dumps(
                        {
                            "next_action": v.assessment.next_action.value,
                            "rules": v.assessment.rule_ids,
                            "confirmation_gaps": v.assessment.confirm_gaps,
                        },
                        indent=2,
                    ),
                    language="json",
                ).classes("w-full")

    def conversation(self, v):
        with ui.column().classes("panel"):
            with ui.row().classes("heading-row"):
                label("Conversation", "section-title")
                badge(
                    f"{len(v.messages)} message" + ("s" if len(v.messages) != 1 else "")
                )

            def show(m):
                with ui.column().classes(
                    "w-full gap-2 "
                    + ("outbound" if m.direction == Direction.OUTBOUND_REPORTED else "")
                ):
                    label(
                        (
                            "Team · reported sent"
                            if m.direction == Direction.OUTBOUND_REPORTED
                            else "Guest"
                        )
                        + " · "
                        + when(m.received_at, self.cfg),
                        "message-meta",
                    )
                    label(m.text, "message")

            if len(v.messages) > 2:
                with ui.expansion(f"{len(v.messages) - 2} earlier messages"):
                    for m in v.messages[:-2]:
                        show(m)
            for m in v.messages[-2:]:
                show(m)
            with connection(self.kind) as wb:
                pending = wb.pending_message_ids(v.inquiry.id)
            if pending:
                notice(
                    "New text has not been interpreted. Review it or interpret it explicitly.",
                    "info",
                )
                button(
                    "Interpret message",
                    self.action(
                        lambda wb, k: wb.interpret(v.inquiry.id, k),
                        v,
                        success="Interpretation recorded",
                    ),
                    test="interpret",
                )
            with ui.expansion("Add guest reply", icon="add_comment"):
                buffer_key = "message:" + v.inquiry.id
                message = (
                    ui.textarea(
                        "New guest message",
                        value=self.buffers.get(buffer_key, ""),
                        on_change=lambda e: self.buffers.update({buffer_key: e.value}),
                    )
                    .props("outlined rows=4")
                    .classes("w-full")
                )

                async def add():
                    if not (message.value or "").strip():
                        notify("Enter the guest message.", type="warning")
                        return

                    def command(wb, k):
                        r = wb.add_message(v.inquiry.id, message.value, None, k)
                        if r.ok and wb.provider.mode == "offline_rules":
                            wb.interpret(v.inquiry.id, k + ":interpret")
                        return r

                    await self.action(
                        command,
                        v,
                        stage="Plan",
                        success="Guest reply added. Review the updated request.",
                        after=lambda r: self.buffers.pop(buffer_key, None),
                    )()

                button("Add message", add, primary=True, test="add-message")

    def details(self, v):
        with ui.column().classes("panel"):
            label("Guest details", "section-title")
            for group, fields in GROUPS.items():
                with ui.expansion(group, value=group != "Guest & preferences"):
                    for n in fields:
                        f = v.facts.get(n)
                        with ui.element("div").classes("detail-row"):
                            label(FIELD_LABELS[n], "muted")
                            with ui.column().classes("value gap-1 items-end"):
                                label(
                                    f"{v.facts.duration_minutes} min · policy default"
                                    if n == "requested_duration_minutes"
                                    and f.value is None
                                    else pretty(f.value)
                                )
                                if f.state in ("conflict", "needs_review"):
                                    badge("Review needed", "amber")
                    button(
                        "Edit " + group.lower(),
                        lambda group=group: self.edit(v, group),
                        icon="edit",
                        test="edit-" + group.split()[0].lower(),
                    )
            reviews = [
                f
                for f in v.facts.fields.values()
                if f.state in ("conflict", "needs_review")
            ]
            for f in reviews:
                with ui.column().classes("seating-card"):
                    label(
                        "Review " + FIELD_LABELS[f.field.value], "text-sm font-semibold"
                    )
                    if f.current:
                        label(
                            f.current.quote or f.current.note or "Coordinator record",
                            "muted",
                        )
                    if f.value is not None:
                        button(
                            "Keep " + pretty(f.value),
                            self.action(
                                lambda wb, k, f=f: wb.confirm_fact(
                                    v.inquiry.id,
                                    f.field.value,
                                    k,
                                    v.inquiry.record_version,
                                ),
                                v,
                                success="Detail confirmed",
                            ),
                        )
                    for o in f.conflicts:
                        label(o.quote or o.note or "Guest correction", "muted")
                        button(
                            "Use " + pretty(o.value),
                            self.action(
                                lambda wb, k, f=f, o=o: wb.set_fact(
                                    v.inquiry.id,
                                    f.field.value,
                                    o.value,
                                    "Resolved guest correction",
                                    k,
                                    v.inquiry.record_version,
                                ),
                                v,
                                success="Correction recorded",
                            ),
                        )
            with ui.expansion("Sources & previous values"):
                for f in v.facts.fields.values():
                    if f.current:
                        label(
                            FIELD_LABELS[f.field.value] + " · " + pretty(f.value),
                            "text-sm font-semibold",
                        )
                        label(
                            f.current.quote or f.current.note or "Coordinator record",
                            "muted",
                        )
                        for o, _ in f.history:
                            label(
                                pretty(o.value)
                                + " · "
                                + (o.quote or o.note or o.source_type),
                                "small text-slate-500",
                            )

    def edit(self, v, group):
        with ui.dialog() as dialog, ui.card().classes("dialog-card"):
            label("Edit " + group.lower(), "section-title")
            label(
                "Changes retain their source history and invalidate dependent plans and replies.",
                "muted",
            )
            controls = {}
            with ui.element("div").classes("form-grid"):
                for n in GROUPS[group]:
                    value = v.facts.get(n).value
                    if n in ENUM_VALUES:
                        controls[n] = ui.select(
                            {x: pretty(x) for x in ENUM_VALUES[n]},
                            label=FIELD_LABELS[n],
                            value=value if value in ENUM_VALUES[n] else None,
                            clearable=True,
                        ).props("outlined")
                    elif n in ("party_size", "requested_duration_minutes"):
                        controls[n] = ui.number(
                            FIELD_LABELS[n], value=value, min=1, max=500, precision=0
                        ).props("outlined clearable")
                    else:
                        controls[n] = ui.input(
                            FIELD_LABELS[n], value=str(value or "")
                        ).props("outlined")
                        if n == "requested_date":
                            controls[n].props("type=date")
                        if n == "requested_time":
                            controls[n].props("type=time")
            if group == "Reservation":
                label(
                    f"Blank duration uses the restaurant default ({v.facts.duration_minutes} minutes for the current party).",
                    "muted",
                )
            with ui.expansion("Clear incorrect information"):
                clear = (
                    ui.select(
                        {n: FIELD_LABELS[n] for n in GROUPS[group]},
                        label="Mark unknown",
                        multiple=True,
                        value=[],
                    )
                    .props("outlined use-chips")
                    .classes("w-full")
                )
                label("Clearing removes the current value, not its history.", "muted")
            reason = (
                ui.input("Source or reason", value="Coordinator review")
                .props("outlined")
                .classes("w-full")
            )
            error = label("", "text-negative text-sm")

            async def save():
                values = {
                    n: (None if n in clear.value or c.value == "" else c.value)
                    for n, c in controls.items()
                }
                changes = {n: x for n, x in values.items() if x != v.facts.get(n).value}
                if not changes:
                    error.set_text("No changes to save.")
                    return
                if not reason.value.strip():
                    error.set_text("Record the source or reason for this change.")
                    return
                await self.action(
                    lambda wb, k: wb.set_facts(
                        v.inquiry.id, changes, reason.value, k, v.inquiry.record_version
                    ),
                    v,
                    dialog=dialog,
                    stage="Plan",
                    success="Details updated. Review seating and the reply.",
                )()

            with ui.row().classes("w-full justify-end"):
                button("Cancel", dialog.close)
                button("Save changes", save, primary=True, test="save-details")
        dialog.open()

    def plan(self, v):
        a, b, p = v.assessment, v.booking, v.active_proposal
        label("Reservation plan", "section-title")
        if b:
            with ui.column().classes("booking-summary gap-1"):
                label("CURRENT BOOKING · " + b.status.value.upper(), "eyebrow")
                label(
                    f"{b.party_size} guests · {when(b.start, self.cfg)}",
                    "font-semibold",
                )
                label(
                    " + ".join(b.table_ids) + " · until " + when(b.end, self.cfg, False)
                )
        if a.requested_change:
            notice(
                "Change requested. The existing booking remains in place until you apply the change."
            )
        for issue in a.blockers + a.reviews:
            notice(issue.message.replace("_", " "))
        self.policy_reviews(v)
        if a.next_action.value == "process_cancellation":
            button(
                "Review cancellation",
                lambda: self.reason_dialog(v, "cancel"),
                primary=True,
                test="review-cancellation",
            )
        elif a.next_action.value == "escalate_private_events" or work_status(v) in (
            "Referral pending",
            "Referral recorded",
        ):
            label("Private-room availability is not checked by this app.", "muted")
            if not referral_done(v):
                button(
                    "Record completed referral",
                    lambda: self.reason_dialog(v, "referral"),
                    primary=True,
                )
            else:
                notice("Referral recorded as completed outside this app.", "success")
        elif not b or a.requested_change or b.status == BookingStatus.HELD:
            selected = p and p.status in (
                ProposalStatus.PROPOSED,
                ProposalStatus.APPROVED,
            )
            if p and p.status == ProposalStatus.STALE:
                notice(
                    "The earlier arrangement is out of date. Select again after reviewing the changed details."
                )
            option = selected_option(v)
            if option and (not b or a.requested_change):
                self.option_card(v, option, selected=bool(selected), primary=True)
            if selected:

                async def commit(action, expiry=None):
                    await self.action(
                        lambda wb, k: wb.review_and_commit(p.id, action, k, expiry),
                        v,
                        stage="Reply",
                        success="Booking decision recorded. Review the guest reply.",
                    )()

                with ui.row().classes("action-bar"):
                    if p.kind == ProposalKind.MODIFICATION:
                        button(
                            "Apply booking change",
                            lambda: commit("modify"),
                            primary=True,
                            test="commit-change",
                        )
                    else:
                        btn = button(
                            "Confirm booking",
                            lambda: commit("confirm"),
                            primary=True,
                            test="confirm-booking",
                        )
                        btn.set_enabled(not a.confirm_gaps)
                        button(
                            "Create hold",
                            lambda: self.hold_dialog(v, p),
                            test="create-hold",
                        )
                label(
                    "Availability and record versions are checked again before saving.",
                    "muted small",
                )
            elif b and hold_is_active(b, self.now) and not a.requested_change:
                btn = button(
                    "Confirm held booking",
                    self.action(
                        lambda wb, k: wb.confirm(
                            v.inquiry.id,
                            k,
                            expected_record_version=v.inquiry.record_version,
                        ),
                        v,
                        stage="Reply",
                        success="Booking confirmed. Review the reply.",
                    ),
                    primary=True,
                    test="confirm-held",
                )
                btn.set_enabled(not a.confirm_gaps)
            if a.confirm_gaps:
                button(
                    "Prepare clarification",
                    lambda: self.switch_stage("Reply"),
                    primary=True,
                    test="prepare-clarification",
                )
            with ui.expansion(
                "Compare seating & other times", icon="view_module", value=not option
            ):
                opts = list(a.availability.options) if a.availability else []
                alt = list(
                    {(o.unit_id, o.start): o for _, o in a.alternatives}.values()
                )
                with ui.tabs().classes("w-full") as tabs:
                    requested = ui.tab("Requested time")
                    other = ui.tab("Other times")
                with ui.tab_panels(tabs, value=requested if opts else other).classes(
                    "w-full bg-transparent"
                ):
                    with ui.tab_panel(requested).classes("p-0"):
                        self.options_list(v, opts)
                    with ui.tab_panel(other).classes("p-0"):
                        notice(
                            "An alternative is an offer. Record the guest’s accepted time before finalizing.",
                            "info",
                        )
                        self.options_list(v, alt)
                if a.availability and a.availability.rejected:
                    with ui.expansion("Why other tables do not fit"):
                        for rejected in a.availability.rejected:
                            label(
                                rejected.unit_id + " · " + "; ".join(rejected.reasons),
                                "muted",
                            )
        if a.advisories:
            with ui.expansion("Service & policy notes"):
                for issue in a.advisories:
                    label(issue.message, "muted")
        button(
            "Continue to reply",
            lambda: self.switch_stage("Reply"),
            icon="arrow_forward",
        )
        with ui.expansion("Other booking actions"):
            actions = []
            if b and b.status in (BookingStatus.HELD, BookingStatus.CONFIRMED):
                actions.append(("cancel", "Cancel booking"))
            if b and b.status == BookingStatus.HELD:
                actions.append(("release", "Release hold"))
            if not b:
                actions.append(("decline", "Decline request"))
            actions += [
                ("escalate", "Flag for private-events review"),
                ("external", "Record external action"),
                ("await", "Waiting for guest"),
            ]
            actions.append(
                ("reopen", "Reopen inquiry")
                if work_status(v)
                in (
                    "Closed",
                    "Completed",
                    "Waiting for guest",
                    "Referral pending",
                    "Referral recorded",
                )
                else ("close", "Close inquiry")
            )
            if a.requested_change:
                actions.append(("revert", "Keep original booking details"))
            for action, title in actions:
                button(title, lambda action=action: self.reason_dialog(v, action))
        self.notes(v)

    def options_list(self, v, opts):
        if not opts:
            label(
                "No suitable options. Review another time or clarify the request.",
                "muted",
            )
        for option in opts[:3]:
            self.option_card(v, option)
        if len(opts) > 3:
            with ui.expansion(f"Show {len(opts) - 3} more options"):
                for option in opts[3:]:
                    self.option_card(v, option)

    def option_card(self, v, o, selected=False, primary=False):
        with ui.column().classes("seating-card " + ("chosen" if selected else "")):
            with ui.row().classes("heading-row"):
                label(
                    "SELECTED ARRANGEMENT"
                    if selected
                    else "SUGGESTED ARRANGEMENT"
                    if primary
                    else o.area.upper(),
                    "eyebrow",
                )
                if selected:
                    badge("Selected", "blue")
            label(o.area.title() + " · " + " + ".join(o.table_ids), "section-title")
            label(
                f"{when(o.start, self.cfg)}–{when(o.end, self.cfg, False)} · up to {o.capacity} guests",
                "muted",
            )
            with ui.row().classes("gap-2"):
                badge("Step-free" if o.step_free else "Stairs")
                badge("Separate tables" if o.split else "One table")
            if not selected:
                button(
                    "Select arrangement",
                    self.action(
                        lambda wb, k: wb.propose(
                            v.inquiry.id, k, unit_id=o.unit_id, start_override=o.start
                        ),
                        v,
                        success="Arrangement selected",
                    ),
                    primary=primary,
                    test="select-arrangement" if primary else None,
                )
            with ui.expansion("Preview tables", icon="grid_view"):
                with connection(self.kind) as wb:
                    occ = blocking_occupancies(wb.repo.list_bookings(), wb.now())
                for area in self.cfg.areas:
                    label(area.title(), "eyebrow")
                    with ui.element("div").classes("table-grid"):
                        for table in [t for t in self.cfg.tables if t.area == area]:
                            busy = any(
                                table.id in x.table_ids
                                and x.start < o.end
                                and o.start
                                < x.end
                                + timedelta(
                                    minutes=self.cfg.policies.turnover_buffer_minutes
                                )
                                and (not v.booking or x.booking_id != v.booking.id)
                                for x in occ
                            )
                            state = (
                                "Preview"
                                if table.id in o.table_ids
                                else "Occupied"
                                if busy
                                else "Unoccupied"
                            )
                            with ui.column().classes(
                                "table-unit "
                                + (
                                    "preview"
                                    if state == "Preview"
                                    else "busy"
                                    if busy
                                    else ""
                                )
                            ):
                                label(table.id, "font-semibold")
                                label(f"{table.capacity} seats", "small")
                                label(state, "small")
                label(
                    "Schematic, not a physical floor plan. Unoccupied tables still need capacity, access and grouping checks.",
                    "muted small",
                )

    def hold_dialog(self, v, p):
        with ui.dialog() as dialog, ui.card().classes("dialog-card"):
            label("Create a hold", "section-title")
            label(
                "The hold reserves these tables only in the local workspace. It does not notify the guest.",
                "muted",
            )
            expiry = None
            if v.assessment.hold_needs_operator_deadline:
                expiry = (
                    ui.input(
                        "Hold expiry",
                        value=(self.now + timedelta(hours=2))
                        .astimezone(self.cfg.tz)
                        .strftime("%Y-%m-%dT%H:%M"),
                    )
                    .props("outlined type=datetime-local")
                    .classes("w-full")
                )
                label("Time zone: " + self.cfg.restaurant.timezone, "muted")
            else:
                label(
                    f"Default expiry: {self.cfg.policies.hold_hours:g} hours, subject to restaurant policy.",
                    "muted",
                )

            async def save():
                try:
                    dt = (
                        datetime.fromisoformat(expiry.value).replace(tzinfo=self.cfg.tz)
                        if expiry
                        else None
                    )
                except (ValueError, TypeError):
                    notify("Enter a valid expiry date and time.", type="negative")
                    return
                await self.action(
                    lambda wb, k: wb.review_and_commit(p.id, "hold", k, dt),
                    v,
                    dialog=dialog,
                    stage="Reply",
                    success="Hold recorded. Review the guest reply.",
                )()

            with ui.row().classes("justify-end w-full"):
                button("Cancel", dialog.close)
                button("Record hold", save, primary=True, test="record-hold")
        dialog.open()

    def reason_dialog(self, v, action):
        titles = {
            "cancel": "Cancel booking",
            "release": "Release hold",
            "decline": "Decline request",
            "close": "Close inquiry",
            "reopen": "Reopen inquiry",
            "referral": "Record completed referral",
            "escalate": "Flag for private-events review",
            "revert": "Keep original booking details",
            "external": "Record external action",
            "await": "Waiting for guest",
        }
        methods = {
            "cancel": "cancel_booking",
            "release": "release_hold",
            "decline": "decline",
            "close": "close",
            "reopen": "reopen",
            "referral": "report_referral",
            "escalate": "escalate",
            "revert": "revert_facts_to_booking",
            "external": "record_external_action",
            "await": "mark_awaiting_guest",
        }
        with ui.dialog() as dialog, ui.card().classes("dialog-card"):
            label(titles[action], "section-title")
            label(guest(v), "muted")
            if action in ("cancel", "release"):
                notice(
                    "This releases the allocated tables in the local record. No message will be sent."
                )
            elif action == "close":
                notice(
                    "This removes the inquiry from active work. It does not cancel the booking."
                )
            elif action in ("referral", "external", "await"):
                notice(
                    "Record only an action already completed outside this app.", "info"
                )
            reason = (
                ui.textarea("Reason / reference")
                .props("outlined rows=3")
                .classes("w-full")
            )

            async def save():
                if not (reason.value or "").strip():
                    notify("Enter a reason or reference.", type="warning")
                    return
                await self.action(
                    lambda wb, k: getattr(wb, methods[action])(
                        v.inquiry.id, reason.value, k
                    ),
                    v,
                    dialog=dialog,
                    stage="Reply"
                    if action in ("cancel", "release", "referral", "decline")
                    else "Plan",
                    success=titles[action] + " recorded",
                )()

            with ui.row().classes("w-full justify-end"):
                button("Go back", dialog.close)
                button(titles[action], save, primary=True, test="confirm-" + action)
        dialog.open()

    def policy_reviews(self, v):
        rules = {x.rule_id for x in v.assessment.reviews}
        if "R-ALLERGY" in rules:
            with ui.column().classes("seating-card"):
                label("Allergy follow-up", "text-sm font-semibold")
                label(pretty(v.facts.get("allergies").value), "muted")
                note = (
                    ui.input("Follow-up note").props("outlined dense").classes("w-full")
                )
                button(
                    "Record allergy review",
                    self.action(
                        lambda wb, k: wb.acknowledge_allergy(
                            v.inquiry.id, note.value, k
                        ),
                        v,
                        success="Allergy follow-up recorded",
                    ),
                )
                label("Review does not guarantee accommodation.", "muted small")
        if "R-MINSPEND" in rules:
            with ui.column().classes("seating-card"):
                label("Minimum-spend review", "text-sm font-semibold")
                current = v.facts.value("min_spend_amount")
                amount = (
                    ui.number("Amount (CAD)", value=current or 0, min=0, precision=2)
                    .props("outlined dense")
                    .classes("w-full")
                )
                note = (
                    ui.input("Decision / guest agreement reference")
                    .props("outlined dense")
                    .classes("w-full")
                )
                button(
                    "Save amount",
                    self.action(
                        lambda wb, k: wb.set_fact(
                            v.inquiry.id,
                            "min_spend_amount",
                            amount.value,
                            note.value,
                            k,
                            v.inquiry.record_version,
                        ),
                        v,
                        success="Amount recorded; renewed agreement is required.",
                    ),
                )
                if current is not None:
                    agreement = button(
                        "Record guest agreement",
                        self.action(
                            lambda wb, k: wb.set_fact(
                                v.inquiry.id,
                                "min_spend_acknowledged",
                                "yes",
                                note.value,
                                k,
                                v.inquiry.record_version,
                            ),
                            v,
                            success="Guest agreement recorded",
                        ),
                    )
                    agreement.bind_enabled_from(
                        amount, "value", lambda value: value == current
                    )
                label(
                    "Changing the amount invalidates the earlier agreement.",
                    "muted small",
                )

    def regenerate_dialog(self, v, purpose):
        with ui.dialog() as dialog, ui.card().classes("dialog-card"):
            label("Regenerate draft?", "section-title")
            label(
                "A new version uses the current record. Previous saved versions and this page’s unsaved edits remain available.",
                "muted",
            )
            with ui.row().classes("w-full justify-end"):
                button("Cancel", dialog.close)
                button(
                    "Regenerate draft",
                    self.action(
                        lambda wb, k: wb.generate_draft(v.inquiry.id, k, purpose),
                        v,
                        dialog=dialog,
                        stage="Reply",
                        success="New draft prepared",
                    ),
                    primary=True,
                    test="regenerate-confirm",
                )
        dialog.open()

    def reply(self, v):
        d = v.latest_draft
        sent = sent_event(v)
        with ui.row().classes("heading-row"):
            label("Guest reply", "section-title")
            badge(response_status(v), "green" if sent else "blue")
        if sent:
            notice("Reply recorded as sent externally", "success")
            label(
                when(sent.created_at, self.cfg)
                + " · Operator reported; delivery is not verified.",
                "muted",
            )
            with ui.expansion("View recorded reply"):
                label(d.text, "message")
            button(
                "Prepare follow-up", lambda: self.regenerate_dialog(v, "clarification")
            )
            self.notes(v)
            return
        purpose = resolve_purpose(v)
        label(PURPOSE_LABELS.get(purpose, pretty(purpose)), "eyebrow")
        if v.booking:
            b = v.booking
            label(
                f"Booking details: {b.party_size} guests · {when(b.start, self.cfg)} · "
                + " + ".join(b.table_ids),
                "booking-summary",
            )
        if not d:
            label(
                "Prepare a response from the current record, then review the wording before handoff.",
                "muted",
            )
            if purpose:
                button(
                    "Prepare reply",
                    self.action(
                        lambda wb, k: wb.generate_draft(v.inquiry.id, k, purpose),
                        v,
                        stage="Reply",
                        success="Draft prepared",
                    ),
                    primary=True,
                    test="generate-reply",
                )
            else:
                notice("Review the request before preparing a reply.", "info")
            return
        stale = v.draft_is_stale(d)
        if stale:
            notice(
                "This draft is out of date. Regenerate it using the latest message, details and seating."
            )
            button(
                "Update draft",
                lambda: self.regenerate_dialog(v, purpose),
                primary=True,
                test="update-draft",
            )
        draft_key = self.kind + ":draft:" + d.id
        original = self.draft_bases.setdefault(draft_key, d.text)
        local_text = self.buffers.get(draft_key, d.text)
        if local_text == d.text:
            self.draft_bases[draft_key] = d.text
        elif original != d.text:
            notice(
                "The saved reply changed in another tab. Your unsaved edits are retained. Compare them before saving."
            )
            with ui.expansion("Current saved reply", value=True):
                label(d.text, "message")
        text = (
            ui.textarea("Reply", value=self.buffers.get(draft_key, d.text))
            .props("outlined autogrow")
            .classes("reply-editor")
        )
        saved = label("", "muted small")
        action_area = ui.row().classes("action-bar")
        errors = [x for x in d.validation if x["severity"] == "error"]
        for item in d.validation:
            notice(item["message"], "error" if item["severity"] == "error" else "")

        def handoff_current():
            # Revalidate immediately before handing out approved text.
            with connection(self.kind) as wb:
                fresh = wb.load(v.inquiry.id)
                if (
                    not fresh.latest_draft
                    or fresh.latest_draft.id != d.id
                    or fresh.draft_is_stale(d)
                    or fresh.latest_draft.text != d.text
                    or not fresh.draft_approval_current(fresh.latest_draft)
                ):
                    notify(
                        "The record changed. Refresh and review the latest reply.",
                        type="warning",
                    )
                    return False
            return True

        def download_reply():
            if handoff_current():
                ui.download.content(
                    d.text,
                    filename=v.inquiry.id + "-reply.txt",
                    media_type="text/plain",
                )

        async def copy_reply():
            if not handoff_current():
                return
            payload = json.dumps(d.text).replace("<", "\\u003c")
            ok = await ui.run_javascript(
                "return navigator.clipboard.writeText("
                + payload
                + ").then(()=>true).catch(()=>false)",
                timeout=5,
            )
            if ok:
                with connection(self.kind) as wb:
                    wb.record_copy(v.inquiry.id, "reply", key(), draft_id=d.id)
                notify("Reply copied", type="positive")
                self.refresh()
            else:
                notify(
                    "Clipboard access is blocked. Use Download reply or select the text.",
                    type="warning",
                )

        def actions():
            dirty = text.value != d.text
            self.buffers[draft_key] = text.value
            saved.set_text(
                "Unsaved edits · retained while this page stays open"
                if dirty
                else "Saved draft · review before sending"
                if not v.draft_approval_current(d)
                else "Reviewed · ready to copy"
            )
            action_area.clear()
            with action_area:
                if dirty:
                    button(
                        "Save reply",
                        self.action(
                            lambda wb, k: wb.save_draft_edit(d.id, text.value, k),
                            v,
                            stage="Reply",
                            success="Reply saved",
                        ),
                        primary=True,
                        test="save-reply",
                    ).set_enabled(not stale)
                elif not stale and not v.draft_approval_current(d):
                    button(
                        "Mark reviewed",
                        self.action(
                            lambda wb, k: wb.approve_draft(d.id, k),
                            v,
                            stage="Reply",
                            success="Reply reviewed",
                        ),
                        primary=True,
                        test="review-reply",
                    ).set_enabled(not errors)
                elif not stale:
                    button(
                        "Copy reply",
                        copy_reply,
                        primary=True,
                        icon="content_copy",
                        test="copy-reply",
                    )
                    button(
                        "Download reply",
                        download_reply,
                    )
                    button(
                        "Mark as sent externally",
                        self.action(
                            lambda wb, k: wb.report_reply_sent(v.inquiry.id, d.id, k),
                            v,
                            stage="Reply",
                            success="Reply recorded as sent externally",
                        ),
                        test="sent-reply",
                    )

        text.on_value_change(lambda _: actions())
        actions()
        with ui.expansion("Reply options", icon="tune"):
            allowed = allowed_purposes(v)
            select = (
                ui.select(
                    {x: PURPOSE_LABELS.get(x, pretty(x)) for x in allowed},
                    label="Reply purpose",
                    value=purpose
                    if purpose in allowed
                    else (allowed[0] if allowed else None),
                )
                .props("outlined dense")
                .classes("w-full")
            )
            button("Regenerate draft", lambda: self.regenerate_dialog(v, select.value))
            if not v.draft_approval_current(d):
                button(
                    "Download unreviewed draft",
                    lambda: ui.download.content(
                        text.value,
                        filename=v.inquiry.id + "-UNREVIEWED.txt",
                        media_type="text/plain",
                    ),
                )
        self.notes(v)
        if len(v.drafts) > 1:
            with ui.expansion("Previous reply versions"):
                for prev in reversed(v.drafts[:-1]):
                    label(
                        prev.id
                        + " · "
                        + PURPOSE_LABELS.get(prev.purpose, pretty(prev.purpose)),
                        "muted",
                    )
                    label(
                        self.buffers.get(self.kind + ":draft:" + prev.id, prev.text),
                        "message",
                    )

    def notes(self, v):
        with connection(self.kind) as wb:
            notes = wb.booking_notes(v.inquiry.id)
        with ui.expansion("Booking notes for handoff", icon="description"):
            label(notes, "message text-xs")
            button(
                "Download booking notes",
                lambda: ui.download.content(
                    notes, filename=v.inquiry.id + "-notes.txt", media_type="text/plain"
                ),
            )

    def service(self):
        with connection(self.kind) as wb:
            bookings = wb.repo.list_bookings()
            occ = blocking_occupancies(bookings, wb.now())
            days = sorted({o.start.astimezone(self.cfg.tz).date() for o in occ})
            day = (
                date.fromisoformat(self.service_day)
                if self.service_day
                else (days[0] if days else self.now.astimezone(self.cfg.tz).date())
            )
            rows = daily_handoff(wb, day)
            buckets = arrival_buckets(self.cfg, bookings, self.now, day)
            inquiry_ids = {b.id: b.inquiry_id for b in bookings}
        with ui.row().classes("heading-row"):
            self.heading(
                "Service", "The arrivals, requirements and decisions that matter today."
            )
            button(
                "Export handoff",
                lambda: ui.download.content(
                    handoff_csv(rows),
                    filename=f"service-{day}.csv",
                    media_type="text/csv",
                ),
                icon="download",
            )
        with ui.row().classes("toolbar"):
            day_input = (
                ui.input("Service date", value=day.isoformat())
                .props("outlined dense type=date")
                .classes("w-48")
            )

            def change_day(e):
                try:
                    date.fromisoformat(e.value)
                except (ValueError, TypeError):
                    return
                self.service_day = e.value
                self.refresh()

            day_input.on_value_change(change_day)
            ui.space()
            with ui.row().classes("segmented w-64"):
                for name in ["Arrivals", "Timeline"]:

                    def change(name=name):
                        self.service_mode = name
                        self.refresh()

                    button(name, change).classes(
                        "active" if self.service_mode == name else ""
                    )
        self.stats(
            [
                (len(rows), "Active bookings"),
                (sum(r["Guests"] for r in rows), "Guests, including holds"),
                (sum(bool(r["Outstanding"]) for r in rows), "Need attention"),
            ]
        )
        for bucket in buckets:
            if bucket.count >= self.cfg.policies.arrival_warning_party_count:
                notice(
                    f"{bucket.count} large parties arrive around {bucket.bucket_start:%H:%M}. Review pacing. This is an arrival-count prompt, not a kitchen-capacity prediction."
                )
        if not rows:
            with ui.column().classes("panel"):
                label("No active bookings on this date.", "section-title")
        elif self.service_mode == "Timeline":
            self.timeline(day, occ)
        else:
            with ui.column().classes("panel flush-panel"):
                for r in rows:
                    with ui.column().classes("service-row"):
                        with ui.row().classes("heading-row"):
                            with ui.row().classes("items-center gap-3"):
                                label(r["Start"], "font-semibold text-primary")
                                label(
                                    f"{r['Guest']} · {r['Guests']} guests", "guest-name"
                                )
                                badge(
                                    r["Status"],
                                    "green" if r["Status"] == "Confirmed" else "amber",
                                )
                            iid = inquiry_ids.get(r["Booking"])
                            if iid:
                                button(
                                    "Open inquiry",
                                    lambda iid=iid: self.open_inquiry(iid),
                                    icon="arrow_forward",
                                )
                        label(
                            f"{r['Tables']} · until {r['End']} · {r['Billing']}",
                            "muted",
                        )
                        needs = [
                            f"{n}: {r[n]}"
                            for n in ["Accessibility", "Allergies", "Occasion"]
                            if r[n] not in ("none", "None reported", "Not recorded")
                        ]
                        if needs:
                            label(" · ".join(needs), "text-sm")
                        if r["Outstanding"]:
                            label(r["Outstanding"], "text-xs text-amber-800")
                        if r["Status"] == "Held":
                            label("Hold expires: " + r["Hold expires"], "muted small")
                        with ui.expansion("Full service notes"):
                            for n, x in r.items():
                                label(f"{n}: {x}", "small")

    def timeline(self, day, occ):
        start = datetime.combine(
            day, self.cfg.restaurant.opening_time, tzinfo=self.cfg.tz
        )
        end = datetime.combine(
            day, self.cfg.restaurant.closing_time, tzinfo=self.cfg.tz
        )
        slots = []
        while start < end:
            slots.append(start)
            start += timedelta(minutes=15)
        heads = "".join(
            f"<th>{s:%H:%M}</th>" if s.minute == 0 else "<th></th>" for s in slots
        )
        body = []
        for table in self.cfg.tables:
            cells = []
            i = 0
            while i < len(slots):
                s = slots[i]
                hit = next(
                    (
                        x
                        for x in occ
                        if table.id in x.table_ids
                        and x.start < s + timedelta(minutes=15)
                        and s < x.end
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
                title = f"{hit.guest_label} · {hit.party_size} · {when(hit.start, self.cfg, False)}–{when(hit.end, self.cfg, False)} · {hit.status}"
                cells.append(
                    f'<td colspan="{span}" class="{html.escape(hit.status)}" title="{html.escape(title)}">{html.escape(title)}</td>'
                )
                i += span
            body.append(
                f"<tr><th>{html.escape(table.id)} · {table.capacity}</th>{''.join(cells)}</tr>"
            )
        with ui.column().classes("panel"):
            ui.html(
                f'<div class="timeline-wrap" tabindex="0" role="region" aria-label="Service occupancy timeline"><table class="timeline"><tr><th>Table · seats</th>{heads}</tr>{"".join(body)}</table></div>'
            ).classes("w-full")
            label(
                "15-minute grid · Blue: confirmed · Amber: hold. Arrival briefs contain exact times and requirements.",
                "muted",
            )
            for x in occ:
                if x.start.astimezone(self.cfg.tz).date() == day:
                    with connection(self.kind) as wb:
                        b = wb.repo.get_booking(x.booking_id)
                    if b and b.inquiry_id:
                        button(
                            f"{x.guest_label} · {when(x.start, self.cfg, False)}",
                            lambda iid=b.inquiry_id: self.open_inquiry(iid),
                        )

    def settings(self):
        self.heading("Settings", "Workspace, interpretation and data controls.")
        with ui.column().classes("panel"):
            label("Workspace", "section-title")
            pick = (
                ui.select(
                    {"demo": "Demo · fixed clock", "session": "Session · real clock"},
                    value=self.kind,
                    label="Database",
                )
                .props("outlined")
                .classes("w-full max-w-md")
            )

            def switch(e):
                if self.busy:
                    return
                self.kind = e.value
                self.iid = None
                self.service_day = None
                self.refresh()

            pick.on_value_change(switch)
            label(
                when(self.now, self.cfg) + " · " + self.cfg.restaurant.timezone, "muted"
            )
            if self.kind == "demo":
                with ui.row():
                    for hours, title in [(1, "Advance 1 hour"), (24, "Advance 1 day")]:
                        button(
                            title,
                            self.action(
                                lambda wb, k, hours=hours: wb.set_demo_clock(
                                    wb.now() + timedelta(hours=hours), k
                                ),
                                success="Demo clock advanced",
                            ),
                        )
            with connection(self.kind) as wb:
                description = wb.provider.describe()
            label("Interpreter", "section-title")
            label(description, "message text-sm")
            label(
                "Live interpretation requires RW_PROVIDER=live and ANTHROPIC_API_KEY in .env, then a restart. Offline mode uses pattern rules, not a language model.",
                "muted",
            )
        with ui.column().classes("panel"):
            label("Import guest messages", "section-title")
            label(
                "CSV columns: guest_label, message; optional received_at (ISO), inquiry_id. Imported messages are interpreted. Live mode can make API calls.",
                "muted",
            )
            upload_state = {}

            async def uploaded(e):
                upload_state["data"] = await e.file.read()
                upload_label.set_text(e.file.name + " ready to import")

            ui.upload(
                label="Choose a CSV file",
                on_upload=uploaded,
                auto_upload=True,
                max_file_size=5_000_000,
                on_rejected=lambda: notify(
                    "Choose a CSV smaller than 5 MB.", type="warning"
                ),
            ).props("accept=.csv").classes("w-full max-w-md")
            upload_label = label("No file selected", "muted")
            report_area = ui.column().classes("w-full")

            async def import_rows():
                if "data" not in upload_state:
                    notify("Select a CSV file first.", type="warning")
                    return
                if self.busy:
                    return
                from ..services.csv_import import import_csv
                import hashlib

                content = upload_state["data"]
                kind = self.kind

                def process():
                    with connection(kind) as wb:
                        return import_csv(
                            wb,
                            content,
                            batch_key="nicegui:csv:"
                            + hashlib.sha256(content).hexdigest(),
                            interpret=True,
                        )

                self.busy = True
                self.overlay.set_visibility(True)
                try:
                    report = await run.io_bound(process)
                    report_area.clear()
                    with report_area:
                        if report.fatal:
                            notice(report.fatal, "error")
                        else:
                            notice(
                                f"{report.imported} imported · {report.failed} rejected",
                                "info",
                            )
                            for row in report.rows:
                                if not row.ok:
                                    label(
                                        f"Row {row.row}: {row.message}",
                                        "text-negative text-sm",
                                    )
                except Exception as exc:
                    notify(str(exc), type="negative")
                finally:
                    self.busy = False
                    self.overlay.set_visibility(False)

            button("Import CSV", import_rows, primary=True)
        if self.kind == "demo":
            with ui.expansion("Reset synthetic demo data", icon="restart_alt").classes(
                "panel"
            ):
                label(
                    "Replaces only the designated demo database. The session database is never reset.",
                    "muted",
                )
                button("Reset demo", self.reset_dialog)

    def reset_dialog(self):
        from ..services.bootstrap import reset_demo

        with ui.dialog() as dialog, ui.card().classes("dialog-card"):
            label("Reset the demo workspace?", "section-title")
            notice(
                "All changes in the demo database will be replaced with the original synthetic examples. Other open tabs must be reloaded."
            )
            check = ui.checkbox("Replace the demo records")

            async def reset():
                if not check.value or self.busy:
                    return
                self.busy = True
                try:
                    await run.io_bound(reset_demo)
                    self.buffers.clear()
                    self.draft_bases.clear()
                    self.iid = None
                    self.service_day = None
                    dialog.close()
                    self.refresh()
                    notify("Demo reset", type="positive")
                except Exception as exc:
                    notify(str(exc), type="negative")
                finally:
                    self.busy = False

            with ui.row().classes("justify-end w-full"):
                button("Cancel", dialog.close)
                button("Reset demo data", reset, primary=True).bind_enabled_from(
                    check, "value"
                )
        dialog.open()

    def project(self):
        self.heading(
            "Project", "From an operational workflow to a tested reservation workbench."
        )
        label(
            "Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.",
            "muted",
        )
        with ui.tabs().classes("w-full") as tabs:
            examples = ui.tab("Examples")
            evidence = ui.tab("Evidence")
            study = ui.tab("Operator study")
            policies = ui.tab("Policies")
        with ui.tab_panels(tabs, value=examples).classes("w-full bg-transparent"):
            with ui.tab_panel(examples).classes("p-0"):
                notice(
                    "Synthetic restaurant, guests and policies. The original JOEY workflow used LLM chat tools and manual booking operations; this is its later software implementation.",
                    "info",
                )
                for iid, title, desc in [
                    (
                        "INQ-0101",
                        "A straightforward booking",
                        "Choose seating, confirm the booking and review the guest reply.",
                    ),
                    (
                        "INQ-0103",
                        "An accessibility conflict",
                        "Resolve requirements and compare step-free seating.",
                    ),
                    (
                        "INQ-0104",
                        "A changing party size",
                        "Check how a correction invalidates the earlier arrangement.",
                    ),
                ]:
                    with ui.column().classes("panel mt-4"):
                        label(title, "section-title")
                        label(desc, "muted")
                        if self.kind == "demo":
                            button(
                                "Open example",
                                lambda iid=iid: self.open_inquiry(iid),
                                icon="arrow_forward",
                            )
                        else:
                            label(
                                "Switch to Demo in Settings to open the seeded examples.",
                                "muted",
                            )
            with ui.tab_panel(evidence).classes("p-0"):
                with ui.column().classes("panel"):
                    label("Evidence and limits", "section-title")
                    label(
                        "The inspected 40-case offline regression recorded 39/40 expected next actions, 97/97 labelled fields and zero critical-error cases. These are regression results on synthetic cases, not an independent production benchmark.",
                        "message",
                    )
                    label(
                        "The original blind run, later retests and a 12-case extraction challenge are retained in results/. Verification dates record actual software test runs.",
                        "muted",
                    )
                    notice(
                        "Live API performance and human time savings remain unmeasured. No messages are sent and no external reservation system is connected.",
                        "info",
                    )
                    label(
                        "See docs/VERIFICATION.md, docs/EVALUATION.md and docs/NICEGUI_MIGRATION.md for reproducible checks and migration decisions.",
                        "muted",
                    )
            with ui.tab_panel(study).classes("p-0"):
                self.study_area = ui.column().classes("w-full gap-4")
                self.study()
            with ui.tab_panel(policies).classes("p-0"):
                with ui.column().classes("panel"):
                    label("Synthetic restaurant configuration", "section-title")
                    label(
                        "These are demonstration values, not JOEY operating policies.",
                        "muted",
                    )
                    pol = self.cfg.policies
                    rows = [
                        ("Time zone", self.cfg.restaurant.timezone),
                        (
                            "Opening hours",
                            f"{self.cfg.restaurant.opening_time:%H:%M}–{self.cfg.restaurant.closing_time:%H:%M}",
                        ),
                        (
                            "Default duration",
                            f"{pol.default_duration_minutes} minutes; up to {pol.small_party_max} guests: {pol.small_party_duration_minutes} minutes",
                        ),
                        ("Turnover buffer", f"{pol.turnover_buffer_minutes} minutes"),
                        (
                            "Hold expiry",
                            f"{pol.hold_hours:g} hours; short-notice holds need an explicit deadline",
                        ),
                        (
                            "Automatic gratuity",
                            f"{pol.auto_gratuity_percent:g}% for parties of {pol.auto_gratuity_min_party}+",
                        ),
                        (
                            "Minimum-spend review",
                            f"Parties of {pol.minimum_spend_review_min_party}+",
                        ),
                        (
                            "Main-restaurant party limit",
                            str(self.cfg.restaurant.max_main_restaurant_party),
                        ),
                        (
                            "Confirmation requirements",
                            ", ".join(
                                FIELD_LABELS.get(n, n)
                                for n in pol.confirmation_required_fields
                            ),
                        ),
                    ]
                    for title, value in rows:
                        with ui.element("div").classes("detail-row"):
                            label(title, "muted")
                            label(value, "value")
                    with ui.expansion("Tables, groupings and full configuration"):
                        ui.code(
                            self.cfg.model_dump_json(indent=2), language="json"
                        ).classes("w-full")

    def study(self):
        from ..study.harness import (
            StudyStore,
            load_cases,
            status,
            CHECKLIST,
            METHOD_LABELS,
            TRANSITIONS,
            sessions_csv,
        )

        store = StudyStore()
        try:
            rows = [dict(r) for r in store.sessions()]
            summary = status(store)
            r = rows[self.study_seq - 1]
            state = store.state(self.study_seq)
            durations = store.durations(self.study_seq)
            csv = sessions_csv(store)
        finally:
            store.conn.close()
        case = next(c for c in load_cases() if c.id == r["case_id"])
        self.study_area.clear()
        with self.study_area:
            notice(
                f"{summary['sessions_completed']}/{summary['sessions_planned']} sessions completed. Timings are recorded from operator actions; none are generated.",
                "info",
            )

            def choose(e):
                self.study_seq = e.value
                self.study()

            ui.select(
                {
                    x[
                        "seq"
                    ]: f"#{x['seq']} · {x['case_id']} · {METHOD_LABELS[x['method']]} · {x['status']}"
                    for x in rows
                },
                value=self.study_seq,
                label="Study session",
                on_change=choose,
            ).props("outlined").classes("w-full")
            with ui.column().classes("panel"):
                label(case.title, "section-title")
                label(case.brief, "message")
                label("Method: " + METHOD_LABELS[r["method"]], "muted")
                label(
                    "Materials: docs/study/PROTOCOL.md and the method/availability sheets.",
                    "muted small",
                )
                badge("Timer: " + state, "blue")

                def timer(action):
                    s = StudyStore()
                    try:
                        s.record(self.study_seq, action)
                    except ValueError as exc:
                        notify(str(exc), type="warning")
                    finally:
                        s.conn.close()
                    self.study()

                with ui.row():
                    for action, title in [
                        ("start", "Start"),
                        ("pause", "Pause"),
                        ("resume", "Resume"),
                        ("wait_start", "Model wait"),
                        ("wait_end", "Wait done"),
                        ("finish", "Finish"),
                    ]:
                        button(title, lambda action=action: timer(action)).set_enabled(
                            action in TRANSITIONS[state]
                        )
                if durations["active_s"] is not None:
                    label(
                        f"Active {durations['active_s']}s · elapsed {durations['elapsed_s']}s · model wait {durations['model_wait_s']}s",
                        "muted",
                    )
                    label("Expected outcome: " + case.expected_outcome, "message")
                operator = (
                    ui.input("Operator", value=r["operator"] or "")
                    .props("outlined")
                    .classes("w-full")
                )
                familiarity = (
                    ui.select(
                        [
                            "first exposure",
                            "seen in an earlier method",
                            "seen during development",
                        ],
                        value=r["familiarity"] or "first exposure",
                        label="Case familiarity",
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                old = json.loads(r["checklist"] or "{}")
                checks = {
                    n: ui.checkbox(title, value=bool(old.get(n)))
                    for n, title in CHECKLIST
                }
                counts = {}
                with ui.element("div").classes("form-grid"):
                    for n, title in [
                        ("corrections", "Corrections"),
                        ("errors", "Errors"),
                        ("incomplete_requirements", "Incomplete requirements"),
                    ]:
                        counts[n] = ui.number(
                            title, value=r[n] or 0, min=0, max=99, precision=0
                        ).props("outlined")
                notes = (
                    ui.textarea("Study notes", value=r["notes"] or "")
                    .props("outlined")
                    .classes("w-full")
                )
                artifact = (
                    ui.input("Output artifact path", value=r["artifact_path"] or "")
                    .props("outlined")
                    .classes("w-full")
                )

                def save():
                    s = StudyStore()
                    try:
                        s.update(
                            self.study_seq,
                            operator=operator.value,
                            familiarity=familiarity.value,
                            checklist={n: c.value for n, c in checks.items()},
                            notes=notes.value,
                            artifact_path=artifact.value,
                            **{n: c.value for n, c in counts.items()},
                        )
                    finally:
                        s.conn.close()
                    notify("Study record saved", type="positive")
                    self.study()

                button("Save study record", save, primary=True)
            button(
                "Export study sessions",
                lambda: ui.download.content(
                    csv, filename="study-sessions.csv", media_type="text/csv"
                ),
            )


def start():
    from dotenv import load_dotenv

    load_dotenv()

    @ui.page("/")
    def index():
        Desk()

    ui.run(
        host=os.getenv("RW_HOST", "127.0.0.1"),
        port=int(os.getenv("RW_PORT", "8080")),
        title="Reservation desk",
        favicon="R",
        reload=False,
        show=False,
    )
