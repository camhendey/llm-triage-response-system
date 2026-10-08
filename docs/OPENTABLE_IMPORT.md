# OpenTable imports

## Current version 3.0 coordinator

At `/`, reports persist in the separate coordinator database and survive reloads. A new shift asks for a fresh report or explicit manual-check exception. Raw snapshots clear at shift end or expire after 24 hours on next access; copied evidence persists separately. An observed restaurant ID remains pinned after clearing reports.

Every mapping still needs review, including remembered exact-header suggestions. Applying replaces the report type with stable-ID added/changed/absent summaries where possible. Absence never cancels a booking. Complete coverage must be attested for snapshot assistance. Freshness, reviewed actual layout, occupancy estimate, known overlapping statuses/tables and adequate coverage are required. `Potentially feasible` is not live availability; manual verification remains mandatory.

The historical behavior below applies to `/demo`. Read `COORDINATOR_WORKFLOW.md` and `OPERATOR_GUIDE.md` for the primary workspace.

## Historical version 2.1

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025. This feature is part of the later software implementation, not a claim of deployment at JOEY.

## What changed

Every new NiceGUI page and reload starts at **Prepare your session**. A reservations report supplies dated service context; an optional guestbook supplies historical guest context. The operator can explicitly choose the synthetic demo instead. **Session exports** remains accessible for replacing or clearing reports.

The evidence pack did not verify a genuine recent dashboard CSV with original headers. It documents available report categories and includes historical TSV headers and API structures with fake values. Therefore the importer uses reviewed column mapping instead of pretending those examples are the current dashboard schema. The unchanged evidence pack is under `docs/research/opentable/`.

## Operator workflow

1. Export reservations for the relevant restaurant and date range. Include guest contact details, status, guest requests, notes and tags where available. Review filters: a filtered report cannot establish that a restaurant is empty.
2. Upload UTF-8 CSV or TSV, at most 5 MB and 20,000 records. Comma, semicolon and tab delimiters, BOM, quoted commas and multiline notes are supported. Excel workbooks, PDFs and API JSON are not accepted. Convert a workbook to UTF-8 CSV first.
3. Review suggested column mappings. Reservations require party size and either an ISO timestamp or separate visit date and time. Timestamp takes precedence if both forms are mapped. IDs and table numbers are optional; they are never inferred from row position or guest name. Expand **IDs, notes and additional columns** to inspect all source mappings.
4. Enter restaurant name, IANA time zone, slash-date order, actual export creation time with UTC offset and declared report coverage. The app does not infer export freshness from file modification time. Confirm the settings and filter review checkbox.
5. Select **Validate report**. Invalid rows block the whole import, with record numbers and errors. No partial import silently drops occupancy. Review the preview, then select **Use this report**. Applying replaces the report of that type for this page; it never appends reservations.
6. Add a guestbook only if required context is missing from the reservations report. Choose **Optional guestbook** as report type. Review its settings separately. Restaurant identifiers, when present in both reports, must agree. Both must use the same time zone.
7. Open the workbench. Under an inquiry's **Plan**, review exported reservations for the requested date, potentially active reservation/cover totals, and candidate contact matches. Source filename, record number and declared export time remain available with notes.
8. Verify current seating, guest identity, allergies and any actual changes in OpenTable. Refresh the export whenever report age or service changes make it unreliable. The four-hour warning is a configurable-in-code prototype heuristic, not an OpenTable rule or a freshness guarantee.

## What the report can and cannot prove

| Topic | Implemented behavior |
|---|---|
| Service load | Date-scoped row and cover totals; original status and table text displayed. Totals are not simultaneous occupancy. |
| Status | Cancelled/canceled, no-show/no show, finished/done excluded from potentially active totals. Other unknown or blank statuses remain included and produce a warning. Source status is retained. |
| Coverage | Date range is declared by the operator. Out-of-range inquiry dates warn explicitly. Zero matching rows does not prove availability. |
| IDs | Duplicate reservation ID within a restaurant blocks import. Multi-restaurant reports block import. Missing IDs warn; identical-looking rows are not silently deduplicated. |
| Guest matching | Exact case-insensitive email or normalized complete phone digits produces candidates, including all shared-contact matches. No name matching or automatic merge. The service also supports restaurant-scoped guest-ID lookup; inquiry UI uses contacts because its fact model has no external guest-ID field. |
| Notes | Guest request, visit notes, guestbook notes, venue notes and tags remain separate verbatim strings. Empty mapped cells differ from unmapped columns. CSV cannot reliably distinguish database null from an empty string; text `null` is not silently converted. |
| Time | ISO timestamps preserve offsets and are converted to the selected venue zone. Local dates/times use the explicitly selected zone and date order. Ambiguous/nonexistent DST times require an offset-bearing timestamp. |
| Tables | Multiple table numbers remain source text. No conversion to synthetic table IDs or implied table capacity. |
| Availability | Imported rows do not feed the synthetic seating engine. A verified restaurant layout, table mapping, durations, status semantics and complete coverage are prerequisites for trustworthy occupancy integration. |
| Replies and facts | Imports never overwrite facts, automatically copy historical allergy notes, change drafts, call an LLM or perform external actions. |
| Reimport | One reservation snapshot and one guestbook snapshot per page. Replacing a snapshot is atomic after validation, without reservation creation or append duplicates. |

## Session and data handling

A session means one NiceGUI browser page, not a login or persistent shift record. A new page or reload requires setup again; other tabs do not inherit imports. Snapshots and uploaded rows are held by that page's server-side object and are not saved to SQLite, committed as fixtures, included in CSV-message imports, or sent to the optional live interpreter. Clear session exports removes the active page references. Framework/upload buffers can persist briefly until cleanup; this is not a secure-erasure guarantee. Restarting the app clears in-memory snapshots.

Only illustrative fixtures are packaged. The app binds to localhost by default and has no authentication or production access-control/retention system. Keep real exports outside the repository. Manually putting export content into an inquiry is a separate action governed by the configured interpreter. Do not publish screenshots of real guest data in a portfolio.

## Try it without guest data

Use `data/synthetic/opentable/reservations_ILLUSTRATIVE.csv`, then optionally `guests_ILLUSTRATIVE.csv`. These are invented test inputs, **not genuine OpenTable exports or verified schemas**. Set report coverage to 2026-11-13 through 2026-11-14 and enter an honest past timestamp for the demo upload. An inquiry for November 13 with `morgan@example.invalid` shows one potentially active reservation, six covers and two guestbook candidates sharing that email.

## Technical structure and portfolio claims

- `services/opentable_import.py`: bounded file parsing, explicit mapping, validation, immutable snapshot envelope, conservative status handling and candidate search. No database/provider dependency.
- `web/imports.py`: page-scoped upload, mapping, preview, replacement and inquiry context.
- `web/main.py`: session gate, navigation and Plan integration. Existing transaction and booking services are retained.
- No database schema migration or additional runtime dependency. CLI and optional legacy Streamlit UI do not gain this upload workflow.
- Tests cover malformed input, delimiter/quoting variants, explicit dates, DST, coverage, duplicate and multi-venue IDs, unknown statuses, shared contacts and mapping errors. Browser verification covers the actual upload journey and session isolation.

Defensible claim: **Built a schema-adaptive, human-reviewed export ingestion workflow that preserves source provenance and exposes uncertainty before reservation decisions.** Do not claim authenticated OpenTable integration, real dashboard compatibility certification, imported table-occupancy optimization, AI accuracy gains or measured time savings from this feature. The next validation milestone is testing anonymized genuine dashboard exports and collecting operator feedback, not adding more assumed schemas.
