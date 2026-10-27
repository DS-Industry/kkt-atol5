# The Estimate — Phase C Config + GUI + TCP

**Mission:** `.nelson/missions/2026-08-11_115717_a0711f64/`
**Checkpoint discipline:** Collapsed (admiral authorized). Sailing orders clear; Q1 no surprises; multi-file but single coherent subsystem “config+connect+admin UI”; proceed without human turn.

## 1. Reconnaissance

Terrain matches Phase B handoff. No reframing needed.

**Config (`conf.py`):** Module constants only — `LIBRARY_PATH`, timeouts (shift/QR/document), reconnect backoff, log rotation sizes. No connection mode, TCP IP/port, HTTP bind, log path, or `instance/config.json`. Comments explicitly defer TCP/GUI to Phase C. `main.py` hardcodes log `"atol.log"` and `app.run(host='0.0.0.0')` (port implicit 5000; AGENTS.md mentions 5050 — prefer conf default aligned with FSD `0.0.0.0:5000` or keep current run behavior; document chosen default).

**CashierService:** USB-only — `_initialize_device` sets `LIBFPTR_PORT_USB` then `applySingleSettings`. `ensure_connected` / `open_connection` USB path; docstring notes TCP left for Phase C. Open failures: `code` 500/503, `layer=LINK`. All `fptr` under `threading.RLock`. Boot applies model + port + OFD channel AUTO only — **no mass OFD/Wi-Fi table rewrite** (F-CONN-06 already held). Phase C must not reintroduce device-table commits.

**Admin/API:** JSON `GET /health` and `GET|POST /admin/diagnostics` ready for Screen A (connection/shift/layer/last_failure) but lack queue counts and reconnect action in health payload. No templates/static HTML. `GET /get-checks` sufficient for Screen D list. **No admin retry API / anti-double-print** — Screen D = list only (no unsafe retry). Tests: `FakeIFptr`, `app_db`, Phase B endpoint patterns reusable. `requirements.txt` has Flask stack + pytest.

**IP disambiguation (F-CONN-07):** Implement Settings field (A) Driver TCP target only; label clearly; do not expose (B)/(C) unless read-only labels already exist (they do not).

**Surprises:** None material. HTTP listen port default inconsistency (AGENTS 5050 vs Flask 5000) — resolve in defaults to FSD Screen B `0.0.0.0:5000` or preserve `app.run` behavior; call out in captain brief.

## 2. Intent

Site staff must configure USB or TCP driver reachability, persist those settings without redeploying code, and operate Admin screens A–D over the LAN — so AC-5 and AC-6 hold without SSH edits. Connection remains solely through CashierService (`applySingleSettings` then `open`); boot stays slim (no mass OFD/Wi‑Fi table rewrite). Driver TCP target (A) is the only IP field in Settings; fiscal sequence, `/create-check`, tax/payment mapping, and Check field names stay untouched. Unauthenticated admin on LAN is accepted for MVP but must be flagged for support. Optional F-DIAG-06/08 if time; not blocking. Team Lead does not implement; dispatch is developer → reviewer → test-engineer.

## 3. Effects

### Effect: Persistent config load, save, and defaults (F-CFG-01–04)

Lands on `conf.py` plus `instance/config.json` (or equivalent under `instance/`). Medium complexity.

**Commander's guidance:** Ship a defaults map covering F-CFG-02 (mode USB|TCP, driver IP/port default 5555, library path, HTTP bind host/port, QR/shift timeouts, log path, max log lines). Prefer FSD Screen B default `0.0.0.0:5000` for HTTP listen unless preserving current `app.run` behavior is called out and documented. Load file at startup; merge over defaults; save atomically. No secrets required. Env override optional, not required.

**Acceptance criteria:**
- Missing config file yields documented defaults; app still starts
- Round-trip save/load preserves mode, IP, port, and F-CFG-02 fields
- Config is editable without code redeploy (file under `instance/` or documented path)
- Chosen HTTP listen default is explicit in code or captain brief (resolve AGENTS 5050 vs Flask 5000)

