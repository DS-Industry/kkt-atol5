# Estimate Briefing 1 — Q2 Intent + Q3 Effects

Mission dir: `/Users/eshom/Developer/kkt-atol5/.nelson/missions/2026-08-11_115717_a0711f64/`

## Task
Append H2 sections for **Q2 Intent** and **Q3 Effects** to `{mission-dir}/estimate.md` (after existing Q1). Do not rewrite Q1. Voice: concise officer register per `.cursor/skills/nelson/references/the-estimate.md`.

## Sailing orders (summary)
- Outcome: Phase C — persistent config USB|TCP, CashierService TCP connect, Admin GUI A–D; AC-5/AC-6
- Metric: AC-5+AC-6; mocked tests USB/TCP+GUI persist; reviewer APPROVE or REQUEST_CHANGES addressed; no commit/push
- Deadline: This session
- IN: F-CFG-01–04; F-CONN-01–03,07–08; Screens A–D (D list stub if retry unsafe); optional DIAG-06/08
- OUT: Phase D packaging; Auth/PIN; tax/payment; libfptr10 edits; silent Check renames; commit; mass OFD boot; break /create-check
- Constraints: Flask HTTP in main.py; all IFptr via CashierService; fiscal sequence; errorCode checks; HTTP status matches code; atol-docs for TCPIP

## Q1 synthesis (see estimate.md §1)
- No config.json yet; USB hardcoded; TCP comment-only
- /health + /admin/diagnostics JSON ready; no HTML UI
- F-CONN-06 OK — do not reintroduce OFD mass write
- Screen D: list only, no retry (no anti-double-print API)
- Defaults: map F-CFG-02; resolve HTTP port default vs AGENTS 5050

## User preferences (not only in sailing-orders)
- Team Lead must NOT implement — specialists only
- Dispatch order mandatory: senior-python-developer → code-reviewer → test-engineer
- Admiral: collapse checkpoints; do not block for human unless tax/auth ambiguous
- Prefer (A) Driver TCP IP only in Settings
- Optional F-DIAG-06/08 if time — not blocking

## Effect requirements
Each effect needs: lands-on hint, complexity, **Commander's guidance**, **Acceptance criteria** (verifiable). Cover at least:
1. Persistent config load/save + defaults (F-CFG-*)
2. CashierService USB|TCP applySingleSettings + open (F-CONN-01–03)
3. Admin Screen B Settings API/UI + reconnect
4. Admin Screen A Status wired to health/diagnostics + queue counts + actions
5. Admin Screen C Logs tail
6. Admin Screen D Checks list (no unsafe retry)
7. Tests + review gate (or note as control, not effect)

Write the file append yourself.
