# Operator handling-time study protocol

Status: **ready to run; no sessions recorded.** No handling-time results exist and none are reported.

## Design

- 12 cases (`data/study/cases.yaml`), drawn from the development split, never the held-out split.
- 3 methods per case, 36 sessions in total:
  1. **Template-only**: synthetic templates ([METHOD_TEMPLATE_ONLY.md](METHOD_TEMPLATE_ONLY.md)) plus manual inspection of the printed [availability sheet](AVAILABILITY_SHEET.md).
  2. **Reconstructed structured-LLM workflow**: a general chat LLM used with the reconstructed prompt in [METHOD_STRUCTURED_LLM.md](METHOD_STRUCTURED_LLM.md), with manual availability checks and booking-note updates.
  3. **Workbench**: this application, demo database, same information.
- Order: the six permutations of the three methods are each assigned to two cases. Sessions run in three rounds; within a round cases are shuffled with a fixed seed, so a case is never handled twice in a row. `rw study plan` writes `results/study/study_plan.csv`.
- Every method receives identical information: the guest messages of the referenced scenario and the same availability sheet.

## Timing boundaries

- **Start**: when the operator first opens the case.
- **Stop**: when the required simulated booking action and booking notes are recorded **and** a reviewed initial guest response is ready (not sent).
- **Pause/Resume**: interruptions unrelated to the task. Paused time is excluded from active time.
- **Model wait**: time spent waiting for an LLM response (method 2, and method 3 in live mode). It is logged separately and is *included* in active time; API latency is never substituted for handling time.
- Durations come only from timer events recorded in the Operator study view (`data/study/study_sessions.sqlite`).

## Completion checklist (all methods)

1. All guest facts captured; unknowns marked unknown, not guessed.
2. Simulated availability checked for the requested time (or alternatives).
3. Applicable policies checked: gratuity, accessibility, minimum spend, allergies.
4. Required simulated booking action recorded (hold, confirm, change or none) with notes.
5. Booking notes updated in the standard format.
6. Initial guest response drafted and reviewed (not sent).

Also record corrections made, errors found afterwards against the case's expected outcome, incomplete requirements, familiarity with the case, and the path to the saved notes/response for the session.

## Analysis (after real sessions only)

- Report every individual observation, then median and range per method, and error counts.
- `rw study export` writes `results/study/study_sessions.csv` (editable). `python scripts/make_charts.py` draws the handling-time chart only from completed sessions; with none, it writes a pending status instead of a chart.
- Disclose limitations: a single operator (likely Cameron), familiarity with cases and the tool he designed, practice effects across rounds, synthetic cases. No causal or significance claims from this self-test.
- Cameron's historical ~45-to-5-minute figure is a separate recollection about his past work (see `docs/PROVENANCE.md`); it is not compared with or validated by this study.
