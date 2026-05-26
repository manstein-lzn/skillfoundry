#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_WORKTREE_ROOT="$(cd "$ROOT/.." && pwd)/skillfoundry-worktrees"
WORKTREE_ROOT="${SKILLFOUNDRY_WORKTREE_ROOT:-$DEFAULT_WORKTREE_ROOT}"
BASE_BRANCH="${BASE_BRANCH:-main}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/worktree_task.sh new <task-slug> [base-branch]
  scripts/worktree_task.sh list
  scripts/worktree_task.sh status
  scripts/worktree_task.sh remove <task-slug>

Environment:
  SKILLFOUNDRY_WORKTREE_ROOT  Parent directory for sibling worktrees.
  BASE_BRANCH                 Default base branch for new worktrees.

Examples:
  scripts/worktree_task.sh new adaptive-benchmark
  scripts/worktree_task.sh new codexarium-live main
  scripts/worktree_task.sh list
USAGE
}

safe_slug() {
  local slug="$1"
  if [[ ! "$slug" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "task-slug must be a safe branch/path segment" >&2
    exit 2
  fi
}

git_root_clean_enough_for_new_worktree() {
  if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
    cat >&2 <<'MSG'
Current main worktree has uncommitted changes.
Commit or stash the relevant work before creating a new upgrade worktree.
This script does not move dirty changes automatically.
MSG
    exit 1
  fi
}

new_worktree() {
  local slug="$1"
  local base="${2:-$BASE_BRANCH}"
  safe_slug "$slug"
  git_root_clean_enough_for_new_worktree

  local branch="work/$slug"
  local path="$WORKTREE_ROOT/$slug"
  if [[ -e "$path" ]]; then
    echo "worktree path already exists: $path" >&2
    exit 1
  fi

  mkdir -p "$WORKTREE_ROOT"
  git -C "$ROOT" fetch origin "$base"
  git -C "$ROOT" worktree add -b "$branch" "$path" "origin/$base"
  cat <<MSG
Created worktree:
  path:   $path
  branch: $branch

Next:
  cd "$path"
  python3 -m venv .venv
  .venv/bin/python -m pip install -e third_party/contextforge
  .venv/bin/python -m pip install -e '.[test,forgeunit]'
MSG
}

list_worktrees() {
  git -C "$ROOT" worktree list --porcelain
}

status_worktrees() {
  while IFS= read -r line; do
    case "$line" in
      worktree\ *)
        local path="${line#worktree }"
        echo "== $path =="
        git -C "$path" status --short --branch
        ;;
    esac
  done < <(git -C "$ROOT" worktree list --porcelain)
}

remove_worktree() {
  local slug="$1"
  safe_slug "$slug"
  local path="$WORKTREE_ROOT/$slug"
  git -C "$ROOT" worktree remove "$path"
}

case "${1:-}" in
  new)
    if [[ $# -lt 2 || $# -gt 3 ]]; then
      usage >&2
      exit 2
    fi
    new_worktree "$2" "${3:-$BASE_BRANCH}"
    ;;
  list)
    list_worktrees
    ;;
  status)
    status_worktrees
    ;;
  remove)
    if [[ $# -ne 2 ]]; then
      usage >&2
      exit 2
    fi
    remove_worktree "$2"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
