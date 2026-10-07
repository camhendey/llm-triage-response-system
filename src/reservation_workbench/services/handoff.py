"""Service handoff from canonical booking records."""

import csv
import io
from ..domain.models import BookingStatus
from ..rules.availability import hold_is_active


def daily_handoff(wb, day):
    rows = []
    for b in wb.repo.list_bookings():
        if b.start.astimezone(wb.cfg.tz).date() != day or not (
            b.status == BookingStatus.CONFIRMED or hold_is_active(b, wb.now())
        ):
            continue
        v = wb.load(b.inquiry_id) if b.inquiry_id else None

        def f(n):
            value = v.facts.value(n) if v else None
            return str(value).replace("_", " ") if value is not None else None

        pending = list(v.assessment.confirm_gaps) if v else []
        if v:
            pending += [x.message for x in v.assessment.blockers + v.assessment.reviews]
            if v.assessment.requested_change:
                pending.insert(0, "Requested change pending; booked allocation shown")
        rows.append(
            {
                "Guest": f("guest_name") or b.guest_label,
                "Status": b.status.value.title(),
                "Guests": b.party_size,
                "Tables": " + ".join(b.table_ids),
                "Start": b.start.astimezone(wb.cfg.tz).strftime("%H:%M"),
                "End": b.end.astimezone(wb.cfg.tz).strftime("%H:%M"),
                "Accessibility": f("accessibility") or "Unknown",
                "Allergies": f("allergies") or "Unknown",
                "Billing": f("billing") or "Unknown",
                "Occasion": f("occasion") or "Not recorded",
                "Outstanding": "; ".join(dict.fromkeys(pending)),
                "Hold expires": b.hold_expires_at.astimezone(wb.cfg.tz).isoformat()
                if b.hold_expires_at
                else "",
                "Booking": b.id,
                "Environment": "Simulated restaurant",
            }
        )
    return sorted(rows, key=lambda r: (r["Start"], r["Tables"]))


def handoff_csv(rows):
    s = io.StringIO()
    if rows:
        w = csv.DictWriter(s, fieldnames=list(rows[0]))
        w.writeheader()
        for row in rows:
            w.writerow(
                {
                    k: (
                        "'" + v
                        if isinstance(v, str) and v.startswith(("=", "+", "-", "@"))
                        else v
                    )
                    for k, v in row.items()
                }
            )
    return s.getvalue()
