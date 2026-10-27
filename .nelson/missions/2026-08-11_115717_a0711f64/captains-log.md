# Captain's Log — Phase C Config + GUI + TCP

## Mission summary
- **planned outcome:** Ship Phase C so site staff can select USB|TCP, set KKT driver IP/port, persist settings, and operate Admin screens A–D without SSH (AC-5, AC-6).
- **achieved outcome:** Delivered. Persistent `instance/config.json`; CashierService USB|TCP via `applySingleSettings`→`open`; Admin A–D; Vigilant APPROVE; pytest green.
- **success metric result:** AC-5+AC-6 met; `44 passed, 0 failed` (`python3 -m pytest tests/`); code-reviewer **APPROVE**; no commit/push.

## Delivered artifacts
- Mission dir: `.nelson/missions/2026-08-11_115717_a0711f64/`
- Code: `conf.py`, `cashierService.py`, `main.py`, `templates/admin/*`
- Docs: `docs/ops-runbook.md` (admin table + unauth LAN note)
- Tests: `tests/test_phase_c.py` (17) + FakeIFptr settings recording; Phase A+B retained

## Key decisions
- **Estimate conducted** (authorized); checkpoints collapsed — sailing orders clear, Q1 no surprises.
- **Execute without interactive permission:** Admiral ordered full session execute.
- **HTTP listen default `0.0.0.0:5000`** (FSD Screen B); AGENTS.md still mentions 5050 — residual doc drift.
- **Screen D list-only** — no retry (no anti-double-print API).
- **F-DIAG-06/08 skipped** (optional, not blocking).
- **Should-fix from Vigilant not blocking** — left as follow-ups (double diagnostics form POST; HTML reconnect HTTP 200; TCP fields always enabled in UI; runbook port examples).

## Config schema (`instance/config.json`)
Missing file → defaults. Atomic write. No secrets.
Fields: `connection_mode` (usb|tcp), `kkt_ip`, `kkt_tcp_port` (5555), `library_path`, `http_host`/`http_port`, timeouts, `log_path`, `max_log_lines`, plus retained reconnect/retention/log-rotation knobs.

## New / updated endpoints & pages
- `GET /admin`, `/admin/status` — Status (reconnect / diagnostics / refresh)
- `POST /admin/reconnect`
- `GET|POST /admin/settings` — Save / Save & reconnect / Reset
- `GET /admin/logs`
- `GET /admin/checks` — list only
- `GET /health` — additive `queue` + `connection`
- Existing `GET|POST /admin/diagnostics` retained

## Validation evidence
- HMS Resolute: implementation + smoke; 27→ then Assay 44
- HMS Vigilant: **APPROVE** (0 must-fix)
- HMS Assay: 17 Phase C tests
- Admiral re-run: `44 passed` (pytest `-q`)

## Open risks / Phase D leftovers
| Risk | Owner | Next |
|------|-------|------|
| Unauthenticated `/admin*` | Ops / product | PIN/auth if beyond LAN |
| AGENTS.md port 5050 vs config default 5000 | Docs | Align docs |
| Vigilant should-fix (diag double-run, HTML status, TCP field enable) | Next polish | Optional |
| F-DIAG-06 support report / F-DIAG-08 TCP ping | Phase C residual / later | Optional |
| Screen D retry + anti-double-print | Later | Not until safe |
| Phase D packaging (systemd, CI packaging) | Phase D | |
| Uncommitted A+B+C on `feature/kassa-2.0` | Admiral | Commit when ready — **not this mission** |
| Hardware smoke USB/TCP open | Field | When Orange Pi available |

## Follow-ups
- Optional Vigilant should-fix polish
- Phase D packaging & CI
- Auth/PIN if exposed beyond trusted LAN

## Mentioned in Despatches
- **HMS Resolute** — full Phase C config + TCP + Admin A–D in one pass
- **HMS Vigilant** — clear APPROVE with actionable should-fix only
- **HMS Assay** — 17 focused Phase C tests; suite to 44 green

## Reusable patterns
- **Adopt:** Atomic `instance/config.json` + merge-over-defaults; FakeIFptr settings recording for USB vs TCP asserts
- **Adopt:** Settings IP labeled Driver TCP target (A) only — never conflate OFD/KKT Ethernet
- **Avoid:** Admin retry into fiscal sequence without anti-double-print
