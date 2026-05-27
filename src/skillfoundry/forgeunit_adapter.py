"""Thin SkillFoundry product adapter for ForgeUnit work-unit execution."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from contextforge import ContextKernel, ContextLedger, VerificationGate, with_computed_hash

from .acceptance import (
    ACCEPTANCE_COVERAGE_PLAN_REF,
    ACCEPTANCE_COVERAGE_RESULT_REF,
    ACCEPTANCE_CRITERIA_REF,
    AcceptanceCoverageEvaluator,
    AcceptanceCriteriaPlanner,
)
from .bundle_verifier import BUNDLE_VERIFICATION_RESULT_REF
from .contracts import (
    BUILD_NODE_CONTRACT_REF,
    CONTRACT_MANIFEST_REF,
    GOAL_CONTRACT_REF,
    VERIFICATION_GATE_REF,
    write_contextforge_contract_artifacts,
)
from .goal_runtime import (
    GOAL_RUNTIME_LEDGER_REF,
    GOAL_RUNTIME_RESULT_REF,
    GOAL_RUNTIME_STATE_REF,
    GOAL_RUNTIME_STATE_SCHEMA_VERSION,
    seed_goal_harness_context,
)
from .graph_v2 import (
    SkillFoundryV2State,
    V2Route,
    V2Stage,
    V2Status,
    build_human_review_node,
    compile_skillfoundry_v2_graph,
    route_after_verification,
    validate_v2_graph_state,
)
from .registry import DEFAULT_REGISTRY_VERSION, DuplicatePolicy, LocalSkillRegistry
from .schema import (
    ArtifactRecord,
    ExecutionReport,
    JsonValue,
    VerificationResult,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .security import validate_relative_path
from .verifier import Verifier
from .verification_bridge import CONTEXTFORGE_VERIFICATION_RESULT_REF, bridge_skillfoundry_verification_result
from .workspace import JOB_ID_RE, JobWorkspace


FORGEUNIT_ADAPTER_VERSION = "skillfoundry.forgeunit_adapter.v1"
FORGEUNIT_TASK_YAML_REF = "task.yaml"
FORGEUNIT_SUMMARY_REF = "contextforge/forgeunit_summary.json"
FORGEUNIT_BOUNDARY_VERIFICATION_REF = "contextforge/forgeunit_boundary_verification.json"
FORGEUNIT_PILOT_GRAPH_STATE_REF = "contextforge/forgeunit_pilot_graph_state.json"
FORGEUNIT_CODEX_EXEC_UNIT_ID = "execute"
FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID = "001"
FORGEUNIT_REPAIR_ATTEMPT_ID = "002"
FORGEUNIT_VERIFICATION_RESULT_REF = "verifier/verification_result.json"
FORGEUNIT_REPAIR_PACKET_REF = "contextforge/forgeunit_repair_packet.json"
FORGEUNIT_REPAIR_GRAPH_STATE_REF = "contextforge/forgeunit_repair_graph_state.json"
FORGEUNIT_REGISTRY_DECISION_REF = "registry/decision.json"
FORGEUNIT_REGISTRY_ENTRY_REF = "registry/entry.json"
FORGEUNIT_FINAL_REPORT_REF = "final_report.json"
_FRONTDESK_CONVERSATION_REF = "frontdesk/conversation.jsonl"
_FORGEUNIT_CONTEXT_GRAPH_ID = "skillfoundry-v2"
_FORGEUNIT_CONTEXT_TASK_ID = "build_skill"
_FORGEUNIT_CONTEXT_NODE_ID = "build_skill"


class ForgeUnitIntegrationError(RuntimeError):
    """Raised when the ForgeUnit product adapter cannot proceed."""


@dataclass(frozen=True)
class ForgeUnitTaskPackArtifacts:
    """Refs produced when a SkillFoundry workspace is materialized as a task pack."""

    task_pack_dir: Path
    task_yaml_ref: str
    task_yaml_hash: str


@dataclass(frozen=True)
class ForgeUnitNodeResult:
    """Refs-only summary of one ForgeUnit-backed product node invocation."""

    task_pack: ForgeUnitTaskPackArtifacts
    run_dir_ref: str
    summary_ref: str
    summary_hash: str
    dry_run_plan_ref: str | None
    run_id: str
    status: str
    route: str
    current_node: str


@dataclass(frozen=True)
class ForgeUnitBridgeResult:
    """SkillFoundry evidence refs derived from a successful ForgeUnit worker boundary."""

    attempt_id: str
    input_manifest_ref: str
    execution_report_ref: str
    transcript_ref: str
    diff_ref: str
    artifact_manifest_ref: str


def materialize_forgeunit_task_pack(
    workspace: JobWorkspace,
    *,
    adaptive_contract_ref: str | None = None,
    adaptive_worker_input_ref: str | None = None,
    unit_objective: str | None = None,
    expected_output_refs: list[str] | None = None,
    write_scope: list[str] | None = None,
) -> ForgeUnitTaskPackArtifacts:
    """Write a ForgeUnit task pack over the existing SkillFoundry job workspace."""

    workspace.check_locked_inputs()
    for relative_dir in ("package", "evidence"):
        workspace.resolve_path(relative_dir).mkdir(parents=True, exist_ok=True)

    inputs: dict[str, dict[str, str]] = {
        "skill_spec": {
            "path": "skill_spec.yaml",
            "kind": "skill_spec",
            "summary": "Frozen SkillFoundry SkillSpec.",
        },
        "verification_spec": {
            "path": "verification_spec.yaml",
            "kind": "verification_spec",
            "summary": "Frozen SkillFoundry VerificationSpec.",
        },
        "build_contract": {
            "path": "build_contract.yaml",
            "kind": "build_contract",
            "summary": "Locked SkillFoundry build contract.",
        },
        "worker_input": {
            "path": "worker_input.md",
            "kind": "worker_input",
            "summary": "Natural-language requirement summary.",
        },
    }
    if adaptive_contract_ref is not None:
        validate_relative_path(adaptive_contract_ref)
        inputs["adaptive_next_step_contract"] = {
            "path": adaptive_contract_ref,
            "kind": "adaptive_next_step_contract",
            "summary": "Current adaptive steering contract for this bounded work unit.",
        }
    if adaptive_worker_input_ref is not None:
        validate_relative_path(adaptive_worker_input_ref)
        inputs["adaptive_worker_input"] = {
            "path": adaptive_worker_input_ref,
            "kind": "adaptive_worker_input",
            "summary": "Human-readable adaptive work-unit instructions derived from the current contract.",
        }

    execute_objective = unit_objective or (
        "Build a Codex Skill package from the frozen SkillFoundry inputs. "
        "Write package/SKILL.md and boundary evidence before reporting completion."
    )
    execute_expected_outputs = [
        {"path": ref, "kind": "adaptive_expected_output" if ref.startswith("adaptive/") else "codex_skill"}
        for ref in (expected_output_refs or ["package/SKILL.md"])
    ]
    execute_write_scope = write_scope or ["package", "evidence"]
    task_payload = {
        "id": f"skillfoundry_{workspace.job_id}_forgeunit",
        "version": "skillfoundry.forgeunit_task_pack.v1",
        "graph": "plan_execute_verify",
        "max_repair_attempts": 1,
        "inputs": inputs,
        "units": {
            "plan": {
                "objective": "Create a concise build plan from the frozen SkillFoundry inputs.",
                "worker": {"kind": "fake"},
                "expected_outputs": [{"path": "attempts/forgeunit_plan.md", "kind": "plan"}],
                "verify": [{"type": "file_exists", "path": "attempts/forgeunit_plan.md"}],
            },
            FORGEUNIT_CODEX_EXEC_UNIT_ID: {
                "objective": execute_objective,
                "worker": {
                    "kind": "codex_boundary",
                    "write_scope": execute_write_scope,
                    "required_boundary_evidence": ["evidence/transcript.md", "evidence/manifest.json"],
                },
                "expected_outputs": execute_expected_outputs,
                "verify": [
                    {"type": "file_exists", "path": "package/SKILL.md"},
                    {"type": "worker_evidence_manifest", "path": "evidence/manifest.json"},
                ],
            },
            "verify": {
                "objective": "Verify the SkillFoundry skill package and worker evidence refs.",
                "worker": {"kind": "fake", "produce_outputs": False},
                "verify": [
                    {"type": "file_exists", "path": "package/SKILL.md"},
                    {"type": "worker_evidence_manifest", "path": "evidence/manifest.json"},
                ],
            },
        },
    }
    task_yaml = workspace.resolve_path(FORGEUNIT_TASK_YAML_REF)
    task_yaml.write_text(yaml.safe_dump(task_payload, sort_keys=False), encoding="utf-8")
    _validate_with_forgeunit(workspace.root)
    return ForgeUnitTaskPackArtifacts(
        task_pack_dir=workspace.root,
        task_yaml_ref=FORGEUNIT_TASK_YAML_REF,
        task_yaml_hash=sha256_file(task_yaml),
    )


def run_forgeunit_codex_exec_node(
    workspace: JobWorkspace,
    *,
    dry_run: bool = True,
    command: str | None = None,
    unit_id: str = FORGEUNIT_CODEX_EXEC_UNIT_ID,
    adaptive_contract_ref: str | None = None,
    adaptive_worker_input_ref: str | None = None,
    unit_objective: str | None = None,
    expected_output_refs: list[str] | None = None,
    write_scope: list[str] | None = None,
) -> ForgeUnitNodeResult:
    """Invoke ForgeUnit's public LangGraph adapter for one SkillFoundry workspace."""

    task_pack = materialize_forgeunit_task_pack(
        workspace,
        adaptive_contract_ref=adaptive_contract_ref,
        adaptive_worker_input_ref=adaptive_worker_input_ref,
        unit_objective=unit_objective,
        expected_output_refs=expected_output_refs,
        write_scope=write_scope,
    )
    forgeunit_node = _load_forgeunit_node()(
        "codex_exec",
        unit_id=unit_id,
        dry_run=dry_run,
        command=command,
    )
    node_state = forgeunit_node({"task_pack": str(task_pack.task_pack_dir)})
    forgeunit_summary = _refs_only_forgeunit_summary(node_state)
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    summary_path = workspace.resolve_path(FORGEUNIT_SUMMARY_REF)
    _write_json(summary_path, forgeunit_summary)

    run_dir = Path(str(node_state["run_dir"]))
    run_dir_ref = _relative_ref(workspace, run_dir)
    adapter_result = forgeunit_summary.get("adapter_result", {})
    dry_run_plan_ref = None
    if isinstance(adapter_result, Mapping) and adapter_result.get("plan_path"):
        dry_run_plan_ref = _relative_ref(workspace, Path(str(adapter_result["plan_path"])))

    return ForgeUnitNodeResult(
        task_pack=task_pack,
        run_dir_ref=run_dir_ref,
        summary_ref=FORGEUNIT_SUMMARY_REF,
        summary_hash=sha256_file(summary_path),
        dry_run_plan_ref=dry_run_plan_ref,
        run_id=str(forgeunit_summary.get("run_id") or run_dir.name),
        status=str(forgeunit_summary.get("status") or ""),
        route=str(forgeunit_summary.get("route") or ""),
        current_node=str(forgeunit_summary.get("current_node") or ""),
    )


