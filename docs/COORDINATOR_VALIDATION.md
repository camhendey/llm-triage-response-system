# Validation and operator study

## Automated verification

`tests/test_coordinator.py` covers empty stores, independent completion gates, material-change invalidation, contact changes, atomic failure, stale tabs, shift changes, exact acceptance sources, no-answer follow-ups, current policy, photos, approval order, external checklist/reference/hold rules, offers, premature confirmation, handoff changes, report persistence/expiry/venue identity, conditional availability/reconciliation, buffers, deletion and audit provenance.

`scripts/verify_coordinator.py` starts a local server and disposable database, configures a fictional restaurant through the UI, uploads an illustrative CSV, reloads, works an inquiry, blocks premature confirmation, records acceptance, recovers a draft, reads actual clipboard contents, reports external sending, records staff review and checks 820/390 px overflow. Screenshots are actual browser output, not mockups. Old parser/engine/provider/UI regressions remain.

See `VERIFICATION.md` and exact logs for actual results. Tests inspected during development are regression evidence, not a blind benchmark.

## Human study: not yet run

1. Recruit reservation coordinators, record experience, obtain consent, and use synthetic/anonymized cases.
2. Include ordinary booking, no-answer, split seating, ambiguous allergy, spend approval, infeasible request, change, cancellation, stale export and shift handoff.
3. Counterbalance manual-template and app order across participants/scenario sets; provide equivalent training and record familiarity.
4. Measure active work separately from elapsed time and external waiting. Built-in click timers measure elapsed intervals only; supplement with observation/interruption records.
5. Grade outputs against independently specified facts, correct action sequence, accurate terms, source-backed acceptance, valid final response and complete handoff. Separate critical errors from minor corrections.
6. Record success, clarification requests, navigation errors, missing attachments, stale-data mistakes and post-task ease ratings. Gather think-aloud feedback without coaching.
7. Retain anonymized artifacts, scenario versions, raw timings and adjudication notes. Report sample sizes, exclusions, spread and uncertainty.

Development timing is not user-study evidence. The historical ~45→5 minute owner estimate belongs to the earlier manual LLM-assisted workflow, not this software.

## Before a real pilot

Verify a genuine sanitized dashboard export; have the restaurant approve layout, policy and photos; test duration/status/accessibility/pacing assumptions; establish authentication, encryption, backups, restore testing and retention; and validate with actual coordinators, keyboard navigation and assistive technology. Browser overflow checks alone are not an accessibility audit.
