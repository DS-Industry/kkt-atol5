# AGENT.md

> **What this is:** a Flask microservice that talks to an **ATOL fiscal
> registrar** (a Russian cash-register/fiscal printer) over USB via the
> vendor `libfptr10` SDK. It runs on an **Orange Pi** at the point of sale,
> receives check/receipt data over HTTP, and drives the physical printer to
> open shifts, register items, take payment, and print/close fiscal receipts
> per Russian 54-FZ requirements.
>
> **Project stage:** early / pre-alpha. There is no dependency manifest, no
> test suite, and no linter configured yet — do not assume tooling exists
> just because a mature project would have it. Verify before relying on it.
>
> **Local git is behind origin.** `main` locally may be several commits
> behind `origin/main`. Check `git status` / `git log origin/main` before
> starting work and flag it to the user rather than silently working from a
> stale checkout.
>
> **Known field issues:** `docs/issues/issues.md` is a running log of real
> hardware/deployment problems seen with this printer + Orange Pi combo
> (USB autosuspend dropping the device, FN/OFD errors, shift operations
> taking minutes and overflowing the DB). Read it before debugging anything
> that looks like a device-communication or timing issue — it's probably
> already diagnosed there.
>
> **Official ATOL docs:** [integration.atol.ru](https://integration.atol.ru/api-en)
> is the authoritative reference for `libfptr10` — methods, call order,
> parameters, and the full error-code table. It outranks this file and the
> code comments whenever they disagree. See the `atol-docs` skill
> (`.cursor/skills/atol-docs/`) for a curated anchor index instead of
> browsing the whole page.
>
> **Briefing an agent:** use [TASK_TEMPLATE.md](TASK_TEMPLATE.md) — pick the
> right agent for the job and fill in outcome/scope/constraints before
> handing off. Agents have no memory of prior sessions; a vague brief
> produces vague work.

## 1. Stack

- **Language**: Python 3.11 (no virtualenv/pyproject.toml committed — confirm
  the active interpreter before assuming a package is available)
- **Web framework**: Flask, with `flask_sqlalchemy` for the DB layer
- **DB**: SQLite (`instance/check.db`), no migration tooling (no
  Flask-Migrate/Alembic) — schema changes are currently applied by hand
- **Hardware SDK**: `libfptr10.py` — vendor-provided wrapper around ATOL's
  native fiscal-registrar library (`conf.py: LIBRARY_PATH`, expected at
  `/usr/lib/`). Treat this file as third-party/vendor code: don't "clean up"
  its style, only consume its documented API.
- **Deployment target**: Orange Pi SBC, printer attached over USB
  (`LIBFPTR_PORT_USB`). Behavior on a dev laptop without the device attached
  will differ from production — see §9.
- **No dependency manifest exists.** If you add a new import that isn't in
  the standard library, also add/update a `requirements.txt` — don't leave
  dependency drift for the next person to discover by trial and error.

## 2. Commands

```bash
python3 main.py            # runs the Flask dev server on 0.0.0.0:5050, debug=True
```

There is currently no configured way to: install dependencies from a
manifest, run tests, lint, or type-check. If your task is to add any of
these, that's real, valuable work — don't skip it just because nothing
mandates it yet, but also don't silently invent a stack (e.g. poetry vs pip,
pytest vs unittest) without checking `docs/` or asking.

## 3. Project layout

```
main.py            # Flask app, SQLAlchemy Check model, HTTP routes
cashierService.py   # CashierService — all libfptr10/device calls live here
conf.py             # LIBRARY_PATH and other device config
libfptr10.py        # vendor SDK wrapper — do not hand-edit, only consume
instance/check.db   # SQLite DB (gitignored data, not schema — see §3.1)
docs/issues/issues.md  # field-issue log (hardware, OFD, USB) — read before
                        # debugging device/timing problems
```

**3.1 Layering rule:** HTTP/Flask concerns stay in `main.py`. Every call
into `libfptr10`/the physical device goes through `cashierService.py`'s
`CashierService`. Do not call `IFptr` methods directly from a Flask route —
add a method to `CashierService` instead, matching its existing
`{"code": ..., "message"/"status": ...}` return contract.

## 4. Fiscal-printer protocol rules (non-negotiable)

This is the part of the codebase where a bug has real financial/legal
consequences (an incorrectly closed fiscal receipt is not something you can
just retry), so these rules are stricter than normal code-review taste:

- A shift must be `OPEN` (not `EXPIRED`) before any receipt operations.
  `EXPIRED` shifts must be closed via a close-shift report before a new
  receipt opens — see `CashierService.get_shift_status`.
- Receipt sequence is fixed and must never be reordered or partially
  skipped: `openReceipt()` → per-item `setParam(...)` + `registration()` →
  `setParam(PAYMENT_*)` + `payment()` → `receiptTax()` → `receiptTotal()` →
  `closeReceipt()`. If anything fails after `openReceipt()` succeeds, the
  code must close or cancel that receipt — never leave one dangling open on
  the device.
- `fptr` calls can fail without raising a Python exception. After calls that
  matter (`open()`, `registration()`, `payment()`, `closeReceipt()`), check
  `fptr.errorCode()` / `fptr.errorDescription()` — don't assume success just
  because nothing raised. Look up nonzero codes in the official `#error_list`
  reference (`atol-docs` skill) rather than guessing what one means.
- `cashier_service = CashierService()` is a module-level singleton
  instantiated at import time. `_initialize_device()` runs then, but
  `open_connection()` does not — never assume the device connection is live
  just because the module imported successfully.
