# FrontDesk Live Semantic Eval

Last updated: 2026-05-23

Status: explicit manual gate, not default CI

## Purpose

This eval checks whether the full live command-boundary path preserves scenario
semantics while keeping public summaries refs-only:

```text
FrontDesk API
  -> FrontDesk approved/frozen job
  -> ContextForge-governed build boundary
  -> ForgeUnit SkillFoundry vNext
  -> live Codex exec command bridge
  -> SkillFoundry Verifier
  -> Registry
  -> refs-only eval summary
```

The gate exists because an infrastructure success is not enough. A run only
counts when different scenarios produce distinct skill identities and package
content that still contains the required semantic markers.

## When To Run

Run this manually after changes to:

- FrontDesk request capture or plan/freeze behavior;
- ContextForge/Goal Runtime context propagation;
- ForgeUnit command boundary or evidence policy;
- SkillFoundry verifier/registry promotion gates;
- `scripts/run_frontdesk_live_codex_eval.py`;
- `scripts/forgeunit_codex_exec_worker.py`.

Do not run it in default pytest or CI. It uses live Codex, takes several
minutes, and depends on the local Codex CLI authentication state.

## Preconditions

```bash
which codex
codex --version
.venv/bin/python -m pytest tests/test_frontdesk_live_codex_eval_script.py -q
```

The Codex CLI must be able to execute:

```bash
codex exec --sandbox workspace-write --skip-git-repo-check -
```

## Command

From the SkillFoundry repo root:

```bash
PYTHON="$PWD/.venv/bin/python"
WRAPPER="$PWD/scripts/forgeunit_codex_exec_worker.py"

"$PYTHON" scripts/run_frontdesk_live_codex_eval.py \
  --runs-root .local/frontdesk_live_codex_eval_runs \
  --eval-id frontdesk-semantic-live-manual \
  --registry-path registry.json \
  --limit 2 \
  --version-prefix frontdesk-semantic-live-manual \
  --created-at 2026-05-23T00:00:00Z \
  --command "$PYTHON $WRAPPER --timeout 1800 --codex-command 'codex exec --sandbox workspace-write --skip-git-repo-check -'" \
  --overwrite
```

Use `--limit 2` for the normal gate. Increase the limit only when intentionally
testing broader scenario coverage.

## Required Gates

The refs-only `eval_summary.json` must satisfy:

```text
totals.total == 2
totals.registered == 2
totals.failed == 0
totals.verification_failed == 0
totals.registry_rejected == 0
totals.semantic_fidelity_configured == 2
totals.semantic_fidelity_passed == 2
totals.semantic_fidelity_failed == 0
totals.redaction_failures == 0
totals.unique_registry_skill_ids == 2
failure_taxonomy == []
redaction_findings == []
```

Each scenario must report:

```text
status == registered
forgeunit_skillfoundry.verification_passed == true
forgeunit_skillfoundry.registry_approved == true
semantic_fidelity.source_passed == true
semantic_fidelity.package_checked == true
semantic_fidelity.package_passed == true
```

## Forbidden Public Summary Content

The eval summary must not include:

```text
raw FrontDesk conversation
raw worker input
raw prompt
raw transcript
raw stdout
raw stderr
package body
worker script path or name
command string
ForgeUnit worker environment variable names
```

A quick scan:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

text = Path(
    ".local/frontdesk_live_codex_eval_runs/frontdesk-semantic-live-manual/eval_summary.json"
).read_text(encoding="utf-8")
forbidden = [
    "forgeunit_codex_exec_worker.py",
    "codex exec --sandbox",
    "--skip-git-repo-check",
    "FORGEUNIT_TASK_DIR",
    "FORGEUNIT_WORKER_RESULT",
    "Build a governed Codex skill for analyzing pasted pytest failures",
    "Build a governed Codex skill for creating concise repository onboarding",
]
bad = [item for item in forbidden if item in text]
print({"bad": bad, "bytes": len(text.encode("utf-8"))})
raise SystemExit(1 if bad else 0)
PY
```

## Failure Interpretation

- `frontdesk_build_failed`: inspect refs and structured worker result summaries
  first; do not paste raw stdout/stderr/transcript into public reports.
- `semantic_fidelity_failed`: check whether `frontdesk/clarification_summary.md`,
  `frontdesk/core_need_brief.json`, `frontdesk/draft_skill_spec.yaml`, frozen
  `skill_spec.yaml`, and `worker_input.md` still carry scenario-specific terms.
- `unique_registry_skill_ids < total`: package identity has flattened.
- `redaction_failures > 0`: trust-boundary regression; stop promotion.
- verifier or registry failure: treat worker output as evidence only; the
  independent verifier/registry gates remain authoritative.

## Current Evidence

The latest successful two-scenario live run was completed on 2026-05-23:

```text
eval_id: frontdesk-semantic-live-002
registered: 2
semantic_fidelity_passed: 2
semantic_fidelity_failed: 0
redaction_failures: 0
unique_registry_skill_ids: 2
```

This evidence is local operational state under `.metaloop/` and `.local/`; it is
not committed to the repository.
