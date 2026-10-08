# Reservation Operations Workbench

A single-operator, human-reviewed workbench for large-party restaurant reservation inquiries, built on a **simulated restaurant** ("Harbour Table Demo") with **synthetic data only**. It turns guest emails into typed facts with quoted evidence, checks seating with deterministic rules, records holds, confirmations, changes and cancellations in a local demo database, and prepares reviewed draft replies that the operator copies elsewhere.

**Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.** The original workflow used LLM chat tools and manual booking operations. This repository is its later software implementation; the dates on software verification records remain the actual run dates.

Nothing in this application sends email, reads or updates any external booking system, takes payments or is deployed anywhere. It is a portfolio project by Cameron Hendey; see [docs/PROVENANCE.md](docs/PROVENANCE.md) for how it relates to his earlier, manual, LLM-assisted workflow.

![Refined workbench (real application screenshot)](docs/screenshots/nicegui/02-workspace.png)

## Status (2026-10-07)

| Gate | State |
|---|---|
| Implemented | Workbench UI, service layer, rules engine, offline and live interpreters, CLI, evaluation runner, study harness |
| Deterministic tests | **129 passed** (`pytest`), covering acceptance scenarios A01-A30 |
| Actual UI verified | Chromium captures at 1440 px, 820 px and 390 px; two real NiceGUI browser journeys plus retained legacy UI tests ([docs/VERIFICATION.md](docs/VERIFICATION.md)) |
| Live model verified | **not_run**: no API key or spending limit was supplied ([results/eval/live_status.json](results/eval/live_status.json)) |
| Human handling-time study | **pending**: harness and protocol ready, 0 of 36 sessions recorded |

The original 40-case blind offline run allowed the expected next action in **33/40** cases with **1 critical-error case**. The refinement regression run reaches **39/40** with **0 critical-error cases** and 97/97 labelled field agreement. This is a **retest of previously inspected synthetic cases**, not a fresh blind benchmark; making occasion optional explains two improved next-action results. Live AI performance and time savings remain unmeasured. [Evaluation and limitations](docs/EVALUATION.md).

Version **2.0** replaces the primary interface with NiceGUI: compact inquiry rows, a conversation-and-decision workspace, focused reply editing, mobile Request/Plan/Reply views, and arrival briefs. Business rules and the SQLite schema are retained. [Migration and workflow coverage](docs/NICEGUI_MIGRATION.md).

Version **1.2** simplified navigation, separated booking and reply progress, grouped editable details, added explicit unknown-value clearing, and put arrival briefs first. [UI changes and decisions](docs/UI_REDESIGN.md).

Version **1.1** added a unified coordinator workspace, typed guest-detail editing, selected-plan drafting, seating/time comparisons, outgoing conversation history, explicit referral reporting and a daily handoff export. [Changes](docs/REFINEMENT.md).

## Quick start

Requires Python 3.11+. NiceGUI is the main UI. No separate Node.js, npm or frontend build is required. The offline demo requires no API key.

In **Cursor → Terminal → New Terminal**, use PowerShell:

```powershell
cd "C:\Users\camer\Documents\dev\reservation-workbench"
# Create the environment only if it does not exist:
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints-tested.txt -e .
.\.venv\Scripts\python.exe app.py
```

Open **http://localhost:8080**. Keep the terminal running; Ctrl+C stops the app. After setup, `start-windows.cmd` runs the same command. For subsequent launches, only run `.\.venv\Scripts\python.exe app.py`.

When upgrading, stop the previous app and copy the files inside this ZIP's `reservation-workbench` folder into your existing project folder. Keep your `.env`, `.venv` and existing `data` databases. Re-run the installation command above to install NiceGUI. The database schema has not changed. Avoid creating a nested `reservation-workbench/reservation-workbench` folder.

