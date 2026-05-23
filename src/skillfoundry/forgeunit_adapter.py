"""Thin SkillFoundry product adapter for ForgeUnit work-unit execution."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from .graph_v2 import SkillFoundryV2State, V2Route, V2Stage, V2Status, validate_v2_graph_state
from .schema import sha256_file
from .workspace import JOB_ID_RE, JobWorkspace


FORGEUNIT_ADAPTER_VERSION = "skillfoundry.forgeunit_adapter.v1"
FORGEUNIT_TASK_YAML_REF = "task.yaml"
FORGEUNIT_SUMMARY_REF = "contextforge/forgeunit_summary.json"
FORGEUNIT_CODEX_EXEC_UNIT_ID = "execute"


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
