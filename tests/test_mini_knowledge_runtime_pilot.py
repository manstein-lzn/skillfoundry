from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from forgeunit_skillfoundry import AdaptiveGraphConfig, AdaptiveWorkUnitResult, run_adaptive_graph
from skillfoundry.adaptive_workspace import read_decision_ledger, read_observation_report
from skillfoundry.bundle import BUNDLE_MANIFEST_REF
from skillfoundry.bundle_verifier import BundleVerifier
from skillfoundry.schema import sha256_file
from skillfoundry.workspace import JobWorkspace


KNOWLEDGE_SKILL = """---
name: mini-knowledge-runtime
description: Synthetic knowledge runtime pilot.
---

# Mini Knowledge Runtime

## Overview

This skill queries a tiny synthetic JSONL knowledge runtime.

## When To Use

- Use when validating reference-heavy capability bundle infrastructure.

## When Not To Use

- Do not use for private EdaSkill data or semiconductor production work.

## Inputs

- A short search term.

## Outputs

- Matching synthetic knowledge records as JSON.

## Workflow

1. Query the bundled JSONL runtime knowledge base.
2. Return matching records.

## Safety

- The fixture uses only synthetic local records.
"""


def knowledge_runtime_worker(workspace: JobWorkspace, contract) -> AdaptiveWorkUnitResult:
    if "package/SKILL.md" in contract.expected_outputs:
        workspace.resolve_path("package/SKILL.md").write_text(KNOWLEDGE_SKILL, encoding="utf-8")
        return AdaptiveWorkUnitResult(
            produced_artifacts=["package/SKILL.md"],
            changed_refs=["package/SKILL.md"],
            worker_claims=["Wrote synthetic knowledge runtime skill entrypoint."],
            verifier_evidence=["package/SKILL.md"],
            verification_status="passed",
        )

    data_ref = "package/data/runtime_kb.jsonl"
    data_manifest_ref = "package/data/runtime_kb.manifest.json"
    query_script_ref = "package/scripts/query_runtime_kb.py"
    workflow_ref = "package/references/workflow.md"
    manifest_ref = BUNDLE_MANIFEST_REF
    workspace.resolve_path("package/data").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/scripts").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/references").mkdir(parents=True, exist_ok=True)
    records = [
        {"id": "layout-rule", "title": "Synthetic Layout Rule", "body": "Metal spacing must be checked."},
        {"id": "query-flow", "title": "Synthetic Query Flow", "body": "Search returns records by term."},
    ]
    workspace.resolve_path(data_ref).write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )
    workspace.resolve_path(data_manifest_ref).write_text(
        json.dumps(
            {
                "schema_version": "skillfoundry.runtime_kb_manifest.v1",
                "document_count": len(records),
                "runtime_kb_ref": "data/runtime_kb.jsonl",
                "runtime_kb_sha256": sha256_file(workspace.resolve_path(data_ref, must_exist=True)),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    workspace.resolve_path(query_script_ref).write_text(
        "import json, sys\n"
        "term = (sys.argv[1] if len(sys.argv) > 1 else '').lower()\n"
        "matches = []\n"
        "with open('package/data/runtime_kb.jsonl', encoding='utf-8') as handle:\n"
        "    for line in handle:\n"
        "        item = json.loads(line)\n"
        "        text = (item['title'] + ' ' + item['body']).lower()\n"
        "        if term in text:\n"
        "            matches.append(item)\n"
        "print(json.dumps({'matches': matches}, sort_keys=True))\n",
        encoding="utf-8",
    )
    workspace.resolve_path(workflow_ref).write_text(
        "# Synthetic Knowledge Runtime Workflow\n\n"
        "Query `package/data/runtime_kb.jsonl` through `package/scripts/query_runtime_kb.py`.\n",
        encoding="utf-8",
    )
    workspace.resolve_path(manifest_ref).write_text(
        json.dumps(
            {
                "schema_version": "skillfoundry.bundle.v1",
                "bundle_id": "mini-knowledge-runtime",
                "bundle_type": "knowledge_runtime",
                "entrypoint": "SKILL.md",
                "capability_surface": {"query": "synthetic local knowledge records"},
                "runtime_assets": ["scripts/query_runtime_kb.py"],
                "data_assets": ["data/runtime_kb.jsonl", "data/runtime_kb.manifest.json"],
                "references": ["references/workflow.md"],
                "environment": {"python": ">=3.11"},
                "permissions": {"network": False},
                "verification": {"sample_query": "layout"},
                "distribution": {"kind": "synthetic_fixture"},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return AdaptiveWorkUnitResult(
        produced_artifacts=[manifest_ref, data_ref, data_manifest_ref, query_script_ref, workflow_ref],
        changed_refs=[manifest_ref, data_ref, data_manifest_ref, query_script_ref, workflow_ref],
        commands_run=["python package/scripts/query_runtime_kb.py layout"],
        tests_run=["synthetic sample query"],
        worker_claims=["Wrote synthetic knowledge runtime bundle."],
        verifier_evidence=[manifest_ref, data_manifest_ref, query_script_ref],
        recommended_next_steps=["Run sample query against the synthetic knowledge runtime."],
        verification_status="passed",
    )


def test_mini_knowledge_runtime_pilot_builds_queryable_bundle(tmp_path: Path) -> None:
    config = AdaptiveGraphConfig(runs_root=tmp_path / "runs", job_id="knowledge-runtime-pilot-001")

    result = run_adaptive_graph(config, worker=knowledge_runtime_worker)

    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    serialized_state = json.dumps(result.state)
    assert result.state["contextforge"]["adaptive_latest_iteration"] == 2
    assert result.state["contextforge"]["adaptive_latest_route"] == "closure"
    assert "knowledge runtime" in read_observation_report(workspace, 2).worker_claims[0]
    assert read_decision_ledger(workspace).decisions[-1].chosen_option == "closure"

    bundle_result = BundleVerifier().verify(workspace)
    assert bundle_result.passed is True
    kb_manifest = json.loads(
        workspace.resolve_path("package/data/runtime_kb.manifest.json", must_exist=True).read_text(encoding="utf-8")
    )
    assert kb_manifest["document_count"] == 2
    assert kb_manifest["runtime_kb_sha256"] == sha256_file(
        workspace.resolve_path("package/data/runtime_kb.jsonl", must_exist=True)
    )

    completed = subprocess.run(
        [sys.executable, workspace.resolve_path("package/scripts/query_runtime_kb.py", must_exist=True), "layout"],
        check=True,
        capture_output=True,
        cwd=workspace.root,
        text=True,
    )
    matches = json.loads(completed.stdout)["matches"]
    assert matches[0]["id"] == "layout-rule"
    assert "Metal spacing must be checked" not in serialized_state
    assert "raw_prompt" not in serialized_state
    assert "raw_transcript" not in serialized_state