For development and testing on macOS/Linux:

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -c constraints-tested.txt -e ".[dev]"
cp .env.example .env                                     # optional; offline mode is the default
python app.py                                           # http://localhost:8080
```

The app opens on the **demo** database (`data/demo/workbench_demo.sqlite`), seeded from `data/synthetic/demo_inquiries.json` with a fixed demo clock of Tue Nov 10 2026, 10:00 America/Toronto. Use **Advance 1 hour / Advance 1 day** in **Settings** to move the demo clock (holds expire against it). Switch to the **session** database for a persistent workspace on the real clock.

```bash
rw init-demo                    # create/seed the demo database if missing
rw reset-demo                   # delete and re-seed ONLY the designated demo database
rw queue                        # queue as text
rw show INQ-0103 --notes        # facts, rules and copyable booking notes
rw import-csv messages.csv --interpret          # into the session database
pytest                                          # 129 tests
rw eval validate                                # dataset shape and freeze hash
rw eval run --split heldout --mode offline      # writes results/eval/<run>/
python scripts/run_worked_examples.py           # replays examples/01-03
python scripts/make_charts.py                   # historical evaluation figures
python scripts/capture_nicegui.py                # current screenshots; needs Playwright Chromium
```

`reset-demo` refuses any path other than the designated demo database and refuses any database whose stored kind is not `demo`.

## Demo versus live interpreter

| | Offline (default) | Live (optional) |
|---|---|---|
| What reads the email | Deterministic pattern rules in `providers/offline.py` | Anthropic Messages API with JSON-schema output, validated again locally |
| Needs | nothing | `RW_PROVIDER=live` and `ANTHROPIC_API_KEY` in `.env` |
| Honesty | Labelled "offline pattern rules (not a language model)"; unsupported text is returned as `unsupported` for manual interpretation | Every quote must exist verbatim in a guest message; invalid output is retried a bounded number of times, then fails visibly |

In both modes seating, policy checks, booking state and the critical facts in drafts (dates, times, party size, tables, status) come from deterministic code. A live model may only write a greeting line and a closing line, and validators reject digits or booking/policy words in that prose.

Live evaluation runs only with a key **and** explicit limits:

```bash
rw eval live --max-calls 400 --budget-usd 5 --usd-per-mtok-input <rate> --usd-per-mtok-output <rate>
```

Without them it writes `results/eval/live_status.json` with `status: not_run` and reports no live numbers.

## What the operator can do

- Queue sorted by urgency and deadline; add or paste messages; import CSV with row-level errors.
- Facts with status (known, unknown, needs review, conflict, operator-confirmed), quoted evidence and change history. Operator values are never overwritten by later guest text; disagreements become conflicts.
- Seating check over tables and groupings with reasons for every rejected option, checked alternative times, split-seating disclosure, and a private-events route above 25 guests.
- Proposals bound to a record version; review and commit a demo hold (reserving every constituent table until expiry), record a demo confirmation, commit a change atomically, record a cancellation, release, decline or escalate. Each action is idempotent.
- Minimum spend and allergies require a recorded human decision; nothing is guaranteed to the guest.
- Drafts from templates with deterministic validators; edit, mark reviewed, copy or export. Exports do not send anything. A separate operator assertion adds the exact reviewed reply to conversation history.
- Configuration-derived seating schematic and time comparisons; service occupancy grid, daily handoff CSV, and an arrival-bucket heuristic (not a kitchen-capacity model).
- Operator study timer and protocol; no synthetic time-saving claims.

## Repository map

| Path | Contents |
|---|---|
| `src/reservation_workbench/domain` | Typed models, config loading, clocks |
| `src/reservation_workbench/rules` | Fact reconciliation, availability engine, assessment (next action, rule results) |
| `src/reservation_workbench/providers` | Offline interpreter, live Anthropic provider, shared validation |
| `src/reservation_workbench/services` | Workbench service layer (used by UI, CLI, tests and evaluation), drafting, CSV import, bootstrap/reset |
| `src/reservation_workbench/persistence` | SQLite schema and repository (events, idempotency keys) |
| `src/reservation_workbench/web` | NiceGUI interface, command boundary and visual system |
| `src/reservation_workbench/ui` | Optional legacy Streamlit interface |
| `src/reservation_workbench/evaluation`, `data/eval` | Scenario loader, freeze, runner; 20 development + 40 held-out scenarios |
| `src/reservation_workbench/study`, `data/study`, `docs/study` | Handling-time study harness, cases and protocol |
| `config/restaurant_demo.yaml` | Synthetic restaurant: tables, groupings, policies, seed bookings |
| `examples/` | Three replayable worked examples |
| `results/eval/` | Every saved evaluation run, including the first blind run |
| `docs/` | Documentation, diagrams, figures, screenshots |

## Documentation

[Domain and policies](docs/DOMAIN_AND_POLICIES.md) · [Decisions](docs/DECISIONS.md) · [Provenance](docs/PROVENANCE.md) · [Operator guide](docs/OPERATOR_GUIDE.md) · [Evaluation](docs/EVALUATION.md) · [Verification](docs/VERIFICATION.md) · [Claims](docs/CLAIMS.md) · [Build status](docs/BUILD_STATUS.md)

## Scope boundaries

Synthetic restaurant and guests only. Policies in `config/restaurant_demo.yaml` are demonstration values, not any real restaurant's current policy. No real guest data, no restaurant branding, no affiliation with or integration into any reservation platform, no deployment. All guest text is treated as untrusted data and never as instructions.

License: MIT.

## Legacy interface

The previous Streamlit UI remains available for comparison and recovery:

```bash
python -m pip install -c constraints-tested.txt -e ".[legacy]"
python -m streamlit run streamlit_app.py
```

Use `python app.py` for the new interface. Do not run `streamlit run app.py`. Both interfaces use the same configured database, so run one interface at a time during normal use.

The server binds to `127.0.0.1:8080`. `RW_PORT` can change the port. This remains a local single-operator prototype, with no login, role permissions or production deployment configuration.
