"""ContextForge Goal Harness contract bridge for SkillFoundry v2."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal

from contextforge import (
    AGENT_NODE_CONTRACT_SCHEMA,
    CHECKPOINT_POLICY_SCHEMA,
    GOAL_CONTRACT_SCHEMA,
    TOOL_PERMISSION_SCHEMA,
    VERIFICATION_GATE_SCHEMA,
    WRITE_SCOPE_SCHEMA,
    AgentNodeContract,
    GoalContract,
    VerificationGate,
    with_computed_hash,
)

from .budgets import (
    TOKEN_BUDGET_MODE_UNLIMITED_DEFAULT,
    UNLIMITED_TOKEN_BUDGET_SENTINEL,
)
from .schema import (
    ArtifactManifest,
    BuildContract,
    JsonValue,
    SchemaValidationError,
    SkillSpec,
    VerificationSpec,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .security import PathSecurityError, validate_relative_path
from .workspace import JobWorkspace


CONTEXTFORGE_CONTRACT_DIR = "contextforge"
GOAL_CONTRACT_REF = f"{CONTEXTFORGE_CONTRACT_DIR}/goal_contract.json"
BUILD_NODE_CONTRACT_REF = f"{CONTEXTFORGE_CONTRACT_DIR}/build_node_contract.json"
VERIFICATION_GATE_REF = f"{CONTEXTFORGE_CONTRACT_DIR}/verification_gate.json"
CONTRACT_MANIFEST_REF = f"{CONTEXTFORGE_CONTRACT_DIR}/contract_manifest.json"
CONTRACT_MANIFEST_SCHEMA_VERSION = "skillfoundry.contextforge_contract_manifest.v1"

_CONTRACT_VERSION = "0.1"
_BUILD_NODE_ID = "build_skill"
_BUILD_NODE_ROLE = "skill_builder"
_DEFAULT_WORKER_VERSION = "skillfoundry.v2.phase1"
_DEFAULT_MAX_WORKER_RUNS = 1
_DEFAULT_FORBIDDEN_PATHS = [".env", ".secrets", "secrets", "secrets.json"]
_DEFAULT_FORBIDDEN_WRITE_PATHS = [
    *_DEFAULT_FORBIDDEN_PATHS,
    "skill_spec.yaml",
    "verification_spec.yaml",
    "build_contract.yaml",
    "worker_input.md",
    "artifact_manifest.json",
    "frontdesk",
]
_DEFAULT_REQUIRED_EVIDENCE = [
    "package/SKILL.md",
    "artifact_manifest.json",
    "verifier/verification_result.json",
    "qa/acceptance_coverage_result.json",
]
_FORBIDDEN_CONTEXT_TAGS = [
    "raw_frontdesk_conversation",
    "secret",
    "unapproved_plan_draft",
    "rejected_plan_revision",
]
_FORBIDDEN_CLAIMS = [
    "self-approved",
    "verified without verifier evidence",
    "registry approved by builder",
]


@dataclass(frozen=True)
class ContextForgeContractArtifacts:
    """Contracts written for one SkillFoundry job workspace."""

    goal_contract: GoalContract
    build_node_contract: AgentNodeContract
    verification_gate: VerificationGate
    manifest: dict[str, JsonValue]


def build_goal_contract(
    workspace: JobWorkspace,
    *,
    skill_spec: SkillSpec | None = None,
    verification_spec: VerificationSpec | None = None,
    build_contract: BuildContract | None = None,
    created_at: str | None = None,
) -> GoalContract:
    """Map frozen SkillFoundry inputs to a ContextForge ``GoalContract``."""

    workspace.check_locked_inputs()
    records = _load_workspace_records(
        workspace,
        skill_spec=skill_spec,
        verification_spec=verification_spec,
        build_contract=build_contract,
    )
    success_criteria = list(records.skill_spec.acceptance_criteria)
    if not success_criteria:
        success_criteria = list(records.verification_spec.acceptance_criteria)
    if not success_criteria:
        raise SchemaValidationError("GoalContract success_criteria must not be empty")

    timestamp = created_at or utc_now()
    source_refs = _source_refs(records.build_contract)
    source_hashes = _source_hashes(workspace, records)
    payload = {
        "schema": GOAL_CONTRACT_SCHEMA,
        "version": _CONTRACT_VERSION,
        "goal_id": _goal_id(workspace.job_id),
        "objective": _objective_from_skill_spec(records.skill_spec),
        "success_criteria": success_criteria,
        "non_goals": list(records.skill_spec.non_trigger_scenarios),
        "constraints": _goal_constraints(records.skill_spec, records.verification_spec, records.build_contract),
        "assumptions": _goal_assumptions(records.skill_spec),
        "budgets": {
            "timeout_seconds": records.build_contract.timeout_seconds,
            "attempt_limit": records.build_contract.attempt_limit,
            "max_worker_runs": records.build_contract.attempt_limit,
            "locked_input_hashes": dict(records.build_contract.locked_input_hashes),
            "source_refs": source_refs,
            "source_hashes": source_hashes,
        },
        "checkpoint_policy": _checkpoint_policy_payload(),
        "stop_conditions": [
            "verification_gate_passes",
            "registry_decision_recorded",
            "budget_exhausted",
        ],
        "verification_gate_id": _verification_gate_id(workspace.job_id),
        "created_at": timestamp,
        "locked_at": timestamp,
        "contract_hash": "",
        "metadata": {
            "bridge": "skillfoundry.contextforge_contract_bridge.v1",
            "job_id": workspace.job_id,
            "skill_id": records.skill_spec.skill_id,
            "source_refs": source_refs,
            "source_hashes": source_hashes,
            "raw_conversation_included": False,
        },
    }
    return GoalContract.from_dict(with_computed_hash(payload, "contract_hash"))


def build_verification_gate(
    workspace: JobWorkspace,
    goal_id: str,
    *,
    verification_spec: VerificationSpec | None = None,
    artifact_manifest: ArtifactManifest | None = None,
    build_contract: BuildContract | None = None,
) -> VerificationGate:
    """Map SkillFoundry verifier requirements to a ContextForge gate."""

    workspace.check_locked_inputs()
    records = _load_workspace_records(
        workspace,
        verification_spec=verification_spec,
        artifact_manifest=artifact_manifest,
        build_contract=build_contract,
    )
    required_evidence = _required_evidence(records.verification_spec)
    forbidden_paths, rejected_path_policies = _forbidden_paths(records.build_contract.blocked_paths)
    artifact_hashes, rejected_artifact_hash_paths = _artifact_hash_requirements(
        workspace,
        records.build_contract,
        records.artifact_manifest,
    )
    validators = [
        {
            "validator_id": f"required-evidence-{_id_fragment(path)}",
            "type": "file_exists",
            "mode": "executable",
            "severity": "blocking",
            "params": {"path": path},
            "metadata": {"source": "skillfoundry.required_evidence"},
        }
        for path in required_evidence
    ]
    review_required = _contains_manual_authority(records.verification_spec.acceptance_criteria, review_only=True)
    human_authority_required = _contains_manual_authority(records.verification_spec.acceptance_criteria)
    payload = {
        "schema": VERIFICATION_GATE_SCHEMA,
        "version": _CONTRACT_VERSION,
        "verification_gate_id": _verification_gate_id(workspace.job_id),
        "goal_id": goal_id,
        "validators": validators,
        "required_evidence": required_evidence,
        "metric_gates": [],
        "artifact_hashes": artifact_hashes,
        "forbidden_paths": forbidden_paths,
        "forbidden_claims": list(_FORBIDDEN_CLAIMS),
        "review_required": review_required,
        "human_authority_required": human_authority_required,
        "unsupported_behavior": "fail_closed",
        "gate_hash": "",
        "metadata": {
            "bridge": "skillfoundry.contextforge_contract_bridge.v1",
            "gate_stage": "post_build_verification_promotion",
            "runner_precondition": (
                "Run this gate after SkillFoundry verifier and acceptance coverage artifacts exist."
            ),
            "job_id": workspace.job_id,
            "verification_spec_ref": records.build_contract.verification_spec_ref,
            "verifier_version": records.verification_spec.verifier_version,
            "required_checks": list(records.verification_spec.required_checks),
            "path_policies": list(records.verification_spec.path_policies),
            "rejected_forbidden_path_policies": rejected_path_policies,
            "rejected_artifact_hash_paths": rejected_artifact_hash_paths,
        },
    }
    return VerificationGate.from_dict(with_computed_hash(payload, "gate_hash"))


def build_agent_node_contract(
    workspace: JobWorkspace,
    goal_contract: GoalContract,
    verification_gate: VerificationGate,
    *,
    build_contract: BuildContract | None = None,
    worker_kind: Literal["llm", "codex_sdk_thread", "fake_model", "external_agent"] = "fake_model",
    worker_name: str = "skillfoundry-fake-skill-builder",
    created_at: str | None = None,
) -> AgentNodeContract:
    """Build the ContextForge contract for SkillFoundry's build node."""

    del created_at
    workspace.check_locked_inputs()
    records = _load_workspace_records(workspace, build_contract=build_contract)
    source_hashes = _source_hashes(workspace, records)
    allowed_paths = _required_safe_paths(records.build_contract.allowed_write_paths, "allowed_write_paths")
    forbidden_paths, rejected_path_policies = _forbidden_write_paths(records.build_contract.blocked_paths)
    visible_context = _visible_context_selectors()
    forbidden_context = _forbidden_context_selectors()
    tool_permissions = [
        {
            "schema": TOOL_PERMISSION_SCHEMA,
            "tool_name": "filesystem",
            "allowed": True,
            "argument_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "operation": {"enum": ["read", "write", "list", "mkdir"]},
                },
                "required": ["path", "operation"],
            },
            "path_policy": "workspace_only",
            "network_policy": "disabled",
            "max_calls": 200,
            "timeout_seconds": records.build_contract.timeout_seconds,
            "requires_approval": False,
            "metadata": {"write_scope_ref": "write_scope"},
        },
        {
            "schema": TOOL_PERMISSION_SCHEMA,
            "tool_name": "shell",
            "allowed": True,
            "argument_schema": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                "required": ["cmd"],
            },
            "path_policy": "workspace_only",
            "network_policy": "disabled",
            "max_calls": 50,
            "timeout_seconds": records.build_contract.timeout_seconds,
            "requires_approval": False,
            "metadata": {
                "purpose": "offline tests and deterministic package checks",
                "network_disabled": True,
            },
        },
        {
            "schema": TOOL_PERMISSION_SCHEMA,
            "tool_name": "network",
            "allowed": False,
            "argument_schema": {"type": "object"},
            "path_policy": "none",
            "network_policy": "disabled",
            "max_calls": None,
            "timeout_seconds": None,
            "requires_approval": True,
            "metadata": {"purpose": "Network is disabled by default for deterministic builds."},
        },
    ]
    cache_epoch_id = _cache_epoch_id(
        goal_contract=goal_contract,
        verification_gate=verification_gate,
        worker_kind=worker_kind,
        worker_name=worker_name,
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
        visible_context=visible_context,
        forbidden_context=forbidden_context,
        tool_permissions=tool_permissions,
        source_hashes=source_hashes,
    )
    payload = {
        "schema": AGENT_NODE_CONTRACT_SCHEMA,
        "version": _CONTRACT_VERSION,
        "node_id": _BUILD_NODE_ID,
        "goal_id": goal_contract.goal_id,
        "role": _BUILD_NODE_ROLE,
        "mission": "Generate a candidate Codex Skill package from frozen SkillFoundry inputs only.",
        "visible_context": visible_context,
        "forbidden_context": forbidden_context,
        "allowed_tools": tool_permissions,
        "write_scope": {
            "schema": WRITE_SCOPE_SCHEMA,
            "allowed_paths": allowed_paths,
            "forbidden_paths": forbidden_paths,
            "allowed_artifact_kinds": ["skill_package", "report", "manifest", "test_output"],
            "max_bytes": 5_000_000,
            "requires_diff_review": True,
            "metadata": {
                "source": "BuildContract.allowed_write_paths",
                "rejected_blocked_path_policies": rejected_path_policies,
            },
        },
        "output_contract": (
            "Write candidate package artifacts under package/ and execution evidence under attempts/. "
            "Return artifact refs, hashes, changed paths, and a concise execution summary only. "
            "Do not claim verification or registry approval."
        ),
        "worker": {
            "kind": worker_kind,
            "name": worker_name,
            "version": _DEFAULT_WORKER_VERSION,
            "model": None,
            "parameters": {"temperature": 0},
            "metadata": {
                "boundary": "ContextForge records the node boundary; worker internals remain worker-owned.",
                "codex_internal_loop_controlled_by_contextforge": False,
                "internal_prompt_replay_available": False,
                "internal_tool_loop_control_available": False,
                "boundary_enforcement": "input_contract_and_post_run_diff",
                "usage_reporting": "unavailable_allowed_with_reason",
            },
        },
        "budgets": {
            "prompt_budget_tokens": UNLIMITED_TOKEN_BUDGET_SENTINEL,
            "context_budget_tokens": UNLIMITED_TOKEN_BUDGET_SENTINEL,
            "token_budget_mode": TOKEN_BUDGET_MODE_UNLIMITED_DEFAULT,
            "timeout_seconds": records.build_contract.timeout_seconds,
            "attempt_limit": records.build_contract.attempt_limit,
            "max_worker_runs": _DEFAULT_MAX_WORKER_RUNS,
            "recent_item_limit": 20,
            "memory_limit": 5,
        },
        "cache_policy": {
            "mode": "stable_prefix",
            "cache_epoch_id": cache_epoch_id,
            "max_prefix_churn": 0.05,
            "metadata": {
                "strategy": "stable_prefix",
                "epoch_inputs": [
                    "goal_contract_hash",
                    "verification_gate_hash",
                    "node_visibility_policy",
                    "tool_permissions",
                    "write_scope",
                    "frozen_source_hashes",
                ],
            },
        },
        "checkpoint_policy": _checkpoint_policy_payload(),
        "stop_conditions": [
            "worker_completed",
            "verification_gate_passes",
            "budget_exhausted",
        ],
        "verification_gate_id": verification_gate.verification_gate_id,
        "handoff_policy": {
            "on_success": "route_to_verification",
            "on_failure": "record_checkpoint_and_route_to_repair",
            "handoff_requires_checkpoint": True,
        },
        "contract_hash": "",
        "metadata": {
            "bridge": "skillfoundry.contextforge_contract_bridge.v1",
            "job_id": workspace.job_id,
            "source_refs": _source_refs(records.build_contract),
            "source_hashes": source_hashes,
            "verification_gate_hash": verification_gate.gate_hash,
            "raw_conversation_forbidden": True,
            "codex_internal_prompt_cache_tool_loop_controlled": False,
            "excluded_artifacts": ["frontdesk/conversation.jsonl"],
        },
    }
    return AgentNodeContract.from_dict(with_computed_hash(payload, "contract_hash"))