def build_forgeunit_codex_exec_node(
    runs_root: str | Path,
    *,
    dry_run: bool = True,
    command: str | None = None,
    unit_id: str = FORGEUNIT_CODEX_EXEC_UNIT_ID,
) -> Any:
    """Return a SkillFoundry v2 node backed by ForgeUnit's Codex exec adapter."""

    runs_path = Path(runs_root)

    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        validate_v2_graph_state(state)
        job_id = _job_id(state)
        workspace = JobWorkspace(root=runs_path / job_id, job_id=job_id)
        result = run_forgeunit_codex_exec_node(
            workspace,
            dry_run=dry_run,
            command=command,
            unit_id=unit_id,
        )

        refs = dict(state.get("refs", {}))
        refs.update(
            {
                "forgeunit_task_yaml": result.task_pack.task_yaml_ref,
                "forgeunit_run": result.run_dir_ref,
                "forgeunit_summary": result.summary_ref,
            }
        )
        if result.dry_run_plan_ref:
            refs["forgeunit_codex_exec_plan"] = result.dry_run_plan_ref

        hashes = dict(state.get("hashes", {}))
        hashes.update(
            {
                "forgeunit_task_yaml": result.task_pack.task_yaml_hash,
                "forgeunit_summary": result.summary_hash,
            }
        )

        contextforge = dict(state.get("contextforge", {}))
        contextforge.update(
            {
                "forgeunit_adapter_version": FORGEUNIT_ADAPTER_VERSION,
                "forgeunit_run_id": result.run_id,
                "forgeunit_status": result.status,
                "forgeunit_route": result.route,
                "forgeunit_current_node": result.current_node,
                "forgeunit_codex_exec_dry_run": dry_run,
                "forgeunit_worker_self_report_is_not_acceptance": True,
            }
        )

        next_state: SkillFoundryV2State = dict(state)
        next_state.update(
            {
                "schema_version": str(state.get("schema_version") or "skillfoundry.graph_v2_state.v1"),
                "job_id": job_id,
                "stage": V2Stage.BUILD_GOAL_NODE.value,
                "status": V2Status.BUILD_RECORDED.value,
                "attempt_count": max(int(state.get("attempt_count", 0)), 1),
                "attempt_limit": int(state.get("attempt_limit", 1)),
                "refs": refs,
                "hashes": hashes,
                "contextforge": contextforge,
                "human_review_required": False,
                "next_route": V2Route.CONTINUE.value,
            }
        )
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def build_forgeunit_boundary_verification_node(
    runs_root: str | Path,
    *,
    created_at: str | None = None,
) -> Any:
    """Return a verifier node that truthfully stops ForgeUnit boundary dry-runs."""

    runs_path = Path(runs_root)

    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        validate_v2_graph_state(state)
        job_id = _job_id(state)
        workspace = JobWorkspace(root=runs_path / job_id, job_id=job_id)
        workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)

        reason_code = _boundary_reason_code(state)
        verification_status = "human_acceptance_required"
        boundary_status = (
            "dry_run_plan_ready"
            if reason_code == "forgeunit_codex_exec_dry_run_boundary_pending"
            else "boundary_pending"
        )
        payload = _boundary_verification_payload(
            job_id=job_id,
            state=state,
            verification_status=verification_status,
            boundary_status=boundary_status,
            reason_code=reason_code,
            created_at=created_at or utc_now(),
        )
        boundary_path = workspace.resolve_path(FORGEUNIT_BOUNDARY_VERIFICATION_REF)
        _write_json(boundary_path, payload)

        refs = dict(state.get("refs", {}))
        refs["forgeunit_boundary_verification"] = FORGEUNIT_BOUNDARY_VERIFICATION_REF
        hashes = dict(state.get("hashes", {}))
        hashes["forgeunit_boundary_verification"] = sha256_file(boundary_path)
        contextforge = dict(state.get("contextforge", {}))
        contextforge.update(
            {
                "last_verification_result_id": str(payload["verification_result_id"]),
                "last_verification_status": verification_status,
                "forgeunit_boundary_status": boundary_status,
                "forgeunit_boundary_reason_code": reason_code,
                "forgeunit_boundary_verification_ref": FORGEUNIT_BOUNDARY_VERIFICATION_REF,
                "worker_self_report_is_not_acceptance": True,
            }
        )
        next_state: SkillFoundryV2State = dict(state)
        next_state.update(
            {
                "stage": V2Stage.VERIFY.value,
                "status": V2Status.HUMAN_REVIEW_REQUIRED.value,
                "refs": refs,
                "hashes": hashes,
                "contextforge": contextforge,
                "human_review_required": True,
                "next_route": V2Route.HUMAN_REVIEW.value,
            }
        )
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def bridge_forgeunit_success_to_skillfoundry_attempt(
    workspace: JobWorkspace,
    state: Mapping[str, Any],
    *,
    attempt_id: str = FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID,
    created_at: str | None = None,
) -> ForgeUnitBridgeResult:
    """Materialize a successful ForgeUnit command bridge as SkillFoundry attempt evidence.

    This does not trust the worker result as acceptance. It only creates the
    evidence files that SkillFoundry's independent Verifier and Registry already
    know how to validate.
    """

    if not attempt_id.isdecimal():
        raise ForgeUnitIntegrationError("attempt_id must be decimal for SkillFoundry registry compatibility")
    workspace.check_locked_inputs()
    summary = _read_json_object(workspace.resolve_path(FORGEUNIT_SUMMARY_REF, must_exist=True), "ForgeUnit summary")
    _require_forgeunit_command_success(summary)

    adapter_result = summary.get("adapter_result")
    if not isinstance(adapter_result, Mapping):
        raise ForgeUnitIntegrationError("ForgeUnit summary is missing adapter_result")
    worker_result_value = adapter_result.get("worker_result")
    if not isinstance(worker_result_value, str) or not worker_result_value.strip():
        raise ForgeUnitIntegrationError("ForgeUnit adapter_result is missing worker_result ref")

    worker_result_path = Path(worker_result_value)
    if not worker_result_path.is_absolute():
        worker_result_path = workspace.root / worker_result_path
    worker_result_ref = _relative_ref(workspace, worker_result_path)
    worker_result = _read_json_object(
        workspace.resolve_path(worker_result_ref, must_exist=True),
        "ForgeUnit worker_result",
    )
    if worker_result.get("status") != "completed":
        raise ForgeUnitIntegrationError(
            f"ForgeUnit worker_result status must be completed, got {worker_result.get('status')!r}"
        )

    expected_refs = [
        "package/SKILL.md",
        "evidence/transcript.md",
        "evidence/manifest.json",
    ]
    for ref in expected_refs:
        workspace.resolve_path(ref, must_exist=True)

    refs = state.get("refs") if isinstance(state.get("refs"), Mapping) else {}
    contextforge = state.get("contextforge") if isinstance(state.get("contextforge"), Mapping) else {}
    assert isinstance(refs, Mapping)
    assert isinstance(contextforge, Mapping)
    run_id = str(contextforge.get("forgeunit_run_id") or summary.get("run_id") or "unknown-run")
    invocation_id = f"{workspace.job_id}:forgeunit-command-bridge:{attempt_id}:{run_id}"
    timestamp = created_at or utc_now()
    attempt_dir = workspace.resolve_path(f"attempts/{attempt_id}")
    attempt_dir.mkdir(parents=True, exist_ok=True)

    input_manifest_ref = f"attempts/{attempt_id}/input_manifest.json"
    execution_report_ref = f"attempts/{attempt_id}/execution_report.json"
    transcript_ref = f"attempts/{attempt_id}/worker_transcript.log"
    diff_ref = f"attempts/{attempt_id}/output_diff.patch"

    input_manifest = {
        "schema_version": "skillfoundry.forgeunit_worker_input_manifest.v1",
        "invocation_id": invocation_id,
        "job_id": workspace.job_id,
        "attempt_id": attempt_id,
        "worker_type": "forgeunit.codex_exec.command_bridge",
        "adapter_version": FORGEUNIT_ADAPTER_VERSION,
        "build_contract_ref": "build_contract.yaml",
        "worker_input_ref": "worker_input.md",
        "task_yaml_ref": FORGEUNIT_TASK_YAML_REF,
        "forgeunit_summary_ref": FORGEUNIT_SUMMARY_REF,
        "forgeunit_run_ref": str(refs.get("forgeunit_run") or ""),
        "forgeunit_worker_result_ref": worker_result_ref,
        "raw_prompt_included": False,
        "raw_transcript_included": False,
        "package_body_included": False,
    }
    _write_json(workspace.resolve_path(input_manifest_ref), input_manifest)

    transcript_text = "\n".join(
        [
            "ForgeUnit command bridge execution transcript pointer.",
            "",
            f"job_id: {workspace.job_id}",
            f"attempt_id: {attempt_id}",
            f"forgeunit_run_id: {run_id}",
            f"forgeunit_summary_ref: {FORGEUNIT_SUMMARY_REF}",
            f"forgeunit_worker_result_ref: {worker_result_ref}",
            "worker_boundary_transcript_ref: evidence/transcript.md",
            "",
            "Raw prompt, raw model transcript, and package body are intentionally excluded from graph state.",
            "",
        ]
    )
    workspace.resolve_path(transcript_ref).write_text(transcript_text, encoding="utf-8")
    workspace.resolve_path(diff_ref).write_text(
        "\n".join(
            [
                "# ForgeUnit command bridge output",
                "",
                "Package and evidence artifacts were produced by the external command bridge.",
                "No inline package diff is stored in graph state.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    artifact_refs = _dedupe_strings(
        [
            *_artifact_paths(worker_result.get("output_artifacts")),
            *_artifact_paths(worker_result.get("boundary_evidence")),
            *_string_list(worker_result.get("changed_files")),
            *expected_refs,
            "evidence/manifest.json",
            worker_result_ref,
        ]
    )
    report = ExecutionReport(
        report_id=f"{workspace.job_id}:forgeunit-command-bridge:{attempt_id}",
        invocation_id=invocation_id,
        job_id=workspace.job_id,
        attempt_id=attempt_id,
        status="completed",
        started_at=timestamp,
        finished_at=timestamp,
        duration_ms=0,
        exit_status="success",
        summary="ForgeUnit command bridge completed; SkillFoundry verifier remains the acceptance gate.",
        artifacts=artifact_refs,
        failures=[],
    )
    report.write_json_file(workspace.resolve_path(execution_report_ref))

    _upsert_manifest_records(
        workspace,
        _dedupe_strings(
            [
                FORGEUNIT_TASK_YAML_REF,
                FORGEUNIT_SUMMARY_REF,
                *expected_refs,
                worker_result_ref,
                input_manifest_ref,
                execution_report_ref,
                transcript_ref,
                diff_ref,
            ]
        ),
        created_by="skillfoundry.forgeunit_adapter",
    )
    return ForgeUnitBridgeResult(
        attempt_id=attempt_id,
        input_manifest_ref=input_manifest_ref,
        execution_report_ref=execution_report_ref,
        transcript_ref=transcript_ref,
        diff_ref=diff_ref,
        artifact_manifest_ref="artifact_manifest.json",
    )


def write_forgeunit_repair_packet(
    workspace: JobWorkspace,
    state: Mapping[str, Any],
    verification_result: VerificationResult,
    *,
    failed_attempt_id: str = FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID,
    repair_attempt_id: str = FORGEUNIT_REPAIR_ATTEMPT_ID,
    failed_summary_ref: str | None = None,
    created_at: str | None = None,
) -> str:
    """Write a refs-only packet describing why the ForgeUnit boundary must repair."""

    if not failed_attempt_id.isdecimal() or not repair_attempt_id.isdecimal():
        raise ForgeUnitIntegrationError("repair packet attempt ids must be decimal")
    failed_summary = failed_summary_ref or _forgeunit_summary_archive_ref(failed_attempt_id)
    failed_check_names = _failed_primary_check_names(verification_result)
    payload = {
        "schema_version": "skillfoundry.forgeunit_repair_packet.v1",
        "job_id": workspace.job_id,
        "failed_attempt_id": failed_attempt_id,
        "repair_attempt_id": repair_attempt_id,
        "created_at": created_at or utc_now(),
        "reason_code": "skillfoundry_verifier_failed",
        "verification_result_id": verification_result.result_id,
        "verification_result_ref": _verification_archive_ref(failed_attempt_id),
        "failed_execution_report_ref": f"attempts/{failed_attempt_id}/execution_report.json",
        "failed_forgeunit_summary_ref": failed_summary,
        "latest_forgeunit_summary_ref": FORGEUNIT_SUMMARY_REF,
        "failure_count": len(verification_result.failures),
        "failed_check_names": failed_check_names,
        "repair_boundary": {
            "worker_type": "forgeunit.codex_exec.command_bridge",
            "next_attempt_id": repair_attempt_id,
            "worker_self_report_is_not_acceptance": True,
        },
        "trust_boundaries": {
            "worker_self_report_is_not_acceptance": True,
            "raw_prompt_included": False,
            "raw_transcript_included": False,
            "package_body_included": False,
            "raw_worker_input_included": False,
            "registry_promotion_allowed": False,
        },
    }
    compatible = ensure_json_compatible(payload)
    if not isinstance(compatible, dict):
        raise ForgeUnitIntegrationError("repair packet payload must be a JSON object")
    _write_json(workspace.resolve_path(FORGEUNIT_REPAIR_PACKET_REF), compatible)
    _upsert_manifest_records(
        workspace,
        [FORGEUNIT_REPAIR_PACKET_REF],
        created_by="skillfoundry.forgeunit_adapter",
    )
    return FORGEUNIT_REPAIR_PACKET_REF


def build_forgeunit_skillfoundry_verification_node(
    runs_root: str | Path,
    *,
    created_at: str | None = None,
) -> Any:
    """Return a verifier node that bridges successful ForgeUnit output into SkillFoundry gates."""

    runs_path = Path(runs_root)
    dry_run_boundary_node = build_forgeunit_boundary_verification_node(runs_path, created_at=created_at)

    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        validate_v2_graph_state(state)
        refs = state.get("refs") if isinstance(state.get("refs"), Mapping) else {}
        contextforge = state.get("contextforge") if isinstance(state.get("contextforge"), Mapping) else {}
        assert isinstance(refs, Mapping)
        assert isinstance(contextforge, Mapping)
        if contextforge.get("forgeunit_codex_exec_dry_run") is True or refs.get("forgeunit_codex_exec_plan"):
            return dry_run_boundary_node(state)

        job_id = _job_id(state)
        workspace = JobWorkspace(root=runs_path / job_id, job_id=job_id)
        return _bridge_and_verify_forgeunit_attempt_state(
            workspace,
            state,
            attempt_id=FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID,
            created_at=created_at,
        )

    return _node


def build_forgeunit_registry_gate_node(
    runs_root: str | Path,
    *,
    registry_path: str | Path,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
) -> Any:
    """Return a registry gate for ForgeUnit command-bridge verifier output."""

    runs_path = Path(runs_root)
    registry_file = Path(registry_path)

    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        validate_v2_graph_state(state)
        job_id = _job_id(state)
        workspace = JobWorkspace(root=runs_path / job_id, job_id=job_id)
        state = _maybe_write_acceptance_coverage(workspace, state)
        timestamp = created_at or utc_now()
        try:
            verification_gate = VerificationGate.from_dict(
                json.loads(workspace.resolve_path(VERIFICATION_GATE_REF, must_exist=True).read_text(encoding="utf-8"))
            )
        except Exception:
            verification_gate = write_contextforge_contract_artifacts(workspace, created_at=timestamp).verification_gate
        acceptance_coverage_required = _workspace_has_acceptance_criteria(workspace)
        if not acceptance_coverage_required:
            verification_gate = _verification_gate_without_acceptance_coverage(verification_gate)
            _write_json(workspace.resolve_path(VERIFICATION_GATE_REF), verification_gate.to_dict())
        contextforge_verification_result = bridge_skillfoundry_verification_result(
            workspace,
            verification_gate,
            goal_run_id=f"forgeunit-command-bridge-{job_id}",
            worker_id="forgeunit-command-bridge",
            expected_gate_hash=verification_gate.gate_hash,
            require_acceptance_coverage=acceptance_coverage_required,
            created_at=timestamp,
        )
        if contextforge_verification_result.status != "passed":
            raise ForgeUnitIntegrationError(
                "ForgeUnit registry gate requires passed ContextForge verification bridge"
            )
        contextforge = dict(state.get("contextforge", {}))
        if contextforge.get("last_verification_status") != "passed":
            raise ForgeUnitIntegrationError("ForgeUnit registry gate requires passed SkillFoundry verification")

        entry = LocalSkillRegistry(
            registry_file,
            duplicate_policy=DuplicatePolicy.IDEMPOTENT,
        ).add_verified(
            workspace,
            version=version,
            review_status="forgeunit_command_bridge_verified",
            require_contextforge_verification=True,
        )
        verification_report = LocalSkillRegistry(registry_file).verify_entry(entry)
        if not verification_report.valid:
            raise ForgeUnitIntegrationError(
                "ForgeUnit registry gate failed: " + "; ".join(verification_report.failures)
            )

        from .final_report import emit_final_report

        final_report = emit_final_report(
            workspace.root,
            final_status=V2Status.REGISTERED.value,
            registry_path=registry_file,
            registry_entry=entry,
        )

        entry_hash = sha256_json(entry.to_dict())
        entry_payload = {
            "schema_version": "skillfoundry.forgeunit.registry_entry_snapshot.v1",
            "job_id": job_id,
            "registry_path": registry_file.as_posix(),
            "entry_hash": entry_hash,
            "entry": entry.to_dict(),
            "verification_report": verification_report.to_dict(),
            "created_at": timestamp,
        }
        decision_payload = {
            "schema_version": "skillfoundry.forgeunit.registry_decision.v1",
            "job_id": job_id,
            "passed": True,
            "decision": "registered",
            "registry_path": registry_file.as_posix(),
            "skill_id": entry.skill_id,
            "version": entry.version,
            "entry_ref": FORGEUNIT_REGISTRY_ENTRY_REF,
            "entry_hash": entry_hash,
            "verification_result_ref": FORGEUNIT_VERIFICATION_RESULT_REF,
            "contextforge_verification_result_ref": CONTEXTFORGE_VERIFICATION_RESULT_REF,
            "final_report_ref": FORGEUNIT_FINAL_REPORT_REF,
            "created_at": timestamp,
        }
        workspace.resolve_path("registry").mkdir(parents=True, exist_ok=True)
        _write_json(workspace.resolve_path(FORGEUNIT_REGISTRY_ENTRY_REF), entry_payload)
        _write_json(workspace.resolve_path(FORGEUNIT_REGISTRY_DECISION_REF), decision_payload)

        refs = dict(state.get("refs", {}))
        refs.update(
            {
                "final_report": FORGEUNIT_FINAL_REPORT_REF,
                "contextforge_verification_result": CONTEXTFORGE_VERIFICATION_RESULT_REF,
                "registry_decision": FORGEUNIT_REGISTRY_DECISION_REF,
                "registry_entry": FORGEUNIT_REGISTRY_ENTRY_REF,
            }
        )
        hashes = dict(state.get("hashes", {}))
        hashes.update(
            {
                "final_report": sha256_file(workspace.resolve_path(FORGEUNIT_FINAL_REPORT_REF, must_exist=True)),
                "contextforge_verification_result": sha256_file(
                    workspace.resolve_path(CONTEXTFORGE_VERIFICATION_RESULT_REF, must_exist=True)
                ),
                "registry_decision": sha256_file(
                    workspace.resolve_path(FORGEUNIT_REGISTRY_DECISION_REF, must_exist=True)
                ),
                "registry_entry": sha256_file(workspace.resolve_path(FORGEUNIT_REGISTRY_ENTRY_REF, must_exist=True)),
            }
        )
        contextforge.update(
            {
                "registry_approved": True,
                "registry_skill_id": entry.skill_id,
                "registry_version": entry.version,
                "registry_verification_report_valid": True,
                "contextforge_verification_result_id": contextforge_verification_result.verification_result_id,
                "contextforge_verification_status": contextforge_verification_result.status,
                "final_report_status": str(final_report.get("final_status") or final_report.get("status") or ""),
            }
        )
        next_state: SkillFoundryV2State = dict(state)
        next_state.update(
            {
                "stage": V2Stage.REGISTRY_GATE.value,
                "status": V2Status.REGISTERED.value,
                "refs": refs,
                "hashes": hashes,
                "contextforge": contextforge,
                "human_review_required": False,
                "next_route": V2Route.CONTINUE.value,
            }
        )
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def _workspace_has_acceptance_criteria(workspace: JobWorkspace) -> bool:
    try:
        workspace.resolve_path(ACCEPTANCE_CRITERIA_REF, must_exist=True)
    except Exception:
        return False
    return True


def _verification_gate_without_acceptance_coverage(gate: VerificationGate) -> VerificationGate:
    payload = gate.to_dict()
    payload["required_evidence"] = [
        ref for ref in payload.get("required_evidence", []) if ref != ACCEPTANCE_COVERAGE_RESULT_REF
    ]
    payload["validators"] = [
        validator
        for validator in payload.get("validators", [])
        if not (
            isinstance(validator, Mapping)
            and isinstance(validator.get("params"), Mapping)
            and validator["params"].get("path") == ACCEPTANCE_COVERAGE_RESULT_REF
        )
    ]
    payload["gate_hash"] = ""
    return VerificationGate.from_dict(with_computed_hash(payload, "gate_hash"))


def _maybe_write_acceptance_coverage(
    workspace: JobWorkspace,
    state: SkillFoundryV2State,
) -> SkillFoundryV2State:
    try:
        workspace.resolve_path(ACCEPTANCE_CRITERIA_REF, must_exist=True)
    except Exception:
        return state

    try:
        plan = AcceptanceCriteriaPlanner().plan(workspace)
        result = AcceptanceCoverageEvaluator().evaluate(workspace, plan=plan)
    except Exception as exc:
        raise ForgeUnitIntegrationError(f"acceptance coverage evaluation failed: {exc}") from exc

    if result.passed is not True:
        raise ForgeUnitIntegrationError("acceptance coverage evaluation did not pass")
    _upsert_manifest_records(
        workspace,
        [ACCEPTANCE_COVERAGE_PLAN_REF, ACCEPTANCE_COVERAGE_RESULT_REF],
        created_by="skillfoundry.forgeunit_adapter",
    )

    refs = dict(state.get("refs", {}))
    refs.update(
        {
            "acceptance_coverage_plan": ACCEPTANCE_COVERAGE_PLAN_REF,
            "acceptance_coverage_result": ACCEPTANCE_COVERAGE_RESULT_REF,
        }
    )
    hashes = dict(state.get("hashes", {}))
    hashes.update(
        {
            "acceptance_coverage_plan": sha256_file(
                workspace.resolve_path(ACCEPTANCE_COVERAGE_PLAN_REF, must_exist=True)
            ),
            "acceptance_coverage_result": sha256_file(
                workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF, must_exist=True)
            ),
        }
    )
    contextforge = dict(state.get("contextforge", {}))
    contextforge.update(
        {
            "acceptance_coverage_passed": True,
            "acceptance_coverage_result_ref": ACCEPTANCE_COVERAGE_RESULT_REF,
        }
    )
    next_state: SkillFoundryV2State = dict(state)
    next_state.update({"refs": refs, "hashes": hashes, "contextforge": contextforge})
    validate_v2_graph_state(next_state)
    return next_state


def compile_forgeunit_pilot_graph(
    runs_root: str | Path,
    *,
    dry_run: bool = True,
    command: str | None = None,
    unit_id: str = FORGEUNIT_CODEX_EXEC_UNIT_ID,
    created_at: str | None = None,
) -> Any:
    """Compile the dedicated ForgeUnit-backed SkillFoundry pilot graph."""

    return compile_skillfoundry_v2_graph(
        build_node_callable=build_forgeunit_codex_exec_node(
            runs_root,
            dry_run=dry_run,
            command=command,
            unit_id=unit_id,
        ),
        verify_node_callable=build_forgeunit_boundary_verification_node(
            runs_root,
            created_at=created_at,
        ),
        human_review_node_callable=build_human_review_node(
            runs_root,
            created_at=created_at,
        ),
    )


def compile_forgeunit_command_bridge_pilot_graph(
    runs_root: str | Path,
    *,
    registry_path: str | Path,
    command: str,
    unit_id: str = FORGEUNIT_CODEX_EXEC_UNIT_ID,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
) -> Any:
    """Compile the offline ForgeUnit command-bridge pilot graph."""

    return compile_skillfoundry_v2_graph(
        build_node_callable=build_forgeunit_codex_exec_node(
            runs_root,
            dry_run=False,
            command=command,
            unit_id=unit_id,
        ),
        verify_node_callable=build_forgeunit_skillfoundry_verification_node(
            runs_root,
            created_at=created_at,
        ),
        registry_gate_callable=build_forgeunit_registry_gate_node(
            runs_root,
            registry_path=registry_path,
            version=version,
            created_at=created_at,
        ),
        human_review_node_callable=build_human_review_node(
            runs_root,
            created_at=created_at,
        ),
    )


def run_forgeunit_pilot_graph(
    runs_root: str | Path,
    job_id: str,
    *,
    attempt_limit: int = 2,
    dry_run: bool = True,
    command: str | None = None,
    unit_id: str = FORGEUNIT_CODEX_EXEC_UNIT_ID,
    created_at: str | None = None,
) -> SkillFoundryV2State:
    """Run the dedicated ForgeUnit-backed pilot graph and persist refs-only state."""

    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise ForgeUnitIntegrationError("job_id must be a safe SkillFoundry job id")
    runs_path = Path(runs_root)
    graph = compile_forgeunit_pilot_graph(
        runs_path,
        dry_run=dry_run,
        command=command,
        unit_id=unit_id,
        created_at=created_at,
    )
    result = graph.invoke({"job_id": job_id, "attempt_limit": attempt_limit})
    validate_v2_graph_state(result)
    workspace = JobWorkspace(root=runs_path / job_id, job_id=job_id)
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    state_path = workspace.resolve_path(FORGEUNIT_PILOT_GRAPH_STATE_REF)
    _write_json(state_path, result)
    return result


def run_forgeunit_command_bridge_pilot_graph(
    runs_root: str | Path,
    job_id: str,
    *,
    registry_path: str | Path,
    command: str,
    attempt_limit: int = 2,
    unit_id: str = FORGEUNIT_CODEX_EXEC_UNIT_ID,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
) -> SkillFoundryV2State:
    """Run the offline ForgeUnit command-bridge pilot through verifier and registry gates."""

    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise ForgeUnitIntegrationError("job_id must be a safe SkillFoundry job id")
    if not isinstance(command, str) or not command.strip():
        raise ForgeUnitIntegrationError("command must be a non-empty explicit command bridge")
    runs_path = Path(runs_root)
    graph = compile_forgeunit_command_bridge_pilot_graph(
        runs_path,
        registry_path=registry_path,
        command=command,
        unit_id=unit_id,
        version=version,
        created_at=created_at,
    )
    result = graph.invoke({"job_id": job_id, "attempt_limit": attempt_limit})
    validate_v2_graph_state(result)
    workspace = JobWorkspace(root=runs_path / job_id, job_id=job_id)
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    state_path = workspace.resolve_path(FORGEUNIT_PILOT_GRAPH_STATE_REF)
    _write_json(state_path, result)
    return result


def run_forgeunit_repair_pilot_graph(
    runs_root: str | Path,
    job_id: str,
    *,
    registry_path: str | Path,
    build_command: str,
    repair_command: str,
    attempt_limit: int = 2,
    unit_id: str = FORGEUNIT_CODEX_EXEC_UNIT_ID,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
) -> SkillFoundryV2State:
    """Run the minimal offline ForgeUnit repair pilot through verifier and registry gates."""

    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise ForgeUnitIntegrationError("job_id must be a safe SkillFoundry job id")
    if attempt_limit < 2:
        raise ForgeUnitIntegrationError("repair pilot requires attempt_limit >= 2")
    if not isinstance(build_command, str) or not build_command.strip():
        raise ForgeUnitIntegrationError("build_command must be a non-empty explicit command bridge")
    if not isinstance(repair_command, str) or not repair_command.strip():
        raise ForgeUnitIntegrationError("repair_command must be a non-empty explicit command bridge")

    runs_path = Path(runs_root)
    workspace = JobWorkspace(root=runs_path / job_id, job_id=job_id)
    build_node = build_forgeunit_codex_exec_node(
        runs_path,
        dry_run=False,
        command=build_command,
        unit_id=unit_id,
    )
    repair_node = build_forgeunit_codex_exec_node(
        runs_path,
        dry_run=False,
        command=repair_command,
        unit_id=unit_id,
    )

    first_build_state = build_node({"job_id": job_id, "attempt_limit": attempt_limit})
    first_verified_state = _bridge_and_verify_forgeunit_attempt_state(
        workspace,
        first_build_state,
        attempt_id=FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID,
        created_at=created_at,
    )
    first_summary_ref = _archive_current_forgeunit_summary(
        workspace,
        FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID,
    )
    first_verification_ref, first_verification = _archive_current_verification_result(
        workspace,
        FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID,
    )
    if first_verification.passed:
        initial_success_state = _with_initial_repair_pilot_success_state(
            workspace,
            first_verified_state,
            first_summary_ref=first_summary_ref,
            first_verification_ref=first_verification_ref,
        )
        registry_state = build_forgeunit_registry_gate_node(
            runs_path,
            registry_path=registry_path,
            version=version,
            created_at=created_at,
        )(initial_success_state)

        refs = dict(registry_state.get("refs", {}))
        refs["forgeunit_repair_graph_state"] = FORGEUNIT_REPAIR_GRAPH_STATE_REF
        final_state: SkillFoundryV2State = dict(registry_state)
        final_state.update(
            {
                "stage": V2Stage.EMIT_REPORT.value,
                "status": V2Status.REPORT_EMITTED.value,
                "refs": refs,
                "human_review_required": False,
                "next_route": V2Route.CONTINUE.value,
            }
        )
        validate_v2_graph_state(final_state)
        workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
        _write_json(workspace.resolve_path(FORGEUNIT_REPAIR_GRAPH_STATE_REF), final_state)
        return final_state

    repair_packet_ref = write_forgeunit_repair_packet(
        workspace,
        first_verified_state,
        first_verification,
        failed_attempt_id=FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID,
        repair_attempt_id=FORGEUNIT_REPAIR_ATTEMPT_ID,
        failed_summary_ref=first_summary_ref,
        created_at=created_at,
    )
    repair_ready_state = _with_repair_packet_state(
        workspace,
        first_verified_state,
        repair_packet_ref=repair_packet_ref,
        first_summary_ref=first_summary_ref,
        first_verification_ref=first_verification_ref,
    )

    repair_input_state: SkillFoundryV2State = dict(repair_ready_state)
    repair_input_state["attempt_count"] = int(FORGEUNIT_REPAIR_ATTEMPT_ID)
    second_build_state = repair_node(repair_input_state)
    second_verified_state = _bridge_and_verify_forgeunit_attempt_state(
        workspace,
        second_build_state,
        attempt_id=FORGEUNIT_REPAIR_ATTEMPT_ID,
        created_at=created_at,
    )
    second_summary_ref = _archive_current_forgeunit_summary(workspace, FORGEUNIT_REPAIR_ATTEMPT_ID)
    second_verification_ref, second_verification = _archive_current_verification_result(
        workspace,
        FORGEUNIT_REPAIR_ATTEMPT_ID,
    )
    if not second_verification.passed:
        raise ForgeUnitIntegrationError("repair pilot expected attempt 002 verifier success")

    repaired_state = _with_repair_success_state(
        workspace,
        second_verified_state,
        second_summary_ref=second_summary_ref,
        second_verification_ref=second_verification_ref,
    )
    registry_state = build_forgeunit_registry_gate_node(
        runs_path,
        registry_path=registry_path,
        version=version,
        created_at=created_at,
    )(repaired_state)

    refs = dict(registry_state.get("refs", {}))
    refs["forgeunit_repair_graph_state"] = FORGEUNIT_REPAIR_GRAPH_STATE_REF
    final_state: SkillFoundryV2State = dict(registry_state)
    final_state.update(
        {
            "stage": V2Stage.EMIT_REPORT.value,
            "status": V2Status.REPORT_EMITTED.value,
            "refs": refs,
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
        }
    )
    validate_v2_graph_state(final_state)
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    _write_json(workspace.resolve_path(FORGEUNIT_REPAIR_GRAPH_STATE_REF), final_state)
    return final_state


def _bridge_and_verify_forgeunit_attempt_state(
    workspace: JobWorkspace,
    state: Mapping[str, Any],
    *,
    attempt_id: str,
    created_at: str | None,
) -> SkillFoundryV2State:
    bridge = bridge_forgeunit_success_to_skillfoundry_attempt(
        workspace,
        state,
        attempt_id=attempt_id,
        created_at=created_at,
    )
    _maybe_write_contextforge_frontdesk_boundary_evidence(workspace, created_at=created_at)
    _upsert_existing_manifest_records(
        workspace,
        [
            FORGEUNIT_VERIFICATION_RESULT_REF,
            "verifier/static_report.json",
            "verifier/sandbox.log",
            BUNDLE_VERIFICATION_RESULT_REF,
            ACCEPTANCE_COVERAGE_PLAN_REF,
            ACCEPTANCE_COVERAGE_RESULT_REF,
        ],
        created_by="skillfoundry.forgeunit_adapter.pre_verifier_refresh",
    )
    result = Verifier().verify(workspace, attempt_id=bridge.attempt_id)
    _upsert_existing_manifest_records(
        workspace,
        [
            FORGEUNIT_VERIFICATION_RESULT_REF,
            "verifier/static_report.json",
            "verifier/sandbox.log",
            BUNDLE_VERIFICATION_RESULT_REF,
        ],
        created_by="skillfoundry.forgeunit_adapter.post_verifier_refresh",
    )

    refs_out = dict(state.get("refs", {}))
    refs_out.update(
        {
            "forgeunit_attempt_input_manifest": bridge.input_manifest_ref,
            "forgeunit_attempt_execution_report": bridge.execution_report_ref,
            "forgeunit_attempt_transcript": bridge.transcript_ref,
            "forgeunit_attempt_diff": bridge.diff_ref,
            "skillfoundry_verification_result": FORGEUNIT_VERIFICATION_RESULT_REF,
            "verification_result": FORGEUNIT_VERIFICATION_RESULT_REF,
        }
    )
    if attempt_id == FORGEUNIT_REPAIR_ATTEMPT_ID:
        refs_out.update(
            {
                "forgeunit_repair_attempt_input_manifest": bridge.input_manifest_ref,
                "forgeunit_repair_attempt_execution_report": bridge.execution_report_ref,
                "forgeunit_repair_attempt_transcript": bridge.transcript_ref,
                "forgeunit_repair_attempt_diff": bridge.diff_ref,
            }
        )

    hashes = dict(state.get("hashes", {}))
    hashes.update(
        {
            "artifact_manifest": sha256_file(workspace.resolve_path(bridge.artifact_manifest_ref, must_exist=True)),
            "forgeunit_attempt_input_manifest": sha256_file(
                workspace.resolve_path(bridge.input_manifest_ref, must_exist=True)
            ),
            "forgeunit_attempt_execution_report": sha256_file(
                workspace.resolve_path(bridge.execution_report_ref, must_exist=True)
            ),
            "forgeunit_attempt_transcript": sha256_file(workspace.resolve_path(bridge.transcript_ref, must_exist=True)),
            "forgeunit_attempt_diff": sha256_file(workspace.resolve_path(bridge.diff_ref, must_exist=True)),
            "skillfoundry_verification_result": sha256_file(
                workspace.resolve_path(FORGEUNIT_VERIFICATION_RESULT_REF, must_exist=True)
            ),
            "verification_result": sha256_file(
                workspace.resolve_path(FORGEUNIT_VERIFICATION_RESULT_REF, must_exist=True)
            ),
        }
    )
    if attempt_id == FORGEUNIT_REPAIR_ATTEMPT_ID:
        hashes.update(
            {
                "forgeunit_repair_attempt_input_manifest": hashes["forgeunit_attempt_input_manifest"],
                "forgeunit_repair_attempt_execution_report": hashes["forgeunit_attempt_execution_report"],
                "forgeunit_repair_attempt_transcript": hashes["forgeunit_attempt_transcript"],
                "forgeunit_repair_attempt_diff": hashes["forgeunit_attempt_diff"],
            }
        )

    contextforge_out = dict(state.get("contextforge", {}))
    contextforge_out.update(
        {
            "last_verification_result_id": result.result_id,
            "last_verification_status": "passed" if result.passed else "failed",
            "skillfoundry_verification_result_ref": FORGEUNIT_VERIFICATION_RESULT_REF,
            "forgeunit_command_bridge_attempt_id": bridge.attempt_id,
            "worker_self_report_is_not_acceptance": True,
            "registry_approved": False,
        }
    )
    if attempt_id == FORGEUNIT_REPAIR_ATTEMPT_ID:
        contextforge_out["forgeunit_repair_attempt_id"] = attempt_id

    status = V2Status.VERIFIED.value if result.passed else V2Status.VERIFICATION_FAILED.value
    route_state = dict(state)
    route_state.update({"status": status, "contextforge": contextforge_out})
    next_state: SkillFoundryV2State = dict(state)
    next_state.update(
        {
            "schema_version": str(state.get("schema_version") or "skillfoundry.graph_v2_state.v1"),
            "job_id": workspace.job_id,
            "stage": V2Stage.VERIFY.value,
            "status": status,
            "attempt_count": max(int(state.get("attempt_count", 0)), int(attempt_id)),
            "attempt_limit": int(state.get("attempt_limit", 1)),
            "refs": refs_out,
            "hashes": hashes,
            "contextforge": contextforge_out,
            "human_review_required": False,
            "next_route": route_after_verification(route_state),
        }
    )
    validate_v2_graph_state(next_state)
    return next_state


def _maybe_write_contextforge_frontdesk_boundary_evidence(
    workspace: JobWorkspace,
    *,
    created_at: str | None,
) -> None:
    raw_path = workspace.root.joinpath(*Path(_FRONTDESK_CONVERSATION_REF).parts)
    if not raw_path.is_file():
        return

    timestamp = created_at or utc_now()
    run_id = f"{workspace.job_id}-forgeunit-context-boundary"
    try:
        contracts = write_contextforge_contract_artifacts(workspace, created_at=timestamp, overwrite=False)
        ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF))
        ledger.initialize()
        try:
            seed_goal_harness_context(
                workspace,
                ledger,
                contracts,
                run_id=run_id,
                created_at=timestamp,
                task_id=_FORGEUNIT_CONTEXT_TASK_ID,
                node_id=_FORGEUNIT_CONTEXT_NODE_ID,
            )
            compiled_context = ContextKernel(ledger).prepare_goal_context(
                contracts.goal_contract,
                contracts.build_node_contract,
                graph_id=_FORGEUNIT_CONTEXT_GRAPH_ID,
                run_id=run_id,
                task_id=_FORGEUNIT_CONTEXT_TASK_ID,
                created_at=timestamp,
                metadata={
                    "skillfoundry_job_id": workspace.job_id,
                    "worker_boundary": "forgeunit_codex_exec_command_bridge",
                    "raw_frontdesk_conversation_policy": "forbidden_from_prompt",
                },
            )
        finally:
            ledger.close()
    except Exception as exc:
        raise ForgeUnitIntegrationError(f"ContextForge FrontDesk boundary evidence failed: {exc}") from exc

    state_payload = {
        "schema_version": GOAL_RUNTIME_STATE_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "stage": "build",
        "status": "context_boundary_prepared",
        "attempt_count": 1,
        "refs": {
            "goal_contract": GOAL_CONTRACT_REF,
            "build_node_contract": BUILD_NODE_CONTRACT_REF,
            "verification_gate": VERIFICATION_GATE_REF,
            "contract_manifest": CONTRACT_MANIFEST_REF,
            "ledger": GOAL_RUNTIME_LEDGER_REF,
            "runtime_result": GOAL_RUNTIME_RESULT_REF,
        },
        "hashes": {
            "goal_contract": contracts.goal_contract.contract_hash,
            "build_node_contract": contracts.build_node_contract.contract_hash,
            "verification_gate": contracts.verification_gate.gate_hash,
        },
        "contextforge": {
            "last_context_view_id": compiled_context.context_view.context_view_id,
            "last_prompt_cache_plan_id": compiled_context.cache_plan.cache_plan_id,
            "forgeunit_context_boundary": True,
            "raw_frontdesk_conversation_forbidden": True,
        },
        "next_route": "verify",
        "created_at": timestamp,
    }
    workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
    _write_json(workspace.resolve_path(GOAL_RUNTIME_STATE_REF), state_payload)


