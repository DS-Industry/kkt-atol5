# Sailing Orders — Phase B Operability (P0/P1)

- **Outcome:** Implement Phase B operability (F-Q-04–07, F-CONN-04–05, F-OPS-01–02, F-DIAG-01–05/+07) without Phase C Admin GUI.
- **Success metric:** pytest green for Phase B + Phase A; code-reviewer must-fix resolved.
- **Deadline:** This session.

## Constraints
- Token/time: this session
- Reliability: no regress of Phase A AC-1..AC-4; fiscal sequence unbroken; errorCode checked; no dangling open receipts
- Compliance: AGENTS.md §3.1, §4, §5, §6, §7, §10; ATOL docs via atol-docs; field issues in docs/issues/issues.md
- Forbidden: edit libfptr10.py style; change tax/payment mapping without confirmation; silent typo renames; commit/push without ask; Phase C Admin GUI / F-CONN-01–03 TCP GUI; Phase D packaging beyond tests

## Scope
**In:** F-Q-04–07, F-CONN-04–05, F-OPS-01–02, F-DIAG-01–05 (MUST), F-DIAG-07 (SHOULD if time), docs ops runbook (USB autosuspend + scheduler start)
**Out:** F-DIAG-06/08 if time-tight; Phase C screens A–D / F-CFG-*; F-CONN-01–03 TCP mode selector GUI; Phase D packaging

## Estimate
Skipped — FSD Phase B already concrete in `docs/FSD-production-stable.md` §9; same rationale as Phase A mission `2026-08-11_105418_af6f98f6`. Admiral ordered execute (no wait for confirmation).

## Stop criteria
Stop when implement → review (must-fix addressed) → pytest pass, Nelson stand-down artifacts written, structured summary ready for admiral.

## Handoff artifacts
Mission dir under `.nelson/missions/`; captains-log; stand-down.json; summary: files, schema, endpoints, review verdict, pytest count, residual risks / Phase C leftovers. Do NOT commit.
