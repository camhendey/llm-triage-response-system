"""Offline pattern interpreter: limited, deterministic, and explicit about it.

This is *not* a language model and does not pretend to be one. It recognises a
documented set of English phrasings (see ``OFFLINE_SCOPE``) and cites the exact
span for every fact. Sentences it cannot interpret are returned as
``uninterpreted`` so the coordinator reads them; a message with nothing
recognisable returns ``status="unsupported"`` rather than a canned answer.
"""

from __future__ import annotations

import re
import time as _time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..domain.models import FieldName, Intent
from .base import (
    ExtractedFact,
    InterpretationResult,
    InterpretContext,
    MessageInput,
    ProseRequest,
    ProseResult,
)

OFFLINE_SCOPE = """\
Offline pattern interpreter (deterministic, English only). It recognises:
- party size written as digits or words with a unit ("12 people", "party of 8", "table for four", "dinner for 7",
  "30 seats"); counts describing part of the group ("two guests use wheelchairs") are not party sizes;
- dates with a month name or ISO form, "today/tonight/tomorrow"; weekday-only references are flagged for review;
- clock times with am/pm or 24-hour form; bare hours ("at 6") are assumed pm and flagged as an assumption;
- emails, North-American phone numbers, "my name is ..." and simple sign-offs;
- accessibility, minors, allergy, billing, occasion, area/table and split-seating phrases from a fixed list;
- cancellation / change / booking intent keywords and instruction-like guest text.
Anything else is returned as uninterpreted text for the coordinator to read. It does not understand
sarcasm, other languages, implied facts or multi-step reasoning."""

WORDNUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "twenty-one": 21, "twenty-two": 22,
    "twenty-three": 23, "twenty-four": 24, "twenty-five": 25, "twenty-six": 26, "thirty": 30, "forty": 40,
    "a couple": 2, "a dozen": 12, "dozen": 12,
}
NUM = r"(\d{1,3}|" + "|".join(sorted((re.escape(k) for k in WORDNUM), key=len, reverse=True)) + r")"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
MONTH_ABBR = {k[:3]: v for k, v in MONTHS.items()}
MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_RE = r"\b(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b"

NEG_CUE = re.compile(r"\b(no|not|nobody|no one|none|without|never|n't)\b[^.;!?]{0,25}$", re.I)
SUBGROUP_VERB = re.compile(r"\s+(?:uses?|has|have|needs?|requires?|is allergic|are allergic|is vegan|are vegan|"
                           r"is vegetarian|are vegetarian|cannot|can't|is in a wheelchair|are in wheelchairs|"
                           r"is celiac|are celiac|is coeliac|will need)\b")
CORRECTION_CUE = re.compile(r"\b(correction|actually|instead|now|update|updated|change[sd]?|make it|rather|not)\b", re.I)


def _num(s: str) -> int:
    s = s.lower().strip()
    return int(s) if s.isdigit() else WORDNUM[s]


class _Hit:
    __slots__ = ("field", "value", "start", "end", "status", "note")

    def __init__(self, field, value, start, end, status="extracted", note=None):
        self.field, self.value, self.start, self.end, self.status, self.note = field, value, start, end, status, note


def _sentences(text: str) -> list[tuple[int, int]]:
    spans = []
    start = 0
    for m in re.finditer(r"[.!?;\n]+(?=\s|$)|\n", text):
        end = m.start()
        if text[start:end].strip():
            spans.append((start, end))
        start = m.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    # strip leading whitespace in spans
    out = []
    for s, e in spans:
        while s < e and text[s].isspace():
            s += 1
        out.append((s, e))
    return out


TRIVIAL = re.compile(
    r"^(hi|hello|hey|good (morning|afternoon|evening)|dear [\w ]+|thanks?( you)?( so much)?( in advance)?|thank you|"
    r"cheers|best( regards)?|regards|kind regards|warm regards|sincerely|looking forward( to (it|hearing from you))?|"
    r"please (let me know|advise|confirm)|let me know|talk soon|appreciate it|much appreciated|ok(ay)?|great|perfect|"
    r"sounds good|that works|sorry for the (?:trouble|inconvenience|short notice)|apologies(?: for [a-z ]+)?|hope (you're|you are) well|[A-Z][a-z]+( [A-Z][a-z]+)?|- ?[A-Z][a-z]+)[\s,!]*$",
    re.I,
)


