"""Replay scenarios through the real services and score the outcome.

Modes
  offline  - OfflineRulesProvider interprets messages (deterministic, no network).
  oracle   - offline interpretation, then every labelled literal field the interpreter got wrong is
             corrected through the operator path (set_fact). Measures the rules/next-action engine
             given correct facts; it is NOT an interpreter score.
  live     - AnthropicLiveProvider; refuses to start without a key, a call cap and a dollar budget
             with explicit token rates. Otherwise the run is recorded as not_run.

Gold labels are read only by the scorer. Providers receive guest messages and nothing else.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import platform
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..domain.clock import FixedClock
from ..domain.config import RestaurantConfig, config_hash, load_config
from ..domain.models import Booking, BookingStatus, FieldName, NextAction, ProposalStatus
from ..persistence.db import Database
from ..providers.offline import OfflineRulesProvider
from ..services.bootstrap import seed_bookings_only
from ..services.drafting import resolve_purpose
from ..services.workbench import Workbench
from .dataset import SPLIT_FILES, Scenario, check_frozen, file_hash, load_split, EVAL_DIR

RESULTS_DIR = Path(__file__).resolve().parents[3] / "results" / "eval"
CRITICAL_FIELDS = (FieldName.PARTY_SIZE, FieldName.REQUESTED_DATE, FieldName.REQUESTED_TIME,
                   FieldName.ACCESSIBILITY, FieldName.ALLERGIES)
COMMIT_ACTIONS = {NextAction.CREATE_HOLD.value, NextAction.CONFIRM_BOOKING.value,
                  NextAction.PROCESS_MODIFICATION.value}
GLOBAL_PROHIBITED = ["opentable", "we have sent", "has been sent", "guaranteed"]


# ---------------------------------------------------------------------------- scoring helpers
def field_matches(expected: Any, state: str, value: Any) -> bool:
    if expected == "unknown":
        return state == "unknown"
    if expected == "review":
        return state in ("needs_review", "conflict")
    if state != "known":
        return False
    if expected == "known":
        return True
    if isinstance(expected, str) and expected.startswith("contains:"):
        return expected[9:].lower() in str(value).lower()
    if isinstance(expected, str) or isinstance(value, str):
        return str(expected).strip().lower() == str(value).strip().lower()
    return expected == value


def is_silent_guess(expected: Any, state: str, value: Any) -> bool:
    """A known value that contradicts the label (wrong value, or a guess where the label says unknown/review)."""
    return state == "known" and not field_matches(expected, state, value) and expected != "known"


@dataclass
class CaseResult:
    scenario_id: str
    split: str
    group: str
    repeat: int
    mode: str
    status: str = "ok"  # ok | error | not_run_budget
    error: str | None = None
    provider_statuses: list[str] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    interpret_latency_ms: list[int] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    provider_calls: int = 0
    step_results: list[dict[str, Any]] = field(default_factory=list)
    oracle_corrections: list[str] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    next_action: str | None = None
    next_ok: bool | None = None
    rules_raised: list[str] = field(default_factory=list)
    rules_required_missing: list[str] = field(default_factory=list)
    rules_required_n: int = 0
    false_warnings: list[str] = field(default_factory=list)
    booking_checks: list[dict[str, Any]] = field(default_factory=list)
    event_checks: list[dict[str, Any]] = field(default_factory=list)
    draft_purpose: str | None = None
    draft_text: str | None = None
    draft_validation_errors: list[str] = field(default_factory=list)
    prohibited_found: list[str] = field(default_factory=list)
    critical: list[str] = field(default_factory=list)
    raw_outputs: list[str | None] = field(default_factory=list)


def _insert_setup_booking(wb: Workbench, spec: dict[str, Any], at: datetime) -> None:
    start = datetime.fromisoformat(spec["start"])
    end = start + timedelta(minutes=int(spec["minutes"]))
    exp = datetime.fromisoformat(spec["expires_at"]).astimezone(UTC) if spec.get("expires_at") else None
    wb.repo.insert_booking(Booking(
        id=spec["id"], inquiry_id=None, guest_label=f"Eval setup {spec['id']}", status=BookingStatus(spec["status"]),
        table_ids=list(spec["tables"]), party_size=int(spec["party"]), start=start.astimezone(UTC),
        end=end.astimezone(UTC), hold_expires_at=exp, source="eval_setup", created_at=at, updated_at=at))


def _counter():
    c = itertools.count()
    return lambda tag: f"eval:{tag}:{next(c)}"


def run_case(sc: Scenario, provider, mode: str, cfg: RestaurantConfig, repeat: int = 0,
             call_guard=None) -> CaseResult:
    res = CaseResult(sc.id, sc.split, sc.group, repeat, mode)
    key = _counter()
    clock = FixedClock(sc.clock)
    wb = Workbench(Database.open(":memory:"), cfg, clock, provider, mode="eval")
    seed_bookings_only(wb)
    with wb.db.transaction():
        for b in sc.setup_bookings:
            _insert_setup_booking(wb, b, sc.clock)
    wb.reconcile()
    iid = f"INQ-{sc.existing_booking}" if sc.existing_booking else None
    n_msgs = sc.message_count
    msg_i = 0
    try:
        for st in sc.steps:
            if "msg" in st:
                msg_i += 1
                at = datetime.fromisoformat(st["at"]) if st.get("at") else sc.clock - timedelta(minutes=2 * (n_msgs - msg_i))
                if iid is None:
                    r = wb.create_inquiry(f"Eval guest {sc.id}", st["msg"], at, key=key("create"))
                    iid = r.data.get("inquiry_id") if r.ok else None
                else:
                    r = wb.add_message(iid, st["msg"], at, key=key("msg"))
                res.step_results.append({"step": "msg", "ok": r.ok, "message": r.message})
                if not r.ok or iid is None:
                    raise RuntimeError(f"message step failed: {r.message}")
                if call_guard is not None and not call_guard():
                    res.status = "not_run_budget"
                    return res
                t0 = time.perf_counter()
                ir = wb.interpret(iid, key=key("interpret"))
                res.interpret_latency_ms.append(int((time.perf_counter() - t0) * 1000))
                last = wb.repo.interpretations(iid)[-1] if wb.repo.interpretations(iid) else None
                if last is not None:
                    res.provider_statuses.append(last.status)
                    if last.error:
                        res.provider_errors.append(last.error)
                    res.raw_outputs.append(last.raw_output)
                    for k2 in ("input_tokens", "output_tokens"):
                        if isinstance(last.usage.get(k2), int):
                            res.usage[k2] = res.usage.get(k2, 0) + last.usage[k2]
                    res.provider_calls += int(last.usage.get("attempts", 0) or 0)
                elif not ir.ok:
                    res.provider_statuses.append("failed")
                    res.provider_errors.append(ir.message)
            elif "op_set" in st:
                o = st["op_set"]
                r = wb.set_fact(iid, o["field"], o["value"], o.get("reason", "eval operator step"), key("set"))
                res.step_results.append({"step": "op_set", "ok": r.ok, "message": r.message})
            elif "propose" in st:
                o = st["propose"] or {}
                r = wb.propose(iid, key("propose"), unit_id=o.get("unit"))
                ok = r.ok
                if r.ok:
                    a = wb.approve_proposal(r.data["proposal_id"], key("approve"))
                    ok = a.ok
                res.step_results.append({"step": "propose", "ok": ok, "message": r.message})
            elif "hold" in st:
                v = wb.load(iid)
                p = next((p for p in reversed(v.proposals) if p.status == ProposalStatus.APPROVED), None)
                r = wb.create_hold(p.id, key("hold")) if p else None
                res.step_results.append({"step": "hold", "ok": bool(r and r.ok),
                                         "message": r.message if r else "no approved proposal"})
            elif "confirm" in st:
                r = wb.confirm(iid, key("confirm"))
                res.step_results.append({"step": "confirm", "ok": r.ok, "message": r.message})
            elif "clock" in st:
                r = wb.set_demo_clock(datetime.fromisoformat(st["clock"]), key("clock"))
                res.step_results.append({"step": "clock", "ok": r.ok, "message": r.message})
        exp = sc.expect
        if mode == "oracle" and iid is not None:
            v = wb.load(iid)
            for fname, want in (exp.get("fields") or {}).items():
                if want in ("unknown", "review", "known") or (isinstance(want, str) and want.startswith("contains:")):
                    continue
                fv = v.facts.get(FieldName(fname))
                if not field_matches(want, fv.state, fv.value):
                    r = wb.set_fact(iid, fname, want, "oracle correction (evaluation only)", key("oracle"))
                    res.oracle_corrections.append(f"{fname}: {fv.value!r} -> {want!r} ({'ok' if r.ok else r.message})")
        wb.reconcile()
        wb.reconcile()  # second pass must not duplicate expiry events
        _score(sc, wb, iid, res, key)
    except Exception as exc:  # recorded, never hidden
        res.status = "error"
        res.error = f"{type(exc).__name__}: {exc}"
        res.critical.append("run_error")
    return res


def _score(sc: Scenario, wb: Workbench, iid: str | None, res: CaseResult, key) -> None:
    exp = sc.expect
    v = wb.load(iid) if iid else None
    if v is not None:
        msgs = [m for m in v.messages if m.source.value != "seed"]
        msg_index = {m.id: i + 1 for i, m in enumerate(msgs)}
        # ---- fields
        for fname, want in (exp.get("fields") or {}).items():
            fv = v.facts.get(FieldName(fname))
            ok = field_matches(want, fv.state, fv.value)
            res.fields.append({"field": fname, "expected": want, "state": fv.state, "value": fv.value, "match": ok})
            if FieldName(fname) in CRITICAL_FIELDS and is_silent_guess(want, fv.state, fv.value):
                res.critical.append(f"critical_fact:{fname}={fv.value!r} (expected {want!r})")
        # ---- provenance: every accepted guest-message observation must quote its message verbatim
        by_id = {m.id: m for m in v.messages}
        obs = [o for o in wb.repo.observations(iid) if o.source_type == "message"]
        valid = 0
        for o in obs:
            m = by_id.get(o.message_id)
            if m is not None and o.quote and o.quote in m.text and (
                    o.span_start is None or m.text[o.span_start:o.span_end] == o.quote):
                valid += 1
        rejected = sum(len(i.usage.get("rejected_facts", []) or []) for i in wb.repo.interpretations(iid))
        gold = exp.get("provenance") or {}
        gold_hits = 0
        gold_detail = {}
        for fname, idx in gold.items():
            fv = v.facts.get(FieldName(fname))
            cited = msg_index.get(fv.current.message_id) if fv.current is not None and fv.current.source_type == "message" else None
            gold_detail[fname] = {"expected_message": idx, "cited_message": cited}
            gold_hits += int(cited == idx)
        res.provenance = {"accepted": len(obs), "verbatim_valid": valid, "rejected_by_validator": rejected,
                          "gold_n": len(gold), "gold_hits": gold_hits, "gold_detail": gold_detail}
        # ---- next action and rules
        a = v.assessment
        res.next_action = a.next_action.value
        if exp.get("next"):
            res.next_ok = res.next_action in exp["next"]
        res.rules_raised = sorted({r.rule_id for r in a.blockers + a.reviews + a.advisories})
        req = exp.get("rules_required") or []
        res.rules_required_n = len(req)
        res.rules_required_missing = [r for r in req if r not in res.rules_raised]
        for r in exp.get("critical_rules") or []:
            if r not in res.rules_raised:
                res.critical.append(f"missed_rule:{r}")
        res.false_warnings = [r for r in (exp.get("rules_forbidden") or []) if r in res.rules_raised]
        if exp.get("no_commit") and res.next_action in COMMIT_ACTIONS:
            res.critical.append(f"unsafe_commit_recommendation:{res.next_action}")
        # ---- draft
        purpose = resolve_purpose(v)
        if purpose is not None:
            r = wb.generate_draft(iid, key("draft"))
            if r.ok:
                d = wb.repo.get_draft(r.data["draft_id"])
                res.draft_purpose = d.purpose
                res.draft_text = d.text
                res.draft_validation_errors = [x["message"] for x in d.validation if x["severity"] == "error"]
                low = d.text.lower()
                for phrase in list(exp.get("prohibited_claims") or []) + GLOBAL_PROHIBITED:
                    if phrase.lower() in low:
                        res.prohibited_found.append(phrase)
                if res.prohibited_found:
                    res.critical.append("prohibited_claim:" + "|".join(res.prohibited_found))
            else:
                res.draft_validation_errors = [f"draft not generated: {r.message}"]
    # ---- bookings and events
    bexp = exp.get("booking")
    if bexp:
        bid = bexp.get("id") or (v.booking.id if v and v.booking else None)
        b = wb.repo.get_booking(bid) if bid else None
        checks = {}
        if b is None:
            checks["exists"] = False
        else:
            if "status" in bexp:
                checks["status"] = b.status.value == bexp["status"]
            if "tables" in bexp:
                checks["tables"] = sorted(b.table_ids) == sorted(bexp["tables"])
            if "start" in bexp:
                checks["start"] = b.start == datetime.fromisoformat(bexp["start"])
        ok = all(checks.values())
        res.booking_checks.append({"booking": bid, "checks": checks, "ok": ok,
                                   "actual": None if b is None else {"status": b.status.value, "tables": b.table_ids,
                                                                     "start": b.start.isoformat()}})
        if not ok:
            res.critical.append(f"booking_state:{bid}")
    for etype, n in (exp.get("event_counts") or {}).items():
        actual = sum(1 for e in wb.repo.events() if e.event_type == etype)
        res.event_checks.append({"event": etype, "expected": n, "actual": actual, "ok": actual == n})
        if actual != n:
            res.critical.append(f"event_count:{etype}={actual}")


# ---------------------------------------------------------------------------- aggregation
def _ratio(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "d": d, "rate": round(n / d, 4) if d else None}


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    ran = [r for r in results if r.status != "not_run_budget"]
    fields = [f for r in ran for f in r.fields]
    known_exp = [f for f in fields if f["expected"] not in ("unknown", "review")]
    unk_exp = [f for f in fields if f["expected"] == "unknown"]
    rev_exp = [f for f in fields if f["expected"] == "review"]
    nxt = [r for r in ran if r.next_ok is not None]
    prov_acc = sum(r.provenance.get("accepted", 0) for r in ran)
    prov_valid = sum(r.provenance.get("verbatim_valid", 0) for r in ran)
    gold_n = sum(r.provenance.get("gold_n", 0) for r in ran)
    gold_hits = sum(r.provenance.get("gold_hits", 0) for r in ran)
    drafts = [r for r in ran if r.draft_text is not None]
    statuses: dict[str, int] = {}
    for r in ran:
        for s in r.provider_statuses:
            statuses[s] = statuses.get(s, 0) + 1
    lat = [x for r in ran for x in r.interpret_latency_ms]
    by_group: dict[str, dict[str, Any]] = {}
    for r in ran:
        g = by_group.setdefault(r.group, {"cases": 0, "next_ok": 0, "next_scored": 0, "critical_cases": 0})
        g["cases"] += 1
        if r.next_ok is not None:
            g["next_scored"] += 1
            g["next_ok"] += int(r.next_ok)
        g["critical_cases"] += int(bool(r.critical))
    return {
        "cases_total": len(results),
        "cases_run": len(ran),
        "cases_not_run_budget": len(results) - len(ran),
        "run_errors": sum(1 for r in ran if r.status == "error"),
        "field_agreement_all": _ratio(sum(f["match"] for f in fields), len(fields)),
        "field_agreement_known_values": _ratio(sum(f["match"] for f in known_exp), len(known_exp)),
        "unknown_kept_unknown": _ratio(sum(f["match"] for f in unk_exp), len(unk_exp)),
        "ambiguity_sent_to_review": _ratio(sum(f["match"] for f in rev_exp), len(rev_exp)),
        "provenance_verbatim_valid": _ratio(prov_valid, prov_acc),
        "provenance_gold_message_match": _ratio(gold_hits, gold_n),
        "citations_rejected_by_validator": sum(r.provenance.get("rejected_by_validator", 0) for r in ran),
        "next_action_allowed": _ratio(sum(int(r.next_ok) for r in nxt), len(nxt)),
        "required_constraint_recall": _ratio(sum(r.rules_required_n - len(r.rules_required_missing) for r in ran),
                                             sum(r.rules_required_n for r in ran)),
        "false_warnings": sum(len(r.false_warnings) for r in ran),
        "drafts_generated": len(drafts),
        "drafts_with_prohibited_claims": sum(1 for r in drafts if r.prohibited_found),
        "prohibited_claims_total": sum(len(r.prohibited_found) for r in drafts),
        "drafts_with_validator_errors": sum(1 for r in drafts if r.draft_validation_errors),
        "cases_with_critical_errors": sum(1 for r in ran if r.critical),
        "critical_errors_total": sum(len(r.critical) for r in ran),
        "provider_status_counts": statuses,
        "provider_failures": statuses.get("failed", 0),
        "interpret_calls": len(lat),
        "interpret_latency_ms": ({"median": statistics.median(lat), "max": max(lat)} if lat else None),
        "usage_tokens": {k: sum(r.usage.get(k, 0) for r in ran) for k in ("input_tokens", "output_tokens")},
        "by_group": by_group,
    }


# ---------------------------------------------------------------------------- environment + output
def _git_rev() -> str:
    """HEAD commit, with "+uncommitted" when tracked source/config/data files differ from it."""
    root = Path(__file__).resolve().parents[3]
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             cwd=root, timeout=5).stdout.strip()
        if not rev:
            return "unknown (not a git checkout)"
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "config", "data/eval", "data/synthetic"],
                               capture_output=True, text=True, cwd=root, timeout=5).stdout.strip()
        return rev + ("+uncommitted" if dirty else "")
    except Exception:
        return "unknown (not a git checkout)"


def environment(mode: str, provider) -> dict[str, Any]:
    from importlib import metadata

    pkgs = {}
    for p in ("pydantic", "anthropic", "streamlit", "pyyaml"):
        try:
            pkgs[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            pkgs[p] = None
    env: dict[str, Any] = {
        "python": platform.python_version(), "platform": platform.platform(), "packages": pkgs,
        "code_version": _git_rev(), "config_hash": config_hash(), "mode": mode,
        "provider_mode": getattr(provider, "mode", None),
        "dataset_hashes": {n: file_hash(EVAL_DIR / n) for n in SPLIT_FILES.values()},
    }
    if getattr(provider, "mode", "") == "live_anthropic":
        from ..providers.anthropic_live import EXTRACTION_SCHEMA, PROSE_PROMPT, PROSE_SCHEMA, SYSTEM_PROMPT
        env["generation"] = provider.settings.public()
        env["prompt_hash"] = hashlib.sha256((SYSTEM_PROMPT + PROSE_PROMPT + json.dumps(EXTRACTION_SCHEMA, sort_keys=True)
                                             + json.dumps(PROSE_SCHEMA, sort_keys=True)).encode()).hexdigest()[:16]
    else:
        env["generation"] = {"model": "offline-pattern-v1", "note": "deterministic pattern rules, not a language model"}
    return env


def write_run(out_dir: Path, meta: dict[str, Any], results: list[CaseResult], summary: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run.json").write_text(json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    with (out_dir / "cases.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(asdict(r), default=str) + "\n")
    (out_dir / "report.md").write_text(render_report(meta, summary, results), encoding="utf-8")
    return out_dir


def _fmt(r: dict[str, Any]) -> str:
    return f"{r['n']}/{r['d']}" + (f" ({r['rate']:.1%})" if r["rate"] is not None else "")


def render_report(meta: dict[str, Any], s: dict[str, Any], results: list[CaseResult]) -> str:
    lines = [f"# Evaluation run {meta['run_id']}", "",
             f"- Mode: **{meta['mode']}** (provider `{meta['environment']['provider_mode']}`)",
             f"- Split: {meta['split']} · repeats: {meta['repeats']} · frozen check: {meta['frozen_check']}",
             f"- Started: {meta['started_at']} · duration: {meta['duration_s']} s · code {meta['environment']['code_version']}",
             f"- Retest: {meta.get('retest_note') or 'no'}", "",
             "Synthetic scenarios written by the same coding agent that built the system. These are "
             "engineering checks, not an independent benchmark.", "",
             "| Metric | Result |", "|---|---|"]
    rows = [
        ("Cases run / total", f"{s['cases_run']}/{s['cases_total']} (run errors: {s['run_errors']})"),
        ("Field agreement, all labelled fields", _fmt(s["field_agreement_all"])),
        ("Field agreement, labelled known values", _fmt(s["field_agreement_known_values"])),
        ("Unknowns kept unknown", _fmt(s["unknown_kept_unknown"])),
        ("Ambiguities sent to review", _fmt(s["ambiguity_sent_to_review"])),
        ("Provenance: accepted citations quoting their message verbatim", _fmt(s["provenance_verbatim_valid"])),
        ("Provenance: cited message matches labelled message", _fmt(s["provenance_gold_message_match"])),
        ("Citations rejected by evidence validator", str(s["citations_rejected_by_validator"])),
        ("Next action within allowed set", _fmt(s["next_action_allowed"])),
        ("Required-constraint recall", _fmt(s["required_constraint_recall"])),
        ("False warnings (forbidden rules raised)", str(s["false_warnings"])),
        ("Drafts generated", str(s["drafts_generated"])),
        ("Drafts with prohibited claims (total claims)",
         f"{s['drafts_with_prohibited_claims']} ({s['prohibited_claims_total']})"),
        ("Drafts with validator errors", str(s["drafts_with_validator_errors"])),
        ("Cases with critical errors (total)", f"{s['cases_with_critical_errors']} ({s['critical_errors_total']})"),
        ("Provider statuses", json.dumps(s["provider_status_counts"])),
        ("Interpret latency ms (median / max)",
         f"{s['interpret_latency_ms']['median']} / {s['interpret_latency_ms']['max']}" if s["interpret_latency_ms"] else "-"),
        ("Token usage (input / output)", f"{s['usage_tokens']['input_tokens']} / {s['usage_tokens']['output_tokens']}"),
        ("Cost", meta.get("cost", "unknown")),
    ]
    lines += [f"| {a} | {b} |" for a, b in rows]
    lines += ["", "## By group", "", "| Group | Cases | Next action OK | Cases with critical errors |", "|---|---|---|---|"]
    for g, d in sorted(s["by_group"].items()):
        lines.append(f"| {g} | {d['cases']} | {d['next_ok']}/{d['next_scored']} | {d['critical_cases']} |")
    lines += ["", "## Cases needing attention", ""]
    bad = [r for r in results if r.critical or r.next_ok is False or r.rules_required_missing
           or any(not f["match"] for f in r.fields)]
    if not bad:
        lines.append("None.")
    for r in bad:
        miss = [f"{f['field']}: expected {f['expected']!r}, got {f['state']} {f['value']!r}" for f in r.fields if not f["match"]]
        lines.append(f"- **{r.scenario_id}** (rep {r.repeat}) next `{r.next_action}`"
                     f"{' (not allowed)' if r.next_ok is False else ''}")
        for m in miss:
            lines.append(f"  - field {m}")
        for m in r.rules_required_missing:
            lines.append(f"  - missing rule {m}")
        for c in r.critical:
            lines.append(f"  - CRITICAL {c}")
        if r.error:
            lines.append(f"  - error {r.error}")
    return "\n".join(lines) + "\n"


def run_eval(split: str, mode: str, repeats: int = 1, provider=None, out_root: Path = RESULTS_DIR,
             call_guard=None, require_frozen: bool = True, retest_note: str | None = None,
             cost_fn=None) -> tuple[Path, dict[str, Any]]:
    cfg = load_config()
    frozen_ok, frozen_msg = check_frozen(split)
    if require_frozen and not frozen_ok:
        raise RuntimeError(f"refusing to run: {frozen_msg}")
    scenarios = load_split(split)
    provider = provider or OfflineRulesProvider()
    started = datetime.now().astimezone()
    t0 = time.perf_counter()
    results = []
    for rep in range(repeats):
        for sc in scenarios:
            results.append(run_case(sc, provider, mode, cfg, rep, call_guard))
    summary = summarize(results)
    run_id = f"{started:%Y%m%dT%H%M%S}-{split}-{mode}"
    meta = {"run_id": run_id, "split": split, "mode": mode, "repeats": repeats,
            "started_at": started.isoformat(timespec="seconds"), "duration_s": round(time.perf_counter() - t0, 2),
            "frozen_check": frozen_msg, "retest_note": retest_note, "environment": environment(mode, provider),
            "cost": cost_fn(summary) if cost_fn else ("not applicable (offline, no API calls)" if mode != "live" else "unknown")}
    out = write_run(out_root / run_id, meta, results, summary)
    return out, summary


def write_not_run(out_root: Path, reason: str, requested: dict[str, Any]) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    rec = {"status": "not_run", "reason": reason, "requested": requested,
           "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "note": "No live-model results exist. No live scores are reported or estimated."}
    p = out_root / "live_status.json"
    p.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return p


def live_preconditions(max_calls: int | None, budget_usd: float | None, in_rate: float | None,
                       out_rate: float | None) -> str | None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY is not set"
    missing = [n for n, v in (("--max-calls", max_calls), ("--budget-usd", budget_usd),
                              ("--usd-per-mtok-input", in_rate), ("--usd-per-mtok-output", out_rate)) if v is None]
    if missing:
        return "spend limits not supplied: " + ", ".join(missing)
    return None
