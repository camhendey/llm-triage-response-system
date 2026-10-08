# Coordinator operator guide · 3.0

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.

## First setup

Start `app.py`, open localhost:8080 and enter your coordinator name, restaurant and IANA time zone. Confirm authorized local storage. Settings must reflect the **current restaurant**, not an old manual. Add actual table IDs, capacities, area/style, verified step-free status and allowed combinations. Add occupancy-duration estimates, turnover buffer and separate minimum-spend and manager-approval thresholds. A blank threshold disables that automated threshold; it does not prove the restaurant has no policy. Record who reviewed the configuration. Table changes clear that review.

Upload authorized seating photographs with meaningful captions. Real layout, current policy and photographs are not invented for you. Use another database for another restaurant: name/time zone are locked once cases exist, and imported restaurant IDs remain pinned after report clearing.

## Each shift

In **Shift & reports**, upload a fresh reservations CSV/TSV. Optional guestbooks are separate. Check mappings, report type, slash-date order, export timestamp with explicit offset, and inclusive date coverage. Preview warnings and changes before applying. Attest completeness only after checking filters; otherwise the report remains reference-only. Remembered header mappings still require review.

A report replaces its type, never appends duplicates. Missing rows do not mean cancellation. Exports over four hours old cannot support snapshot assistance. Reloads preserve the shift; ending it clears raw reports. Reports also expire after 24 hours on next access. If unavailable, record a manual-check reason and check availability externally.

## Request

Enter the original inquiry, source and originally received timestamp with offset. The queue prioritizes overdue and near-term tasks/holds, then original receipt time. Record requirements as not asked, awaiting, historical or confirmed. Confirmation requires a value and evidence; use explicit `None` where appropriate. Local extraction provides quoted suggestions, never automatic fact replacement.

Record new messages as changes unless genuinely acknowledgement-only. Changes block outcome responses until reviewed. Record reached-guest calls, no answer, voicemail, incorrect number or callback requested. Unsuccessful calls create follow-up tasks. The calling window is a warning, not a telephone integration; schedule any specific callback as an owned follow-up task.

## Plan

Save date/time, party, duration, configured tables and a guest-facing seating explanation. Multiple tables need an allowed grouping with sufficient capacity. Where relevant, record spend amount, currency, total/per-person basis and inclusions/exclusions; waivers require approval. Choose a seating photograph or record a case-specific exception.

`Cannot assess` means missing or unsafe evidence, not no availability. `Potentially feasible` assumes the configured layout, declared coverage and estimated occupancy. Verify current OpenTable availability and restaurant flow in every case, record evidence, then obtain any required approval.

Perform the actual booking externally. Reopen and check date/time, tables/party, guest requirements, large-party classification and saved notes/Made by. Record reference, status and evidence. A hold deadline must be future and before the visit. Expiry creates a manual-release action, never an automatic external release.

Obtain guest agreement using an exact quote from an Email/Phone message or reached-guest call. Explicitly attest that it accepts the current arrangement and terms. A plan change makes acceptance stale. Contact/requirement changes require renewed external verification without necessarily discarding the accepted seating terms.

## Communicate

Choose clarification, offer, final confirmation, decline, referral or cancellation/release. Final confirmation requires complete plan and visit facts, guest acceptance, current external verification, reviewed policy, photo/exception and required approvals. An offer is not final confirmation.

Save edited text, review the saved version, copy, send externally, then report sent. If a photo is selected, attach it in your email client and attest that it was attached. The wording guard is deliberately narrow; human review remains essential. `Saved` never means `Sent`.

Working text and response purpose survive reload for the same browser URL. A recovered buffer can predate another tab's changes. Review it before saving. Changed evidence invalidates saved review.

## Outcomes and follow-ups

Plan → Alternative outcome supports decline, referral, cancellation and release with reasons. Release/cancel active external bookings before decline/referral. Referral requires a current feasibility record and actual recipient/handoff evidence. Cancellation/release must match the linked external reference. Prepare the matching outcome response; a clarification cannot complete a declined case.

Tasks need an owner, waiting-on party, offset-aware deadline and completion evidence. Offer sending creates a guest-acceptance follow-up; acceptance closes that task, not unrelated work. Close only fully completed inquiries. A new change message can reopen one.

## Service and end of shift

Select the service date. The brief shows the **saved external allocation**, not the proposed change. Review requirements, promises, owner and pending work. Record the staff recipient. Changes since that receipt are flagged. CSV export neutralizes leading spreadsheet formula characters.

End the shift in Shift & reports. Inquiries, copied evidence, photos and audits remain; raw snapshots are cleared and running timers stop. Timers record elapsed click intervals, not validated productivity evidence.

## Privacy and recovery

Back up `data/coordinator/workbench.sqlite` with the app stopped and protect it as guest information. No authentication, encryption, remote synchronization or secure-delete guarantee is provided. Do not expose this server publicly. Typed-ID removal of a closed case deletes its local record, audit and buffers, with no in-app undo; source reports, photos, backups and external bookings are unaffected.

`/demo` preserves the synthetic workbench and optional live-provider path. Its data and fixed clock never establish real availability. Its older session mode is distinct from the new empty coordinator database.
