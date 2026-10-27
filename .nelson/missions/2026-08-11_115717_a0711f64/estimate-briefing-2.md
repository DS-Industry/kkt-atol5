# Estimate Briefing 2 — Q4–Q7

Mission dir: `/Users/eshom/Developer/kkt-atol5/.nelson/missions/2026-08-11_115717_a0711f64/`

## Task
Read `{mission-dir}/estimate.md` (Q1–Q3 approved by admiral via collapsed checkpoint). Append H2 sections:
- ## 4. Terrain
- ## 5. Forces
- ## 6. Coordination
- ## 7. Control

Per `.cursor/skills/nelson/references/the-estimate.md`. Voice: concise officer register.

## Execution constraints (user preferences)
- Team Lead / admiral does NOT implement
- Mandatory sequential specialists: senior-python-developer → code-reviewer → test-engineer (repo agent types via Task tool)
- Single implementation captain owns all code files to avoid split-keel conflicts (conf.py, cashierService.py, main.py, templates/, optional new config module, tests may be test-engineer)
- Mode: subagents (sequential dependency chain — not parallel captains on same files)
- Action stations: TCP connect + settings = Station 2+ (medium); GUI list/logs = Station 1–2
- Do not commit/push

## Forces mapping for this repo
Available Task subagent_types: `senior-python-developer`, `code-reviewer`, `test-engineer` (plus explore/generalPurpose for recon only).

Map effects to: one implementation ship (Resolute-class), then Vigilant (reviewer), then Assay (tests). Or fold tests into developer then test-engineer extends — admiral prefers: developer implements + maybe smoke tests, test-engineer owns Phase C suite, reviewer in between.

Write append to estimate.md only. Return confirmation of Q4–Q7 written.
