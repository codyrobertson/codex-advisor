# Briefing Protocol

Use artifacts to move evidence between model roles. Do not rely on inherited transcript context for correctness.

## Luna investigation brief

```markdown
# INVESTIGATION: <topic>

## Goal
<What decision or plan this investigation must enable.>

## Questions
1. <Concrete repository question>

## Search roots
- <path or module>

## Constraints and repo rules
- <non-negotiable instruction>

## Known evidence
- <fact already verified by the root>

## Non-goals
- <what Luna must not investigate or change>

## Return EVIDENCE_PACKET. Do not edit files.
```

Luna may read a broad code surface. It must prefer `rg`/`rg --files`, use at most three shell calls, cap each command to 80 lines or 8 KB, avoid rereads, cite `path:line` and symbols, and name contradictions and unknowns. Use symlink-aware inspection when relevant.

## Sol advisor brief

Target 500-1,000 tokens; hard cap 1,500.

```markdown
# ADVISOR BRIEF: <topic>

## Question
<One question that can receive a verdict.>

## Context
<Current state and why the decision is needed now.>

## Options
A. <option and known tradeoff>
B. <option and known tradeoff>

## Constraints
- <non-negotiable>

## Already rejected
- <path and reason>

## Accepted evidence
- E1: <claim>; <path:line>; <verification>

## Unknowns
- <material uncertainty>

## Return ADVISOR_VERDICT.
```

## Sol planner brief

```markdown
# PLANNING BRIEF: <topic>

## Goal and acceptance criteria
<Desired observable result.>

## Accepted evidence
- E1: <claim>; <path:line>

## Invariants
- <behavior or boundary that must remain true>

## Scope and non-goals
- In: <owned surface>
- Out: <excluded surface>

## Dependencies and constraints
- <repo rule, sequence, release, data, or safety constraint>

## Open decisions
- <only unresolved choices the planner must settle>

## Return PLAN_CONTRACT.
```

## Terra execution brief

```markdown
# EXECUTION SLICE: <name>

## Plan contract
<Approved contract or path to it.>

## This slice
<One bounded outcome.>

## Owned paths
- <path>

## Test-first signal
<Focused failing test or gap-revealing check.>

## Acceptance criteria
- <observable condition>

## Stop conditions
- <contradiction, scope expansion, or missing authority that requires return>

## Return SLICE_REPORT.
```

## Reject malformed briefs

Reject a brief when it has no precise goal/question, omits material constraints, hides rejected paths, includes raw logs/full diffs without a reason, or asks the role to cross its authority boundary. Return `BRIEFING_REJECTED: <specific defect>`.