def _archive_current_forgeunit_summary(workspace: JobWorkspace, attempt_id: str) -> str:
    archive_ref = _forgeunit_summary_archive_ref(attempt_id)
    payload = _read_json_object(
        workspace.resolve_path(FORGEUNIT_SUMMARY_REF, must_exist=True),
        "ForgeUnit summary",
    )
    _write_json(workspace.resolve_path(archive_ref), payload)
    _upsert_manifest_records(
        workspace,
        [FORGEUNIT_SUMMARY_REF, archive_ref],
        created_by="skillfoundry.forgeunit_adapter",
    )
    return archive_ref


def _archive_current_verification_result(
    workspace: JobWorkspace,
    attempt_id: str,
) -> tuple[str, VerificationResult]:
    result = VerificationResult.read_json_file(
        workspace.resolve_path(FORGEUNIT_VERIFICATION_RESULT_REF, must_exist=True)
    )
    archive_ref = _verification_archive_ref(attempt_id)
    result.write_json_file(workspace.resolve_path(archive_ref))
    _upsert_manifest_records(
        workspace,
        [
            FORGEUNIT_VERIFICATION_RESULT_REF,
            archive_ref,
            "verifier/static_report.json",
            "verifier/sandbox.log",
        ],
        created_by="skillfoundry.forgeunit_adapter",
    )
    return archive_ref, result


