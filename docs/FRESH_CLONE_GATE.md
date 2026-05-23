# Fresh Clone Gate

Last updated: 2026-05-23

Status: deterministic offline readiness gate

## Purpose

This gate proves that a new checkout of SkillFoundry can install and run the
current ForgeUnit-backed FrontDesk path without relying on local sibling
directories, `.local` state, or the developer machine's existing virtualenv.

The gate does not call live Codex. It uses the deterministic `--fake-mode happy`
semantic eval path.

## Dependency Boundary

SkillFoundry keeps ContextForge as a submodule:

```text
third_party/contextforge
```

ForgeUnit is not resolved from `../ForgeUnit` anymore. The `forgeunit` extra is
pinned to the pushed Git tag:

```text
git+ssh://git@github.com/manstein-lzn/forgeunit.git@v1.2.1
```

This keeps the fresh clone path independent from the local workspace layout
while still avoiding a PyPI publishing step.

## Manual Fresh Clone Install

From an empty directory:

```bash
git clone --recurse-submodules git@github.com:manstein-lzn/skillfoundry.git
cd skillfoundry

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e third_party/contextforge
.venv/bin/python -m pip install -e ".[test,forgeunit]"
```

Then run a focused deterministic check:

```bash
.venv/bin/python -m pytest tests/test_frontdesk_live_codex_eval_script.py -q
```

Run the offline semantic smoke:

```bash
.venv/bin/python scripts/run_frontdesk_live_codex_eval.py \
  --runs-root .local/fresh_clone_gate_runs \
  --eval-id phase10-fresh-clone-smoke \
  --registry-path registry.json \
  --fake-mode happy \
  --limit 2 \
  --created-at 2026-05-23T00:00:00Z \
  --overwrite
```

Expected summary gates:

```text
totals.total == 2
totals.registered == 2
totals.failed == 0
totals.semantic_fidelity_failed == 0
totals.redaction_failures == 0
totals.unique_registry_skill_ids == 2
```

## Scripted Gate

The repository includes a wrapper that performs the same check in a temporary
clone:

```bash
.venv/bin/python scripts/check_fresh_clone_readiness.py \
  --repo-url git@github.com:manstein-lzn/skillfoundry.git \
  --branch main \
  --summary-out .metaloop/phase10_fresh_clone_smoke_summary.json
```

The script:

1. clones SkillFoundry with submodules;
2. creates a new virtualenv inside the clone;
3. installs ContextForge from the submodule;
4. installs SkillFoundry with `.[test,forgeunit]`;
5. runs the focused eval-harness test;
6. runs a two-scenario fake-mode semantic smoke;
7. copies `eval_summary.json` to the requested evidence path.

The copied evidence is refs-only. It must not include raw FrontDesk
conversation, raw worker input, raw prompt, raw transcript, command string,
stdout/stderr, or package body.

## Failure Interpretation

- Install failure before tests usually means the Git dependency, submodule, or
  SSH access boundary is broken.
- Focused pytest failure means the eval harness contract changed.
- `registered < total` means the default deterministic FrontDesk vNext path
  regressed.
- `semantic_fidelity_failed > 0` means scenario semantics are being flattened or
  lost before package generation.
- `redaction_failures > 0` means refs-only output boundaries regressed.

Live Codex failures are intentionally out of scope for this gate.
