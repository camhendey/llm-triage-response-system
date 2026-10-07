# Worked example 2: accessibility and availability conflict

Replay: `python scripts/run_worked_examples.py`. Synthetic data, fixed demo clock, offline interpreter. Nothing is sent and no external system is read or updated.

| Demo clock (America/Toronto) | Who | Action | Result |
|---|---|---|---|
| Tue Nov 10 10:00 | guest | message received (new inquiry) | ok: Created INQ-0001 |
| Tue Nov 10 10:00 | operator | Interpret new messages (offline rules) | ok: Interpretation ok: 10 facts |
| Tue Nov 10 10:00 | operator | Try proposing stairs-only M1 (should be refused) | refused: M1 cannot be used: R-ACCESS: stairs-only seating; guest needs step-free access |
| Tue Nov 10 10:00 | operator | Propose checked alternative 20:30 on G_L3_L4 | ok: Proposal P-0001: G_L3_L4 (tables L3+L4), Fri Nov 13 20:30. Approve it before creating a hold or confirmation. |
| Tue Nov 10 10:00 | operator | Approve proposal | ok: Proposal P-0001 approved for record version 2. |
| Tue Nov 10 10:00 | operator | Generate draft | ok: Draft DR-0001 generated (alternative_offer, prose: deterministic). |
| Tue Nov 10 10:00 | operator | Mark draft reviewed | ok: Draft marked reviewed. It has not been sent anywhere. |
| Tue Nov 10 10:00 | operator | Record that I copied the draft (not sent) | ok: draft copy/export recorded (not a send). |
| Tue Nov 10 10:00 | operator | Mark reply sent (reported) - awaiting guest | ok: INQ-0001: awaiting guest marked. |
| Tue Nov 10 11:30 | guest | message received | ok: Added message INQ-0001-M2 |
| Tue Nov 10 11:30 | operator | Interpret new messages (offline rules) | ok: Interpretation ok: 1 facts |
| Tue Nov 10 11:30 | operator | Check & propose | ok: Proposal P-0002: G_L3_L4 (tables L3+L4), Fri Nov 13 20:30. Approve it before creating a hold or confirmation. |
| Tue Nov 10 11:30 | operator | Approve proposal | ok: Proposal P-0002 approved for record version 3. |
| Tue Nov 10 11:30 | operator | Create demo hold | ok: Demo hold B-A0001 created on L3, L4 until 2026-11-12 11:30. |
| Tue Nov 10 11:30 | operator | Record demo confirmation | ok: Demo confirmation recorded for B-A0001. |
| Tue Nov 10 11:30 | operator | Generate draft | ok: Draft DR-0002 generated (confirmation, prose: deterministic). |
| Tue Nov 10 11:30 | operator | Mark draft reviewed | ok: Draft marked reviewed. It has not been sent anywhere. |
| Tue Nov 10 11:30 | operator | Record that I copied the draft (not sent) | ok: draft copy/export recorded (not a send). |

Files: `inputs.json` (guest messages), `decisions.json` (every action), `snapshots.json` (facts, rules and next action at each checkpoint), `final_record.json` (inquiry, booking, events), `drafts.md`, `booking_notes.txt`.
