# Claims register

Every public claim about this project should appear here with its evidence and qualification. If a claim is not here, it should not be made. Status: **supported** (evidence in this repository), **qualified** (supported only with the stated caveat), **not supported** (do not claim).

## About the software

| # | Claim | Status | Evidence | Qualification |
|---|---|---|---|---|
| C1 | A working, human-reviewed reservation workbench with queue, facts with provenance, seating rules, holds, confirmations, changes, cancellations and reviewed drafts | supported | source; `docs/screenshots/`; 117 passing tests | Simulated restaurant and synthetic data only |
| C2 | Seating decisions are deterministic and explainable (every rejected option lists its reasons) | supported | `rules/availability.py`; screenshot 03; `examples/02_accessibility_conflict/snapshots.json` | Simple fixed ranking, not an optimiser |
| C3 | It never sends messages or updates an external booking system | supported | no network code besides the optional model API; copy/send events (A25); draft validator | Operators can record that they sent something elsewhere; the app cannot verify it |
| C4 | Operator corrections are never silently overwritten | supported | `rules/facts.py`; test A03 | |
| C5 | Approvals are tied to a record version; a fact change blocks the old approval | supported | tests A02, A10, A24; `docs/figures/correction_sequence.png` | |
| C6 | Holds reserve real tables until expiry; groupings consume their tables | supported | tests A06, A09 | |
| C7 | Changes are atomic and actions are idempotent | supported | tests A11, A13, A14 | SQLite transactions and record-version checks; single-operator prototype |
| C8 | Guest text cannot instruct the system | qualified | tests A19 (offline and fake live client); held-out adversarial group 3/3 | Live-model behaviour not tested against the real API |
| C9 | Critical facts in drafts (dates, times, party size, status) come from the record, not from a model | supported | `services/drafting.py`; test A30; 0 validator errors across 38 drafts per held-out run | |
| C10 | Live model integration with structured output, validation and bounded retries | qualified | `providers/anthropic_live.py`; fake-client tests A20, A22 | **Not run against the real API.** Do not claim measured live accuracy |
| C11 | Runs offline with no API key | supported | clean-install check | The offline interpreter is pattern rules with narrow coverage |

## About evaluation

| # | Claim | Status | Evidence | Qualification |
|---|---|---|---|---|
| E1 | 60 synthetic scenarios (20 development, 40 held-out), frozen by hash before the first held-out run | supported | `data/eval/`, `FREEZE.json`, `rw eval validate` | Agent-authored labels; no independent review |
| E2 | First blind held-out run: next action allowed 33/40, field agreement 91/97, constraint recall 17/20, 1 critical-error case | supported | `results/eval/20261006T235717-heldout-offline` | Offline interpreter; synthetic, agent-authored |
| E3 | Final retest: 37/40, 97/97, 20/20, 0 critical-error cases | qualified | `results/eval/20261007T002542-heldout-offline` | **Retest after inspecting held-out failures; not blind.** Always quote it next to E2 |
| E4 | 0 prohibited claims in generated drafts | qualified | all held-out runs | Deterministic phrase checks on templated drafts, not semantic review |
| E5 | The evaluation found and fixed a critical party-size error and a ranking regression | supported | EVALUATION.md, commits `d2a508e`, `fd9fe2b`, `dedb30a` | |
| E6 | Any live-model accuracy, latency or cost figure | **not supported** | `results/eval/live_status.json` (`not_run`) | Needs a key and an explicit budget |
| E7 | "Production-ready", "deployed", "used by a restaurant" | **not supported** | | Not deployed; no users |

## About time savings and history

| # | Claim | Status | Evidence | Qualification |
|---|---|---|---|---|
| H1 | During his employment Cameron used LLMs with structured workflows, not Python or APIs | supported (Cameron's statement) | PROVENANCE.md | |
| H2 | Cameron inherited base templates and created the additional workflow | supported (Cameron's statement) | PROVENANCE.md | Line-level split not documented |
| H3 | His workflow cut active handling of a typical complex inquiry from about 45 to about 5 minutes | qualified | Cameron's own estimate | Not a benchmark; measurement method not established; describes the historical workflow, not this app |
| H4 | This application saves operator time | **not supported** | `docs/figures/handling_time_status.json` (pending, 0/36 sessions) | Only claimable after real study sessions, and then only as a small single-operator self-test with median and range |
| H5 | This application prevents real double bookings | **not supported** | | It tests overlap logic on synthetic data only |
| H6 | Affiliation with, endorsement by or integration into any restaurant or reservation platform | **not supported** | | None exists |

## About how it was built

| # | Claim | Status | Evidence | Qualification |
|---|---|---|---|---|
| B1 | Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025 | supported (Cameron’s statement) | PROVENANCE.md | Inherited base response templates remain credited as inherited; development tools do not imply co-developers. This does not backdate the later Python implementation. |

## Refinement evidence (1.1)

| Claim | Evidence | Qualification |
|---|---|---|
| Selected-arrangement drafts, full reported conversation, typed editing and daily handoff | `tests/test_refinements.py`, UI tests and refined screenshots | Simulated bookings; outbound records are operator assertions |
| Current regression result: 39/40 next actions, 97/97 field agreement, 0 critical-error cases | `results/eval/20261006T222849-heldout-offline/` | Previously inspected 40-case suite, not blind; occasion policy change explains two improved next actions |
| 15 new regression/UI tests, 117 total | `results/verification/pytest.txt` | Passing tests demonstrate specified cases, not production reliability |

Supplemental extraction challenge: 31/32 labelled fields and 6/6 unknowns across 12 new development-authored cases (`results/refinement-challenge/`). First execution, no subsequent tuning; not independent, and next-action accuracy was not scored.