def write_contextforge_contract_artifacts(
    workspace: JobWorkspace,
    *,
    created_at: str | None = None,
    overwrite: bool = True,
) -> ContextForgeContractArtifacts:
    """Generate and write all Phase 1 ContextForge contract artifacts."""

    workspace.check_locked_inputs()
    if not overwrite and _contextforge_contract_artifacts_exist(workspace):
        return read_contextforge_contract_artifacts(workspace)

    timestamp = created_at or utc_now()
    goal_contract = build_goal_contract(workspace, created_at=timestamp)
    verification_gate = build_verification_gate(workspace, goal_contract.goal_id)
    build_node_contract = build_agent_node_contract(workspace, goal_contract, verification_gate)

    contract_dir = workspace.root / CONTEXTFORGE_CONTRACT_DIR
    contract_dir.mkdir(parents=True, exist_ok=True)
    _write_record(workspace, GOAL_CONTRACT_REF, goal_contract.to_dict())
    _write_record(workspace, BUILD_NODE_CONTRACT_REF, build_node_contract.to_dict())
    _write_record(workspace, VERIFICATION_GATE_REF, verification_gate.to_dict())

    records = _load_workspace_records(workspace)
    source_refs = _source_refs(records.build_contract)
    source_hashes = _source_hashes(workspace, records)
    manifest = {
        "schema_version": CONTRACT_MANIFEST_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "created_at": timestamp,
        "goal_contract_ref": GOAL_CONTRACT_REF,
        "goal_contract_hash": sha256_file(workspace.resolve_path(GOAL_CONTRACT_REF, must_exist=True)),
        "build_node_contract_ref": BUILD_NODE_CONTRACT_REF,
        "build_node_contract_hash": sha256_file(workspace.resolve_path(BUILD_NODE_CONTRACT_REF, must_exist=True)),
        "verification_gate_ref": VERIFICATION_GATE_REF,
        "verification_gate_hash": sha256_file(workspace.resolve_path(VERIFICATION_GATE_REF, must_exist=True)),
        "contextforge_contract_hashes": {
            "goal_contract": goal_contract.contract_hash,
            "build_node_contract": build_node_contract.contract_hash,
            "verification_gate": verification_gate.gate_hash,
        },
        "source_refs": source_refs,
        "source_hashes": source_hashes,
        "excluded_artifacts": ["frontdesk/conversation.jsonl"],
    }
    compatible_manifest = ensure_json_compatible(manifest)
    if not isinstance(compatible_manifest, dict):
        raise SchemaValidationError("contract manifest must be a JSON object")
    _write_record(workspace, CONTRACT_MANIFEST_REF, compatible_manifest)
    return ContextForgeContractArtifacts(
        goal_contract=goal_contract,
        build_node_contract=build_node_contract,
        verification_gate=verification_gate,
        manifest=compatible_manifest,
    )


