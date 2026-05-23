# CodexWorker Pilot

WP8 adds `CodexWorker` as a pilot adapter behind the existing
`BuildWorker` / `WorkerAdapter` protocol. It invokes `codex exec` only at the
worker boundary, records stdout/stderr as transcript evidence, and leaves
acceptance to the independent `Verifier` and `LocalSkillRegistry` gates.

## Boundary

`CodexWorker` can configure:

- workspace root passed with `--cd`;
- sandbox mode, defaulting to `workspace-write`;
- approval policy, defaulting to `never`;
- optional model and profile;
- optional `--config key=value` overrides;
- required package files, defaulting to `package/SKILL.md`.

The prompt instructs Codex to write only under `package/` and the current
`attempts/<id>/` directory. The adapter also fails closed when `codex exec`
times out, exits nonzero, modifies files outside those roots, or does not
produce required package files.

SkillFoundry does not control or replay Codex internal prompt planning, tool
loop, context compaction, cache, or cost. ContextForge may record worker
boundary evidence, but Codex internals remain external evidence only. Codex
self-report is not acceptance evidence.

## Usage Availability

`CodexWorker` records `usage_available=False` with:

```text
Codex CLI pilot usage is unavailable because the CLI boundary does not expose reliable provider usage.
```

Do not infer provider cost or token usage from the transcript.

## Default Tests

Default automated tests use deterministic fake command runners. They do not
invoke live Codex, network, or a real model provider.

## Manual Live Pilot

Live Codex is opt-in. Set `SKILLFOUNDRY_RUN_CODEX_PILOT=1` before using the
default subprocess runner:

```bash
SKILLFOUNDRY_RUN_CODEX_PILOT=1 .venv/bin/python - <<'PY'
from pathlib import Path

from skillfoundry import (
    APPROVAL_APPROVED,
    DEFAULT_REGISTRY_VERSION,
    LocalSkillRegistry,
    Verifier,
)
from skillfoundry.offline import prepare_offline_workspace
from skillfoundry.worker import CodexWorker, WorkerAdapter

root = Path("runs/codex-pilot")
workspace = prepare_offline_workspace(
    requirement_path=None,
    output=root,
    requirement_text="Build a small Codex Skill that explains SkillFoundry verifier evidence.",
    attempt_limit=1,
    timeout_seconds=300,
    overwrite=True,
)

attempt = WorkerAdapter(CodexWorker()).invoke(workspace, "001")
verification = Verifier().verify(workspace, attempt_id="001")

print({"attempt_ready_for_verifier": attempt.ready_for_verifier, "verifier_passed": verification.passed})

if verification.passed:
    entry = LocalSkillRegistry(root.parent / "registry.json").add_verified(
        workspace,
        version=DEFAULT_REGISTRY_VERSION,
        review_status="manual_codex_pilot",
    )
    assert entry.approval_status == APPROVAL_APPROVED
    print({"registered": entry.skill_id, "version": entry.version})
PY
```

Run the normal test suite before any live pilot:

```bash
.venv/bin/python -m pytest -q
```
