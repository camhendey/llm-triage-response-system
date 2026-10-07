"""Command-line interface over the same service layer as the UI.

    rw init-demo | reset-demo
    rw queue [--db demo|session]
    rw show INQUIRY_ID [--db ...]
    rw import-csv FILE [--db ...] [--interpret]
    rw eval validate | freeze | run --split heldout --mode offline|oracle [--repeats N] [--retest NOTE]
    rw eval live --max-calls N --budget-usd X --usd-per-mtok-input A --usd-per-mtok-output B
    rw study plan | export | status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .domain.models import NEXT_ACTION_LABELS


def _wb(kind: str):
    from .services.bootstrap import open_workbench

    return open_workbench(kind)


def cmd_init_demo(a) -> int:
    from .services.bootstrap import demo_db_path

    wb = _wb("demo")
    print(f"Demo database ready: {demo_db_path()} ({len(wb.queue())} inquiries)")
    return 0


def cmd_reset_demo(a) -> int:
    from .services.bootstrap import ResetRefused, reset_demo

    try:
        p = reset_demo(a.path)
    except ResetRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"Demo database reset: {p}")
    return 0


def cmd_queue(a) -> int:
    wb = _wb(a.db)
    tz = wb.cfg.tz
    print(f"{'ID':<10} {'STATE':<17} {'BOOKING':<10} {'URG':<6} NEXT ACTION")
    for v in wb.queue():
        b = v.booking.status.value if v.booking else "none"
        print(f"{v.inquiry.id:<10} {v.inquiry.state.value:<17} {b:<10} {v.assessment.urgency:<6} "
              f"{NEXT_ACTION_LABELS[v.assessment.next_action]}")
    print(f"clock: {wb.now().astimezone(tz):%Y-%m-%d %H:%M} {tz.key} · provider: {wb.provider.mode}")
    return 0


def cmd_show(a) -> int:
    wb = _wb(a.db)
    v = wb.load(a.inquiry_id)
    a_ = v.assessment
    print(f"{v.inquiry.id} {v.inquiry.guest_label} · inquiry {v.inquiry.state.value} · booking "
          f"{v.booking.status.value if v.booking else 'none'} · record v{v.inquiry.record_version}")
    print(f"NEXT: {a_.label} - {a_.next_action_detail}")
    for sev, rows in (("BLOCKER", a_.blockers), ("REVIEW", a_.reviews), ("INFO", a_.advisories)):
        for r in rows:
            print(f"  [{sev}] {r.rule_id}: {r.message}")
    print("FACTS:")
    for fv in v.facts.fields.values():
        src = ""
        if fv.current is not None:
            src = fv.current.quote or fv.current.source_type
        print(f"  {fv.field.value:<28} {fv.state:<13} {fv.value!s:<24} {src[:60]}")
    if a.notes:
        print(wb.booking_notes(v.inquiry.id))
    return 0


def cmd_import_csv(a) -> int:
    from .services.csv_import import import_csv

    wb = _wb(a.db)
    content = Path(a.file).read_bytes()
    import hashlib

    rep = import_csv(wb, content, batch_key=f"cli:csv:{hashlib.sha256(content).hexdigest()[:16]}",
                     interpret=a.interpret)
    if rep.fatal:
        print(f"ERROR: {rep.fatal}", file=sys.stderr)
        return 2
    for r in rep.rows:
        print(f"row {r.row}: {'ok' if r.ok else 'REJECTED'} - {r.message}")
    print(f"imported {rep.imported}, rejected {rep.failed}")
    return 0 if rep.failed == 0 else 1


def cmd_eval(a) -> int:
    from .evaluation import dataset, runner

    if a.eval_cmd == "validate":
        bad = 0
        for split in dataset.SPLIT_FILES:
            sc = dataset.load_split(split)
            errs = dataset.validate(sc, split)
            multi = sum(1 for s in sc if s.message_count >= 2)
            print(f"{split}: {len(sc)} scenarios, {multi} multi-message, problems: {errs or 'none'}")
            ok, msg = dataset.check_frozen(split)
            print(f"  freeze: {msg}")
            bad += len(errs)
        return 1 if bad else 0
    if a.eval_cmd == "freeze":
        print(json.dumps(dataset.freeze(), indent=2))
        return 0
    if a.eval_cmd == "run":
        out, s = runner.run_eval(a.split, a.mode, repeats=a.repeats, retest_note=a.retest)
        print(f"wrote {out}")
        print(json.dumps({k: s[k] for k in ("cases_run", "next_action_allowed", "field_agreement_all",
                                            "required_constraint_recall", "cases_with_critical_errors")}, indent=2))
        return 0
    if a.eval_cmd == "live":
        requested = {"split": "heldout", "repeats": a.repeats, "max_calls": a.max_calls, "budget_usd": a.budget_usd}
        why = runner.live_preconditions(a.max_calls, a.budget_usd, a.usd_per_mtok_input, a.usd_per_mtok_output)
        if why:
            p = runner.write_not_run(runner.RESULTS_DIR, why, requested)
            print(f"live evaluation not_run: {why}\nrecorded {p}")
            return 0
        from .providers.anthropic_live import AnthropicLiveProvider

        prov = AnthropicLiveProvider()
        max_attempts = prov.settings.max_attempts

        def spent_usd() -> float:
            i = sum(c.get("input_tokens", 0) or 0 for c in prov.calls)
            o = sum(c.get("output_tokens", 0) or 0 for c in prov.calls)
            return i / 1e6 * a.usd_per_mtok_input + o / 1e6 * a.usd_per_mtok_output

        def guard() -> bool:
            # stop before a step that could exceed either cap (each interpret may retry up to max_attempts)
            if len(prov.calls) + max_attempts + 1 > a.max_calls:
                return False
            return spent_usd() < a.budget_usd * 0.9

        def cost(_s):
            return (f"USD {spent_usd():.4f} computed from recorded token usage at the supplied rates "
                    f"({a.usd_per_mtok_input}/{a.usd_per_mtok_output} per million input/output tokens)")

        out, s = runner.run_eval("heldout", "live", repeats=a.repeats, provider=prov, call_guard=guard,
                                 cost_fn=cost, retest_note=a.retest)
        (out / "calls.json").write_text(json.dumps(prov.calls, indent=2, default=str), encoding="utf-8")
        print(f"wrote {out}; calls {len(prov.calls)}; {cost(s)}")
        return 0
    return 2


def cmd_study(a) -> int:
    from .study import harness

    if a.study_cmd == "plan":
        p = harness.write_plan()
        print(f"wrote {p}")
    elif a.study_cmd == "export":
        p = harness.export_csv()
        print(f"wrote {p}")
    elif a.study_cmd == "status":
        print(json.dumps(harness.status(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()  # reads .env if present; existing environment variables win
    ap = argparse.ArgumentParser(prog="rw", description="Reservation Operations Workbench (synthetic demo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-demo", help="create and seed the demo database if missing").set_defaults(fn=cmd_init_demo)
    p = sub.add_parser("reset-demo", help="delete and re-seed ONLY the designated demo database")
    p.add_argument("--path", help="must equal the designated demo path; anything else is refused")
    p.set_defaults(fn=cmd_reset_demo)
    for name, fn in (("queue", cmd_queue), ("show", cmd_show)):
        p = sub.add_parser(name)
        p.add_argument("--db", choices=["demo", "session"], default="demo")
        if name == "show":
            p.add_argument("inquiry_id")
            p.add_argument("--notes", action="store_true", help="also print copyable booking notes")
        p.set_defaults(fn=fn)
    p = sub.add_parser("import-csv")
    p.add_argument("file")
    p.add_argument("--db", choices=["demo", "session"], default="session")
    p.add_argument("--interpret", action="store_true")
    p.set_defaults(fn=cmd_import_csv)
    p = sub.add_parser("eval")
    es = p.add_subparsers(dest="eval_cmd", required=True)
    es.add_parser("validate")
    es.add_parser("freeze")
    r = es.add_parser("run")
    r.add_argument("--split", choices=["development", "heldout"], default="heldout")
    r.add_argument("--mode", choices=["offline", "oracle"], default="offline")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--retest", help="note marking this run as a retest after inspecting failures")
    lv = es.add_parser("live")
    lv.add_argument("--repeats", type=int, default=3)
    lv.add_argument("--max-calls", type=int)
    lv.add_argument("--budget-usd", type=float)
    lv.add_argument("--usd-per-mtok-input", type=float)
    lv.add_argument("--usd-per-mtok-output", type=float)
    lv.add_argument("--retest")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("study")
    ss = p.add_subparsers(dest="study_cmd", required=True)
    for n in ("plan", "export", "status"):
        ss.add_parser(n)
    p.set_defaults(fn=cmd_study)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
