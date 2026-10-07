# Evaluation run refinement-challenge-first-pass

- Mode: **offline** (provider `offline_rules`)
- Split: challenge · repeats: 1 · frozen check: 2ad720b92158e2ba315d1eb8fe0ec385cc012d10b739779a4260ccf4e907ec70
- Started: 2026-10-06T22:33:39.455618-04:00 · duration: None s · code unknown (not a git checkout)
- Retest: First execution of development-authored supplemental cases; not independent or a replacement for the original blind run.

Synthetic scenarios authored within this project development process. These are engineering checks, not an independent benchmark.

| Metric | Result |
|---|---|
| Cases run / total | 12/12 (run errors: 0) |
| Field agreement, all labelled fields | 31/32 (96.9%) |
| Field agreement, labelled known values | 25/26 (96.2%) |
| Unknowns kept unknown | 6/6 (100.0%) |
| Ambiguities sent to review | 0/0 |
| Provenance: accepted citations quoting their message verbatim | 45/45 (100.0%) |
| Provenance: cited message matches labelled message | 0/0 |
| Citations rejected by evidence validator | 0 |
| Next action within allowed set | 0/0 |
| Required-constraint recall | 0/0 |
| False warnings (forbidden rules raised) | 0 |
| Drafts generated | 11 |
| Drafts with prohibited claims (total claims) | 0 (0) |
| Drafts with validator errors | 0 |
| Cases with critical errors (total) | 0 (0) |
| Provider statuses | {"ok": 12, "partial": 2, "unsupported": 1} |
| Interpret latency ms (median / max) | 1 / 8 |
| Token usage (input / output) | 0 / 0 |
| Cost | No API calls |

## By group

| Group | Cases | Next action OK | Cases with critical errors |
|---|---|---|---|
| refinement | 12 | 0/0 | 0 |

## Cases needing attention

- **RC03** (rep 0) next `operator_review`
  - field accessibility: expected 'none', got needs_review 'none'

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025. These software run timestamps are retained as recorded.
