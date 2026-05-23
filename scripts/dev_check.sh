#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-focused}"
PYTHON_BIN="${PYTHON:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

usage() {
  cat <<'USAGE'
Usage: scripts/dev_check.sh [focused|full|fresh-clone|all|live-help]

Modes:
  focused      Run the fast deterministic checks for the FrontDesk/ForgeUnit path.
  full         Run the full deterministic pytest suite.
  fresh-clone Run the fresh-clone offline smoke. This uses network/Git but not live Codex.
  all          Run full plus fresh-clone.
  live-help    Print the manual live semantic eval runbook path. Does not call Codex.
USAGE
}

case "$MODE" in
  focused)
    "$PYTHON_BIN" -m py_compile scripts/check_fresh_clone_readiness.py
    "$PYTHON_BIN" -m pytest \
      tests/test_frontdesk_live_codex_eval_script.py \
      tests/test_frontdesk_api.py \
      tests/test_forgeunit_adapter.py \
      -q
    ;;
  full)
    "$PYTHON_BIN" -m py_compile scripts/check_fresh_clone_readiness.py
    "$PYTHON_BIN" -m pytest -q
    ;;
  fresh-clone)
    "$PYTHON_BIN" scripts/check_fresh_clone_readiness.py \
      --summary-out .metaloop/phase10_fresh_clone_smoke_summary.json
    ;;
  all)
    "$0" full
    "$0" fresh-clone
    ;;
  live-help)
    cat <<'HELP'
Live Codex semantic eval is manual and opt-in.
Read docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md and run the command there explicitly.
HELP
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