def read_contextforge_contract_artifacts(workspace: JobWorkspace) -> ContextForgeContractArtifacts:
    """Read previously written ContextForge contract artifacts without rewriting them."""

    goal_payload = _read_json_record(workspace, GOAL_CONTRACT_REF)
    build_node_payload = _read_json_record(workspace, BUILD_NODE_CONTRACT_REF)
    verification_gate_payload = _read_json_record(workspace, VERIFICATION_GATE_REF)
    manifest_payload = _read_json_record(workspace, CONTRACT_MANIFEST_REF)
    return ContextForgeContractArtifacts(
        goal_contract=GoalContract.from_dict(goal_payload),
        build_node_contract=AgentNodeContract.from_dict(build_node_payload),
        verification_gate=VerificationGate.from_dict(verification_gate_payload),
        manifest=manifest_payload,
    )


def _contextforge_contract_artifacts_exist(workspace: JobWorkspace) -> bool:
    refs = (GOAL_CONTRACT_REF, BUILD_NODE_CONTRACT_REF, VERIFICATION_GATE_REF, CONTRACT_MANIFEST_REF)
    try:
        return all(workspace.resolve_path(ref).is_file() for ref in refs)
    except PathSecurityError:
        return False


@dataclass(frozen=True)
class _WorkspaceRecords:
    skill_spec: SkillSpec
    verification_spec: VerificationSpec
    build_contract: BuildContract
    artifact_manifest: ArtifactManifest


