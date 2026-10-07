"""CSV import of guest messages with row-level validation.

Required column: ``message``. Optional: ``guest_label``, ``received_at`` (ISO
8601 with offset; naive values are interpreted in the restaurant timezone and
reported), ``inquiry_id`` (append to an existing inquiry). Valid rows are
imported even when other rows fail; every failure is reported with its row
number and reason.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from ..domain.models import MessageSource
from .workbench import Workbench


@dataclass
class RowResult:
    row: int
    ok: bool
    message: str
    inquiry_id: str | None = None


@dataclass
class ImportReport:
    rows: list[RowResult] = field(default_factory=list)
    fatal: str | None = None

    @property
    def imported(self) -> int:
        return sum(1 for r in self.rows if r.ok)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if not r.ok)


def import_csv(wb: Workbench, content: str | bytes, batch_key: str, interpret: bool = False) -> ImportReport:
    rep = ImportReport()
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            rep.fatal = "File is not UTF-8 text."
            return rep
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        rep.fatal = "CSV is empty (no header row)."
        return rep
    cols = [c.strip().lower() for c in reader.fieldnames]
    if "message" not in cols:
        rep.fatal = f"CSV must have a 'message' column; found {cols}."
        return rep
    tz = wb.cfg.tz
    for i, raw in enumerate(reader, start=2):  # row 1 is the header
        row = {(k or "").strip().lower(): (v if v is not None else "") for k, v in raw.items()}
        if None in raw:
            rep.rows.append(RowResult(i, False, "Row has more values than header columns."))
            continue
        msg = str(row.get("message", "")).strip()
        if not msg:
            rep.rows.append(RowResult(i, False, "Empty message."))
            continue
        label = str(row.get("guest_label", "")).strip() or f"CSV guest row {i}"
        at_raw = str(row.get("received_at", "")).strip()
        note = ""
        if at_raw:
            try:
                at = datetime.fromisoformat(at_raw)
            except ValueError:
                rep.rows.append(RowResult(i, False, f"received_at {at_raw!r} is not ISO 8601."))
                continue
            if at.tzinfo is None:
                at = at.replace(tzinfo=tz)
                note = f" (naive timestamp interpreted in {wb.cfg.restaurant.timezone})"
        else:
            at = wb.now()
            note = " (no timestamp; used current clock)"
        target = str(row.get("inquiry_id", "")).strip()
        key = f"{batch_key}:row{i}"
        if target:
            if wb.repo.get_inquiry(target) is None:
                rep.rows.append(RowResult(i, False, f"inquiry_id {target} does not exist."))
                continue
            res = wb.add_message(target, msg, at, key=key, source=MessageSource.CSV_IMPORT)
            iid = target
        else:
            res = wb.create_inquiry(label, msg, at, key=key, source=MessageSource.CSV_IMPORT)
            iid = res.data.get("inquiry_id")
        if not res.ok:
            rep.rows.append(RowResult(i, False, res.message))
            continue
        if interpret and iid:
            wb.interpret(iid)
        rep.rows.append(RowResult(i, True, ("Imported" if not res.duplicate else "Already imported") + note, iid))
    return rep
