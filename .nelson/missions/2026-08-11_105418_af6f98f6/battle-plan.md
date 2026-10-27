# Battle Plan — Phase A Safety

**Commander's intent:** Make the Orange Pi fiscal bridge fail safely — never claim success after a native failure, never leave a receipt open, never wipe the queue on restart, and never hang forever waiting on the KKT — without changing tax rules, car-wash field typos, or Phase B+ operability features.

**Workflow suitability:** not selected — three sequential specialist handoffs on a small file set; subagents mode with dependency chain.

## Standing Order Check
- **becalmed-fleet:** No — work needs specialist roles (impl / review / test), not admiral implementing.
- **light-squadron:** Three tasks = three independent work units (impl → review → test); not under-split.
- **split-keel:** T1 owns `cashierService.py`/`main.py`/`conf.py`; T2 read-only; T4 owns `tests/` + `requirements.txt`. No write conflicts.
- **unclassified-engagement:** T1 Station 2 (fiscal), T2 Station 2 (red-cell), T4 Station 1.
- **all-hands / skeleton / crew-without-canvas:** Captains implement/review/test directly — no extra crew.
- **captain-at-the-capstan / press-ganged-navigator / admiral-at-the-helm:** Code-reviewer is red-cell (read-only); admiral coordinates only.
- **wrong-ensign:** subagents mode — report via Agent return; admiral tracks.
- **pulling-the-oar:** On failed dispatch, re-brief and re-dispatch.

---

### Task 1 — Implement Phase A Safety
- **Name:** Implement Phase A fail-stop fiscal + queue
- **Owner:** senior-python-developer (HMS Resolute — flagship)
- **Crew:** Captain implements directly
- **Deliverable:** Working Phase A changes in service + Flask layers meeting AC-1..AC-4
- **Dependencies:** none
- **Station tier:** 2
- **File ownership:** `cashierService.py`, `main.py`, `conf.py` (minimal)
- **Modification targets:**
  - `CashierService._initialize_device` — slim to model/port/OFD channel only (P5 / F-CONN-06)
  - `CashierService.print_check` — fail-stop + cancelReceipt (P1, F-FISC-01..04,08)
  - `CashierService.checkClose` / cancel path (F-FISC-03)
  - `CashierService.openShift` / `get_shift_status` — timeouts (P4, F-FISC-05)
  - Device lock around fptr (F-FISC-06, F-Q-08)
  - `main.py` job lifecycle + remove `db.drop_all` (P2, P3, F-Q-01..03)
  - `find_actual_check` / QR wait timeout (P4, AC-4)
  - Timeout constants (shift 120s, QR 180s defaults)
- **Acceptance:** AC-1..AC-4; layering §3.1; payment `"0"`=cash else electronic; tax untouched; schema change called out
- **admiralty-action-required:** no

### Task 2 — Code review Phase A
- **Name:** Review Phase A diff
- **Owner:** code-reviewer (HMS Vigilant — destroyer / red-cell)
- **Crew:** Captain implements directly (read-only)
- **Deliverable:** Verdict + must-fix / should-fix findings
- **Dependencies:** Task 1
- **Station tier:** 2
- **File ownership:** read-only all changed `.py`
- **admiralty-action-required:** no

### Task 3 — Address must-fix (conditional)
- **Name:** Fix review must-fix
- **Owner:** senior-python-developer (HMS Resolute)
- **Dependencies:** Task 2 (only if must-fix exist)
- **Station tier:** 2
- **File ownership:** same as Task 1
- **admiralty-action-required:** no

### Task 4 — Pytest suite Phase A
- **Name:** Add mocked IFptr Phase A tests
- **Owner:** test-engineer (HMS Assay — frigate)
- **Crew:** Captain implements directly
- **Deliverable:** pytest covering fail at registration/payment/close→cancel; happy path; shift timeout; no drop_all; queue states; requirements.txt if missing
- **Dependencies:** Task 1 + Task 2/3 clear
- **Station tier:** 1
- **File ownership:** `tests/**`, `requirements.txt`, `conftest.py` as needed
- **admiralty-action-required:** no
