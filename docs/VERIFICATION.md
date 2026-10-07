# Verification — version 1.1

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.

Current checks ran on Linux with Python 3.12.14. Exact package versions are in `results/verification/environment.json`; `constraints-tested.txt` pins the directly used packages for reproduction. Original-release verification is retained in `archive/VERIFICATION_1.0.md` and is not a current test report.

## Reproduce

```bash
python -m venv .venv
source .venv/bin/activate
pip install -c constraints-tested.txt -e '.[dev]'
python -m pytest -o addopts='' -q
rw eval validate
rw eval run --split heldout --mode offline --retest '1.1 regression replay'
python scripts/run_refinement_challenge.py --out results/challenge-replay
python scripts/run_worked_examples.py
python -m playwright install chromium
python scripts/capture_refined.py
```

The supplemental challenge refuses to overwrite its saved first-pass results. The screenshot script creates disposable databases and closes its server when finished. Set `RW_CHROMIUM` when using an existing Chromium executable.

Editable installation was also checked with `pip install --no-deps --no-build-isolation -e .` against the installed dependencies. A separate clean environment dependency download was not repeated in this revision.

## Results

- **117 tests passed**: original service/rule/provider/evaluation acceptance checks plus 13 refinement regression tests and 2 additional UI interaction tests. Exact test output: `results/verification/pytest.txt`.
- The UI journey selects seating, confirms a simulated booking, prepares a reply, edits it, navigates away/back without losing the edit, saves/reviews it and records the exact reported outgoing message. A second UI test edits party size through the typed form and verifies the selected plan becomes stale.
- Frozen 40-case offline regression: 39/40 expected next actions, 97/97 field agreement, 20/20 required constraints, 0 critical-error cases. Previously inspected cases, not blind.
- New 12-case development-authored extraction challenge: 31/32 fields, 6/6 unknowns preserved; one conservatively reviewed access-negation phrase. No next-action accuracy measured in this set.
- Three replayable worked examples cover a normal booking, accessibility/alternative-time resolution with reported outgoing history, and modification/cancellation.
- Actual Chromium screenshots at 1440 and 820 pixels are in `screenshots/refined/`. The screenshot script asserts no Streamlit exception and exercises a real confirmation/reply/handoff journey.

## Visual checks

| Capture | What it demonstrates |
|---|---|
| `01-overview.png` | Authorship, scenario entry points and queue |
| `02-seating.png` | Selected option and configuration-derived table schematic |
| `03-reply.png` | Confirmed booking and one editable, record-grounded reply |
| `04-conversation.png` | Reported outgoing message alongside inbound guest content |
| `05-service.png` | Occupancy, arrival heuristic and daily handoff export |
| `06-narrow.png` | Stacked workflow at 820 px; text wraps within available space |

These are unedited captures, not renderings of an imagined interface. This is visual inspection, not a formal accessibility or mobile-device audit. Original screenshot/composite files outside `refined/` show release 1.0.

## Unverified boundaries

The live provider has fake-client tests, but no real API run occurred. No handling-time sessions or independent label review occurred. Browser coverage is Chromium; Windows/macOS installations, real mobile devices and screen readers were not tested. No production service or external integration was deployed. The 2024/2025 provenance dates do not date these tests.
