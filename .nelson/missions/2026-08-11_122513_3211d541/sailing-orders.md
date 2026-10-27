```text
Sailing orders:
- Outcome: Deliver Phase D packaging — requirements, root .gitignore, systemd unit, hardware smoke checklist, pytest green, ops-runbook pointers
- Success metric: F-OPS-04 gitignore present; systemd example committed; smoke checklist written; pytest -q green (~44+); requirements complete for declared imports
- Deadline: This session

Constraints:
- Token/time budget: This session
- Reliability floor: pytest suite must not regress; packaging must not break Phase A–C behavior
- Compliance/safety constraints: AGENTS.md layering (libfptr via CashierService only); no libfptr10.py style edits
- Forbidden actions: No commit/push; no Auth/PIN; no tax/payment remapping; no Check typo renames; no /create-check client breaks

Scope:
- In scope: requirements.txt verify/complete; root .gitignore (F-OPS-04); systemd unit example (F-OPS-05); hardware smoke checklist (FSD §10.2); ops-runbook pointers; pytest stay green / CI glue docs
- Out of scope: Auth/PIN; tax/payment remapping; mass OFD rewrite; Admin GUI polish; Screen D retry; committing uncommitted A+B+C+D work

Stop criteria:
- Stop when: Metric met, code-reviewer and test-engineer have reported, stand-down logged

Required handoff artifacts:
- Must produce: Files list, pytest result, reviewer verdict, risks, mission dir path
```
