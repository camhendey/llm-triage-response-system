# Worked example 3: an existing booking changes (and a cancellation)

Replay: `python scripts/run_worked_examples.py`. Synthetic data, fixed demo clock, offline interpreter. Nothing is sent and no external system is read or updated.

| Demo clock (America/Toronto) | Who | Action | Result |
|---|---|---|---|
| Tue Nov 10 10:00 | guest | message received | ok: Added message INQ-B002-M2 |
| Tue Nov 10 10:00 | operator | Interpret new messages (offline rules) | ok: Interpretation ok: 7 facts |
| Tue Nov 10 10:00 | operator | Check & propose (L1 at 19:00) | refused: L1 cannot be used: R-OVERLAP: table L1 confirmed by B001 18:00-20:30 |
| Tue Nov 10 10:00 | operator | Generate draft | ok: Draft DR-0001 generated (change_unavailable, prose: deterministic). |
| Tue Nov 10 10:00 | operator | Mark draft reviewed | ok: Draft marked reviewed. It has not been sent anywhere. |
| Tue Nov 10 10:00 | operator | Record that I copied the draft (not sent) | ok: draft copy/export recorded (not a send). |
| Tue Nov 10 10:30 | guest | message received | ok: Added message INQ-B002-M3 |
| Tue Nov 10 10:30 | operator | Interpret new messages (offline rules) | ok: Interpretation ok: 2 facts |
| Tue Nov 10 10:30 | operator | Check & propose | ok: Proposal P-0001: D1, Fri Nov 13 19:00. Approve it before creating a hold or confirmation. |
| Tue Nov 10 10:30 | operator | Approve proposal | ok: Proposal P-0001 approved for record version 3. |
| Tue Nov 10 10:30 | operator | Commit demo change | ok: B002 moved to D1 2026-11-13 19:00. |
| Tue Nov 10 10:30 | operator | Commit demo change again (rerun) | refused: Proposal P-0001 was already committed. |
| Tue Nov 10 10:30 | operator | Generate draft | ok: Draft DR-0002 generated (change_confirmed, prose: deterministic). |
| Tue Nov 10 10:30 | operator | Mark draft reviewed | ok: Draft marked reviewed. It has not been sent anywhere. |
| Tue Nov 10 10:30 | operator | Record that I copied the draft (not sent) | ok: draft copy/export recorded (not a send). |
| Tue Nov 10 11:30 | guest | message received | ok: Added message INQ-B002-M4 |
| Tue Nov 10 11:30 | operator | Interpret new messages (offline rules) | ok: Interpretation ok: 0 facts |
| Tue Nov 10 11:30 | operator | Generate draft | ok: Draft DR-0003 generated (cancellation_received, prose: deterministic). |
| Tue Nov 10 11:30 | operator | Record demo cancellation | ok: Demo cancellation recorded for B002; tables released. |
| Tue Nov 10 11:30 | operator | Generate draft | ok: Draft DR-0004 generated (cancellation_confirmed, prose: deterministic). |
| Tue Nov 10 11:30 | operator | Mark draft reviewed | ok: Draft marked reviewed. It has not been sent anywhere. |
| Tue Nov 10 11:30 | operator | Record that I copied the draft (not sent) | ok: draft copy/export recorded (not a send). |

Files: `inputs.json` (guest messages), `decisions.json` (every action), `snapshots.json` (facts, rules and next action at each checkpoint), `final_record.json` (inquiry, booking, events), `drafts.md`, `booking_notes.txt`.
