"""SkillFoundry v2 worker boundaries for ContextForge Goal Harness nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import PurePosixPath
from typing import Any, Literal, Mapping

from contextforge import (
    ContextKernel,
    ContextLedger,
    FakeModelClient,
    ModelCallEnvelope,
    PolicyViolation,
    WorkerInfo,
    WorkerRunRequest,
    WorkerRunResult,
    context_request_from_agent_node_contract,
    enforce_write_scope,
)

from .schema import JsonValue, ensure_json_compatible
from .security import PathSecurityError, validate_relative_path
from .workspace import JobWorkspace


WORKERS_V2_VERSION = "skillfoundry.workers_v2.v1"
WorkerBoundaryStatus = Literal["completed", "failed", "blocked", "cancelled"]

OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION = "skillfoundry.owned_llm_worker_output.v1"

_FAKE_PACKAGE_REF = "package/SKILL.md"
_FAKE_REPORT_REF = "attempts/fake_worker_report.json"
_FAKE_TRANSCRIPT_REF = "attempts/fake_worker_transcript.log"
_OWNED_LLM_REPORT_TEMPLATE = "attempts/{attempt_id}/owned_llm_worker_report.json"
_OWNED_LLM_TRANSCRIPT_TEMPLATE = "attempts/{attempt_id}/owned_llm_worker_transcript.log"
_DEFAULT_LEDGER_REF = "contextforge/ledger.sqlite3"
_DEFAULT_OWNED_MODEL = "skillfoundry-owned-llm-fake-model"
_DEFAULT_OWNED_PROVIDER = "fake"


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
class OwnedLLMSkillBuilderWorker:
    """White-box owned LLM worker behind the ContextForge Goal Harness boundary."""

    workspace: JobWorkspace
    name: str = "skillfoundry-owned-llm-builder"
    client: Any | None = None
    provider: str = _DEFAULT_OWNED_PROVIDER
    model: str = _DEFAULT_OWNED_MODEL
    model_params: Mapping[str, JsonValue] = field(default_factory=lambda: {"temperature": 0})
    ledger_ref: str = _DEFAULT_LEDGER_REF

    kind: str = "llm"

    def run(self, request: WorkerRunRequest) -> WorkerRunResult:
        attempt_id = _attempt_id(request)
        report_ref = _OWNED_LLM_REPORT_TEMPLATE.format(attempt_id=attempt_id)
        transcript_ref = _OWNED_LLM_TRANSCRIPT_TEMPLATE.format(attempt_id=attempt_id)
        diagnostic_refs = [report_ref, transcript_ref]
        diagnostic_policy_error = _write_scope_error(diagnostic_refs, request)

        try:
            record = _invoke_owned_llm(self, request)
        except Exception as exc:
            return _owned_llm_failed_result(
                request,
                worker=self,
                report_ref=report_ref,
                transcript_ref=transcript_ref,
                failure_class="contextforge_model_call_failed",
                summary=f"Owned LLM call failed before a model record was available: {type(exc).__name__}: {exc}",
                diagnostic_policy_error=diagnostic_policy_error,
            )

        model_call_ids = [record.id]
        prompt_view_ids = _dedupe([request.prompt_view.id, record.prompt_view_id])
        if record.error is not None:
            return _owned_llm_failed_result(
                request,
                worker=self,
                report_ref=report_ref,
                transcript_ref=transcript_ref,
                failure_class="provider_error",
                summary=f"Owned LLM provider returned {record.error.error_type}: {record.error.message}",
                diagnostic_policy_error=diagnostic_policy_error,
                model_call_ids=model_call_ids,
                prompt_view_ids=prompt_view_ids,
                replay_bundle_ref=record.replay_bundle_ref,
            )
        if record.response is None:
            return _owned_llm_failed_result(
                request,
                worker=self,
                report_ref=report_ref,
                transcript_ref=transcript_ref,
                failure_class="provider_error",
                summary="Owned LLM call did not return a response.",
                diagnostic_policy_error=diagnostic_policy_error,
                model_call_ids=model_call_ids,
                prompt_view_ids=prompt_view_ids,
                replay_bundle_ref=record.replay_bundle_ref,
            )

        try:
            package_files = _parse_owned_llm_output(record.response.text)
        except ValueError as exc:
            return _owned_llm_failed_result(
                request,
                worker=self,
                report_ref=report_ref,
                transcript_ref=transcript_ref,
                failure_class="model_output_invalid",
                summary=str(exc),
                diagnostic_policy_error=diagnostic_policy_error,
                model_call_ids=model_call_ids,
                prompt_view_ids=prompt_view_ids,
                replay_bundle_ref=record.replay_bundle_ref,
            )

        changed_files = [item.ref for item in package_files]
        planned_changes = [*changed_files, *diagnostic_refs]
        policy_error = _write_scope_error(planned_changes, request)
        if policy_error is not None:
            return _owned_llm_failed_result(
                request,
                worker=self,
                report_ref=report_ref,
                transcript_ref=transcript_ref,
                failure_class="write_scope_violation",
                summary=f"Owned LLM output violated write scope: {policy_error}",
                diagnostic_policy_error=diagnostic_policy_error,
                model_call_ids=model_call_ids,
                prompt_view_ids=prompt_view_ids,
                replay_bundle_ref=record.replay_bundle_ref,
                attempted_changed_files=planned_changes,
                policy_error=policy_error,
            )

        write_preflight_error = _write_security_error(self.workspace, planned_changes)
        if write_preflight_error is not None:
            return _owned_llm_failed_result(
                request,
                worker=self,
                report_ref=report_ref,
                transcript_ref=transcript_ref,
                failure_class=write_preflight_error.failure_class,
                summary=(
                    "Owned LLM output could not be written safely: "
                    f"{write_preflight_error.message}"
                ),
                diagnostic_policy_error=diagnostic_policy_error,
                model_call_ids=model_call_ids,
                prompt_view_ids=prompt_view_ids,
                replay_bundle_ref=record.replay_bundle_ref,
                attempted_changed_files=planned_changes,
                policy_error=write_preflight_error.message,
            )

        try:
            for package_file in package_files:
                _write_text(self.workspace, package_file.ref, _ensure_trailing_newline(package_file.content))
            _write_owned_llm_report(
                self.workspace,
                request,
                report_ref,
                status="completed",
                failure_class=None,
                changed_files=[*changed_files, *diagnostic_refs],
                attempted_changed_files=planned_changes,
                model_call_id=record.id,
                model_prompt_view_id=record.prompt_view_id,
                replay_bundle_ref=record.replay_bundle_ref,
                policy_error=None,
            )
            _write_transcript(
                self.workspace,
                transcript_ref,
                [
                    "SkillFoundry v2 owned LLM worker consumed ContextForge Goal Harness prompt/cache boundary.",
                    f"goal_run_id={request.goal_run_id}",
                    f"context_view_id={request.context_view.context_view_id}",
                    f"harness_prompt_view_id={request.prompt_view.id}",
                    f"model_prompt_view_id={record.prompt_view_id}",
                    f"prompt_cache_plan_id={request.cache_plan.cache_plan_id}",
                    f"model_call_id={record.id}",
                    f"replay_bundle_ref={record.replay_bundle_ref}",
                    "worker_self_report_is_not_acceptance=true",
                ],
            )
        except (OSError, PathSecurityError) as exc:
            write_error = _write_error_from_exception(exc)
            return _owned_llm_failed_result(
                request,
                worker=self,
                report_ref=report_ref,
                transcript_ref=transcript_ref,
                failure_class=write_error.failure_class,
                summary=f"Owned LLM output write failed closed: {write_error.message}",
                diagnostic_policy_error=diagnostic_policy_error,
                model_call_ids=model_call_ids,
                prompt_view_ids=prompt_view_ids,
                replay_bundle_ref=record.replay_bundle_ref,
                attempted_changed_files=planned_changes,
                policy_error=write_error.message,
            )

        usage_unavailable_reason = (
            record.usage_unavailable_reason
            if record.usage_id is None
            else None
        )
        if record.usage_id is None and usage_unavailable_reason is None:
            usage_unavailable_reason = "owned_llm_usage_unavailable_from_provider"
        return _worker_result(
            request,
            worker_name=self.name,
            worker_kind=self.kind,
            status="completed",
            final_output_ref=_FAKE_PACKAGE_REF,
            summary="Owned LLM worker wrote a package candidate; verifier, coverage, and registry remain authoritative.",
            failure_class=None,
            artifact_refs=[*changed_files, *diagnostic_refs],
            changed_files=[*changed_files, *diagnostic_refs],
            attempted_changed_files=planned_changes,
            usage_unavailable_reason=usage_unavailable_reason,
            model_call_ids=model_call_ids,
            prompt_view_ids=prompt_view_ids,
            usage_provider=self.provider,
            usage_model=self.model,
            usage_summary_extra={
                "model_call_id": record.id,
                "model_prompt_view_id": record.prompt_view_id,
                "replay_bundle_ref": record.replay_bundle_ref,
                "usage_available": record.usage_id is not None,
                "usage_id": record.usage_id,
            },
            metadata={
                "owned_llm_worker": True,
                "model_call_ids": model_call_ids,
                "model_prompt_view_id": record.prompt_view_id,
                "replay_bundle_ref": record.replay_bundle_ref,
                "contextforge_invoke_model_used": True,
                "contextforge_prompt_view_id": request.prompt_view.id,
                "contextforge_prompt_cache_plan_id": request.cache_plan.cache_plan_id,
            },
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
    usage_unavailable_reason: str | None = "offline_fake_worker",
    model_call_ids: list[str] | None = None,
    prompt_view_ids: list[str] | None = None,
    usage_provider: str | None = None,
    usage_model: str | None = None,
    usage_summary_extra: dict[str, JsonValue] | None = None,
    metadata: dict[str, JsonValue | list[str] | dict[str, JsonValue] | None] | None = None,
) -> WorkerRunResult:
    usage_summary = {
        "provider": usage_provider or ("offline" if worker_kind == "fake_model" else worker_kind),
        "model": usage_model or worker_kind,
        "expected_cacheable_tokens": request.cache_plan.expected_cacheable_tokens,
        "cache_telemetry_status": request.cache_plan.cache_telemetry_status,
    }
    if usage_unavailable_reason is not None:
        usage_summary["usage_unavailable_reason"] = usage_unavailable_reason
    usage_summary.update(dict(usage_summary_extra or {}))
    return WorkerRunResult(
        status=status,
        worker_name=worker_name,
        final_output_ref=final_output_ref,
        summary=summary,
        failure_class=failure_class,
        prompt_view_ids=prompt_view_ids or [request.prompt_view.id],
        model_call_ids=list(model_call_ids or []),
        artifact_ids=[_artifact_id(request.metadata.get("skillfoundry_job_id"), ref) for ref in artifact_refs],
        usage_summary=usage_summary,
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


@dataclass(frozen=True)
class _OwnedLLMPackageFile:
    ref: str
    content: str


@dataclass(frozen=True)
class _WriteError:
    failure_class: str
    message: str


def _invoke_owned_llm(worker: OwnedLLMSkillBuilderWorker, request: WorkerRunRequest):
    ledger = ContextLedger.connect(worker.workspace.resolve_path(worker.ledger_ref, must_exist=True))
    try:
        kernel = ContextKernel(ledger)
        context_request = context_request_from_agent_node_contract(
            request.goal_contract,
            request.node_contract,
            graph_id=request.prompt_view.graph_id,
            run_id=request.prompt_view.run_id,
            task_id=request.prompt_view.task_id,
            allowed_context_item_ids=list(request.context_view.included_item_ids),
            forbidden_context_item_ids=list(request.context_view.forbidden_item_ids),
            created_at=request.prompt_view.created_at,
            metadata={
                **dict(request.metadata),
                "owned_llm_worker_v2": WORKERS_V2_VERSION,
                "source_context_view_id": request.context_view.context_view_id,
                "source_prompt_view_id": request.prompt_view.id,
                "source_prompt_cache_plan_id": request.cache_plan.cache_plan_id,
            },
        )
        envelope = ModelCallEnvelope(
            graph_id=context_request.graph_id,
            run_id=context_request.run_id,
            task_id=context_request.task_id,
            node_id=context_request.node_id,
            intent=context_request.intent,
            context_request=context_request,
            provider=worker.provider,
            model=worker.model,
            model_params=ensure_json_compatible(dict(worker.model_params)),  # type: ignore[arg-type]
            tool_schemas=[],
            worker=WorkerInfo(
                kind="llm",
                name=worker.name,
                version=WORKERS_V2_VERSION,
                metadata={
                    "owned_by": "skillfoundry",
                    "goal_harness_worker": True,
                    "worker_self_report_is_not_acceptance": True,
                },
            ),
            metadata={
                "workers_v2": WORKERS_V2_VERSION,
                "scope": "owned SkillFoundry LLM call through Goal Harness worker boundary",
                "worker_self_report_is_not_acceptance": True,
            },
        )
        client = worker.client if worker.client is not None else FakeModelClient()
        return kernel.invoke_model(envelope, client)
    finally:
        ledger.close()


def _owned_llm_failed_result(
    request: WorkerRunRequest,
    *,
    worker: OwnedLLMSkillBuilderWorker,
    report_ref: str,
    transcript_ref: str,
    failure_class: str,
    summary: str,
    diagnostic_policy_error: str | None,
    model_call_ids: list[str] | None = None,
    prompt_view_ids: list[str] | None = None,
    replay_bundle_ref: str | None = None,
    attempted_changed_files: list[str] | None = None,
    policy_error: str | None = None,
) -> WorkerRunResult:
    diagnostic_refs = [report_ref, transcript_ref]
    can_write_diagnostics = diagnostic_policy_error is None
    diagnostic_write_error = None
    if can_write_diagnostics:
        diagnostic_preflight_error = _write_security_error(worker.workspace, diagnostic_refs)
        if diagnostic_preflight_error is not None:
            diagnostic_write_error = diagnostic_preflight_error.message
            can_write_diagnostics = False
    changed_files = diagnostic_refs if can_write_diagnostics else []
    if can_write_diagnostics:
        written_diagnostic_refs: list[str] = []
        try:
            _write_transcript(
                worker.workspace,
                transcript_ref,
                [
                    "SkillFoundry v2 owned LLM worker failed closed.",
                    f"failure_class={failure_class}",
                    f"summary={summary}",
                    f"policy_error={policy_error}",
                    "worker_self_report_is_not_acceptance=true",
                ],
            )
            written_diagnostic_refs.append(transcript_ref)
            _write_owned_llm_report(
                worker.workspace,
                request,
                report_ref,
                status="failed",
                failure_class=failure_class,
                changed_files=changed_files,
                attempted_changed_files=attempted_changed_files or diagnostic_refs,
                model_call_id=model_call_ids[0] if model_call_ids else None,
                model_prompt_view_id=(prompt_view_ids or [None])[-1],
                replay_bundle_ref=replay_bundle_ref,
                policy_error=policy_error,
            )
            written_diagnostic_refs.append(report_ref)
        except (OSError, PathSecurityError) as exc:
            diagnostic_write_error = _write_error_from_exception(exc).message
            can_write_diagnostics = False
            changed_files = written_diagnostic_refs
        else:
            changed_files = diagnostic_refs
    final_output_ref = None
    if report_ref in changed_files:
        final_output_ref = report_ref
    elif transcript_ref in changed_files:
        final_output_ref = transcript_ref
    return _worker_result(
        request,
        worker_name=worker.name,
        worker_kind=worker.kind,
        status="failed",
        final_output_ref=final_output_ref,
        summary=summary,
        failure_class=failure_class,
        artifact_refs=changed_files,
        changed_files=changed_files,
        attempted_changed_files=attempted_changed_files or diagnostic_refs,
        usage_unavailable_reason="owned_llm_worker_failed_before_verified_usage",
        model_call_ids=list(model_call_ids or []),
        prompt_view_ids=prompt_view_ids or [request.prompt_view.id],
        usage_provider=worker.provider,
        usage_model=worker.model,
        usage_summary_extra={
            "replay_bundle_ref": replay_bundle_ref,
            "diagnostic_policy_error": diagnostic_policy_error,
            "diagnostic_write_error": diagnostic_write_error,
        },
        metadata={
            "owned_llm_worker": True,
            "contextforge_invoke_model_used": bool(model_call_ids),
            "diagnostic_policy_error": diagnostic_policy_error,
            "diagnostic_write_error": diagnostic_write_error,
            "policy_error": policy_error,
            "replay_bundle_ref": replay_bundle_ref,
        },
    )


def _parse_owned_llm_output(response_text: str) -> list[_OwnedLLMPackageFile]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"owned LLM output is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("owned LLM output must be a JSON object")
    if payload.get("schema_version") != OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION!r}")
    skill_markdown = payload.get("skill_markdown")
    if not isinstance(skill_markdown, str) or not skill_markdown.strip():
        raise ValueError("skill_markdown must be a non-empty string")
    _reject_nul(skill_markdown, "skill_markdown")
    files = [_OwnedLLMPackageFile(_FAKE_PACKAGE_REF, skill_markdown)]
    seen = {_FAKE_PACKAGE_REF}
    for field_name, expected_root in {
        "reference_files": "references",
        "script_files": "scripts",
        "test_files": "tests",
    }.items():
        for package_file in _optional_owned_files(payload, field_name, expected_root):
            if package_file.ref in seen:
                raise ValueError(f"duplicate package output path: {package_file.ref}")
            seen.add(package_file.ref)
            files.append(package_file)
    return files


def _optional_owned_files(payload: Mapping[str, Any], field_name: str, expected_root: str) -> list[_OwnedLLMPackageFile]:
    value = payload.get(field_name, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    files: list[_OwnedLLMPackageFile] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(f"{field_name}[{index}] must be an object")
        raw_path = item.get("path")
        content = item.get("content")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"{field_name}[{index}].path must be a non-empty relative path")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"{field_name}[{index}].content must be non-empty")
        _reject_nul(content, f"{field_name}[{index}].content")
        files.append(_OwnedLLMPackageFile(_normalize_owned_package_ref(raw_path, expected_root), content))
    return files


def _normalize_owned_package_ref(raw_path: str, expected_root: str) -> str:
    try:
        safe = validate_relative_path(raw_path)
    except PathSecurityError as exc:
        raise ValueError(f"unsafe package output path {raw_path!r}: {exc}") from exc
    parts = safe.parts
    if parts and parts[0] == "package":
        parts = parts[1:]
    if len(parts) < 2 or parts[0] != expected_root:
        raise ValueError(f"optional file path must stay under package/{expected_root}/: {raw_path}")
    package_ref = PurePosixPath("package", *parts).as_posix()
    validate_relative_path(package_ref)
    return package_ref


def _write_owned_llm_report(
    workspace: JobWorkspace,
    request: WorkerRunRequest,
    report_ref: str,
    *,
    status: str,
    failure_class: str | None,
    changed_files: list[str],
    attempted_changed_files: list[str],
    model_call_id: str | None,
    model_prompt_view_id: str | None,
    replay_bundle_ref: str | None,
    policy_error: str | None,
) -> None:
    payload = {
        "schema_version": "skillfoundry.owned_llm_worker_report.v1",
        "workers_v2": WORKERS_V2_VERSION,
        "job_id": workspace.job_id,
        "goal_run_id": request.goal_run_id,
        "context_view_id": request.context_view.context_view_id,
        "harness_prompt_view_id": request.prompt_view.id,
        "model_prompt_view_id": model_prompt_view_id,
        "prompt_cache_plan_id": request.cache_plan.cache_plan_id,
        "model_call_id": model_call_id,
        "replay_bundle_ref": replay_bundle_ref,
        "status": status,
        "failure_class": failure_class,
        "changed_files": changed_files,
        "attempted_changed_files": attempted_changed_files,
        "policy_error": policy_error,
        "worker_self_report_is_not_acceptance": True,
    }
    _write_json(workspace, report_ref, payload)


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
    safe_ref = validate_relative_path(relative_path)
    root = workspace.root.resolve(strict=True)
    current = root
    for part in safe_ref.parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise PathSecurityError(f"symlink components are not allowed: {current}")
            if not current.is_dir():
                raise PathSecurityError(f"parent path is not a directory: {current}")
            current.resolve(strict=True).relative_to(root)
    parent = root.joinpath(*safe_ref.parts[:-1])
    parent.mkdir(parents=True, exist_ok=True)
    path = workspace.resolve_path(safe_ref.as_posix())
    if path.exists() and not path.is_file():
        raise PathSecurityError(f"target path is not a regular file: {path}")
    path.write_text(content, encoding="utf-8")


def _write_security_error(workspace: JobWorkspace, relative_paths: list[str]) -> _WriteError | None:
    try:
        root = workspace.root.resolve(strict=True)
        for relative_path in relative_paths:
            safe_ref = validate_relative_path(relative_path)
            current = root
            for index, part in enumerate(safe_ref.parts):
                current = current / part
                if current.exists() or current.is_symlink():
                    if current.is_symlink():
                        raise PathSecurityError(f"symlink components are not allowed: {current}")
                    is_final = index == len(safe_ref.parts) - 1
                    if is_final:
                        if not current.is_file():
                            raise PathSecurityError(f"target path is not a regular file: {current}")
                    elif not current.is_dir():
                        raise PathSecurityError(f"parent path is not a directory: {current}")
                    current.resolve(strict=True).relative_to(root)
    except PathSecurityError as exc:
        return _write_error_from_exception(exc)
    except OSError as exc:
        return _write_error_from_exception(exc)
    except ValueError as exc:
        return _WriteError("path_security_violation", str(exc))
    return None


def _write_error_from_exception(exc: OSError | PathSecurityError) -> _WriteError:
    if isinstance(exc, PathSecurityError):
        return _WriteError("path_security_violation", str(exc))
    return _WriteError("filesystem_write_failed", f"{type(exc).__name__}: {exc}")


def _attempt_id(request: WorkerRunRequest) -> str:
    value = request.metadata.get("attempt_id")
    if isinstance(value, str) and value.isdecimal():
        return value
    return "001"


def _ensure_trailing_newline(content: str) -> str:
    return content if content.endswith("\n") else content + "\n"


def _reject_nul(content: str, field_name: str) -> None:
    if "\x00" in content:
        raise ValueError(f"{field_name} must not contain NUL bytes")


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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _artifact_id(job_id: object, ref: str) -> str:
    prefix = str(job_id) if isinstance(job_id, str) and job_id else "skillfoundry-job"
    return f"{prefix}:{ref}"


def _synthetic_thread_id(request: WorkerRunRequest) -> str:
    return f"thread-{request.goal_run_id}-{request.node_contract.node_id}"


__all__ = [
    "CodexThreadSkillBuilderWorker",
    "ExternalAgentSkillBuilderWorker",
    "FakeSkillBuilderWorker",
    "OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION",
    "OwnedLLMSkillBuilderWorker",
    "WORKERS_V2_VERSION",
]
