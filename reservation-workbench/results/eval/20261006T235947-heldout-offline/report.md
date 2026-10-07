# Evaluation run 20261006T235947-heldout-offline

- Mode: **offline** (provider `offline_rules`)
- Split: heldout · repeats: 1 · frozen check: scenarios_heldout.yaml matches frozen hash d731ee1ec2c7
- Started: 2026-10-06T23:59:47+00:00 · duration: 0.36 s · code 088d2ba
- Retest: RETEST 2 after inspecting held-out failures (runs 20261006T235717, 20261006T235823): offline party-size parsing and stairs-preference review changed. Not a blind result.

Synthetic scenarios written by the same coding agent that built the system. These are engineering checks, not an independent benchmark.

| Metric | Result |
|---|---|
| Cases run / total | 40/40 (run errors: 0) |
| Field agreement, all labelled fields | 97/97 (100.0%) |
| Field agreement, labelled known values | 82/82 (100.0%) |
| Unknowns kept unknown | 10/10 (100.0%) |
| Ambiguities sent to review | 5/5 (100.0%) |
| Provenance: accepted citations quoting their message verbatim | 261/261 (100.0%) |
| Provenance: cited message matches labelled message | 13/13 (100.0%) |
| Citations rejected by evidence validator | 0 |
| Next action within allowed set | 36/40 (90.0%) |
| Required-constraint recall | 20/20 (100.0%) |
| False warnings (forbidden rules raised) | 0 |
| Drafts generated | 38 |
| Drafts with prohibited claims (total claims) | 0 (0) |
| Drafts with validator errors | 0 |
| Cases with critical errors (total) | 1 (1) |
| Provider statuses | {"ok": 54, "partial": 4, "unsupported": 4} |
| Interpret latency ms (median / max) | 1.0 / 11 |
| Token usage (input / output) | 0 / 0 |
| Cost | not applicable (offline, no API calls) |

## By group

| Group | Cases | Next action OK | Cases with critical errors |
|---|---|---|---|
| adversarial_unsupported | 3 | 3/3 | 0 |
| capacity_accessibility | 6 | 5/6 | 1 |
| missing_conflicting | 6 | 6/6 | 0 |
| modification_cancellation | 6 | 6/6 | 0 |
| ordinary | 6 | 4/6 | 0 |
| overlap_hold_time | 6 | 5/6 | 0 |
| oversized_minspend | 4 | 4/4 | 0 |
| service_allergy | 3 | 3/3 | 0 |

## Cases needing attention

- **HO-ORD-01** (rep 0) next `operator_review` (not allowed)
- **HO-ORD-02** (rep 0) next `create_hold` (not allowed)
- **HO-CAP-04** (rep 0) next `create_hold` (not allowed)
  - CRITICAL unsafe_commit_recommendation:create_hold
- **HO-TIM-05** (rep 0) next `create_hold` (not allowed)
