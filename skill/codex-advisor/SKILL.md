---
name: codex-advisor
description: Use when a Codex task would benefit from specialist architecture judgment, broad repository investigation, implementation planning, bounded execution, a consequential second opinion, pre-merge review, or recovery after repeated failures.
---

# Codex Advisor

Use specialists only when they reduce uncertainty or execution cost. Root remains the primary agent and may inspect, plan, implement, verify, and finish directly.

## Roles

| Role | Default | Best for | Writes |
|---|---|---|---|
| `luna_worker` | Luna `medium` | Cheap broad search and cited evidence | No |
| `sol_advisor` | Sol `xhigh` | Consequential forks, audits, unblocking | No |
| `sol_planner` | Sol `xhigh` | Plans when a real contract is missing | No |
| `terra_executor` | Terra `xhigh` | A bounded implementation or test slice | Yes |

Names do not pin models. Use configured roles or the fallback runner.

## Choose the shortest useful path

- **Root only:** Evidence is already available, the task is simple, or root can safely complete it.
- **Luna:** Entry points, invariants, or current repository facts are genuinely missing.
- **Sol advisor:** A consequential decision has competing options. Skip it when there is no real fork.
- **Sol planner:** Execution needs a contract that root does not already have.
- **Terra:** The user requested implementation and delegation will help.

There is no required sequence. Do not invoke a role to prove the skill was used. Existing evidence skips Luna; an existing decision or plan skips Sol; root may integrate and verify without Terra.

After partial work, root inspects the actual diff and focused checks first. Refresh with Luna only when changed state makes evidence uncertain. Return to Terra only when a correction remains. Add Sol only when the underlying decision is now questionable.

## Briefs and reports

Brief in plain language. Give each role one outcome, relevant evidence, constraints, and stop conditions. Terra also needs explicit owned paths so write scope can be enforced.

Treat response contracts as useful templates, not ceremony. Extra bullets, headings, wording drift, or omitted optional fields should produce a warning—not another model call. Accept semantically useful output and let root note any caveat.

Rerun only when the result is unusable or unsafe: process failure, wrong/stale fingerprint, repository mutation during read-only work, missing core verdict/decision, or writes outside Terra's owned paths.

Prefer `rg`, compact artifacts, and one specialist at a time. Luna should usually answer one question with a small cited evidence set. Terra should usually receive one outcome, not a full transcript.

## Fallback

```bash
~/.codex/skills/codex-advisor/scripts/run-role.sh \
  terra-executor "$PWD" brief.md report.md
```

Read `references/runtime-operations.md` for runner and recovery behavior. Use `references/briefing-protocol.md` and `references/response-contracts.md` only when a reusable artifact helps.

Root verifies the real diff, commands, runtime state, and completion claim. Reports are evidence, not authority.
