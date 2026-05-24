from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from forgeunit_skillfoundry import AdaptiveGraphConfig, AdaptiveWorkUnitResult, run_adaptive_graph
from skillfoundry.adaptive_workspace import read_decision_ledger, read_observation_report
from skillfoundry.bundle import BUNDLE_MANIFEST_REF
from skillfoundry.bundle_verifier import BundleVerifier
from skillfoundry.workspace import JobWorkspace


CODE_RUNTIME_SKILL = """---
name: mini-code-runtime
description: Clean-room deterministic code runtime pilot.
---

# Mini Code Runtime

## Overview

This clean-room skill wraps a tiny local Python runtime.

## When To Use

- Use when a deterministic code runtime fixture is needed.

## When Not To Use

- Do not use for live Codexarium behavior or private local code.

## Inputs

- A short command argument.

## Outputs

- A deterministic JSON response from the local runtime.

## Workflow

1. Run the bundled Python runtime.
2. Inspect the JSON response.

## Safety

- The runtime is local, deterministic, and does not use network access.
"""


def code_runtime_worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
    if "package/SKILL.md" in contract.expected_outputs:
        workspace.resolve_path("package/SKILL.md").write_text(CODE_RUNTIME_SKILL, encoding="utf-8")
        return AdaptiveWorkUnitResult(
            produced_artifacts=["package/SKILL.md"],
            changed_refs=["package/SKILL.md"],
            worker_claims=["Wrote clean-room code runtime skill entrypoint."],
            verifier_evidence=["package/SKILL.md"],
            verification_status="passed",
        )

    runtime_ref = "package/runtime/mini_runtime.py"
    test_ref = "package/tests/test_mini_runtime.py"
    manifest_ref = BUNDLE_MANIFEST_REF
    workspace.resolve_path("package/runtime").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/tests").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path(runtime_ref).write_text(
        "import json, sys\n"
        "payload = {'runtime': 'mini-code-runtime', 'input': sys.argv[1] if len(sys.argv) > 1 else '', 'ok': True}\n"
        "print(json.dumps(payload, sort_keys=True))\n",
        encoding="utf-8",
    )
    workspace.resolve_path(test_ref).write_text(
        "def test_runtime_fixture_contract():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    workspace.resolve_path(manifest_ref).write_text(
        json.dumps(
            {
                "schema_version": "skillfoundry.bundle.v1",
                "bundle_id": "mini-code-runtime",
                "bundle_type": "code_runtime",
                "entrypoint": "SKILL.md",
                "capability_surface": {"commands": ["mini-runtime"]},
                "runtime_assets": ["runtime/mini_runtime.py", "tests/test_mini_runtime.py"],
                "data_assets": [],
                "references": [],
                "environment": {"python": ">=3.11"},
                "permissions": {"network": False},
                "verification": {"commands": ["python runtime/mini_runtime.py smoke"]},
                "distribution": {"kind": "clean_room_fixture"},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return AdaptiveWorkUnitResult(
        produced_artifacts=[manifest_ref, runtime_ref, test_ref],
        changed_refs=[manifest_ref, runtime_ref, test_ref],
        commands_run=["python package/runtime/mini_runtime.py smoke"],
        tests_run=["package/tests/test_mini_runtime.py"],
        worker_claims=["Wrote clean-room Python code runtime and manifest."],
        verifier_evidence=[manifest_ref, runtime_ref, test_ref],
        recommended_next_steps=["Run BundleVerifier and a runtime smoke command."],
        verification_status="passed",
    )


def test_code_runtime_pilot_builds_verified_clean_room_bundle(tmp_path: Path) -> None:
    config = AdaptiveGraphConfig(runs_root=tmp_path / "runs", job_id="code-runtime-pilot-001")

    result = run_adaptive_graph(config, worker=code_runtime_worker)

    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    state = result.state
    serialized_state = json.dumps(state)
    assert state["contextforge"]["adaptive_latest_iteration"] == 2
    assert state["contextforge"]["adaptive_latest_route"] == "closure"
    assert read_observation_report(workspace, 2).produced_artifacts == [
        BUNDLE_MANIFEST_REF,
        "package/runtime/mini_runtime.py",
        "package/tests/test_mini_runtime.py",
    ]
    assert [decision.decision_id for decision in read_decision_ledger(workspace).decisions] == [
        "adaptive-decision-001",
        "adaptive-decision-002",
    ]

    bundle_result = BundleVerifier().verify(workspace)
    assert bundle_result.passed is True
    manifest = json.loads(workspace.resolve_path(BUNDLE_MANIFEST_REF, must_exist=True).read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "code_runtime"
    assert manifest["runtime_assets"] == ["runtime/mini_runtime.py", "tests/test_mini_runtime.py"]

    completed = subprocess.run(
        [sys.executable, workspace.resolve_path("package/runtime/mini_runtime.py", must_exist=True), "smoke"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == {"input": "smoke", "ok": True, "runtime": "mini-code-runtime"}
    assert "Codexarium" not in serialized_state
    assert "raw_prompt" not in serialized_state
    assert "raw_transcript" not in serialized_state
