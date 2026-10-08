# Coordinator architecture and decisions

NiceGUI renders a per-page `CoordinatorDesk` which invokes `Workflow` commands against a separate SQLite `Store`. The original synthetic engine remains behind `/demo`. No schema migration, silent model upload, OpenTable write client or email sender is introduced.

`coordinator/store.py` owns transactions, report expiry, photo validation and buffers. `coordinator/workflow.py` owns state rules. `coordinator/availability.py` owns conditional snapshot assessment. `web/coordinator.py` renders operator actions. The existing bounded parser remains in `services/opentable_import.py`.

## Evidence binding

| Evidence | Bound to | Invalidation |
|---|---|---|
| Guest acceptance | Plan hash including seating, duration, terms and photo/exception | Plan edit |
| Manual availability | Plan hash, policy version, four-hour window | Plan/policy edit or expiry |
| Manager approval | Plan hash and policy version | Plan/policy edit |
| External verification | Plan/contact/requirements/promises hash and policy version | Relevant record/policy edit |
| Response review | Saved text hash and source fingerprint | Text/evidence change or non-acknowledgement message |
| Staff receipt | Snapshot/hash of service record | Changed allocation, requirements, promises, owner, status or tasks |

External allocation is a deep copy at verification time. Requested changes do not overwrite it. Guest acceptance, external confirmation, response review/sending and task completion are independent.

## Concurrency and durability

Case commands use `BEGIN IMMEDIATE`, check active operator and expected revision, apply the command, increment revision and append before/after audit changes atomically. Failures roll back. Policy writes have version checks. URL-specific draft buffers survive reload but are not approvals. This protects ordinary tabs, not a production multi-user authorization boundary.

## Snapshot assessment

Imports use reviewed mappings and one-venue validation. An observed restaurant ID is pinned. Reports replace by type. Stable reservation IDs support added/changed/absent summaries; missing IDs limit reconciliation. Absence never cancels a booking.

Assistance requires reviewed layout, complete-coverage attestation, matching time zone, fresh report and occupancy estimate. Coverage must include overlapping prior-day occupancy. Unknown overlapping status/table assignments block assessment. Only configured single tables or allowed groups with capacity are considered; known step-free requirements constrain options. Options rank by number of tables, then capacity, not revenue or staffing.

The linked booking is excluded for change planning. Newer manually verified allocations overlay older reports by reference. Newer contradictory/absent snapshots require manual reconciliation. Durations are estimated where exports lack end times. All results require a live manual availability/flow check.

## Human decisions and limitations

The coordinator determines whether a message is acknowledgement-only, a quote truly accepts current terms, an imported contact is the same person, a photo exception is justified and restaurant flow supports the booking. Exact quote validation proves provenance, not semantic truth. The wording regex blocks limited confirmation language, not every possible misleading sentence.

The primary workspace uses offline pattern extraction. The optional live model remains in the synthetic demo for controlled evaluation. No new live-AI quality/cost result is claimed.

Raw reports are cleared at shift end or logically expired on next access after 24 hours, not guaranteed idle-time deletion. Cases, copied evidence, audits, buffers and photos persist separately. Typed-ID deletion removes only a closed case, its audit and buffers. SQLite deletion is not forensic erasure. Production use requires authentication, encryption, roles, backup/restore and an organizational retention policy.

Staffing/pacing, day-specific table preferences, booth preferences, exceptional accessibility needs and variable real dining durations remain manual flow considerations. Validated local rules and representative data are prerequisites for automating them. No autonomous sending, booking, payment, escalation, identity merging, historical-allergy confirmation, inferred cancellation or automatic hold release is implemented.
