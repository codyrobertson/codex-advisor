#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir=$(cd "$(dirname "$0")" && pwd -P)

usage() {
  printf 'Usage: %s <sol-advisor|sol-planner|luna-worker|terra-executor> <repo> <briefing.md> <output.md>\n' "$0" >&2
  exit 64
}

[[ $# -eq 4 ]] || usage

role=$1
repo_arg=$2
brief=$3
output=$4

[[ -d "$repo_arg" ]] || {
  printf 'Repository directory not found: %s\n' "$repo_arg" >&2
  exit 66
}

repo=$(git -C "$repo_arg" rev-parse --show-toplevel 2>/dev/null) || {
  printf 'Repository is not a Git worktree: %s\n' "$repo_arg" >&2
  exit 65
}
repo=$(cd "$repo" && pwd -P)

relative_to_repo() {
  case "$1" in
    "$repo"/*) printf '%s\n' "${1#"$repo"/}" ;;
    *) printf '\n' ;;
  esac
}

[[ -f "$brief" ]] || {
  printf 'Briefing not found: %s\n' "$brief" >&2
  exit 66
}

brief_dir=$(cd "$(dirname "$brief")" && pwd -P)
brief_abs="$brief_dir/$(basename "$brief")"
output_dir=$(dirname "$output")
mkdir -p "$output_dir"
output_dir_abs=$(cd "$output_dir" && pwd -P)
output_abs="$output_dir_abs/$(basename "$output")"

[[ "$brief_abs" != "$output_abs" ]] || {
  printf 'Briefing and output must be different files: %s\n' "$brief_abs" >&2
  exit 65
}

case "$role" in
  sol-advisor)
    model=${CODEX_ADVISOR_SOL_MODEL:-gpt-5.6-sol}
    effort=${CODEX_ADVISOR_SOL_EFFORT:-xhigh}
    sandbox='read-only'
    max_brief_bytes=8000
    max_output_bytes=6000
    default_timeout_seconds=900
    contract='Read the briefing first. Act only as a read-only expert advisor. Return ADVISOR_VERDICT. Do not implement, explore beyond the brief, or spawn agents.'
    output_headings=('## VERDICT' '## WHY' '## RISKS' '## FIRST MOVE' '## CONFIDENCE')
    format_rules='VERDICT is one decisive sentence; WHY is at most five sentences; FIRST MOVE is one action; CONFIDENCE starts with High, Medium, or Low.'
    ;;
  sol-planner)
    model=${CODEX_ADVISOR_SOL_MODEL:-gpt-5.6-sol}
    effort=${CODEX_ADVISOR_SOL_EFFORT:-xhigh}
    sandbox='read-only'
    max_brief_bytes=8000
    max_output_bytes=6000
    default_timeout_seconds=900
    contract='Read the briefing first. Act only as a read-only implementation planner. Return PLAN_CONTRACT. Do not edit, execute the plan, or spawn agents.'
    output_headings=('## DECISION' '## INVARIANTS' '## SLICES' '## DEPENDENCIES' '## VERIFICATION MATRIX' '## STOP CONDITIONS' '## CONFIDENCE')
    format_rules='SLICES includes Owned paths, Test-first signal, Done when, and Rollback; CONFIDENCE starts with High, Medium, or Low.'
    ;;
  luna-worker)
    model=${CODEX_ADVISOR_LUNA_MODEL:-gpt-5.6-luna}
    effort=${CODEX_ADVISOR_LUNA_EFFORT:-medium}
    sandbox='read-only'
    max_brief_bytes=12000
    max_output_bytes=8000
    default_timeout_seconds=600
    contract='Read the briefing first. Use rg first. Use at most three shell calls, cap each to 80 lines or 8 KB, avoid rereads, and use symlink-aware inspection when relevant. Return EVIDENCE_PACKET with at most eight findings. Do not edit or spawn agents.'
    output_headings=('## STATE FINGERPRINT' '## FINDINGS' '## FLOW' '## CONTRADICTIONS' '## UNKNOWNS' '## RECOMMENDED NEXT READS')
    format_rules='Each observed FINDING uses: - E1 [observed]: claim - path:line.'
    ;;
  terra-executor)
    model=${CODEX_ADVISOR_TERRA_MODEL:-gpt-5.6-terra}
    effort=${CODEX_ADVISOR_TERRA_EFFORT:-xhigh}
    sandbox='workspace-write'
    max_brief_bytes=24000
    max_output_bytes=12000
    default_timeout_seconds=1800
    contract='Read the briefing first. Implement only its approved bounded slice. Preserve unrelated work, verify the slice, and return SLICE_REPORT. Do not expand scope or spawn agents.'
    output_headings=('## SLICE' '## TEST-FIRST SIGNAL' '## CHANGES' '## VERIFICATION' '## DEVIATIONS' '## RISKS AND UNKNOWNS' '## DECISION')
    format_rules='DECISION is exactly complete, blocked, or needs review.'
    ;;
  *)
    usage
    ;;
esac

timeout_seconds=${CODEX_ADVISOR_TIMEOUT_SECONDS:-$default_timeout_seconds}
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || {
  printf 'CODEX_ADVISOR_TIMEOUT_SECONDS must be a positive integer.\n' >&2
  exit 65
}

brief_bytes=$(wc -c < "$brief_abs" | tr -d '[:space:]')
if (( brief_bytes > max_brief_bytes )); then
  printf 'Briefing too large for %s: %s bytes, limit %s\n' "$role" "$brief_bytes" "$max_brief_bytes" >&2
  exit 65
fi

if [[ "$role" == 'terra-executor' ]]; then
  rg -F -x -- '## Owned paths' "$brief_abs" >/dev/null || {
    printf 'Terra briefing needs an exact ## Owned paths heading for write-scope enforcement.\n' >&2
    exit 65
  }
  owned_paths=()
  owned_count=0
  while IFS= read -r owned; do
    owned=${owned#- }
    [[ -n "$owned" ]] || continue
    owned_paths[owned_count]=$owned
    owned_count=$((owned_count + 1))
  done < <(awk '/^## Owned paths$/{inside=1; next} inside && /^## /{exit} inside && /^- /{print}' "$brief_abs")
  (( owned_count > 0 )) || {
    printf 'Terra briefing needs at least one bullet under ## Owned paths; use - None for a no-write slice.\n' >&2
    exit 65
  }
fi

for dependency in git rg jq perl python3; do
  command -v "$dependency" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "$dependency" >&2
    exit 69
  }
done

codex debug models 2>/dev/null | jq -e \
  --arg model "$model" \
  --arg effort "$effort" \
  '(if type == "array" then . else (.models // .data // []) end)
   | any(.slug == $model and (.supported_reasoning_levels | any(.effort == $effort)))' \
  >/dev/null || {
    printf 'Requested model pin is unavailable: %s at %s\n' "$model" "$effort" >&2
    exit 69
  }

headings_text=$(printf '%s\n' "${output_headings[@]}")
state_rule=''
fingerprint_exclude=''
compute_repo_diff_hash() {
  untracked_paths=()
  untracked_count=0
  while IFS= read -r -d '' untracked; do
    [[ -n "$fingerprint_exclude" && "$untracked" == "$fingerprint_exclude" ]] && continue
    untracked_paths[untracked_count]=$untracked
    untracked_count=$((untracked_count + 1))
  done < <(git -C "$repo" ls-files --others --exclude-standard -z)
  {
    git -C "$repo" diff --binary HEAD --
    if (( untracked_count > 0 )); then
      printf 'UNTRACKED %s\n' "${untracked_paths[@]}"
      git -C "$repo" hash-object -- "${untracked_paths[@]}"
    fi
  } | git -C "$repo" hash-object --stdin
}
if [[ "$role" == 'luna-worker' ]]; then
  repo_head=$(git -C "$repo" rev-parse HEAD)
  repo_diff_hash=$(compute_repo_diff_hash)
  state_rule=" STATE FINGERPRINT must contain exactly HEAD $repo_head and diff $repo_diff_hash."
fi
prompt=$(printf '%s\nRepository: %s\nBriefing: %s\nDo not load skills or contract files. If the brief is malformed, return only BRIEFING_REJECTED: <specific defect>. Otherwise return exactly these headings once, in order, with nonempty bodies and no extra headings:\n%s\nRules:%s %s' "$contract" "$repo" "$brief_abs" "$headings_text" "$state_rule" "$format_rules")

tmp_output=$(mktemp "$output_dir_abs/.codex-advisor-${role}.XXXXXX")
fingerprint_exclude=$(relative_to_repo "$tmp_output")
timeout_marker="$tmp_output.timedout"
terra_snapshot=''
scope_report=''
runtime_home=''
exec_pid=''
watchdog_pid=''
cleanup() {
  if [[ -n "$watchdog_pid" ]] && kill -0 "$watchdog_pid" 2>/dev/null; then
    kill "$watchdog_pid" 2>/dev/null || true
  fi
  if [[ -n "$exec_pid" ]] && kill -0 "$exec_pid" 2>/dev/null; then
    kill -TERM -- "-$exec_pid" 2>/dev/null || true
    sleep 0.2
    kill -KILL -- "-$exec_pid" 2>/dev/null || true
  fi
  rm -f "$tmp_output"
  rm -f "$timeout_marker"
  [[ -z "$terra_snapshot" ]] || rm -f "$terra_snapshot"
  [[ -z "$scope_report" ]] || rm -f "$scope_report"
  if [[ -n "$runtime_home" ]]; then
    rm -rf "$runtime_home"
  fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

original_home=$HOME
source_codex_home=${CODEX_HOME:-$original_home/.codex}
child_codex_home=$source_codex_home
child_home=$original_home
shell_home=''
set -- --ignore-user-config
if [[ "${CODEX_ADVISOR_ISOLATE_HOME:-1}" != '0' ]]; then
  runtime_home=$(mktemp -d "${TMPDIR:-/tmp}/codex-role-home.XXXXXX")
  chmod 700 "$runtime_home"
  if [[ -f "$source_codex_home/auth.json" ]]; then
    ln -s "$source_codex_home/auth.json" "$runtime_home/auth.json"
  fi
  if [[ -f "$source_codex_home/models_cache.json" ]]; then
    ln -s "$source_codex_home/models_cache.json" "$runtime_home/models_cache.json"
  fi
  shell_home="$runtime_home/shell-home"
  mkdir -p "$shell_home"
  chmod 700 "$shell_home"
  toml_repo=$(printf '%s' "$repo" | sed 's/\\/\\\\/g; s/"/\\"/g')
  toml_shell_home=$(printf '%s' "$shell_home" | sed 's/\\/\\\\/g; s/"/\\"/g')
  {
    printf '[projects."%s"]\n' "$toml_repo"
    printf 'trust_level = "trusted"\n\n'
    printf '[shell_environment_policy]\ninherit = "core"\n\n'
    printf '[shell_environment_policy.set]\nHOME = "%s"\nCODEX_HOME = "%s"\n' "$toml_shell_home" "$toml_shell_home"
  } > "$runtime_home/config.toml"
  child_codex_home=$runtime_home
  child_home=$runtime_home
  set --
fi

if [[ "$role" == 'terra-executor' ]]; then
  terra_snapshot=$(mktemp "$output_dir_abs/.codex-advisor-terra-state.XXXXXX")
  scope_report=$(mktemp "$output_dir_abs/.codex-advisor-terra-scope.XXXXXX")
  tmp_relative=$(relative_to_repo "$tmp_output")
  timeout_relative=$(relative_to_repo "$timeout_marker")
  snapshot_relative=$(relative_to_repo "$terra_snapshot")
  scope_relative=$(relative_to_repo "$scope_report")
  python3 "$script_dir/worktree-state.py" snapshot "$repo" "$terra_snapshot" \
    --exclude "$tmp_relative" \
    --exclude "$timeout_relative" \
    --exclude "$snapshot_relative" \
    --exclude "$scope_relative"
fi

set +e
HOME="$child_home" CODEX_HOME="$child_codex_home" perl -e 'setpgrp(0, 0); exec @ARGV or die "exec codex failed: $!\n"' codex exec \
  --ephemeral \
  "$@" \
  --skip-git-repo-check \
  --disable apps \
  --disable memories \
  --disable multi_agent \
  --disable goals \
  -C "$repo" \
  -m "$model" \
  -c "model_reasoning_effort=\"$effort\"" \
  -c 'approval_policy="never"' \
  -s "$sandbox" \
  -o "$tmp_output" \
  "$prompt" </dev/null &
exec_pid=$!
perl -e '
  my ($pid, $seconds, $marker) = @ARGV;
  $SIG{TERM} = sub { exit 0 };
  $SIG{INT} = sub { exit 0 };
  sleep $seconds;
  if (kill 0, $pid) {
    open my $fh, ">", $marker or die "timeout marker: $!\n";
    close $fh;
    kill "TERM", -$pid;
    sleep 1;
    kill "KILL", -$pid;
  }
' "$exec_pid" "$timeout_seconds" "$timeout_marker" &
watchdog_pid=$!
wait "$exec_pid"
exec_rc=$?
exec_pid=''
kill "$watchdog_pid" 2>/dev/null || true
wait "$watchdog_pid" 2>/dev/null || true
watchdog_pid=''
set -e

if [[ "$role" == 'terra-executor' ]]; then
  set +e
  python3 "$script_dir/worktree-state.py" check "$repo" "$terra_snapshot" "${owned_paths[@]}" > "$scope_report"
  scope_rc=$?
  set -e
  if (( scope_rc == 3 )); then
    if [[ -s "$tmp_output" ]]; then
      mv -f "$tmp_output" "$output_abs.invalid"
    fi
    mv -f "$scope_report" "$output_abs.scope.json"
    scope_report=''
    printf 'Terra changed paths outside owned paths; inspect %s.scope.json and the worktree.\n' "$output_abs" >&2
    exit 65
  elif (( scope_rc != 0 )); then
    printf 'Terra scope verification failed with exit %s.\n' "$scope_rc" >&2
    exit 70
  fi
fi

if (( exec_rc != 0 )); then
  if [[ -s "$tmp_output" ]]; then
    mv -f "$tmp_output" "$output_abs.failed"
  fi
  if [[ -e "$timeout_marker" ]]; then
    printf 'Role process timed out: %s after %ss\n' "$role" "$timeout_seconds" >&2
  else
    printf 'Role process failed: %s exited %s\n' "$role" "$exec_rc" >&2
  fi
  exit "$exec_rc"
fi

[[ -s "$tmp_output" ]] || {
  printf 'Role returned no output: %s\n' "$role" >&2
  exit 70
}

reject_output() {
  local reason=$1
  mv -f "$tmp_output" "$output_abs.invalid"
  printf '%s; saved to %s.invalid\n' "$reason" "$output_abs" >&2
  exit 65
}

warn_output() {
  printf 'Warning: %s. Accepting the report; root must judge the evidence.\n' "$1" >&2
}

output_bytes=$(wc -c < "$tmp_output" | tr -d '[:space:]')
if (( output_bytes > max_output_bytes )); then
  reject_output "Role output too large: $output_bytes bytes, limit $max_output_bytes"
fi

if rg -q '^BRIEFING_REJECTED: .+' "$tmp_output"; then
  rejection_lines=$(awk 'NF { count++ } END { print count + 0 }' "$tmp_output")
  (( rejection_lines == 1 )) || reject_output 'BRIEFING_REJECTED must be the only nonempty line'
  mv -f "$tmp_output" "$output_abs"
  cleanup
  trap - EXIT HUP INT TERM
  printf 'Role: %s\nModel: %s\nEffort: %s\nOutput: %s\n' "$role" "$model" "$effort" "$output_abs"
  exit 0
fi

heading_lines=()
previous_line=0
for heading in "${output_headings[@]}"; do
  matches=$(rg -n -F -x -- "$heading" "$tmp_output" || true)
  match_count=$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l | tr -d '[:space:]')
  (( match_count == 1 )) || reject_output "Role output must contain exactly one heading: $heading"
  line=${matches%%:*}
  (( line > previous_line )) || reject_output "Role output headings are out of order at: $heading"
  heading_lines+=("$line")
  previous_line=$line
done

heading_count=$(rg -c '^## ' "$tmp_output" || true)
if (( heading_count != ${#output_headings[@]} )); then
  warn_output 'role output contains extra headings'
fi

total_lines=$(awk 'END { print NR }' "$tmp_output")
section_bodies=()
for ((i = 0; i < ${#heading_lines[@]}; i++)); do
  start=$((heading_lines[i] + 1))
  if (( i + 1 < ${#heading_lines[@]} )); then
    end=$((heading_lines[i + 1] - 1))
  else
    end=$total_lines
  fi
  (( start <= end )) || reject_output "Role output section is empty: ${output_headings[i]}"
  body=$(sed -n "${start},${end}p" "$tmp_output")
  printf '%s\n' "$body" | rg -q '[^[:space:]]' || reject_output "Role output section is empty: ${output_headings[i]}"
  section_bodies+=("$body")
done

case "$role" in
  luna-worker)
    current_head=$(git -C "$repo" rev-parse HEAD)
    current_diff_hash=$(compute_repo_diff_hash)
    [[ "$current_head" == "$repo_head" && "$current_diff_hash" == "$repo_diff_hash" ]] || reject_output 'Repository state changed during Luna investigation'
    printf '%s\n' "${section_bodies[0]}" | rg -F -q "HEAD $repo_head" || reject_output 'Luna fingerprint does not match repository HEAD'
    printf '%s\n' "${section_bodies[0]}" | rg -F -q "diff $repo_diff_hash" || reject_output 'Luna fingerprint does not match repository diff hash'
    printf '%s\n' "${section_bodies[1]}" | rg -q '^- E[0-9]+ \[(observed|inferred)\]:' || warn_output 'Luna findings lack typed evidence entries'
    finding_count=$(printf '%s\n' "${section_bodies[1]}" | rg -c '^- E[0-9]+ \[(observed|inferred)\]:' || true)
    (( finding_count <= 8 )) || warn_output "Luna returned $finding_count findings; preferred limit is 8"
    observed_count=$(printf '%s\n' "${section_bodies[1]}" | rg -c '^- E[0-9]+ \[observed\]:' || true)
    observed_with_location=$(printf '%s\n' "${section_bodies[1]}" | rg -c '^- E[0-9]+ \[observed\]:.* - .+:[0-9]+' || true)
    (( observed_count == observed_with_location )) || warn_output 'some observed Luna findings lack path:line evidence'
    next_read_count=$(printf '%s\n' "${section_bodies[5]}" | rg -c '^- ' || true)
    (( next_read_count <= 3 )) || warn_output "Luna returned $next_read_count next reads; preferred limit is 3"
    ;;
  sol-advisor)
    printf '%s\n' "${section_bodies[2]}" | rg -q '^- .+ -> .+' || warn_output 'advisor risks do not pair every risk with a mitigation'
    confidence=$(printf '%s\n' "${section_bodies[4]}" | sed -n '/[^[:space:]]/{p;q;}')
    printf '%s\n' "$confidence" | rg -q '^(High|Medium|Low)([[:space:]]*[-:].*)?$' || warn_output 'advisor confidence does not use the preferred High, Medium, or Low form'
    ;;
  sol-planner)
    for term in 'Owned paths' 'Test-first signal' 'Done when' 'Rollback'; do
      printf '%s\n' "${section_bodies[2]}" | rg -qi "$term" || warn_output "planner slices omit the preferred field: $term"
    done
    confidence=$(printf '%s\n' "${section_bodies[6]}" | sed -n '/[^[:space:]]/{p;q;}')
    printf '%s\n' "$confidence" | rg -q '^(High|Medium|Low)([[:space:]]*[-:].*)?$' || warn_output 'planner confidence does not use the preferred High, Medium, or Low form'
    ;;
  terra-executor)
    decision=$(printf '%s\n' "${section_bodies[6]}" | sed -n '/[^[:space:]]/{p;q;}')
    printf '%s\n' "$decision" | rg -q '^(complete|blocked|needs review)$' || reject_output 'Terra decision must be complete, blocked, or needs review'
    if [[ "$decision" == 'complete' ]]; then
      printf '%s\n' "${section_bodies[1]}" | rg -q '.+ -> .+' || warn_output 'completed Terra report lacks a test-first command and observed signal'
      printf '%s\n' "${section_bodies[2]}" | rg -q '^- .+ - .+' || warn_output 'completed Terra report changes are not path-qualified'
      printf '%s\n' "${section_bodies[3]}" | rg -q '^- .+ -> .+' || warn_output 'completed Terra report lacks exact verification results'
    fi
    ;;
esac

mv -f "$tmp_output" "$output_abs"
cleanup
trap - EXIT HUP INT TERM

printf 'Role: %s\nModel: %s\nEffort: %s\nOutput: %s\n' "$role" "$model" "$effort" "$output_abs"
