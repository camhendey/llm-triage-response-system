# Evaluation run 20261007T002544-development-offline

- Mode: **offline** (provider `offline_rules`)
- Split: development · repeats: 1 · frozen check: scenarios_dev.yaml matches frozen hash 3592494d77e4
- Started: 2026-10-07T00:25:44+00:00 · duration: 0.17 s · code d06cbee
- Retest: no

Synthetic scenarios written by the same coding agent that built the system. These are engineering checks, not an independent benchmark.

| Metric | Result |
|---|---|
| Cases run / total | 20/20 (run errors: 0) |
| Field agreement, all labelled fields | 77/78 (98.7%) |
| Field agreement, labelled known values | 67/68 (98.5%) |
| Unknowns kept unknown | 8/8 (100.0%) |
| Ambiguities sent to review | 2/2 (100.0%) |
| Provenance: accepted citations quoting their message verbatim | 122/122 (100.0%) |
| Provenance: cited message matches labelled message | 6/6 (100.0%) |
| Citations rejected by evidence validator | 0 |
| Next action within allowed set | 19/19 (100.0%) |
| Required-constraint recall | 15/15 (100.0%) |
| False warnings (forbidden rules raised) | 0 |
| Drafts generated | 19 |
| Drafts with prohibited claims (total claims) | 0 (0) |
| Drafts with validator errors | 0 |
| Cases with critical errors (total) | 0 (0) |
| Provider statuses | {"ok": 19, "partial": 2, "unsupported": 1} |
| Interpret latency ms (median / max) | 1.0 / 10 |
| Token usage (input / output) | 0 / 0 |
| Cost | not applicable (offline, no API calls) |

## By group

| Group | Cases | Next action OK | Cases with critical errors |
|---|---|---|---|
| adversarial_unsupported | 2 | 2/2 | 0 |
| capacity_accessibility | 2 | 2/2 | 0 |
| missing_conflicting | 3 | 3/3 | 0 |
| modification_cancellation | 3 | 3/3 | 0 |
| ordinary | 3 | 3/3 | 0 |
| overlap_hold_time | 3 | 2/2 | 0 |
| oversized_minspend | 2 | 2/2 | 0 |
| service_allergy | 2 | 2/2 | 0 |

## Cases needing attention

- **DEV-10** (rep 0) next `create_hold`
  - field split_seating_ok: expected 'yes', got unknown None
