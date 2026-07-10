---
name: codex-advisor
description: Use when a Codex task needs architecture judgment, implementation planning, broad repository investigation, bounded execution, a consequential second opinion, pre-merge review, recovery after repeated failures, or token-efficient Sol, Luna, and Terra routing.
---

# Codex Advisor

Route by cost: Luna gathers evidence, Sol decides/plans, Terra executes. Use the shortest safe lane.

**Rule:** names do not pin models. Select a configured role or use the runner.

## Roles

| Role | Pin | Purpose | Writes |
|---|---|---|---|
| `sol_advisor` | Sol `xhigh` | Forks, audits, unblocking | No |
| `sol_planner` | Sol `xhigh` | Plan contracts | No |
| `luna_worker` | Luna `medium` | Cheap long-context `rg` evidence | No |
| `terra_executor` | Terra `xhigh` | Bounded implementation/tests | Yes |

Root owns scope, accepted evidence, integration, and completion claims.

## Lanes

| Lane | Trigger | Sequence |
|---|---|---|
| Root | No specialist evidence/judgment/execution | Root only |
| Fast | Clear, bounded, low-risk | Root contract -> Terra |
| Standard | Unfamiliar/cross-cutting | Missing evidence: Luna; missing contract: planner; requested execution: Terra |
| High-risk | Architecture/security/data risk or two failed fixes | Luna if needed -> advisor -> planner if needed -> Terra if requested -> Luna sweep -> optional Sol audit |

Unknown entry points or invariants stay Standard; Luna discovers them. Escalate only for a consequential architecture choice, security boundary, irreversible data-integrity risk, or repeated failure. Database access alone is not High-risk.

Omit satisfied or unauthorized stages. Accepted current evidence forbids redundant Luna; an existing contract skips Sol; evidence/advice/plan-only scope stops before Terra. Start one Luna; add one only for a disjoint search. Keep Terra sequential unless writes are isolated.

After partial Terra execution, use High-risk recovery: root inspects the actual diff, Luna refreshes changed evidence, then Terra receives one recovery slice. Add Sol only when the prior decision or plan is invalid.

## Invocation

Prefer native roles. Otherwise:

```bash
~/.codex/skills/codex-advisor/scripts/run-role.sh \
  terra-executor "$PWD" brief.md report.md
```

Roles: `sol-advisor`, `sol-planner`, `luna-worker`, `terra-executor`.

The runner isolates unrelated skills, embeds only the selected output schema, pins model/effort/sandbox, caps bytes, validates structure/semantics, checks Terra's Git-visible owned paths, and atomically promotes valid output. Read `references/runtime-operations.md` before fallback, parallelism, retry, or recovery.

## Workflow

1. **Luna:** Ask one narrow question over broad read-only roots. Require fingerprinted `path:line` evidence. Max three shell calls, 80 lines/8 KB each, no rereads, eight findings. Use symlink-aware tools when needed.
2. **Sol:** Send accepted evidence, constraints, and rejected paths. Target 500-1,000 tokens; hard cap 1,500. Use advisor only for a real fork/audit; otherwise planner once. Missing evidence returns one Luna query.
3. **Terra:** Send one slice with owned paths, test signal, criteria, and stop conditions. Stop on contradictions.
4. **Root:** Verify actual diff/commands. Reports never override runtime truth.

Read `references/briefing-protocol.md` for briefs and `references/response-contracts.md` when judging outputs.

## Resources

- `references/runtime-operations.md`: isolation, atomic output, retry/recovery.
- `scripts/run-role.sh`: pinned fallback.
- `scripts/worktree-state.py`: Terra pre/post scope verifier.
- `assets/agent-configs/*.toml`: native roles.
