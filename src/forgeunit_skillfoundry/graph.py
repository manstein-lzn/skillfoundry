"""Thin LangGraph product graph for SkillFoundry on ForgeUnit."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from skillfoundry.graph_v2 import SkillFoundryV2State, V2Route, V2Stage, V2Status, validate_v2_graph_state
from skillfoundry.schema import sha256_file
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace

from .config import ForgeUnitSkillFoundryError, SkillFactoryConfig, SkillFactoryMode
from .engine import ForgeUnitSkillFactoryEngine
from .report import write_evidence_summary
from .state import FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF, write_product_state


FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF = "contextforge/forgeunit_skillfoundry_graph_state.json"
GRAPH_STATE_SCHEMA_VERSION = "forgeunit_skillfoundry.graph_state.v1"


@dataclass(frozen=True)
class SkillFactoryGraphResult:
    """Result returned by the LangGraph product skeleton."""

    job_id: str
    mode: SkillFactoryMode
    workspace_root: Path
    registry_path: Path
    state: SkillFoundryV2State


def compile_skill_factory_graph(
    config: SkillFactoryConfig,
    *,
    engine: ForgeUnitSkillFactoryEngine | None = None,
) -> Any:
    """Compile the thin product-stage LangGraph for one configured run."""

    selected_engine = engine or ForgeUnitSkillFactoryEngine()
    graph = StateGraph(SkillFoundryV2State)
    graph.add_node("prepare_workspace", _prepare_workspace_node(config))
    graph.add_node("run_forgeunit_engine", _run_forgeunit_engine_node(config, selected_engine))
    graph.add_node("verify_product_state", _verify_product_state_node(config))
    graph.add_node("emit_product_report", _emit_product_report_node(config))
    graph.add_edge(START, "prepare_workspace")
    graph.add_edge("prepare_workspace", "run_forgeunit_engine")
    graph.add_edge("run_forgeunit_engine", "verify_product_state")
    graph.add_edge("verify_product_state", "emit_product_report")
    graph.add_edge("emit_product_report", END)
    return graph.compile()


def run_skill_factory_graph(
    config: SkillFactoryConfig,
    *,
    engine: ForgeUnitSkillFactoryEngine | None = None,
) -> SkillFactoryGraphResult:
    """Run the LangGraph product skeleton and persist its refs-only final state."""

    graph = compile_skill_factory_graph(config, engine=engine)
    state = graph.invoke({"job_id": config.job_id})
    validate_v2_graph_state(state)
    workspace = JobWorkspace(root=config.runs_root / config.job_id, job_id=config.job_id)
    return SkillFactoryGraphResult(
        job_id=config.job_id,
        mode=config.mode,
        workspace_root=workspace.root,
        registry_path=config.registry_path,
        state=state,
    )


def _prepare_workspace_node(config: SkillFactoryConfig) -> Any:
    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        _require_config_job_state(config, state)
        workspace = _prepare_workspace(config)
        workspace.check_locked_inputs()
        next_state: SkillFoundryV2State = {
            "schema_version": "skillfoundry.graph_v2_state.v1",
            "job_id": config.job_id,
            "stage": V2Stage.FREEZE_CONTRACTS.value,
            "status": V2Status.READY_TO_BUILD.value,
            "attempt_count": 0,
            "attempt_limit": config.attempt_limit,
            "refs": {
                "skill_spec": "skill_spec.yaml",
                "verification_spec": "verification_spec.yaml",
                "build_contract": "build_contract.yaml",
                "worker_input_ref": "worker_input.md",
                "artifact_manifest": "artifact_manifest.json",
            },
            "hashes": {
                "skill_spec": sha256_file(workspace.resolve_path("skill_spec.yaml", must_exist=True)),
                "verification_spec": sha256_file(
                    workspace.resolve_path("verification_spec.yaml", must_exist=True)
                ),
                "build_contract": sha256_file(workspace.resolve_path("build_contract.yaml", must_exist=True)),
                "worker_input_ref": sha256_file(workspace.resolve_path("worker_input.md", must_exist=True)),
                "artifact_manifest": sha256_file(workspace.resolve_path("artifact_manifest.json", must_exist=True)),
            },
            "contextforge": {
                "forgeunit_skillfoundry_engine": "forgeunit",
                "forgeunit_skillfoundry_mode": config.mode,
                "forgeunit_skillfoundry_graph_node": "prepare_workspace",
                "worker_self_report_is_not_acceptance": True,
            },
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
        }
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def _run_forgeunit_engine_node(config: SkillFactoryConfig, engine: ForgeUnitSkillFactoryEngine) -> Any:
    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        _require_config_job_state(config, state)
        result = engine.run(config)
        next_state = dict(result.state)
        contextforge = dict(next_state.get("contextforge", {}))
        contextforge.update(
            {
                "forgeunit_skillfoundry_engine": "forgeunit",
                "forgeunit_skillfoundry_mode": result.mode,
                "forgeunit_skillfoundry_graph_node": "run_forgeunit_engine",
            }
        )
        next_state["contextforge"] = contextforge
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def _verify_product_state_node(config: SkillFactoryConfig) -> Any:
    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        _require_config_job_state(config, state)
        _require_verified_registered_state(state)
        workspace = JobWorkspace(root=config.runs_root / config.job_id, job_id=config.job_id)
        next_state = write_product_state(
            workspace,
            state,
            mode=config.mode,
            registry_path=config.registry_path,
            created_at=config.created_at,
        )
        contextforge = dict(next_state.get("contextforge", {}))
        contextforge["forgeunit_skillfoundry_graph_node"] = "verify_product_state"
        next_state["contextforge"] = contextforge
        validate_v2_graph_state(next_state)
        return next_state

    return _node


def _emit_product_report_node(config: SkillFactoryConfig) -> Any:
    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        _require_config_job_state(config, state)
        _require_verified_registered_state(state)
        workspace = JobWorkspace(root=config.runs_root / config.job_id, job_id=config.job_id)
        workspace.resolve_path("contextforge").mkdir(parents=True, exist_ok=True)
        refs = dict(state.get("refs", {}))
        refs["forgeunit_skillfoundry_graph_state"] = FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF
        contextforge = dict(state.get("contextforge", {}))
        contextforge.update(
            {
                "forgeunit_skillfoundry_graph_node": "emit_product_report",
                "forgeunit_skillfoundry_graph_state_ref": FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF,
            }
        )
        final_state: SkillFoundryV2State = dict(state)
        final_state.update(
            {
                "stage": V2Stage.EMIT_REPORT.value,
                "status": V2Status.REPORT_EMITTED.value,
                "refs": refs,
                "contextforge": contextforge,
                "human_review_required": False,
                "next_route": V2Route.CONTINUE.value,
            }
        )
        validate_v2_graph_state(final_state)
        graph_state_payload = _graph_state_payload(final_state, config=config)
        workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF).write_text(
            json.dumps(graph_state_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        final_state = write_evidence_summary(
            workspace,
            final_state,
            mode=config.mode,
            registry_path=config.registry_path,
            created_at=config.created_at,
        )
        return final_state

    return _node


def _prepare_workspace(config: SkillFactoryConfig) -> JobWorkspace:
    workspace_root = config.runs_root / config.job_id
    if workspace_root.exists() and (workspace_root / "artifact_manifest.json").is_file() and not config.overwrite_workspace:
        return JobWorkspace(root=workspace_root, job_id=config.job_id)
    return initialize_job_workspace(
        config.runs_root,
        config.job_id,
        worker_input=config.worker_input,
        overwrite=config.overwrite_workspace,
    )


def _require_config_job_state(config: SkillFactoryConfig, state: SkillFoundryV2State) -> None:
    validate_v2_graph_state(state)
    job_id = state.get("job_id")
    if job_id != config.job_id:
        raise ForgeUnitSkillFoundryError(f"graph state job_id must be {config.job_id!r}, got {job_id!r}")


def _require_verified_registered_state(state: SkillFoundryV2State) -> None:
    validate_v2_graph_state(state)
    refs = state.get("refs", {})
    contextforge = state.get("contextforge", {})
    if not isinstance(refs, dict) or not isinstance(contextforge, dict):
        raise ForgeUnitSkillFoundryError("graph state refs/contextforge must be mappings")
    required_refs = {
        "final_report",
        "registry_decision",
        "registry_entry",
        "skillfoundry_verification_result",
    }
    missing = sorted(ref for ref in required_refs if not refs.get(ref))
    if missing:
        raise ForgeUnitSkillFoundryError("registered product state missing refs: " + ", ".join(missing))
    if contextforge.get("last_verification_status") != "passed":
        raise ForgeUnitSkillFoundryError("product graph requires passed SkillFoundry verification")
    if contextforge.get("registry_approved") is not True:
        raise ForgeUnitSkillFoundryError("product graph requires registry approval")


def _graph_state_payload(state: SkillFoundryV2State, *, config: SkillFactoryConfig) -> dict[str, Any]:
    refs = state.get("refs", {})
    contextforge = state.get("contextforge", {})
    assert isinstance(refs, dict)
    assert isinstance(contextforge, dict)
    return {
        "schema_version": GRAPH_STATE_SCHEMA_VERSION,
        "job_id": config.job_id,
        "engine": "forgeunit",
        "mode": config.mode,
        "stage": state.get("stage"),
        "status": state.get("status"),
        "refs": {
            key: value
            for key, value in refs.items()
            if key
            in {
                "final_report",
                "acceptance_coverage_plan",
                "acceptance_coverage_result",
                "forgeunit_repair_packet",
                "forgeunit_skillfoundry_graph_state",
                "forgeunit_skillfoundry_product_state",
                "registry_decision",
                "registry_entry",
                "skillfoundry_verification_result",
            }
            and isinstance(value, str)
        },
        "contextforge": {
            key: value
            for key, value in contextforge.items()
            if key
            in {
                "forgeunit_skillfoundry_engine",
                "forgeunit_skillfoundry_graph_node",
                "forgeunit_skillfoundry_mode",
                "acceptance_coverage_passed",
                "last_verification_status",
                "registry_approved",
                "registry_skill_id",
                "registry_version",
            }
            and isinstance(value, (str, int, bool))
        },
        "trust_boundaries": {
            "worker_self_report_is_not_acceptance": True,
            "raw_prompt_included": False,
            "raw_transcript_included": False,
            "raw_worker_input_included": False,
            "package_body_included": False,
            "command_string_included": False,
        },
    }
