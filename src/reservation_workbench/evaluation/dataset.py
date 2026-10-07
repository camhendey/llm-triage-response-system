"""Load, validate and freeze the synthetic evaluation scenarios."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..domain.models import ENUM_VALUES, FieldName, NextAction

EVAL_DIR = Path(__file__).resolve().parents[3] / "data" / "eval"
SPLIT_FILES = {"development": "scenarios_dev.yaml", "heldout": "scenarios_heldout.yaml"}
FREEZE_FILE = "FREEZE.json"

HELDOUT_GROUPS = {"ordinary": 6, "missing_conflicting": 6, "capacity_accessibility": 6, "overlap_hold_time": 6,
                  "modification_cancellation": 6, "oversized_minspend": 4, "service_allergy": 3,
                  "adversarial_unsupported": 3}
STEP_TYPES = {"msg", "op_set", "propose", "hold", "confirm", "clock"}
SPECIAL = {"unknown", "review", "known"}


class DatasetError(ValueError):
    pass


@dataclass
class Scenario:
    id: str
    split: str
    group: str
    title: str
    clock: datetime
    steps: list[dict[str, Any]]
    expect: dict[str, Any]
    tags: list[str] = field(default_factory=list)
    existing_booking: str | None = None
    setup_bookings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def message_count(self) -> int:
        return sum(1 for s in self.steps if "msg" in s)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_split(split: str, eval_dir: Path = EVAL_DIR) -> list[Scenario]:
    path = eval_dir / SPLIT_FILES[split]
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("split") != split:
        raise DatasetError(f"{path.name}: split field is {raw.get('split')!r}, expected {split!r}")
    default_clock = datetime.fromisoformat(raw["default_clock"])
    out = []
    for r in raw["scenarios"]:
        out.append(Scenario(
            id=r["id"], split=split, group=r["group"], title=r["title"], tags=list(r.get("tags", [])),
            clock=datetime.fromisoformat(r["clock"]) if r.get("clock") else default_clock,
            steps=list(r.get("steps") or []), expect=dict(r.get("expect") or {}),
            existing_booking=r.get("existing_booking"), setup_bookings=list(r.get("setup_bookings") or []),
        ))
    return out


def validate(scenarios: list[Scenario], split: str) -> list[str]:
    """Return a list of problems (empty when the split is well formed)."""
    errs: list[str] = []
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        errs.append("duplicate scenario ids")
    expected_n = 20 if split == "development" else 40
    if len(scenarios) != expected_n:
        errs.append(f"{split}: {len(scenarios)} scenarios, expected {expected_n}")
    if split == "heldout":
        counts: dict[str, int] = {}
        for s in scenarios:
            counts[s.group] = counts.get(s.group, 0) + 1
        if counts != HELDOUT_GROUPS:
            errs.append(f"heldout group counts {counts} != {HELDOUT_GROUPS}")
        multi = sum(1 for s in scenarios if s.message_count >= 2)
        if multi < 20:
            errs.append(f"heldout has {multi} multi-message scenarios, need >= 20")
    fields = {f.value for f in FieldName}
    actions = {a.value for a in NextAction}
    for s in scenarios:
        if s.clock.tzinfo is None:
            errs.append(f"{s.id}: clock lacks offset")
        for st in s.steps:
            if len(st) == 0 or not (set(st) - {"at"}) <= STEP_TYPES:
                errs.append(f"{s.id}: bad step {st}")
        exp = s.expect
        for f, v in (exp.get("fields") or {}).items():
            if f not in fields:
                errs.append(f"{s.id}: unknown field {f}")
            elif isinstance(v, str) and f in ENUM_VALUES and v not in SPECIAL and not v.startswith("contains:") \
                    and v not in ENUM_VALUES[f]:
                errs.append(f"{s.id}: {f}={v!r} is not a valid enum value")
        for f in (exp.get("provenance") or {}):
            if f not in fields:
                errs.append(f"{s.id}: provenance for unknown field {f}")
        for a in exp.get("next") or []:
            if a not in actions:
                errs.append(f"{s.id}: unknown next action {a}")
        if s.message_count == 0 and not s.existing_booking:
            errs.append(f"{s.id}: no messages and no existing booking")
    return errs


def freeze(eval_dir: Path = EVAL_DIR) -> dict[str, Any]:
    """Record the hash of both split files. Refuses to overwrite an existing freeze."""
    target = eval_dir / FREEZE_FILE
    if target.exists():
        raise DatasetError(f"{target} already exists; the split is frozen. Changing it makes later runs retests.")
    problems = []
    for split in SPLIT_FILES:
        problems += validate(load_split(split, eval_dir), split)
    if problems:
        raise DatasetError("cannot freeze an invalid dataset: " + "; ".join(problems))
    rec = {
        "frozen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": {SPLIT_FILES[s]: file_hash(eval_dir / SPLIT_FILES[s]) for s in SPLIT_FILES},
        "note": "Frozen before the first held-out run (the development split was run beforehand to debug the runner). Labels produced within the same development process as the "
                "workbench; no independent review yet.",
    }
    target.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return rec


def check_frozen(split: str, eval_dir: Path = EVAL_DIR) -> tuple[bool, str]:
    target = eval_dir / FREEZE_FILE
    if not target.exists():
        return False, "dataset not frozen (run `rw eval freeze`)"
    rec = json.loads(target.read_text(encoding="utf-8"))
    name = SPLIT_FILES[split]
    actual = file_hash(eval_dir / name)
    if rec["files"].get(name) != actual:
        return False, f"{name} hash {actual[:12]} differs from frozen {str(rec['files'].get(name))[:12]}"
    return True, f"{name} matches frozen hash {actual[:12]}"
