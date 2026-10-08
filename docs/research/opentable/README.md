# OpenTable import evidence pack

This is a development/research pack, NOT a collection of recent genuine OpenTable restaurant dashboard CSV exports. As of 2026-10-07, an authentic recent full dashboard CSV with original headers was not verified in public sources.

## Files
- `reservation_2025_api_structure_FAKE_VALUES.json` and `guest_2025_api_structure_FAKE_VALUES.json`: field structures transcribed from publicly posted April 23, 2025 OpenTable Sync API examples. Personal data and identifying IDs are replaced with invented values. JSON field names, nesting, and null/array types are preserved. Not dashboard CSV exports.
- `guest_legacy_v7_DOCUMENTED_HEADER_RECONSTRUCTION.tsv`: header-only tab-separated schema derived from OpenTable v7 manual pp.224-227. Not a downloaded OpenTable file. Excludes `Guest Codes (1-20)`, since manual documentation does not clarify how its 20 codes appear as separate exported headers.
- `source_evidence_index.csv`: evidence/uncertainty matrix.

## Sources
- 2026 reservation report: https://support.opentable.com/s/article/Reservations-Report-in-GuestCenter
- Current guest export: https://support.opentable.com/s/article/Export-your-Guestbook
- 2025 API reservation example: https://gist.github.com/nickohara-klaviyo/15f966b7c082c8ddb8ba1cbee1a93670
- 2025 API guest example: https://gist.github.com/nickohara-klaviyo/b0b28777cdf0edfcba0a3e4cf092756f
- Historical OpenTable v7 manual: https://manualzilla.com/doc/5747345/chapter-1
- Current migration workflow: https://tock.zendesk.com/hc/en-us/articles/34628828437140-Data-Transfer-Instructions

## Important ingestion assertions to test
- In 2026, reservation reporting can be configured to include guestbook notes and tags. Do not require a second guestbook file for routine imports if those fields already appear in the reservation CSV.
- Avoid assuming 2025 API property names are 2026 report CSV headers, or that CSV contains `guest_id` or `reservation_id`.
- Preserve a restaurant ID plus reservation ID when both exist. Join to guests on a stable ID where present; otherwise review ambiguities for reused phone numbers and missing contacts.
- Distinguish null, empty string and genuinely present notes; retain provenance for guest request, visit notes, guestbook notes and venue notes.
- Treat table numbers as potentially multiple, and timestamps with and without a timezone as distinct.
- Validate rows with embedded commas, quotes, multiline notes, UTF-8, semicolon/tab delimiters, BOM, 12/24-hour clocks and date ambiguity.
- Avoid unsafe spreadsheet-formula execution when writing new CSVs. Mask sensitive guest notes in non-production fixtures; limit access to production exports.