### Effect: CashierService USB|TCP connect via applySingleSettings + open (F-CONN-01–03, 07–08)

Lands on `cashierService.py` (consume `libfptr10` only; no vendor style edits). High complexity — fiscal-adjacent device path.

**Commander's guidance:** Read connection mode and TCP IP/port from config (not hardcoded USB). USB → `LIBFPTR_PORT_USB`; TCP → `LIBFPTR_PORT_TCPIP` with driver `IPAddress`/`IPPort`. Always `applySingleSettings()` then `open()`; check `errorCode()`; surface failures with clear `code`/`layer=LINK`. Keep existing RLock and F-CONN-04 backoff on fiscal paths. Do not reintroduce mass OFD/device-table commits on boot (F-CONN-06). Routes and GUI never call `IFptr` (F-CONN-08). atol-docs for TCPIP parameters.

**Acceptance criteria:**
- Config mode USB opens with USB port setting; TCP opens with configured IP/port (mocked IFptr)
- Open failure returns non-200 service `code` with description; HTTP status matches when exposed
- Boot path does not write full OFD/Wi‑Fi/IP device tables
- No `IFptr` usage outside `CashierService`

### Effect: Admin Screen B — Settings API/UI and reconnect (F-CFG-03, F-CONN-07)

Lands on `main.py` admin routes plus templates/static under `/admin`. Medium complexity.

**Commander's guidance:** Screen B fields per FSD: mode USB|TCP, KKT IP (enabled when TCP), port (default 5555), library path, QR/shift timeouts, HTTP host/port. Buttons: Save; Save & reconnect; Reset to defaults. Label the IP field as **driver TCP target** (Orange→KKT) only — do not expose or conflate KKT Ethernet params or OFD host (prefer A). Save persists config; Save & reconnect applies via CashierService and warns if device busy. Flask layering: HTTP in `main.py`, device work only through service.

**Acceptance criteria:**
- GET shows current settings; POST save writes config and returns success/error with correct HTTP status
- Save & reconnect invokes CashierService reconnect/open — not direct `IFptr`
- TCP IP field labeled as driver target; no OFD/KKT-Ethernet settings fields
- Reset restores F-CFG-04 defaults

### Effect: Admin Screen A — Status wired to health/diagnostics (AC-6)

Lands on `main.py` (`/health`, `/admin/diagnostics`, admin Status page). Medium complexity.

**Commander's guidance:** Wire Screen A to existing health/diagnostics JSON: connection, shift (OPEN/CLOSED/EXPIRED), fault layer + short hint, last failure. Add queue counts (pending/printing/failed/done today). Actions: Reconnect, Run diagnostics, Refresh — all via CashierService / existing diagnostic ladder; no sell receipt. Extend health payload if queue counts or reconnect action are missing. Optional F-DIAG-06 support-report / F-DIAG-08 TCP ping only if time.

**Acceptance criteria:**
- Status page shows connection, shift, fault layer, queue summary, last error
- Reconnect and Run diagnostics work from UI without calling `IFptr` from the route
- `/health` or diagnostics JSON remains usable for remote LAN support (per-step or status fields intact)
- F-DIAG-06/08 absent is acceptable if time-boxed; note residual if skipped

### Effect: Admin Screen C — Logs tail

Lands on `main.py` admin Logs route/UI reading configured log path. Low–medium complexity.

**Commander's guidance:** Tail last N lines of configured log (default `atol.log` / F-CFG path; N from config, e.g. 200–500). Manual refresh; optional auto-refresh ~5s. Optional ERROR/INFO filter. Never dump Wi‑Fi/device passwords. Highlight of codes 4/123/OFD is SHOULD, not blocking.

**Acceptance criteria:**
- Logs screen shows last N lines from configured path
- Refresh updates content; path respects config when set
- No secrets from settings dumps appear in the log view payload

