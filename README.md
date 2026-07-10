# Codex Advisor

Codex skill and runtime for routing work across four specialist roles:

| Role | Default pin | Boundary |
|---|---|---|
| `sol_advisor` | `gpt-5.6-sol`, `xhigh` | Read-only architecture/advice |
| `sol_planner` | `gpt-5.6-sol`, `xhigh` | Read-only implementation planning |
| `luna_worker` | `gpt-5.6-luna`, `medium` | Cheap read-only repository evidence |
| `terra_executor` | `gpt-5.6-terra`, `xhigh` | One bounded workspace-write slice |

The defaults are preview model slugs and may not exist for every account. The fallback runner fails before launch when a pin is unavailable. Override them with `CODEX_ADVISOR_SOL_MODEL`, `CODEX_ADVISOR_LUNA_MODEL`, or `CODEX_ADVISOR_TERRA_MODEL`; use the matching `*_EFFORT` variable when necessary.

## Install

Requirements: macOS or Ubuntu, Bash, Git, Python 3, Perl, `jq`, `rg`, and an authenticated Codex CLI. The current release is exercised in CI on macOS and Ubuntu; Windows is not supported.

```bash
git clone https://github.com/codyrobertson/codex-advisor.git
cd codex-advisor
./scripts/install.sh --link
```

`--link` keeps the checkout canonical. Use `--copy` for a detached installation. The installer refuses to overwrite an existing skill or agent config. To uninstall, remove `$CODEX_HOME/skills/codex-advisor` and the four matching TOMLs under `$CODEX_HOME/agents` after confirming they belong to this repository.

Native roles are preferred. The pinned subprocess fallback is:

```bash
~/.codex/skills/codex-advisor/scripts/run-role.sh \
  luna-worker /path/to/repo briefing.md evidence.md
```

## Evaluation

The release gate has two tiers.

Deterministic tests use a generated Git repository and fake Codex executable. They verify model/effort/sandbox pins, all role contracts, atomic output promotion, malformed and failed output quarantine, timeout cleanup, minimal-home isolation, public-tree secret scans, installation, Luna fingerprints, and Terra's Git-visible owned-path boundary.

```bash
python3 evals/evaluate.py deterministic
```

Live routing evals use 16 role-neutral scenarios across routing, authority boundaries, recovery, and token pressure. They record exact-route score, forbidden-role violations, latency, Codex version, skill commit, and token usage when the CLI emits it. A release passes at 90% aggregate with no critical failures. One repetition is useful while developing; use three for release qualification.

```bash
python3 evals/evaluate.py live --dry-run
python3 evals/evaluate.py live --repetitions 3 --output evals/results/live.json
```

Public cases are regression tests, not a hidden benchmark. Maintain separate paraphrased/held-out cases for claims about generalization.

The checked-in [live smoke baseline](evals/baselines/live-smoke.json) records a real three-case run on `gpt-5.6-luna` medium: 3/3 exact routes, 11.8s median latency, and 21,433 median total tokens. Treat it as a reproducible smoke baseline, not a general model-quality claim.

## Safety and privacy

- Use only trusted repositories and briefs. Repository text can contain prompt injection.
- Read-only and workspace-write sandboxes are authority controls, not confidentiality boundaries.
- The fallback creates a minimal temporary Codex home and symlinks the existing Codex auth file; it does not copy credentials or import personal global instructions. A hostile process with the same user permissions may still read local credentials.
- Specialist calls can transmit source and brief content to the configured model provider. Do not send material your provider is not authorized to process.
- Terra scope checking covers Git-tracked and non-ignored untracked files. Ignored files and external side effects remain the root agent's responsibility.
- `.failed`, `.invalid`, `.scope.json`, and `.codex/advisor/` artifacts may contain sensitive context. They are ignored here, created with restrictive permissions, and should be redacted or deleted before sharing.
- The runner does not auto-revert scope violations or partial work because that could destroy pre-existing user changes.

This project is independent and is not affiliated with or endorsed by OpenAI. Codex and OpenAI are trademarks of their respective owner.

## License

MIT. See [LICENSE](LICENSE).