def _with_repair_packet_state(
    workspace: JobWorkspace,
    state: Mapping[str, Any],
    *,
    repair_packet_ref: str,
    first_summary_ref: str,
    first_verification_ref: str,
) -> SkillFoundryV2State:
    refs = dict(state.get("refs", {}))
    refs.update(
        {
            "forgeunit_repair_packet": repair_packet_ref,
            "forgeunit_initial_summary": first_summary_ref,
            "forgeunit_initial_verification_result": first_verification_ref,
        }
    )
    hashes = dict(state.get("hashes", {}))
    hashes.update(
        {
            "forgeunit_repair_packet": sha256_file(workspace.resolve_path(repair_packet_ref, must_exist=True)),
            "forgeunit_initial_summary": sha256_file(workspace.resolve_path(first_summary_ref, must_exist=True)),
            "forgeunit_initial_verification_result": sha256_file(
                workspace.resolve_path(first_verification_ref, must_exist=True)
            ),
        }
    )
    contextforge = dict(state.get("contextforge", {}))
    contextforge.update(
        {
            "forgeunit_repair_packet_ref": repair_packet_ref,
            "forgeunit_repair_failed_attempt_id": FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID,
            "forgeunit_repair_attempt_id": FORGEUNIT_REPAIR_ATTEMPT_ID,
            "forgeunit_repair_status": "repair_packet_written",
        }
    )
    next_state: SkillFoundryV2State = dict(state)
    next_state.update(
        {
            "stage": V2Stage.REPAIR_GOAL_NODE.value,
            "status": V2Status.REPAIR_PLANNED.value,
            "refs": refs,
            "hashes": hashes,
            "contextforge": contextforge,
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
        }
    )
    validate_v2_graph_state(next_state)
    return next_state


