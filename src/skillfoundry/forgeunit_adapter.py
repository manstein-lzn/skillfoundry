"""Thin SkillFoundry product adapter for ForgeUnit work-unit execution."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

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
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .verifier import Verifier
from .workspace import JOB_ID_RE, JobWorkspace


FORGEUNIT_ADAPTER_VERSION = "skillfoundry.forgeunit_adapter.v1"
FORGEUNIT_TASK_YAML_REF = "task.yaml"
FORGEUNIT_SUMMARY_REF = "contextforge/forgeunit_summary.json"
FORGEUNIT_BOUNDARY_VERIFICATION_REF = "contextforge/forgeunit_boundary_verification.json"
FORGEUNIT_PILOT_GRAPH_STATE_REF = "contextforge/forgeunit_pilot_graph_state.json"
FORGEUNIT_CODEX_EXEC_UNIT_ID = "execute"
FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID = "001"
FORGEUNIT_VERIFICATION_RESULT_REF = "verifier/verification_result.json"
FORGEUNIT_REGISTRY_DECISION_REF = "registry/decision.json"
FORGEUNIT_REGISTRY_ENTRY_REF = "registry/entry.json"
FORGEUNIT_FINAL_REPORT_REF = "final_report.json"


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


def materialize_forgeunit_task_pack(workspace: JobWorkspace) -> ForgeUnitTaskPackArtifacts:
    """Write a ForgeUnit task pack over the existing SkillFoundry job workspace."""

    workspace.check_locked_inputs()
    for relative_dir in ("package", "evidence"):
        workspace.resolve_path(relative_dir).mkdir(parents=True, exist_ok=True)

    task_payload = {
        "id": f"skillfoundry_{workspace.job_id}_forgeunit",
        "version": "skillfoundry.forgeunit_task_pack.v1",
        "graph": "plan_execute_verify",
        "max_repair_attempts": 1,
        "inputs": {
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
        },
        "units": {
            "plan": {
                "objective": "Create a concise build plan from the frozen SkillFoundry inputs.",
                "worker": {"kind": "fake"},
                "expected_outputs": [{"path": "attempts/forgeunit_plan.md", "kind": "plan"}],
                "verify": [{"type": "file_exists", "path": "attempts/forgeunit_plan.md"}],
            },
            FORGEUNIT_CODEX_EXEC_UNIT_ID: {
                "objective": (
                    "Build a Codex Skill package from the frozen SkillFoundry inputs. "
                    "Write package/SKILL.md and boundary evidence before reporting completion."
                ),
                "worker": {
                    "kind": "codex_boundary",
                    "write_scope": ["package", "evidence"],
                    "required_boundary_evidence": ["evidence/transcript.md", "evidence/manifest.json"],
                },
                "expected_outputs": [{"path": "package/SKILL.md", "kind": "codex_skill"}],
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
) -> ForgeUnitNodeResult:
    """Invoke ForgeUnit's public LangGraph adapter for one SkillFoundry workspace."""

    task_pack = materialize_forgeunit_task_pack(workspace)
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
        bridge = bridge_forgeunit_success_to_skillfoundry_attempt(
            workspace,
            state,
            attempt_id=FORGEUNIT_SKILLFOUNDRY_ATTEMPT_ID,
            created_at=created_at,
        )
        result = Verifier().verify(workspace, attempt_id=bridge.attempt_id)

        refs_out = dict(refs)
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
                "forgeunit_attempt_transcript": sha256_file(
                    workspace.resolve_path(bridge.transcript_ref, must_exist=True)
                ),
                "forgeunit_attempt_diff": sha256_file(workspace.resolve_path(bridge.diff_ref, must_exist=True)),
                "skillfoundry_verification_result": sha256_file(
                    workspace.resolve_path(FORGEUNIT_VERIFICATION_RESULT_REF, must_exist=True)
                ),
                "verification_result": sha256_file(
                    workspace.resolve_path(FORGEUNIT_VERIFICATION_RESULT_REF, must_exist=True)
                ),
            }
        )

        contextforge_out = dict(contextforge)
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
        status = V2Status.VERIFIED.value if result.passed else V2Status.VERIFICATION_FAILED.value
        route_state = dict(state)
        route_state.update({"status": status, "contextforge": contextforge_out})
        next_state: SkillFoundryV2State = dict(state)
        next_state.update(
            {
                "schema_version": str(state.get("schema_version") or "skillfoundry.graph_v2_state.v1"),
                "job_id": job_id,
                "stage": V2Stage.VERIFY.value,
                "status": status,
                "attempt_count": max(int(state.get("attempt_count", 0)), 1),
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
            require_contextforge_verification=False,
        )
        verification_report = LocalSkillRegistry(registry_file).verify_entry(entry)
        if not verification_report.valid:
            raise ForgeUnitIntegrationError(
                "ForgeUnit registry gate failed: " + "; ".join(verification_report.failures)
            )

        from .offline import emit_final_report

        final_report = emit_final_report(
            workspace.root,
            final_status=V2Status.REGISTERED.value,
            registry_path=registry_file,
            registry_entry=entry,
        )

        timestamp = created_at or utc_now()
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
                "registry_decision": FORGEUNIT_REGISTRY_DECISION_REF,
                "registry_entry": FORGEUNIT_REGISTRY_ENTRY_REF,
            }
        )
        hashes = dict(state.get("hashes", {}))
        hashes.update(
            {
                "final_report": sha256_file(workspace.resolve_path(FORGEUNIT_FINAL_REPORT_REF, must_exist=True)),
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
