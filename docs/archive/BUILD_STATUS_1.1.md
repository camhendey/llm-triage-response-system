# Build status — version 1.1

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025. Current software verification retains its execution dates.

| Gate | Status | Evidence |
|---|---|---|
| Working offline prototype | Implemented | Source, synthetic seed data, configuration, CLI and UI |
| Automated tests | 117 passing | `results/verification/pytest.txt`; 15 tests added to the original 102 |
| Complete UI journey | Verified | `tests/test_ui_apptest.py`: selection, confirmation, draft edit/save/review, navigation and reported sending |
| Rendered UI | Captured in Chromium | `docs/screenshots/refined/` and reproducible script |
| Frozen-case regression | 39/40 next actions, 97/97 fields, 0 critical-error cases | `results/eval/20261006T222849-heldout-offline/` |
| Supplemental extraction challenge | 31/32 fields, 6/6 unknowns across 12 cases | `results/refinement-challenge/`; no independent review |
| Live API verification | Not run | No credentials/budget supplied; fake-client tests only |
| Human handling-time study | Pending | Existing study harness and protocol; no completed sessions |
| Production integration | Out of scope | No email sending, external booking changes or deployment |

The 2024/2025 dates refer to project provenance, not the test run timestamps. The runtime clock for this refinement run was earlier than the original package's run timestamps; retain the recorded timestamps and use revision context rather than chronological folder sorting to identify this run.

## Remaining limitations

HO-ORD-01 still needs operator review because the offline parser does not interpret its access wording reliably. The two occasion-related next-action misses disappear because occasion is now optional, not because the parser learned those phrases. Original frozen labels remain unchanged. The inspected 40 cases are a regression suite; independent cases and external label review are needed before broader accuracy claims.

Read [REFINEMENT.md](REFINEMENT.md), [VERIFICATION.md](VERIFICATION.md) and [CLAIMS.md](CLAIMS.md) for the current evidence boundaries. The original acceptance scenarios A01–A30 remain in the test suite.