def _with_initial_repair_pilot_success_state(
    workspace: JobWorkspace,
    state: Mapping[str, Any],
    *,
    first_summary_ref: str,
    first_verification_ref: str,
) -> SkillFoundryV2State:
    refs = dict(state.get("refs", {}))
    refs.update(
        {
            "forgeunit_initial_summary": first_summary_ref,
            "forgeunit_initial_verification_result": first_verification_ref,
        }
    )
    hashes = dict(state.get("hashes", {}))
    hashes.update(
        {
            "forgeunit_initial_summary": sha256_file(workspace.resolve_path(first_summary_ref, must_exist=True)),
            "forgeunit_initial_verification_result": sha256_file(
                workspace.resolve_path(first_verification_ref, must_exist=True)
            ),
        }
    )
    contextforge = dict(state.get("contextforge", {}))
    contextforge.update(
        {
            "forgeunit_repair_failed_attempt_id": None,
            "forgeunit_repair_attempt_id": None,
            "forgeunit_repair_status": "initial_verified_no_repair",
        }
    )
    next_state: SkillFoundryV2State = dict(state)
    next_state.update(
        {
            "refs": refs,
            "hashes": hashes,
            "contextforge": contextforge,
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
        }
    )
    validate_v2_graph_state(next_state)
    return next_state


