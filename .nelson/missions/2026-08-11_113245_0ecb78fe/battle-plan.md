# Battle Plan — Phase B Operability

**Commander's intent:** Make the ATOL bridge operable in production: checks polled by id with soft retention, device reconnect on link loss, health/diagnostics that tell support whether the fault is APP, LINK, KKT, or FN_OFD — without building Admin GUI (Phase C). Build on Phase A Safety; do not regress fail-stop, queue states, timeouts, or no-drop_all.

**Workflow suitability:** not selected because work is a single sequential Tier-M pipeline (implement → review → fix → test) on shared core files, not large fan-out / audit / migration.

## Standing Order Check

- **becalmed-fleet:** No — Tier M needs specialist subagents (Resolute / Vigilant / Assay) as ordered; not single-session admiral implementation.
- **light-squadron:** Task count = independent work units (implement, review, fix, test). Not under-split.
- **split-keel:** Task 1 owns app code + docs; Task 2 read-only; Task 3 same as 1 after review; Task 4 owns tests/. No parallel writers on same files.
- **unclassified-engagement:** All tasks have station_tier (2 for fiscal/ops code; 2 for review; 1 for tests).
- **all-hands-on-deck / skeleton-crew / crew-without-canvas:** Captains implement directly (0 crew) — atomic specialist roles already match agent types.
- **captain-at-the-capstan:** N/A (no crew).
- **press-ganged-navigator:** Red-cell is HMS Vigilant (code-reviewer) — review only, no implementation on review task.
- **admiral-at-the-helm:** Admiral coordinates only; no implementation.
- **wrong-ensign:** Mode `subagents` — Task tool dispatch; no agent-team messaging.
- **pulling-the-oar:** On failed dispatch, fix brief and re-dispatch; admiral does not absorb implementation.

---

## Task 1 — Implement Phase B operability

- **Owner:** HMS Resolute (`senior-python-developer`)
- **Ship:** HMS Resolute (flagship)
- **Crew:** Captain implements directly
- **Deliverable:** Phase B MUST features in code + `docs/ops-runbook.md` (or equivalent under `docs/`)
- **Dependencies:** none
- **Station tier:** 2
- **File ownership:** `cashierService.py`, `main.py`, `conf.py`, `docs/` (ops runbook / issues extension)
- **Modification targets:**
  - `main.py`: `find_actual_check`, `create_check`, Check model + schema migrate, soft-retain (no delete on QR success), scheduler start under real entrypoint, `/health`, `/admin/diagnostics`, RotatingFileHandler params
  - `cashierService.py`: reconnect with exponential backoff on not-opened / error 4; diagnostics ladder helpers; layer mapping; ensure connection before fiscal ops
  - `conf.py`: retention days, reconnect backoff knobs, log rotation size/count if not already
  - Docs: USB autosuspend + how APScheduler/`job1` starts in production
- **Acceptance criteria:**
  - F-Q-04: poll/wait by check id; response keeps practical backward-compatible fields (F-API-01)
  - F-Q-05: QR timeout configurable; 504 + id + status
  - F-Q-06: no delete on QR success; retention constant in conf; optional cleanup helper OK
  - F-Q-07: scheduler starts under real process entrypoint; documented in docs/
  - F-CONN-04: reconnect + backoff via CashierService only; clear logs for error 4
  - F-CONN-05: USB autosuspend documented
  - F-OPS-01: rotating file logs with sensible size + backupCount
  - F-OPS-02: `/health` DB + device open + shift; HTTP 200 vs 503
  - F-DIAG-01..05: failure fields + layer map + read-only ladder + Where/What next JSON + per-step health/diagnostics
  - F-DIAG-07 SHOULD: failed checks include `layer`
  - Schema changes called out explicitly (ALTER); no silent typo renames; no Phase C GUI
  - Phase A AC-1..AC-4 not regressed
- **Validation:** code review + pytest (later tasks)
- **Rollback note:** yes — schema ALTERs additive only
- **admiralty-action-required:** no

---

## Task 2 — Review Phase B diff

- **Owner:** HMS Vigilant (`code-reviewer`)
- **Ship:** HMS Vigilant (destroyer / red-cell)
- **Crew:** Captain implements directly (read-only review)
- **Deliverable:** REQUEST_CHANGES or APPROVE + must-fix / should-fix list
- **Dependencies:** [1]
- **Station tier:** 2
- **File ownership:** (read-only) `cashierService.py`, `main.py`, `conf.py`, `docs/`, `tests/` if present
- **Acceptance criteria:** Fiscal layering, HTTP status match, reconnect safety, no dangling receipts, schema callouts, Phase A non-regression
- **admiralty-action-required:** no

---

## Task 3 — Fix review must-fix

- **Owner:** HMS Resolute (`senior-python-developer`)
- **Ship:** HMS Resolute (flagship)
- **Deliverable:** Must-fix addressed or documented N/A with rationale
- **Dependencies:** [2]
- **Station tier:** 2
- **File ownership:** `cashierService.py`, `main.py`, `conf.py`, `docs/`
- **admiralty-action-required:** no

---

## Task 4 — Phase B pytest + keep Phase A green

- **Owner:** HMS Assay (`test-engineer`)
- **Ship:** HMS Assay (frigate)
- **Crew:** Captain implements directly
- **Deliverable:** pytest covering id-poll, soft-retain, reconnect, health/diagnostics, fault layers; Phase A tests still pass; `python3 -m pytest tests/ -v` green
- **Dependencies:** [1, 3]
- **Station tier:** 1
- **File ownership:** `tests/`, `pytest.ini`, `requirements.txt` (deps only)
- **Acceptance criteria:** New Phase B behaviors covered with mocked IFptr; prior Phase A tests pass
- **admiralty-action-required:** no

---

## Squadron Formation Orders

```
Mode: subagents
Captain count: 3 (Resolute, Vigilant, Assay) — sequential Resolute → Vigilant → (fix) → Assay

Ships:
  HMS Resolute — flagship — Implement Phase B operability
    Crew: Captain implements directly
  HMS Vigilant — destroyer / red-cell — Review Phase B
    Crew: Captain implements directly (read-only)
  HMS Assay — frigate — Phase B + Phase A pytest
    Crew: Captain implements directly

Red-cell navigator — HMS Vigilant (review task only)
```

Admiral ordered execute — permission gate auto-granted for this mission.
