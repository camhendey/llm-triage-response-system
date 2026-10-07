# Verification record

Run date: **2026-10-07** (UTC), Linux x86_64, Python 3.13.16. Package versions from the clean install: streamlit 1.65.0, pydantic 2.13.5, anthropic 1.11.0, PyYAML 6.0.3, python-dotenv 1.2.4, tzdata 2026.5, pytest 9.1.1, matplotlib 3.11.2, pillow 12.3.0, playwright 1.63.0. Provider mode for every check below: **offline** (`offline_rules`); `ANTHROPIC_API_KEY` was not set.

## 1. Clean install

From `git archive HEAD` extracted into an empty directory (no `.venv`, no databases, no `.env`):

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"            # 40 s
.venv/bin/python -m pytest -o addopts="" -q  # 102 passed in 3.77 s (re-run on the release commit)
.venv/bin/rw eval validate                   # dev 20, held-out 40 (22 multi-message), both match frozen hashes
.venv/bin/rw init-demo                       # Demo database ready (11 inquiries)
.venv/bin/rw reset-demo --path /tmp/not-the-demo.sqlite   # REFUSED, exit code 2
.venv/bin/rw reset-demo                      # Demo database reset
.venv/bin/rw eval run --split heldout --mode offline --retest "clean-install check"   # 37/40 next action, 0 critical
.venv/bin/rw eval live --max-calls 10 --budget-usd 1 --usd-per-mtok-input 1 --usd-per-mtok-output 1
                                             # live evaluation not_run: ANTHROPIC_API_KEY is not set