class OfflineRulesProvider:
    mode = "offline_rules"

    def describe(self) -> str:
        return OFFLINE_SCOPE

    # ------------------------------------------------------------ interpret
    def interpret(self, messages: list[MessageInput], ctx: InterpretContext) -> InterpretationResult:
        t0 = _time.perf_counter()
        tz = ZoneInfo(ctx.timezone)
        facts: list[ExtractedFact] = []
        intents: set[str] = set()
        ambiguities: list[str] = []
        uninterpreted: list[str] = []
        table_ids = {t.upper() for t in ctx.table_ids}
        for m in messages:
            if not m.is_new:
                continue
            # Short acceptance is resolved only against a reported outbound offer,
            # and remains review-required rather than committing a booking.
            acceptance = re.fullmatch(r"\s*(?:yes[,! ]*)?(?:(?:the )?(later|earlier|first|second) (?:option|time)|that(?: time)?|that works|yes|sounds good)(?: (?:works|is fine|please))?[.! ]*", m.text, re.I)
            prior = [x for x in messages if x.direction == "outbound_reported" and x.received_at <= m.received_at]
            if acceptance and prior:
                offer = prior[-1]
                dates = re.findall(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), ([A-Za-z]+ \d{1,2}, \d{4})", offer.text)
                starts = re.findall(r"(?:from |^- )(\d{1,2}:\d{2} [AP]M) to", offer.text, re.M)
                choices = list(dict.fromkeys(starts))
                which = (acceptance.group(1) or "").lower()
                chosen = None
                if len(choices) == 1: chosen = choices[0]
                elif choices and which in ("later", "earlier"):
                    ordered = sorted(choices, key=lambda t: datetime.strptime(t, "%I:%M %p").time())
                    chosen = ordered[-1 if which == "later" else 0]
                elif choices and which in ("first", "second") and len(choices) >= (2 if which == "second" else 1):
                    chosen = choices[1 if which == "second" else 0]
                if chosen and len(set(dates)) == 1:
                    day = datetime.strptime(dates[0], "%B %d, %Y").date().isoformat()
                    tm = datetime.strptime(chosen, "%I:%M %p").strftime("%H:%M")
                    for field, value in ((FieldName.REQUESTED_DATE, day), (FieldName.REQUESTED_TIME, tm)):
                        facts.append(ExtractedFact(field=field, value=value, message_id=m.id, quote=m.text,
                            status="needs_review", note=f"Acceptance interpreted using reported reply {offer.id}; coordinator must confirm."))
                    intents.add("provide_details")
                    continue
            hits, m_intents, m_amb, m_unint = self._interpret_one(m, tz, table_ids)
            intents |= m_intents
            ambiguities += m_amb
            uninterpreted += m_unint
            for h in hits:
                facts.append(ExtractedFact(field=h.field, value=h.value, message_id=m.id,
                                           quote=m.text[h.start:h.end], span_start=h.start, span_end=h.end,
                                           status=h.status, note=h.note))
        if not facts and not intents and not any(a.startswith("GUEST-INSTRUCTION") for a in ambiguities):
            status = "unsupported"
        elif uninterpreted:
            status = "partial"
        else:
            status = "ok"
        return InterpretationResult(
            provider_mode=self.mode, model="offline-pattern-v1", status=status, facts=facts,
            intents=sorted(intents), ambiguities=ambiguities, uninterpreted=uninterpreted,
            latency_ms=int((_time.perf_counter() - t0) * 1000),
            error=None if status != "unsupported" else "outside offline interpreter scope; manual review required",
        )

    def draft_prose(self, req: ProseRequest) -> ProseResult:
        # Offline drafting is fully deterministic: no model-written prose.
        return ProseResult(ok=False, error="offline mode uses deterministic templates only", provider_mode=self.mode)

    # ------------------------------------------------------------ internals
    def _interpret_one(self, m: MessageInput, tz: ZoneInfo, table_ids: set[str]):
        text = m.text
        low = text.lower()
        local = m.received_at.astimezone(tz)
        hits: list[_Hit] = []
        covered: list[tuple[int, int]] = []
        intents: set[str] = set()
        amb: list[str] = []

        def add(h: _Hit):
            hits.append(h)
            covered.append((h.start, h.end))

        # ---- contact --------------------------------------------------
        for mm in re.finditer(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text):
            add(_Hit(FieldName.CONTACT_EMAIL, mm.group(0).lower().rstrip("."), mm.start(), mm.end()))
        for mm in re.finditer(r"(?<!\d)(?:\+?1[\s.-]?)?\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-](\d{4})(?!\d)", text):
            add(_Hit(FieldName.CONTACT_PHONE, f"{mm.group(1)}-{mm.group(2)}-{mm.group(3)}", mm.start(), mm.end()))
        for mm in re.finditer(r"\b(?:my name is|this is|name'?s)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text):
            add(_Hit(FieldName.GUEST_NAME, mm.group(1), mm.start(1), mm.end(1)))
        mm = re.search(r"(?:^|\n)\s*(?:thanks|thank you|cheers|best|regards|best regards|kind regards)[,!]?\s*\n\s*"
                       r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s*$", text, re.I)
        if mm:
            add(_Hit(FieldName.GUEST_NAME, mm.group(1), mm.start(1), mm.end(1)))

        # ---- party size -------------------------------------------------
        party_hits: list[_Hit] = []
        unit = r"(?:people|persons|guests|adults|of us|pax|diners|ppl|seats|attendees|ppl\.)"
        pats = [
            rf"\b{NUM}\s+{unit}\b",
            rf"\b(?:party|group|table|booking|reservation|headcount|dinner|lunch|brunch|breakfast|space)\s+(?:of|for|is|at|:)\s*{NUM}\b(?!\s*(?:pm|am|:\d|o'clock|th\b|st\b|nd\b|rd\b|hours?|minutes?|mins?))",
            rf"\bfor\s+{NUM}(?=\s*(?:[.!?]|$|on\b|this\b|tomorrow\b|tonight\b|next\b))",
            rf"\bwe(?:'re| are| will be|'ll be)\s+(?:a (?:group|party) of\s+)?{NUM}\b(?!\s*(?:pm|am|:\d))",
            rf"\b(?:make it|change (?:it )?to|now|increase(?:d)? to|up to|down to|bump (?:it )?to|reduce (?:it )?to)\s+{NUM}\b(?!\s*(?:pm|am|:\d|o'clock|th\b))(?=[^.;!?]*\b(?:people|guests|us|party|group|headcount|instead|seats)\b|\s*(?:people|guests|instead|total))",
        ]
        seen_spans = set()
        for p in pats:
            for mm in re.finditer(p, low):
                g = mm.group(1)
                s = mm.start(1)
                if (s, mm.end(1)) in seen_spans:
                    continue
                if low[max(0, s - 4):s] == "not ":
                    continue
                if SUBGROUP_VERB.match(low, mm.end()):
                    continue  # "two guests use wheelchairs" describes part of the group, not its size
                try:
                    n = _num(g)
                except KeyError:
                    continue
                seen_spans.add((s, mm.end(1)))
                party_hits.append(_Hit(FieldName.PARTY_SIZE, n, mm.start(), mm.end()))
        kids = re.search(rf"\b{NUM}\s+(?:kids|children|minors|toddlers|teens|teenagers)\b", low)
        adults = re.search(rf"\b{NUM}\s+adults\b", low)
        if kids and adults:
            total = _num(adults.group(1)) + _num(kids.group(1))
            party_hits = [h for h in party_hits if not (h.start == adults.start())]
            party_hits.append(_Hit(FieldName.PARTY_SIZE, total, adults.start(), kids.end(), "needs_review",
                                   f"summed {adults.group(1)} adults + {kids.group(1)} children"))
        distinct = sorted({h.value for h in party_hits})
        if len(distinct) == 1:
            add(party_hits[0])
        elif len(distinct) > 1:
            party_hits.sort(key=lambda h: h.start)
            last = party_hits[-1]
            before = low[party_hits[0].end:last.start]
            if CORRECTION_CUE.search(before) or CORRECTION_CUE.search(low[last.start - 15:last.start]) or \
                    re.search(r"\bnot\s+\d", low[last.end:last.end + 12]):
                last.note = f"later value in message replaces {', '.join(str(h.value) for h in party_hits[:-1])}"
                add(last)
            else:
                last.status = "needs_review"
                last.note = f"several party sizes mentioned: {distinct}"
                add(last)
            for h in party_hits[:-1]:
                covered.append((h.start, h.end))

        # ---- dates --------------------------------------------------------
        date_hits = self._dates(text, low, local)
        weekday_hits = [(mm.start(), mm.end(), mm.group(1)) for mm in re.finditer(WEEKDAY_RE, low)
                        if not re.match(r"sat\b|sun\b|mon\b|wed\b", low[mm.start():mm.end() + 1]) or
                        len(mm.group(1)) > 3]
        rel = re.search(r"\b(tonight|today|tomorrow)\b", low)
        if date_hits:
            chosen = self._choose(date_hits, low)
            if chosen is not None:
                if weekday_hits:
                    wd_name = weekday_hits[0][2][:3]
                    actual = date.fromisoformat(chosen.value).strftime("%a").lower()
                    if wd_name != actual:
                        chosen.status = "needs_review"
                        chosen.note = (f"weekday '{weekday_hits[0][2]}' does not match "
                                       f"{date.fromisoformat(chosen.value):%A %B %d}")
                    covered.append(weekday_hits[0][:2])
                add(chosen)
        elif rel:
            word = rel.group(1)
            d = local.date() + (timedelta(days=1) if word == "tomorrow" else timedelta(0))
            add(_Hit(FieldName.REQUESTED_DATE, d.isoformat(), rel.start(), rel.end(), "extracted",
                     f"'{word}' resolved relative to message time {local:%Y-%m-%d %H:%M %Z}"))
        elif weekday_hits:
            s, e, wd = weekday_hits[0]
            idx = [w[:3] for w in WEEKDAYS].index(wd[:3])
            delta = (idx - local.weekday()) % 7
            mod = re.search(r"\b(this|next|coming)\s+$", low[max(0, s - 8):s])
            if delta == 0:
                delta = 7
            if mod and mod.group(1) == "next" and delta < 7:
                pass  # "next Friday" is genuinely ambiguous; keep nearest candidate and flag
            cand = local.date() + timedelta(days=delta)
            add(_Hit(FieldName.REQUESTED_DATE, cand.isoformat(), s - (len(mod.group(0)) if mod else 0), e,
                     "needs_review", f"weekday-only reference; nearest {wd.title()} after message is {cand:%B %d}, "
                                     "but the guest may mean a later week"))

        # ---- times --------------------------------------------------------
        th = self._times(text, low)
        if th:
            add(th)
        dur = re.search(r"\bfor\s+(\d+(?:\.\d+)?|" + "|".join(k for k in WORDNUM if " " not in k) +
                        r"|two and a half)\s*(hours?|hrs?)\b", low)
        if dur:
            g = dur.group(1)
            hours = 2.5 if g == "two and a half" else (float(g) if g[0].isdigit() else WORDNUM[g])
            add(_Hit(FieldName.REQUESTED_DURATION, int(round(hours * 60)), dur.start(), dur.end()))

        # ---- negated lists ("no accessibility needs, minors or allergies") ----
        for mm in re.finditer(r"\b(?:no|without|none of|zero|nobody with)\s+([a-z ,/'-]+?)(?=[.;!?\n]|$|\bbut\b)", low):
            items = re.split(r",|\bor\b|\band\b|/", mm.group(1))
            for it in items:
                it = re.sub(r"^(?:no|without|any)\s+", "", it.strip())
                if not it:
                    continue
                f = None
                if re.match(r"(accessibility|mobility|access|special access|wheelchair|accessible)", it):
                    f, v = FieldName.ACCESSIBILITY, "none"
                elif re.match(r"(minors|kids|children|child|under[- ]?19s?|under[- ]?18s?|little ones)", it):
                    f, v = FieldName.MINORS, "none"
                elif re.match(r"(allerg|dietary|food allerg|restrictions)", it):
                    f, v = FieldName.ALLERGIES, "none"
                elif re.match(r"(special )?occasion|celebration", it):
                    f, v = FieldName.OCCASION, "none"
                if f is not None:
                    rel_s = mm.start(1) + mm.group(1).find(it)
                    add(_Hit(f, v, mm.start(), rel_s + len(it)))

        # ---- accessibility ----------------------------------------------
        if not any(h.field == FieldName.ACCESSIBILITY for h in hits):
            for mm in re.finditer(r"\b(wheelchairs?|mobility (?:aid|scooter|device|issues?)|walker|crutches|"
                                  r"(?:can(?:no|')t|cannot|unable to) (?:do|manage|climb|use) (?:the )?stairs|"
                                  r"no stairs|step[- ]free|accessible (?:seating|table|entrance|spot))", low):
                if NEG_CUE.search(low[max(0, mm.start() - 30):mm.start()]) and "no stairs" not in mm.group(0) \
                        and "can" not in mm.group(0):
                    add(_Hit(FieldName.ACCESSIBILITY, "none", mm.start(), mm.end(), "needs_review",
                             "negated accessibility phrase; confirm no needs"))
                else:
                    add(_Hit(FieldName.ACCESSIBILITY, "step_free_required", mm.start(), mm.end()))
                break
            else:
                mm = re.search(r"\b(hard of hearing|deaf|service (?:dog|animal)|visually impaired|blind|"
                               r"low vision|guide dog)\b", low)
                if mm:
                    add(_Hit(FieldName.ACCESSIBILITY, "other_needs", mm.start(), mm.end(), "extracted",
                             f"detail: {text[mm.start():mm.end()]}"))
                else:
                    mm = re.search(r"\b(all (?:of us )?(?:can|are fine with) (?:do )?stairs|stairs are fine|"
                                   r"stairs (?:are|is) (?:not a problem|no problem|ok|okay))\b", low)
                    if mm:
                        add(_Hit(FieldName.ACCESSIBILITY, "none", mm.start(), mm.end()))

        # ---- minors -------------------------------------------------------
        if not any(h.field == FieldName.MINORS for h in hits):
            mm = re.search(r"\b(all adults|adults only|everyone is (?:over|19\+|of age)|all (?:over|19\+))\b", low)
            if mm:
                add(_Hit(FieldName.MINORS, "none", mm.start(), mm.end()))
            else:
                mm = re.search(rf"\b(?:{NUM}\s+)?(kids|children|child|minors|toddlers?|babies|baby|teens|teenagers|"
                               r"high ?chairs?|(?:a )?(?:son|daughter|nephew|niece)s? (?:aged|age) \d+|under[- ]?19)\b",
                               low)
                if mm and not NEG_CUE.search(low[max(0, mm.start() - 20):mm.start()]):
                    add(_Hit(FieldName.MINORS, "present", mm.start(), mm.end(), "extracted",
                             f"detail: {text[mm.start():mm.end()]}"))

        # ---- allergies ----------------------------------------------------
        if not any(h.field == FieldName.ALLERGIES for h in hits):
            mm = re.search(r"\b(?:severe |serious |mild )?(?:[a-z]+ )?(?:nut|peanut|tree[- ]nut|shellfish|fish|"
                           r"gluten|dairy|lactose|egg|soy|sesame|wheat)(?: and [a-z]+)? allerg(?:y|ies)\b|"
                           r"\ballergic to [a-z ,]+?(?=[.;!?\n]|$| and | but )|\b(?:celiac|coeliac|anaphyla\w+|epipen)\b",
                           low)
            if mm and not NEG_CUE.search(low[max(0, mm.start() - 15):mm.start()]):
                add(_Hit(FieldName.ALLERGIES, text[mm.start():mm.end()].strip(), mm.start(), mm.end()))
            else:
                mm = re.search(r"\ballerg(?:y|ies)\s*(?::|-)\s*none\b|\bnobody has (?:any )?allergies\b", low)
                if mm:
                    add(_Hit(FieldName.ALLERGIES, "none", mm.start(), mm.end()))

        # ---- billing ------------------------------------------------------
        mm = re.search(r"\b(one bill|single bill|one cheque|one check|one tab|one payment|all on one(?: bill)?|"
                       r"together on one)\b", low)
        mm2 = re.search(r"\b(separate (?:bills|cheques|checks|tabs|payments)|split (?:the )?(?:bill|cheque|check)s?|"
                        r"individual (?:bills|cheques|checks)|pay(?:ing)? separately|split bills)\b", low)
        if mm and mm2:
            add(_Hit(FieldName.BILLING, "one_bill" if mm.start() > mm2.start() else "separate_bills",
                     min(mm.start(), mm2.start()), max(mm.end(), mm2.end()), "needs_review",
                     "both one bill and separate bills mentioned"))
        elif mm:
            add(_Hit(FieldName.BILLING, "one_bill", mm.start(), mm.end()))
        elif mm2:
            add(_Hit(FieldName.BILLING, "separate_bills", mm2.start(), mm2.end()))

        # ---- occasion -----------------------------------------------------
        if not any(h.field == FieldName.OCCASION for h in hits):
            mm = re.search(r"\b(no (?:special )?occasion|just (?:a )?(?:dinner|catch[- ]up|get[- ]together|meal)|"
                           r"nothing special|no particular reason)\b", low)
            if mm:
                add(_Hit(FieldName.OCCASION, "none", mm.start(), mm.end()))
            else:
                mm = re.search(r"\b((?:\d+(?:st|nd|rd|th) )?birthday|anniversary|retirement|graduation|engagement|"
                               r"farewell|going[- ]away|(?:work|team|business|client|company|office|holiday|"
                               r"christmas|year[- ]end) (?:dinner|party|lunch|event|celebration|gathering)|reunion|"
                               r"bachelorette|bachelor|baby shower|bridal shower|promotion|rehearsal dinner|"
                               r"celebration of life)\b", low)
                if mm:
                    add(_Hit(FieldName.OCCASION, mm.group(1), mm.start(), mm.end()))

        # ---- seating --------------------------------------------------------
        mm = re.search(r"\b(lounge|dining room|main dining|mezzanine|upstairs)\b", low)
        if mm and not NEG_CUE.search(low[max(0, mm.start() - 12):mm.start()]):
            area = {"lounge": "lounge", "dining room": "dining", "main dining": "dining", "mezzanine": "mezzanine",
                    "upstairs": "mezzanine"}[mm.group(1)]
            add(_Hit(FieldName.PREFERRED_AREA, area, mm.start(), mm.end()))
        elif (mm := re.search(r"\b(anywhere is fine|no (?:seating )?preference|wherever)\b", low)):
            add(_Hit(FieldName.PREFERRED_AREA, "no_preference", mm.start(), mm.end()))
        for mm in re.finditer(r"\b([A-Za-z]\d)\b", text):
            if mm.group(1).upper() in table_ids and (
                    re.search(r"\b(table|to|at|on|specifically)\b", low[max(0, mm.start() - 15):mm.start()])
                    or re.match(r"\s+(?:is|would be|works)\b", low[mm.end():mm.end() + 12])):
                add(_Hit(FieldName.PREFERRED_TABLE, mm.group(1).upper(), mm.start(), mm.end()))
                break
        mm = re.search(r"\b(separate tables? (?:are|is) (?:fine|ok|okay)|(?:don't|do not) mind (?:being )?"
                       r"(?:split|separate)|(?:can|could) be split|fine (?:to|with) (?:split|separate|two tables)|"
                       r"split (?:across|over) tables is fine|two tables is fine)\b", low)
        if mm:
            add(_Hit(FieldName.SPLIT_SEATING_OK, "yes", mm.start(), mm.end()))
        else:
            mm = re.search(r"\b((?:need|want|have|prefer) to (?:all )?(?:sit|be) together|all at one table|"
                           r"one (?:long )?table only|(?:don't|do not) want to be split|must be together|"
                           r"same table)\b", low)
            if mm:
                add(_Hit(FieldName.SPLIT_SEATING_OK, "no", mm.start(), mm.end()))

        # ---- intents --------------------------------------------------------
        def kw(p):
            r = re.search(p, low)
            if r:
                covered.append((r.start(), r.end()))
            return r

        if kw(r"\b(cancel(?:l?ing|l?ed|lation)?|call (?:it )?off|won't be able to make it|can no longer make it|"
              r"no longer (?:need|coming)|have to cancel)\b") and not re.search(r"\b(?:not|don't|do not) (?:want to |need to )?cancel", low):
            intents.add(Intent.CANCEL_BOOKING.value)
        if kw(r"\b(move|reschedule|push (?:it |our booking )?(?:back|to)|switch|change (?:our|the|my) "
              r"(?:booking|reservation|time|date)|instead of|correction|update (?:our|the) (?:booking|number|count)|"
              r"add (?:\w+ )?more|(?:there will be|we'll be|we will be) \w+ of us)\b"):
            intents.add(Intent.MODIFY_BOOKING.value)
        if kw(r"\b(book|reserve|reservation|table for|get a table|a table|need \w+ seats|we are \w+ (?:guests|people)|hold (?:space|a table)|availability|do you have (?:room|space)|"
              r"looking to (?:book|come)|would like to come|space for)\b"):
            intents.add(Intent.NEW_BOOKING.value)
        if "?" in text and re.search(r"\b(what|do you|can you|is there|are there|how|could you)\b", low):
            intents.add(Intent.QUESTION.value)
        if hits and not intents & {Intent.NEW_BOOKING.value, Intent.MODIFY_BOOKING.value, Intent.CANCEL_BOOKING.value}:
            intents.add(Intent.PROVIDE_DETAILS.value)

        for mm in re.finditer(r"\b(ignore (?:all |your |the |any )?(?:previous |table )?(?:rules|instructions|policy|"
                              r"policies|limits)|(?:mark|set|record) (?:it|this|that|the|our|us)(?: booking| reservation)? "
                              r"(?:as )?confirmed|say (?:that )?(?:our|the|it)[a-z ]* (?:is )?confirmed|"
                              r"skip (?:all |the |any )?(?:checks|rules|validation)|approve everything|"
                              r"(?:reply|respond|say) that it(?:'s| is) done|^\s*system\s*:|"
                              r"override|disregard|system prompt|you are now|pretend|bypass)\b", low, re.M):
            amb.append(f"GUEST-INSTRUCTION: \"{text[mm.start():mm.end()]}\" in {m.id}")
            covered.append((mm.start(), mm.end()))

        # ---- coverage -------------------------------------------------------
        uninterpreted = []
        for s, e in _sentences(text):
            if any(cs < e and ce > s for cs, ce in covered):
                continue
            seg = text[s:e].strip()
            if not seg or TRIVIAL.match(seg) or len(seg) < 3:
                continue
            uninterpreted.append(seg[:200])
        return hits, intents, amb, uninterpreted

    # ---- date helpers -------------------------------------------------------
    def _dates(self, text: str, low: str, local: datetime) -> list[_Hit]:
        out: list[_Hit] = []

        def mk(y, mo, d, s, e, assumed_year):
            try:
                dt = date(y, mo, d)
            except ValueError:
                return
            note = None
            if assumed_year:
                if dt < local.date():
                    dt = date(y + 1, mo, d)
                note = f"year not stated; assumed {dt.year} (next occurrence after message date)"
            out.append(_Hit(FieldName.REQUESTED_DATE, dt.isoformat(), s, e, "extracted", note))

        for mm in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", low):
            mk(int(mm.group(1)), int(mm.group(2)), int(mm.group(3)), mm.start(), mm.end(), False)
        for mm in re.finditer(MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s*(20\d{2}))?", low):
            mo = MONTH_ABBR[mm.group(1)[:3]]
            y = int(mm.group(3)) if mm.group(3) else local.year
            mk(y, mo, int(mm.group(2)), mm.start(), mm.end(), mm.group(3) is None)
        for mm in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MONTH_RE + r"(?:,?\s*(20\d{2}))?", low):
            mo = MONTH_ABBR[mm.group(2)[:3]]
            y = int(mm.group(3)) if mm.group(3) else local.year
            if not any(h.start <= mm.start() < h.end or mm.start() <= h.start < mm.end() for h in out):
                mk(y, mo, int(mm.group(1)), mm.start(), mm.end(), mm.group(3) is None)
        for mm in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?\b", low):
            a, b = int(mm.group(1)), int(mm.group(2))
            y = int(mm.group(3)) if mm.group(3) else local.year
            if a > 12 and b <= 12:
                mk(y, b, a, mm.start(), mm.end(), mm.group(3) is None)
            elif b > 12 and a <= 12:
                mk(y, a, b, mm.start(), mm.end(), mm.group(3) is None)
            else:
                n = len(out)
                mk(y, a, b, mm.start(), mm.end(), mm.group(3) is None)
                if len(out) > n:
                    out[-1].status = "needs_review"
                    out[-1].note = "numeric date could be month/day or day/month"
        return out

    def _choose(self, hits: list[_Hit], low: str) -> _Hit | None:
        distinct = {h.value for h in hits}
        hits = sorted(hits, key=lambda h: h.start)
        if len(distinct) == 1:
            return hits[0]
        last = hits[-1]
        between = low[hits[0].end:last.start]
        if re.search(r"\b(to|instead|actually|now|rather|move|change)\b", between):
            last.note = (last.note + "; " if last.note else "") + f"replaces {hits[0].value} mentioned earlier"
            return last
        last.status = "needs_review"
        last.note = f"several dates mentioned: {sorted(distinct)}"
        return last

    def _times(self, text: str, low: str) -> _Hit | None:
        cands: list[_Hit] = []
        for mm in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.m\.(?=\s*\w)|p\.m\.(?=\s*\w)|a\.m|p\.m|am|pm)(?![a-z])", low):
            h, mi = int(mm.group(1)), int(mm.group(2) or 0)
            ap = mm.group(3)[0]
            if h > 12 or mi > 59:
                continue
            h = (h % 12) + (12 if ap == "p" else 0)
            cands.append(_Hit(FieldName.REQUESTED_TIME, f"{h:02d}:{mi:02d}", mm.start(), mm.end()))
        for mm in re.finditer(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(?:a\.?m|p\.?m))", low):
            if any(c.start <= mm.start() < c.end for c in cands):
                continue
            h, mi = int(mm.group(1)), int(mm.group(2))
            if h <= 10:
                cands.append(_Hit(FieldName.REQUESTED_TIME, f"{h + 12:02d}:{mi:02d}", mm.start(), mm.end(),
                                  "extracted", f"'{mm.group(0)}' without am/pm assumed evening (opens 11:00)"))
            elif h in (11, 12):
                cands.append(_Hit(FieldName.REQUESTED_TIME, f"{h:02d}:{mi:02d}", mm.start(), mm.end(),
                                  "needs_review", "no am/pm given"))
            else:
                cands.append(_Hit(FieldName.REQUESTED_TIME, f"{h:02d}:{mi:02d}", mm.start(), mm.end()))
        for mm in re.finditer(r"\b(noon|midday)\b", low):
            cands.append(_Hit(FieldName.REQUESTED_TIME, "12:00", mm.start(), mm.end()))
        if not cands:
            for mm in re.finditer(r"\b(?:at|around|for|by|from)\s+(\d{1,2})(?:\s*o'clock)?\b(?!\s*(?:people|guests|"
                                  r"of us|pax|adults|kids|children|seats|persons|ppl|:|/|th|st|nd|rd|-\d|hours?|hrs?))",
                                  low):
                h = int(mm.group(1))
                if 1 <= h <= 10:
                    cands.append(_Hit(FieldName.REQUESTED_TIME, f"{h + 12:02d}:00", mm.start(1), mm.end(),
                                      "extracted", f"'{mm.group(0).strip()}' without am/pm assumed evening"))
                elif h in (11, 12):
                    cands.append(_Hit(FieldName.REQUESTED_TIME, f"{h:02d}:00", mm.start(1), mm.end(),
                                      "needs_review", "no am/pm given"))
        if not cands:
            return None
        cands.sort(key=lambda c: c.start)
        distinct = {c.value for c in cands}
        if len(distinct) == 1:
            return cands[0]
        first, last = cands[0], cands[-1]
        between = low[first.end:last.start]
        if re.search(r"\b(instead|actually|now|rather|move|change|push)\b", low) and re.search(r"\bto\b", between):
            last.note = f"change from {first.value} to {last.value}"
            return last
        if re.search(r"^\s*(?:-|to|until|till)\s*$", between) or re.search(r"^\s*(?:-|to|until|till)\s", between):
            # a time range: start + duration is handled by the caller via note only
            first.note = f"range {first.value}-{last.value} stated; dining duration follows policy"
            return first
        last.status = "needs_review"
        last.note = f"several times mentioned: {sorted(distinct)}"
        return last
