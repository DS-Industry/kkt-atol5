# Hardware smoke checklist (Orange Pi + ATOL KKT)

Operator checklist for FSD §10.2 **Hardware** row. Run on a real Orange Pi with the
printer attached. Mocked pytest does **not** replace this.

Related: [`docs/issues/issues.md`](issues/issues.md) (USB autosuspend, PSU sag, FN/OFD),
[`docs/ops-runbook.md`](ops-runbook.md) (health, diagnostics, systemd).

**Do not invent Auth/PIN** — `/admin*` is LAN-trust only for this MVP.

Mark each box after a successful pass. Record Orange Pi hostname, KKT serial/model, and
date at the bottom.

---

## Preconditions

- [ ] ATOL driver / `libfptr10` present (`LIBRARY_PATH`, typically `/usr/lib/`)
- [ ] Service running (`python3 main.py` or systemd unit `deploy/kkt-atol5.service`)
- [ ] If USB flaky historically: `usbcore.autosuspend=-1` in `/boot/orangepiEnv.txt` and reboot ([issues.md](issues/issues.md))
- [ ] Stable PSU (field notes: voltage sag → multi-minute ops / timeouts)

Default HTTP: `http://<orangepi>:5050` (from `instance/config.json` / conf defaults).

---

## 1. USB and/or TCP open

Connection mode is set in Admin → Settings (`usb` | `tcp`) or `instance/config.json`.

**USB**

- [ ] Cable seated; KKT powered
- [ ] `GET /health` → HTTP **200**, device reported open (or reconnect then recheck)
- [ ] `GET` or `POST /admin/diagnostics` reaches past library/open (not stuck on LINK)

**TCP** (Driver TCP target = Orange Pi → KKT; not OFD host)

- [ ] Settings: mode `tcp`, correct KKT IP + port (default driver port often `5555`)
- [ ] Restart service after settings change if required
- [ ] `/health` and `/admin/diagnostics` show open connection

```bash
curl -s http://127.0.0.1:5050/health | python3 -m json.tool
curl -s http://127.0.0.1:5050/admin/diagnostics | python3 -m json.tool
```

---

## 2. One sell + QR

Shift must be **OPEN** (not EXPIRED). Close-shift report first if expired (ops / device UI).

- [ ] Create one real sell check via the normal client path (`POST /create-check` or site POS flow)
- [ ] Queue processes the check (`pending` → `printing` → `done`)
- [ ] Paper receipt prints; fiscal QR present on receipt / success payload as expected for this site
- [ ] Check row retained in DB / Admin → Checks (soft retain; not deleted on QR success)

If stuck: check `layer` on failed rows (`GET /get-checks?layer=…`) and diagnostics — see runbook §3.

---

## 3. Restart keeps DB

- [ ] Note a known check id / count before restart
- [ ] Restart service: `sudo systemctl restart kkt-atol5` (or stop/start `python3 main.py`)
- [ ] After start: same SQLite data present (`instance/` DB); prior checks still listed
- [ ] Scheduler/`job1` running again (logs mention APScheduler / pending work drains)

---

## 4. Mid-fail recover (if safe)

Only if site policy allows a deliberate interrupt on non-production or spare paper.

- [ ] Start a print, then interrupt in a **safe** way (e.g. brief USB unplug mid-job, or kill process **after** understanding dangling-receipt risk — prefer cancel/close paths over leaving an open receipt)
- [ ] Restore link / restart service
- [ ] Diagnostics and `/health` recover to a known state
- [ ] No permanent stuck `printing` without operator visibility; failed rows show a useful `layer`
- [ ] Next sell+QR still succeeds after recovery

If unsure about an open fiscal receipt on the device, stop and use ATOL/device tools — do not force a second open receipt.

---

## 5. Diagnostics with cable unplugged → LINK

- [ ] With service up, unplug USB (or break TCP) so the KKT is unreachable
- [ ] `GET`/`POST /admin/diagnostics` fails at connection/open and reports fault layer **LINK** (or equivalent link-layer signal)
- [ ] `/health` unhealthy (**503**) while link is down
- [ ] Replug cable; reconnect / wait for backoff; diagnostics pass open again

USB error **4** (port unavailable) and autosuspend: [issues.md](issues/issues.md), runbook §2.

---

## Sign-off

| Field | Value |
|-------|--------|
| Date | |
| Orange Pi host | |
| KKT model / FN | |
| Connection mode (USB / TCP) | |
| Operator | |
| Result (PASS / FAIL + notes) | |