def _load_workspace_records(
    workspace: JobWorkspace,
    *,
    skill_spec: SkillSpec | None = None,
    verification_spec: VerificationSpec | None = None,
    build_contract: BuildContract | None = None,
    artifact_manifest: ArtifactManifest | None = None,
) -> _WorkspaceRecords:
    contract = build_contract or BuildContract.read_yaml_file(workspace.resolve_path("build_contract.yaml", must_exist=True))
    spec = skill_spec or SkillSpec.read_yaml_file(workspace.resolve_path(contract.skill_spec_ref, must_exist=True))
    verifier_spec = verification_spec or VerificationSpec.read_yaml_file(
        workspace.resolve_path(contract.verification_spec_ref, must_exist=True)
    )
    manifest = artifact_manifest or workspace.read_manifest()
    return _WorkspaceRecords(
        skill_spec=spec,
        verification_spec=verifier_spec,
        build_contract=contract,
        artifact_manifest=manifest,
    )


def _goal_id(job_id: str) -> str:
    return f"skillfoundry-{job_id}"


def _verification_gate_id(job_id: str) -> str:
    return f"vg-{job_id}"


def _objective_from_skill_spec(skill_spec: SkillSpec) -> str:
    return f"{skill_spec.title}\n\n{skill_spec.description}"


