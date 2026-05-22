"""SkillFoundry v2 worker boundaries for ContextForge Goal Harness nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Literal

from contextforge import PolicyViolation, WorkerRunRequest, WorkerRunResult, enforce_write_scope

from .schema import JsonValue, ensure_json_compatible
from .workspace import JobWorkspace


WORKERS_V2_VERSION = "skillfoundry.workers_v2.v1"
WorkerBoundaryStatus = Literal["completed", "failed", "blocked", "cancelled"]

_FAKE_PACKAGE_REF = "package/SKILL.md"
_FAKE_REPORT_REF = "attempts/fake_worker_report.json"
_FAKE_TRANSCRIPT_REF = "attempts/fake_worker_transcript.log"


@dataclass(frozen=True)
class FakeSkillBuilderWorker:
    """Deterministic v2 builder that implements the ContextForge worker boundary."""

    workspace: JobWorkspace
    name: str = "skillfoundry-fake-skill-builder"
    status: WorkerBoundaryStatus = "completed"
    failure_class: str | None = None
    extra_changed_files: tuple[str, ...] = ()

    kind: str = "fake_model"

    def run(self, request: WorkerRunRequest) -> WorkerRunResult:
        planned_changes = _fake_planned_changes(self.status, self.extra_changed_files)
        policy_error = _write_scope_error(planned_changes, request)
        if policy_error is not None:
            diagnostic_changes = [_FAKE_REPORT_REF, _FAKE_TRANSCRIPT_REF]
            diagnostic_policy_error = _write_scope_error(diagnostic_changes, request)
            if diagnostic_policy_error is not None:
                return _worker_result(
                    request,
                    worker_name=self.name,
                    worker_kind=self.kind,
                    status="failed",
                    final_output_ref=None,
                    summary="Fake SkillFoundry builder failed closed before filesystem diagnostics.",
                    failure_class="write_scope_violation",
                    artifact_refs=[],
                    changed_files=[],
                    attempted_changed_files=planned_changes,
                    metadata={
                        "policy_error": policy_error,
                        "diagnostic_policy_error": diagnostic_policy_error,
                    },
                )
            _write_fake_worker_report(
                self.workspace,
                request,
                _FAKE_REPORT_REF,
                "failed",
                "write_scope_violation",
                changed_files=diagnostic_changes,
                attempted_changed_files=planned_changes,
                policy_error=policy_error,
            )
            _write_transcript(
                self.workspace,
                _FAKE_TRANSCRIPT_REF,
                [
                    "SkillFoundry v2 fake worker failed before writing candidate artifacts.",
                    f"policy_error={policy_error}",
                ],
            )
            return _worker_result(
                request,
                worker_name=self.name,
                worker_kind=self.kind,
                status="failed",
                final_output_ref=_FAKE_REPORT_REF,
                summary="Fake SkillFoundry builder failed closed on write scope policy.",
                failure_class="write_scope_violation",
                artifact_refs=diagnostic_changes,
                changed_files=diagnostic_changes,
                attempted_changed_files=planned_changes,
                metadata={"policy_error": policy_error},
            )

        changed_files = list(planned_changes)
        if self.status == "completed":
            _write_fake_skill_package(self.workspace, request, _FAKE_PACKAGE_REF)
        _write_fake_worker_report(
            self.workspace,
            request,
            _FAKE_REPORT_REF,
            self.status,
            self.failure_class,
            changed_files=changed_files,
            attempted_changed_files=planned_changes,
            policy_error=None,
        )
        _write_transcript(
            self.workspace,
            _FAKE_TRANSCRIPT_REF,
            [
                "SkillFoundry v2 fake worker consumed ContextForge prompt/context boundary.",
                f"goal_run_id={request.goal_run_id}",
                f"context_view_id={request.context_view.context_view_id}",
                f"prompt_cache_plan_id={request.cache_plan.cache_plan_id}",
                f"status={self.status}",
            ],
        )
        artifact_refs = [_FAKE_REPORT_REF, _FAKE_TRANSCRIPT_REF]
        if self.status == "completed":
            artifact_refs.insert(0, _FAKE_PACKAGE_REF)
        return _worker_result(
            request,
            worker_name=self.name,
            worker_kind=self.kind,
            status=self.status,
            final_output_ref=_FAKE_PACKAGE_REF if self.status == "completed" else _FAKE_REPORT_REF,
            summary="Fake SkillFoundry builder wrote deterministic offline artifacts.",
            failure_class=self.failure_class,
            artifact_refs=artifact_refs,
            changed_files=changed_files,
            attempted_changed_files=planned_changes,
            metadata={"fake_skillfoundry_worker": True},
        )


@dataclass(frozen=True)
class CodexThreadSkillBuilderWorker:
    """Black-box Codex SDK thread boundary for SkillFoundry v2.

    ContextForge controls and records the node boundary. It does not claim
    access to the internal Codex prompt, cache chain, compaction, or tool loop.
    """

    workspace: JobWorkspace
    name: str = "skillfoundry-codex-thread-builder"
    thread_id: str | None = None
    transcript_ref: str | None = None
    diff_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    status: WorkerBoundaryStatus = "completed"
    failure_class: str | None = None
    final_output_ref: str | None = None
    summary: str = "Codex thread worker completed with SkillFoundry boundary evidence."

    kind: str = "codex_sdk_thread"

    def run(self, request: WorkerRunRequest) -> WorkerRunResult:
        policy_error = _write_scope_error(list(self.changed_files), request)
        evidence_error = _boundary_evidence_error(
            artifact_refs=list(self.artifact_refs),
            required_refs=[self.transcript_ref],
        )
        failure_class = _first_failure("write_scope_violation" if policy_error else None, evidence_error)
        status = "failed" if failure_class is not None else self.status
        metadata = {
            "black_box_worker": True,
            "worker_kind": self.kind,
            "thread_id": self.thread_id or _synthetic_thread_id(request),
            "transcript_ref": self.transcript_ref,
            "diff_refs": list(self.diff_refs),
            "changed_files": list(self.changed_files),
            "attempted_changed_files": list(self.changed_files),
            "policy_error": policy_error,
            "boundary_evidence_error": evidence_error,
            "internal_prompt_replay_available": False,
            "internal_cache_chain_control_available": False,
            "internal_tool_loop_replay_available": False,
            "contextforge_controls_internal_codex_loop": False,
        }
        return _worker_result(
            request,
            worker_name=self.name,
            worker_kind=self.kind,
            status=status,
            final_output_ref=self.final_output_ref or self.transcript_ref,
            summary=self.summary,
            failure_class=failure_class or self.failure_class,
            artifact_refs=[*self.artifact_refs, *self.diff_refs, *([self.transcript_ref] if self.transcript_ref else [])],
            changed_files=list(self.changed_files),
            attempted_changed_files=list(self.changed_files),
            usage_unavailable_reason="codex_thread_boundary_does_not_report_provider_usage",
            metadata=metadata,
        )


@dataclass(frozen=True)
class ExternalAgentSkillBuilderWorker:
    """Generic external-agent boundary with explicit artifact and evidence refs."""

    workspace: JobWorkspace
    name: str
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    status: WorkerBoundaryStatus = "completed"
    failure_class: str | None = None
    final_output_ref: str | None = None
    summary: str = "External agent worker completed with SkillFoundry boundary evidence."

    kind: str = "external_agent"

    def run(self, request: WorkerRunRequest) -> WorkerRunResult:
        policy_error = _write_scope_error(list(self.changed_files), request)
        evidence_error = _boundary_evidence_error(
            artifact_refs=list(self.artifact_refs),
            required_refs=list(self.evidence_refs),
        )
        failure_class = _first_failure("write_scope_violation" if policy_error else None, evidence_error)
        status = "failed" if failure_class is not None else self.status
        metadata = {
            "black_box_worker": True,
            "worker_kind": self.kind,
            "evidence_refs": list(self.evidence_refs),
            "changed_files": list(self.changed_files),
            "attempted_changed_files": list(self.changed_files),
            "policy_error": policy_error,
            "boundary_evidence_error": evidence_error,
            "internal_prompt_replay_available": False,
            "internal_tool_loop_replay_available": False,
        }
        return _worker_result(
            request,
            worker_name=self.name,
            worker_kind=self.kind,
            status=status,
            final_output_ref=self.final_output_ref or _first_ref(self.artifact_refs, self.evidence_refs),
            summary=self.summary,
            failure_class=failure_class or self.failure_class,
            artifact_refs=[*self.artifact_refs, *self.evidence_refs],
            changed_files=list(self.changed_files),
            attempted_changed_files=list(self.changed_files),
            usage_unavailable_reason="external_agent_boundary_does_not_report_provider_usage",
            metadata=metadata,
        )


def _fake_planned_changes(status: WorkerBoundaryStatus, extra_changed_files: tuple[str, ...]) -> list[str]:
    changes = [_FAKE_REPORT_REF, _FAKE_TRANSCRIPT_REF]
    if status == "completed":
        changes.insert(0, _FAKE_PACKAGE_REF)
    changes.extend(extra_changed_files)
    return changes


def _worker_result(
    request: WorkerRunRequest,
    *,
    worker_name: str,
    worker_kind: str,
    status: str,
    final_output_ref: str | None,
    summary: str,
    failure_class: str | None,
    artifact_refs: list[str],
    changed_files: list[str],
    attempted_changed_files: list[str],
    usage_unavailable_reason: str = "offline_fake_worker",
    metadata: dict[str, JsonValue | list[str] | dict[str, JsonValue] | None] | None = None,
) -> WorkerRunResult:
    return WorkerRunResult(
        status=status,
        worker_name=worker_name,
        final_output_ref=final_output_ref,
        summary=summary,
        failure_class=failure_class,
        prompt_view_ids=[request.prompt_view.id],
        artifact_ids=[_artifact_id(request.metadata.get("skillfoundry_job_id"), ref) for ref in artifact_refs],
        usage_summary={
            "provider": "offline" if worker_kind == "fake_model" else worker_kind,
            "model": worker_kind,
            "expected_cacheable_tokens": request.cache_plan.expected_cacheable_tokens,
            "cache_telemetry_status": request.cache_plan.cache_telemetry_status,
            "usage_unavailable_reason": usage_unavailable_reason,
        },
        metadata={
            "workers_v2": WORKERS_V2_VERSION,
            "worker_kind": worker_kind,
            "changed_files": list(changed_files),
            "attempted_changed_files": list(attempted_changed_files),
            "artifact_refs": list(artifact_refs),
            "worker_self_report_is_not_acceptance": True,
            **dict(metadata or {}),
        },
    )


def _write_fake_skill_package(
    workspace: JobWorkspace,
    request: WorkerRunRequest,
    package_ref: str,
) -> None:
    content = "\n".join(
        [
            "---",
            "name: generated-review-assistant",
            "description: Deterministic offline SkillFoundry package generated by Goal Harness tests.",
            "---",
            "",
            "# Generated Review Assistant",
            "",
            "## Overview",
            "",
            "This deterministic package is generated by the SkillFoundry v2 Goal Harness fixture.",
            "",
            "## When To Use",
            "",
            "Use this skill when a user asks for repository review assistance.",
            "",
            "## When Not To Use",
            "",
            "- Do not use it as evidence that worker output was verified or registered.",
            "",
            "## Inputs",
            "",
            "- A frozen SkillFoundry skill specification.",
            "- Frozen acceptance criteria and verification requirements.",
            "",
            "## Outputs",
            "",
            "- A candidate Codex Skill package under `package/`.",
            "",
            "## Workflow",
            "",
            "- Inspect repository-local evidence before reporting findings.",
            "- Report correctness risks before summaries.",
            "- Include file and line references for each finding.",
            "",
            "## Safety",
            "",
            "- Do not claim verification or registry approval.",
            "",
            "## Goal Harness Evidence",
            "",
            f"- Goal run: {request.goal_run_id}",
            f"- Context view: {request.context_view.context_view_id}",
            f"- Prompt cache plan: {request.cache_plan.cache_plan_id}",
            "",
        ]
    )
    _write_text(workspace, package_ref, content)


def _write_fake_worker_report(
    workspace: JobWorkspace,
    request: WorkerRunRequest,
    report_ref: str,
    status: str,
    failure_class: str | None,
    *,
    changed_files: list[str],
    attempted_changed_files: list[str],
    policy_error: str | None,
) -> None:
    payload = {
        "schema_version": "skillfoundry.fake_worker_report.v2",
        "workers_v2": WORKERS_V2_VERSION,
        "job_id": workspace.job_id,
        "goal_run_id": request.goal_run_id,
        "context_view_id": request.context_view.context_view_id,
        "prompt_view_id": request.prompt_view.id,
        "cache_plan_id": request.cache_plan.cache_plan_id,
        "status": status,
        "failure_class": failure_class,
        "changed_files": changed_files,
        "attempted_changed_files": attempted_changed_files,
        "policy_error": policy_error,
        "worker_self_report_is_not_acceptance": True,
    }
    _write_json(workspace, report_ref, payload)


def _write_transcript(workspace: JobWorkspace, transcript_ref: str, lines: list[str]) -> None:
    _write_text(workspace, transcript_ref, "\n".join(lines) + "\n")


def _write_json(workspace: JobWorkspace, relative_path: str, payload: dict[str, JsonValue]) -> None:
    compatible = ensure_json_compatible(payload)
    if not isinstance(compatible, dict):
        raise ValueError("worker report payload must be a JSON object")
    _write_text(
        workspace,
        relative_path,
        json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )


def _write_text(workspace: JobWorkspace, relative_path: str, content: str) -> None:
    path = workspace.resolve_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_scope_error(paths: list[str], request: WorkerRunRequest) -> str | None:
    try:
        enforce_write_scope(paths, request.node_contract.write_scope)
    except PolicyViolation as exc:
        return str(exc)
    return None


def _boundary_evidence_error(*, artifact_refs: list[str], required_refs: list[str | None]) -> str | None:
    if not artifact_refs:
        return "missing_boundary_artifacts"
    if not required_refs:
        return "missing_boundary_evidence"
    if any(ref is None or not str(ref).strip() for ref in required_refs):
        return "missing_boundary_evidence"
    return None


def _first_failure(*failure_classes: str | None) -> str | None:
    for failure_class in failure_classes:
        if failure_class:
            return failure_class
    return None


def _first_ref(*ref_groups: tuple[str, ...]) -> str | None:
    for refs in ref_groups:
        if refs:
            return refs[0]
    return None


def _artifact_id(job_id: object, ref: str) -> str:
    prefix = str(job_id) if isinstance(job_id, str) and job_id else "skillfoundry-job"
    return f"{prefix}:{ref}"


def _synthetic_thread_id(request: WorkerRunRequest) -> str:
    return f"thread-{request.goal_run_id}-{request.node_contract.node_id}"


__all__ = [
    "CodexThreadSkillBuilderWorker",
    "ExternalAgentSkillBuilderWorker",
    "FakeSkillBuilderWorker",
    "WORKERS_V2_VERSION",
]
