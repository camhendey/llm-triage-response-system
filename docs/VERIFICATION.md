# Verification: version 2.0 (NiceGUI)

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.

Checks ran on Linux with Python 3.12.14. `results/verification/environment.json` records the actual installed package versions. `constraints-tested.txt` pins direct packages used for reproduction. Earlier verification reports are retained under `docs/archive/`.

## Reproduce

```bash
python -m pip install -c constraints-tested.txt -e '.[dev]'
python -m pytest -o addopts='' -q
python -m playwright install chromium --only-shell
python scripts/capture_nicegui.py
python scripts/verify_nicegui_workflows.py
python -m reservation_workbench.cli eval validate
python -m reservation_workbench.cli eval run --split heldout --mode offline --retest '2.0 NiceGUI migration regression'
```

Set `RW_CHROMIUM` to an existing Chromium executable if needed. Both browser scripts create disposable booking/session/study databases and stop their temporary servers. They use ports 8623 and 8624. Screenshot captures are unedited application output.

## Results

- **129 automated tests passed.** The original 123 checks remain, including the optional legacy Streamlit AppTests. Six new tests cover stale record rejection, transactional rollback, idempotent retries, draft changes without record-version increments, connection/database separation and blank environment-path defaults.
- The NiceGUI screenshot journey edits a selected reservation, verifies plan invalidation, selects again, confirms, generates and edits a reply, preserves unsaved text across navigation, saves/reviews, checks actual clipboard contents and records reported sending. It visits Service, Timeline, Project and Settings, then checks widths of 820 and 390 pixels for document overflow.
- The additional browser journey creates an inquiry, holds and confirms it, verifies independent unsaved buffers in two browser pages, rejects a stale save, invalidates a reviewed reply after a new message, records cancellation, imports CSV and exercises the study timer.
- The inspected 40-case offline regression remains 39/40 allowed next actions, 97/97 labelled fields, 20/20 required constraints and zero critical-error cases. It is a retest, not an independent blind benchmark.
- The previously recorded 12-case challenge remains historical evidence: 31/32 field matches, 6/6 unknowns preserved. It is not relabelled as new migration validation.

Exact outputs are saved under `results/verification/`. Current captures are under `docs/screenshots/nicegui/`. The `clean/`, `refined/` and original screenshot folders describe earlier interfaces.

## Boundaries

No live API calls, human usability/timing sessions, external booking integration or deployment occurred. Browser checks use desktop Chromium, including resized viewports; physical phones, screen readers and Windows/macOS installations were not tested. The UI binds locally by default and has no authentication. The unchanged schema permits existing databases, but no user-owned Windows database was accessed during this work.
