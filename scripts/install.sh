#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s [--codex-home DIR] [--link|--copy]\n' "$0" >&2
  exit 64
}

script_dir=$(cd "$(dirname "$0")" && pwd -P)
repo_root=$(cd "$script_dir/.." && pwd -P)
source_skill="$repo_root/skill/codex-advisor"
codex_home=${CODEX_HOME:-$HOME/.codex}
mode='link'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --codex-home)
      [[ $# -ge 2 ]] || usage
      codex_home=$2
      shift 2
      ;;
    --link)
      mode='link'
      shift
      ;;
    --copy)
      mode=copy
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      usage
      ;;
  esac
done

[[ -f "$source_skill/SKILL.md" ]] || {
  printf 'Skill source is missing: %s\n' "$source_skill" >&2
  exit 66
}

mkdir -p "$codex_home/skills" "$codex_home/agents"
target_skill="$codex_home/skills/codex-advisor"
if [[ -e "$target_skill" || -L "$target_skill" ]]; then
  if [[ -L "$target_skill" && "$(readlink "$target_skill")" == "$source_skill" && "$mode" == link ]]; then
    :
  else
    printf 'Refusing to replace existing skill: %s\n' "$target_skill" >&2
    printf 'Move or remove it explicitly, then rerun the installer.\n' >&2
    exit 73
  fi
else
  if [[ "$mode" == link ]]; then
    ln -s "$source_skill" "$target_skill"
  else
    cp -R "$source_skill" "$target_skill"
  fi
fi

for role in sol_advisor sol_planner luna_worker terra_executor; do
  source_role="$source_skill/assets/agent-configs/$role.toml"
  target_role="$codex_home/agents/$role.toml"
  if [[ -e "$target_role" || -L "$target_role" ]]; then
    if [[ -L "$target_role" && "$(readlink "$target_role")" == "$source_role" && "$mode" == link ]]; then
      continue
    fi
    if [[ "$mode" == copy ]] && cmp -s "$source_role" "$target_role"; then
      continue
    fi
    printf 'Refusing to replace existing role config: %s\n' "$target_role" >&2
    exit 73
  fi
  if [[ "$mode" == link ]]; then
    ln -s "$source_role" "$target_role"
  else
    cp "$source_role" "$target_role"
  fi
done

printf 'Installed codex-advisor (%s) into %s\n' "$mode" "$codex_home"
