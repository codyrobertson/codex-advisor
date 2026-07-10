# Response Contracts

## EVIDENCE_PACKET

```markdown
## STATE FINGERPRINT
<git HEAD plus dirty-diff hash used for this investigation>

## FINDINGS
- E1 [observed]: <claim> - <path:line, symbol, command>
- E2 [inferred]: <claim> - based on E1; confidence <high|medium|low>
<At most 8 findings.>

## FLOW
<Concise control/data/dependency flow.>

## CONTRADICTIONS
- <evidence that does not agree>

## UNKNOWNS
- <missing evidence and exact next query>

## RECOMMENDED NEXT READS
- <at most three paths or commands>
```

No implementation plan unless the brief explicitly asks for candidate options.

## ADVISOR_VERDICT

```markdown
## VERDICT
<One decisive sentence.>

## WHY
<Only reasoning that discriminates between options; at most five sentences.>

## RISKS
- <risk> -> <mitigation>

## FIRST MOVE
<One immediately executable next action.>

## CONFIDENCE
<High|Medium|Low> - <one missing fact if not High>
```

## PLAN_CONTRACT

```markdown
## DECISION
<Chosen shape and rejected alternatives.>

## INVARIANTS
- <must remain true>

## SLICES
1. <slice>
   - Owned paths: <paths>
   - Test-first signal: <test/check>
   - Changes: <specific actions>
   - Done when: <observable outcome>
   - Rollback: <reversal path>

## DEPENDENCIES
<Required order and external prerequisites.>

## VERIFICATION MATRIX
- <risk/behavior> -> <command or proof>

## STOP CONDITIONS
- <when executor must stop and return>

## CONFIDENCE
<High|Medium|Low> - <reason>
```

## SLICE_REPORT

```markdown
## SLICE
<Name and completion state.>

## TEST-FIRST SIGNAL
<Command and observed failing/gap signal before implementation.>

## CHANGES
- <path> - <what and why>

## VERIFICATION
- <command> -> <exact result>

## DEVIATIONS
<None, or explicit contract deviation and reason.>

## RISKS AND UNKNOWNS
- <remaining item>

## DECISION
<complete|blocked|needs review>
```
