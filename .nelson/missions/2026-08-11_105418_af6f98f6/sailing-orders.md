# Sailing Orders — Phase A Safety (P0)

- **Outcome:** Stop data loss and fiscal dangling: fail-stop receipts with cancel, durable queue states, no DB wipe on boot, hard timeouts, slim device init.
- **Success metric:** AC-1..AC-4 (Phase A) met; pytest green with mocked IFptr; code-reviewer must-fix cleared.
- **Deadline:** This session.

## Constraints
- Token/time: this session
- Reliability: fiscal sequence unbroken; errorCode checked; no dangling open receipts
- Compliance: AGENTS.md §3.1, §4, §5, §6, §7, §10; ATOL docs via atol-docs skill
- Forbidden: edit libfptr10.py style; change tax regime; silent typo renames; commit without ask; Phase B/C/D scope

## Scope
**In:** P1–P5, F-FISC-01..08, F-Q-01..03, F-Q-08; requirements.txt if needed for pytest
**Out:** F-Q-04–07, F-CONN-04–05, F-OPS-01–02, F-DIAG-*, Admin GUI, F-CFG-*

## Estimate
Skipped — FSD Phase A already lists concrete P/F IDs.

## Stop criteria
Stop when implement → review (must-fix addressed) → pytest pass, and structured summary ready for parent.

## Handoff artifacts
Structured summary: IDs implemented, files, review verdict, test results, schema changes, deferred/risks, mission dir.
