"""Shared labels, scoped connections and guarded command dispatch."""

from contextlib import contextmanager
from uuid import uuid4
from ..services.bootstrap import open_workbench
from ..services.workbench import CommandResult, DomainError

GROUPS = {
    "Reservation": [
        "party_size",
        "requested_date",
        "requested_time",
        "requested_duration_minutes",
    ],
    "Requirements": ["accessibility", "allergies", "minors", "billing"],
    "Guest & preferences": [
        "guest_name",
        "contact_email",
        "contact_phone",
        "occasion",
        "preferred_area",
        "preferred_table",
        "split_seating_ok",
    ],
}
LABELS = {
    "none": "None reported",
    "step_free_required": "Step-free required",
    "other_needs": "Other access needs",
    "present": "Minors attending",
    "one_bill": "One bill",
    "separate_bills": "Separate bills",
    "no_preference": "No preference",
    "yes": "Yes",
    "no": "No",
}
PURPOSE_LABELS = {
    "availability_offer": "Available seating offer",
    "clarification": "Request missing information",
    "confirmation": "Booking confirmation",
    "hold_offer": "Hold details",
    "alternative_offer": "Alternative seating or time",
    "change_unavailable": "Change unavailable",
    "change_available": "Proposed booking change",
    "change_confirmed": "Booking change confirmed",
    "cancellation_received": "Cancellation request received",
    "cancellation_confirmed": "Cancellation confirmation",
    "decline": "Request declined",
    "private_events_referral": "Private-events referral",
    "hold_released": "Hold released",
}


def pretty(value):
    return (
        "Not provided"
        if value is None
        else LABELS.get(str(value), str(value).replace("_", " "))
    )


def guest(v):
    return v.facts.value("guest_name") or v.inquiry.guest_label.replace(
        "Synthetic Guest ", "Guest "
    )


def when(dt, cfg, full=True):
    if not dt:
        return "Date or time needed"
    return dt.astimezone(cfg.tz).strftime("%a %d %b, %H:%M" if full else "%H:%M")


def key():
    return "nicegui:" + uuid4().hex


@contextmanager
def connection(kind):
    """Never share a SQLite connection between browser clients or worker threads."""
    wb = open_workbench(kind)
    try:
        yield wb
    finally:
        wb.db.close()


class _FailedCommand(Exception):
    def __init__(self, result):
        self.result = result


def execute(kind, fn, expected=None):
    """Check the screen version within the same transaction as its command.

    The closure owns its idempotency key; a retried click cannot repeat a write.
    Each invocation opens its connection in the calling worker thread.
    """
    with connection(kind) as wb:
        try:
            with wb.db.transaction():
                if expected:
                    wb._check_version(wb._inq(expected[0]), expected[1])
                    if len(expected) > 2:
                        current = wb.load(expected[0])
                        latest_event = current.events[-1].id if current.events else None
                        if latest_event != expected[2]:
                            raise DomainError(
                                "stale_screen",
                                "This inquiry changed in another action or tab. Refresh and review the latest record before saving.",
                            )
                result = fn(wb)
                if not result.ok:
                    raise _FailedCommand(result)
                return result
        except _FailedCommand as exc:
            return exc.result
        except DomainError as exc:
            return CommandResult(ok=False, code=exc.code, message=exc.message)