def _goal_constraints(
    skill_spec: SkillSpec,
    verification_spec: VerificationSpec,
    build_contract: BuildContract,
) -> list[str]:
    constraints = [
        *skill_spec.constraints,
        *[f"Security: {item}" for item in skill_spec.security_notes],
        *[f"Path policy: {item}" for item in verification_spec.path_policies],
        f"Allowed write paths: {', '.join(build_contract.allowed_write_paths)}",
        f"Blocked path policies: {', '.join(build_contract.blocked_paths)}",
        f"Timeout seconds: {build_contract.timeout_seconds}",
        f"Attempt limit: {build_contract.attempt_limit}",
        *(
            [f"Task contract ref: {build_contract.task_contract_ref}"]
            if build_contract.task_contract_ref
            else []
        ),
        "Builder cannot read raw frontdesk conversation.",
        "Builder cannot self-approve verification or registry acceptance.",
    ]
    return _dedupe(constraints)


def _goal_assumptions(skill_spec: SkillSpec) -> list[str]:
    assumptions = [
        *[f"Required input: {item}" for item in skill_spec.required_inputs],
        *[f"Expected output: {item}" for item in skill_spec.expected_outputs],
        *[f"Reference material: {item}" for item in skill_spec.reference_materials],
    ]
    return _dedupe(assumptions)


