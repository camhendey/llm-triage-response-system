# Verification · version 3.0

## Current release

`python scripts/run_release_checks.py` captures actual outputs and environment metadata under `results/verification/`. Current suite: **198 passing tests**, including 45 coordinator cases and all 153 retained regressions.

The coordinator browser journey verifies shift setup, Settings forms, CSV mapping/preview/apply, reload persistence, intake, confirmed visit facts, conditional availability, external verification, blocked premature confirmation, call acceptance, draft recovery, review, real clipboard contents, reported sending, staff review, 820/390 px layouts and shift end. Data are synthetic; screenshots under `docs/screenshots/coordinator/` are actual browser output at 1440 px plus narrow captures.

The other three browser scripts cover the preserved demo booking, import and screenshot journeys. Exact outputs: `coordinator-browser.txt`, `nicegui-workflows.txt`, `opentable-browser.txt`, `nicegui-browser.txt`, `pytest.txt` and `environment.json`. The runner stops on failure; run dates are actual execution dates.

New tests cover stale tabs/operators, atomic rollback, independent completion gates, change invalidation, no-answer follow-ups, quoted acceptance, separate policy thresholds, photos/attachments, unique references, cancellation matching, hold expiry, conservative snapshot assumptions, reconciliation, expiry/venue identity, draft isolation, before/after audits and scoped closed-case deletion.

Limits: synthetic fixtures, Chromium only, no live-model run, no current authenticated dashboard-export certification, no production pilot, no controlled human study and no formal accessibility audit. External actions are operator attestations, not API receipts. The old 39/40 demo retest is not a new v3 benchmark.

## Historical version 2.1 verification

The sections below describe the previous release. Per-page imports remain in `/demo`; coordinator imports now persist for the shift. The prior document is also retained in `docs/archive/VERIFICATION_2.1.md`.

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025. Software checks below were run in October 2026, not during the original manual workflow.

## Reproduce

```bash
python -m pip install -c constraints-tested.txt -e '.[dev]'
python -m pytest -o addopts='' -q
python -m playwright install chromium --only-shell
python scripts/verify_opentable_import.py
python scripts/verify_nicegui_workflows.py
python scripts/capture_nicegui.py
```

Browser scripts launch their own server and temporary databases, on ports 8625, 8624 and 8623 respectively. `RW_CHROMIUM` can point to an existing Chromium executable.

## Results

- **153 automated tests pass**, including the previous 129 and 24 import contract cases. Import tests exercise BOM, comma/semicolon/tab separators, quoted and multiline UTF-8 notes, date order, DST, explicit offsets, invalid rows, coverage, duplicate IDs, multi-restaurant rejection, header/shape failures, conservative status handling, shared contacts, freshness and mapping validation.
- The OpenTable browser journey uses labelled illustrative CSVs: initial setup, rejected empty report, reservations upload, optional guestbook, reviewed preview, replacement without append, date-scoped totals, shared-email candidate records, page isolation, reload reset, mobile setup/mapping and explicit demo continuation. No browser errors or server tracebacks.
- The existing booking workflow browser test passes: creation, hold, confirmation, independent draft buffers, stale-tab rejection, new-message draft invalidation, cancellation, guest-message CSV import and study timer.
- The existing screenshot journey passes: selected-plan edits, booking/reply workflow, real clipboard contents, Service/Timeline/Project/Settings and document overflow checks at 820 and 390 pixels.

Exact outputs: `results/verification/pytest.txt`, `opentable-browser.txt`, `nicegui-workflows.txt`, `nicegui-browser.txt`. Screenshots are unedited browser output under `docs/screenshots/opentable/` and `docs/screenshots/nicegui/`.

The previous 39/40 next-action regression and challenge results remain historical evidence from inspected synthetic cases. They were not rerun or relabelled as new import benchmarks. Prior verification reports are retained in `docs/archive/`.

## Limits

No genuine recent dashboard export was available for compatibility testing. No live provider, OpenTable account, human timing/usability study, Windows installation, physical phone or screen-reader test was performed. This is a read-only CSV/TSV workflow, not booking-system synchronization. No real restaurant data or runtime databases are packaged.
