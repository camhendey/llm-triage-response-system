# Evaluation run 20261006T235717-heldout-offline

- Mode: **offline** (provider `offline_rules`)
- Split: heldout · repeats: 1 · frozen check: scenarios_heldout.yaml matches frozen hash d731ee1ec2c7
- Started: 2026-10-06T23:57:17+00:00 · duration: 0.35 s · code bb0ccab
- Retest: no

Synthetic scenarios written by the same coding agent that built the system. These are engineering checks, not an independent benchmark.

| Metric | Result |
|---|---|
| Cases run / total | 40/40 (run errors: 0) |
| Field agreement, all labelled fields | 91/97 (93.8%) |
| Field agreement, labelled known values | 76/82 (92.7%) |
| Unknowns kept unknown | 10/10 (100.0%) |
| Ambiguities sent to review | 5/5 (100.0%) |
| Provenance: accepted citations quoting their message verbatim | 251/251 (100.0%) |
| Provenance: cited message matches labelled message | 12/13 (92.3%) |
| Citations rejected by evidence validator | 0 |
| Next action within allowed set | 33/40 (82.5%) |
| Required-constraint recall | 17/20 (85.0%) |
| False warnings (forbidden rules raised) | 0 |
| Drafts generated | 38 |
| Drafts with prohibited claims (total claims) | 0 (0) |
| Drafts with validator errors | 0 |
| Cases with critical errors (total) | 1 (3) |
| Provider statuses | {"ok": 54, "partial": 4, "unsupported": 4} |
| Interpret latency ms (median / max) | 1.0 / 11 |
| Token usage (input / output) | 0 / 0 |
| Cost | not applicable (offline, no API calls) |

## By group

| Group | Cases | Next action OK | Cases with critical errors |
|---|---|---|---|
| adversarial_unsupported | 3 | 3/3 | 0 |
| capacity_accessibility | 6 | 4/6 | 1 |
| missing_conflicting | 6 | 6/6 | 0 |
| modification_cancellation | 6 | 6/6 | 0 |
| ordinary | 6 | 2/6 | 0 |
| overlap_hold_time | 6 | 5/6 | 0 |
| oversized_minspend | 4 | 4/4 | 0 |
| service_allergy | 3 | 3/3 | 0 |

## Cases needing attention

- **HO-ORD-01** (rep 0) next `operator_review` (not allowed)
- **HO-ORD-02** (rep 0) next `create_hold` (not allowed)
- **HO-ORD-03** (rep 0) next `clarify`
  - field party_size: expected 7, got unknown None
- **HO-ORD-05** (rep 0) next `clarify` (not allowed)
  - field party_size: expected 6, got unknown None
- **HO-ORD-06** (rep 0) next `clarify` (not allowed)
  - field party_size: expected 2, got unknown None
- **HO-CAP-01** (rep 0) next `operator_review` (not allowed)
  - field party_size: expected 9, got needs_review 1
- **HO-CAP-02** (rep 0) next `confirm_booking` (not allowed)
  - field party_size: expected 20, got known 2
  - missing rule R-NO-OPTION
  - CRITICAL critical_fact:party_size=2 (expected 20)
  - CRITICAL missed_rule:R-NO-OPTION
  - CRITICAL unsafe_commit_recommendation:confirm_booking
- **HO-CAP-04** (rep 0) next `clarify`
  - missing rule R-ACCESS-CONFLICT
- **HO-TIM-05** (rep 0) next `clarify` (not allowed)
  - field party_size: expected 4, got unknown None
  - missing rule R-PREF
