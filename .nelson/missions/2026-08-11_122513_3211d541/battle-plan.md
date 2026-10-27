# Battle Plan — Phase D Packaging & Tests

Commander's intent:
Deliver Phase D packaging and deploy hygiene so the Orange Pi service is installable, ignorable-noise stays out of git, operators have a systemd example and hardware smoke checklist, and the existing mocked pytest suite stays green — without touching fiscal sequences, auth, tax mapping, or committing A–C work.

Workflow suitability: not selected because three sequential specialist handoffs (implement → review → test) with small file fan-out; subagents mode fits.

## Standing Order Check

- **becalmed-fleet:** No single-session — Admiralty mandated specialist chain (Resolute → Vigilant → Assay); serial subagents, not agent-team.
- **light-squadron:** Three independent work units (implement packaging, review, test) — one captain each; not under-split.
- **split-keel:** Exclusive ownership: Resolute owns packaging/docs artifacts; Vigilant owns only its damage-report path (read-only review of Resolute outputs); Assay owns `tests/` + pytest run. Serialized by deps so no write conflicts.
- **unclassified-engagement:** All tasks Station 1 (Caution).
- **all-hands-on-deck:** Captains implement/review/test directly — no idle crew roles.
- **skeleton-crew:** No single-crew atomic tasks; captains implement directly.
- **crew-without-canvas:** Three agents justified by mandatory specialist skills.
- **captain-at-the-capstan:** N/A — no crew; captains work directly.
- **press-ganged-navigator:** No red-cell (Station 1, packaging only).
- **admiral-at-the-helm:** Admiral coordinates only; no implementation.
- **wrong-ensign:** Mode `subagents` — Task tool for captains; admiral tracks progress.
- **pulling-the-oar:** On failed dispatch, fix brief and re-dispatch — do not absorb.

---

Commander's intent (verbatim for briefs):
Deliver Phase D packaging and deploy hygiene so the Orange Pi service is installable, ignorable-noise stays out of git, operators have a systemd example and hardware smoke checklist, and the existing mocked pytest suite stays green — without touching fiscal sequences, auth, tax mapping, or committing A–C work.

---

Task ID: 1
- Name: Implement Phase D packaging artifacts
- Owner: HMS Resolute
- Ship: HMS Resolute (frigate)
- Crew manifest: Captain implements directly
- Deliverable: Complete/verify requirements.txt; root .gitignore (F-OPS-04); systemd unit under deploy/; hardware smoke checklist doc; ops-runbook pointers for packaging/systemd/smoke/how-to-run-tests
- Dependencies: none
- Station tier: 1
- File ownership: `.gitignore`, `requirements.txt`, `deploy/kkt-atol5.service`, `docs/hardware-smoke-checklist.md`, `docs/ops-runbook.md`
- Modification targets: `requirements.txt` (verify/complete pins); `docs/ops-runbook.md` (add pointers only)
- Acceptance criteria:
  - Root `.gitignore` covers pycache, logs, DBs, `.env`, IDE junk, `.nelson`, instance DB, atol.log (F-OPS-04) — review
  - systemd example: restart on failure, runs Flask service (F-OPS-05) — review
  - Hardware smoke checklist matches FSD §10.2 Hardware row — review
  - requirements.txt covers Flask stack + pytest for declared imports — review
  - Minimal code churn; no fiscal/tax/auth/Check-rename changes — review
- Validation required: Files exist; content matches F-OPS / §10.2
- Rollback note required: yes (delete new files / revert ops-runbook section)
- admiralty-action-required: no

Task ID: 2
- Name: Review Phase D packaging changes
- Owner: HMS Vigilant
- Ship: HMS Vigilant (destroyer — review)
- Crew manifest: Captain implements directly (read-only review)
- Deliverable: Must-fix / should-fix review of all Phase D changed files
- Dependencies: 1
- Station tier: 1
- File ownership: `.nelson/missions/2026-08-11_122513_3211d541/damage-reports/HMS-Vigilant.json`
- Acceptance criteria:
  - All changed files reviewed against AGENTS.md + FSD F-OPS / DoD — review
  - Must-fix items listed; no silent scope creep into fiscal/auth — review
- Validation required: Written damage/review report with verdict
- Rollback note required: no
- admiralty-action-required: no

Task ID: 3
- Name: Ensure pytest suite green
- Owner: HMS Assay
- Ship: HMS Assay (frigate)
- Crew manifest: Captain implements directly
- Deliverable: Suite stays green; add packaging/CI glue tests only if needed; report pass count
- Dependencies: 2
- Station tier: 1
- File ownership: `tests/**`, `pytest.ini`
- Modification targets: existing tests only if packaging broke them; document run via Resolute's ops-runbook (Assay verifies)
- Acceptance criteria:
  - `pytest -q` green with no regression from ~44 — test
  - Pass count reported — test
- Validation required: pytest stdout
- Rollback note required: yes if test files changed
- admiralty-action-required: no
