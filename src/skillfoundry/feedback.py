"""WP11 feedback capture and version governance helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .qa import QA_REPORT_VERSION
from .registry import (
    DuplicatePolicy,
    LocalSkillRegistry,
    RegistryEntryNotFound,
    RegistryGateError,
)
from .schema import (
    JsonValue,
    RegistryEntry,
    SchemaModel,
    SchemaValidationError,
    VerificationResult,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .workspace import JOB_ID_RE, JobWorkspace


FEEDBACK_RECORD_VERSION = "skillfoundry.feedback.record.v1"
FEEDBACK_REPAIR_PLAN_VERSION = "skillfoundry.feedback.repair_plan.v1"
FEEDBACK_VERSIONING_PROVENANCE_VERSION = "skillfoundry.feedback.versioning_provenance.v1"
VERSION_CHANGE_REPORT_VERSION = "skillfoundry.feedback.version_change_report.v1"
ROLLBACK_EVENT_VERSION = "skillfoundry.feedback.rollback_event.v1"

DEFAULT_REQUIRED_VERSION_GATES = (
    "verifier/verification_result.json passed",
    "qa/quality_report.json passed",
    "LocalSkillRegistry.add_verified",
)


class FeedbackVersioningError(ValueError):
    """Base class for feedback/version governance failures."""


class FeedbackVersionGateError(FeedbackVersioningError):
    """Raised when a repaired version does not satisfy WP11 gates."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__("feedback version gate failed: " + "; ".join(failures))


@dataclass
class FeedbackRecord(SchemaModel):
    """Durable failed-usage feedback tied to one approved source version."""

    feedback_id: str
    skill_id: str
    source_version: str
    source_build_job_id: str
    reporter: str
    channel: str
    severity: str
    summary: str
    failed_usage_case: str
    expected_behavior: str
    actual_behavior: str
    evidence_refs: list[str]
    created_at: str = field(default_factory=utc_now)
    rating: int | float | None = None
    schema_version: str = FEEDBACK_RECORD_VERSION

    def validate(self) -> None:
        super().validate()
        if self.schema_version != FEEDBACK_RECORD_VERSION:
            raise SchemaValidationError(f"schema_version must be {FEEDBACK_RECORD_VERSION!r}")
        for name in (
            "feedback_id",
            "skill_id",
            "source_version",
            "source_build_job_id",
            "reporter",
            "channel",
            "severity",
            "summary",
            "failed_usage_case",
            "expected_behavior",
            "actual_behavior",
            "created_at",
        ):
            _require_non_empty_str(getattr(self, name), name)
        _require_str_list(self.evidence_refs, "evidence_refs")
        if self.rating is not None and not (
            isinstance(self.rating, (int, float)) and not isinstance(self.rating, bool)
        ):
            raise SchemaValidationError("rating must be a number when present")


@dataclass
class FeedbackRepairPlan(SchemaModel):
    """Machine-readable plan for a feedback-driven repair/version job."""

    plan_id: str
    feedback_id: str
    skill_id: str
    source_version: str
    source_build_job_id: str
    source_package_hash: str
    source_registry_entry_ref: str
    source_registry_entry_hash: str
    source_registry_entry: dict[str, JsonValue]
    suggested_new_version: str
    repair_goal: str
    acceptance_notes: list[str]
    target_repair_job_id: str
    feedback_ref: str
    feedback_hash: str
    required_gates: list[str]
    created_at: str = field(default_factory=utc_now)
    schema_version: str = FEEDBACK_REPAIR_PLAN_VERSION

    def validate(self) -> None:
        super().validate()
        if self.schema_version != FEEDBACK_REPAIR_PLAN_VERSION:
            raise SchemaValidationError(f"schema_version must be {FEEDBACK_REPAIR_PLAN_VERSION!r}")
        for name in (
            "plan_id",
            "feedback_id",
            "skill_id",
            "source_version",
            "source_build_job_id",
            "source_package_hash",
            "source_registry_entry_ref",
            "source_registry_entry_hash",
            "suggested_new_version",
            "repair_goal",
            "target_repair_job_id",
            "feedback_ref",
            "feedback_hash",
            "created_at",
        ):
            _require_non_empty_str(getattr(self, name), name)
        _require_sha256(self.source_package_hash, "source_package_hash")
        _require_sha256(self.source_registry_entry_hash, "source_registry_entry_hash")
        _require_sha256(self.feedback_hash, "feedback_hash")
        _require_json_mapping(self.source_registry_entry, "source_registry_entry")
        _require_str_list(self.acceptance_notes, "acceptance_notes")
        _require_str_list(self.required_gates, "required_gates")
        if not JOB_ID_RE.fullmatch(self.target_repair_job_id):
            raise SchemaValidationError("target_repair_job_id must be a safe job id")
        if self.suggested_new_version == self.source_version:
            raise SchemaValidationError("suggested_new_version must differ from source_version")


