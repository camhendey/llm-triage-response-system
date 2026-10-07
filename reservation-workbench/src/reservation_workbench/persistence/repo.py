"""Typed read/write helpers over ``Database``. No business rules live here."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ..domain.clock import iso, parse_iso
from ..domain.models import (
    ACTIVE_BOOKING_STATUSES,
    Booking,
    BookingStatus,
    Draft,
    Event,
    Inquiry,
    Interpretation,
    Message,
    Observation,
    Proposal,
    SeatingOption,
)
from .db import Database, dumps, loads


class Repo:
    def __init__(self, db: Database):
        self.db = db

    # ---- inquiries ----------------------------------------------------
    def insert_inquiry(self, inq: Inquiry) -> None:
        self.db.conn.execute(
            "INSERT INTO inquiries(id,guest_label,title,state,booking_id,record_version,handled_seq,handled_obs_seq,"
            "state_set_seq,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (inq.id, inq.guest_label, inq.title, inq.state.value, inq.booking_id, inq.record_version,
             inq.handled_seq, inq.handled_obs_seq, inq.state_set_seq, iso(inq.created_at), iso(inq.updated_at)),
        )

    def update_inquiry(self, inq: Inquiry) -> None:
        self.db.conn.execute(
            "UPDATE inquiries SET guest_label=?,title=?,state=?,booking_id=?,record_version=?,handled_seq=?,"
            "handled_obs_seq=?,state_set_seq=?,updated_at=? WHERE id=?",
            (inq.guest_label, inq.title, inq.state.value, inq.booking_id, inq.record_version, inq.handled_seq,
             inq.handled_obs_seq, inq.state_set_seq, iso(inq.updated_at), inq.id),
        )

    @staticmethod
    def _inquiry(r: sqlite3.Row) -> Inquiry:
        return Inquiry(
            id=r["id"], guest_label=r["guest_label"], title=r["title"], state=r["state"],
            booking_id=r["booking_id"], record_version=r["record_version"],
            handled_seq=r["handled_seq"], handled_obs_seq=r["handled_obs_seq"], state_set_seq=r["state_set_seq"],
            created_at=parse_iso(r["created_at"]), updated_at=parse_iso(r["updated_at"]),
        )

    def get_inquiry(self, inquiry_id: str) -> Inquiry | None:
        r = self.db.one("SELECT * FROM inquiries WHERE id=?", (inquiry_id,))
        return None if r is None else self._inquiry(r)

    def list_inquiries(self) -> list[Inquiry]:
        return [self._inquiry(r) for r in self.db.query("SELECT * FROM inquiries ORDER BY id")]

    # ---- messages -----------------------------------------------------
    def insert_message(self, m: Message) -> None:
        self.db.conn.execute(
            "INSERT INTO messages(id,inquiry_id,seq,direction,text,received_at,source) VALUES(?,?,?,?,?,?,?)",
            (m.id, m.inquiry_id, m.seq, m.direction.value, m.text, iso(m.received_at), m.source.value),
        )

    def messages(self, inquiry_id: str) -> list[Message]:
        rows = self.db.query("SELECT * FROM messages WHERE inquiry_id=? ORDER BY received_at, seq", (inquiry_id,))
        return [
            Message(id=r["id"], inquiry_id=r["inquiry_id"], seq=r["seq"], direction=r["direction"], text=r["text"],
                    received_at=parse_iso(r["received_at"]), source=r["source"])
            for r in rows
        ]

    def message_count(self, inquiry_id: str) -> int:
        return self.db.one("SELECT COUNT(*) AS n FROM messages WHERE inquiry_id=?", (inquiry_id,))["n"]

    # ---- interpretations ---------------------------------------------
    def insert_interpretation(self, it: Interpretation) -> None:
        self.db.conn.execute(
            "INSERT INTO interpretations(id,inquiry_id,message_ids,provider_mode,model,status,intents,ambiguities,"
            "uninterpreted,error,raw_output,latency_ms,usage,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (it.id, it.inquiry_id, dumps(it.message_ids), it.provider_mode, it.model, it.status, dumps(it.intents),
             dumps(it.ambiguities), dumps(it.uninterpreted), it.error, it.raw_output, it.latency_ms,
             dumps(it.usage), iso(it.created_at)),
        )

    def interpretations(self, inquiry_id: str) -> list[Interpretation]:
        rows = self.db.query("SELECT * FROM interpretations WHERE inquiry_id=? ORDER BY created_at, rowid", (inquiry_id,))
        return [
            Interpretation(
                id=r["id"], inquiry_id=r["inquiry_id"], message_ids=loads(r["message_ids"]),
                provider_mode=r["provider_mode"], model=r["model"], status=r["status"], intents=loads(r["intents"]),
                ambiguities=loads(r["ambiguities"]), uninterpreted=loads(r["uninterpreted"]), error=r["error"],
                raw_output=r["raw_output"], latency_ms=r["latency_ms"], usage=loads(r["usage"]),
                created_at=parse_iso(r["created_at"]),
            )
            for r in rows
        ]

    # ---- observations -------------------------------------------------
    def insert_observation(self, o: Observation) -> None:
        self.db.conn.execute(
            "INSERT INTO observations(id,inquiry_id,seq,field,value,source_type,message_id,span_start,span_end,quote,"
            "status,note,provider_mode,interpretation_id,observed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (o.id, o.inquiry_id, o.seq, o.field.value, dumps(o.value), o.source_type, o.message_id, o.span_start,
             o.span_end, o.quote, o.status.value, o.note, o.provider_mode, o.interpretation_id, iso(o.observed_at)),
        )

    def observations(self, inquiry_id: str) -> list[Observation]:
        rows = self.db.query("SELECT * FROM observations WHERE inquiry_id=? ORDER BY seq", (inquiry_id,))
        return [
            Observation(
                id=r["id"], inquiry_id=r["inquiry_id"], seq=r["seq"], field=r["field"], value=loads(r["value"]),
                source_type=r["source_type"], message_id=r["message_id"], span_start=r["span_start"],
                span_end=r["span_end"], quote=r["quote"], status=r["status"], note=r["note"],
                provider_mode=r["provider_mode"], interpretation_id=r["interpretation_id"],
                observed_at=parse_iso(r["observed_at"]),
            )
            for r in rows
        ]

    def next_obs_seq(self, inquiry_id: str) -> int:
        r = self.db.one("SELECT COALESCE(MAX(seq),0)+1 AS n FROM observations WHERE inquiry_id=?", (inquiry_id,))
        return r["n"]

    # ---- bookings -----------------------------------------------------
    def insert_booking(self, b: Booking) -> None:
        self.db.conn.execute(
            "INSERT INTO bookings(id,inquiry_id,guest_label,status,party_size,start_utc,end_utc,hold_expires_at,version,"
            "source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (b.id, b.inquiry_id, b.guest_label, b.status.value, b.party_size, iso(b.start), iso(b.end),
             iso(b.hold_expires_at), b.version, b.source, iso(b.created_at), iso(b.updated_at)),
        )
        for t in b.table_ids:
            self.db.conn.execute("INSERT INTO booking_tables(booking_id,table_id) VALUES(?,?)", (b.id, t))

    def update_booking(self, b: Booking, expected_version: int) -> None:
        """Optimistic update; raises if the stored version moved."""
        cur = self.db.conn.execute(
            "UPDATE bookings SET inquiry_id=?,guest_label=?,status=?,party_size=?,start_utc=?,end_utc=?,"
            "hold_expires_at=?,version=?,updated_at=? WHERE id=? AND version=?",
            (b.inquiry_id, b.guest_label, b.status.value, b.party_size, iso(b.start), iso(b.end),
             iso(b.hold_expires_at), b.version, iso(b.updated_at), b.id, expected_version),
        )
        if cur.rowcount != 1:
            raise StaleWrite(f"booking {b.id} changed since version {expected_version}")
        self.db.conn.execute("DELETE FROM booking_tables WHERE booking_id=?", (b.id,))
        for t in b.table_ids:
            self.db.conn.execute("INSERT INTO booking_tables(booking_id,table_id) VALUES(?,?)", (b.id, t))

    def _booking(self, r: sqlite3.Row) -> Booking:
        tables = [x["table_id"] for x in self.db.query(
            "SELECT table_id FROM booking_tables WHERE booking_id=? ORDER BY table_id", (r["id"],))]
        return Booking(
            id=r["id"], inquiry_id=r["inquiry_id"], guest_label=r["guest_label"], status=r["status"],
            table_ids=tables, party_size=r["party_size"], start=parse_iso(r["start_utc"]),
            end=parse_iso(r["end_utc"]), hold_expires_at=parse_iso(r["hold_expires_at"]), version=r["version"],
            source=r["source"], created_at=parse_iso(r["created_at"]), updated_at=parse_iso(r["updated_at"]),
        )

    def get_booking(self, booking_id: str) -> Booking | None:
        r = self.db.one("SELECT * FROM bookings WHERE id=?", (booking_id,))
        return None if r is None else self._booking(r)

    def list_bookings(self, statuses: tuple[BookingStatus, ...] | None = None) -> list[Booking]:
        if statuses:
            qs = ",".join("?" for _ in statuses)
            rows = self.db.query(f"SELECT * FROM bookings WHERE status IN ({qs}) ORDER BY start_utc, id",
                                 tuple(s.value for s in statuses))
        else:
            rows = self.db.query("SELECT * FROM bookings ORDER BY start_utc, id")
        return [self._booking(r) for r in rows]

    def active_bookings(self) -> list[Booking]:
        return self.list_bookings(ACTIVE_BOOKING_STATUSES)

    # ---- proposals ----------------------------------------------------
    def insert_proposal(self, p: Proposal) -> None:
        self.db.conn.execute(
            "INSERT INTO proposals(id,inquiry_id,kind,source_record_version,policy_version,booking_id,booking_version,"
            "option,party_size,rule_results,required_decisions,status,approved_at,approval_reason,created_at,"
            "status_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p.id, p.inquiry_id, p.kind.value, p.source_record_version, p.policy_version, p.booking_id,
             p.booking_version, p.option.model_dump_json(), p.party_size,
             dumps([r.model_dump(mode="json") for r in p.rule_results]), dumps(p.required_decisions),
             p.status.value, iso(p.approved_at), p.approval_reason, iso(p.created_at), p.status_reason),
        )

    def set_proposal_status(self, proposal_id: str, status: str, reason: str | None = None,
                            approved_at: datetime | None = None, approval_reason: str | None = None) -> None:
        if approved_at is not None:
            self.db.conn.execute(
                "UPDATE proposals SET status=?,status_reason=?,approved_at=?,approval_reason=? WHERE id=?",
                (status, reason, iso(approved_at), approval_reason, proposal_id),
            )
        else:
            self.db.conn.execute("UPDATE proposals SET status=?,status_reason=? WHERE id=?",
                                 (status, reason, proposal_id))

    def _proposal(self, r: sqlite3.Row) -> Proposal:
        from ..domain.models import RuleResult

        return Proposal(
            id=r["id"], inquiry_id=r["inquiry_id"], kind=r["kind"], source_record_version=r["source_record_version"],
            policy_version=r["policy_version"], booking_id=r["booking_id"], booking_version=r["booking_version"],
            option=SeatingOption.model_validate_json(r["option"]), party_size=r["party_size"],
            rule_results=[RuleResult.model_validate(x) for x in loads(r["rule_results"])],
            required_decisions=loads(r["required_decisions"]), status=r["status"],
            approved_at=parse_iso(r["approved_at"]), approval_reason=r["approval_reason"],
            created_at=parse_iso(r["created_at"]), status_reason=r["status_reason"],
        )

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        r = self.db.one("SELECT * FROM proposals WHERE id=?", (proposal_id,))
        return None if r is None else self._proposal(r)

    def proposals(self, inquiry_id: str) -> list[Proposal]:
        return [self._proposal(r) for r in self.db.query(
            "SELECT * FROM proposals WHERE inquiry_id=? ORDER BY created_at, id", (inquiry_id,))]

    # ---- drafts -------------------------------------------------------
    def upsert_draft(self, d: Draft) -> None:
        self.db.conn.execute(
            "INSERT INTO drafts(id,inquiry_id,purpose,text,generated_text,source_record_version,facts_hash,"
            "policy_version,proposal_id,booking_version,validation,status,approved_at,approved_record_version,"
            "provider_mode,prose_source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET text=excluded.text,validation=excluded.validation,status=excluded.status,"
            "approved_at=excluded.approved_at,approved_record_version=excluded.approved_record_version,"
            "updated_at=excluded.updated_at",
            (d.id, d.inquiry_id, d.purpose, d.text, d.generated_text, d.source_record_version, d.facts_hash,
             d.policy_version, d.proposal_id, d.booking_version, dumps(d.validation), d.status, iso(d.approved_at),
             d.approved_record_version, d.provider_mode, d.prose_source, iso(d.created_at), iso(d.updated_at)),
        )

    def _draft(self, r: sqlite3.Row) -> Draft:
        return Draft(
            id=r["id"], inquiry_id=r["inquiry_id"], purpose=r["purpose"], text=r["text"],
            generated_text=r["generated_text"], source_record_version=r["source_record_version"],
            facts_hash=r["facts_hash"], policy_version=r["policy_version"], proposal_id=r["proposal_id"],
            booking_version=r["booking_version"], validation=loads(r["validation"]), status=r["status"],
            approved_at=parse_iso(r["approved_at"]), approved_record_version=r["approved_record_version"],
            provider_mode=r["provider_mode"], prose_source=r["prose_source"], created_at=parse_iso(r["created_at"]),
            updated_at=parse_iso(r["updated_at"]),
        )

    def get_draft(self, draft_id: str) -> Draft | None:
        r = self.db.one("SELECT * FROM drafts WHERE id=?", (draft_id,))
        return None if r is None else self._draft(r)

    def drafts(self, inquiry_id: str) -> list[Draft]:
        return [self._draft(r) for r in self.db.query(
            "SELECT * FROM drafts WHERE inquiry_id=? ORDER BY created_at, id", (inquiry_id,))]

    # ---- events -------------------------------------------------------
    def find_event(self, idempotency_key: str) -> Event | None:
        r = self.db.one("SELECT * FROM events WHERE idempotency_key=?", (idempotency_key,))
        return None if r is None else self._event(r)

    def insert_event(self, e: Event) -> None:
        self.db.conn.execute(
            "INSERT INTO events(id,idempotency_key,inquiry_id,booking_id,actor,event_type,before,after,reason,"
            "created_at,mode,proposal_id,record_version,booking_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.id, e.idempotency_key, e.inquiry_id, e.booking_id, e.actor, e.event_type, dumps(e.before),
             dumps(e.after), e.reason, iso(e.created_at), e.mode, e.proposal_id, e.record_version, e.booking_version),
        )

    @staticmethod
    def _event(r: sqlite3.Row) -> Event:
        return Event(
            id=r["id"], idempotency_key=r["idempotency_key"], inquiry_id=r["inquiry_id"], booking_id=r["booking_id"],
            actor=r["actor"], event_type=r["event_type"], before=loads(r["before"]), after=loads(r["after"]),
            reason=r["reason"], created_at=parse_iso(r["created_at"]), mode=r["mode"], proposal_id=r["proposal_id"],
            record_version=r["record_version"], booking_version=r["booking_version"],
        )

    def events(self, inquiry_id: str | None = None, event_type: str | None = None) -> list[Event]:
        sql = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if inquiry_id is not None:
            sql += " AND inquiry_id=?"
            params.append(inquiry_id)
        if event_type is not None:
            sql += " AND event_type=?"
            params.append(event_type)
        sql += " ORDER BY seq"
        return [self._event(r) for r in self.db.query(sql, tuple(params))]


class StaleWrite(RuntimeError):
    pass
