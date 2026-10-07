"""Build figures only from saved results. Nothing here invents a number.

    python scripts/make_charts.py

Writes docs/figures/:
  evaluation_reliability.png/.svg  - held-out offline runs (first blind run, final retest) and oracle,
                                     from results/eval/*/summary.json; live shown as not_run when no
                                     live summary exists
  constraint_resolution.png/.svg   - rejected options and reasons in worked example 02, from
                                     examples/02_accessibility_conflict/snapshots.json
  handling_time.png/.svg           - only when completed study sessions exist; otherwise
                                     handling_time_status.json says it is pending
  figures_manifest.json            - which source file fed each figure
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
RESULTS = ROOT / "results" / "eval"
OUT = ROOT / "docs" / "figures"

# validated categorical order (scripts/validate_palette from the dataviz method); text uses ink colours
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
INK, INK_2, GRID = "#1E1C19", "#5b5750", "#e6e1d8"
SURFACE = "#FFFFFF"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK_2,
    "xtick.color": INK_2, "ytick.color": INK_2, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})


def _save(fig, name: str) -> list[str]:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("png", "svg"):
        p = OUT / f"{name}.{ext}"
        fig.savefig(p, dpi=160 if ext == "png" else None, bbox_inches="tight")
        paths.append(str(p.relative_to(ROOT)))
    plt.close(fig)
    return paths


def _runs(split: str = "heldout") -> list[tuple[Path, dict]]:
    out = []
    for d in sorted(RESULTS.glob(f"*-{split}-*")):
        f = d / "summary.json"
        if f.exists():
            out.append((d, json.loads(f.read_text(encoding="utf-8"))))
    return out


def _run_meta(d: Path) -> dict:
    p = d / "run.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def reliability() -> dict:
    runs = _runs()
    offline = [(d, s) for d, s in runs if d.name.endswith("-offline")]
    oracle = [(d, s) for d, s in runs if d.name.endswith("-oracle")]
    live = [(d, s) for d, s in runs if d.name.endswith("-live")]
    if not offline:
        return {"status": "skipped", "reason": "no held-out offline runs saved"}
    first, final = offline[0], offline[-1]
    series = [("Offline, first blind run", first), (f"Offline, final retest (not blind)", final)]
    if oracle:
        series.append(("Oracle facts, final retest", oracle[-1]))
    metrics = [("Next action allowed", "next_action_allowed"), ("Field agreement", "field_agreement_all"),
               ("Required-constraint recall", "required_constraint_recall")]

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.2), gridspec_kw={"width_ratios": [3, 1.15]})
    bw, gap = 0.26, 0.02
    for si, (label, (_d, s)) in enumerate(series):
        for mi, (_mlab, key) in enumerate(metrics):
            m = s[key]
            x = mi + (si - (len(series) - 1) / 2) * (bw + gap)
            ax.bar(x, m["rate"] * 100, bw, color=SERIES[si], label=label if mi == 0 else None, zorder=2)
            ax.text(x, m["rate"] * 100 + 1.2, f"{m['n']}/{m['d']}", ha="center", va="bottom", fontsize=8,
                    color=INK)
    ax.set_xticks(range(len(metrics)), [m for m, _ in metrics])
    ax.set_ylim(0, 112)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("% of scored items (count shown above bar)")
    ax.yaxis.grid(True, color=GRID, zorder=0)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=9)
    ax.set_title("Held-out split (40 agent-authored scenarios)", loc="left", color=INK, fontsize=11)

    # critical-error cases as counts, separate panel (different unit -> separate axis, not a dual axis)
    for si, (label, (_d, s)) in enumerate(series):
        v = s["cases_with_critical_errors"]
        ax2.bar(si, v, 0.6, color=SERIES[si], zorder=2)
        ax2.text(si, v + 0.08, f"{v} of {s['cases_run']}", ha="center", va="bottom", fontsize=8, color=INK)
    ax2.set_xticks(range(len(series)), ["first", "final", "oracle"][: len(series)])
    top = max(3, max(s["cases_with_critical_errors"] for _l, (_d, s) in series) + 1)
    ax2.set_ylim(0, top)
    ax2.set_yticks(range(0, top + 1))
    ax2.yaxis.grid(True, color=GRID, zorder=0)
    ax2.set_title("Cases with a critical error", loc="left", color=INK, fontsize=11)
    live_note = ("Live model: not_run (no API key or budget supplied); no live scores exist."
                 if not live else f"Live model runs saved: {len(live)} (see results/eval).")
    fig.text(0.01, -0.17, f"{live_note} Final retest = {final[0].name}; first run = {first[0].name}. "
             "Retests were run after inspecting failures and are not blind.", fontsize=8, color=INK_2, wrap=True)
    paths = _save(fig, "evaluation_reliability")
    return {"figure": paths, "sources": [str((d / "summary.json").relative_to(ROOT)) for _l, (d, _s) in series],
            "live": "not_run" if not live else "present"}


def constraint_resolution() -> dict:
    src = ROOT / "examples" / "02_accessibility_conflict" / "snapshots.json"
    if not src.exists():
        return {"status": "skipped", "reason": f"{src} missing (run scripts/run_worked_examples.py)"}
    snaps = json.loads(src.read_text(encoding="utf-8"))
    first, after = snaps[0], snaps[1]
    rules = ["R-CAP", "R-OVERLAP", "R-ACCESS"]
    names = {"R-CAP": "too small", "R-OVERLAP": "already booked", "R-ACCESS": "stairs only"}

    def counts(s):
        c = Counter()
        for r in s["availability"]["rejected"]:
            for reason in r["reasons"]:
                c[reason.split(":")[0]] += 1
        return c

    c1, c2 = counts(first), counts(after)
    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    y = list(range(len(rules)))
    h = 0.36
    for i, (lab, c, col) in enumerate(((f"Requested 18:00 ({len(first['availability']['options'])} feasible)", c1,
                                         SERIES[0]),
                                        (f"Guest-accepted 20:30 ({len(after['availability']['options'])} feasible)",
                                         c2, SERIES[1]))):
        ys = [v + (i - 0.5) * (h + 0.04) for v in y]
        vals = [c.get(r, 0) for r in rules]
        ax.barh(ys, vals, h, color=col, label=lab, zorder=2)
        for yy, v in zip(ys, vals):
            ax.text(v + 0.15, yy, str(v), va="center", fontsize=8, color=INK)
    ax.set_yticks(y, [f"{r} ({names[r]})" for r in rules])
    ax.invert_yaxis()
    ax.set_xlabel("Tables/groupings rejected for this reason (one option can have several reasons)")
    ax.xaxis.grid(True, color=GRID, zorder=0)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=9)
    best = after["availability"]["options"][0] if after["availability"]["options"] else None
    chosen = (f"Chosen after guest agreed: {best['unit']} ({' + '.join(best['tables'])}), step-free"
              f"{', separate tables disclosed' if best['split'] else ''}." if best else "")
    ax.set_title("Worked example 02: 12 guests, wheelchair user, 18:00 requested", loc="left", color=INK,
                 fontsize=11, pad=34)
    fig.text(0.01, -0.08, f"{chosen} Source: examples/02_accessibility_conflict/snapshots.json "
             f"({len(first['availability']['rejected'])} options checked at 18:00).", fontsize=8, color=INK_2)
    return {"figure": _save(fig, "constraint_resolution"), "sources": [str(src.relative_to(ROOT))]}


def handling_time() -> dict:
    from reservation_workbench.study import harness

    st = harness.status()
    status_path = OUT / "handling_time_status.json"
    OUT.mkdir(parents=True, exist_ok=True)
    if st["sessions_completed"] == 0:
        status_path.write_text(json.dumps({**st, "figure": None,
                                           "reason": "No completed operator sessions; no handling-time chart is "
                                                     "drawn and no times are estimated."}, indent=2) + "\n",
                               encoding="utf-8")
        return {"status": "pending", "file": str(status_path.relative_to(ROOT))}
    store = harness.StudyStore()
    by_method: dict[str, list[float]] = {m: [] for m in harness.METHODS}
    for r in store.sessions():
        if r["status"] == "completed":
            d = store.durations(r["seq"])
            if d["active_s"] is not None:
                by_method[r["method"]].append(d["active_s"] / 60)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for i, m in enumerate(harness.METHODS):
        vals = by_method[m]
        ax.scatter([i] * len(vals), vals, s=36, color=SERIES[i], zorder=3, edgecolor=SURFACE, linewidth=1.5)
        if vals:
            med = sorted(vals)[len(vals) // 2]
            ax.text(i + 0.12, med, f"median {med:.1f} min (n={len(vals)})", va="center", fontsize=8, color=INK)
    ax.set_xticks(range(3), [harness.METHOD_LABELS[m] for m in harness.METHODS], fontsize=8)
    ax.set_ylabel("Active handling time (min), from timer events")
    ax.yaxis.grid(True, color=GRID, zorder=0)
    ax.set_title(f"Operator study: {st['sessions_completed']} of {st['sessions_planned']} sessions completed",
                 loc="left", color=INK, fontsize=11)
    status_path.write_text(json.dumps({**st, "figure": "handling_time.png"}, indent=2) + "\n", encoding="utf-8")
    return {"figure": _save(fig, "handling_time"), "sources": [str(harness.DB_PATH)]}


def main() -> int:
    manifest = {"evaluation_reliability": reliability(), "constraint_resolution": constraint_resolution(),
                "handling_time": handling_time()}
    (OUT / "figures_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