### Effect: Admin Screen D — Checks list without unsafe retry

Lands on `main.py` admin Checks page using existing `GET /get-checks` (or thin admin wrapper). Low complexity.

**Commander's guidance:** List recent checks: id, bay, sum, status, QR present, last error/layer if available. **No retry button** — no anti-double-print API exists; retry would risk double fiscal print. Soft-complete/audit rows remain readable. Stub is acceptable per sailing orders.

**Acceptance criteria:**
- Checks screen lists recent rows with status and error fields sufficient for support
- No retry/re-print control that re-enters the fiscal sequence
- `/create-check` client contract unchanged

### Control (not an effect): Review and mocked test gate

**Commander's guidance:** After implementation, mandatory dispatch: `code-reviewer` then `test-engineer`. Tests use `FakeIFptr` / fixtures — cover USB and TCP connect paths, config persist round-trip, and GUI/API save. Reviewer APPROVE or REQUEST_CHANGES must be addressed before stand-down. No commit/push this mission. Team Lead does not implement.

**Acceptance criteria:**
- pytest green for USB/TCP connect + config persistence + settings save (mocked device)
- code-reviewer verdict APPROVE, or all REQUEST_CHANGES items fixed and re-checked
- No commit or push; handoff artifacts note residual risks (incl. unauthenticated admin LAN)

## 4. Terrain

One coherent subsystem — config, driver connect, and Admin UI — lands on a small, shared set of files. Split-keel risk is real if two writers touch the same modules; therefore a single implementation captain owns all production code for this mission.

| Effect | Primary landfall | Blast radius |
|--------|------------------|--------------|
| Persistent config (F-CFG-01–04) | `conf.py`; new `instance/config.json` (optional thin config helper only if `conf.py` grows unwieldy) | Startup path in `main.py` (load before routes/app.run); any module that today reads module-level constants |
| USB\|TCP connect (F-CONN-01–03, 07–08) | `cashierService.py` (`_initialize_device` / `open_connection` / reconnect) | Every fiscal and diagnostic path that calls `ensure_connected`; **not** `libfptr10.py` (consume only) |
| Screen B Settings + reconnect | `main.py` admin settings routes; new `templates/` (and minimal static if needed) under `/admin` | Config save/load API; CashierService reconnect entrypoints only — no direct `IFptr` |
| Screen A Status | `main.py` (`/health`, `/admin/diagnostics`, Status template); may extend health JSON with queue counts | Existing Phase B JSON consumers (keep fields intact; additive only) |
| Screen C Logs | `main.py` Logs route/UI; configured log path (today hardcoded `atol.log`) | Read-only file tail — no device calls |
| Screen D Checks | `main.py` Checks template (thin wrapper over `GET /get-checks`) | List-only; **no** retry into fiscal sequence |

**Tests:** `tests/` (existing `FakeIFptr`, `conftest`, Phase B patterns). New coverage for USB/TCP connect, config round-trip, settings save/reconnect API. Test-engineer owns the suite; developer may leave thin smoke hooks only.

**Out of blast radius:** `libfptr10.py`, Check field renames, `/create-check` client contract, tax/payment mapping, mass OFD/device-table writes on boot.

## 5. Forces

Mode: **subagents** — sequential Task dispatches; no parallel captains on shared files. Admiral / Team Lead coordinates only; does **not** implement.

| Ship | Agent type | Role |
|------|------------|------|
| **HMS Resolute** (flagship) | `senior-python-developer` | Sole implementation captain — owns `conf.py`, `cashierService.py`, `main.py`, `templates/` (+ optional config helper). Ships all six effects; may add minimal smoke tests. Station 2+ on connect/settings; Station 1–2 on list/logs GUI. |
| **HMS Vigilant** (destroyer / red-cell) | `code-reviewer` | Read-only review after implementation (and after any must-fix pass). Fiscal layering, F-CONN-06/07/08, HTTP status match, no dangling receipts, no unsafe Screen D retry. |
| **HMS Assay** (survey) | `test-engineer` | Owns Phase C pytest suite: USB/TCP mocked connect, config persist, settings save/reconnect, admin API/UI contracts as testable. Extends `FakeIFptr` / fixtures; does not rewrite production fiscal sequence. |

