"""Evidence-bound workflow. Recording an external action never performs that action."""

import json
import re
from copy import deepcopy
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from .store import digest, now, stamp

DETAILS = ("accessibility", "minors", "allergies", "billing", "occasion")
STATES = (
    "Not asked",
    "Asked; awaiting response",
    "Historical; verify",
    "Confirmed for this visit",
)
CHECKS = (
    "Date and time",
    "Tables and party size",
    "Guest details and requirements",
    "Large-party classification",
    "Made by and saved notes",
)
PURPOSES = (
    "Clarification",
    "Arrangement offer",
    "Final confirmation",
    "Decline",
    "Referral",
    "Cancellation / release",
)


def profile():
    return {
        "name": "",
        "timezone": "America/Toronto",
        "version": 1,
        "verified_by": "",
        "call_start": "09:00",
        "call_cutoff": "21:00",
        "duration_minutes": None,
        "buffer_minutes": 0,
        "min_spend_threshold": None,
        "manager_threshold": None,
        "tables": [],
        "groupings": [],
    }


def instant(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Include an explicit time-zone offset in timestamps.")
    return dt


def required(value, message):
    if not value or (isinstance(value, str) and not value.strip()):
        raise ValueError(message)
    return value


def plan_hash(c):
    return digest(c["plan"])


def record_hash(c):
    return digest(
        [c["plan"], c["guest"], c["email"], c["phone"], c["details"], c["promises"]]
    )


def draft_hash(c, p):
    return digest(
        [
            record_hash(c),
            c["disposition"],
            c["external"],
            c["acceptance"],
            c["approval"],
            p["version"],
            [m["id"] for m in c["messages"] if not m.get("ack")],
            c["unreviewed"],
        ]
    )


def accepted(c):
    return bool(c["acceptance"] and c["acceptance"]["plan_hash"] == plan_hash(c))


def external_current(c, p):
    e = c["external"]
    return bool(
        e
        and e["status"] == "Confirmed"
        and e["record_hash"] == record_hash(c)
        and e["policy_version"] == p["version"]
    )


def available(c, p):
    a = c["availability"]
    return bool(
        a
        and a["result"] == "Available externally"
        and a["plan_hash"] == plan_hash(c)
        and a["policy_version"] == p["version"]
        and now() - instant(a["at"]) < timedelta(hours=4)
    )


def approval_needed(c, p):
    return bool(
        (p["manager_threshold"] and c["plan"].get("party", 0) >= p["manager_threshold"])
        or c["plan"].get("waiver")
    )


def approved(c, p):
    a = c["approval"]
    return not approval_needed(c, p) or bool(
        a and a["plan_hash"] == plan_hash(c) and a["policy_version"] == p["version"]
    )


def plan_gaps(c):
    return [
        k
        for k in ("date", "time", "party", "duration", "tables", "arrangement")
        if not c["plan"].get(k)
    ]


def final_gaps(c, p):
    gaps = ["Plan: " + k for k in plan_gaps(c)]
    if not p["verified_by"]:
        gaps.append("Current restaurant policy review")
    if not c["email"] and not c["phone"]:
        gaps.append("Guest contact")
    if c["unreviewed"]:
        gaps.append("Review the latest request/change")
    gaps += [
        k.title() + " confirmed for this visit"
        for k, v in c["details"].items()
        if v["state"] != STATES[-1]
    ]
    if not c["plan"].get("photo_id") and not c["plan"].get("photo_exception"):
        gaps.append("Approved seating photo or documented exception")
    if not accepted(c):
        gaps.append("Guest acceptance of this arrangement")
    if not external_current(c, p):
        gaps.append("Current external booking verification")
    if not approved(c, p):
        gaps.append("Manager approval")
    if (
        p["min_spend_threshold"]
        and c["plan"].get("party", 0) >= p["min_spend_threshold"]
        and not (c["plan"].get("amount") or c["plan"].get("waiver"))
    ):
        gaps.append("Minimum-spend terms or approved waiver")
    return gaps


def sent_current(c, p):
    d = c["draft"]
    return bool(
        d
        and d.get("sent_at")
        and d["source_hash"] == draft_hash(c, p)
        and d.get("reviewed_hash") == digest(d["text"])
    )


def referral_current(c, p):
    r = c.get("referral")
    return bool(
        r and r["plan_hash"] == plan_hash(c) and r["policy_version"] == p["version"]
    )


def next_action(c, p):
    if c.get("closed_reason"):
        return "Closed"
    if c["unreviewed"]:
        return "Review new guest message"
    if c["disposition"] != "Book":
        if c["disposition"] in ("Cancel", "Release") and (
            not c["external"]
            or c["external"]["status"] not in ("Cancelled", "Released")
        ):
            return "Verify cancellation / release externally"
        if c["disposition"] == "Refer" and not referral_current(c, p):
            return "Record referral handoff"
        purpose = {
            "Decline": "Decline",
            "Refer": "Referral",
            "Cancel": "Cancellation / release",
            "Release": "Cancellation / release",
        }[c["disposition"]]
        return (
            "Complete"
            if sent_current(c, p)
            and c["draft"]["purpose"] == purpose
            and not any(not t.get("done_at") for t in c["tasks"])
            else "Prepare outcome response / follow-up"
        )
    if (
        c.get("hold_until")
        and c["external"]
        and c["external"]["status"] == "Held"
        and instant(c["hold_until"]) <= now()
    ):
        return "Hold expired: check and release externally"
    if plan_gaps(c):
        return "Complete requested arrangement"
    if not available(c, p) and not external_current(c, p):
        return "Check availability in OpenTable"
    if not approved(c, p):
        return "Request manager approval"
    if not accepted(c):
        return "Obtain guest acceptance"
    if not external_current(c, p):
        return "Verify saved external booking"
    if final_gaps(c, p):
        return "Confirm visit details"
    if not sent_current(c, p) or c["draft"]["purpose"] != "Final confirmation":
        return "Review and send final confirmation"
    return (
        "Complete follow-up tasks"
        if any(not t.get("done_at") for t in c["tasks"])
        else "Complete"
    )


def priority(c):
    dues = [instant(t["due"]) for t in c["tasks"] if not t.get("done_at")]
    if c.get("hold_until") and c["external"] and c["external"]["status"] == "Held":
        dues.append(instant(c["hold_until"]))
    due = min(dues) if dues else None
    band = (
        0
        if due and due <= now()
        else 1
        if due and due <= now() + timedelta(hours=6)
        else 2
    )
    return band, instant(c["received_at"])


def booking_package(c):
    q = c["plan"]
    lines = [
        f"TABLE {', '.join(q.get('tables', [])) or 'Unassigned'} | TIME {q.get('date', '')} {q.get('time', '')}",
        f"{c['guest']} | {q.get('party', '?')} guests | {q.get('duration', '?')} minutes",
        q.get("arrangement", ""),
        f"Contact: {c['email']} {c['phone']}",
        f"Guest acceptance: {'current' if accepted(c) else 'not current'}",
    ]
    lines += [
        f"{k.title()}: {v['value'] or 'Unknown'} [{v['state']}]"
        for k, v in c["details"].items()
    ]
    if q.get("amount"):
        lines.append(
            f"Minimum spend: {q['currency']} {q['amount']} {q['basis']}; includes/excludes: {q['includes']}"
        )
    if q.get("waiver"):
        lines.append("Requested waiver: " + q["waiver"])
    lines += [
        "Promises: " + c["promises"],
        "Large-party classification: verify against current policy",
        "Made by: " + c["made_by"],
        "Owner: " + c["owner"],
        "Hold deadline: " + c.get("hold_until", ""),
    ]
    return "\n".join(lines)


def validate_purpose(c, p, purpose):
    if purpose not in PURPOSES:
        raise ValueError("Choose a supported response purpose.")
    if purpose != "Clarification" and c["unreviewed"]:
        raise ValueError(
            "Review the latest request before preparing an outcome response."
        )
    if purpose == "Final confirmation":
        required(c["disposition"] == "Book", "This inquiry is not a booking.")
        gaps = final_gaps(c, p)
        required(not gaps, "Before final confirmation: " + ", ".join(gaps))
    if purpose == "Arrangement offer":
        required(
            c["disposition"] == "Book" and not plan_gaps(c),
            "Complete the booking arrangement first.",
        )
        required(
            p["verified_by"] and available(c, p) and approved(c, p),
            "Review policy, check availability and obtain required approval first.",
        )
        required(
            c["plan"].get("photo_id") or c["plan"].get("photo_exception"),
            "Choose a seating photo or document an exception.",
        )
        if p["min_spend_threshold"] and c["plan"]["party"] >= p["min_spend_threshold"]:
            required(
                c["plan"].get("amount") or c["plan"].get("waiver"),
                "Record minimum-spend terms or an approved waiver.",
            )
    if purpose in ("Arrangement offer", "Final confirmation"):
        dt = datetime.fromisoformat(
            c["plan"]["date"] + "T" + c["plan"]["time"]
        ).replace(tzinfo=ZoneInfo(p["timezone"]))
        required(dt > now(), "Visit time is in the past. Review the arrangement.")
    if purpose == "Decline":
        required(c["disposition"] == "Decline", "Record the decline outcome first.")
    if purpose == "Referral":
        required(
            c["disposition"] == "Refer" and referral_current(c, p),
            "Record the referral recipient and handoff first.",
        )
    if purpose == "Cancellation / release":
        required(
            c["disposition"] in ("Cancel", "Release")
            and c["external"]
            and c["external"]["status"] in ("Cancelled", "Released"),
            "Verify the external cancellation or release first.",
        )


def compose(c, p, purpose):
    validate_purpose(c, p, purpose)
    q = c["plan"]
    if purpose == "Clarification":
        missing = plan_gaps(c) + [
            k for k, v in c["details"].items() if v["state"] != STATES[-1]
        ]
        body = (
            "Could you please confirm "
            + (
                ", ".join(missing)
                if missing
                else "whether the proposed arrangement meets your needs"
            )
            + "?"
        )
    elif purpose in ("Arrangement offer", "Final confirmation"):
        prefix = (
            "Your reservation is confirmed"
            if purpose == "Final confirmation"
            else "Following our availability check, the proposed arrangement is"
        )
        body = f"{prefix}: {q['party']} guests on {q['date']} at {q['time']}, for {q['duration']} minutes.\n{q['arrangement']}"
        if q.get("amount"):
            body += f"\nMinimum spend: {q['currency']} {q['amount']} {q['basis']}. {q['includes']}"
        if q.get("waiver"):
            body += "\nAgreed exception: " + q["waiver"]
        if q.get("photo_id"):
            body += "\nPlease see the attached seating photograph."
        if purpose == "Arrangement offer":
            body += "\nPlease reply to confirm that you accept this arrangement. This message is not a final booking confirmation."
    elif purpose == "Decline":
        body = (
            "Unfortunately, we cannot accommodate this request. "
            + c["disposition_reason"]
        )
    elif purpose == "Referral":
        body = (
            "We have referred your inquiry to "
            + c["referral"]["recipient"]
            + ". They will need to confirm their own availability and terms."
        )
    else:
        body = (
            "We have verified that your booking has been "
            + c["external"]["status"].lower()
            + "."
        )
    return f"Hello {c['guest']},\n\n{body}\n\nKind regards,\n{c['owner']}\n{p['name']}"


def service_record(c, p):
    e = c["external"] or {}
    return {
        "guest": c["guest"],
        "external_reference": e.get("reference", ""),
        "status": e.get("status", "No external record"),
        "saved_arrangement": e.get("plan", {}),
        "pending_change": bool(e and e.get("plan_hash") != plan_hash(c)),
        "current_verification": external_current(c, p),
        "guest_acceptance": accepted(c),
        "requirements": c["details"],
        "promises": c["promises"],
        "owner": c["owner"],
        "next_action": next_action(c, p),
        "outstanding_tasks": [t for t in c["tasks"] if not t.get("done_at")],
    }


class Workflow:
    def __init__(self, store, actor):
        self.store, self.actor = store, actor

    def create(self, guest, email, phone, source, received_at, text):
        required(
            guest.strip() and text.strip(),
            "Enter a guest label and the original inquiry.",
        )
        required(
            source in ("Email", "Phone", "Paper", "Internal"),
            "Choose an intake source.",
        )
        received = instant(received_at)
        required(
            received <= now() + timedelta(minutes=5),
            "Received time cannot be in the future.",
        )
        shift = self.store.setting("shift", {})
        required(
            shift.get("operator") == self.actor and not shift.get("ended"),
            "Start your shift first.",
        )
        c = {
            "id": "C-" + uuid4().hex[:10],
            "revision": 1,
            "guest": guest.strip(),
            "email": email.strip(),
            "phone": phone.strip(),
            "source": source,
            "received_at": received.isoformat(),
            "created_at": stamp(),
            "updated_at": stamp(),
            "owner": self.actor,
            "made_by": self.actor,
            "messages": [
                {
                    "id": uuid4().hex,
                    "text": text.strip(),
                    "source": source,
                    "at": received.isoformat(),
                    "ack": False,
                }
            ],
            "calls": [],
            "details": {
                k: {"value": "", "state": STATES[0], "evidence": ""} for k in DETAILS
            },
            "plan": {},
            "promises": "",
            "tasks": [],
            "disposition": "Book",
            "disposition_reason": "",
            "unreviewed": False,
            "availability": None,
            "approval": None,
            "acceptance": None,
            "external": None,
            "draft": None,
            "hold_until": "",
            "handoff": None,
            "referral": None,
            "handling_samples": [],
        }
        return self.store.create(c, self.actor)

    def run(self, c, action, **data):
        def change(x, db):
            row = db.execute("SELECT data FROM settings WHERE key='profile'").fetchone()
            p = json.loads(row[0]) if row else profile()
            if action == "interpret":
                from ..providers.base import (
                    InterpretContext,
                    MessageInput,
                    validate_evidence,
                )
                from ..providers.offline import OfflineRulesProvider

                messages = [
                    MessageInput(
                        id=m["id"], text=m["text"], received_at=instant(m["at"])
                    )
                    for m in x["messages"]
                    if not m["ack"]
                ]
                result = validate_evidence(
                    OfflineRulesProvider().interpret(
                        messages,
                        InterpretContext(
                            p["timezone"],
                            p["name"],
                            [t["id"] for t in p["tables"]],
                            now(),
                        ),
                    ),
                    messages,
                )
                x["interpretation"] = result.model_dump(mode="json")
            elif action == "details":
                for k, v in data["details"].items():
                    required(
                        k in DETAILS and v["state"] in STATES, "Invalid detail state."
                    )
                    if v["state"] == STATES[-1]:
                        required(
                            v["value"].strip() and v["evidence"].strip(),
                            "Confirmed visit details need a value (including explicit none) and evidence.",
                        )
                x["details"] = data["details"]
                for k in ("email", "phone", "owner", "promises"):
                    x[k] = str(data[k]).strip()
                required(x["owner"], "Assign an owner.")
            elif action == "plan":
                q = deepcopy(data["plan"])
                for k in ("party", "duration"):
                    required(
                        q[k] and float(q[k]).is_integer() and 0 < float(q[k]) <= 1440,
                        "Use positive whole numbers for party size and duration.",
                    )
                    q[k] = int(q[k])
                # Strict parser also rejects ambiguous/nonexistent local DST times.
                from ..services.opentable_import import parse_start

                parse_start(
                    {"date": q["date"], "time": q["time"]},
                    "MDY",
                    ZoneInfo(p["timezone"]),
                )
                required(
                    q["tables"] and set(q["tables"]) <= {t["id"] for t in p["tables"]},
                    "Choose configured tables.",
                )
                options = [
                    {"tables": [t["id"]], "capacity": t["capacity"]}
                    for t in p["tables"]
                ] + p["groupings"]
                required(
                    any(
                        set(o["tables"]) == set(q["tables"])
                        and o["capacity"] >= q["party"]
                        for o in options
                    ),
                    "Use a configured table or allowed grouping with enough capacity.",
                )
                required(
                    q["arrangement"].strip(),
                    "Describe the seating and any split-table arrangement.",
                )
                if q.get("amount"):
                    required(
                        float(q["amount"]) > 0
                        and q.get("currency")
                        and q.get("basis") in ("Total", "Per person")
                        and q.get("includes"),
                        "Record positive spend, currency, basis and inclusions/exclusions.",
                    )
                if q.get("photo_id"):
                    required(
                        db.execute(
                            "SELECT id FROM photos WHERE id=?", (q["photo_id"],)
                        ).fetchone(),
                        "Selected photo is no longer available.",
                    )
                x["plan"] = q
            elif action == "message":
                required(data["text"].strip(), "Enter the message.")
                x["messages"].append(
                    {
                        "id": uuid4().hex,
                        "text": data["text"].strip(),
                        "source": data["source"],
                        "at": stamp(),
                        "ack": bool(data["ack"]),
                    }
                )
                if not data["ack"]:
                    x["unreviewed"] = True
                    x.pop("closed_reason", None)
            elif action == "resolve":
                required(
                    data["note"].strip(),
                    "Explain what was reviewed and any changes made.",
                )
                x["unreviewed"] = False
                x["messages"][-1]["resolution"] = data["note"]
            elif action == "call":
                required(
                    data["summary"].strip(), "Record the call outcome and evidence."
                )
                allowed = (
                    "Reached guest",
                    "No answer",
                    "Voicemail",
                    "Callback requested",
                    "Incorrect number",
                )
                required(data["outcome"] in allowed, "Choose a valid call outcome.")
                x["calls"].append(
                    dict(id=uuid4().hex, at=stamp(), actor=self.actor, **data)
                )
                if data["outcome"] != "Reached guest":
                    due = now() + timedelta(hours=1)
                    x["tasks"].append(
                        {
                            "id": uuid4().hex,
                            "title": "Arrange callback"
                            if data["outcome"] == "Callback requested"
                            else "Send initial follow-up email",
                            "owner": x["owner"],
                            "waiting_on": "Coordinator",
                            "due": due.isoformat(),
                        }
                    )
            elif action == "availability":
                required(not plan_gaps(x), "Complete the requested arrangement first.")
                required(
                    data["evidence"].strip()
                    and data["result"]
                    in ("Available externally", "Unavailable", "Cannot assess"),
                    "Record the check outcome and evidence.",
                )
                x["availability"] = dict(
                    **data,
                    plan_hash=plan_hash(x),
                    policy_version=p["version"],
                    at=stamp(),
                    actor=self.actor,
                )
            elif action == "approval":
                required(
                    available(x, p),
                    "Check feasibility externally before requesting approval.",
                )
                required(
                    data["approver"].strip() and data["note"].strip(),
                    "Record approver and decision evidence.",
                )
                x["approval"] = dict(
                    **data,
                    plan_hash=plan_hash(x),
                    policy_version=p["version"],
                    at=stamp(),
                )
            elif action == "accept":
                required(
                    not plan_gaps(x) and not x["unreviewed"],
                    "Complete and review the current arrangement first.",
                )
                sources = {
                    m["id"]: m["text"]
                    for m in x["messages"]
                    if m["source"] in ("Email", "Phone")
                }
                sources.update(
                    {
                        v["id"]: v["summary"]
                        for v in x["calls"]
                        if v["outcome"] == "Reached guest"
                    }
                )
                required(
                    data["source_id"] in sources
                    and data["quote"].strip()
                    and data["quote"] in sources[data["source_id"]],
                    "Acceptance must quote a guest message or reached-guest call exactly.",
                )
                x["acceptance"] = dict(
                    **data, plan_hash=plan_hash(x), at=stamp(), actor=self.actor
                )
                for t in x["tasks"]:
                    if t.get("kind") == "acceptance" and not t.get("done_at"):
                        t.update(
                            done_at=stamp(),
                            note="Guest acceptance recorded",
                            done_by=self.actor,
                        )
            elif action == "external":
                required(
                    data["reference"].strip() and data["note"].strip(),
                    "Enter the external reference and verification evidence.",
                )
                required(
                    set(data["checks"]) == set(CHECKS),
                    "Complete every external verification check.",
                )
                required(
                    data["status"] in ("Held", "Confirmed", "Cancelled", "Released"),
                    "Choose an external status.",
                )
                if data["status"] in ("Held", "Confirmed"):
                    required(
                        available(x, p) and approved(x, p),
                        "Recheck availability (within 4 hours) and required approval first.",
                    )
                    for row in db.execute(
                        "SELECT data FROM cases WHERE id!=?", (x["id"],)
                    ):
                        other = json.loads(row[0]).get("external")
                        required(
                            not other
                            or other["reference"] != data["reference"].strip(),
                            "This external reference is already linked to another inquiry.",
                        )
                else:
                    required(
                        x["external"]
                        and x["external"]["reference"] == data["reference"].strip(),
                        "Cancellation / release must match the linked external reference.",
                    )
                if data["status"] == "Held":
                    dt = instant(data["hold_until"])
                    visit = datetime.fromisoformat(
                        x["plan"]["date"] + "T" + x["plan"]["time"]
                    ).replace(tzinfo=ZoneInfo(p["timezone"]))
                    required(
                        now() < dt < visit,
                        "Hold deadline must be future and before the visit.",
                    )
                    x["hold_until"] = dt.isoformat()
                else:
                    x["hold_until"] = ""
                x["external"] = dict(data)
                x["external"].update(
                    reference=data["reference"].strip(),
                    record_hash=record_hash(x),
                    plan_hash=plan_hash(x),
                    policy_version=p["version"],
                    plan=deepcopy(x["plan"]),
                    checked_at=stamp(),
                    checked_by=self.actor,
                )
            elif action == "disposition":
                required(
                    data["value"] in ("Book", "Decline", "Refer", "Cancel", "Release"),
                    "Choose a supported outcome.",
                )
                required(data["reason"].strip(), "Explain the outcome.")
                if data["value"] in ("Decline", "Refer"):
                    required(
                        not x["external"]
                        or x["external"]["status"] in ("Cancelled", "Released"),
                        "Release or cancel the active external booking first.",
                    )
                x["disposition"], x["disposition_reason"] = (
                    data["value"],
                    data["reason"],
                )
            elif action == "referral":
                required(
                    x["disposition"] == "Refer"
                    and data["recipient"].strip()
                    and data["note"].strip(),
                    "Choose referral outcome and record recipient and handoff evidence.",
                )
                required(
                    x["availability"]
                    and x["availability"]["plan_hash"] == plan_hash(x)
                    and x["availability"]["policy_version"] == p["version"],
                    "Record feasibility for the current arrangement before referral.",
                )
                x["referral"] = dict(
                    **data,
                    at=stamp(),
                    actor=self.actor,
                    plan_hash=plan_hash(x),
                    policy_version=p["version"],
                )
            elif action == "task":
                required(
                    data["title"].strip() and data["owner"].strip(),
                    "Give the task a title and owner.",
                )
                instant(data["due"])
                x["tasks"].append(dict(id=uuid4().hex, **data))
            elif action == "task_done":
                required(data["note"].strip(), "Record what was done.")
                task = next((t for t in x["tasks"] if t["id"] == data["id"]), None)
                required(
                    task is not None and not task.get("done_at"),
                    "Task is already complete or missing.",
                )
                task.update(done_at=stamp(), done_by=self.actor, note=data["note"])
            elif action == "draft":
                validate_purpose(x, p, data["purpose"])
                required(data["text"].strip(), "Response cannot be empty.")
                if data["purpose"] not in (
                    "Final confirmation",
                    "Cancellation / release",
                ):
                    required(
                        not re.search(
                            r"\b(?:reservation|booking)\s+(?:is |has been )?confirmed\b",
                            data["text"],
                            re.IGNORECASE,
                        ),
                        "Use the guarded final-confirmation response for confirmation wording.",
                    )
                x["draft"] = dict(
                    **data, source_hash=draft_hash(x, p), saved_at=stamp()
                )
            elif action in ("review", "sent"):
                d = required(x["draft"], "Save a response first.")
                required(
                    d["source_hash"] == draft_hash(x, p),
                    "The response is stale. Generate or save a fresh response.",
                )
                validate_purpose(x, p, d["purpose"])
                if action == "review":
                    d.update(
                        reviewed_hash=digest(d["text"]),
                        reviewed_by=self.actor,
                        reviewed_at=stamp(),
                    )
                else:
                    required(
                        d.get("reviewed_hash") == digest(d["text"]),
                        "Review this exact response before recording it as sent.",
                    )
                    required(
                        not d.get("sent_at"), "This response was already reported sent."
                    )
                    if x["plan"].get("photo_id") and d["purpose"] in (
                        "Arrangement offer",
                        "Final confirmation",
                    ):
                        required(
                            data.get("attachment_checked"),
                            "Confirm that the correct seating photo was attached externally.",
                        )
                    d.update(sent_at=stamp(), sent_by=self.actor)
                    if (
                        d["purpose"] == "Arrangement offer"
                        and not accepted(x)
                        and not any(
                            t.get("kind") == "acceptance" and not t.get("done_at")
                            for t in x["tasks"]
                        )
                    ):
                        x["tasks"].append(
                            {
                                "id": uuid4().hex,
                                "title": "Follow up on guest acceptance",
                                "kind": "acceptance",
                                "owner": x["owner"],
                                "waiting_on": "Guest",
                                "due": (now() + timedelta(days=1)).isoformat(),
                            }
                        )
            elif action == "handoff":
                required(
                    data["recipient"].strip(),
                    "Record who reviewed the service handoff.",
                )
                current = service_record(x, p)
                x["handoff"] = dict(
                    hash=digest(current),
                    snapshot=current,
                    at=stamp(),
                    actor=self.actor,
                    **data,
                )
            elif action == "close":
                required(
                    data["reason"].strip() and next_action(x, p) == "Complete",
                    "Finish the booking / outcome and outstanding tasks before closing.",
                )
                x["closed_reason"] = data["reason"]
            elif action == "timer":
                if x.get("timer_start"):
                    seconds = (now() - instant(x.pop("timer_start"))).total_seconds()
                    x["handling_samples"].append(
                        {
                            "seconds": round(seconds, 1),
                            "actor": self.actor,
                            "at": stamp(),
                        }
                    )
                else:
                    x["timer_start"] = stamp()
            else:
                raise ValueError("Unknown workflow command.")

        return self.store.mutate(c["id"], c["revision"], self.actor, action, change)


def save_profile(store, p, expected_version):
    p = deepcopy(p)
    required(p["name"].strip(), "Enter the restaurant name.")
    ZoneInfo(p["timezone"])
    for k in ("call_start", "call_cutoff"):
        time.fromisoformat(p[k])
    required(
        p["call_start"] < p["call_cutoff"],
        "Calling hours must start before the cutoff.",
    )
    for k in (
        "duration_minutes",
        "min_spend_threshold",
        "manager_threshold",
        "buffer_minutes",
    ):
        if p[k] is not None:
            required(
                float(p[k]).is_integer()
                and 0 <= float(p[k]) <= 1440
                and (k == "buffer_minutes" or p[k] > 0),
                "Use positive whole-number policy settings; buffer can be zero.",
            )
            p[k] = int(p[k])
    ids = []
    for t in p["tables"]:
        required(
            t["id"].strip()
            and t["id"] not in ids
            and float(t["capacity"]).is_integer()
            and int(t["capacity"]) > 0,
            "Table IDs must be unique and capacities positive whole numbers.",
        )
        t["capacity"] = int(t["capacity"])
        ids.append(t["id"])
    for g in p["groupings"]:
        required(
            len(set(g["tables"])) >= 2 and set(g["tables"]) <= set(ids),
            "Groupings must use at least two known tables.",
        )
        required(
            0
            < int(g["capacity"])
            <= sum(t["capacity"] for t in p["tables"] if t["id"] in g["tables"]),
            "Grouping capacity must fit its tables.",
        )
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT data FROM settings WHERE key='profile'").fetchone()
        old = json.loads(row[0]) if row else profile()
        required(
            old["version"] == expected_version,
            "Settings changed in another tab. Refresh before saving.",
        )
        if db.execute("SELECT 1 FROM cases LIMIT 1").fetchone():
            required(
                old["name"] == p["name"] and old["timezone"] == p["timezone"],
                "Use a separate workspace for another restaurant or time zone once inquiries exist.",
            )
        p["version"] = expected_version + 1
        p["verified_at"] = stamp() if p["verified_by"] else ""
        db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?,?)", ("profile", json.dumps(p))
        )
    return p