- Payment-type and tax-type mapping (`LIBFPTR_PT_CASH` /
  `LIBFPTR_PT_ELECTRONICALLY`, `LIBFPTR_TAX_NO`) must reflect the actual
  business rules (payment method, VAT regime) — confirm with the user before
  changing or copying these, don't treat the current hardcoded values as
  self-evidently correct.

## 5. HTTP/API conventions

- Every route validates required JSON fields before use and returns `400`
  on missing/malformed input — don't let a `KeyError`/`TypeError` surface as
  a bare `500`.
- The Flask response's HTTP status must match the `code` field the service
  layer returns (`{"code": 500, ...}` must produce an actual HTTP 500, not
  the Flask default `200`).
- No route ships with an empty/incomplete body. Finish it or don't merge it.
- Don't propagate raw `str(e)` exception text to API responses if this
  service is ever reachable beyond localhost — it currently leaks internals.
- There is currently no authentication on any route, even though routes can
  trigger real payments/fiscal receipts. Don't treat this as fine just
  because it's the status quo — flag it explicitly if you're asked to expose
  this service beyond a trusted local network.

## 6. Data layer

- `Check` (in `main.py`) is the only model. Field names currently include
  typos (`quiantity`, `isProcessed`, `dateProccesed`) that are already baked
  into the DB/API contract — don't silently "fix" them in a way that breaks
  existing data/callers; if you rename them, do it as a deliberate,
  called-out migration.
- No migration tooling exists. Any schema change is a manual, riskier
  operation — call it out explicitly rather than doing it quietly.

## 7. Testing

No test suite exists yet. When asked to add tests:
- Use `pytest` (skill: `pytest`) for structure, fixtures, and mocking.
- The device dependency (`IFptr`) requires physical USB hardware and can't
  run in CI — stub it at the `CashierService` boundary with
  `unittest.mock`/fixtures rather than skipping coverage for that code.
  Cover both success and error paths (device not opened, unexpected shift
  state, a native call raising).

## 8. Git / PR hygiene

- Small, focused commits.
- Don't mix formatting-only changes with logic changes.
- Check `git log origin/main` vs local `main` before starting — see the
  banner at the top of this file.

## 9. Anti-patterns to avoid

- ❌ Calling `IFptr`/`libfptr10` methods directly from a Flask route instead
  of through `CashierService`
- ❌ Reordering or skipping steps in the open→register→pay→tax→total→close
  receipt sequence, or leaving a receipt open on error
- ❌ Assuming the device connection is live just because
  `cashier_service` imported without error
- ❌ Trusting a `fptr` call succeeded just because no exception was raised —
  check `errorCode()`
- ❌ Returning HTTP `200` while the JSON body says `{"code": 500}`
- ❌ Adding a new dependency without updating a dependency manifest
- ❌ Editing `libfptr10.py`'s vendor code style/formatting
- ❌ "Fixing" `Check` model field typos without treating it as a real,
  called-out migration
- ❌ Debugging a flaky device/timing issue from scratch without first
  checking `docs/issues/issues.md`

## 10. Definition of done

- [ ] Fiscal-printer call sequence (§4) is unbroken — no dangling open
      receipts, error codes checked after native calls
- [ ] New/changed routes validate input and return correct HTTP status
      codes (§5)
- [ ] Any new dependency is reflected in a dependency manifest
- [ ] Schema changes are called out explicitly (no migration tooling — §6)
- [ ] New device-facing logic has test coverage via a mocked `IFptr` (§7),
      not skipped just because hardware isn't available locally
- [ ] Manually exercised against the real device when the change touches
      §4, if hardware is available — mocked tests alone aren't sufficient
      sign-off for fiscal-sequence changes

## 11. Agent team & module ownership

| Area                          | Files / artifacts                          | Owner agent               |
|--------------------------------|---------------------------------------------|----------------------------|
| Planning & coordination       | multi-step or multi-file work                | `team-lead` (uses `nelson` skill) |
| Implementation                | `main.py`, `cashierService.py`, `conf.py`    | `senior-python-developer` (uses `flaskapi`, `python-patterns`) |
| Pre-merge review              | any changed `.py` file                       | `code-reviewer` (read-only; uses `flaskapi`, `python-patterns`) |
| Tests                          | new/changed test files                       | `test-engineer` (uses `pytest`) |
| Vendor SDK                    | `libfptr10.py`                               | consume only — no owner edits it |

Agent definitions live in `.cursor/agents/`. `.cursor/rules/`,
`.cursor/hooks/`, and a dependency manifest are all currently empty/missing —
if a task calls for one, that's real setup work, not a pre-existing
convention to discover.

## 12. Agent workflow (tiered)

| Tier | Trigger | Loop |
|------|---------|------|
| **S** | Single-file fix, one route/method | `senior-python-developer` (± `code-reviewer`) |
| **M** | Change spans routes + service + model, or touches the fiscal sequence (§4) | `team-lead` runs a `nelson` mission → `senior-python-developer` → `code-reviewer` → `test-engineer` |
| **L** | New subsystem (auth, migrations, CI) | `team-lead` via full `nelson` workflow (Sailing Orders → Estimate → Battle Plan → Squadron) |

Reserve full Nelson ceremony for work that genuinely spans multiple
files/steps — for a one-line fix, go straight to
`senior-python-developer`.

## 13. Notes for agents

- You start with no memory of prior sessions — this file plus your task
  prompt is your whole context. If something here was ambiguous or wrong,
  propose a correction to this file rather than guessing silently next time.
- When in doubt about intent (tax regime, auth requirements, field
  renames), ask — this service handles real payments and legally regulated
  fiscal receipts, where a wrong guess isn't just a bug, it's a compliance
  problem.