Explore / generalPurpose: recon only — already spent in Q1; do not re-dispatch for implementation. No navigator, marines, or multi-crew canvas — captains implement (or review/test) directly. Skills in briefs: `flask-api`, `python-patterns` for Resolute/Vigilant; `pytest` for Assay; `atol-docs` anchor for TCPIP params on the connect effect.

## 6. Coordination

**Dependency chain (strictly sequential — no parallel writers):**

1. **Resolute — implement.** Order of work *within* the single captain (same ownership, logical sequence):
   - Config defaults + load/save (`conf.py` / `instance/config.json`) first — every later effect reads it.
   - CashierService USB|TCP via `applySingleSettings` → `open` (consumes config; F-CONN-06/08 held).
   - Admin Screen B (Settings + Save / Save & reconnect / Reset) — needs both config and service reconnect.
   - Screens A → C → D (Status, Logs, Checks) — A may extend health; C/D are thinner and may trail if time-boxed; D remains list-only stub if needed.
2. **Vigilant — review.** Depends on Resolute complete. Verdict APPROVE or REQUEST_CHANGES.
3. **Resolute — must-fix** (if REQUEST_CHANGES). Same file ownership; no new parallel ship.
4. **Assay — Phase C tests.** Depends on review gate cleared (APPROVE or must-fix done). Owns `tests/`; may read production code, must not fight Resolute on `main.py`/`cashierService.py` mid-implementation.

**Shared surfaces:** `instance/config.json` schema and CashierService reconnect contract — defined once by Resolute; Vigilant and Assay verify, do not redesign. Coordination artifact: mission dir battle plan / captains-log; no cross-captain file locks beyond sequential dispatch.

**Not parallel:** Do not split Screens A–D to a second developer while connect lands — shared `main.py`/`templates/`. Do not run Assay writers before Vigilant has ruled on the connect path.

## 7. Control

**Quality gates**
- After implementation: Vigilant must return APPROVE, or every REQUEST_CHANGES item fixed and re-checked before stand-down.
- Before stand-down: pytest green for USB/TCP connect, config persistence, and settings save (mocked `IFptr`); Assay owns the suite count reported in handoff.
- Layering spot-checks: no `IFptr` outside `CashierService`; boot does not mass-write OFD/Wi‑Fi tables; Screen D has no retry control; HTTP status matches service `code`.

**Action stations**
- Station **2+**: TCP/USB connect path and Settings save & reconnect (fiscal-adjacent device path; errorCode discipline).
- Station **1–2**: Admin list/logs GUI and read-only status/log tail.
- Review and test tasks: Station **2** (review of fiscal-adjacent code) and Station **1** (mocked suite) respectively unless the Battle Plan tightens.

**Intervention points**
- HTTP listen default (AGENTS 5050 vs Flask/FSD `0.0.0.0:5000`) — captain brief must pick and document; admiral inspects if ambiguous.
- Unauthenticated admin on LAN — accepted for MVP; must be flagged in residual risks / support handoff.
- Optional F-DIAG-06/08 — time-box; skip is acceptable if residual noted.
- No commit/push this mission — admiral does not authorize git publish.

**Rollback**
- Delete or rename `instance/config.json` → documented defaults; USB-only behavior restored if code paths honor missing file.
- Templates/admin routes are additive; disable by not mounting or reverting the Resolute diff.
- No schema typo renames; no irreversible device-table commits on boot — prefer file/config rollback over device reflash.
- If TCP connect proves wrong against live hardware, mocked tests still gate CI-local; hardware smoke is out of this mission’s mandatory metric unless available.
