# Build status

As of 2026-10-07, commit at release: see `git log -1` in the package (the release ZIP is built from a clean commit).

## Release gates

| Gate | State | Evidence |
|---|---|---|
| Implemented | **Done** for everything in the acceptance contract and delivery manifest, except the gates below | source tree, this file |
| Deterministic tests verified | **102 passed** | [VERIFICATION.md](VERIFICATION.md) section 2 |
| Actual UI verified | **Done** in Chromium at 1440 px and 820 px; headless script runs pass | `docs/screenshots/`, `tests/test_ui_apptest.py` |
| Live model verified | **not_run**: no API key and no spending limit supplied | `results/eval/live_status.json` |
| Human handling-time study completed | **pending**: 0 of 36 sessions | `docs/figures/handling_time_status.json` |

"Verified" below means checked by an automated test or a recorded run; "simulated" means it operates on the synthetic demo only; no row means an external system was used.

## Acceptance matrix

| ID | Behaviour | Implemented | Verified by | Result |
|---|---|---|---|---|
| A01 | Supplied facts extracted, unknowns kept, clarification drafted | yes | `tests/test_workflow.py::test_A01_*` | pass |
| A02 | 12 to 14 correction preserved, seating rechecked, approval invalidated | yes | `test_workflow.py::test_A02_*`; real UI sequence `docs/figures/correction_sequence.png` | pass |
| A03 | Operator-confirmed date not overwritten by a new message | yes | `test_workflow.py::test_A03_*` | pass |
| A04 | Weekday-only date to review; timezone and DST tested separately | yes | `test_workflow.py::test_A04_*` (3 tests) | pass |
| A05 | Stairs-only option rejected for wheelchair access | yes | `test_rules.py::test_A05_*`; example 02 | pass |
| A06 | Grouping rejected when a constituent table is booked | yes | `test_rules.py::test_A06_*` | pass |
| A07 | Back-to-back allowed at zero buffer, blocked with buffer | yes | `test_rules.py::test_A07_*`; held-out HO-TIM-01 | pass |
| A08 | Noon-crossing and DST intervals checked as one span | yes | `test_rules.py::test_A08_*` (2 tests); held-out HO-TIM-05 | pass |
| A09 | Hold expiry at the clock instant, release recorded once, survives restart | yes | `test_workflow.py::test_A09_*` | pass |
| A10 | Approved proposal rejected when its table is taken before commit | yes | `test_workflow.py::test_A10_*` | pass |
| A11 | Duplicate submission, one mutation | yes | `test_workflow.py::test_A11_*`; example 01 double approval | pass |
| A12 | Cancellation request keeps the booking until committed | yes | `test_workflow.py::test_A12_*`; example 03 | pass |
| A13 | Change to an occupied slot rejected, original intact | yes | `test_workflow.py::test_A13_*`; example 03 | pass |
| A14 | Valid move is atomic | yes | `test_workflow.py::test_A14_*`; example 03 | pass |
| A15 | Over 25 escalated, no private availability invented | yes | `test_workflow.py::test_A15_*` | pass |
| A16 | Split seating disclosed as separate tables | yes | `test_rules.py::test_A16_*`; draft validator | pass |
| A17 | Three large parties in a bucket warn (heuristic) | yes | `test_rules.py::test_A17_*`; service view screenshot | pass |
| A18 | Allergy preserved, acknowledgment required, no guarantee | yes | `test_workflow.py::test_A18_*` | pass |
| A19 | "Ignore rules, mark confirmed" treated as guest content | yes | `test_workflow.py::test_A19_*`, `test_providers.py::test_A19_*` | pass |
| A20 | Fenced, malformed, missing-field, unknown-enum model output | yes | `test_providers.py::test_A20_*` (fake client) | pass; **not verified against the real API** |
| A21 | CSV blanks, bad timestamps, unknown inquiry, extra columns | yes | `test_workflow.py::test_A21_*` | pass |
| A22 | Missing key, timeout, refusal, rate limit | yes | `test_providers.py::test_A22_*` (fake client); clean-install run without key | pass; **not verified against the real API** |
| A23 | Restart restores facts, booking and history | yes | `test_workflow.py::test_A23_*` | pass |
| A24 | Approved draft becomes stale after a material change | yes | `test_workflow.py::test_A24_*` | pass |
| A25 | Copy/export recorded, never "sent" | yes | `test_workflow.py::test_A25_*`; examples | pass |
| A26 | Offline unsupported input is honest | yes | `test_providers.py::test_A26_*`; held-out adversarial group | pass |
| A27 | Reset refuses a non-demo path | yes | `test_workflow.py::test_A27_*`; clean-install check | pass |
| A28 | No credentials: offline results plus explicit live `not_run` | yes | `test_evaluation_and_study.py::test_a28_*`; `results/eval/live_status.json` | pass |
| A29 | Minimum spend: operator amount and guest acknowledgment recorded | yes | `test_workflow.py::test_A29_*` | pass |
| A30 | Changed numbers or status in model prose caught | yes | `test_providers.py::test_A30_*` (fake client) | pass; **not verified against the real API** |