def _checkpoint_policy_payload() -> dict[str, JsonValue]:
    return {
        "schema": CHECKPOINT_POLICY_SCHEMA,
        "triggers": [
            "phase_complete",
            "context_pressure",
            "repeated_failure",
            "handoff",
            "budget_threshold",
        ],
        "max_interval_seconds": 3600,
        "max_steps_between_checkpoints": 25,
        "summary_budget_tokens": 1000,
        "required": True,
        "metadata": {"policy": "skillfoundry_goal_harness_v2"},
    }


def _visible_context_selectors() -> list[dict[str, JsonValue]]:
    selectors = [
        (
            "visible-skill-spec",
            {"metadata.skillfoundry_context_type": "skill_spec"},
            True,
            "The builder needs the frozen skill specification.",
            "goal",
        ),
        (
            "visible-acceptance-criteria",
            {"metadata.skillfoundry_context_type": "acceptance_criteria"},
            True,
            "The builder must optimize against locked acceptance criteria.",
            "acceptance_criteria",
        ),
        (
            "visible-verification-gate",
            {"metadata.skillfoundry_context_type": "verification_gate"},
            True,
            "The builder must know the external gate but cannot approve it.",
            "constraints",
        ),
        (
            "visible-build-contract",
            {"metadata.skillfoundry_context_type": "build_contract"},
            True,
            "The builder needs write scope, timeout, and attempt limits.",
            "constraints",
        ),
        (
            "visible-task-contract",
            {"metadata.skillfoundry_context_type": "task_contract"},
            False,
            "The builder should prefer the canonical FrontDesk task contract when present.",
            "goal",
        ),
        (
            "visible-latest-checkpoint",
            {"metadata.skillfoundry_context_type": "checkpoint"},
            False,
            "Checkpoint summaries help resume without raw conversation.",
            "open_work",
        ),
    ]
    return [
        {
            "selector_id": selector_id,
            "kind": "scope",
            "value": value,
            "required": required,
            "reason": reason,
            "metadata": {
                "context_need": context_need,
                "stable_prefix": required,
                "selector_semantics": "skillfoundry_context_type",
            },
        }
        for selector_id, value, required, reason, context_need in selectors
    ] + [
        {
            "selector_id": "visible-verifier-failure",
            "kind": "tag",
            "value": "verifier_failure",
            "required": False,
            "reason": "Repair attempts may need the latest governed verifier failure.",
            "metadata": {"context_need": "recent_failures", "stable_prefix": False},
        }
    ]


