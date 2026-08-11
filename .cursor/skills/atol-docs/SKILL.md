---
name: atol-docs
description: >-
  Canonical ATOL Fiscal Printer Driver v.10 documentation (integration.atol.ru) —
  the authoritative reference for every libfptr10 method, parameter, error
  code, and device model this project depends on. Use before implementing or
  reviewing anything that touches CashierService/libfptr10, or when
  researching device/protocol behavior, instead of guessing from source
  comments or general knowledge.
paths: ["cashierService.py", "libfptr10.py", "main.py", "conf.py"]
---

# ATOL integration docs

Official docs, not project-authored — treat as source of truth over any
assumption in this repo's own code comments. Covered by ATOL's own terms
(`https://integration.atol.ru/eula/`,
`https://integration.atol.ru/rules/`) — **link to it, fetch the specific
section you need, don't bulk-copy pages into this repo.**

- **English Native API reference (primary — matches `libfptr10.py`'s
  English `LIBFPTR_*` constant names):**
  `https://integration.atol.ru/api-en/#<anchor>`
- Russian equivalent: `https://integration.atol.ru/api/#<anchor>`
- REST API (WebRequests) reference, if a task ever needs HTTP instead of the
  native driver: `https://integration.atol.ru/web_requests-en/`

It's a single long page per language with a left-nav table of contents and a
language-tab switcher (C++/**Python**/Java/Android/Obj-C/C#/COM/Go) — the
Python tab's code samples are the closest match to this codebase's usage.
Fetch `https://integration.atol.ru/api-en/#<anchor>` for the section you
need; a plain fetch returns all language tabs' code in the page, so just
read the Python block.

## Anchor index (English reference)

Research the specific anchor for your task — don't fetch the whole page
when one section answers the question.

**Setup**
- `#getting-started-to-work-with-the-driver`, `#connection-to-project`,
  `#driver-initialization`, `#driver-configuration`,
  `#driver-methods-and-parameters` — how `IFptr(LIBRARY_PATH)` /
  `setSingleSetting` / `applySingleSettings` are meant to be used
- `#error-handling` — the pattern for checking `errorCode()` /
  `errorDescription()` after a call
- `#appendix` → `#error_list` — **full numeric error-code table** for every
  `LIBFPTR_ERROR_*` value; consult this whenever `errorCode()` returns
  nonzero instead of guessing what it means
- `#kkt_params_list` — per-model parameter tables (relevant since `conf.py`
  sets `LIBFPTR_MODEL_ATOL_AUTO`)

**Connection & status**
- `#connection-to-fiscal-printer`
- `#request-for-fiscal-printer-info` → `#shift-state`, `#receipt-state`,
  `#fiscal-printer-model-info`

**Shifts**
- `#shift-operation` → `#open-shift`, `#close-shift`

**Receipts** (the sequence `cashierService.print_check` implements)
- `#receipt-operations` → `#general-algorithm-for-receipt-formation`,
  `#open-receipt`, `#cancel-receipt`, `#register-position`,
  `#register-payment`, `#register-receipt-tax`, `#register-result`,
  `#check-document-closure`, `#finish-document-printing`

**Cash movements & reports**
- `#cash-incomes-and-outcomes`
- `#report-printing` → `#x-report`, `#shift-total-counters`,
  `#fn-total-counters`

**FN (fiscal drive) / OFD**
- `#request-for-information-from-fn-fiscal-memory-device` →
  `#fn-info`, `#ofd-exchange-errors`, `#ofd-ticket`,
  `#date-and-time-of-last-successful-exchange-with-ofd-fiscal-data-operator`
  — check these first for anything resembling the "no data reaching OFD" /
  "FN resource exhausted" issues logged in `docs/issues/issues.md`

**Registration / re-registration / FN lifecycle**
- `#fn_registration`, `#fn_change_params`, `#fn-replacement`,
  `#fn-archive-closing`

## How to use this while working

1. Before implementing or reviewing a `CashierService` change, identify
   which lifecycle stage it touches (shift, receipt, FN/OFD, reporting) and
   fetch the matching anchor above.
2. When a `fptr` call's error code shows up (in code, logs, or
   `docs/issues/issues.md`), look it up in `#error_list` before speculating.
3. Prefer the documented method/parameter names verbatim over inferring
   them from `libfptr10.py`'s Python signatures alone — the doc states
   required call order and preconditions that the wrapper code doesn't
   comment on.
