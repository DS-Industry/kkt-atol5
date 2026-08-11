# Ops runbook — Orange Pi + ATOL KKT (Phase B ops + D packaging)

Short production notes for site ops and tech support. Related: `docs/issues/issues.md`,
`docs/FSD-production-stable.md` §5.7–5.8.

**Quick pointers (Phase D packaging):**

| Topic | Where |
|-------|--------|
| Install deps + run mocked tests | `pip install -r requirements.txt` then `pytest -q` (no hardware / no native `libfptr10` required for the suite) |
| Dev Mac (no ATOL driver) | `MOCK_IFPTR=1 python3 main.py` — uses `tests/fake_fptr` so Admin GUI/API start without `libfptr10`; **not** for fiscal/print validation |
| systemd unit example | [`deploy/kkt-atol5.service`](../deploy/kkt-atol5.service) — copy to `/etc/systemd/system/`, set `WorkingDirectory`/`User`, `Restart=on-failure` |
| Hardware smoke (Orange Pi) | [`docs/hardware-smoke-checklist.md`](hardware-smoke-checklist.md) — FSD §10.2 Hardware row |

---

## 1. How APScheduler / `job1` starts (F-Q-07)

The background print worker is Flask-APScheduler task `job1` (interval ~3s). It must run
in the **same process** that serves HTTP.

**Autostart:** `main.py` calls `start_scheduler()` on module import when safe (not under
pytest, not when `DISABLE_SCHEDULER=1`). That covers:

| How you run | Scheduler |
|-------------|-----------|
| `python3 main.py` | Starts on import / `__main__` |
| systemd / unit running `python3 main.py` | Starts on import |
| `gunicorn -w 1 ... "main:app"` (or similar WSGI import of `main:app`) | Starts when the worker imports `main` |

**Disable for tests/debug:** `DISABLE_SCHEDULER=1`.

**Important:** Use **one worker process** for fiscal printing (`-w 1`). Multiple Gunicorn
workers would each run `job1` and race the USB device. Single-flight printing is also
enforced by `CashierService`’s lock (F-Q-08).

**Verify:** After start, logs should include `APScheduler started (job1 interval print worker)`.
Pending checks in SQLite move `pending` → `printing` → `done`|`failed` without a separate
cron.

---

## 2. USB autosuspend fix (F-CONN-05)

Field symptom: ATOL error **4** (port unavailable) — Orange Pi intermittently does not see
the KKT over USB (`docs/issues/issues.md`).

**Fix on Orange Pi:**

```bash
sudo nano /boot/orangepiEnv.txt
```

Append (if missing):

```
usbcore.autosuspend=-1
```

Reboot the Orange Pi. Confirm the KKT is powered and the USB cable is seated, then hit
`GET /health` or `POST /admin/diagnostics`.

The app also **reconnects with exponential backoff** on `isOpened==0` / error-4 class
(F-CONN-04). Autosuspend still needs the kernel line above; software reconnect alone is
not a substitute.

---

## 3. Health & diagnostics (F-OPS-02, F-DIAG-*)

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | DB + device open + shift (best-effort). **200** healthy / **503** unhealthy; JSON `code` matches HTTP. |
| `GET` or `POST /admin/diagnostics` | Read-only ladder (no sell receipt): (1) app+DB → (2) library → (3) open → (4) shift → (5) FN/OFD. Stops at first fail; returns `where` + `what_to_do_next`. |

Example:

```bash
curl -s http://127.0.0.1:5000/health | python3 -m json.tool
curl -s http://127.0.0.1:5000/admin/diagnostics | python3 -m json.tool
```

Failed queue rows include `layer` (`APP`|`LINK`|`KKT`|`FN_OFD`|…) for filtering:

```bash
curl -s 'http://127.0.0.1:5000/get-checks?layer=LINK'
```

Admin GUI (Phase C): open `http://<orangepi>:5000/admin` on the LAN.

| Screen | Path | Purpose |
|--------|------|---------|
| A Status | `/admin` / `/admin/status` | Connection, shift, fault layer, queue; Reconnect / Diagnostics |
| B Settings | `/admin/settings` | USB\|TCP, Driver TCP target (Orange→KKT), timeouts, HTTP bind |
| C Logs | `/admin/logs` | Tail of configured log path |
| D Checks | `/admin/checks` | Recent checks list only — **no retry** |

**Security:** `/admin*` is **unauthenticated** (LAN trust MVP). Do not expose beyond the
site network. Auth/PIN is not in Phase C.

Persistent config: `instance/config.json` (defaults if missing). Driver TCP target is the
only IP in Settings — never conflate with OFD host or KKT Ethernet (params 71–74).

HTTP listen default in config: `0.0.0.0:5000` (FSD). Process restart required after changing
HTTP host/port.

---

## 4. Check retention (F-Q-06)

Completed checks are **soft-retained** (not deleted on QR success). Retention default:
`check_retention_days` in `instance/config.json` / `conf.py` defaults (30). Optional cleanup
helper: `cleanup_old_checks()` in `main.py`.