def _forbidden_context_selectors() -> list[dict[str, JsonValue]]:
    return [
        {
            "selector_id": f"forbid-{tag.replace('_', '-')}",
            "kind": "tag",
            "value": tag,
            "required": False,
            "reason": f"Context tagged {tag!r} must not enter the builder prompt.",
            "metadata": {"fail_closed": True},
        }
        for tag in _FORBIDDEN_CONTEXT_TAGS
    ] + [
        {
            "selector_id": "forbid-frontdesk-conversation-artifact",
            "kind": "artifact",
            "value": "frontdesk/conversation.jsonl",
            "required": False,
            "reason": "Raw frontdesk conversation is provenance only and must not enter builder prompt context.",
            "metadata": {"fail_closed": True},
        }
    ]


def _required_evidence(verification_spec: VerificationSpec) -> list[str]:
    return _dedupe(
        [
            *_required_safe_paths(verification_spec.artifact_requirements, "artifact_requirements"),
            *_DEFAULT_REQUIRED_EVIDENCE,
        ]
    )


def _artifact_hash_requirements(
    workspace: JobWorkspace,
    build_contract: BuildContract,
    artifact_manifest: ArtifactManifest,
) -> tuple[list[dict[str, JsonValue]], list[str]]:
    by_path: dict[str, str] = {}
    rejected: list[str] = []
    for path, digest in build_contract.locked_input_hashes.items():
        try:
            by_path[_safe_relative_path(path, "locked_input_hashes")] = digest
        except SchemaValidationError:
            rejected.append(path)
    for record in artifact_manifest.locked_records():
        try:
            by_path[_safe_relative_path(record.path, "artifact_manifest.locked_records")] = record.sha256
        except SchemaValidationError:
            rejected.append(record.path)
    requirements = [
        {
            "path": path,
            "sha256": _sha256_ref(digest),
            "metadata": {"source": "SkillFoundry locked input"},
        }
        for path, digest in sorted(by_path.items())
    ]
    return requirements, rejected


def _forbidden_paths(blocked_paths: list[str]) -> tuple[list[str], list[str]]:
    accepted: list[str] = []
    rejected: list[str] = []
    for path in [*_DEFAULT_FORBIDDEN_PATHS, *blocked_paths]:
        try:
            accepted.append(_safe_relative_path(path, "blocked_paths"))
        except SchemaValidationError:
            rejected.append(path)
    return _dedupe(accepted), _dedupe(rejected)


def _forbidden_write_paths(blocked_paths: list[str]) -> tuple[list[str], list[str]]:
    accepted: list[str] = []
    rejected: list[str] = []
    for path in [*_DEFAULT_FORBIDDEN_WRITE_PATHS, *blocked_paths]:
        try:
            accepted.append(_safe_relative_path(path, "blocked_paths"))
        except SchemaValidationError:
            rejected.append(path)
    return _dedupe(accepted), _dedupe(rejected)


