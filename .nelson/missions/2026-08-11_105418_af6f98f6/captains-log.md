# Captain's Log — Phase A Safety (P0)

**Mission:** `.nelson/missions/2026-08-11_105418_af6f98f6`  
**Branch:** `feature/kassa-2.0` (not committed)  
**Outcome:** Achieved — AC-1..AC-4 Phase A met with mocked tests green.

## Decisions
- Skipped The Estimate (FSD Phase A already concrete).
- Mode: subagents, sequential Resolute → Vigilant → Resolute (must-fix) → Assay.
- Schema: add `status`, `error_message`, `error_code`; keep legacy typos/`isProcessed`/`isQr`.
- OFD mass rewrite removed from boot (P5); provisioning is now operational/out-of-band.

## Pipeline
1. **HMS Resolute** — Phase A impl (fail-stop, queue, no drop_all, timeouts, slim init, RLock).
2. **HMS Vigilant** — REQUEST_CHANGES (M1 encoding, M2 backfill reprint, M3 retryable, M4 close_shift timeout).
3. **HMS Resolute** — M1–M4 fixed.
4. **HMS Assay** — 12 pytest cases, all passed.

## Validation
```
python3 -m pytest tests/ -v
# 12 passed in 0.38s
```

## Open risks / Phase B
- Stuck `printing` after crash (boot recovery).
- Fiscal success + QR fail → `failed` may encourage duplicate create-check.
- Soft-retain / no delete-on-QR (P6), id-poll redesign F-Q-04–07, reconnect, diagnostics.
- Hardware smoke still required for §4 fiscal sign-off.
- OFD settings no longer rewritten on every start — ensure device already provisioned.

## Mentioned in Despatches
- HMS Vigilant — caught duplicate-print migration risk (M2) and retryable gap (M3).
- HMS Assay — clean mocked suite without production edits.
