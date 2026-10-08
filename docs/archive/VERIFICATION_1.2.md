# Verification — version 1.2

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.

Current checks ran on Linux with Python 3.12.14. Exact package versions are in `results/verification/environment.json`; `constraints-tested.txt` pins the directly used packages for reproduction. Original-release verification is retained in `archive/VERIFICATION_1.0.md` and is not a current test report.

## Reproduce

```bash
python -m venv .venv
source .venv/bin/activate
pip install -c constraints-tested.txt -e '.[dev]'
python -m pytest -o addopts='' -q
rw eval validate
rw eval run --split heldout --mode offline --retest '1.2 UI and response-state regression replay'
python scripts/run_refinement_challenge.py --out results/challenge-replay
python scripts/run_worked_examples.py
python -m playwright install chromium
python scripts/capture_clean.py
```

The supplemental challenge refuses to overwrite its saved first-pass results. The screenshot script creates disposable databases and closes its server when finished. Set `RW_CHROMIUM` when using an existing Chromium executable.

Editable installation was also checked with `pip install --no-deps --no-build-isolation -e .` against the installed dependencies. A separate clean environment dependency download was not repeated in this revision.

## Results

- **123 tests passed**: original service/rule/provider/evaluation acceptance checks plus refinement regression, UI interaction and six additional progress/clearing/read-receipt tests. Exact test output: `results/verification/pytest.txt`.
- The UI journey selects seating, confirms a simulated booking, prepares a reply, edits it, navigates away/back without losing the edit, saves/reviews it and records the exact reported outgoing message. An AppTest verifies updated details invalidate a selected plan. The real Chromium journey separately edits party size through the actual dialog, checks the stale-plan warning, selects again, confirms, reviews and records the reply as sent.
- Frozen 40-case offline regression: 39/40 expected next actions, 97/97 field agreement, 20/20 required constraints, 0 critical-error cases. Previously inspected cases, not blind.
- New 12-case development-authored extraction challenge: 31/32 fields, 6/6 unknowns preserved; one conservatively reviewed access-negation phrase. No next-action accuracy measured in this set.
- Three replayable worked examples cover a normal booking, accessibility/alternative-time resolution with reported outgoing history, and modification/cancellation.
- Actual Chromium screenshots at 1440, 820 and 390 pixels are in `screenshots/clean/`. The screenshot script asserts no Streamlit exception and exercises a real confirmation/reply/handoff journey.

## Visual checks

| Capture | What it demonstrates |
|---|---|
| `01-inbox.png` | Focused inquiry entry and compact queue |
| `02-plan.png`, `04-selected.png` | Conversation alongside the next seating decision |
| `03-edit.png` | Grouped reservation editor with explicit unknown controls |
| `05-reply.png`, `06-reviewed.png` | Draft and reviewed handoff states |
| `07-complete.png` | Reported sending closes into a completion record |
| `08-service.png`, `09-timeline.png` | Arrival briefs and secondary occupancy timeline |
| `10-workspace-820.png`, `10-workspace-390.png` | Action-first stacked layout without document overflow |

These are unedited application captures. Automated checks verified document widths at 820 and 390 pixels. This is not a formal accessibility or mobile-device audit. Older screenshot folders remain historical evidence. Clipboard support depends on browser permissions; downloadable text is available as a fallback.

## Unverified boundaries

The live provider has fake-client tests, but no real API run occurred. No handling-time sessions or independent label review occurred. Browser coverage is Chromium; Windows/macOS installations, real mobile devices and screen readers were not tested. No production service or external integration was deployed. The 2024/2025 provenance dates do not date these tests.
