"""Run the frozen refinement challenge without modifying the original held-out split."""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from reservation_workbench.domain.config import load_config
from reservation_workbench.evaluation.dataset import Scenario
from reservation_workbench.evaluation.runner import (
    run_case,
    summarize,
    write_run,
    environment,
)
from reservation_workbench.providers.offline import OfflineRulesProvider

root = Path(__file__).resolve().parents[1]
p = root / "data/eval/refinement_challenge.json"
expected = (p.with_suffix(".sha256")).read_text().split()[0]
assert hashlib.sha256(p.read_bytes()).hexdigest() == expected, (
    "Challenge labels changed"
)
d = json.loads(p.read_text())
provider = OfflineRulesProvider()
cfg = load_config()
results = []
for c in d["cases"]:
    sc = Scenario(
        id=c["id"],
        split="challenge",
        group="refinement",
        title=c["title"],
        clock=datetime.fromisoformat(d["clock"]),
        steps=[{"msg": m} for m in c["messages"]],
        expect={"fields": c["fields"]},
    )
    results.append(run_case(sc, provider, "offline", cfg, 0))
summary = summarize(results)
parser = argparse.ArgumentParser()
parser.add_argument("--out", type=Path, default=root / "results/refinement-challenge")
out = parser.parse_args().out
if out.exists():
    raise SystemExit(
        "Refusing to overwrite first challenge run; choose a new explicit output path for retests."
    )
meta = {
    "run_id": "refinement-challenge-first-pass",
    "split": "challenge",
    "mode": "offline",
    "repeats": 1,
    "started_at": datetime.now().astimezone().isoformat(),
    "duration_s": None,
    "frozen_check": expected,
    "retest_note": "First execution of development-authored supplemental cases; not independent or a replacement for the original blind run.",
    "environment": environment("offline", provider),
    "cost": "No API calls",
}
write_run(out, meta, results, summary)
print(json.dumps(summary, indent=2))
