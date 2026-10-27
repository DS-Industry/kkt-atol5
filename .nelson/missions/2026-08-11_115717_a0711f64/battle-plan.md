# Battle Plan — Phase C Config + GUI + TCP

Commander's intent:
Site staff must configure USB or TCP driver reachability, persist those settings without redeploying code, and operate Admin screens A–D over the LAN — so AC-5 and AC-6 hold without SSH edits. Connection remains solely through CashierService (`applySingleSettings` then `open`); boot stays slim (no mass OFD/Wi‑Fi table rewrite). Driver TCP target (A) is the only IP field in Settings; fiscal sequence, `/create-check`, tax/payment mapping, and Check field names stay untouched. Unauthenticated admin on LAN is accepted for MVP but must be flagged for support. Optional F-DIAG-06/08 if time; not blocking. Team Lead does not implement; dispatch is developer → reviewer → test-engineer.

Workflow suitability: not selected because work is a sequential three-captain chain on shared files (conf/cashierService/main), not large fan-out or repeatable workflow orchestration.

Mode: **subagents** (sequential Task dispatches).

---

## Standing Order Check

- **becalmed-fleet:** No — multi-agent warranted (implement + review + test); files shared so sequential, not single-session admiral coding.
- **light-squadron:** Tasks = independent work units (1 implement, 2 review, 3 must-fix, 4 tests). Not under-split.
- **split-keel:** Resolute exclusive ownership of production files; Assay owns `tests/` only; Vigilant read-only. No conflicts.
- **unclassified-engagement:** All tasks have station tiers (2, 2, 2, 1).
- **all-hands-on-deck:** Captains implement/review/test directly — no idle crew roles.
- **skeleton-crew:** No single-crew atomic tasks; captains direct.
- **crew-without-canvas:** Three agents justified by mandatory dispatch order.
- **captain-at-the-capstan:** N/A — no multi-crew ships; captains do the work.
- **press-ganged-navigator:** Red-cell is Vigilant in review role only — no implementation.
- **admiral-at-the-helm:** Admiral coordinates only; no implementation.
- **wrong-ensign:** subagents mode — Task tool returns; no TeamCreate/SendMessage.
- **pulling-the-oar:** On failure, re-brief and re-dispatch; admiral does not absorb coding.

---

## Task 1 — Implement Phase C

- Name: Implement Phase C config + TCP + Admin GUI A–D
- Owner: HMS Resolute
- Ship: HMS Resolute (flagship)
- Crew: Captain implements directly
- Deliverable: Persistent `instance/config.json`; USB|TCP in CashierService; Admin screens A–D (D list-only); AC-5/AC-6
- Dependencies: none
- Station tier: 2
- File ownership: `conf.py`, `cashierService.py`, `main.py`, `templates/`, `instance/config.json` (schema), optional thin helper under project root if needed; may touch `requirements.txt` if deps added; may add minimal smoke in tests only if needed (Assay owns full suite)
- Modification targets:
  - `conf.py` — defaults + load/save for F-CFG-02 fields
  - `CashierService._initialize_device` / `ensure_connected` / `open_connection` — USB|TCP via `LIBFPTR_PORT_*`, `LIBFPTR_SETTING_IPADDRESS`, `LIBFPTR_SETTING_IPPORT`, `applySingleSettings` then open
  - `main.py` — load config at startup; log path from config; HTTP bind from config; admin routes/pages; extend `/health` with queue counts; reconnect action via service
  - New Jinja templates under `templates/admin/` for Screens A–D
- Acceptance criteria: inherited from Effects 1–6 (config round-trip; USB/TCP mocked settings; Settings Save/Reconnect/Reset; Status/Logs/Checks; no OFD mass write; no IFptr outside service; no unsafe retry; `/create-check` unchanged)
- Validation: smoke via FakeIFptr optional; full suite Assay
- Rollback note: yes — delete config.json → defaults; USB path
- admiralty-action-required: no

**Captain notes:**
- HTTP listen default: **FSD `0.0.0.0:5000`** in config defaults; document if `app.run` currently omits port.
- Label Settings IP as **Driver TCP target (Orange Pi → KKT)** only (F-CONN-07 A).
- Skip F-DIAG-06/08 unless cheap; note residual.
- Flag unauthenticated `/admin*` in residual risks.
- Follow `.cursor/skills/atol-docs/` for TCPIP settings; flask-api + python-patterns skills.
- Do NOT commit or push.

---

## Task 2 — Review Phase C

- Name: Review Phase C diff
- Owner: HMS Vigilant
- Ship: HMS Vigilant (destroyer / red-cell)
- Crew: Captain implements directly (read-only)
- Deliverable: Verdict APPROVE or REQUEST_CHANGES with must-fix list; damage-report JSON
- Dependencies: [1]
- Station tier: 2
- File ownership: none (read-only)
- Acceptance criteria: Control gate — fiscal layering, F-CONN-06/07/08, HTTP status match, no dangling receipts, no Screen D retry
- admiralty-action-required: no

---

## Task 3 — Fix review must-fixes

- Name: Fix review must-fixes
- Owner: HMS Resolute
- Ship: HMS Resolute
- Crew: Captain implements directly
- Deliverable: All REQUEST_CHANGES addressed or N/A if APPROVE
- Dependencies: [2]
- Station tier: 2
- File ownership: same as Task 1
- admiralty-action-required: no

---

## Task 4 — Phase C pytest suite

- Name: Add Phase C pytest (USB/TCP, config persist, GUI save)
- Owner: HMS Assay
- Ship: HMS Assay (frigate)
- Crew: Captain implements directly
- Deliverable: Tests green covering USB vs TCP settings, config load/save, settings save/reconnect path, admin contracts; Phase A+B remain green
- Dependencies: [1, 3]
- Station tier: 1
- File ownership: `tests/`, `pytest.ini`, `requirements.txt` (test deps only if needed)
- Acceptance criteria: Control — mocked IFptr; pytest green; count reported
- admiralty-action-required: no

---

## Squadron Formation Orders

```
Mode: subagents
Captain count: 3

Ships:
  HMS Resolute — flagship — Implement Phase C (config + TCP + Admin A–D)
    Crew: Captain implements directly
  HMS Vigilant — destroyer / red-cell — Review Phase C
    Crew: Captain implements directly (read-only)
  HMS Assay — frigate — Phase C pytest suite
    Crew: Captain implements directly

Permission: Admiral ordered execute this session — skip interactive gate; log permission_granted.
```
