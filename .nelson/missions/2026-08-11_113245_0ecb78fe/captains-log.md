# Captain's Log — Phase B Operability

## Mission summary
- **planned outcome:** Implement Phase B operability (F-Q-04–07, F-CONN-04–05, F-OPS-01–02, F-DIAG-01–05/+07) without Phase C Admin GUI.
- **achieved outcome:** Delivered. Must-fixes from red-cell review applied. pytest green.
- **success metric result:** `27 passed, 0 failed, 0 skipped` (`python3 -m pytest tests/ -v`); code-reviewer must-fix resolved.

## Delivered artifacts
- Mission dir: `.nelson/missions/2026-08-11_113245_0ecb78fe/`
- Code: `main.py`, `cashierService.py`, `conf.py`, `fault_isolation.py` (new)
- Docs: `docs/ops-runbook.md` (scheduler start + USB autosuspend + diagnostics)
- Tests: `tests/test_phase_b.py` (+ Phase A suite retained)

## Key decisions
- **Skip Estimate:** FSD §9 already concrete; same rationale as Phase A `2026-08-11_105418_af6f98f6`.
- **Execute without interactive permission:** Admiral ordered execute.
- **Soft-retain + name poll:** After review, name waits bind to newest pending/printing (or id floor); historical done QR cannot satisfy a new wait.
- **Health/diagnostics reconnect policy:** Fiscal paths keep full F-CONN-04 backoff; `/health` and diagnostics shift/FN use `reconnect=False`; diagnostics open uses `max_attempts=1`.
- **New module `fault_isolation.py`:** Layer mapping + last-failure store kept out of Flask routes / CashierService bulk.

## Schema changes (additive ALTER via `_ensure_schema`)
```sql
ALTER TABLE "check" ADD COLUMN layer VARCHAR(20);
ALTER TABLE "check" ADD COLUMN step VARCHAR(50);
ALTER TABLE "check" ADD COLUMN error_description VARCHAR(500);
```
Plus Phase A columns if missing: `status`, `error_message`, `error_code`.
**No renames** of typo fields (`isProcessed`, etc.).

## New / updated endpoints
- `GET /health` — DB + device open + shift best-effort; HTTP 200/503 = JSON `code`; Where / What next
- `GET|POST /admin/diagnostics` — read-only ladder steps 1–5; stop at first fail
- `GET /get-checks?layer=` — includes layer/step/error_description
- `POST /create-check` — id poll; soft-retain; 504 + id + status on QR timeout

## Validation evidence
- HMS Vigilant: REQUEST_CHANGES → 3 must-fixes → Resolute fixed → Assay extended suite
- Independent admiral re-run: `27 passed in 0.45s`

## Open risks / Phase C handoff
| Risk | Owner | Next |
|------|-------|------|
| TCP mode + config GUI (F-CONN-01–03, F-CFG-*) | Phase C | Admin screens B |
| Admin GUI screens A–D (status/logs/settings) | Phase C | Wire diagnostics JSON into UI |
| F-DIAG-06/08 (support report / TCP ping) | Phase C or later | Optional |
| Unauthenticated `/admin/diagnostics` & routes | Ops / Phase C | LAN trust; consider PIN |
| Multi-worker Gunicorn unsafe for job1 | Ops | Documented: `-w 1` in runbook |
| Boot one-shot open may leave device closed until first fiscal reconnect | Acceptable | First print runs full backoff |
| Name-only poll after already-done (no active pending) → 504 by design | Clients | Prefer id (create-check already does) |
| Auth still absent | Product | Flag if exposed beyond LAN |
| Uncommitted Phase A+B work on `feature/kassa-2.0` | Admiral | Commit when ready — **do not commit from this mission** |

## Follow-ups
- Phase C Admin GUI consuming `/health` + `/admin/diagnostics`
- Optional: systemd unit (F-OPS-05 SHOULD)
- Optional: async create-check 202 mode (F-API-05)

## Mentioned in Despatches
- **HMS Resolute** — full Phase B implementation + rapid must-fix turnaround
- **HMS Vigilant** — caught soft-retain stale QR and health/diagnostics reconnect under lock
- **HMS Assay** — hardened suite to 27 green without production churn

## Reusable patterns
- **Adopt:** Separate reconnect policy flags (`reconnect=`, `max_attempts=`) for health vs fiscal paths
- **Adopt:** Additive schema ALTERs with explicit captain's-log callout
- **Avoid:** Name-based QR success after soft-retain without binding to the in-flight check id
