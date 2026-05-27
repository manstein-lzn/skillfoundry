"""Offline fixtures for the clean ForgeUnit SkillFoundry composition layer."""

from __future__ import annotations

from pathlib import Path


VALID_CODEX_SKILL = """---
name: forgeunit-skillfoundry-composition-skill
description: Deterministic ForgeUnit SkillFoundry composition fixture.
---

# ForgeUnit SkillFoundry Composition Skill

## Overview
This skill is a deterministic fixture for the clean SkillFoundry-on-ForgeUnit composition layer.

## When To Use
Use this fixture when validating offline ForgeUnit command-bridge registration.

## When Not To Use
Do not use this fixture for live Codex calls or user-facing package generation.

## Inputs
Provide frozen SkillFoundry workspace refs and a ForgeUnit command boundary.

## Outputs
Return a package/SKILL.md file and refs-only evidence for verifier and registry gates.

## Workflow
1. Read the frozen SkillFoundry workspace refs.
2. Write package and boundary evidence files.
3. Let SkillFoundry verifier decide acceptance.
4. Let SkillFoundry registry promote only verified output.

## Safety
Keep raw prompts, raw transcripts, package bodies, and raw worker input out of graph state.
"""


INVALID_CODEX_SKILL = """---
name: forgeunit-skillfoundry-invalid-fixture
description: Intentionally incomplete fixture.
---

# ForgeUnit SkillFoundry Invalid Fixture

## Overview
This package is ForgeUnit-boundary valid but SkillFoundry-verifier invalid.
"""


def write_fake_codex_exec_command(
    workspace_root: Path,
    *,
    skill_text: str = VALID_CODEX_SKILL,
    repaired_skill_text: str | None = None,
    write_bundle_manifest: bool = False,
    script_name: str = "fake_codex_exec.py",
) -> Path:
    """Write a deterministic command-bridge worker script into a workspace."""

    script = workspace_root / script_name
    script.write_text(
        f"""
from pathlib import Path
import json
import os
import sys

_ = sys.stdin.read()
task_dir = Path(os.environ["FORGEUNIT_TASK_DIR"])
worker_result = Path(os.environ["FORGEUNIT_WORKER_RESULT"])
unit_id = os.environ["FORGEUNIT_UNIT"]
state_file = task_dir / ".fake_adaptive_codex_attempt_count"
try:
    attempt_count = int(state_file.read_text(encoding="utf-8").strip())
except Exception:
    attempt_count = 0
state_file.write_text(str(attempt_count + 1), encoding="utf-8")
skill_text = {skill_text!r}
repaired_skill_text = {repaired_skill_text!r}
if repaired_skill_text is not None and attempt_count > 0:
    skill_text = repaired_skill_text

(task_dir / "package").mkdir(exist_ok=True)
(task_dir / "evidence").mkdir(exist_ok=True)
(task_dir / "package" / "SKILL.md").write_text(skill_text, encoding="utf-8")
bundle_ref = task_dir / "package" / "skillfoundry.bundle.json"
if {write_bundle_manifest!r}:
    bundle_ref.write_text(json.dumps({{
        "schema_version": "skillfoundry.bundle.v1",
        "bundle_id": task_dir.name,
        "bundle_type": "prompt_only",
        "entrypoint": "SKILL.md",
        "capability_surface": {{}},
        "runtime_assets": [],
        "data_assets": [],
        "references": [],
        "environment": {{}},
        "permissions": {{}},
        "verification": {{}},
        "distribution": {{}},
    }}, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
(task_dir / "evidence" / "transcript.md").write_text(
    "deterministic forgeunit skillfoundry transcript pointer\\n",
    encoding="utf-8",
)
changed_files = ["package/SKILL.md", "evidence/transcript.md", "evidence/manifest.json"]
output_artifacts = [
    {{"path": "package/SKILL.md", "kind": "codex_skill", "summary": "fixture skill package"}}
]
if {write_bundle_manifest!r}:
    changed_files.append("package/skillfoundry.bundle.json")
    output_artifacts.append({{"path": "package/skillfoundry.bundle.json", "kind": "bundle_manifest", "summary": "fixture bundle manifest"}})
(task_dir / "evidence" / "manifest.json").write_text(json.dumps({{
    "schema": "forgeunit.worker_evidence_manifest",
    "version": "0.6",
    "unit_id": unit_id,
    "status": "completed",
    "output_artifacts": output_artifacts,
    "evidence_artifacts": [
        {{"path": "evidence/transcript.md", "kind": "transcript", "summary": "fixture transcript"}}
    ],
    "changed_files": changed_files,
    "commands": [{{"command": "fake codex exec", "exit_code": 0, "summary": "fixture command passed"}}],
    "usage": None,
    "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}}, indent=2), encoding="utf-8")
worker_result.write_text(json.dumps({{
    "status": "completed",
    "output_artifacts": output_artifacts,
    "boundary_evidence": [
        {{"path": "evidence/transcript.md", "kind": "transcript", "summary": "fixture transcript"}},
        {{"path": "evidence/manifest.json", "kind": "worker_evidence_manifest", "summary": "manifest"}}
    ],
    "changed_files": changed_files,
    "usage": None,
    "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}}, indent=2), encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    return script
