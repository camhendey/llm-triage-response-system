# Build status: version 2.0

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025. Software verification retains actual execution dates.

| Gate | Status | Evidence |
|---|---|---|
| Primary frontend | NiceGUI implemented | `web/`, `app.py` |
| Existing workflows | Reconnected to original services | `docs/NICEGUI_MIGRATION.md` coverage matrix |
| Automated tests | 129 passing | `results/verification/pytest.txt` |
| Actual browser journeys | Passing in Chromium | Two scripts and saved verification logs |
| Responsive layouts | 1440, 820 and 390 px captures | `docs/screenshots/nicegui/` |
| Frozen-case regression | 39/40 next actions, 97/97 fields, 0 critical-error cases | Migration regression run under `results/eval/` |
| Supplemental extraction challenge | Historical: 31/32 fields and 6/6 unknowns | `results/refinement-challenge/` |
| Live API validation | Not run | Fake-client tests only |
| Human handling-time study | Pending | Harness retained; browser-test records are disposable |
| External reservation/email integration | Not implemented | No sending, booking-system synchronization or deployment |

The original acceptance scenarios A01–A30 remain in the suite. HO-ORD-01 still requires operator review because the offline parser does not reliably interpret its access wording. Independent labels and real-user task measurements remain necessary before broader reliability or productivity claims.
