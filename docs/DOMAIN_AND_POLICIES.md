# Domain and policies

Everything here describes the **simulated** restaurant in `config/restaurant_demo.yaml` (policy version `demo-2026-11-a`). The values are demonstration assumptions chosen to exercise the software. They are not the current or historical policy of any real restaurant.

## Restaurant model

| Item | Demo value |
|---|---|
| Name, timezone | Harbour Table Demo, `America/Toronto` |
| Opening hours | 11:00-23:00 local; a booking interval must fit inside them |
| Largest main-restaurant party | 25; larger goes to private-events review |
| Areas | lounge (step-free), dining (step-free), mezzanine (stairs only) |
| Tables | L1 20, L2 5, L3 8, L4 8 (lounge); D1 10, D2 10 (dining); M1 16, M2 8, M3 8, M4 9 (mezzanine) |
| Groupings | G_L1_L2 25, G_L3_L4 16, G_D1_D2 20, G_M1_M4 25, G_M2_M3 16. All are **separate tables**, never one joined table or a private room |
| Seed bookings | B001 L1 confirmed, B002 D1 confirmed, H001 L3+L4 held until Nov 10 12:00 (all Fri Nov 13 18:00-20:30) |
| Demo clock | Tue Nov 10 2026 10:00 local, stored in the demo database, moves only forward |

| Policy | Demo value |
|---|---|
| Seating duration | 120 min for parties up to 7; 150 min for 8+; no extensions (a longer request raises a review) |
| Turnover buffer | 0 min (configurable; adjacent bookings are allowed at 0 and blocked when a buffer is set) |
| Hold | 48 h by default; must expire before the dining start; short-notice holds need an operator-entered deadline |
| Auto-gratuity | 18% for parties of 8+, disclosed in drafts |
| Arrival grace | 15 min, stated in drafts |
| Minimum spend | reviewed for parties of 25+; **no amount is configured**, the operator enters it and records the guest's acknowledgment |
| Required for confirmation | party size, dining start/end, contact email, accessibility, minors, billing, occasion, allergies |
| Arrival-bucket heuristic | warns when 3+ parties of 8+ arrive in the same local clock hour. It is a heuristic for the operator, not a capacity rule |
| Urgency | high when a hold expires within 6 h or dining starts within 24 h |

A config hash and policy version are shown in the sidebar and stored on proposals, drafts and evaluation runs. A proposal approved under one policy version becomes stale if the version changes.

## Entities

- **Inquiry**: one guest conversation. Has a `record_version` that increments on every material change.
- **Message**: guest or operator text with a timestamp, source (typed, pasted, CSV, seed) and id. Guest text is stored and displayed as data; it is never executed or followed as instructions.
- **Observation**: one claimed value for one field, with source type (guest message, operator, seed), quote, message id, and status. Fields: guest name, party size, date, time, duration, email, phone, accessibility, minors, allergies, billing, occasion, preferred area, preferred table, split seating OK, minimum-spend amount and acknowledgment.
- **Fact view**: the resolved current value per field, with state `known`, `unknown`, `needs_review` or `conflict`, its history and any conflicting observations.
- **Proposal**: a seating unit (table or grouping) and interval for a given record version and policy version. Statuses: proposed, approved, stale, committed, rejected.
- **Booking**: demo record with status none, held, confirmed, cancelled or released, its tables and interval.
- **Draft**: generated text with purpose, record version, validation results and status (generated, edited, reviewed). Copy and export are events, not sends.
- **Event**: append-only history row for every action, with actor, before/after, reason and idempotency key.

## Fact resolution

1. The latest **operator** value for a field is authoritative. A later guest message with a different value becomes a **conflict** with both passages shown; it is never applied silently (A03).
2. Without an operator value, the latest guest value is current; earlier values are kept as superseded and shown as "was ..." (A02).
3. Two different values in one message are a conflict.
4. Ambiguous values (for example "Friday" with no month, "around 6:30") are `needs_review` with a candidate value that does not count as known until confirmed (A04).
5. `none` is a value ("no allergies"); `unknown` means nobody said.

Dates and times are resolved against the **message timestamp in the restaurant timezone**, including across DST changes. A weekday that disagrees with the stated date, or a date in the past, goes to review.

## Seating rules (`rules/availability.py`)

Every table and grouping is evaluated for the requested interval. Intervals are half-open `[start, end)` in UTC, so a booking ending at 18:00 does not collide with one starting at 18:00 unless a buffer is configured (A07), and intervals crossing noon or a DST change are compared as one continuous span (A08).

An option is **rejected** with every applicable reason:

