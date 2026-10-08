"""Browser-page-scoped OpenTable setup and read-only workflow context."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from nicegui import ui
from ..services.opentable_import import (
    FIELDS,
    read_report,
    suggest_mapping,
    validate_report,
    guest_candidates,
)


class SessionImports:
    def __init__(self, desk):
        self.desk = desk
        self.ready = False
        self.snapshots = {}
        self.pending = None
        self.preview = None
        self.mapping = {}
        self.error = ""
        self.venue = ""

    def finish_demo(self):
        self.ready = True
        self.desk.view = "Inquiries"
        self.desk.refresh()

    def page(self):
        d = self.desk
        d.heading(
            "Prepare your session",
            "Start with a fresh reservations export. Add a guestbook only if you need more guest context.",
        )
        with ui.column().classes("panel w-full"):
            ui.label("1 · Upload and review").classes("section-title")
            ui.label(
                "CSV or TSV · 5 MB maximum · one restaurant. Reports are held in server memory for this page, not saved to the project database. A new page or reload starts without them. Nothing is sent to an AI provider or synced to OpenTable."
            ).classes("muted")
            ui.label(
                "Exports may contain guestbook notes and tags already. Dashboard headings vary, so every mapping needs your review."
            ).classes("muted")

            async def uploaded(e):
                try:
                    self.pending = read_report(await e.file.read(), e.file.name)
                    self.mapping = suggest_mapping(self.pending)
                    self.preview = None
                    self.error = ""
                except ValueError as exc:
                    self.pending = self.preview = None
                    self.error = str(exc)
                d.refresh()

            uploader = ui.upload(
                label="Upload OpenTable CSV or TSV",
                auto_upload=True,
                on_upload=uploaded,
                max_file_size=5_000_000,
                on_rejected=lambda: ui.notify(
                    "Choose CSV or TSV, no larger than 5 MB.", type="warning"
                ),
            ).props("accept=.csv,.tsv data-testid=ot-upload").classes("w-full max-w-xl")
            ui.button("Choose export file", icon="upload_file", on_click=lambda: uploader.run_method("pickFiles")).props("no-caps unelevated data-testid=ot-choose")
            if self.error:
                ui.label(self.error).classes("notice whitespace-pre-wrap").props(
                    "role=alert"
                )
        if self.pending:
            self.mapping_form()
        if self.snapshots:
            with ui.column().classes("panel w-full"):
                ui.label("2 · Ready for review").classes("section-title")
                ui.label(self.venue).classes("font-semibold")
                for kind, snapshot in self.snapshots.items():
                    ui.label(
                        f"{kind.title()}: {snapshot.report.filename} · {len(snapshot.rows)} rows"
                    ).classes("font-semibold")
                    ui.label(
                        f"Coverage declared: {snapshot.coverage_start} to {snapshot.coverage_end} · {snapshot.timezone}"
                    ).classes("muted")
                    for warning in snapshot.warnings_now():
                        ui.label(warning).classes("text-sm text-amber-800")
                with ui.expansion("Browse imported reservations").classes("w-full"):
                    reservations = self.snapshots.get("reservations")
                    if reservations:
                        self.reservation_table(reservations.rows)
                ui.label(
                    "The seating engine and booking actions remain a synthetic simulation. Imported rows are read-only reference evidence, not seats in that model. Verify availability and perform all real changes in OpenTable."
                ).classes("notice")
                ui.button("Open workbench", on_click=self.finish_demo).props(
                    "no-caps unelevated data-testid=ot-continue"
                ).set_enabled("reservations" in self.snapshots)
                ui.button("Clear session exports", on_click=self.clear).props(
                    "flat no-caps"
                )
        with ui.row().classes("items-center"):
            ui.button("Use synthetic demo without exports", on_click=self.demo).props(
                "flat no-caps data-testid=ot-demo"
            )
            ui.label("A new page or reload asks for fresh exports again.").classes(
                "muted small"
            )

    def demo(self):
        self.snapshots.clear()
        self.pending = self.preview = None
        self.finish_demo()

    def clear(self):
        self.snapshots.clear()
        self.pending = self.preview = None
        self.ready = False
        self.error = ""
        self.desk.refresh()

    def mapping_form(self):
        report = self.pending
        with ui.column().classes("panel w-full"):
            ui.label(
                f"Review columns · {report.filename} · {len(report.rows)} rows"
            ).classes("section-title")
            ui.label(
                "Suggestions are convenience matches, not verified OpenTable headers. Unmapped fields are not used. Notes remain verbatim; blank and absent columns remain distinct."
            ).classes("muted")
            kind = ui.select(
                {"reservations": "Reservations report", "guests": "Optional guestbook"},
                value="reservations",
                label="Report type",
            ).props("outlined")
            ui.label(
                "Reservations require party size plus a visit timestamp, or separate date and time columns. When both are mapped, the timestamp takes precedence. Guestbooks require a guest ID, email or phone."
            ).classes("muted")
            picks = {}
            for title, fields in [
                (
                    "Visit and guest columns",
                    [
                        "date",
                        "time",
                        "party_size",
                        "status",
                        "name",
                        "email",
                        "phone",
                        "tables",
                    ],
                ),
                (
                    "IDs, notes and additional columns",
                    [
                        f
                        for f in FIELDS
                        if f
                        not in {
                            "date",
                            "time",
                            "party_size",
                            "status",
                            "name",
                            "email",
                            "phone",
                            "tables",
                        }
                    ],
                ),
            ]:
                with ui.expansion(
                    title, value=title == "Visit and guest columns"
                ).classes("w-full"):
                    with ui.element("div").classes(
                        "grid grid-cols-1 md:grid-cols-2 gap-3 w-full"
                    ):
                        for field in fields:
                            picks[field] = (
                                ui.select(
                                    {
                                        "": "Not mapped",
                                        **{h: h for h in report.headers},
                                    },
                                    value=self.mapping.get(field, ""),
                                    label=FIELDS[field],
                                )
                                .props("outlined dense")
                                .classes("w-full")
                            )
            with ui.expansion("View first 5 source records").classes("w-full"):
                ui.table(
                    columns=[
                        {"name": h, "label": h, "field": h} for h in report.headers
                    ],
                    rows=list(report.rows[:5]),
                ).classes("w-full")
            ui.label("Report settings").classes("section-title")
            venue = (
                ui.input("Restaurant name", value=self.venue)
                .props("outlined")
                .classes("w-full")
            )
            tz = (
                ui.input(
                    "Restaurant time zone (IANA)",
                    value=self.desk.cfg.restaurant.timezone,
                )
                .props("outlined")
                .classes("w-full")
            )
            order = ui.select(
                {"MDY": "Month/day/year", "DMY": "Day/month/year"},
                value="MDY",
                label="Slash date format",
            ).props("outlined")
            ui.label(
                "ISO dates use YYYY-MM-DD. Slash dates use your selection; no locale guessing."
            ).classes("muted")
            exported = (
                ui.input(
                    "Export created at (ISO with offset)",
                    placeholder="2026-10-08T09:00:00-04:00",
                )
                .props("outlined")
                .classes("w-full")
            )
            with ui.row().classes("w-full"):
                start = ui.input("Report coverage start").props("type=date outlined").classes("w-full sm:flex-1")
                end = ui.input("Report coverage end").props("type=date outlined").classes("w-full sm:flex-1")
            checked = ui.checkbox(
                "I checked the mappings, restaurant, export time and report date range. I reviewed report filters; missing rows do not prove availability."
            )

            def preview():
                try:
                    if not checked.value or not venue.value.strip():
                        raise ValueError(
                            "Enter the restaurant name and confirm the report settings."
                        )
                    snapshot = validate_report(
                        report,
                        {k: v.value for k, v in picks.items()},
                        kind=kind.value,
                        date_order=order.value,
                        timezone_name=tz.value.strip(),
                        exported_at=datetime.fromisoformat(
                            exported.value.strip().replace("Z", "+00:00")
                        ),
                        coverage_start=date.fromisoformat(start.value),
                        coverage_end=date.fromisoformat(end.value),
                    )
                    if self.snapshots and self.venue != venue.value.strip():
                        raise ValueError(
                            "Restaurant name differs from the current session. Clear exports before switching restaurants."
                        )
                    other = self.snapshots.get(
                        "guests" if kind.value == "reservations" else "reservations"
                    )
                    if other:
                        a = {
                            r.get("restaurant_id")
                            for r in snapshot.rows
                            if r.get("restaurant_id")
                        }
                        b = {
                            r.get("restaurant_id")
                            for r in other.rows
                            if r.get("restaurant_id")
                        }
                        if a and b and a != b:
                            raise ValueError(
                                "Restaurant IDs differ between the two reports."
                            )
                        if snapshot.timezone != other.timezone:
                            raise ValueError(
                                "Use the same restaurant time zone for both reports."
                            )
                    self.preview = snapshot
                    self.mapping = dict(snapshot.mapping)
                    self.venue = venue.value.strip()
                    self.error = ""
                    self.preview_dialog(snapshot)
                except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
                    ui.notify(
                        str(exc) or "Enter valid report dates and settings.",
                        type="negative",
                        timeout=10000,
                        multi_line=True,
                    )

            ui.button("Validate report", on_click=preview).props(
                "no-caps unelevated data-testid=ot-validate"
            )

    def preview_dialog(self, snapshot):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("Review import").classes("section-title")
            ui.label(f"{len(snapshot.rows)} valid rows · no rows skipped")
            ui.label(f"SHA-256: {snapshot.report.digest[:16]}…").classes("muted")
            for warning in snapshot.warnings_now():
                ui.label(warning).classes("text-sm text-amber-800")
            ui.label(
                "Applying replaces the previous report of this type for this page. It never appends duplicates or changes bookings, facts, draft replies or guest records."
            ).classes("notice")

            def apply():
                self.snapshots[snapshot.kind] = snapshot
                self.pending = self.preview = None
                dialog.close()
                self.desk.refresh()

            with ui.row():
                ui.button("Back to mapping", on_click=dialog.close).props(
                    "flat no-caps"
                )
                ui.button("Use this report", on_click=apply).props(
                    "no-caps unelevated data-testid=ot-apply"
                )
        dialog.open()

    def banner(self):
        with ui.row().classes("notice w-full items-center"):
            if self.snapshots:
                snapshot = self.snapshots.get("reservations")
                text = f"{self.venue} · report loaded · read-only reference"
                if snapshot:
                    age = (
                        datetime.now(timezone.utc) - snapshot.exported_at
                    ).total_seconds() / 3600
                    text += f" · export age {age:.1f}h" + (
                        " · REFRESH RECOMMENDED" if age > 4 else ""
                    )
                ui.label(text).classes("grow")
            else:
                ui.label("Synthetic demo · no OpenTable exports loaded").classes("grow")
            ui.button(
                "Session exports",
                on_click=lambda: self.desk.navigate("Session exports"),
            ).props("flat no-caps")

    def context(self, v):
        snapshot = self.snapshots.get("reservations")
        if not snapshot:
            return
        with ui.expansion(
            "OpenTable report context", icon="table_view", value=True
        ).classes("panel w-full"):
            ui.label(
                "Read-only snapshot. Check current availability and all real booking changes in OpenTable."
            ).classes("notice")
            requested = v.facts.value("requested_date")
            if requested:
                day = date.fromisoformat(str(requested))
                if not snapshot.coverage_start <= day <= snapshot.coverage_end:
                    ui.label(
                        "OUTSIDE REPORT COVERAGE · upload an export covering this inquiry’s date."
                    ).classes("text-amber-800 font-semibold")
                else:
                    rows = [r for r in snapshot.rows if r["_start"].date() == day]
                    active = [r for r in rows if r["_active"]]
                    ui.label(
                        f"{day}: {len(active)} potentially active reservations · {sum(r['_party'] for r in active)} covers in this export"
                    ).classes("font-semibold")
                    ui.label(
                        "Counts are report totals, not simultaneous occupancy. Table capacity, duration and report completeness are not verified."
                    ).classes("muted")
                    self.reservation_table(rows)
            else:
                ui.label(
                    "Add a requested date to see that day’s exported reservations."
                ).classes("muted")
            for title, source in [
                ("Reservation contact matches", snapshot),
                ("Guestbook contact matches", self.snapshots.get("guests")),
            ]:
                if not source:
                    continue
                matches = guest_candidates(
                    source,
                    email=v.facts.value("contact_email") or "",
                    phone=v.facts.value("contact_phone") or "",
                )
                ui.label(f"{title}: {len(matches)} candidate records").classes(
                    "font-semibold mt-3"
                )
                if matches:
                    ui.label(
                        "Exact email or normalized phone match only. Verify identity, especially shared contacts. Notes are historical context; confirm allergies with the guest. Nothing is copied into facts or replies."
                    ).classes("muted")
                    for row in matches[:20]:
                        with ui.expansion(
                            f"{row['_name']} · source record {row['_record']}"
                        ).classes("w-full"):
                            for k in [
                                "guest_id",
                                "email",
                                "phone",
                                "guest_request",
                                "visit_notes",
                                "guestbook_notes",
                                "venue_notes",
                                "tags",
                            ]:
                                ui.label(
                                    f"{FIELDS[k]}: {row[k] if row.get(k) else '(blank)' if k in row else '(not exported/mapped)'}"
                                ).classes("whitespace-pre-wrap text-sm")
                            ui.label(
                                f"Source: {source.report.filename} · exported {source.exported_at.isoformat()}"
                            ).classes("muted small")
                    if len(matches) > 20:
                        ui.label(
                            "Showing first 20 candidates. Narrow the report and verify identity in OpenTable."
                        )
            for warning in snapshot.warnings_now():
                ui.label(warning).classes("text-sm text-amber-800")

    def reservation_table(self, rows):
        columns = [
            {"name": k, "label": title, "field": k, "align": "left"}
            for k, title in [
                ("time", "Visit"),
                ("guest", "Guest"),
                ("party", "Party"),
                ("status", "Source status"),
                ("tables", "Source tables"),
            ]
        ]
        ui.table(
            columns=columns,
            rows=[
                {
                    "time": r["_start"].strftime("%Y-%m-%d %H:%M %z"),
                    "guest": r["_name"],
                    "party": r["_party"],
                    "status": r.get("status") or "Unknown",
                    "tables": r.get("tables") or "Not provided",
                }
                for r in sorted(rows, key=lambda r: r["_start"])
            ],
            pagination=10,
        ).classes("w-full")
