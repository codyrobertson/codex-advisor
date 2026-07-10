# Codex Advisor

I got tired of throwing the biggest model at every coding task.

Codex Advisor gives each job to the cheapest model that can handle it. Luna searches the repo. Sol makes the hard calls and writes the plan. Terra gets a small, explicit slice to implement. The root agent still owns scope, verification, and the final call.

The roles are optional specialists, not a pipeline. If the root already has the evidence and can finish safely, it should. The fallback runner enforces fingerprints and write scope, but treats report-format drift as a warning so a useful result does not trigger another expensive model call.

| Role | Default model | What it does | Can write? |
|---|---|---|---|
| `luna_worker` | `gpt-5.6-luna`, `medium` | Searches large repos and returns cited evidence | No |
| `sol_advisor` | `gpt-5.6-sol`, `xhigh` | Handles architecture decisions and second opinions | No |
| `sol_planner` | `gpt-5.6-sol`, `xhigh` | Turns accepted evidence into an implementation plan | No |
| `terra_executor` | `gpt-5.6-terra`, `xhigh` | Implements one bounded slice and runs its checks | Yes |

These model names are preview slugs. Your account may not have them. The runner checks before launch and tells you when a model is missing. You can swap the defaults with `CODEX_ADVISOR_SOL_MODEL`, `CODEX_ADVISOR_LUNA_MODEL`, or `CODEX_ADVISOR_TERRA_MODEL`. The matching `*_EFFORT` variables change reasoning effort.

## Install

You need macOS or Ubuntu, plus Bash, Git, Python 3, Perl, `jq`, `rg`, and an authenticated Codex CLI. CI runs on both operating systems. Windows is not supported yet.

```bash
git clone https://github.com/codyrobertson/codex-advisor.git
cd codex-advisor
./scripts/install.sh --link
```

`--link` makes the checkout your installed copy, so a `git pull` updates the skill. Use `--copy` if you want a detached install. The installer will not overwrite an existing skill or agent config.

To uninstall it, remove `$CODEX_HOME/skills/codex-advisor` and these four files from `$CODEX_HOME/agents`:

```text
sol_advisor.toml
sol_planner.toml
luna_worker.toml
terra_executor.toml
```

Codex should use the native roles when they are available. The subprocess runner is the fallback:

```bash
~/.codex/skills/codex-advisor/scripts/run-role.sh \
  luna-worker /path/to/repo briefing.md evidence.md
```

## Does it work?

I did not want to publish a routing prompt and call it a system, so the repo has two eval layers.

The deterministic suite creates a temporary Git repo and runs every role through a fake Codex binary. It checks the model pins, sandboxes, response contracts, timeouts, cleanup, atomic output handling, Luna fingerprints, secret scanning, installation, and Terra's write scope.

```bash
python3 evals/evaluate.py deterministic
```

The live suite asks Codex to route 18 tasks without leaking the expected answer. The cases cover simple fixes, messy cross-cutting work, security changes, failed patches, stale evidence, pressure to use too many or too few models, already-verified work, and harmless report drift that should not trigger a rerun.

```bash
python3 evals/evaluate.py live --dry-run
python3 evals/evaluate.py live --repetitions 3 --output evals/results/live.json
```

A release needs at least 90% exact routing with zero critical failures.

The checked-in [full qualification run](evals/baselines/live-qualification.json) scored 15/16, or 93.75%, with zero critical failures on the original matrix. Median latency was 13.0 seconds and median token use was 25,198.5. The one miss chose Root for a scheduling decision instead of Fast with Terra. I ran that case three more times and got the expected Fast to Terra route all three times. The variance is in the repo because hiding it would make the eval useless. The two newer anti-ritual cases can be run independently before paying for another full qualification.

There is also a smaller [three-case smoke run](evals/baselines/live-smoke.json). The public cases are regression tests, not a secret benchmark. If you want to make model quality claims, keep a separate set of held-out prompts.

## Safety

This controls what an agent may do. It does not turn an untrusted repo into a safe one.

- Use trusted repositories and briefs. Source files can contain prompt injection.
- A sandbox limits authority, not visibility. A process running as your user may still read local credentials.
- The fallback links your existing Codex auth file into a temporary home. It does not copy the credential or load your personal global instructions.
- Model calls can send source code and brief content to your configured provider.
- Terra checks changes to tracked files and non-ignored untracked files. It cannot catch ignored files or side effects outside the repo.
- Failed and invalid reports may contain sensitive context. The repo ignores them and creates them with private permissions, but you still need to delete or redact them before sharing.
- The runner never auto-reverts unexpected changes. Guessing what to undo is a good way to destroy somebody else's work.

This is an independent project. OpenAI does not endorse or maintain it. Codex and OpenAI are trademarks of their respective owner.

## License

MIT. See [LICENSE](LICENSE).
