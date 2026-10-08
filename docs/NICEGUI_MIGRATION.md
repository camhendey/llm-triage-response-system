# NiceGUI migration, version 2.0

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025. Software verification dates retain their actual execution dates.

## Purpose

Replace the primary Streamlit presentation layer with a more deliberate reservation-desk interface while preserving the tested domain model, booking rules, local data and review checkpoints. No separate JavaScript application or frontend build was added.

## What changed

- A compact inbox replaces repeated oversized entry cards. Search includes canonical guest details and message text; filters separate operational progress from unread messages.
- Persistent navigation, a restrained cobalt/neutral palette, consistent spacing, white form fields and smaller dialogs create a coherent interface.
- A conversation/context column sits beside a wider Plan/Reply column. Small screens use Request/Plan/Reply navigation rather than an endlessly stacked page.
- Seating, booking decisions and reply preparation remain explicit. Reply purpose and regeneration move behind secondary controls once a draft exists.
- Arrival briefs and a secondary timeline support service preparation. CSV handoff remains available.
- Each browser page owns its selection and unsaved text. Each command opens and closes its own database connection within its execution thread.
- Commands check both record version and the latest audit event. This protects draft review from edits that do not increment the booking record version. Failed grouped mutations roll back at the UI boundary.
- Clipboard and reviewed-download actions recheck the current draft. New guest messages still invalidate approval, even when extracted facts stay unchanged.
- Empty optional database environment variables now fall back to the documented paths, so copying `.env.example` does not select a directory as the database.

## Workflow coverage

| Existing capability | NiceGUI location |
|---|---|
| Inquiry queue, search, progress filters, unread state | Inquiries |
| New inquiry and guest replies | New inquiry; Conversation |
| Offline/live interpretation and diagnostics | Conversation; Activity & evidence |
| Typed edits, unknown clearing, conflicting observations and source history | Guest details |
| Suggested seating, alternative times, reasons and table previews | Plan |
| Holds, confirmations, changes and version/availability checks | Plan |
| Cancellation, release, decline, close/reopen and recorded external actions | Other booking actions |
| Referral report, allergy review and minimum-spend agreement | Plan review controls |
| Draft generation, editing, approval, copying, downloads and reported sending | Reply |
| Prior replies, booking notes and audit events | Reply; Activity & evidence |
| Arrival briefing, timeline and daily export | Service |
| CSV import, database selection, clock and guarded demo reset | Settings |
| Examples, policy configuration, evidence and timed study records | Project |

## Architecture

`web/main.py` builds the client-scoped interface. `web/theme.py` contains the visual system. `web/common.py` handles labels, scoped connections and transactional command dispatch. These call the existing services, rules, providers and persistence code. No booking policy was moved into CSS, browser scripts or UI callbacks.

The UI's thread worker keeps synchronous provider calls off the main event loop. SQLite writes remain serialized; this is not a claim of production-scale concurrent service. Record IDs and schema version remain unchanged. The CLI and saved evaluation files remain available.

The retained `streamlit_app.py` and `ui/` modules are a fallback and historical comparison, not the primary frontend. Streamlit is an optional dependency, included in the development extra to run its retained regression tests.

## Evidence and limits

Verification includes backend/legacy UI tests, six new command-boundary tests, and two real Chromium journeys. Browser checks exercise editing and invalidation, confirmation, reply editing across navigation, clipboard content, reported sending, new inquiry creation, holds, cross-tab conflicts, cancellation, CSV upload/import, the study timer and responsive layouts.

The migration does not establish faster human task completion. It does not verify live API quality, real restaurant integrations, Windows/macOS installation, physical mobile devices or screen-reader conformance. Browser study-timer checks use temporary databases and are excluded from human study results. See VERIFICATION.md for the recorded outcomes.
