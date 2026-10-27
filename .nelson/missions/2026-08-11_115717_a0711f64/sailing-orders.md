# Sailing Orders — Phase C Config + GUI + TCP

```text
Sailing orders:
- Outcome: Ship Phase C so site staff can select USB|TCP, set KKT driver IP/port, persist settings, and operate Admin screens A–D without SSH/code edits (AC-5, AC-6).
- Success metric: AC-5+AC-6 met; mocked IFptr tests green for USB/TCP + GUI save + config persistence; code-reviewer APPROVE or REQUEST_CHANGES addressed; no commit/push.
- Deadline: This session

Constraints:
- Token/time budget: This session; sequential specialist dispatch (developer → reviewer → test-engineer)
- Reliability floor: pytest green with mocked IFptr; fiscal sequence unbroken; errorCode checked after native calls
- Compliance/safety constraints: AGENTS.md §3–§5; F-CONN-06 no mass OFD rewrite on boot; F-CONN-07 IP disambiguation; F-CONN-08 no IFptr from routes/GUI; LAN trust flagged for unauthenticated admin
- Forbidden actions: commit/push; edit libfptr10.py style; silent Check typo renames; change tax/payment mapping; break /create-check clients

Scope:
- In scope: F-CFG-01–04; F-CONN-01–03, 07–08; Admin screens A–D (D stub ok if retry unsafe); build on Phase A+B tree; optional F-DIAG-06/08 if time
- Out of scope: Phase D packaging/systemd/full CI; Auth/PIN; tax/payment mapping; libfptr10 edits; silent schema renames; commit/push; mass OFD on boot; breaking /create-check

Stop criteria:
- Stop when: AC-5/AC-6 delivered, reviewer verdict addressed, tests green, handoff artifacts written — or when blocked on true tax/auth ambiguity only

Required handoff artifacts:
- Must produce: sailing-orders, battle-plan, captains-log, stand-down.json, damage-reports; admiral summary (files, endpoints, config schema, review verdict, pytest count, residual risks)
```

**Mission dir:** `.nelson/missions/2026-08-11_115717_a0711f64/`
**Estimate:** Authorized by admiral; recommended (multi-system). Checkpoints collapsed if Q1 clean (admiral: do not block human turn unless ambiguous).
**Dispatch order:** senior-python-developer → code-reviewer → test-engineer (mandatory).
