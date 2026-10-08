"""Read-only report snapshots. No assumed OpenTable dashboard schema or writes."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

MAX_BYTES = 5_000_000
MAX_ROWS = 20_000
FIELDS = {
    "reservation_id": "Reservation ID",
    "restaurant_id": "Restaurant ID",
    "guest_id": "Guest ID",
    "name": "Guest name",
    "first_name": "First name",
    "last_name": "Last name",
    "email": "Email",
    "phone": "Phone",
    "date": "Visit date",
    "time": "Visit time",
    "start": "Visit timestamp",
    "party_size": "Party size",
    "status": "Reservation status",
    "tables": "Table numbers",
    "guest_request": "Guest request",
    "visit_notes": "Visit notes",
    "guestbook_notes": "Guestbook notes",
    "venue_notes": "Venue notes",
    "tags": "Tags",
}
# Suggestions only, always presented for operator review. These are NOT a verified schema.
ALIASES = {
    "name": ["guest name", "name"],
    "first_name": ["first name", "guest first name"],
    "last_name": ["last name", "guest last name"],
    "email": ["email", "guest e-mail address", "guest email"],
    "phone": ["phone", "mobile phone", "guest phone"],
    "date": ["visit date", "reservation date", "date"],
    "time": ["visit time", "reservation time", "time"],
    "start": ["visit timestamp", "scheduled time"],
    "status": ["status", "state", "reservation status"],
    "tables": ["tables", "table numbers", "table number"],
}
INACTIVE = {"cancelled", "canceled", "no show", "no-show", "finished", "done"}
ACTIVE = {"confirmed", "seated", "arrived", "booked", "held", "hold"}


@dataclass(frozen=True)
class Report:
    filename: str
    digest: str
    headers: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    delimiter: str


@dataclass(frozen=True)
class Snapshot:
    report: Report
    kind: str
    mapping: dict[str, str]
    rows: tuple[dict, ...]
    warnings: tuple[str, ...]
    exported_at: datetime
    imported_at: datetime
    coverage_start: date
    coverage_end: date
    timezone: str

    def warnings_now(self, now=None):
        now = now or datetime.now(timezone.utc)
        age = (now - self.exported_at).total_seconds() / 3600
        result = list(self.warnings)
        result.append(
            f"Export age: {max(0, age):.1f} hours. This is a snapshot, not live availability."
        )
        if age > 4:
            result.append(
                "Export is over 4 hours old. Refresh it before making a seating decision."
            )
        return result


def read_report(data: bytes, filename: str) -> Report:
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Choose a non-empty CSV or TSV no larger than 5 MB.")
    if not filename.lower().endswith((".csv", ".tsv")):
        raise ValueError("Use CSV or TSV. API JSON examples are not dashboard reports.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Save this report as UTF-8 CSV or TSV, then upload again."
        ) from exc
    if "\x00" in text:
        raise ValueError("The file contains binary data. Use a UTF-8 CSV or TSV.")
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t")
        parsed = list(csv.reader(io.StringIO(text, newline=""), dialect, strict=True))
    except csv.Error as exc:
        raise ValueError(
            "Cannot read the delimiter or quoting. Use comma, semicolon or tab-separated text."
        ) from exc
    if not parsed:
        raise ValueError("The report is empty.")
    headers = tuple(x.strip() for x in parsed[0])
    if not all(headers) or len(set(headers)) != len(headers) or len(headers) > 150:
        raise ValueError("Use unique, non-empty column headings (at most 150).")
    rows = []
    for n, row in enumerate(parsed[1:], 2):
        if not row or all(not x.strip() for x in row):
            continue
        if len(row) != len(headers):
            raise ValueError(f"CSV record {n}: column count differs from the header.")
        rows.append(dict(zip(headers, row)))
        if len(rows) > MAX_ROWS:
            raise ValueError("Limit the report to 20,000 rows or fewer.")
    if not rows:
        raise ValueError(
            "The report has headers but no data. An empty report cannot establish availability."
        )
    return Report(
        filename,
        hashlib.sha256(data).hexdigest(),
        headers,
        tuple(rows),
        dialect.delimiter,
    )


def suggest_mapping(report: Report) -> dict[str, str]:
    norm = lambda s: re.sub(r"\s+", " ", s.lower().replace("_", " ")).strip()
    result = {}
    for field, title in FIELDS.items():
        candidates = {
            norm(title),
            norm(field),
            *[norm(x) for x in ALIASES.get(field, [])],
        }
        matches = [h for h in report.headers if norm(h) in candidates]
        if len(matches) == 1:
            result[field] = matches[0]
    return result


def parse_start(values: dict, date_order: str, tz: ZoneInfo) -> datetime:
    if values.get("start", "").strip():
        if not re.search(r"[Tt ]\d{2}:?\d{2}", values["start"].strip()):
            raise ValueError("Visit timestamp must include an explicit time, not only a date.")
        try:
            result = datetime.fromisoformat(
                values["start"].strip().replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                "Visit timestamp must be ISO 8601; alternatively map separate date and time columns."
            ) from exc
    else:
        raw = values.get("date", "").strip()
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            fmt = "%m/%d/%Y" if date_order == "MDY" else "%d/%m/%Y"
            day = datetime.strptime(raw, fmt).date()
        raw_time = values.get("time", "").strip().upper()
        clock = None
        for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I %p"):
            try:
                clock = datetime.strptime(raw_time, fmt).time()
                break
            except ValueError:
                pass
        if clock is None:
            raise ValueError("Visit time must be 24-hour HH:MM or 12-hour h:mm AM/PM.")
        result = datetime.combine(day, clock)
    if result.tzinfo is None:
        a, b = result.replace(tzinfo=tz, fold=0), result.replace(tzinfo=tz, fold=1)
        if (
            a.utcoffset() != b.utcoffset()
            or a.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != result
        ):
            raise ValueError(
                "Ambiguous or nonexistent daylight-saving time. Supply a timestamp with an explicit UTC offset."
            )
        result = a
    return result.astimezone(tz)


def validate_report(
    report,
    mapping,
    *,
    kind,
    date_order,
    timezone_name,
    exported_at,
    coverage_start,
    coverage_end,
    now=None,
):
    """Atomic validation. No rows are silently dropped and nothing is persisted."""
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(timezone_name)
    if kind not in ("reservations", "guests") or date_order not in ("MDY", "DMY"):
        raise ValueError("Select a report type and date order.")
    mapping = {k: v for k, v in mapping.items() if v}
    if any(k not in FIELDS or v not in report.headers for k, v in mapping.items()):
        raise ValueError("A mapped column does not exist in this report.")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Map each source column only once.")
    if kind == "reservations" and not (
        "party_size" in mapping
        and ("start" in mapping or {"date", "time"} <= mapping.keys())
    ):
        raise ValueError(
            "Map party size and either visit timestamp or both visit date and time."
        )
    if kind == "guests" and not {"guest_id", "email", "phone"} & mapping.keys():
        raise ValueError("Guestbook reports need a guest ID, email or phone column.")
    if exported_at.tzinfo is None or exported_at > now:
        raise ValueError("Export time needs a UTC offset and cannot be in the future.")
    if coverage_start > coverage_end:
        raise ValueError("Coverage end must be on or after coverage start.")
    rows, errors, warnings, ids = [], [], set(), set()
    for index, raw in enumerate(report.rows, 2):
        values = {k: raw[h] for k, h in mapping.items()}
        values["_record"] = index
        values["_name"] = (
            values.get("name")
            or " ".join(
                filter(None, [values.get("first_name"), values.get("last_name")])
            )
            or "Unnamed guest"
        )
        try:
            if kind == "reservations":
                values["_start"] = parse_start(values, date_order, tz)
                party = int(values["party_size"])
                if not 1 <= party <= 10000:
                    raise ValueError(
                        "Party size must be a positive whole number, at most 10,000."
                    )
                values["_party"] = party
                if not coverage_start <= values["_start"].date() <= coverage_end:
                    raise ValueError(
                        "Visit date is outside the declared report coverage."
                    )
                status = values.get("status", "").strip().lower()
                values["_active"] = status not in INACTIVE
                if status not in INACTIVE | ACTIVE:
                    warnings.add(
                        "Missing or unrecognized statuses remain in potentially active totals. Review them in OpenTable."
                    )
                rid = values.get("reservation_id", "").strip()
                if rid:
                    identity = (values.get("restaurant_id", "").strip(), rid)
                    if identity in ids:
                        raise ValueError(
                            "Duplicate reservation ID within the same restaurant. Export one current row per reservation."
                        )
                    ids.add(identity)
            rows.append(values)
        except (ValueError, OverflowError) as exc:
            errors.append(f"Record {index}: {exc}")
    if errors:
        raise ValueError(
            "\n".join(errors[:12])
            + (f"\n…and {len(errors) - 12} more errors." if len(errors) > 12 else "")
        )
    venues = {
        r.get("restaurant_id", "").strip()
        for r in rows
        if r.get("restaurant_id", "").strip()
    }
    if len(venues) > 1:
        raise ValueError(
            "This report includes multiple restaurants. Export one restaurant per session."
        )
    if "restaurant_id" not in mapping:
        warnings.add(
            "Restaurant ID is absent. Verify both files belong to the same restaurant."
        )
    if kind == "reservations" and "reservation_id" not in mapping:
        warnings.add(
            "Reservation IDs are absent. Rows are not deduplicated; verify the report contains no duplicates."
        )
    return Snapshot(
        report,
        kind,
        dict(mapping),
        tuple(rows),
        tuple(sorted(warnings)),
        exported_at,
        now,
        coverage_start,
        coverage_end,
        timezone_name,
    )


def guest_candidates(
    snapshot: Snapshot, *, email="", phone="", guest_id="", restaurant_id=""
):
    """Exact candidates only. Shared contact details never become an automatic merge."""

    def phone_key(value):
        return re.sub(r"[^0-9]", "", value)

    found = []
    for row in snapshot.rows:
        match = (
            guest_id
            and restaurant_id
            and row.get("guest_id") == guest_id
            and row.get("restaurant_id") == restaurant_id
        )
        match = match or (
            email.strip()
            and row.get("email", "").strip().casefold() == email.strip().casefold()
        )
        match = match or (
            len(phone_key(phone)) >= 7
            and phone_key(row.get("phone", "")) == phone_key(phone)
        )
        if match:
            found.append(row)
    return found
