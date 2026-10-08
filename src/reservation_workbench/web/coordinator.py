"""Focused Request → Plan → Communicate workspace with a separate synthetic demo."""

import csv
import io
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from nicegui import ui

from ..coordinator.availability import assess, compare, restore, serialize
from ..coordinator.store import Store, digest, now, stamp
from ..coordinator.workflow import (
    CHECKS,
    DETAILS,
    PURPOSES,
    STATES,
    Workflow,
    accepted,
    booking_package,
    compose,
    draft_hash,
    external_current,
    final_gaps,
    next_action,
    priority,
    profile,
    save_profile,
    service_record,
    validate_purpose,
)
from ..services.opentable_import import guest_candidates, read_report, suggest_mapping
from .imports import SessionImports
from .theme import CSS


def field(title, value="", multiline=False):
    return (
        (ui.textarea if multiline else ui.input)(title, value=value or "")
        .props("outlined")
        .classes("w-full")
    )


def select(title, options, value=None, multiple=False):
    return (
        ui.select(options, label=title, value=value, multiple=multiple)
        .props("outlined")
        .classes("w-full")
    )


def button(title, fn, primary=False, test=None):
    return ui.button(title, on_click=fn).props(
        ("unelevated" if primary else "flat")
        + " no-caps"
        + (f" data-testid={test}" if test else "")
    )


class PersistentImports(SessionImports):
    def __init__(self, desk):
        super().__init__(desk)
        self.venue = desk.p["name"]
        self.snapshots = {k: restore(v) for k, v in desk.store.reports().items()}

    def page(self):
        d = self.desk
        d.heading(
            "Prepare your shift",
            "Upload and review a fresh reservations report. Reloading this page preserves the active shift.",
        )
        with ui.column().classes("panel"):
            ui.label(
                "Reports are local, read-only snapshots. No OpenTable connection and no AI upload."
            ).classes("section-title")
            ui.label(
                "Raw snapshots expire after 24 hours on next access, or are cleared when you end the shift. Inquiries and copied evidence persist."
            ).classes("muted")

            async def uploaded(e):
                try:
                    self.pending = read_report(await e.file.read(), e.file.name)
                    self.mapping = suggest_mapping(self.pending)
                    saved = d.store.setting("mapping:" + digest(self.pending.headers))
                    if saved:
                        self.mapping = saved
                    d.refresh()
                except ValueError as exc:
                    d.error(exc)

            ui.upload(
                label="Upload OpenTable CSV or TSV",
                auto_upload=True,
                on_upload=uploaded,
                max_file_size=5_000_000,
            ).props("accept=.csv,.tsv data-testid=coord-upload").classes("w-full")
            for kind, value in d.store.reports().items():
                ui.label(
                    f"{kind.title()}: {value['report']['filename']} · {len(value['rows'])} rows"
                ).classes("font-semibold")
                ui.label(
                    f"Coverage: {value['coverage_start']} to {value['coverage_end']} · exported {value['exported_at']}"
                ).classes("muted")
                for warning in restore(value).warnings_now():
                    ui.label(warning).classes("muted")
            if d.store.reports():
                button("Open work queue", lambda: d.go("Queue"), True)
            with ui.expansion("Working without an export").classes("w-full"):
                note = field("Reason for manual checks")

                def manual():
                    if not note.value.strip():
                        return d.error("Record why a fresh export is unavailable.")
                    shift = d.store.setting("shift")
                    shift["manual_reason"] = note.value
                    d.store.set_setting("shift", shift)
                    d.go("Queue")

                ui.label(
                    "Snapshot assistance remains unavailable. Every booking still needs a recorded external availability check."
                ).classes("muted")
                button("Continue with manual checks", manual)
        if self.pending:
            self.mapping_form()
        with ui.column().classes("panel"):
            ui.label("End of shift").classes("section-title")
            ui.label(
                "Saved inquiries and follow-ups remain for the next shift. Raw exports are cleared."
            ).classes("muted")
            button("End shift and clear exports", d.end_shift)

    def preview_dialog(self, snapshot):
        d = self.desk
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("Review import").classes("section-title")
            ui.label(f"{len(snapshot.rows)} valid rows · no rows skipped")
            ui.label(
                compare(d.store.reports().get(snapshot.kind), serialize(snapshot))
            ).classes("muted")
            for warning in snapshot.warnings_now():
                ui.label(warning).classes("muted")
            complete = ui.checkbox(
                "I checked filters and confirm complete reservation coverage for the declared dates."
            )
            ui.label(
                "Without this confirmation the report is reference-only. A missing row never cancels a booking."
            ).classes("notice")

            def apply():
                try:
                    if (
                        self.venue != d.p["name"]
                        or snapshot.timezone != d.p["timezone"]
                    ):
                        raise ValueError(
                            "Restaurant name and time zone must match workspace Settings."
                        )
                    d.store.save_report(serialize(snapshot, complete.value))
                    d.store.set_setting(
                        "mapping:" + digest(snapshot.report.headers), snapshot.mapping
                    )
                    self.snapshots[snapshot.kind] = snapshot
                    self.pending = None
                    dialog.close()
                    d.refresh()
                except ValueError as exc:
                    d.error(exc)

            button("Use this report", apply, True, "ot-apply")
            button("Back", dialog.close)
        dialog.open()


