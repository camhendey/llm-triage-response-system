# Verification · version 2.1

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