def _with_repair_success_state(
    workspace: JobWorkspace,
    state: Mapping[str, Any],
    *,
    second_summary_ref: str,
    second_verification_ref: str,
) -> SkillFoundryV2State:
    refs = dict(state.get("refs", {}))
    refs.update(
        {
            "forgeunit_repair_summary": second_summary_ref,
            "forgeunit_repair_verification_result": second_verification_ref,
        }
    )
    hashes = dict(state.get("hashes", {}))
    hashes.update(
        {
            "forgeunit_repair_summary": sha256_file(workspace.resolve_path(second_summary_ref, must_exist=True)),
            "forgeunit_repair_verification_result": sha256_file(
                workspace.resolve_path(second_verification_ref, must_exist=True)
            ),
        }
    )
    contextforge = dict(state.get("contextforge", {}))
    contextforge.update(
        {
            "forgeunit_repair_attempt_id": FORGEUNIT_REPAIR_ATTEMPT_ID,
            "forgeunit_repair_status": "repaired_and_verified",
        }
    )
    next_state: SkillFoundryV2State = dict(state)
    next_state.update({"refs": refs, "hashes": hashes, "contextforge": contextforge})
    validate_v2_graph_state(next_state)
    return next_state


def _failed_primary_check_names(result: VerificationResult) -> list[str]:
    names: list[str] = []
    for check in result.checks:
        if not isinstance(check, Mapping):
            continue
        if check.get("severity") != "error" or check.get("passed") is not False:
            continue
        name = check.get("name")
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def _verification_archive_ref(attempt_id: str) -> str:
    return f"attempts/{attempt_id}/verification_result.json"