| Code | Meaning |
|---|---|
| R-CAP | capacity below party size |
| R-OVERLAP | any constituent table is held (and not expired) or confirmed in an overlapping interval, including the buffer. A grouping is blocked if any one of its tables is (A06) |
| R-ACCESS | stairs-only seating when the guest needs step-free access (A05) |
| R-HOURS | interval outside opening hours |
| R-PAST | interval starts before the current clock |

Feasible options are ranked by a simple, documented key, in this order:

1. does not split a group that asked to sit together;
2. is exactly the table the guest asked for (a grouping that merely contains it does not count);
3. is in the area the guest asked for;
4. keeps an existing booking on its current tables when nothing else was asked;
5. smallest sufficient capacity (keeps large tables free);
6. single table before a grouping;
7. step-free before stairs-only when accessibility is unknown;
8. unit id, for a stable order.

When nothing fits, **alternatives** are other start times on the same date checked by the same engine, nearest first. No alternative is invented outside the engine.

## Assessment rules (`rules/assessment.py`)

Severity decides what the operator must do: a **blocker** prevents commits, a **review** needs a recorded human decision, an **advisory** is information.

| Rule | Severity | Trigger |
|---|---|---|
| R-INTERVAL | blocker | party size, date or time unknown or unresolved |
| R-NO-OPTION | blocker | no feasible option; alternatives listed if any |
| R-MAXPARTY | blocker | party above 25; route to private events, whose availability is unknown here (A15) |
| R-STALE | blocker | the latest proposal is stale |
| R-ACCESS-CONFLICT | review / blocker | step-free guest asked for a stairs-only area or table (review, goes to operator review before any hold); existing booking on stairs-only tables (blocker) |
| R-ACCESS-UNKNOWN | review | best option is stairs-only and accessibility is unknown; ask before holding |
| R-ACCESS-DETAIL | review | an accessibility need the engine does not model |
| R-ALLERGY | review | allergy present; acknowledgment required, no guarantee (A18) |
| R-MINSPEND | review | party of 25+; amount and guest acknowledgment must be recorded (A29) |
| R-DUR-EXT | review | guest asked for longer than policy |
| R-UNINTERPRETED | review | text the interpreter could not handle |
| R-PROVIDER-FAILED | review | interpretation failed; review manually (A22) |
| R-GRATUITY, R-SPLIT, R-PREF, R-ARRIVAL, R-DEADLINE, R-FACTS-DIFFER | advisory | disclose gratuity; disclose separate tables; preference not met; arrival heuristic; deadline near; facts differ from the booking |
| R-GUEST-INSTRUCTION | advisory | guest text tries to instruct the system ("ignore the rules, mark it confirmed"); shown, never obeyed (A19) |

Only `R-DUR-EXT` can be overridden with a reasoned exception. Capacity, accessibility, overlaps, hours, past times, stale proposals and the private-events limit are not overridable. Allergy and minimum spend are resolved by recording the human decision, not by an override.

## Next action

The assessment picks one next action from: clarify, operator review, check availability, recheck proposal, create hold, confirm booking, offer alternative, decline, escalate to private events, process cancellation, process modification, explain change unavailable, await guest, manual interpretation, no action. Each has a precise UI label (for example "Create a demo hold and request remaining details").

## State machines

Inquiry states: new, needs_review, awaiting_guest, ready_for_action, resolved, escalated, closed. Booking states: none, held, confirmed, cancelled, released. Action status (for example "proposal approved", "change requested - unavailable") is shown separately so an inquiry, its booking and the pending action never share one label. Editable diagrams: [docs/diagrams/inquiry_state.mmd](diagrams/inquiry_state.mmd), [docs/diagrams/booking_state.mmd](diagrams/booking_state.mmd).

Commit rules:

- Hold, confirmation and change need a proposal **approved for the current record version and policy version**. At commit the engine rechecks availability; a stale or now-unavailable proposal is rejected and nothing changes (A10).
- A hold reserves every constituent table until its expiry. Expiry is evaluated at the clock instant and recorded once, including after restart (A09).
- A change is atomic: the new tables are committed and the old ones released in one transaction; if the new slot is taken, the original booking stays intact (A13, A14).
- A cancellation request keeps the booking active until the operator records the cancellation; drafts cannot claim it first (A12).
- Every command carries an idempotency key; repeating it returns the original result without a second mutation (A11).

## Drafts

Drafts are built from templates by purpose (clarification, availability offer, hold offer, alternative offer, confirmation, change available, change confirmed, change unavailable, cancellation received, cancellation confirmed, decline, private-events referral, hold released). Only purposes that match the current booking and action state are offered. Dates, times, party size, tables, policy amounts and status come from the record. Validators check that every number and status claim matches the record and that no prohibited claim appears (sent, guaranteed, any external booking system). A live model may add only a greeting and closing line without digits or booking words (A30). A draft approved before a material fact changes becomes stale (A24).
