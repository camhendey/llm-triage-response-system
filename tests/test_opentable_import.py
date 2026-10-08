"""Contract tests on synthetic reports, not claims of real export compatibility."""

from datetime import datetime, date, timezone
import pytest
from reservation_workbench.services.opentable_import import (
    read_report,
    suggest_mapping,
    validate_report,
    guest_candidates,
)

NOW = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)


def validate(text, **kw):
    report = read_report(text.encode("utf-8"), "synthetic.csv")
    args = dict(
        kind="reservations",
        date_order="MDY",
        timezone_name="America/Toronto",
        exported_at=NOW,
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        now=NOW,
    )
    args.update(kw)
    return validate_report(report, suggest_mapping(report), **args)


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_delimiters_bom_quotes_and_multiline_notes(delimiter):
    import csv, io

    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter)
    writer.writerow(
        ["Guest name", "Visit date", "Visit time", "Party size", "Guestbook notes"]
    )
    writer.writerow(
        ["Zoë", "2026-10-08", "7:30 PM", "4", 'He said "hello",\nallergy unconfirmed']
    )
    s = validate("\ufeff" + stream.getvalue())
    assert s.rows[0]["_name"] == "Zoë"
    assert s.rows[0]["_start"].hour == 19
    assert s.rows[0]["guestbook_notes"] == 'He said "hello",\nallergy unconfirmed'


def test_explicit_date_order():
    text = "Visit date,Visit time,Party size\n03/04/2026,19:30,4\n"
    assert validate(text).rows[0]["_start"].month == 3
    assert validate(text, date_order="DMY").rows[0]["_start"].month == 4


@pytest.mark.parametrize("stamp", ["2026-03-08T02:30:00", "2026-11-01T01:30:00"])
def test_dst_requires_offset(stamp):
    with pytest.raises(ValueError, match="daylight-saving"):
        validate(f"Visit timestamp,Party size\n{stamp},4\n")


def test_explicit_offset_is_respected():
    s = validate("Visit timestamp,Party size\n2026-11-01T01:30:00-04:00,4\n")
    assert s.rows[0]["_start"].utcoffset().total_seconds() == -14400


@pytest.mark.parametrize(
    "text,message",
    [
        ("Visit date,Visit time,Party size\n2026-10-08,19:00,2.5\n", "Record 2"),
        ("Visit date,Visit time,Party size\n2026-10-08,19:00,0\n", "positive"),
        ("Visit date,Visit time,Party size\nnot a date,19:00,2\n", "Record 2"),
        ("Visit date,Visit time,Party size\n2027-10-08,19:00,2\n", "coverage"),
        (
            "Visit date,Visit time,Party size,Reservation ID\n2026-10-08,19:00,2,R1\n2026-10-08,19:30,4,R1\n",
            "Duplicate",
        ),
        (
            "Visit date,Visit time,Party size,Restaurant ID\n2026-10-08,19:00,2,A\n2026-10-08,19:30,4,B\n",
            "multiple restaurants",
        ),
    ],
)
def test_invalid_rows_block_whole_report(text, message):
    with pytest.raises(ValueError, match=message):
        validate(text)


@pytest.mark.parametrize(
    "data", [b"A,A\n1,2\n", b"A,B\n1,2,3\n", b"A,B\n", b"", b"\x00test"]
)
def test_bad_files(data):
    with pytest.raises(ValueError):
        read_report(data, "report.csv")


def test_status_unknown_conservative_and_notes_not_merged():
    s = validate(
        "Visit date,Visit time,Party size,Status,Guest request,Guestbook notes\n2026-10-08,19:00,2,Canceled,,old note\n2026-10-08,20:00,4,Waitlisted,request,\n"
    )
    assert not s.rows[0]["_active"] and s.rows[1]["_active"]
    assert s.rows[0]["guest_request"] == ""
    assert "visit_notes" not in s.rows[0]
    assert any("unrecognized" in w for w in s.warnings)


def test_guest_shared_contact_returns_all_candidates():
    s = validate(
        "Guest ID,Email,Phone,Guestbook notes\nG1,a@example.invalid,+1 (555) 555-5555,one\nG2,A@example.invalid,15555555555,two\n",
        kind="guests",
    )
    assert len(guest_candidates(s, email="a@example.invalid")) == 2
    assert len(guest_candidates(s, phone="1-555-555-5555")) == 2
    assert not guest_candidates(s, email="a@other.invalid", phone="555")
    assert not guest_candidates(s, guest_id="G1")  # stable ID needs restaurant scope


def test_staleness_and_future_export():
    s = validate("Visit date,Visit time,Party size\n2026-10-08,19:00,2\n")
    assert any("over 4 hours" in w for w in s.warnings_now(NOW.replace(hour=21)))
    with pytest.raises(ValueError, match="future"):
        validate(
            "Visit date,Visit time,Party size\n2026-10-08,19:00,2\n",
            exported_at=NOW.replace(hour=17),
        )


def test_mapping_conflicts_and_unknown_headers():
    report = read_report(b"Date,Time,Party size\n2026-10-08,19:00,2\n", "test.csv")
    kwargs = dict(
        kind="reservations",
        date_order="MDY",
        timezone_name="UTC",
        exported_at=NOW,
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        now=NOW,
    )
    with pytest.raises(ValueError, match="only once"):
        validate_report(
            report,
            {
                "date": "Date",
                "time": "Time",
                "party_size": "Party size",
                "name": "Date",
            },
            **kwargs,
        )
    with pytest.raises(ValueError, match="does not exist"):
        validate_report(report, {"date": "bogus"}, **kwargs)


def test_formula_like_notes_remain_inert_text():
    s = validate(
        'Email,Guestbook notes\na@example.invalid,=HYPERLINK("https://example.invalid")\n',
        kind="guests",
    )
    assert s.rows[0]["guestbook_notes"].startswith("=HYPERLINK")


def test_timestamp_without_time_is_not_assumed_midnight():
    with pytest.raises(ValueError, match="explicit time"):
        validate("Visit timestamp,Party size\n2026-10-08,4\n")
