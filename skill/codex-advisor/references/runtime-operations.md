# Runtime Operations

## Performance

- Prefer native roles to avoid subprocess startup.
- Use `fork_turns="none"` or a small fork; pass context in artifacts.
- Reference files instead of pasting raw context.
- Start one Luna worker. Add one more only for a disjoint question likely to save more than one process startup.
- Keep Terra sequential unless worktrees or write sets are isolated.
- Reuse evidence only when its fingerprint matches current `HEAD` and dirty-diff hash.
- The fallback uses temporary minimal `HOME` and `CODEX_HOME` values to exclude unrelated skills. It symlinks auth/cache for the Codex process, does not import personal rules or global instructions, trusts only the target repo, and gives spawned shells a separate minimal home plus the core environment. This is context isolation, not a confidentiality boundary; use trusted repositories and briefs. Set `CODEX_ADVISOR_ISOLATE_HOME=0` only for diagnostics requiring the full personal Codex home.

## Fallback Runner

`run-role.sh` requires role, Git worktree, brief, and output paths. It validates:

- repository and distinct paths;
- model/effort availability;
- role-specific brief/output byte caps;
- Terra execution headings;
- unique, ordered response headings with nonempty bodies;
- exact runner-computed Luna fingerprint/evidence shape, Sol confidence values, and Terra's decision enum.
- Terra's declared owned paths against pre/post snapshots of Git-visible files. Scope violations remain in the worktree for deliberate inspection and produce `<output>.scope.json`; the runner never destroys unknown work.

Default watchdogs are 10 minutes for Luna, 15 for Sol, and 30 for Terra. Override with a positive `CODEX_ADVISOR_TIMEOUT_SECONDS` value.

The selected response schema is embedded in the role prompt; specialists do not open the shared contract reference.

Model output is written to a temporary file. Valid output atomically replaces the requested artifact. Malformed output is saved as `<output>.invalid`; nonzero process output as `<output>.failed`. Neither is an accepted result.

The runner applies `umask 077`, so new briefs, reports, failure artifacts, and scope reports are private to the current user by default. Redact sensitive material and remove retained artifacts when no longer needed.

The default model pins can be overridden without editing the skill: `CODEX_ADVISOR_SOL_MODEL`, `CODEX_ADVISOR_LUNA_MODEL`, and `CODEX_ADVISOR_TERRA_MODEL`; corresponding `*_EFFORT` variables override reasoning effort. Availability is checked before launch.

## Retry And Recovery

- Retry read-only Luna/Sol once only for a transient process failure.
- Fix the brief before retrying malformed output.
- Never blindly retry Terra after partial execution.
- After Terra failure, freeze execution and inspect the actual diff and focused test state.
- Classify changed paths as valid partial progress, invalid change requiring deliberate reversal, or unresolved.
- Re-run Luna if the worktree fingerprint changed.
- Give Terra a new narrowly owned recovery slice with current state, test signal, criteria, and stop conditions.

## Durable Artifacts

Use `.codex/advisor/<topic>/` for consequential work:

```text
evidence.md        # Luna EVIDENCE_PACKET + fingerprint
briefing.md        # compact Sol input
verdict.md         # ADVISOR_VERDICT or PLAN_CONTRACT
slice-<n>.md       # Terra SLICE_REPORT
verification.md   # root-owned command/diff ledger
```

Do not commit these unless the repository expects orchestration state. Reports never override worktree, test, deploy, or runtime evidence.
