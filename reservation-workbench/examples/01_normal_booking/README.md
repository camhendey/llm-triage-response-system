# Worked example 1: a normal booking

Replay: `python scripts/run_worked_examples.py`. Synthetic data, fixed demo clock, offline interpreter. Nothing is sent and no external system is read or updated.

| Demo clock (America/Toronto) | Who | Action | Result |
|---|---|---|---|
| Tue Nov 10 10:00 | guest | message received (new inquiry) | ok: Created INQ-0001 |
| Tue Nov 10 10:00 | operator | Interpret new messages (offline rules) | ok: Interpretation partial: 9 facts |
| Tue Nov 10 10:00 | operator | Check & propose | ok: Proposal P-0001: L3, Sat Nov 14 19:30. Approve it before creating a hold or confirmation. |
| Tue Nov 10 10:00 | operator | Approve proposal | ok: Proposal P-0001 approved for record version 2. |
| Tue Nov 10 10:00 | operator | Approve proposal again (double click) | refused: Proposal P-0001 is approved; only proposed can be approved. |
| Tue Nov 10 10:00 | operator | Create demo hold | ok: Demo hold B-A0001 created on L3 until 2026-11-12 10:00. |
| Tue Nov 10 10:00 | operator | Generate draft | ok: Draft DR-0001 generated (hold_offer, prose: deterministic). |
| Tue Nov 10 10:00 | operator | Mark draft reviewed | ok: Draft marked reviewed. It has not been sent anywhere. |
| Tue Nov 10 10:00 | operator | Record that I copied the draft (not sent) | ok: draft copy/export recorded (not a send). |
| Tue Nov 10 10:45 | guest | message received | ok: Added message INQ-0001-M2 |
| Tue Nov 10 10:45 | operator | Interpret new messages (offline rules) | ok: Interpretation ok: 0 facts |
| Tue Nov 10 10:45 | operator | Record demo confirmation | ok: Demo confirmation recorded for B-A0001. |
| Tue Nov 10 10:45 | operator | Generate draft | ok: Draft DR-0002 generated (confirmation, prose: deterministic). |
| Tue Nov 10 10:45 | operator | Mark draft reviewed | ok: Draft marked reviewed. It has not been sent anywhere. |
| Tue Nov 10 10:45 | operator | Record that I copied the draft (not sent) | ok: draft copy/export recorded (not a send). |
| Tue Nov 10 10:45 | operator | Record that I copied booking notes | ok: booking_notes copy/export recorded (not a send). |

Files: `inputs.json` (guest messages), `decisions.json` (every action), `snapshots.json` (facts, rules and next action at each checkpoint), `final_record.json` (inquiry, booking, events), `drafts.md`, `booking_notes.txt`.