@dataclass(frozen=True)
class RepairRegistrationResult:
    """Result returned after a repaired version passes all WP11 gates."""

    registry_entry: RegistryEntry
    version_change_report: dict[str, JsonValue]
    version_change_report_path: Path


class SkillVersionManager:
    """Capture feedback and register feedback-driven repaired versions.

    The manager is intentionally small and local. It never mutates approved
    package files; it writes feedback/versioning metadata and delegates final
    registry acceptance to ``LocalSkillRegistry.add_verified``.
    """

    def __init__(
        self,
        registry_path: str | Path,
        *,
        runs_root: str | Path | None = None,
        duplicate_policy: DuplicatePolicy | str = DuplicatePolicy.REJECT,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.runs_root = Path(runs_root) if runs_root is not None else self.registry_path.parent / "runs"
        self.duplicate_policy = DuplicatePolicy(duplicate_policy)

    @property
    def registry(self) -> LocalSkillRegistry:
        return LocalSkillRegistry(self.registry_path, duplicate_policy=self.duplicate_policy)

    def write_feedback_record(
        self,
        feedback: FeedbackRecord,
        path: str | Path,
    ) -> Path:
        """Persist a feedback record as deterministic JSON."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        feedback.write_json_file(target)
        return target

    def plan_repair_from_feedback(
        self,
        feedback: FeedbackRecord,
        source_entry: RegistryEntry,
        *,
        suggested_new_version: str | None = None,
        repair_goal: str | None = None,
        acceptance_notes: list[str] | None = None,
        target_repair_job_id: str | None = None,
    ) -> FeedbackRepairPlan:
        """Write ``runs/<repair_job_id>/feedback_repair_plan.json`` from feedback."""

        _check_feedback_matches_source(feedback, source_entry)
        new_version = suggested_new_version or _suggest_next_version(source_entry.version)
        if new_version == source_entry.version:
            raise FeedbackVersionGateError(["suggested_new_version must differ from source version"])

        repair_job_id = target_repair_job_id or _safe_job_id(f"repair-{feedback.feedback_id}")
        if not JOB_ID_RE.fullmatch(repair_job_id):
            raise FeedbackVersionGateError([f"target_repair_job_id is unsafe: {repair_job_id!r}"])
        if repair_job_id == source_entry.build_job_id:
            raise FeedbackVersionGateError(["target_repair_job_id must differ from source build job id"])

        repair_dir = self.runs_root / repair_job_id
        repair_dir.mkdir(parents=True, exist_ok=True)

        feedback_ref = "feedback_record.json"
        feedback_path = repair_dir / feedback_ref
        feedback.write_json_file(feedback_path)
        feedback_hash = sha256_file(feedback_path)

        source_entry_payload = source_entry.to_dict()
        source_entry_hash = sha256_json(source_entry_payload)
        notes = acceptance_notes or _default_acceptance_notes(feedback)
        goal = repair_goal or _default_repair_goal(feedback)
        plan = FeedbackRepairPlan(
            plan_id=_plan_id(feedback.feedback_id, source_entry.skill_id, source_entry.version, new_version),
            feedback_id=feedback.feedback_id,
            skill_id=source_entry.skill_id,
            source_version=source_entry.version,
            source_build_job_id=source_entry.build_job_id,
            source_package_hash=source_entry.package_hash,
            source_registry_entry_ref=_registry_entry_ref(source_entry),
            source_registry_entry_hash=source_entry_hash,
            source_registry_entry=source_entry_payload,
            suggested_new_version=new_version,
            repair_goal=goal,
            acceptance_notes=notes,
            target_repair_job_id=repair_job_id,
            feedback_ref=feedback_ref,
            feedback_hash=feedback_hash,
            required_gates=list(DEFAULT_REQUIRED_VERSION_GATES),
        )
        plan.write_json_file(repair_dir / "feedback_repair_plan.json")
        return plan

    def register_repaired_version(
        self,
        workspace: JobWorkspace | str | Path,
        feedback: FeedbackRecord,
        source_entry: RegistryEntry,
        *,
        version: str | None = None,
        plan: FeedbackRepairPlan | None = None,
        review_status: str = "feedback_repair_verified",
    ) -> RepairRegistrationResult:
        """Register a repaired version only after Verifier, QA Lab, and Registry pass."""

        job_workspace = _coerce_workspace(workspace)
        selected_version = version or (plan.suggested_new_version if plan is not None else None)
        if selected_version is None:
            selected_version = _suggest_next_version(source_entry.version)

        plan = plan or self._load_or_create_plan(
            job_workspace,
            feedback,
            source_entry,
            suggested_new_version=selected_version,
        )
        failures = _registration_preflight_failures(job_workspace, feedback, source_entry, plan, selected_version)
        if failures:
            raise FeedbackVersionGateError(failures)

        verifier_result, verifier_ref, verifier_hash = _read_verifier_gate(job_workspace)
        qa_report, qa_ref, qa_hash = _read_qa_gate(job_workspace, verifier_hash=verifier_hash)
        registry = self.registry
        try:
            entry = registry.add_verified(
                job_workspace,
                skill_id=source_entry.skill_id,
                version=selected_version,
                review_status=review_status,
            )
        except RegistryGateError as exc:
            raise FeedbackVersionGateError([f"registry.add_verified: {failure}" for failure in exc.failures]) from exc

        updated_entry = self._augment_registry_provenance(
            registry,
            entry,
            feedback=feedback,
            plan=plan,
            source_entry=source_entry,
            verifier_result=verifier_result,
            verifier_ref=verifier_ref,
            verifier_hash=verifier_hash,
            qa_report=qa_report,
            qa_ref=qa_ref,
            qa_hash=qa_hash,
        )
        report, report_path = self.write_version_change_report(
            job_workspace,
            feedback=feedback,
            plan=plan,
            source_entry=source_entry,
            new_entry=updated_entry,
            verifier_result=verifier_result,
            verifier_ref=verifier_ref,
            verifier_hash=verifier_hash,
            qa_report=qa_report,
            qa_ref=qa_ref,
            qa_hash=qa_hash,
        )
        return RepairRegistrationResult(
            registry_entry=updated_entry,
            version_change_report=report,
            version_change_report_path=report_path,
        )

    def quarantine_version(self, skill_id: str, version: str, reason: str) -> RegistryEntry:
        """Quarantine a version and assert it is excluded from default reuse candidates."""

        registry = self.registry
        entry = registry.quarantine(skill_id, version, reason)
        leaked = [
            candidate
            for candidate in registry.reuse_candidates()
            if candidate.skill_id == skill_id and candidate.version == version
        ]
        if leaked:
            raise FeedbackVersioningError(f"quarantined version still appears in reuse candidates: {skill_id}@{version}")
        return entry

    def record_rollback(
        self,
        *,
        restored_entry: RegistryEntry,
        rolled_back_from_entry: RegistryEntry,
        reason: str,
        workspace: JobWorkspace | str | Path | None = None,
        event_id: str | None = None,
    ) -> tuple[dict[str, JsonValue], Path]:
        """Write a rollback event/report without mutating package files."""

        _require_non_empty_str(reason, "reason")
        if restored_entry.skill_id != rolled_back_from_entry.skill_id:
            raise FeedbackVersioningError("rollback entries must have the same skill_id")

        selected_event_id = event_id or _rollback_event_id(restored_entry, rolled_back_from_entry)
        payload = ensure_json_compatible(
            {
                "schema_version": ROLLBACK_EVENT_VERSION,
                "event_id": selected_event_id,
                "event": "rollback_preferred_version_restored",
                "skill_id": restored_entry.skill_id,
                "restored": _entry_summary(restored_entry),
                "rolled_back_from": _entry_summary(rolled_back_from_entry),
                "preferred_version": restored_entry.version,
                "reason": reason,
                "package_mutation": False,
                "created_at": utc_now(),
            }
        )
        if workspace is None:
            event_dir = self.registry_path.parent / "rollback_events"
            event_path = event_dir / f"{selected_event_id}.json"
        else:
            job_workspace = _coerce_workspace(workspace)
            job_workspace.resolve_path("versioning").mkdir(parents=False, exist_ok=True)
            event_path = job_workspace.resolve_path("versioning/rollback_event.json")
        _write_json(event_path, payload)  # type: ignore[arg-type]
        return payload, event_path

    def write_version_change_report(
        self,
        workspace: JobWorkspace | str | Path,
        *,
        feedback: FeedbackRecord,
        plan: FeedbackRepairPlan,
        source_entry: RegistryEntry,
        new_entry: RegistryEntry,
        verifier_result: VerificationResult,
        verifier_ref: str,
        verifier_hash: str,
        qa_report: Mapping[str, Any],
        qa_ref: str,
        qa_hash: str,
        rollback_event: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, JsonValue], Path]:
        """Write ``versioning/version_change_report.json`` for a repaired version."""

        job_workspace = _coerce_workspace(workspace)
        source_current = _get_entry_or_none(self.registry, source_entry.skill_id, source_entry.version)
        source_quarantine_status = (
            source_current.quarantine_status if source_current is not None else source_entry.quarantine_status
        )
        report = ensure_json_compatible(
            {
                "schema_version": VERSION_CHANGE_REPORT_VERSION,
                "skill_id": source_entry.skill_id,
                "feedback": {
                    "feedback_id": feedback.feedback_id,
                    "summary": feedback.summary,
                    "failed_usage_case": feedback.failed_usage_case,
                    "expected_behavior": feedback.expected_behavior,
                    "actual_behavior": feedback.actual_behavior,
                    "evidence_refs": feedback.evidence_refs,
                },
                "plan": {
                    "plan_id": plan.plan_id,
                    "ref": "feedback_repair_plan.json",
                    "sha256": _sha_if_exists(job_workspace, "feedback_repair_plan.json"),
                    "target_repair_job_id": plan.target_repair_job_id,
                    "repair_goal": plan.repair_goal,
                    "acceptance_notes": plan.acceptance_notes,
                    "required_gates": plan.required_gates,
                },
                "old_version": _entry_summary(source_entry),
                "new_version": _entry_summary(new_entry),
                "quarantine": {
                    "old_version_status": source_quarantine_status,
                    "old_version_excluded_from_default_reuse": not _is_reuse_candidate(
                        self.registry,
                        source_entry.skill_id,
                        source_entry.version,
                    ),
                },
                "rollback": {
                    "recorded": rollback_event is not None,
                    "event": ensure_json_compatible(dict(rollback_event)) if rollback_event is not None else None,
                },
                "gates": {
                    "verifier": {
                        "ref": verifier_ref,
                        "sha256": verifier_hash,
                        "result_id": verifier_result.result_id,
                        "passed": verifier_result.passed,
                    },
                    "qa_lab": {
                        "ref": qa_ref,
                        "sha256": qa_hash,
                        "passed": qa_report.get("passed"),
                        "hard_gate_passed": qa_report.get("hard_gate_passed"),
                        "quality_score": qa_report.get("quality_score"),
                    },
                    "registry": {
                        "method": "LocalSkillRegistry.add_verified",
                        "entry_ref": _registry_entry_ref(new_entry),
                        "entry_hash": sha256_json(new_entry.to_dict()),
                    },
                },
                "created_at": utc_now(),
            }
        )
        job_workspace.resolve_path("versioning").mkdir(parents=False, exist_ok=True)
        report_path = job_workspace.resolve_path("versioning/version_change_report.json")
        _write_json(report_path, report)  # type: ignore[arg-type]
        return report, report_path

    def _load_or_create_plan(
        self,
        workspace: JobWorkspace,
        feedback: FeedbackRecord,
        source_entry: RegistryEntry,
        *,
        suggested_new_version: str,
    ) -> FeedbackRepairPlan:
        plan_path = workspace.resolve_path("feedback_repair_plan.json")
        if plan_path.exists():
            return FeedbackRepairPlan.read_json_file(plan_path)
        return self.plan_repair_from_feedback(
            feedback,
            source_entry,
            suggested_new_version=suggested_new_version,
            target_repair_job_id=workspace.job_id,
        )

    def _augment_registry_provenance(
        self,
        registry: LocalSkillRegistry,
        entry: RegistryEntry,
        *,
        feedback: FeedbackRecord,
        plan: FeedbackRepairPlan,
        source_entry: RegistryEntry,
        verifier_result: VerificationResult,
        verifier_ref: str,
        verifier_hash: str,
        qa_report: Mapping[str, Any],
        qa_ref: str,
        qa_hash: str,
    ) -> RegistryEntry:
        provenance = dict(entry.provenance)
        provenance["feedback_versioning"] = ensure_json_compatible(
            {
                "schema_version": FEEDBACK_VERSIONING_PROVENANCE_VERSION,
                "source": {
                    "skill_id": source_entry.skill_id,
                    "version": source_entry.version,
                    "build_job_id": source_entry.build_job_id,
                    "package_hash": source_entry.package_hash,
                    "registry_entry_ref": _registry_entry_ref(source_entry),
                    "registry_entry_hash": sha256_json(source_entry.to_dict()),
                },
                "feedback_record": {
                    "feedback_id": feedback.feedback_id,
                    "skill_id": feedback.skill_id,
                    "source_version": feedback.source_version,
                    "source_build_job_id": feedback.source_build_job_id,
                    "summary": feedback.summary,
                    "hash": sha256_json(feedback.to_dict()),
                },
                "repair_plan": {
                    "plan_id": plan.plan_id,
                    "target_repair_job_id": plan.target_repair_job_id,
                    "suggested_new_version": plan.suggested_new_version,
                    "repair_goal": plan.repair_goal,
                    "hash": sha256_json(plan.to_dict()),
                },
                "repair_job": {
                    "job_id": entry.build_job_id,
                    "package_hash": entry.package_hash,
                },
                "gates": {
                    "verifier": {
                        "ref": verifier_ref,
                        "sha256": verifier_hash,
                        "result_id": verifier_result.result_id,
                        "passed": verifier_result.passed,
                    },
                    "qa_lab": {
                        "ref": qa_ref,
                        "sha256": qa_hash,
                        "passed": qa_report.get("passed"),
                        "hard_gate_passed": qa_report.get("hard_gate_passed"),
                    },
                    "registry": {
                        "method": "LocalSkillRegistry.add_verified",
                        "entry_ref": _registry_entry_ref(entry),
                    },
                },
                "new_registry_entry": {
                    "skill_id": entry.skill_id,
                    "version": entry.version,
                    "build_job_id": entry.build_job_id,
                    "package_hash": entry.package_hash,
                    "registry_entry_ref": _registry_entry_ref(entry),
                },
            }
        )
        updated = RegistryEntry(
            skill_id=entry.skill_id,
            version=entry.version,
            package_path=entry.package_path,
            package_hash=entry.package_hash,
            build_job_id=entry.build_job_id,
            worker_invocation_id=entry.worker_invocation_id,
            verification_spec_hash=entry.verification_spec_hash,
            verification_result_hash=entry.verification_result_hash,
            artifact_manifest_hash=entry.artifact_manifest_hash,
            verifier_version=entry.verifier_version,
            approval_status=entry.approval_status,
            review_status=entry.review_status,
            created_at=entry.created_at,
            provenance=ensure_json_compatible(provenance),  # type: ignore[arg-type]
            quarantine_status=entry.quarantine_status,
        )
        updated.validate()
        entries = registry._load_entries()
        for index, existing in enumerate(entries):
            if existing.skill_id == updated.skill_id and existing.version == updated.version:
                entries[index] = updated
                registry._write_entries(entries)
                return updated
        raise FeedbackVersioningError(
            f"registered entry disappeared before provenance update: {_registry_entry_ref(entry)}"
        )


def _registration_preflight_failures(
    workspace: JobWorkspace,
    feedback: FeedbackRecord,
    source_entry: RegistryEntry,
    plan: FeedbackRepairPlan,
    version: str,
) -> list[str]:
    failures: list[str] = []
    try:
        _check_feedback_matches_source(feedback, source_entry)
    except FeedbackVersionGateError as exc:
        failures.extend(exc.failures)
    if version == source_entry.version:
        failures.append("version: repaired version must differ from source version")
    if plan.feedback_id != feedback.feedback_id:
        failures.append(f"plan.feedback_id: expected {feedback.feedback_id}, got {plan.feedback_id}")
    if plan.skill_id != source_entry.skill_id:
        failures.append(f"plan.skill_id: expected {source_entry.skill_id}, got {plan.skill_id}")
    if plan.source_version != source_entry.version:
        failures.append(f"plan.source_version: expected {source_entry.version}, got {plan.source_version}")
    if plan.source_package_hash != source_entry.package_hash:
        failures.append("plan.source_package_hash does not match source registry entry")
    if plan.target_repair_job_id != workspace.job_id:
        failures.append(f"plan.target_repair_job_id: expected {workspace.job_id}, got {plan.target_repair_job_id}")
    if workspace.job_id == source_entry.build_job_id:
        failures.append("repair workspace job_id must differ from source build job id")
    if plan.suggested_new_version != version:
        failures.append(f"plan.suggested_new_version: expected {version}, got {plan.suggested_new_version}")
    missing_gates = [gate for gate in DEFAULT_REQUIRED_VERSION_GATES if gate not in plan.required_gates]
    if missing_gates:
        failures.append(f"plan.required_gates missing: {', '.join(missing_gates)}")

    try:
        _read_verifier_gate(workspace)
    except FeedbackVersionGateError as exc:
        failures.extend(exc.failures)
    else:
        try:
            verifier_hash = sha256_file(workspace.resolve_path("verifier/verification_result.json", must_exist=True))
            _read_qa_gate(workspace, verifier_hash=verifier_hash)
        except FeedbackVersionGateError as exc:
            failures.extend(exc.failures)
    return failures


def _read_verifier_gate(workspace: JobWorkspace) -> tuple[VerificationResult, str, str]:
    ref = "verifier/verification_result.json"
    failures: list[str] = []
    try:
        path = workspace.resolve_path(ref, must_exist=True)
        result_hash = sha256_file(path)
        result = VerificationResult.read_json_file(path)
    except Exception as exc:
        raise FeedbackVersionGateError([f"verifier: missing or invalid {ref}: {exc}"]) from exc

    if result.job_id != workspace.job_id:
        failures.append(f"verifier.job_id: expected {workspace.job_id}, got {result.job_id}")
    if not result.passed:
        failures.append("verifier.passed: verifier did not pass")
    if result.failures:
        failures.append("verifier.failures: passed verifier result must not contain failures")
    for index, check in enumerate(result.checks):
        if check.get("severity") == "error" and check.get("passed") is False:
            failures.append(f"verifier.checks[{index}]: failed error check present")
            break
    if failures:
        raise FeedbackVersionGateError(failures)
    return result, ref, result_hash


def _read_qa_gate(workspace: JobWorkspace, *, verifier_hash: str) -> tuple[dict[str, JsonValue], str, str]:
    ref = "qa/quality_report.json"
    failures: list[str] = []
    try:
        path = workspace.resolve_path(ref, must_exist=True)
        report_hash = sha256_file(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FeedbackVersionGateError([f"qa_lab: missing or invalid {ref}: {exc}"]) from exc

    if not isinstance(payload, dict):
        raise FeedbackVersionGateError(["qa_lab: quality_report.json must be a JSON object"])
    report = ensure_json_compatible(payload)
    assert isinstance(report, dict)

    if report.get("schema_version") != QA_REPORT_VERSION:
        failures.append(f"qa_lab.schema_version: expected {QA_REPORT_VERSION}, got {report.get('schema_version')!r}")
    if report.get("job_id") != workspace.job_id:
        failures.append(f"qa_lab.job_id: expected {workspace.job_id}, got {report.get('job_id')!r}")
    if report.get("passed") is not True:
        failures.append("qa_lab.passed: QA Lab did not pass")
    if report.get("hard_gate_passed") is not True:
        failures.append("qa_lab.hard_gate_passed: QA hard gate did not pass")
    if report.get("verifier_result_ref") != "verifier/verification_result.json":
        failures.append("qa_lab.verifier_result_ref: missing current verifier result ref")
    if report.get("verifier_result_hash") != verifier_hash:
        failures.append("qa_lab.verifier_result_hash: does not match current verifier result")

    verifier_result = report.get("verifier_result")
    if isinstance(verifier_result, dict):
        if verifier_result.get("passed") is not True:
            failures.append("qa_lab.verifier_result.passed: embedded verifier result did not pass")
    else:
        failures.append("qa_lab.verifier_result: missing embedded verifier evidence")

    if failures:
        raise FeedbackVersionGateError(failures)
    return report, ref, report_hash


def _check_feedback_matches_source(feedback: FeedbackRecord, source_entry: RegistryEntry) -> None:
    failures: list[str] = []
    if feedback.skill_id != source_entry.skill_id:
        failures.append(f"feedback.skill_id: expected {source_entry.skill_id}, got {feedback.skill_id}")
    if feedback.source_version != source_entry.version:
        failures.append(f"feedback.source_version: expected {source_entry.version}, got {feedback.source_version}")
    if feedback.source_build_job_id != source_entry.build_job_id:
        failures.append(
            f"feedback.source_build_job_id: expected {source_entry.build_job_id}, "
            f"got {feedback.source_build_job_id}"
        )
    if failures:
        raise FeedbackVersionGateError(failures)


def _coerce_workspace(workspace: JobWorkspace | str | Path) -> JobWorkspace:
    if isinstance(workspace, JobWorkspace):
        return workspace
    root = Path(workspace)
    job_id = root.name
    manifest_path = root / "artifact_manifest.json"
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("job_id"), str):
                job_id = payload["job_id"]
        except Exception:
            pass
    return JobWorkspace(root=root, job_id=job_id)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    compatible = ensure_json_compatible(dict(payload))
    path.write_text(
        json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _default_repair_goal(feedback: FeedbackRecord) -> str:
    return (
        f"Repair {feedback.skill_id}@{feedback.source_version} so the failed usage case passes: "
        f"{feedback.failed_usage_case}"
    )


def _default_acceptance_notes(feedback: FeedbackRecord) -> list[str]:
    return [
        f"Expected behavior: {feedback.expected_behavior}",
        f"Actual behavior to fix: {feedback.actual_behavior}",
        "Verifier must pass before registration.",
        "QA Lab hard gate must pass before registration.",
        "Registry add_verified must approve the repaired package.",
    ]


def _plan_id(feedback_id: str, skill_id: str, source_version: str, new_version: str) -> str:
    digest = sha256_json(
        {
            "feedback_id": feedback_id,
            "skill_id": skill_id,
            "source_version": source_version,
            "new_version": new_version,
        }
    )[:16]
    return f"repair-plan-{digest}"


def _rollback_event_id(restored_entry: RegistryEntry, rolled_back_from_entry: RegistryEntry) -> str:
    digest = sha256_json(
        {
            "skill_id": restored_entry.skill_id,
            "restored_version": restored_entry.version,
            "rolled_back_from_version": rolled_back_from_entry.version,
        }
    )[:16]
    return f"rollback-{digest}"


def _registry_entry_ref(entry: RegistryEntry) -> str:
    return f"{entry.skill_id}@{entry.version}"


def _entry_summary(entry: RegistryEntry) -> dict[str, JsonValue]:
    return ensure_json_compatible(
        {
            "skill_id": entry.skill_id,
            "version": entry.version,
            "build_job_id": entry.build_job_id,
            "package_hash": entry.package_hash,
            "approval_status": entry.approval_status,
            "quarantine_status": entry.quarantine_status,
            "registry_entry_ref": _registry_entry_ref(entry),
            "registry_entry_hash": sha256_json(entry.to_dict()),
        }
    )  # type: ignore[return-value]


def _get_entry_or_none(registry: LocalSkillRegistry, skill_id: str, version: str) -> RegistryEntry | None:
    try:
        return registry.get(skill_id, version)
    except RegistryEntryNotFound:
        return None


def _is_reuse_candidate(registry: LocalSkillRegistry, skill_id: str, version: str) -> bool:
    return any(entry.skill_id == skill_id and entry.version == version for entry in registry.reuse_candidates())


def _sha_if_exists(workspace: JobWorkspace, relative_path: str) -> str | None:
    try:
        path = workspace.resolve_path(relative_path, must_exist=True)
    except Exception:
        return None
    return sha256_file(path)


def _suggest_next_version(version: str) -> str:
    match = re.fullmatch(r"(?P<prefix>\d+\.\d+\.)(?P<patch>\d+)", version)
    if match is not None:
        return f"{match.group('prefix')}{int(match.group('patch')) + 1}"
    match = re.fullmatch(r"(?P<prefix>\d+\.)(?P<minor>\d+)", version)
    if match is not None:
        return f"{match.group('prefix')}{int(match.group('minor')) + 1}"
    return f"{version}.repair1"


def _safe_job_id(raw: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw.strip()).strip(".-")
    if not value:
        value = "repair-job"
    if not re.match(r"^[A-Za-z0-9]", value):
        value = f"repair-{value}"
    if JOB_ID_RE.fullmatch(value):
        return value
    digest = sha256_json({"raw": raw})[:12]
    return f"repair-{digest}"


def _require_non_empty_str(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")


def _require_str_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list of strings")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(f"{field_name}[{index}] must be a non-empty string")


def _require_json_mapping(value: Any, field_name: str) -> None:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{field_name} must be a JSON object")
    ensure_json_compatible(value, field_name)


def _require_sha256(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"^[0-9a-f]{64}$", value):
        raise SchemaValidationError(f"{field_name} must be a lowercase sha256 hex digest")


__all__ = [
    "DEFAULT_REQUIRED_VERSION_GATES",
    "FEEDBACK_RECORD_VERSION",
    "FEEDBACK_REPAIR_PLAN_VERSION",
    "FEEDBACK_VERSIONING_PROVENANCE_VERSION",
    "ROLLBACK_EVENT_VERSION",
    "VERSION_CHANGE_REPORT_VERSION",
    "FeedbackRecord",
    "FeedbackRepairPlan",
    "FeedbackVersionGateError",
    "FeedbackVersioningError",
    "RepairRegistrationResult",
    "SkillVersionManager",
]