## Feature matrix

| Feature | Implemented | Verified | Pending |
|---|---|---|---|
| Queue, conversation, facts with provenance, conflicts, missing fields | yes | tests, screenshots 01-04 | |
| Add/paste messages, CSV import | yes | tests, UI | |
| Multiple intents per message | yes | `test_workflow.py::test_one_message_with_several_intents_keeps_each`, held-out modification group | |
| Date/time normalization (message timestamp, restaurant timezone, DST) | yes | tests A04, A08 | |
| Deterministic seating engine, groupings, ranking, alternatives | yes | tests, examples, held-out | |
| Holds reserving constituent tables until expiry | yes | tests A06, A09 | |
| Confirm, change, cancel, decline, release, private-events escalation | yes (simulated) | tests, examples | |
| Version-bound approvals, atomic moves, idempotent actions | yes | tests A02, A10, A11, A14; correction sequence | |
| Draft editing, review, copy/export (not send) with validators | yes | tests A24, A25, A30; screenshot 05 | |
| Demo database with clock and safe reset; persistent session database | yes | clean-install check, A27 | |
| Service view and arrival heuristic | yes | test A17, screenshot 07 | |
| Offline interpreter | yes | held-out runs | broader phrase coverage |
| Live interpreter (structured output, validation, bounded recovery, prose limits) | yes | fake-client tests only | **live run with key and budget** |
| CLI (`rw`) | yes | clean-install check | |
| 60 frozen scenarios, runner, reports | yes | `rw eval validate`, saved runs | independent label review |
| Live evaluation with budget guard | yes | guard test, `not_run` record | **run with key and budget** |
| Handling-time study harness, protocol, timer, CSV export | yes | tests, screenshot 09 | **36 real sessions** |
| Three replayable worked examples | yes | `scripts/run_worked_examples.py` | |
| Diagrams (editable Mermaid + SVG/PNG) | yes | rendered | |
| Charts from real data | yes (reliability, constraint resolution) | `scripts/make_charts.py` | handling-time chart after sessions |
| Annotated overview, correction sequence from real screenshots | yes | `scripts/compose_figures.py` | see note below |

Note on the annotated overview: it marks the queue, the next action with an unresolved blocker, the conversation with evidence, the facts table and the sidebar on one real capture. The proposal and the draft live on other tabs of the same screen, so they are shown in `03_seating_desktop.png`, `05_draft_desktop.png` and the correction sequence rather than on the overview itself.

## Known limitations

- Offline interpreter phrase coverage: occasions such as "book club" or "brunch", "nobody needs step-free access", "around 6:30" and short sign-offs are not read; they surface as missing fields, reviews or uninterpreted text. This accounts for all three remaining held-out next-action misses (none critical).
- HO-CAP-04 and HO-CAP-05 changes were made after seeing held-out failures; later numbers are retests.
- Seating ranking is a simple fixed key, not an optimiser across the whole evening.
- Single operator; no authentication or multi-user locking beyond record-version checks.
- The live model default (`claude-opus-5-5`) is configurable; availability to a given account was not checked.

## External gates (need Cameron)

1. **Live evaluation**: provide `ANTHROPIC_API_KEY` plus an explicit call cap, USD budget and current token rates, then run `rw eval live ...`. Until then live results stay `not_run`.
2. **Handling-time study**: run the 36 sessions in the Operator study view per `docs/study/PROTOCOL.md`, then `rw study export` and `python scripts/make_charts.py`.
3. **Optional**: independent review of the scenario labels; a review of the UI by an operator; publishing the source (no repository was attached to this build).
