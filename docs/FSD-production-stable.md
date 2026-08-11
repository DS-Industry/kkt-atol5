# Functional Specification Document (FSD)

**Product:** kkt-atol5 — ATOL fiscal bridge on Orange Pi  
**Version:** 1.2 (draft)  
**Status:** Proposed for production-stable release  
**Audience:** Developers, site ops, product owner, tech support  
**Related:** `AGENTS.md`, `docs/issues/issues.md`, [ATOL Native API](https://integration.atol.ru/api-en)  
**Reviews incorporated:** team-lead outline, code-reviewer must-cover checklist, test-engineer AC/test matrix; fault-isolation for support

---

## 1. Purpose

Define what must change so the service is **stable in production**, **low-maintenance**, and operable by site staff without editing Python.

**Goals**
- Fiscal receipts complete or fail safely (no dangling open checks).
- Survive slow KKT / USB / OFD problems without hanging workers or overflowing the queue.
- Configure connection (USB or TCP), IPs, and timeouts via a simple GUI — not code.
- View recent logs from the same GUI.
- Let tech support **tell Orange Pi / app faults from KKT / FN / OFD faults** without guessing.
- Deploy once; routine ops = GUI + reboot checklist, not SSH code patches.

**Non-goals (this release)**
- Full internet-facing auth / multi-tenant SaaS.
- Replacing the car-wash HTTP client protocol (unless noted as optional improvement).
- Rewriting `libfptr10.py` vendor wrapper.

---

## 2. Current architecture (as-is)

```
Car wash controllers  --HTTP-->  Orange Pi (Flask + SQLite + APScheduler)
                                      |
                                     USB
                                      v
                                   ATOL KKT  ----OFD----> Fiscal operator
```

| Layer | Role today |
|-------|------------|
| Car wash | `POST /create-check` with JSON in `Data` header; waits for QR |
| Orange Pi app | Enqueue check → background job opens shift / prints → returns QR |
| KKT | Fiscalize sell receipt over USB via `libfptr10` |

**Known production pain** (`docs/issues/issues.md`): PSU sag under load; shifts/checks ~5 min → DB/queue overflow; FN error 123 (receipt won’t close); FD storage exhausted / OFD not sending; USB error 4 (Orange doesn’t see KKT; often `usbcore.autosuspend`).

---

## 3. Target architecture (to-be)

```
Car wash  --HTTP-->  Orange Pi app  --USB or TCP-->  ATOL KKT  --> OFD
                         |
                    Admin GUI (local)
                    config + logs + status
```

| Change | Why |
|--------|-----|
| USB **or** TCP to KKT | Avoid USB autosuspend / cable flakiness when Ethernet available |
| Config file + Admin GUI | No code edits for IP, port, timeouts, library path |
| Durable queue states | No silent loss; no infinite HTTP wait |
| Fail-stop fiscal path | Compliance + recoverability (AGENTS.md §4) |
| Health / status page | Ops sees device/shift without SSH |

**LAN trust:** API authentication remains **optional**. Service stays on trusted local network. GUI may use a simple shared PIN later; not required for MVP.

---

## 4. Problems to eliminate (must-fix)

| ID | Current behavior | Required behavior |
|----|------------------|-------------------|
| P1 | `print_check` logs fiscal errors and continues; returns success | Abort on first native failure; `cancelReceipt` if opened; return real error |
| P2 | Job sets `isProcessed=True` before print | Set processed/done only after successful print + QR (or explicit `failed`) |
| P3 | `db.drop_all()` on every start | Never wipe DB on boot; create schema if missing only |
| P4 | `openShift` / `find_actual_check` wait forever | Hard timeouts; HTTP 504/503; retryable failed state |
| P5 | ~50 device settings rewritten every process start | Runtime: model/port/IP only; OFD/network = one-time provisioning |
| P6 | Check row deleted after QR | Keep row (soft-complete); match by `id`, not `name` |
| P7 | No reconnect on USB drop | Detect not-open; reconnect with backoff |
| P8 | No dependency/deploy hygiene | `requirements.txt`, `.gitignore`, documented run (systemd or equivalent) |
| P9 | Config only in code | GUI + file/env for connection and timeouts |
| P10 | Logs only on disk via SSH | Simple log viewer in Admin GUI |

---

## 5. Functional requirements

### 5.1 Fiscal printing (CashierService) — MUST

| ID | Requirement |
|----|-------------|
| F-FISC-01 | Keep receipt order: open → register → payment → tax → total → close ([ATOL receipt algorithm](https://integration.atol.ru/api-en/#general-algorithm-for-receipt-formation)). |
| F-FISC-02 | After each critical native call, check return / `errorCode()`; on failure **stop** and do not call later steps. |
| F-FISC-03 | If receipt was opened and later step fails, call `cancelReceipt()` (or documented `checkDocumentClosed` + cancel). Wire logic currently unused in `checkClose`. |
| F-FISC-04 | Never return success (`201`) when any step failed; return `{code, message, error_code?}`. |
| F-FISC-05 | Before printing: require shift OPEN; if EXPIRED → close-shift report then open; if CLOSED → open. All with timeouts. |
| F-FISC-06 | Serialize all `fptr` access (lock or single worker thread) — USB/TCP driver is not treated as thread-safe. |
| F-FISC-07 | Payment type mapping documented and validated (`"0"` = cash, else electronic) — confirm with business before changing. |
| F-FISC-08 | Do not truncate money incorrectly; use decimal-safe handling for sums (avoid bare `int()` truncating kopecks if floats are used). |

### 5.2 Queue / scheduler / HTTP — MUST

| ID | Requirement |
|----|-------------|
| F-Q-01 | Check lifecycle states: at least `pending` → `printing` → `done` \| `failed` (may map to booleans + status field). |
| F-Q-02 | Mark `printing` when job starts; `done` only after close + QR stored; on failure → `failed` with reason, eligible for limited retry. |
| F-Q-03 | Remove `db.drop_all()` from startup. |
| F-Q-04 | `/create-check`: prefer return by **check id**; poll/wait keyed by **id**, not commodity `name`. |
| F-Q-05 | Waiting for QR: configurable timeout (default e.g. 120–180s); on timeout return 504 with check id and status. |
| F-Q-06 | Do not delete completed checks by default; retain for audit (retention policy configurable, e.g. 30 days). |
| F-Q-07 | Scheduler must run under the real process entrypoint (not only accidental `__main__` quirks); document how it starts under production runner. |
| F-Q-08 | Cap concurrent in-flight prints to 1 (device lock); queue the rest. |

### 5.3 Connection: USB and TCP — MUST

| ID | Requirement |
|----|-------------|
| F-CONN-01 | Support `LIBFPTR_PORT_USB` and `LIBFPTR_PORT_TCPIP` via config (not hardcode). |
| F-CONN-02 | For TCP: configurable **driver** `IPAddress` / `IPPort` (default 5555) — how Orange Pi reaches the KKT. |
| F-CONN-03 | Apply connection settings with `applySingleSettings()` then `open()`; surface open failure clearly. |
| F-CONN-04 | On “port unavailable” / not opened: reconnect with backoff; log error 4 class clearly. |
| F-CONN-05 | Document Orange Pi USB fix (`usbcore.autosuspend=-1`) in ops runbook when USB mode is used. |
| F-CONN-06 | Stop committing full OFD/Wi‑Fi/IP device tables on every app start; separate **provisioning** from **runtime connect**. |
| F-CONN-07 | **Disambiguate IPs in GUI:** (A) Driver TCP target (Orange→KKT) vs (B) KKT’s own Ethernet settings (device params 71–74) vs (C) OFD host — label each field; never conflate. |
| F-CONN-08 | GUI / routes never call `IFptr` directly — only via `CashierService` (AGENTS.md §3.1). |

### 5.4 Configuration — MUST

| ID | Requirement |
|----|-------------|
| F-CFG-01 | Persist settings in a local file (e.g. `instance/config.json` or env + file) editable without redeploying code. |
| F-CFG-02 | Configurable at minimum: connection mode (USB/TCP), KKT IP, KKT TCP port, library path, HTTP bind host/port, QR wait timeout, shift open timeout, log path, max log lines shown. |
| F-CFG-03 | Changing connection settings applies on “Save + reconnect” (or next safe restart); GUI warns if device busy. |
| F-CFG-04 | Defaults shipped for known site; no secrets required for LAN MVP. |

### 5.5 Admin GUI — MUST

Simple local web UI (same Flask app or static pages under `/admin`), usable on phone/laptop on LAN.

#### Screen A — Status (home)

| Element | Behavior |
|---------|----------|
| Device connection | Connected / disconnected + last error |
| Shift state | OPEN / CLOSED / EXPIRED |
| Queue summary | Counts: pending, printing, failed, done (today) |
| **Fault layer** | Clear label: `APP` / `LINK` / `KKT` / `FN_OFD` / `UNKNOWN` + short Russian/English hint for support |
| Actions | Reconnect device; **Run diagnostics**; Refresh status |

#### Screen B — Settings

| Field | Notes |
|-------|--------|
| Connection mode | USB \| TCP |
| KKT IP | Enabled when TCP |
| KKT port | Default 5555 |
| Library path | Default `/usr/lib/` |
| QR wait timeout (s) | Default 180 |
| Shift open timeout (s) | Default 120 |
| HTTP listen host/port | Advanced; default `0.0.0.0:5050` |
| Buttons | Save; Save & reconnect; Reset to defaults |

#### Screen C — Logs

| Element | Behavior |
|---------|----------|
| Tail of `atol.log` (or configured path) | Last N lines (e.g. 200–500) |
| Refresh | Manual + optional auto-refresh every 5s |
| Filter | Optional: level contains ERROR / INFO |
| Highlight | SHOULD: known codes 4, 123, OFD exhausted |
| No secrets | Never display Wi‑Fi/device passwords from settings dumps |

#### Screen D — Checks / queue (SHOULD)

| Element | Behavior |
|---------|----------|
| Recent checks | id, bay, sum, status, QR present, last error |
| Retry | Manual retry for `failed` only, with anti-double-print rules |
| No delete on success | Soft-complete rows remain for audit |

**GUI constraints**
- Russian or bilingual labels OK for site staff.
- No complex dashboard cards; one purpose per screen.
- All device actions go through `CashierService`, not routes.

### 5.6 API (car wash) — MUST / SHOULD

| ID | Priority | Requirement |
|----|----------|-------------|
| F-API-01 | MUST | Keep `/create-check` working for existing clients (header `Data` JSON). |
| F-API-02 | SHOULD | Also accept JSON body; document both. |
| F-API-03 | MUST | Validate required fields; 400 on bad input. |
| F-API-04 | MUST | HTTP status reflects outcome (timeout → 504; device down → 503; fiscal fail → 502/500 with stable error body). |
| F-API-05 | SHOULD | Optional async mode: 202 + `{id}` + `GET /checks/<id>` for status/QR (reduces worker blocking). |
| F-API-06 | COULD | Optional shared API key header — off by default on LAN. |

### 5.7 Observability & ops — MUST / SHOULD

| ID | Priority | Requirement |
|----|----------|-------------|
| F-OPS-01 | MUST | Rotating file logs retained. |
| F-OPS-02 | MUST | `/health` or Admin status: DB ok + device open + shift (best-effort). |
| F-OPS-03 | MUST | `requirements.txt` with pinned Flask stack. |
| F-OPS-04 | MUST | Root `.gitignore` (pycache, logs, DBs, `.env`, IDE junk). |
| F-OPS-05 | SHOULD | systemd unit example for Orange Pi (restart on failure). |
| F-OPS-06 | SHOULD | Short ops runbook: USB autosuspend, OFD check, when to replace PSU/KKT. |

### 5.8 Fault isolation for tech support — MUST

Support must answer in minutes: **is it our Orange Pi / Python service, the USB/TCP link, or the KKT (FN/OFD/hardware)?**

#### Layers (classification model)

| Layer code | Meaning | Typical ownership |
|------------|---------|-------------------|
| `APP` | Flask process, SQLite, queue/state machine, timeouts, config | Our software / Orange Pi deploy |
| `LINK` | Driver cannot open/reach device (USB port, TCP unreachable, autosuspend) | Cabling / Orange USB / network / KKT power-on |
| `KKT` | Device opened but fiscal/shift command fails (busy, paper, shift logic, firmware) | Cash register / site ops |
| `FN_OFD` | FN/OFD errors (e.g. 123 no FN data, FD storage exhausted, OFD exchange) | FN / OFD settings / operator contract |
| `HW_ENV` | Power sag, overheat (from issues.md) — not detectable as a clean SDK code always | Hardware / PSU |
| `UNKNOWN` | Insufficient signal | Escalate with diagnostics bundle |

#### Requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| F-DIAG-01 | MUST | Every failure (API, job, reconnect) stores: `layer`, `step` (e.g. `open`, `openReceipt`, `payment`), `error_code`, `error_description`, `check_id`, timestamp. |
| F-DIAG-02 | MUST | Map known ATOL / field codes to default layer (see table below); allow override when context differs (e.g. open failed after valid TCP = LINK). |
| F-DIAG-03 | MUST | Admin **Run diagnostics** runs a **read-only ladder** (no sell receipt): (1) app+DB alive → (2) library loadable → (3) `open` / `isOpened` → (4) `get_shift_status` / device status → (5) FN/OFD status queries (best-effort). Stop at first fail; show which step failed + layer. |
| F-DIAG-04 | MUST | Status / diagnostics UI shows last result as: **Where:** APP\|LINK\|KKT\|FN_OFD + **What to do next** (one short sentence). |
| F-DIAG-05 | MUST | `/health` (or `/admin/diagnostics`) returns JSON with per-step pass/fail for remote support over LAN. |
| F-DIAG-06 | SHOULD | “Copy support report” / download: last diagnostics + last N log lines + config mode (USB/TCP, IP redacted secrets) + app version/commit. |
| F-DIAG-07 | SHOULD | Queue failed checks show the same `layer` so support can filter “all LINK today” vs “all FN_OFD”. |
| F-DIAG-08 | COULD | Optional ping of KKT TCP port when mode=TCP (OS-level) to separate network from driver. |

#### Default error → layer mapping (initial)

| Signal | Layer | Support hint |
|--------|-------|--------------|
| Process down / HTTP unreachable | `APP` | Restart service / Orange Pi; check systemd |
| SQLite error / schema / wiped queue | `APP` | Our app/data path |
| App timeout while device never opened | `LINK` or `APP` | Diagnostics ladder decides |
| Error **4** port unavailable / `isOpened==0` | `LINK` | USB cable/autosuspend **or** TCP IP/port/power; try TCP if USB flaky |
| Open OK, shift/report/receipt `errorCode` ≠ 0 (not FN/OFD specific) | `KKT` | Shift state, paper, device busy; replace/service KKT if persistent |
| FN **123** / no data in FN / close fails with FN codes | `FN_OFD` | FN/KKT fiscal memory — not fixed by restarting Flask alone |
| FD resource exhausted / OFD not accepting | `FN_OFD` | OFD host/port/channel; operator portal |
| Slow ops (~5 min) then overflow | `KKT` or `HW_ENV` | PSU/KKT load; app must still timeout and label `KKT`/`LINK` not hang as silent APP bug |
| Happy diagnostics, car-wash HTTP 400 | `APP` | Client payload / our validation |

#### Support decision rule (documented in GUI)

1. Run **Diagnostics**.  
2. If fails at steps 1–2 → **our side (APP / Orange Pi)**.  
3. If fails at step 3 → **link** (USB/TCP/power) before blaming software logic.  
4. If open works but step 4–5 fail → **KKT / FN / OFD**.  
5. Attach support report; do not ask for “try reboot everything” without this split.

---

## 6. Data model changes

| Change | Notes |
|--------|--------|
| Add `status` (`pending`/`printing`/`done`/`failed`) | Replaces overloaded boolean-only flow |
| Keep `isProcessed` / `isQr` during transition **or** migrate deliberately | Call out migration; no silent rename of public API fields without notice |
| Store `error_message`, `error_code`, `retry_count` | Ops / GUI |
| Always set `dateProcessed` on terminal state | |
| Do not delete on QR return | Soft-complete |
| **Schema:** manual SQLite change or `create_all` for new columns — document one-time upgrade steps (no Alembic required for MVP) | AGENTS.md §6 |

---

## 7. Non-functional requirements

| ID | Area | Requirement |
|----|------|-------------|
| NFR-01 | Stability | No unbounded loops; all device waits timeout. |
| NFR-02 | Maintainability | Site changes IP/mode via GUI; no Python edit for routine config. |
| NFR-03 | Resilience | USB/TCP reconnect; failed checks retry N times then stay `failed` visible in GUI. |
| NFR-04 | Performance | Single fiscal operation at a time; HTTP handlers must not block for minutes without timeout. |
| NFR-05 | Compliance | Fiscal sequence and cancel-on-fail per ATOL docs + AGENTS.md §4. |
| NFR-06 | Testability | Unit tests with mocked `IFptr`; CI without hardware. |
| NFR-07 | Deploy | Documented start command; survives Orange Pi reboot without wiping queue. |

---

## 8. Out of scope (this release)

- Cloud monitoring / mobile app.
- Multi-KKT load balancing.
- Changing tax regime without business sign-off.
- Auto-fix of Orange Pi kernel USB settings (document only).
- Full Flask-Migrate/Alembic unless time allows.
- Redesign of car-wash payment UX.

---

## 9. Delivery phases

### Phase A — Safety (stop data loss & fiscal dangling) — **P0**
P1–P4, F-FISC-*, F-Q-01–03, F-Q-08, remove settings rewrite (P5).

### Phase B — Operability (timeouts, reconnect, health, fault isolation) — **P0/P1**
F-Q-04–07, F-CONN-04–05, F-OPS-01–02, **F-DIAG-*** (diagnostics ladder + layer labels).

### Phase C — Config + GUI + TCP — **P1**
F-CFG-*, F-CONN-01–03, Admin screens A–D (Status with fault layer, Settings, Logs, Checks).

### Phase D — Packaging & tests — **P1**
requirements, gitignore, systemd example, pytest with mocked IFptr, hardware smoke checklist.

---

## 10. Acceptance criteria & test plan

### 10.1 MUST acceptance (release gate)

| ID | Criterion |
|----|-----------|
| AC-1 | Mid-sequence fiscal failure → fail-stop + `cancelReceipt`; never return success |
| AC-2 | Job states: pending → printing → done\|failed; success flags only after print+QR |
| AC-3 | No `db.drop_all()` on boot; data survives restart |
| AC-4 | Configurable timeouts on shift open and QR wait; no infinite loops |
| AC-5 | USB\|TCP selectable; TCP IP/port valid; no mass OFD overwrite on boot |
| AC-6 | Admin GUI: Status, Settings (incl. driver IP), Logs; settings persist |
| AC-7 | HTTP 400 on bad input; HTTP status matches service outcome |
| AC-8 | Diagnostics ladder classifies fail as APP / LINK / KKT / FN_OFD; support report exportable |

Auth (AC optional): off by default on trusted LAN; if enabled later, config-write stricter than log-read.

### 10.2 Test matrix (summary)

| Layer | Coverage |
|-------|----------|
| **Unit (CI, mock IFptr)** | Fail at registration/payment/close → cancel; happy path; shift timeout; USB vs TCP settings; error→layer mapping (4→LINK, 123→FN_OFD) |
| **Integration (CI)** | Create → pending; success/fail states; no drop_all on restart; QR wait timeout; GUI save + log tail; `/create-check` 400; diagnostics JSON stop-at-fail |
| **Hardware (Orange Pi)** | USB and/or TCP open; one sell+QR; restart keeps DB; mid-fail recover if safe; diagnostics with cable unplugged → LINK |

OFD/FN-123/PSU: ops/hardware — software must fail-stop and log when device returns those codes.

### 10.3 Definition of done

- [ ] AC-1–AC-7 met; mocked tests green in CI  
- [ ] Hardware smoke signed off for sequence changes (AGENTS.md §10)  
- [ ] `requirements.txt`, `.gitignore`, ops runbook for issues.md  
- [ ] GUI usable for day-2 IP/mode/timeout/log without SSH code edits  

---

## 11. Risks & assumptions

| Risk | Mitigation |
|------|------------|
| KKT without Ethernet | Keep USB mode; apply autosuspend fix |
| TCP still slow if PSU weak | Hardware; GUI/status won’t fix voltage sag |
| Existing clients depend on blocking QR response | Keep sync wait with timeout; optional 202 later |
| Mojibake in item names | Fix encoding in same release as GUI polish |
| Overwriting OFD settings historically “helped” a site | Move to explicit provisioning tool, not boot path |

**Assumptions:** Trusted LAN; one KKT per Orange Pi; car wash remains HTTP client.

---

## 12. Traceability to field issues

| Field issue | FSD coverage |
|-------------|--------------|
| 5 min ops → DB overflow | Timeouts, single-flight print, proper states, no premature processed; layer `KKT`/`HW_ENV` not silent hang |
| 123 / receipt won’t close | Fail-stop + cancel; layer `FN_OFD` in diagnostics |
| OFD / FD exhausted | Stop blind settings rewrite; diagnostics step FN/OFD → `FN_OFD` |
| USB error 4 | TCP option + reconnect; diagnostics open-fail → `LINK` |
| PSU overheat | Documented `HW_ENV`; app still times out and reports device stall |
| “Is it us or the KKT?” | §5.8 fault layers + Run diagnostics + support report |

---

## 13. Document control

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2026-08-11 | Initial FSD from production audit + LAN architecture + GUI/TCP needs |
| 1.1 | 2026-08-11 | Merged team-lead / code-reviewer / test-engineer: IP disambiguation, GUI queue screen, AC IDs, test matrix, layering rule |
| 1.2 | 2026-08-11 | §5.8 fault isolation: APP vs LINK vs KKT vs FN_OFD diagnostics for tech support |

**Owners:** Implementation — `senior-python-developer`; Review — `code-reviewer`; Tests — `test-engineer`; Coordination — `team-lead`.