.venv/bin/rw study status                    # pending - no real sessions recorded, 0/36
.venv/bin/streamlit run app.py --server.port 8611   # /_stcore/health -> ok
```

Result: **pass**. The clean tree contains no SQLite files and no `.env`; demo databases are created on first run.

## 2. Automated tests

`pytest`: **102 passed, 0 failed, 0 skipped** (3.7-3.9 s).

| File | Scope |
|---|---|
| `tests/test_rules.py` | Config validation, availability engine (capacity, access, overlap, groupings, buffer, noon and DST intervals, hours, hold expiry, ranking, arrival heuristic, access conflicts, table preference) |
| `tests/test_workflow.py` | End-to-end service behaviour over real SQLite: A01-A04 (weekday-only dates, weekday/date mismatch, relative dates across DST), A09-A15, A18, A19, A21, A23-A25, A27, A29, stale views, illegal transitions, short-notice holds, demo clock, input limits, offer drafts |
| `tests/test_providers.py` | Offline interpreter (party-size regressions, subgroup counts, unsupported and partial text), evidence validation and live provider with a fake client: fenced JSON, invalid output then retry, repair, timeouts, rate limits, auth errors, refusal, empty and truncated output, missing key, prose validation (A19, A20, A22, A26, A30) |
| `tests/test_evaluation_and_study.py` | Dataset shape and freeze, field matching, critical-error scoring, live budget guard, A28 not_run, study plan counterbalancing, timer durations |
| `tests/test_ui_apptest.py` | Headless Streamlit runs of `app.py` (marker `ui`): all four views render without an exception; opening INQ-0103 shows its next action and no external-system mention |

The live provider is tested only against a fake client. **No call to the real API was made.**

## 3. Rendered UI

Real captures of the running app with Playwright and Chromium against a freshly reset demo database: `streamlit run app.py --server.port 8599`, then `python scripts/capture_screenshots.py --out docs/screenshots`.

| Screenshot | Width | Checked |
|---|---|---|
| `01_queue_desktop.png`, `01_queue_narrow.png` | 1440, 820 | queue cards, filters, sidebar, banner |
| `02_conflict_workspace_desktop.png`, `..._narrow.png` | 1440, 820 | INQ-0103: blocker with rule ID, alternatives, highlighted evidence, facts table wraps without overlap |
| `03_seating_desktop.png`, `..._narrow.png` | 1440, 820 | ranked options, rejected reasons, proposal and decision panels |
| `04_facts_provenance_desktop.png` | 1440 | fact statuses and quoted sources |
| `05_draft_desktop.png` | 1440 | generated draft, validator result, copy panel, booking notes |
| `06_history_desktop.png` | 1440 | event history |
| `07_service_view_desktop.png` | 1440 | occupancy grid (confirmed vs demo hold) and labelled arrival heuristic |
| `08_policies_desktop.png` | 1440 | policy values from config |
| `09_operator_study_desktop.png` | 1440 | study status 0/36, timer buttons enabled per state |
| `10a/10b/10c_correction_*.png` | crop | approve P-0001 for v2, operator sets party size 9, P-0001 stale and commit blocked, P-0002 approved for v3 |

Issues found and fixed while inspecting captures: facts table rendering blank (replaced with HTML table), facts column too narrow at 820 px (wrapping rule), study timer labels truncated (two rows), booking-note separators wrapping (shortened). Remaining: at 820 px the layout stacks into one long column, so the narrow captures are tall; that is intended, not verified on a real phone.

Figures composed from these captures: `python scripts/compose_figures.py` (outlines and captions only; element boxes recorded by Playwright in `02_conflict_workspace_desktop.boxes.json`).

## 4. Worked examples

`python scripts/run_worked_examples.py` replays three scenarios through the service layer on in-memory databases and writes `examples/01_normal_booking`, `02_accessibility_conflict`, `03_booking_change_and_cancel`. Each refused step in the logs is an intended refusal (double approval, stairs-only table for a wheelchair user, occupied table L1, recommit of a committed change). Re-running produces the same decisions; only random interpretation IDs differ.

## 5. Evaluation runs

See [EVALUATION.md](EVALUATION.md). Final: `results/eval/20261007T002542-heldout-offline` at commit `d06cbee` (clean), 37/40 next action, 97/97 fields, 20/20 constraint recall, 0 critical-error cases, 0 prohibited draft claims. Live: `results/eval/live_status.json`, `not_run`.

## 6. Charts and diagrams

| Output | Input | Command |
|---|---|---|
| `docs/figures/evaluation_reliability.png/.svg` | `results/eval/20261006T235717-heldout-offline`, `20261007T002542-heldout-offline`, `20261007T002543-heldout-oracle` `summary.json` | `python scripts/make_charts.py` |
| `docs/figures/constraint_resolution.png/.svg` | `examples/02_accessibility_conflict/snapshots.json` | same |
| `docs/figures/handling_time_status.json` (pending, no chart) | study database (0 completed sessions) | same |
| `docs/figures/annotated_overview.png`, `correction_sequence.png` | `docs/screenshots/` | `python scripts/compose_figures.py` |
| `docs/diagrams/*.svg/.png` | `docs/diagrams/*.mmd` | `python scripts/render_diagrams.py --mermaid-js <path to mermaid.min.js>` (Mermaid 11.17.2, Chromium) |

Chart palette checked with a colour-vision validator; the green series is below 3:1 contrast on white, so every bar carries a direct text label.

## 7. Release package checks

- `git ls-files` contains no `.sqlite`, no `.env`, and no historical reference documents.
- Email addresses in tracked files: only `@example.com` / `@example.org`.
- No string matching an API key pattern.
- The name of the historical employer does not appear. The only mentions of the external reservation platform are the validator that forbids it in drafts, the evaluation's prohibited-claim list and a UI test that asserts it is absent.

## Not verified

| Check | Status |
|---|---|
| Live model extraction and prose | **not_run** (no key or budget) |
| Human handling-time study | **pending** (0/36 sessions) |
| Independent review of scenario labels | not done |
| Browsers other than Chromium; real mobile devices | not done |
| Screen-reader or formal accessibility audit of the UI | not done |
| Install on Windows or macOS | not done (Linux only) |
| Review of the UI by Cameron or another operator | not done |
