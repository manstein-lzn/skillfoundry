"""WP5 ContextForge adapter for owned LLM calls and boundary evidence.

This module is intentionally a thin SkillFoundry-facing layer over
ContextForge. It does not copy ContextForge internals and does not model
external worker internals as owned model calls.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .schema import (
    JsonValue,
    VerificationResult,
    WorkerInvocation,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .workspace import JobWorkspace
from .worker import WorkerRunResult


def _import_contextforge() -> dict[str, Any]:
    """Import ContextForge through the project dependency boundary."""

    from contextforge.kernel import ContextKernel, FakeModelClient
    from contextforge.ledger import ContextLedger
    from contextforge.schema import (
        ContextItem,
        ContextNeed,
        ContextRequest,
        ContextSource,
        ModelCallEnvelope,
        ModelCallRecord,
        PromptView,
        ToolCallRecord,
        ToolOutputRecord,
        UsageDraft,
        WorkerInfo,
        estimate_tokens,
    )
    from contextforge.tools import ToolOutputGovernor, ToolOutputGovernorPolicy

    return {
        "ContextItem": ContextItem,
        "ContextKernel": ContextKernel,
        "ContextLedger": ContextLedger,
        "ContextNeed": ContextNeed,
        "ContextRequest": ContextRequest,
        "ContextSource": ContextSource,
        "FakeModelClient": FakeModelClient,
        "ModelCallEnvelope": ModelCallEnvelope,
        "ModelCallRecord": ModelCallRecord,
        "PromptView": PromptView,
        "ToolCallRecord": ToolCallRecord,
        "ToolOutputGovernor": ToolOutputGovernor,
        "ToolOutputGovernorPolicy": ToolOutputGovernorPolicy,
        "ToolOutputRecord": ToolOutputRecord,
        "UsageDraft": UsageDraft,
        "WorkerInfo": WorkerInfo,
        "estimate_tokens": estimate_tokens,
    }


_CF = _import_contextforge()

ContextItem = _CF["ContextItem"]
ContextKernel = _CF["ContextKernel"]
ContextLedger = _CF["ContextLedger"]
ContextNeed = _CF["ContextNeed"]
ContextRequest = _CF["ContextRequest"]
ContextSource = _CF["ContextSource"]
FakeModelClient = _CF["FakeModelClient"]
ModelCallEnvelope = _CF["ModelCallEnvelope"]
ModelCallRecord = _CF["ModelCallRecord"]
PromptView = _CF["PromptView"]
ToolCallRecord = _CF["ToolCallRecord"]
ToolOutputGovernor = _CF["ToolOutputGovernor"]
ToolOutputGovernorPolicy = _CF["ToolOutputGovernorPolicy"]
ToolOutputRecord = _CF["ToolOutputRecord"]
UsageDraft = _CF["UsageDraft"]
WorkerInfo = _CF["WorkerInfo"]
estimate_tokens = _CF["estimate_tokens"]


CONTEXT_ADAPTER_VERSION = "skillfoundry.context.wp5.v1"
DEFAULT_CONTEXT_LEDGER_REF = "context/contextforge.sqlite3"
DEFAULT_GRAPH_ID = "skillfoundry"
OWNED_LLM_SCOPE_NOTE = "owned SkillFoundry LLM call"
WORKER_BOUNDARY_SCOPE_NOTE = "external worker boundary evidence only"


@dataclass(frozen=True)
class OwnedLLMCallResult:
    """Result of one SkillFoundry-owned model call through ContextForge."""

    context_request: Any
    prompt_view: Any
    envelope: Any
    record: Any
    replay_artifact_ref: str
    replay_artifact_path: Path
    usage_available: bool
    usage_unavailable_reason: str | None

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "context_request": self.context_request.to_dict(),
                "prompt_view": self.prompt_view.to_dict(),
                "envelope": self.envelope.to_dict(),
                "record": self.record.to_dict(),
                "replay_artifact_ref": self.replay_artifact_ref,
                "replay_artifact_path": self.replay_artifact_path.as_posix(),
                "usage_available": self.usage_available,
                "usage_unavailable_reason": self.usage_unavailable_reason,
            }
        )  # type: ignore[return-value]


@dataclass(frozen=True)
class WorkerBoundaryEvidence:
    """Boundary record for an external worker invocation."""

    record_id: str
    artifact_ref: str
    artifact_path: Path
    payload: dict[str, JsonValue]
    context_item_id: str

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "record_id": self.record_id,
                "artifact_ref": self.artifact_ref,
                "artifact_path": self.artifact_path.as_posix(),
                "payload": self.payload,
                "context_item_id": self.context_item_id,
            }
        )  # type: ignore[return-value]


@dataclass(frozen=True)
class VerifierPromptEvidence:
    """Governed verifier output that can be injected into owned prompts."""

    tool_call_id: str
    tool_output_id: str
    context_item_id: str
    governed_content: str
    raw_log_refs: list[dict[str, JsonValue]]
    raw_artifact_ref: str | None
    truncated: bool
    summarized: bool
    context_bytes: int
    raw_bytes: int

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "tool_call_id": self.tool_call_id,
                "tool_output_id": self.tool_output_id,
                "context_item_id": self.context_item_id,
                "governed_content": self.governed_content,
                "raw_log_refs": self.raw_log_refs,
                "raw_artifact_ref": self.raw_artifact_ref,
                "truncated": self.truncated,
                "summarized": self.summarized,
                "context_bytes": self.context_bytes,
                "raw_bytes": self.raw_bytes,
            }
        )  # type: ignore[return-value]


@dataclass(frozen=True)
class ReplayCoverageReport:
    """Replay coverage for owned calls, excluding external worker internals."""

    owned_llm_call_count: int
    owned_llm_replay_artifact_count: int
    owned_llm_replay_coverage: float
    external_worker_boundary_count: int
    external_worker_internal_replay_count: int
    external_worker_internal_replay_coverage: float
    excluded_scope: str

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "owned_llm_call_count": self.owned_llm_call_count,
                "owned_llm_replay_artifact_count": self.owned_llm_replay_artifact_count,
                "owned_llm_replay_coverage": self.owned_llm_replay_coverage,
                "external_worker_boundary_count": self.external_worker_boundary_count,
                "external_worker_internal_replay_count": self.external_worker_internal_replay_count,
                "external_worker_internal_replay_coverage": self.external_worker_internal_replay_coverage,
                "excluded_scope": self.excluded_scope,
            }
        )  # type: ignore[return-value]


@dataclass(frozen=True)
class SkillFoundryContextMetrics:
    """Job-level WP5 metrics derived from ContextForge and boundary records."""

    job_id: str
    attempt_count: int
    verification_status: str
    worker_duration_ms: int
    worker_usage_available: bool
    worker_usage_unavailable_reason: str | None
    owned_llm_call_count: int
    owned_llm_usage_available: bool
    owned_llm_usage_unavailable_reasons: list[str]
    external_worker_boundary_count: int
    replay_coverage: ReplayCoverageReport

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "job_id": self.job_id,
                "attempt_count": self.attempt_count,
                "verification_status": self.verification_status,
                "worker_duration_ms": self.worker_duration_ms,
                "worker_usage_available": self.worker_usage_available,
                "worker_usage_unavailable_reason": self.worker_usage_unavailable_reason,
                "owned_llm_call_count": self.owned_llm_call_count,
                "owned_llm_usage_available": self.owned_llm_usage_available,
                "owned_llm_usage_unavailable_reasons": self.owned_llm_usage_unavailable_reasons,
                "external_worker_boundary_count": self.external_worker_boundary_count,
                "replay_coverage": self.replay_coverage.to_dict(),
            }
        )  # type: ignore[return-value]


@dataclass(frozen=True)
class ContextAuditReport:
    """Audit report separating owned model calls from external worker records."""

    job_id: str
    owned_llm_calls: list[dict[str, JsonValue]]
    external_worker_boundaries: list[dict[str, JsonValue]]
    verifier_prompt_evidence: list[dict[str, JsonValue]]
    metrics: SkillFoundryContextMetrics

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "job_id": self.job_id,
                "owned_llm_calls": self.owned_llm_calls,
                "external_worker_boundaries": self.external_worker_boundaries,
                "verifier_prompt_evidence": self.verifier_prompt_evidence,
                "metrics": self.metrics.to_dict(),
            }
        )  # type: ignore[return-value]


class SkillFoundryContextAdapter:
    """SkillFoundry WP5 adapter over ContextForge."""

    def __init__(self, workspace: JobWorkspace, ledger: Any, kernel: Any) -> None:
        self.workspace = workspace
        self.ledger = ledger
        self.kernel = kernel

    @classmethod
    def for_workspace(
        cls,
        workspace: JobWorkspace,
        *,
        ledger_ref: str = DEFAULT_CONTEXT_LEDGER_REF,
    ) -> "SkillFoundryContextAdapter":
        """Create or open the ContextForge ledger inside a job workspace."""

        context_dir = workspace.resolve_path("context")
        context_dir.mkdir(parents=False, exist_ok=True)
        ledger_path = workspace.resolve_path(ledger_ref)
        ledger = ContextLedger.connect(ledger_path)
        ledger.initialize()
        kernel = ContextKernel(ledger)
        return cls(workspace, ledger, kernel)

    def close(self) -> None:
        self.ledger.close()

    def __enter__(self) -> "SkillFoundryContextAdapter":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def call_owned_llm(
        self,
        *,
        node_id: str,
        intent: str,
        input_text: str | None = None,
        output_contract: str | None = None,
        context_needs: Sequence[str | Any] | None = None,
        required_types: Sequence[str] | None = None,
        budget_tokens: int = 4096,
        provider: str = "fake",
        model: str = "skillfoundry-fake-model",
        model_params: Mapping[str, Any] | None = None,
        tool_schemas: Sequence[Mapping[str, Any]] | None = None,
        client: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> OwnedLLMCallResult:
        """Invoke one SkillFoundry-owned LLM call through ContextForge."""

        created_at = utc_now()
        required_type_list = list(required_types or ())
        if input_text:
            item = self.record_user_message(
                node_id=node_id,
                text=input_text,
                created_at=created_at,
                metadata={"prompt_include": True, "owned_llm_input": True},
            )
            if "user_message" not in required_type_list:
                required_type_list.append("user_message")
            input_item_id = item.id
        else:
            input_item_id = None

        request = ContextRequest(
            graph_id=DEFAULT_GRAPH_ID,
            run_id=self.workspace.job_id,
            task_id=self.workspace.job_id,
            node_id=node_id,
            intent=intent,
            budget_tokens=budget_tokens,
            required_types=required_type_list,
            context_needs=_context_needs(context_needs),
            retrieval_query=input_text,
            recent_item_limit=4,
            memory_limit=4,
            include_artifacts=False,
            allow_compaction_on_overflow=False,
            output_contract=output_contract,
            metadata={
                "adapter": CONTEXT_ADAPTER_VERSION,
                "created_at": created_at,
                "input_item_id": input_item_id,
                **ensure_json_compatible(dict(metadata or {})),  # type: ignore[arg-type]
            },
        )
        envelope = ModelCallEnvelope(
            graph_id=request.graph_id,
            run_id=request.run_id,
            task_id=request.task_id,
            node_id=request.node_id,
            intent=request.intent,
            context_request=request,
            provider=provider,
            model=model,
            model_params=ensure_json_compatible(dict(model_params or {})),  # type: ignore[arg-type]
            tool_schemas=[ensure_json_compatible(dict(schema)) for schema in tool_schemas or []],  # type: ignore[list-item]
            worker=WorkerInfo(
                kind="fake_model" if provider == "fake" else "llm",
                name="skillfoundry-owned-llm",
                version=CONTEXT_ADAPTER_VERSION,
                metadata={"owned_by": "skillfoundry"},
            ),
            metadata={
                "adapter": CONTEXT_ADAPTER_VERSION,
                "scope": OWNED_LLM_SCOPE_NOTE,
            },
        )
        model_client = client if client is not None else FakeModelClient()
        record = self.kernel.invoke_model(envelope, model_client)
        prompt_view, _prompt_blocks = self.ledger.get_prompt_view(record.prompt_view_id)
        replay_path = self.resolve_artifact_ref(record.replay_bundle_ref)
        return OwnedLLMCallResult(
            context_request=request,
            prompt_view=prompt_view,
            envelope=envelope,
            record=record,
            replay_artifact_ref=record.replay_bundle_ref,
            replay_artifact_path=replay_path,
            usage_available=record.usage_id is not None,
            usage_unavailable_reason=record.usage_unavailable_reason,
        )

    def record_user_message(
        self,
        *,
        node_id: str,
        text: str,
        created_at: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        payload = {
            "job_id": self.workspace.job_id,
            "node_id": node_id,
            "text": text,
            "created_at": created_at or utc_now(),
            "metadata": ensure_json_compatible(dict(metadata or {})),
        }
        item = ContextItem(
            id=f"context-item-{sha256_json(payload)[:24]}",
            graph_id=DEFAULT_GRAPH_ID,
            run_id=self.workspace.job_id,
            task_id=self.workspace.job_id,
            node_id=node_id,
            type="user_message",
            content=text,
            source=ContextSource(
                kind="user",
                ref=None,
                name="skillfoundry.requirement",
                sha256=sha256_json({"text": text}),
                metadata={},
            ),
            importance=1.0,
            token_estimate=estimate_tokens(text),
            created_at=str(payload["created_at"]),
            artifact_ref=None,
            provenance={"job_id": self.workspace.job_id},
            metadata=ensure_json_compatible(dict(metadata or {})),  # type: ignore[arg-type]
        )
        self.ledger.record_context_item(item)
        return item

    def record_worker_boundary(
        self,
        result: WorkerRunResult,
        *,
        verification_result: VerificationResult | None = None,
        registry_decision_ref: str | None = None,
        failure_class: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkerBoundaryEvidence:
        """Persist external worker boundary evidence without model-call replay."""

        invocation = result.invocation
        verifier_ref, verifier_hash, verification_status = self._verification_ref_hash_status(
            verification_result,
        )
        record_id = f"worker-boundary-{sha256_json({'invocation_id': invocation.invocation_id})[:24]}"
        payload = ensure_json_compatible(
            {
                "schema_version": "skillfoundry.worker_boundary.v1",
                "record_id": record_id,
                "job_id": invocation.job_id,
                "attempt_id": invocation.attempt_id,
                "invocation_id": invocation.invocation_id,
                "worker_type": invocation.worker_type,
                "adapter_version": invocation.adapter_version,
                "evidence_kind": WORKER_BOUNDARY_SCOPE_NOTE,
                "owned_llm_replay": False,
                "external_worker_internal_replay": False,
                "input_manifest": {
                    "ref": f"attempts/{invocation.attempt_id}/input_manifest.json",
                    "sha256": invocation.input_manifest_hash,
                },
                "workspace_hash_before": invocation.workspace_hash_before,
                "workspace_hash_after": invocation.workspace_hash_after,
                "transcript_ref": invocation.transcript_ref,
                "diff_ref": invocation.diff_ref,
                "execution_report_ref": invocation.execution_report_ref,
                "verifier_result_ref": verifier_ref,
                "verifier_result_hash": verifier_hash,
                "registry_decision_ref": registry_decision_ref,
                "duration_ms": invocation.duration_ms,
                "exit_status": invocation.exit_status,
                "ready_for_verifier": result.ready_for_verifier,
                "accepted": result.accepted,
                "failure_class": failure_class if failure_class is not None else result.failure_class,
                "usage_available": invocation.usage_available,
                "usage_unavailable_reason": invocation.usage_unavailable_reason,
                "verification_status": verification_status,
                "created_at": utc_now(),
                "metadata": ensure_json_compatible(dict(metadata or {})),
            }
        )  # type: ignore[assignment]
        artifact_id = f"artifact-{record_id}"
        relative_path = f"worker-boundary/{self.workspace.job_id}/{record_id}.json"
        artifact = self.kernel.replay_store.write_json_artifact(
            relative_path=relative_path,
            payload=payload,
            artifact_id=artifact_id,
            graph_id=DEFAULT_GRAPH_ID,
            run_id=self.workspace.job_id,
            task_id=self.workspace.job_id,
            kind="worker_boundary",
            content_type="application/json",
            created_at=str(payload["created_at"]),
            metadata={
                "record_id": record_id,
                "invocation_id": invocation.invocation_id,
                "attempt_id": invocation.attempt_id,
            },
        )
        artifact_ref = f"artifact:{artifact.id}"
        context_item_id = self._record_worker_boundary_context_item(
            invocation=invocation,
            artifact_ref=artifact_ref,
            payload=payload,
        )
        return WorkerBoundaryEvidence(
            record_id=record_id,
            artifact_ref=artifact_ref,
            artifact_path=self.kernel.replay_store.resolve_artifact_path(artifact.relative_path),
            payload=payload,
            context_item_id=context_item_id,
        )

    def record_verifier_prompt_evidence(
        self,
        verification_result: VerificationResult,
        *,
        raw_log_refs: Sequence[str] = ("verifier/sandbox.log", "verifier/static_report.json"),
        node_id: str = "verifier",
        max_context_bytes: int = 1024,
    ) -> VerifierPromptEvidence:
        """Govern verifier output before it can enter owned LLM prompts."""

        raw_logs = []
        for ref in raw_log_refs:
            path = self.workspace.resolve_path(ref, must_exist=True)
            raw_logs.append(
                {
                    "ref": ref,
                    "sha256": sha256_file(path),
                    "content": path.read_text(encoding="utf-8"),
                }
            )
        verification_ref = "verifier/verification_result.json"
        verification_hash = self._hash_if_exists(verification_ref)
        raw_payload = {
            "verification_result": verification_result.to_dict(),
            "verification_result_ref": verification_ref,
            "verification_result_hash": verification_hash,
            "raw_logs": raw_logs,
        }
        raw_text = json.dumps(raw_payload, sort_keys=True, indent=2, ensure_ascii=False)
        governor = ToolOutputGovernor(
            ToolOutputGovernorPolicy(
                max_context_bytes=max_context_bytes,
                artifact_threshold_bytes=1,
            )
        )
        governed = governor.govern(
            "skillfoundry.verifier",
            raw_text,
            verification_result.passed,
            metadata={
                "reducer_id": "json_payload",
                "selected_paths": [
                    "$.verification_result.passed",
                    "$.verification_result.failures",
                    "$.verification_result.evidence_refs",
                    "$.verification_result.verifier_version",
                    "$.verification_result_ref",
                    "$.verification_result_hash",
                ],
            },
        )
        created_at = utc_now()
        raw_log_summaries = [
            {"ref": str(item["ref"]), "sha256": str(item["sha256"])} for item in raw_logs
        ]
        tool_call_id = f"tool-call-{sha256_json({'result_id': verification_result.result_id})[:24]}"
        tool_output_id = f"tool-output-{sha256_json({'tool_call_id': tool_call_id, 'created_at': created_at})[:24]}"
        tool_call = ToolCallRecord(
            id=tool_call_id,
            graph_id=DEFAULT_GRAPH_ID,
            run_id=self.workspace.job_id,
            task_id=self.workspace.job_id,
            node_id=node_id,
            tool_name="skillfoundry.verifier",
            arguments={
                "verification_result_ref": verification_ref,
                "raw_log_refs": raw_log_summaries,
            },
            created_at=created_at,
            metadata={"adapter": CONTEXT_ADAPTER_VERSION},
        )
        tool_output = ToolOutputRecord(
            id=tool_output_id,
            tool_call_id=tool_call_id,
            raw_artifact_ref=governed.raw_artifact_ref,
            governed_content=governed.governed_content,
            raw_bytes=governed.raw_bytes,
            context_bytes=governed.context_bytes,
            compression_ratio=governed.compression_ratio,
            truncated=governed.truncated,
            summarized=governed.summarized,
            reducer_id=governed.reducer_id,
            success=verification_result.passed,
            created_at=created_at,
            metadata={
                "adapter": CONTEXT_ADAPTER_VERSION,
                "verification_result_ref": verification_ref,
                "verification_result_hash": verification_hash,
                "raw_log_refs": raw_log_summaries,
                "diagnostics": governed.diagnostics,
            },
        )
        self.ledger.record_tool_call(tool_call)
        self.ledger.record_tool_output(tool_output)
        context_item_id = self._record_verifier_context_item(
            node_id=node_id,
            tool_output=tool_output,
            verification_result=verification_result,
            raw_log_refs=raw_log_summaries,
        )
        return VerifierPromptEvidence(
            tool_call_id=tool_call_id,
            tool_output_id=tool_output_id,
            context_item_id=context_item_id,
            governed_content=governed.governed_content,
            raw_log_refs=raw_log_summaries,
            raw_artifact_ref=governed.raw_artifact_ref,
            truncated=governed.truncated,
            summarized=governed.summarized,
            context_bytes=governed.context_bytes,
            raw_bytes=governed.raw_bytes,
        )

    def replay_coverage(self) -> ReplayCoverageReport:
        model_calls = self.ledger.query_model_calls(run_id=self.workspace.job_id)
        replayed = [
            call
            for call in model_calls
            if call.replay_bundle_ref.startswith("artifact:") and self._artifact_ref_exists(call.replay_bundle_ref)
        ]
        worker_boundary_count = len(self._worker_boundary_payloads())
        coverage = len(replayed) / len(model_calls) if model_calls else 1.0
        return ReplayCoverageReport(
            owned_llm_call_count=len(model_calls),
            owned_llm_replay_artifact_count=len(replayed),
            owned_llm_replay_coverage=coverage,
            external_worker_boundary_count=worker_boundary_count,
            external_worker_internal_replay_count=0,
            external_worker_internal_replay_coverage=0.0,
            excluded_scope="external worker internal execution is not part of owned LLM replay",
        )

    def metrics(self) -> SkillFoundryContextMetrics:
        boundaries = self._worker_boundary_payloads()
        model_calls = self.ledger.query_model_calls(run_id=self.workspace.job_id)
        attempts = {str(item["attempt_id"]) for item in boundaries if item.get("attempt_id")}
        worker_duration = sum(_int_value(item.get("duration_ms")) for item in boundaries)
        worker_usage_available = bool(boundaries) and all(bool(item.get("usage_available")) for item in boundaries)
        worker_usage_reasons = [
            str(item["usage_unavailable_reason"])
            for item in boundaries
            if item.get("usage_available") is False and item.get("usage_unavailable_reason")
        ]
        owned_usage_reasons = [
            str(call.usage_unavailable_reason)
            for call in model_calls
            if call.usage_id is None and call.usage_unavailable_reason
        ]
        return SkillFoundryContextMetrics(
            job_id=self.workspace.job_id,
            attempt_count=len(attempts),
            verification_status=self._latest_verification_status(boundaries),
            worker_duration_ms=worker_duration,
            worker_usage_available=worker_usage_available,
            worker_usage_unavailable_reason="; ".join(worker_usage_reasons) if worker_usage_reasons else None,
            owned_llm_call_count=len(model_calls),
            owned_llm_usage_available=bool(model_calls) and all(call.usage_id is not None for call in model_calls),
            owned_llm_usage_unavailable_reasons=owned_usage_reasons,
            external_worker_boundary_count=len(boundaries),
            replay_coverage=self.replay_coverage(),
        )

    def audit_report(self) -> ContextAuditReport:
        model_calls = self.ledger.query_model_calls(run_id=self.workspace.job_id)
        owned_calls = [
            ensure_json_compatible(
                {
                    "kind": "owned_llm_call",
                    "model_call_id": call.id,
                    "prompt_view_id": call.prompt_view_id,
                    "provider": call.envelope.provider,
                    "model": call.envelope.model,
                    "node_id": call.envelope.node_id,
                    "intent": call.envelope.intent,
                    "replay_bundle_ref": call.replay_bundle_ref,
                    "usage_available": call.usage_id is not None,
                    "usage_unavailable_reason": call.usage_unavailable_reason,
                    "success": call.error is None,
                }
            )
            for call in model_calls
        ]
        verifier_outputs = [
            ensure_json_compatible(
                {
                    "kind": "governed_verifier_prompt_evidence",
                    "tool_output_id": output.id,
                    "tool_call_id": output.tool_call_id,
                    "raw_artifact_ref": output.raw_artifact_ref,
                    "context_bytes": output.context_bytes,
                    "raw_bytes": output.raw_bytes,
                    "truncated": output.truncated,
                    "summarized": output.summarized,
                    "reducer_id": output.reducer_id,
                }
            )
            for output in self.ledger.query_tool_outputs(run_id=self.workspace.job_id)
        ]
        return ContextAuditReport(
            job_id=self.workspace.job_id,
            owned_llm_calls=owned_calls,  # type: ignore[arg-type]
            external_worker_boundaries=self._worker_boundary_payloads(),
            verifier_prompt_evidence=verifier_outputs,  # type: ignore[arg-type]
            metrics=self.metrics(),
        )

    def resolve_artifact_ref(self, artifact_ref: str) -> Path:
        """Resolve a ContextForge artifact reference to a local path."""

        if not artifact_ref.startswith("artifact:"):
            raise ValueError("artifact_ref must start with 'artifact:'")
        artifact_id = artifact_ref.removeprefix("artifact:")
        artifact = self.ledger.get_artifact(artifact_id)
        return self.kernel.replay_store.resolve_artifact_path(artifact.relative_path)

    def _record_worker_boundary_context_item(
        self,
        *,
        invocation: WorkerInvocation,
        artifact_ref: str,
        payload: Mapping[str, JsonValue],
    ) -> str:
        content = {
            "summary": f"External worker boundary recorded for {invocation.invocation_id}",
            "attempt_id": invocation.attempt_id,
            "worker_type": invocation.worker_type,
            "duration_ms": invocation.duration_ms,
            "usage_available": invocation.usage_available,
            "usage_unavailable_reason": invocation.usage_unavailable_reason,
            "verification_status": payload.get("verification_status"),
            "boundary_artifact_ref": artifact_ref,
        }
        item_id = f"context-item-{sha256_json({'artifact_ref': artifact_ref})[:24]}"
        item = ContextItem(
            id=item_id,
            graph_id=DEFAULT_GRAPH_ID,
            run_id=self.workspace.job_id,
            task_id=self.workspace.job_id,
            node_id="worker_boundary",
            type="artifact",
            content=ensure_json_compatible(content),  # type: ignore[arg-type]
            source=ContextSource(
                kind="codex_worker",
                ref=artifact_ref,
                name=invocation.worker_type,
                sha256=sha256_json(payload),
                metadata={"boundary_only": True},
            ),
            importance=0.9,
            token_estimate=estimate_tokens(content),
            created_at=str(payload["created_at"]),
            artifact_ref=artifact_ref,
            provenance={"job_id": self.workspace.job_id, "attempt_id": invocation.attempt_id},
            metadata={
                "prompt_category": "worker_result",
                "boundary_only": True,
                "owned_llm_replay": False,
            },
        )
        self.ledger.record_context_item(item)
        return item_id

    def _record_verifier_context_item(
        self,
        *,
        node_id: str,
        tool_output: Any,
        verification_result: VerificationResult,
        raw_log_refs: list[dict[str, JsonValue]],
    ) -> str:
        content = {
            "governed_content": tool_output.governed_content,
            "reducer_id": tool_output.reducer_id,
            "verification_result_id": verification_result.result_id,
            "passed": verification_result.passed,
            "raw_log_refs": raw_log_refs,
        }
        item_id = f"context-item-{sha256_json({'tool_output_id': tool_output.id})[:24]}"
        item = ContextItem(
            id=item_id,
            graph_id=DEFAULT_GRAPH_ID,
            run_id=self.workspace.job_id,
            task_id=self.workspace.job_id,
            node_id=node_id,
            type="tool_output",
            content=ensure_json_compatible(content),  # type: ignore[arg-type]
            source=ContextSource(
                kind="validator",
                ref="verifier/verification_result.json",
                name="skillfoundry.verifier",
                sha256=self._hash_if_exists("verifier/verification_result.json"),
                metadata={"tool_output_id": tool_output.id},
            ),
            importance=0.95,
            token_estimate=estimate_tokens(tool_output.governed_content),
            created_at=tool_output.created_at,
            artifact_ref=tool_output.raw_artifact_ref,
            provenance={"job_id": self.workspace.job_id, "verifier_result_id": verification_result.result_id},
            metadata={
                "governed": True,
                "reducer_id": tool_output.reducer_id,
                "success": verification_result.passed,
                "raw_artifact_ref": tool_output.raw_artifact_ref,
            },
        )
        self.ledger.record_context_item(item)
        return item_id

    def _worker_boundary_payloads(self) -> list[dict[str, JsonValue]]:
        payloads: list[dict[str, JsonValue]] = []
        artifacts = self.ledger.query_artifacts(
            run_id=self.workspace.job_id,
            kind="worker_boundary",
        )
        for artifact in artifacts:
            path = self.kernel.replay_store.resolve_artifact_path(artifact.relative_path)
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        return payloads

    def _artifact_ref_exists(self, artifact_ref: str) -> bool:
        try:
            self.resolve_artifact_ref(artifact_ref)
        except Exception:
            return False
        return True

    def _verification_ref_hash_status(
        self,
        verification_result: VerificationResult | None,
    ) -> tuple[str | None, str | None, str]:
        if verification_result is not None:
            return (
                "verifier/verification_result.json",
                self._hash_if_exists("verifier/verification_result.json") or sha256_json(verification_result),
                "passed" if verification_result.passed else "failed",
            )
        verification_hash = self._hash_if_exists("verifier/verification_result.json")
        if verification_hash is None:
            return None, None, "not_recorded"
        try:
            result = VerificationResult.read_json_file(self.workspace.resolve_path("verifier/verification_result.json"))
        except Exception:
            return "verifier/verification_result.json", verification_hash, "invalid"
        return "verifier/verification_result.json", verification_hash, "passed" if result.passed else "failed"

    def _hash_if_exists(self, relative_path: str) -> str | None:
        try:
            path = self.workspace.resolve_path(relative_path, must_exist=True)
        except Exception:
            return None
        if not path.is_file():
            return None
        return sha256_file(path)

    @staticmethod
    def _latest_verification_status(boundaries: Sequence[Mapping[str, JsonValue]]) -> str:
        if not boundaries:
            return "not_recorded"
        for item in reversed(boundaries):
            status = item.get("verification_status")
            if isinstance(status, str) and status:
                return status
        return "not_recorded"


def _context_needs(values: Sequence[str | Any] | None) -> list[Any]:
    needs: list[Any] = []
    for value in values or ():
        if hasattr(value, "to_dict"):
            needs.append(value)
            continue
        needs.append(
            ContextNeed(
                name=str(value),
                required=False,
                max_tokens=None,
                scope={},
                query=None,
            )
        )
    return needs


def _int_value(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def audit_report_to_json(report: ContextAuditReport, *, indent: int | None = 2) -> str:
    """Serialize a WP5 audit report with deterministic keys."""

    return json.dumps(report.to_dict(), sort_keys=True, indent=indent, ensure_ascii=False)


__all__ = [
    "CONTEXT_ADAPTER_VERSION",
    "ContextAuditReport",
    "OwnedLLMCallResult",
    "ReplayCoverageReport",
    "SkillFoundryContextAdapter",
    "SkillFoundryContextMetrics",
    "VerifierPromptEvidence",
    "WorkerBoundaryEvidence",
    "audit_report_to_json",
]