class CoordinatorDesk:
    def __init__(self, case="", view="Queue", buffer=""):
        ui.add_css(
            CSS
            + """
          .coord-page{max-width:1200px;margin:auto;padding:28px;gap:22px;width:100%}
          .coord-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:20px;width:100%;align-items:start}
          .coord-nav{display:flex;flex-wrap:wrap;gap:6px;width:100%}.coord-nav .selected{background:#e3e9fc;color:#284dc3}
          .coord-page .q-field{min-width:0}.coord-page .q-expansion-item{max-width:100%}.coord-page .q-card{min-width:0}
          .coord-page .q-btn__content{white-space:normal}.coord-page pre{white-space:pre-wrap;overflow-wrap:anywhere}
          @media(max-width:800px){.coord-grid{grid-template-columns:minmax(0,1fr)}.coord-page{padding:16px;gap:16px}.coord-page .panel{padding:16px}.page-title{font-size:25px}}
        """
        )
        ui.colors(primary="#3458d4")
        self.store = Store()
        self.case_id = case
        self.view = view
        self.buffer_id = buffer or uuid4().hex
        self.p = self.store.setting("profile", profile())
        self.cfg = SimpleNamespace(
            restaurant=SimpleNamespace(timezone=self.p["timezone"])
        )
        self.imports = PersistentImports(self)
        self.root = ui.column().classes("coord-page")
        self.refresh()

    def heading(self, title, subtitle=""):
        ui.label(title).classes("page-title")
        if subtitle:
            ui.label(subtitle).classes("subtitle")

    def error(self, exc):
        ui.notify(
            str(exc),
            type="negative",
            position="top-right",
            timeout=7000,
            close_button=True,
        )

    def safe(self, fn):
        try:
            fn()
        except (ValueError, KeyError, TypeError) as exc:
            self.error(exc)

    def go(self, view, cid=None):
        self.view = view
        if cid is not None:
            self.case_id = cid
        self.refresh()

    def act(self, c, action, **data):
        def run():
            self.flow.run(c, action, **data)
            ui.notify(
                "Saved",
                type="positive",
                position="top-right",
                timeout=1000,
                group=False,
            )
            self.refresh()

        self.safe(run)

    def refresh(self):
        self.root.clear()
        self.p = self.store.setting("profile", profile())
        self.cfg.restaurant.timezone = self.p["timezone"]
        self.imports.venue = self.p["name"]
        shift = self.store.setting("shift", {})
        self.actor = shift.get("operator", "")
        self.flow = Workflow(self.store, self.actor)
        with self.root:
            with ui.row().classes("w-full items-center justify-between"):
                with ui.row().classes("items-center"):
                    ui.label("R").classes("brand-mark")
                    ui.label("Reservation coordinator").classes("brand")
                ui.label("LOCAL · NOTHING SENT AUTOMATICALLY").classes("environment")
            if not self.actor or shift.get("ended"):
                self.welcome()
                return
            with ui.row().classes("coord-nav"):
                for label, view in [
                    ("Work queue", "Queue"),
                    ("Service", "Service"),
                    ("Shift & reports", "Reports"),
                    ("Settings", "Settings"),
                ]:
                    button(label, lambda v=view: self.go(v)).classes(
                        "selected" if self.view == view else ""
                    )
                ui.space()
                button("Refresh", self.refresh)
            if (
                not self.store.reports().get("reservations")
                and not shift.get("manual_reason")
                and self.view not in ("Reports", "Settings")
            ):
                ui.label(
                    "Start this shift with a fresh report, or record why manual-only checks are necessary."
                ).classes("notice")
                self.view = "Reports"
            if self.view == "Reports":
                self.imports.page()
            elif self.view == "Settings":
                self.settings()
            elif self.view == "Service":
                self.service()
            elif self.view == "Evidence":
                self.evidence()
            elif self.case_id and self.view in ("Request", "Plan", "Communicate"):
                self.inquiry()
            else:
                self.queue()
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(
                    f"{self.p['name']} · {self.actor} · {self.p['timezone']}"
                ).classes("muted")
                ui.link("Synthetic demo", "/demo").classes("small")
                button("Evidence & measurement", lambda: self.go("Evidence"))
            url = "/?" + __import__("urllib.parse", fromlist=["urlencode"]).urlencode(
                {"case": self.case_id, "view": self.view, "buffer": self.buffer_id}
            )
            ui.timer(
                0.05,
                lambda: ui.run_javascript(
                    'history.replaceState(null,"",' + json.dumps(url) + ")"
                ),
                once=True,
            )

    def welcome(self):
        self.heading(
            "A clear start to every shift",
            "Your work queue is empty until you add inquiries. Synthetic bookings live only in the separate demo.",
        )
        with ui.column().classes("panel max-w-xl"):
            operator = field("Coordinator name")
            name = field("Restaurant name", self.p["name"])
            tz = field("Restaurant time zone (IANA)", self.p["timezone"])
            consent = ui.checkbox(
                "I am authorized to store guest records locally on this computer."
            )

            def start():
                if not operator.value.strip() or not consent.value:
                    raise ValueError(
                        "Enter your name and confirm authorized local storage."
                    )
                p = deepcopy(self.p)
                p.update(name=name.value.strip(), timezone=tz.value.strip())
                if p != self.p:
                    self.p = save_profile(self.store, p, self.p["version"])
                self.store.clear_reports()
                self.store.set_setting(
                    "shift", {"operator": operator.value.strip(), "started_at": stamp()}
                )
                self.cfg.restaurant.timezone = self.p["timezone"]
                self.imports = PersistentImports(self)
                self.go("Reports")

            button("Start shift", lambda: self.safe(start), True, "start-shift")
            ui.label(
                "Single-operator local prototype. No authentication, encryption or production multi-user controls. Use synthetic or anonymized records for a portfolio demonstration."
            ).classes("muted")
            ui.link("Explore the synthetic demo instead", "/demo")

    def end_shift(self):
        shift = self.store.setting("shift", {})
        if shift.get("operator") != self.actor or shift.get("ended"):
            return self.error("The active shift changed. Refresh before ending it.")
        for c in self.store.cases():
            if c.get("timer_start"):
                self.flow.run(c, "timer")
        self.store.clear_reports()
        self.store.set_setting("shift", {"operator": self.actor, "ended": stamp()})
        self.imports = PersistentImports(self)
        self.refresh()

    def queue(self):
        self.heading(
            "Work queue",
            "One next action per inquiry. Overdue follow-ups come first, then due soon, then original received time.",
        )
        with ui.row().classes("w-full items-center"):
            button("New inquiry", self.new_inquiry, True, "coord-new")
        cases = self.store.cases()
        search = field("Search guest or reference")
        show = select("Show", ["Needs action", "All inquiries"], "Needs action")
        rows = ui.column().classes("w-full")

        def draw():
            rows.clear()
            with rows:
                matching = [
                    c
                    for c in cases
                    if search.value.lower()
                    in (
                        c["guest"]
                        + " "
                        + c["id"]
                        + " "
                        + str((c["external"] or {}).get("reference", ""))
                    ).lower()
                    and (
                        show.value == "All inquiries"
                        or next_action(c, self.p) not in ("Complete", "Closed")
                    )
                ]
                if not matching:
                    ui.label(
                        "No inquiries in this view. Add an inquiry or change the filter."
                    ).classes("panel muted")
                for c in sorted(matching, key=priority):
                    with ui.row().classes("panel items-center justify-between"):
                        with ui.column().classes("grow gap-1"):
                            ui.label(c["guest"]).classes("guest-name")
                            ui.label(next_action(c, self.p)).classes("next-title")
                            ui.label(
                                f"{c['owner']} · received {c['received_at']} · {c['source']}"
                            ).classes("muted")
                            band = priority(c)[0]
                            if band < 2:
                                ui.label(
                                    "Overdue task / hold"
                                    if band == 0
                                    else "Deadline within 6 hours"
                                ).classes("badge amber")
                        button(
                            "Open", lambda cid=c["id"]: self.go("Request", cid), True
                        )

        search.on_value_change(draw)
        show.on_value_change(draw)
        draw()

    def new_inquiry(self):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("New inquiry").classes("section-title")
            guest = field("Guest name / label")
            email = field("Email")
            phone = field("Phone")
            source = select("Source", ["Email", "Phone", "Paper", "Internal"], "Email")
            received = field("Originally received (ISO with offset)", stamp())
            message = field("Original inquiry", multiline=True)

            def create():
                c = self.flow.create(
                    guest.value,
                    email.value,
                    phone.value,
                    source.value,
                    received.value,
                    message.value,
                )
                dialog.close()
                self.go("Request", c["id"])

            button("Create inquiry", lambda: self.safe(create), True, "coord-create")
            button("Cancel", dialog.close)
        dialog.open()

    def inquiry(self):
        try:
            c = self.store.get(self.case_id)
        except ValueError:
            self.case_id = ""
            self.queue()
            return
        with ui.row().classes("w-full items-center justify-between"):
            self.heading(c["guest"], c["id"] + " · owner " + c["owner"])
            button("Back to queue", lambda: self.go("Queue"))
        with ui.column().classes("next-action items-start gap-2"):
            ui.label(next_action(c, self.p)).classes("next-title")
            ui.label(
                f"Guest acceptance: {'current' if accepted(c) else 'needed'} · External booking: {'verified' if external_current(c, self.p) else 'needs review'}"
            ).classes("muted")
        with ui.row().classes("coord-nav"):
            for view in ("Request", "Plan", "Communicate"):
                button(view, lambda v=view: self.go(v)).classes(
                    "selected" if self.view == view else ""
                )
        {"Request": self.request, "Plan": self.plan, "Communicate": self.communicate}[
            self.view
        ](c)
        self.tasks(c)

    def request(self, c):
        with ui.element("div").classes("coord-grid"):
            with ui.column().classes("panel"):
                ui.label("Conversation & calls").classes("section-title")
                for m in c["messages"]:
                    ui.label(
                        f"{m['source']} · {m['at']}"
                        + (" · acknowledgement only" if m["ack"] else "")
                    ).classes("message-meta")
                    ui.label(m["text"]).classes("message")
                for call in c["calls"]:
                    ui.label(f"{call['outcome']} · {call['at']}").classes(
                        "message-meta"
                    )
                    ui.label(call["summary"]).classes("message")
                with ui.expansion("Add a guest message").classes("w-full"):
                    msg = field("New message", multiline=True)
                    source = select(
                        "Message source",
                        ["Email", "Phone", "Paper", "Internal"],
                        "Email",
                    )
                    ack = ui.checkbox(
                        "Acknowledgement only; no request, terms or detail changed"
                    )
                    button(
                        "Record message",
                        lambda: self.act(
                            c,
                            "message",
                            text=msg.value,
                            source=source.value,
                            ack=ack.value,
                        ),
                    )
                if c["unreviewed"]:
                    note = field("Review resolution", multiline=True)
                    button(
                        "Mark changes reviewed",
                        lambda: self.act(c, "resolve", note=note.value),
                        True,
                    )
                with ui.expansion("Record a call").classes("w-full"):
                    local = (
                        now().astimezone(ZoneInfo(self.p["timezone"])).strftime("%H:%M")
                    )
                    ui.label(
                        "Within calling hours"
                        if self.p["call_start"] <= local < self.p["call_cutoff"]
                        else "Outside configured calling hours. Schedule a callback; this form only records an action already taken."
                    ).classes("notice")
                    outcome = select(
                        "Call outcome",
                        [
                            "Reached guest",
                            "No answer",
                            "Voicemail",
                            "Callback requested",
                            "Incorrect number",
                        ],
                        "Reached guest",
                    )
                    summary = field("Call summary / exact guest words", multiline=True)
                    button(
                        "Save call",
                        lambda: self.act(
                            c, "call", outcome=outcome.value, summary=summary.value
                        ),
                    )
                self.guest_context(c)
                with ui.expansion("Evidence-backed extraction assistance").classes(
                    "w-full"
                ):
                    ui.label(
                        "Offline pattern rules, not an LLM. Suggestions never replace confirmed facts. The separate synthetic demo retains the optional live-model integration."
                    ).classes("muted")
                    button(
                        "Extract suggestions locally", lambda: self.act(c, "interpret")
                    )
                    interpretation = c.get("interpretation", {})
                    for fact in interpretation.get("facts", []):
                        ui.label(
                            f"{fact['field']}: {fact['value']} · {fact['status']}"
                        ).classes("font-semibold")
                        ui.label("Source: " + fact["quote"]).classes("message")
                    for warning in interpretation.get(
                        "ambiguities", []
                    ) + interpretation.get("uninterpreted", []):
                        ui.label(str(warning)).classes("muted")
            with ui.column().classes("panel"):
                ui.label("Visit details").classes("section-title")
                ui.label(
                    "Unknown is different from none. Historical notes require confirmation for this visit."
                ).classes("muted")
                email = field("Guest email", c["email"])
                phone = field("Guest phone", c["phone"])
                owner = field("Owner", c["owner"])
                picks = {}
                for k in DETAILS:
                    v = c["details"][k]
                    with ui.expansion(k.title() + " · " + v["state"]).classes("w-full"):
                        value = field(k.title() + " value", v["value"])
                        state = select(k.title() + " state", list(STATES), v["state"])
                        evidence = field(k.title() + " evidence", v["evidence"], True)
                        picks[k] = (value, state, evidence)
                promises = field("Promises made to the guest", c["promises"], True)
                button(
                    "Save visit details",
                    lambda: self.act(
                        c,
                        "details",
                        email=email.value,
                        phone=phone.value,
                        owner=owner.value,
                        promises=promises.value,
                        details={
                            k: {"value": a.value, "state": b.value, "evidence": e.value}
                            for k, (a, b, e) in picks.items()
                        },
                    ),
                    True,
                )

    def guest_context(self, c):
        with ui.expansion("Imported guest context · reference only").classes("w-full"):
            for value in self.store.reports().values():
                candidates = guest_candidates(
                    restore(value), email=c["email"], phone=c["phone"]
                )
                for row in candidates[:5]:
                    ui.label(row.get("_name", "Matched contact")).classes(
                        "font-semibold"
                    )
                    for key in (
                        "visit_notes",
                        "guest_request",
                        "guestbook_notes",
                        "venue_notes",
                        "tags",
                    ):
                        if row.get(key):
                            ui.label(
                                key.replace("_", " ").title() + ": " + str(row[key])
                            ).classes("message")
            ui.label(
                "Exact-contact candidates are not identity proof. Never copy historical allergies or preferences into confirmed visit details without review."
            ).classes("muted")

    def plan(self, c):
        q = c["plan"]
        with ui.element("div").classes("coord-grid"):
            with ui.column().classes("panel"):
                ui.label("Requested arrangement").classes("section-title")
                if c["external"]:
                    e = c["external"]
                    saved = e["plan"]
                    ui.label(
                        f"Saved externally: {e['status']} · {e['reference']} · {saved.get('date', '')} {saved.get('time', '')} · tables {', '.join(saved.get('tables', []))}"
                    ).classes("notice info")
                    if saved != q:
                        ui.label(
                            "Requested changes have not replaced the saved external arrangement."
                        ).classes("notice")
                date = field("Visit date", q.get("date", ""))
                date.props("type=date")
                time = field("Visit time", q.get("time", ""))
                time.props("type=time")
                party = (
                    ui.number("Party size", value=q.get("party"), min=1, precision=0)
                    .props("outlined")
                    .classes("w-full")
                )
                duration = (
                    ui.number(
                        "Duration in minutes",
                        value=q.get("duration", self.p["duration_minutes"]),
                        min=1,
                        precision=0,
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                tables = select(
                    "Tables",
                    [t["id"] for t in self.p["tables"]],
                    q.get("tables", []),
                    True,
                )
                arrangement = field(
                    "Guest-facing seating explanation", q.get("arrangement", ""), True
                )
                photos = {
                    "": "No photo selected",
                    **{p["id"]: p["caption"] for p in self.store.photos()},
                }
                photo = select("Approved seating photo", photos, q.get("photo_id", ""))
                exception = field(
                    "Photo exception and reason", q.get("photo_exception", "")
                )
                with ui.expansion("Minimum spend / agreed exception").classes("w-full"):
                    ui.label(
                        "Thresholds come from current reviewed Settings, not the historical manual."
                    ).classes("muted")
                    amount = (
                        ui.number("Minimum spend", value=q.get("amount"), min=0)
                        .props("outlined")
                        .classes("w-full")
                    )
                    currency = field("Currency", q.get("currency", "CAD"))
                    basis = select(
                        "Spend basis", ["Total", "Per person"], q.get("basis", "Total")
                    )
                    includes = field(
                        "Inclusions / exclusions", q.get("includes", ""), True
                    )
                    waiver = field("Requested waiver", q.get("waiver", ""), True)
                button(
                    "Save arrangement",
                    lambda: self.act(
                        c,
                        "plan",
                        plan={
                            "date": date.value,
                            "time": time.value,
                            "party": party.value,
                            "duration": duration.value,
                            "tables": tables.value,
                            "arrangement": arrangement.value,
                            "photo_id": photo.value,
                            "photo_exception": exception.value,
                            "amount": amount.value,
                            "currency": currency.value,
                            "basis": basis.value,
                            "includes": includes.value,
                            "waiver": waiver.value,
                        },
                    ),
                    True,
                )
            with ui.column().classes("gap-4 w-full"):
                with ui.column().classes("panel"):
                    a = assess(
                        c,
                        self.p,
                        self.store.reports().get("reservations"),
                        self.store.cases(),
                    )
                    ui.label("Snapshot check · " + a["status"]).classes("section-title")
                    ui.label(a["reason"]).classes("muted")
                    for option in a["options"]:
                        ui.label(
                            "Possible: "
                            + ", ".join(option["tables"])
                            + f" · {option['capacity']} seats"
                        ).classes("badge")
                    result = select(
                        "Manual availability result",
                        ["Available externally", "Unavailable", "Cannot assess"],
                        "Available externally",
                    )
                    evidence = field(
                        "Availability evidence / flow considerations", multiline=True
                    )
                    button(
                        "Record external availability check",
                        lambda: self.act(
                            c,
                            "availability",
                            result=result.value,
                            evidence=evidence.value,
                        ),
                        True,
                    )
                    with ui.expansion("Manager approval").classes("w-full"):
                        approver = field("Approver")
                        note = field("Approval evidence", multiline=True)
                        button(
                            "Record approval",
                            lambda: self.act(
                                c, "approval", approver=approver.value, note=note.value
                            ),
                        )
                with ui.expansion("Verify saved OpenTable booking").classes("panel"):
                    ui.label(
                        "Perform the action in OpenTable first. This form only records your verification."
                    ).classes("notice")
                    reference = field(
                        "External reservation reference",
                        (c["external"] or {}).get("reference", ""),
                    )
                    status = select(
                        "Verified external status",
                        ["Held", "Confirmed", "Cancelled", "Released"],
                        "Confirmed",
                    )
                    hold = field(
                        "Hold deadline (ISO with offset)", c.get("hold_until", "")
                    )
                    checks = {k: ui.checkbox(k) for k in CHECKS}
                    note = field("External verification evidence", multiline=True)
                    button(
                        "Record external verification",
                        lambda: self.act(
                            c,
                            "external",
                            reference=reference.value,
                            status=status.value,
                            hold_until=hold.value,
                            checks=[k for k, v in checks.items() if v.value],
                            note=note.value,
                        ),
                        True,
                    )
                with ui.expansion("Record guest acceptance").classes("panel"):
                    sources = {
                        m["id"]: m["source"] + " · " + m["text"][:65]
                        for m in c["messages"]
                        if m["source"] in ("Email", "Phone")
                    }
                    sources.update(
                        {
                            v["id"]: "Call · " + v["summary"][:65]
                            for v in c["calls"]
                            if v["outcome"] == "Reached guest"
                        }
                    )
                    source = select("Acceptance source", sources)
                    quote = field("Exact acceptance quote", multiline=True)
                    checked = ui.checkbox(
                        "This evidence accepts the current date, tables, duration and terms."
                    )

                    def accept():
                        if not checked.value:
                            return self.error(
                                "Confirm that the quote accepts the current arrangement."
                            )
                        self.act(c, "accept", source_id=source.value, quote=quote.value)

                    button("Record acceptance", accept, True)
                with ui.expansion("Alternative outcome / referral").classes("panel"):
                    value = select(
                        "Outcome",
                        ["Book", "Decline", "Refer", "Cancel", "Release"],
                        c["disposition"],
                    )
                    reason = field("Outcome reason", c["disposition_reason"], True)
                    button(
                        "Save outcome",
                        lambda: self.act(
                            c, "disposition", value=value.value, reason=reason.value
                        ),
                    )
                    recipient = field("Referral recipient")
                    refnote = field("Referral handoff evidence", multiline=True)
                    button(
                        "Record referral handoff",
                        lambda: self.act(
                            c, "referral", recipient=recipient.value, note=refnote.value
                        ),
                    )
                with ui.expansion("Copyable external booking notes").classes("panel"):
                    ui.label(booking_package(c)).classes("message")
                    button(
                        "Copy booking notes",
                        lambda: ui.clipboard.write(booking_package(c)),
                    )

    def communicate(self, c):
        d = c["draft"] or {}
        with ui.element("div").classes("coord-grid"):
            with ui.column().classes("panel"):
                ui.label("Prepare a response").classes("section-title")
                buffer_key = c["id"] + ":" + self.buffer_id
                saved_purpose = self.store.buffer(buffer_key + ":purpose")
                purpose = select(
                    "Response purpose",
                    list(PURPOSES),
                    saved_purpose["text"]
                    if saved_purpose
                    else d.get("purpose", "Clarification"),
                )
                purpose.on_value_change(
                    lambda e: self.store.buffer(
                        buffer_key + ":purpose", c["revision"], e.value
                    )
                )
                recovered = self.store.buffer(buffer_key)
                value = recovered["text"] if recovered else d.get("text", "")
                if (
                    recovered
                    and recovered["revision"] != c["revision"]
                    and recovered["text"] != d.get("text")
                ):
                    ui.label(
                        "Recovered working text may predate changes to this inquiry. Review it before saving."
                    ).classes("notice")
                text = field("Response text", value, True)
                text.props("autogrow")
                text.on_value_change(
                    lambda e: self.store.buffer(buffer_key, c["revision"], e.value)
                )

                def generate():
                    text.value = compose(c, self.p, purpose.value)

                button("Generate response", lambda: self.safe(generate))
                button(
                    "Save response",
                    lambda: self.act(
                        c, "draft", purpose=purpose.value, text=text.value
                    ),
                    True,
                )
                ui.label(
                    "Working text is saved locally for this browser URL. Save response before reviewing or copying."
                ).classes("muted")
                if d:
                    with ui.expansion("Saved response · " + d["purpose"]).classes(
                        "w-full"
                    ):
                        ui.label(d["text"]).classes("message")
                    current = d["source_hash"] == draft_hash(c, self.p)
                    reviewed = current and d.get("reviewed_hash") == digest(d["text"])
                    ui.label(
                        "Saved response is stale; save updated text before review."
                        if not current
                        else "Saved text reviewed"
                        if reviewed
                        else "Saved text needs review"
                    ).classes("badge amber" if not reviewed else "badge green")
                    button(
                        "Mark saved response reviewed",
                        lambda: self.act(c, "review"),
                        True,
                    ).set_enabled(current and not reviewed)

                    async def copy():
                        try:
                            latest = self.store.get(c["id"])
                            p = self.store.setting("profile", profile())
                            saved = latest["draft"]
                            if (
                                latest["revision"] != c["revision"]
                                or not saved
                                or saved.get("reviewed_hash") != digest(saved["text"])
                                or saved["source_hash"] != draft_hash(latest, p)
                            ):
                                raise ValueError(
                                    "Refresh, save and review the current response before copying."
                                )
                            validate_purpose(latest, p, saved["purpose"])
                            ok = await ui.run_javascript(
                                "navigator.clipboard.writeText("
                                + json.dumps(saved["text"])
                                + ").then(()=>true).catch(()=>false)"
                            )
                            if not ok:
                                raise ValueError(
                                    "Clipboard access was blocked. Select the reviewed text and copy it manually."
                                )
                            ui.notify(
                                "Reviewed response copied",
                                type="positive",
                                position="top-right",
                                timeout=1000,
                                group=False,
                            )
                        except ValueError as exc:
                            self.error(exc)

                    button("Copy reviewed response", copy).set_enabled(reviewed)
                    attachment = ui.checkbox(
                        "I attached the selected seating photo in the external email."
                    )
                    attachment.set_visibility(bool(c["plan"].get("photo_id")))
                    if c["plan"].get("photo_id"):
                        photo = self.store.photo(c["plan"]["photo_id"])
                        if photo:
                            ui.label(photo["caption"]).classes("muted")
                            button(
                                "Download seating photo",
                                lambda: ui.download.content(
                                    photo["data"],
                                    filename=photo["name"],
                                    media_type=photo["mime"],
                                ),
                            )
                    button(
                        "Report sent externally",
                        lambda: self.act(
                            c, "sent", attachment_checked=attachment.value
                        ),
                        True,
                    ).set_enabled(reviewed and not d.get("sent_at"))
                    if d.get("sent_at"):
                        ui.label("Reported sent: " + d["sent_at"]).classes(
                            "badge green"
                        )
            with ui.column().classes("panel"):
                ui.label("Before final confirmation").classes("section-title")
                gaps = final_gaps(c, self.p)
                for gap in gaps:
                    ui.label("• " + gap).classes("muted")
                if not gaps:
                    ui.label("Ready for a reviewed final confirmation.").classes(
                        "badge green"
                    )
                ui.label(
                    "Nothing is sent by this app. Copy into your email client, verify recipient and attachments, then report the action here."
                ).classes("notice info")

    def tasks(self, c):
        with ui.expansion(
            "Follow-ups and activity",
            value=any(not t.get("done_at") for t in c["tasks"]),
        ).classes("panel"):
            for task in c["tasks"]:
                ui.label(
                    task["title"]
                    + (
                        " · complete"
                        if task.get("done_at")
                        else " · due " + task["due"]
                    )
                ).classes("font-semibold")
                ui.label(
                    f"Owner: {task['owner']} · waiting on: {task.get('waiting_on', '')}"
                ).classes("muted")
                if not task.get("done_at"):
                    note = field("Completion note · " + task["title"])
                    button(
                        "Complete task",
                        lambda t=task, n=note: self.act(
                            c, "task_done", id=t["id"], note=n.value
                        ),
                    )
            with ui.expansion("Add a follow-up").classes("w-full"):
                title = field("Task title")
                owner = field("Task owner", c["owner"])
                waiting = field("Waiting on")
                due = field(
                    "Due (ISO with offset)", (now() + timedelta(days=1)).isoformat()
                )
                button(
                    "Add task",
                    lambda: self.act(
                        c,
                        "task",
                        title=title.value,
                        owner=owner.value,
                        waiting_on=waiting.value,
                        due=due.value,
                    ),
                )
            button(
                "Stop handling timer"
                if c.get("timer_start")
                else "Start handling timer",
                lambda: self.act(c, "timer"),
            )
            ui.label(
                "Timer records elapsed time between your clicks, including interruptions; it is not a validated productivity measurement."
            ).classes("muted")
            if next_action(c, self.p) == "Complete":
                reason = field("Closure note")
                button(
                    "Close inquiry", lambda: self.act(c, "close", reason=reason.value)
                )
            with ui.expansion("Audit history").classes("w-full"):
                for event in self.store.events(c["id"]):
                    ui.label(
                        f"{event['at']} · {event['actor']} · {event['kind']}"
                    ).classes("muted")
            if c.get("closed_reason"):
                with ui.expansion("Remove closed local record").classes("w-full"):
                    ui.label(
                        "Removes this inquiry, its audit history and saved draft buffers from this local workspace. It does not cancel the booking or remove source reports, photos, backups or email. No in-app undo; not forensic secure erasure."
                    ).classes("notice")
                    confirmation = field("Type inquiry ID to remove")

                    def remove():
                        if confirmation.value != c["id"]:
                            raise ValueError("Type the exact inquiry ID.")
                        self.store.delete_closed(c["id"], c["revision"])
                        self.case_id = ""
                        self.go("Queue")
                        ui.notify(
                            "Closed local inquiry and its history removed. No in-app undo.",
                            type="warning",
                        )

                    button(
                        "Remove local inquiry permanently", lambda: self.safe(remove)
                    )

    def settings(self):
        self.heading(
            "Restaurant settings",
            "Use current, reviewed rules. The historical JOEY document is not a current policy source.",
        )
        p = self.p
        with ui.column().classes("panel"):
            name = field("Restaurant name", p["name"])
            tz = field("Restaurant time zone (IANA)", p["timezone"])
            start = field("Calling starts", p["call_start"])
            cutoff = field("Calling cutoff", p["call_cutoff"])
            ui.label(
                "09:00–21:00 is an editable starting value, not an asserted current restaurant policy."
            ).classes("muted")
            numbers = {}
            for key, title in [
                ("duration_minutes", "Estimated occupancy minutes"),
                ("buffer_minutes", "Turnover buffer minutes"),
                ("min_spend_threshold", "Minimum-spend party threshold"),
                ("manager_threshold", "Manager-approval party threshold"),
            ]:
                numbers[key] = (
                    ui.number(title, value=p[key], min=0, precision=0)
                    .props("outlined")
                    .classes("w-full")
                )
            reviewer = field("Current policy reviewed by", p["verified_by"])

            def save():
                new = deepcopy(p)
                new.update(
                    name=name.value,
                    timezone=tz.value,
                    call_start=start.value,
                    call_cutoff=cutoff.value,
                    verified_by=reviewer.value.strip(),
                    **{k: v.value for k, v in numbers.items()},
                )
                save_profile(self.store, new, p["version"])
                self.refresh()

            button("Save current policy", lambda: self.safe(save), True)
        with ui.column().classes("panel"):
            ui.label("Actual tables and allowed groupings").classes("section-title")
            for table in p["tables"]:
                ui.label(
                    f"{table['id']} · {table['capacity']} seats · {table['area']} · {table['style']} · {'step-free' if table['step_free'] else 'accessibility unverified'}"
                )
            with ui.expansion("Add or update a table").classes("w-full"):
                tid = field("Table ID")
                cap = (
                    ui.number("Table capacity", min=1, precision=0)
                    .props("outlined")
                    .classes("w-full")
                )
                area = field("Area")
                style = select("Style", ["Table", "Booth", "Other"], "Table")
                access = ui.checkbox("Verified step-free access")

                def add():
                    new = deepcopy(p)
                    new["tables"] = [
                        t for t in new["tables"] if t["id"] != tid.value.strip()
                    ] + [
                        {
                            "id": tid.value.strip(),
                            "capacity": cap.value,
                            "area": area.value,
                            "style": style.value,
                            "step_free": access.value,
                        }
                    ]
                    new["verified_by"] = ""
                    save_profile(self.store, new, p["version"])
                    self.refresh()

                button("Save table", lambda: self.safe(add))
            for group in p["groupings"]:
                ui.label(
                    ", ".join(group["tables"])
                    + f" · {group['capacity']} combined seats · {group['description']}"
                )
            with ui.expansion("Add allowed grouping").classes("w-full"):
                tables = select(
                    "Grouped tables", [t["id"] for t in p["tables"]], [], True
                )
                capacity = (
                    ui.number("Combined capacity", min=1, precision=0)
                    .props("outlined")
                    .classes("w-full")
                )
                description = field("Grouping explanation")

                def group():
                    new = deepcopy(p)
                    new["verified_by"] = ""
                    new["groupings"].append(
                        {
                            "tables": tables.value,
                            "capacity": capacity.value,
                            "description": description.value,
                        }
                    )
                    save_profile(self.store, new, p["version"])
                    self.refresh()

                button("Save grouping", lambda: self.safe(group))
            ui.label(
                "Layout changes clear the policy review. Reconfirm current settings after editing tables."
            ).classes("notice")
        with ui.column().classes("panel"):
            ui.label("Approved seating photographs").classes("section-title")
            ui.label(
                "Upload only authorized, current photographs. No invented restaurant images are supplied."
            ).classes("muted")
            caption = field("Approved photo caption")

            async def upload(e):
                try:
                    self.store.add_photo(
                        e.file.name, caption.value, await e.file.read()
                    )
                    self.refresh()
                except ValueError as exc:
                    self.error(exc)

            ui.upload(
                label="Upload approved photo",
                auto_upload=True,
                on_upload=upload,
                max_file_size=3_000_000,
            ).props("accept=.png,.jpg,.jpeg").classes("w-full")
            for photo in self.store.photos():
                ui.label(photo["caption"] + " · " + photo["name"]).classes("muted")

    def service(self):
        self.heading(
            "Service handoff",
            "The saved external allocation is shown even when a guest has requested a change.",
        )
        visit = field(
            "Service date",
            now().astimezone(ZoneInfo(self.p["timezone"])).date().isoformat(),
        )
        visit.props("type=date")
        content = ui.column().classes("w-full")

        def draw():
            content.clear()
            records = []
            with content:
                for c in self.store.cases():
                    record = service_record(c, self.p)
                    if record["saved_arrangement"].get("date") != visit.value or record[
                        "status"
                    ] not in ("Held", "Confirmed"):
                        continue
                    records.append(record)
                    with ui.column().classes("panel"):
                        q = record["saved_arrangement"]
                        ui.label(
                            f"{c['guest']} · {q['time']} · {q['party']} guests · tables {', '.join(q['tables'])}"
                        ).classes("section-title")
                        ui.label(
                            f"{record['status']} · {record['external_reference']} · {q['duration']} minutes · owner {c['owner']}"
                        ).classes("muted")
                        ui.label(q["arrangement"]).classes("message")
                        if record["pending_change"]:
                            ui.label(
                                "Pending change: requested arrangement differs from the saved external booking."
                            ).classes("notice")
                        for k, v in c["details"].items():
                            ui.label(
                                f"{k.title()}: {v['value'] or 'Unknown'} · {v['state']}"
                            ).classes("muted")
                        ui.label(
                            "Promises: " + (c["promises"] or "None recorded")
                        ).classes("message")
                        ui.label("Next: " + record["next_action"]).classes("muted")
                        if c["handoff"]:
                            changed = [
                                k
                                for k, v in record.items()
                                if c["handoff"]["snapshot"].get(k) != v
                            ]
                            ui.label(
                                "Changed since staff review: " + ", ".join(changed)
                                if changed
                                else "Staff review is current."
                            ).classes("notice" if changed else "badge green")
                        recipient = field("Handoff reviewed by")
                        button(
                            "Record staff review",
                            lambda c=c, r=recipient: self.act(
                                c, "handoff", recipient=r.value
                            ),
                        )
                        button(
                            "Open inquiry", lambda cid=c["id"]: self.go("Request", cid)
                        )
                if not records:
                    ui.label("No verified external allocations for this date.").classes(
                        "muted"
                    )
                button(
                    "Export service handoff CSV",
                    lambda: self.download_csv("service-handoff.csv", records),
                )

        visit.on_value_change(draw)
        draw()

    def download_csv(self, name, rows):
        if not rows:
            return self.error("No rows to export.")
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            safe = {}
            for key, value in row.items():
                text = (
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (list, dict))
                    else str(value)
                )
                safe[key] = (
                    "'" + text
                    if text.lstrip().startswith(("=", "+", "-", "@"))
                    else text
                )
            writer.writerow(safe)
        ui.download.content(out.getvalue(), filename=name, media_type="text/csv")

    def evidence(self):
        self.heading(
            "Evidence, not assumptions",
            "Automated verification and observed operator measurements answer different questions.",
        )
        rows = [
            dict(case=c["id"], **sample)
            for c in self.store.cases()
            for sample in c["handling_samples"]
        ]
        with ui.column().classes("panel"):
            ui.label(f"{len(rows)} locally recorded handling intervals").classes(
                "section-title"
            )
            ui.label(
                "These self-timed intervals are not a controlled study and include pauses. No measured time-saving claim is made."
            ).classes("muted")
            button(
                "Export handling intervals",
                lambda: self.download_csv("handling-intervals.csv", rows),
            )
            ui.label(
                "Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025. The original workflow used LLM chat tools and manual booking operations. Software test dates reflect actual runs."
            ).classes("message")
