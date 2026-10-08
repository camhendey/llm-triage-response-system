# Build status · version 3.0

The primary UI is the unseeded coordinator at `/`: persisted shifts/reports, explicit visit facts, conditional snapshot assistance, version-bound acceptance/approval/external verification, reviewed responses, follow-ups, local retention actions and service review receipts. `/demo` preserves the synthetic workbench; no legacy database is migrated.

Current suite: **198 tests** (153 retained + 45 coordinator cases). Actual browser results/run dates are recorded in `VERIFICATION.md` and `results/verification/`. Live-model evaluation and the human study remain unrun. Genuine current exports, layout, policies and seating photographs must be provided and validated, not invented.

See `COORDINATOR_TRACEABILITY.md` for implemented/manual boundaries and `COORDINATOR_VALIDATION.md` for pilot prerequisites. This is a local portfolio prototype, not a production-ready service.

## Historical version 2.1 status

The table below describes the preserved demo/import baseline, not the primary coordinator workspace.

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.

| Area | State |
|---|---|
| Primary UI | NiceGUI; new session setup, reviewed CSV/TSV import and inquiry reference context |
| Automated checks | 153 passing |
| Browser checks | Import journey, existing booking journey and desktop/mobile screenshot journey |
| Source evidence | Supplied research pack retained; no authenticated current dashboard CSV verified |
| Data | One read-only reservations snapshot and optional guestbook per browser page; no persistent export storage |
| Core services | Existing booking, facts, drafts, rules and SQLite schema retained |
| Live integrations | None added; optional existing live interpreter unverified |
| Human study | Still pending; no new time-saving claim |
| Legacy UI | Optional Streamlit interface retained without session export support |

See `OPENTABLE_IMPORT.md` for supported inputs, setup, decisions and limitations; `VERIFICATION.md` for evidence and reproduction.
