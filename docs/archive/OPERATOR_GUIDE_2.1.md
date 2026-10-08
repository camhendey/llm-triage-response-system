# Operator guide: NiceGUI

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.

Start with `python app.py` and open http://localhost:8080. The main navigation contains Inquiries, Service, Project and Settings. The default workspace contains synthetic restaurant data and uses a fixed demo clock. Nothing is sent to a guest or synchronized with an external booking system.

## Complete an inquiry

1. **Find the request.** Inquiries shows a searchable list with reservation details, next steps and expiring holds. Filter by progress or unread messages, then choose Open. The reading indicator is separate from whether text has been interpreted.
2. **Read and check.** The conversation sits beside the Plan/Reply panel. On smaller screens, switch between Request, Plan and Reply. Unknown information remains missing; disputed values retain their sources. Add guest replies through the conversation panel. Offline interpretation runs after adding a reply. Live mode requires an explicit Interpret message action.
3. **Correct details.** Expand Reservation, Requirements or Guest & preferences and use Edit. Save a source/reason with the changes. Blank duration uses the restaurant default. Clearing a value marks it unknown without deleting its history. Inline review controls can confirm an extracted value or resolve a conflicting guest correction.
4. **Choose seating.** Select the suggested arrangement, or compare other tables and times. The schematic is a preview, not a real floor plan. Selecting an alternative prepares an offer; it does not establish guest agreement. Record accepted date/time changes before finalizing.
5. **Record the booking decision.** Confirm booking, Create hold, Confirm held booking or Apply booking change calls the existing rules and availability checks. Short-notice holds require an expiry deadline. The original booking stays allocated until a modification succeeds. Missing requirements and policy reviews remain visible.
6. **Prepare the reply.** In Reply, prepare the record-grounded draft. Edit, Save reply and Mark reviewed. Reply options contains purpose selection and regeneration. New messages, changed facts or changed seating invalidate earlier approval. Earlier versions remain accessible.
7. **Hand off.** Copy or download the reviewed reply. Copy success is shown only when the browser reports a successful clipboard write. Use the download if clipboard permission is blocked. After actually sending elsewhere, Mark as sent externally records the exact reviewed reply in conversation history. It does not verify delivery.
8. **Prepare service.** Service defaults to arrival briefs. Choose a date, inspect requirements and outstanding work, open the corresponding inquiry or export a CSV handoff. Timeline shows occupancy at 15-minute granularity; arrival briefs retain exact times.

## Exceptions

- Cancellation, hold release, decline, closure and reopening are in Other booking actions. A dialog requires a reason. Closing an inquiry does not cancel its booking.
- Private-events escalation is an internal flag. Record completed referral only after performing the referral elsewhere. Neither action confirms private-room availability.
- Allergy follow-up records human review, never a guarantee of accommodation.
- Minimum-spend changes invalidate earlier agreement. Save the new amount before recording renewed agreement.
- Interpretation limitations remain visible. Review the source text and enter missing facts manually; the app does not infer unknown information to make a booking look complete.
- Activity & evidence contains append-only events, source values, interpretation diagnostics and rule results.

## Drafts and concurrent tabs

Draft edits survive navigation within the same open browser page. Save before reloading, closing the page or stopping the server. Separate browser pages do not share unsaved buffers. Saved records are shared through SQLite.

A command based on an older record or audit event is rejected. Refresh and inspect the current state. If another tab changed a saved draft, your unsaved text remains visible beside the current saved text for comparison. A failed form submission retains its values.

## Settings and project tools

Settings switches between the fixed-clock demo and the real-clock session database. Advancing the demo clock can expire holds. Reset requires confirmation and only replaces the designated demo database; reload other tabs afterward. CSV files are staged in the browser session and imported only after clicking Import CSV. Live mode can make external model calls when interpreting imported rows.

Project contains guided examples, evidence boundaries, the operator study timer and synthetic restaurant policies. Study sessions record actual timer actions and checklist entries. Browser verification uses disposable study databases; it is not a human productivity study.

The optional older interface runs with `python -m streamlit run streamlit_app.py`. Use one interface at a time during ordinary work. Neither interface provides production authentication or multi-user administration.

## Session-start OpenTable exports (2.1)

Every new NiceGUI page or reload opens **Prepare your session**. Upload a reservations CSV/TSV, review mappings and source report settings, then **Validate report → Use this report → Open workbench**. A guestbook is optional. **Use synthetic demo without exports** explicitly bypasses import for practice. **Session exports** replaces or clears snapshots later.

An inquiry's **Plan → OpenTable report context** shows date-scoped reservation rows, potentially active covers and exact-contact guest candidates. These are read-only source records. Historical notes never automatically become current allergy facts. Real availability and booking changes must be verified in OpenTable; the seating model is still synthetic. See [the import guide](OPENTABLE_IMPORT.md) for exact formats and limits.