def _required_safe_paths(paths: list[str], field_name: str) -> list[str]:
    return [_safe_relative_path(path, field_name) for path in paths]


def _safe_relative_path(path: str, field_name: str) -> str:
    try:
        return validate_relative_path(path).as_posix()
    except PathSecurityError as exc:
        raise SchemaValidationError(f"{field_name} contains unsafe path {path!r}: {exc}") from exc


def _source_refs(build_contract: BuildContract) -> dict[str, JsonValue]:
    refs: dict[str, JsonValue] = {
        "skill_spec": build_contract.skill_spec_ref,
        "verification_spec": build_contract.verification_spec_ref,
        "build_contract": "build_contract.yaml",
        "artifact_manifest": "artifact_manifest.json",
        "worker_input": "worker_input.md",
    }
    if build_contract.task_contract_ref:
        refs["task_contract"] = build_contract.task_contract_ref
    return refs


def _source_hashes(workspace: JobWorkspace, records: _WorkspaceRecords) -> dict[str, JsonValue]:
    source_refs = _source_refs(records.build_contract)
    hashes: dict[str, JsonValue] = {
        "skill_spec_payload": sha256_json(records.skill_spec.to_dict()),
        "verification_spec_payload": sha256_json(records.verification_spec.to_dict()),
        "build_contract_payload": sha256_json(records.build_contract.to_dict()),
        "artifact_manifest_payload": sha256_json(records.artifact_manifest.to_dict()),
    }
    for name, ref in source_refs.items():
        if not isinstance(ref, str):
            continue
        try:
            path = workspace.resolve_path(ref, must_exist=True)
        except PathSecurityError:
            continue
        hashes[name] = sha256_file(path)
    return hashes


def _cache_epoch_id(
    *,
    goal_contract: GoalContract,
    verification_gate: VerificationGate,
    worker_kind: str,
    worker_name: str,
    allowed_paths: list[str],
    forbidden_paths: list[str],
    visible_context: list[dict[str, JsonValue]],
    forbidden_context: list[dict[str, JsonValue]],
    tool_permissions: list[dict[str, JsonValue]],
    source_hashes: dict[str, JsonValue],
) -> str:
    payload = {
        "goal_contract_hash": goal_contract.contract_hash,
        "verification_gate_hash": verification_gate.gate_hash,
        "worker_kind": worker_kind,
        "worker_name": worker_name,
        "allowed_paths": allowed_paths,
        "forbidden_paths": forbidden_paths,
        "visible_context": visible_context,
        "forbidden_context": forbidden_context,
        "tool_permissions": tool_permissions,
        "source_hashes": source_hashes,
    }
    return "skillfoundry-cache-epoch-" + sha256_json(payload)[:24]


def _sha256_ref(digest: str) -> str:
    return digest if digest.startswith("sha256:") else f"sha256:{digest}"


def _contains_manual_authority(values: list[str], *, review_only: bool = False) -> bool:
    text = "\n".join(values).lower()
    review_markers = ("manual review", "human review", "review required")
    human_markers = ("human-only", "human authority", "manual acceptance", "user acceptance")
    if review_only:
        return any(marker in text for marker in review_markers)
    return any(marker in text for marker in human_markers)


def _id_fragment(value: str) -> str:
    return (
        value.replace("/", "-")
        .replace("_", "-")
        .replace(".", "-")
        .replace(":", "-")
        .lower()
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _write_record(workspace: JobWorkspace, relative_path: str, payload: dict[str, JsonValue]) -> None:
    path = workspace.resolve_path(relative_path)
    Path(path).write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json_record(workspace: JobWorkspace, relative_path: str) -> dict[str, JsonValue]:
    path = workspace.resolve_path(relative_path, must_exist=True)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SchemaValidationError(f"{relative_path} must contain a JSON object")
    return ensure_json_compatible(payload)  # type: ignore[return-value]
