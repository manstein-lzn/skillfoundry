# Development Workflow

Last updated: 2026-05-23

Status: deterministic local contributor workflow

## Purpose

This document defines the commands a contributor or future agent should run
before claiming that a local SkillFoundry change is ready.

The default workflow does not call live Codex. Live semantic eval is a separate
manual gate documented in `docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md`.

## Command Summary

From the repository root:

```bash
make focused
make test
make fresh-clone-smoke
make live-semantic-eval-help
```

The same commands are available through the script:

```bash
scripts/dev_check.sh focused
scripts/dev_check.sh full
scripts/dev_check.sh fresh-clone
scripts/dev_check.sh live-help
```

For substantial upgrade tracks, first create an isolated git worktree:

```bash
scripts/worktree_task.sh new <task-slug>
cd ../skillfoundry-worktrees/<task-slug>
```

See `docs/WORKTREE_WORKFLOW.md` for branch naming, bootstrap, and merge
discipline.

## Focused Check

Use this after changes to FrontDesk, ForgeUnit adapter boundaries, eval harness
logic, dependency wiring, or docs that describe those paths:

```bash
make focused
```

It runs:

```text
python -m py_compile scripts/check_fresh_clone_readiness.py
pytest tests/test_frontdesk_live_codex_eval_script.py tests/test_frontdesk_api.py tests/test_forgeunit_adapter.py -q
```

This is deterministic and offline.

## Full Test

Use this before committing source changes:

```bash
make test
```

It runs:

```text
python -m py_compile scripts/check_fresh_clone_readiness.py
pytest -q
```

This is deterministic and offline.

## Fresh Clone Smoke

Use this before claiming that a new user can reproduce the current baseline:

```bash
make fresh-clone-smoke
```

It runs `scripts/check_fresh_clone_readiness.py`, which:

1. clones SkillFoundry with submodules into a temporary directory;
2. creates a new virtualenv;
3. installs ContextForge from `third_party/contextforge`;
4. installs SkillFoundry with `.[test,forgeunit]`;
5. resolves ForgeUnit from `git@github.com:manstein-lzn/forgeunit.git@v1.2.1`;
6. runs the focused eval harness test;
7. runs a two-scenario fake-mode semantic smoke.

This uses Git/network access but does not call live Codex.

Expected summary gates:

```text
totals.registered == 2
totals.semantic_fidelity_failed == 0
totals.redaction_failures == 0
totals.unique_registry_skill_ids == 2
```

## Live Semantic Eval

Do not put live Codex eval behind `make test`, `make focused`, or default CI.

To see the manual runbook:

```bash
make live-semantic-eval-help
```

Then read:

```text
docs/FRONTDESK_LIVE_SEMANTIC_EVAL.md
```

Run that gate only when intentionally validating live command-boundary behavior.

## Python Selection

The script chooses Python in this order:

```text
$PYTHON
.venv/bin/python
python3
```

Examples:

```bash
PYTHON=.venv/bin/python make focused
PYTHON=python3 scripts/dev_check.sh full
```

## What Not To Commit

Do not commit:

```text
.local/
.metaloop/
.forgeunit/
package-lock.json
temporary fresh-clone directories
live Codex run artifacts
```

The public repository should contain source, tests, docs, and stable scripts;
runtime evidence stays local unless a future explicit audit policy says
otherwise.
