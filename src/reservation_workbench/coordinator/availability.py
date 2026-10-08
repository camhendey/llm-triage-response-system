"""Conservative snapshot assistance, never a live availability promise."""

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ..services.opentable_import import ACTIVE, INACTIVE, Report, Snapshot
from .store import now
from .workflow import instant, plan_gaps


def serialize(snapshot, complete=False):
    value = json.loads(json.dumps(asdict(snapshot), default=str))
    value["complete"] = bool(complete)
    return value


def restore(value):
    rows = [dict(r) for r in value["rows"]]
    for r in rows:
        if r.get("_start"):
            r["_start"] = instant(r["_start"])
    from datetime import date

    report = Report(**value["report"])
    return Snapshot(
        report,
        value["kind"],
        value["mapping"],
        tuple(rows),
        tuple(value["warnings"]),
        instant(value["exported_at"]),
        instant(value["imported_at"]),
        date.fromisoformat(value["coverage_start"]),
        date.fromisoformat(value["coverage_end"]),
        value["timezone"],
    )


def table_ids(value):
    if isinstance(value, list):
        return [str(x).strip() for x in value]
    if str(value).strip().startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed]
        except ValueError:
            pass
    return [v.strip() for v in re.split(r"[,;|]", str(value or "")) if v.strip()]


def compare(previous, current):
    def keyed(r):
        return {
            (v.get("restaurant_id", ""), v["reservation_id"]): v
            for v in r["rows"]
            if v.get("reservation_id")
        }

    if not previous:
        return "First snapshot. No booking records will be changed."
    a, b = keyed(previous), keyed(current)
    if len(a) != len(previous["rows"]) or len(b) != len(current["rows"]):
        return "Stable reservation IDs are incomplete; row-level reconciliation is unavailable."
    return f"{len(b.keys() - a.keys())} added · {sum(a[k] != b[k] for k in a.keys() & b.keys())} changed · {len(a.keys() - b.keys())} absent. Absence does not mean cancellation."


def assess(c, p, report, others=()):
    def result(status, reason, options=()):
        return {"status": status, "reason": reason, "options": list(options)}

    if plan_gaps(c):
        return result("Cannot assess", "Complete the arrangement first.")
    if not p["verified_by"] or not p["tables"] or not p["duration_minutes"]:
        return result(
            "Cannot assess",
            "Review the current layout and occupancy-duration assumption in Settings.",
        )
    if not report or not report.get("complete"):
        return result(
            "Cannot assess",
            "Apply a reservations report and attest its complete date coverage and filters.",
        )
    if report["timezone"] != p["timezone"] or now() - instant(
        report["exported_at"]
    ) > timedelta(hours=4):
        return result(
            "Cannot assess",
            "Report is stale or has a different time zone. Upload a fresh report.",
        )
    q = c["plan"]
    tz = ZoneInfo(p["timezone"])
    start = (
        datetime.fromisoformat(q["date"] + "T" + q["time"])
        .replace(tzinfo=tz)
        .astimezone(UTC)
    )
    end = start + timedelta(minutes=q["duration"] + p["buffer_minutes"])
    lookback = start - timedelta(minutes=p["duration_minutes"] + p["buffer_minutes"])
    if not (
        report["coverage_start"] <= lookback.astimezone(tz).date().isoformat()
        and report["coverage_end"] >= end.astimezone(tz).date().isoformat()
    ):
        return result(
            "Cannot assess",
            "Coverage must include the visit and any overlapping prior-day occupancy.",
        )
    tables = {t["id"]: t for t in p["tables"]}
    rows = [dict(r) for r in report["rows"]]
    own = (c["external"] or {}).get("reference")
    if own and any(not r.get("reservation_id") for r in rows):
        return result(
            "Cannot assess",
            "Reservation IDs are required to exclude the currently linked booking safely.",
        )
    rows = [r for r in rows if not own or r.get("reservation_id") != own]
    for other in others:
        e = other.get("external")
        if other["id"] == c["id"] or not e:
            continue
        matches = [r for r in rows if r.get("reservation_id") == e["reference"]]
        if instant(e["checked_at"]) > instant(report["exported_at"]):
            rows = [r for r in rows if r.get("reservation_id") != e["reference"]]
            if e["status"] in ("Held", "Confirmed"):
                saved = e["plan"]
                rows.append(
                    {
                        "reservation_id": e["reference"],
                        "status": e["status"],
                        "tables": saved["tables"],
                        "_start": datetime.fromisoformat(
                            saved["date"] + "T" + saved["time"]
                        )
                        .replace(tzinfo=tz)
                        .isoformat(),
                        "_duration": saved["duration"],
                    }
                )
        elif e["status"] in ("Held", "Confirmed") and (
            not matches
            or any(
                r.get("status", "").lower() in INACTIVE
                or set(table_ids(r.get("tables"))) != set(e["plan"]["tables"])
                for r in matches
            )
        ):
            return result(
                "Cannot assess",
                "A newer report contradicts or omits a locally verified active booking. Reconcile it in OpenTable.",
            )
    occupied = set()
    for row in rows:
        dt = instant(row["_start"]).astimezone(UTC)
        finish = dt + timedelta(
            minutes=row.get("_duration", p["duration_minutes"]) + p["buffer_minutes"]
        )
        if dt >= end or finish <= start:
            continue
        status = row.get("status", "").strip().lower()
        if status in INACTIVE:
            continue
        assigned = table_ids(row.get("tables"))
        if status not in ACTIVE or not assigned or not set(assigned) <= set(tables):
            return result(
                "Cannot assess",
                "An overlapping row has unknown status, missing tables or unconfigured tables. Check manually.",
            )
        occupied.update(assigned)
    configurations = [
        {
            "tables": [t["id"]],
            "capacity": t["capacity"],
            "description": t.get("area", ""),
        }
        for t in tables.values()
    ] + p["groupings"]
    options = []
    step_free = c["details"]["accessibility"]["value"].lower()
    needs_step_free = any(
        s in step_free for s in ("wheelchair", "step-free", "step free")
    )
    for option in configurations:
        if option["capacity"] < q["party"] or set(option["tables"]) & occupied:
            continue
        if needs_step_free and not all(
            tables[t]["step_free"] for t in option["tables"]
        ):
            continue
        options.append(option)
    options.sort(key=lambda v: (len(v["tables"]), v["capacity"]))
    selected = next((o for o in options if set(o["tables"]) == set(q["tables"])), None)
    if not selected:
        return result(
            "Conflict detected",
            "Selected tables conflict, exceed configured capacity/groupings, or do not meet step-free requirements.",
            options[:3],
        )
    return result(
        "Potentially feasible",
        "No conflict found under declared coverage and estimated occupancy duration. Live availability, flow and guest suitability still require a manual check.",
        options[:3],
    )