def _forgeunit_summary_archive_ref(attempt_id: str) -> str:
    return f"attempts/{attempt_id}/forgeunit_summary.json"


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ForgeUnitIntegrationError(f"{label} is missing or invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ForgeUnitIntegrationError(f"{label} must be a JSON object")
    return payload


def _require_forgeunit_command_success(summary: Mapping[str, Any]) -> None:
    status = str(summary.get("operation_status") or summary.get("status") or "")
    adapter_result = summary.get("adapter_result")
    adapter_status = ""
    if isinstance(adapter_result, Mapping):
        adapter_status = str(adapter_result.get("status") or "")
    accepted = {"passed", "completed", "success"}
    if status not in accepted and adapter_status not in accepted:
        raise ForgeUnitIntegrationError(
            f"ForgeUnit command bridge must be successful before SkillFoundry verification; "
            f"got operation_status={status!r} adapter_status={adapter_status!r}"
        )


def _artifact_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    paths: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        path = item.get("path")
        if isinstance(path, str) and path.strip():
            paths.append(path)
    return paths


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip() or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _upsert_manifest_records(
    workspace: JobWorkspace,
    refs: list[str],
    *,
    created_by: str,
) -> None:
    manifest = workspace.read_manifest()
    by_path = {record.path: record for record in manifest.artifacts}
    order = [record.path for record in manifest.artifacts]
    now = utc_now()
    for ref in refs:
        path = workspace.resolve_path(ref, must_exist=True)
        if not path.is_file():
            raise ForgeUnitIntegrationError(f"manifest record must point to a file: {ref}")
        existing = by_path.get(ref)
        locked = existing.locked if existing is not None else False
        by_path[ref] = ArtifactRecord(
            artifact_id=existing.artifact_id if existing is not None else f"{workspace.job_id}:{ref.replace('/', ':')}",
            path=ref,
            kind="locked_input" if locked else _artifact_kind_for_ref(ref),
            sha256=sha256_file(path),
            created_by=created_by,
            created_at=existing.created_at if existing is not None else now,
            job_id=workspace.job_id,
            attempt_id=_attempt_id_for_ref(ref),
            locked=locked,
        )
        if ref not in order:
            order.append(ref)
    manifest.artifacts = [by_path[path] for path in order]
    workspace.write_manifest(manifest)


def _upsert_existing_manifest_records(
    workspace: JobWorkspace,
    refs: list[str],
    *,
    created_by: str,
) -> None:
    existing_refs: list[str] = []
    for ref in refs:
        try:
            path = workspace.resolve_path(ref)
        except Exception:
            continue
        if path.is_file():
            existing_refs.append(ref)
    if existing_refs:
        _upsert_manifest_records(workspace, _dedupe_strings(existing_refs), created_by=created_by)


def _artifact_kind_for_ref(ref: str) -> str:
    if ref.startswith("attempts/"):
        return "worker_attempt"
    if ref.startswith("package/"):
        return "skill_package"
    if ref.startswith("evidence/"):
        return "boundary_evidence"
    if ref.startswith("contextforge/"):
        return "contextforge_artifact"
    if ref.startswith(".forgeunit/"):
        return "forgeunit_run_artifact"
    return "forgeunit_adapter_artifact"


def _attempt_id_for_ref(ref: str) -> str | None:
    parts = ref.split("/")
    if len(parts) >= 3 and parts[0] == "attempts" and parts[1].isdecimal():
        return parts[1]
    return None


def _validate_with_forgeunit(task_pack_dir: Path) -> None:
    try:
        from forgeunit import validate_task_pack_or_raise
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without optional dependency
        raise ForgeUnitIntegrationError(
            "ForgeUnit v1.2 is required for SkillFoundry ForgeUnit integration. "
            "Install the sibling ForgeUnit checkout with: python -m pip install -e ../ForgeUnit"
        ) from exc
    validate_task_pack_or_raise(task_pack_dir)


def _load_forgeunit_node() -> Any:
    try:
        from forgeunit import ForgeUnitNode
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without optional dependency
        raise ForgeUnitIntegrationError(
            "ForgeUnit v1.2 is required for SkillFoundry ForgeUnit integration. "
            "Install the sibling ForgeUnit checkout with: python -m pip install -e ../ForgeUnit"
        ) from exc
    return ForgeUnitNode


def _refs_only_forgeunit_summary(node_state: Mapping[str, Any]) -> dict[str, Any]:
    summary = dict(node_state.get("forgeunit") or {})
    adapter_result = dict(summary.get("adapter_result") or {})
    adapter_result.pop("prompt", None)
    if adapter_result:
        summary["adapter_result"] = adapter_result
    return summary


def _boundary_reason_code(state: Mapping[str, Any]) -> str:
    refs = state.get("refs") if isinstance(state.get("refs"), Mapping) else {}
    contextforge = state.get("contextforge") if isinstance(state.get("contextforge"), Mapping) else {}
    assert isinstance(refs, Mapping)
    assert isinstance(contextforge, Mapping)
    if contextforge.get("forgeunit_codex_exec_dry_run") is True or refs.get("forgeunit_codex_exec_plan"):
        return "forgeunit_codex_exec_dry_run_boundary_pending"
    return "forgeunit_boundary_result_pending"


def _boundary_verification_payload(
    *,
    job_id: str,
    state: Mapping[str, Any],
    verification_status: str,
    boundary_status: str,
    reason_code: str,
    created_at: str,
) -> dict[str, JsonValue]:
    refs = state.get("refs") if isinstance(state.get("refs"), Mapping) else {}
    contextforge = state.get("contextforge") if isinstance(state.get("contextforge"), Mapping) else {}
    assert isinstance(refs, Mapping)
    assert isinstance(contextforge, Mapping)
    payload = {
        "schema_version": "skillfoundry.forgeunit_boundary_verification.v1",
        "verification_result_id": f"{job_id}:forgeunit-boundary:{int(state.get('attempt_count', 0)) or 1}",
        "job_id": job_id,
        "status": verification_status,
        "boundary_status": boundary_status,
        "reason_code": reason_code,
        "created_at": created_at,
        "forgeunit": {
            "run_id": contextforge.get("forgeunit_run_id"),
            "status": contextforge.get("forgeunit_status"),
            "route": contextforge.get("forgeunit_route"),
            "current_node": contextforge.get("forgeunit_current_node"),
            "codex_exec_dry_run": contextforge.get("forgeunit_codex_exec_dry_run") is True,
        },
        "evidence_refs": {
            key: value
            for key, value in refs.items()
            if key
            in {
                "forgeunit_task_yaml",
                "forgeunit_run",
                "forgeunit_summary",
                "forgeunit_codex_exec_plan",
            }
            and isinstance(value, str)
            and value
        },
        "trust_boundaries": {
            "worker_self_report_is_not_acceptance": True,
            "dry_run_is_not_verification": True,
            "registry_promotion_allowed": False,
            "raw_prompt_included": False,
            "raw_transcript_included": False,
            "raw_requirement_included": False,
            "package_body_included": False,
        },
    }
    compatible = ensure_json_compatible(payload)
    if not isinstance(compatible, dict):
        raise ForgeUnitIntegrationError("boundary verification payload must be a JSON object")
    return compatible  # type: ignore[return-value]


def _job_id(state: Mapping[str, Any]) -> str:
    value = state.get("job_id")
    if not isinstance(value, str) or not JOB_ID_RE.fullmatch(value):
        raise ForgeUnitIntegrationError("state.job_id must be a safe SkillFoundry job id")
    return value


def _relative_ref(workspace: JobWorkspace, path: Path) -> str:
    resolved_root = workspace.root.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ForgeUnitIntegrationError(f"ForgeUnit artifact escaped workspace: {resolved_path}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
