"""WP16 acceptance criteria coverage planning and evaluation.

This module bridges frozen Front Desk acceptance criteria into deterministic
QA/Verifier evidence. It does not call providers, execute arbitrary commands,
or ask an LLM to decide acceptance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Mapping, Self

from .frontdesk_schema import AcceptanceCriteriaSet, AcceptanceCriterion
from .schema import (
    JsonValue,
    SchemaModel,
    SchemaValidationError,
    VerificationResult,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .security import PathSecurityError, resolve_under_root, validate_relative_path
from .workspace import JobWorkspace


ACCEPTANCE_COVERAGE_PLAN_VERSION = "skillfoundry.acceptance.coverage_plan.v1"
ACCEPTANCE_COVERAGE_RESULT_VERSION = "skillfoundry.acceptance.coverage_result.v1"
ACCEPTANCE_COVERAGE_PLAN_REF = "qa/acceptance_coverage_plan.json"
ACCEPTANCE_COVERAGE_RESULT_REF = "qa/acceptance_coverage_result.json"
MANUAL_ACCEPTANCE_RECORD_REF = "qa/manual_acceptance_record.json"

ACCEPTANCE_CRITERIA_REF = "acceptance_criteria.yaml"
QA_REPORT_REF = "qa/quality_report.json"
VERIFICATION_RESULT_REF = "verifier/verification_result.json"

COVERAGE_MODE_VERIFIER_CHECK = "verifier_check"
COVERAGE_MODE_FIXTURE = "fixture"
COVERAGE_MODE_REQUIRED_EVIDENCE = "required_evidence"
COVERAGE_MODE_QA_REPORT_CHECK = "qa_report_check"
COVERAGE_MODE_MANUAL_AUTHORITY = "manual_authority"
COVERAGE_MODE_UNCOVERED = "uncovered"

COVERAGE_RESULT_STATUS_COVERED_PASS = "covered/pass"
COVERAGE_RESULT_STATUS_COVERED_FAIL = "covered/fail"
COVERAGE_RESULT_STATUS_MANUAL_ONLY = "manual_only"
COVERAGE_RESULT_STATUS_UNCOVERED = "uncovered"

_COVERAGE_MODES = frozenset(
    {
        COVERAGE_MODE_VERIFIER_CHECK,
        COVERAGE_MODE_FIXTURE,
        COVERAGE_MODE_REQUIRED_EVIDENCE,
        COVERAGE_MODE_QA_REPORT_CHECK,
        COVERAGE_MODE_MANUAL_AUTHORITY,
        COVERAGE_MODE_UNCOVERED,
    }
)
_RESULT_STATUSES = frozenset(
    {
        COVERAGE_RESULT_STATUS_COVERED_PASS,
        COVERAGE_RESULT_STATUS_COVERED_FAIL,
        COVERAGE_RESULT_STATUS_MANUAL_ONLY,
        COVERAGE_RESULT_STATUS_UNCOVERED,
    }
)
_PRIORITIES = frozenset({"must", "should", "could"})
_QA_CHECK_NAMES = frozenset(
    {
        "verifier_passed",
        "trigger_fixture_coverage",
        "non_trigger_fixture_coverage",
        "io_contract_coverage",
        "workflow_actionability",
        "safety_actionability",
        "script_smoke",
    }
)
_MACHINE_CHECK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_SYNTHETIC_VERIFIER_CHECK_IDS = frozenset(
    {
        "package_contract_present",
        "skill_package_instruction_contract",
        "skill_instruction_content",
        "skill_clean_room_boundary",
        "skill_scope_exclusion_boundary",
        "skill_privacy_boundary",
        "skill_user_evidence_boundary",
        "evidence_authorization_gate",
        "evidence_references_contract",
        "manifest_schema_documented",
        "candidate_table_contract",
        "candidate_entry_semantics",
        "wiki_structure_contract",
        "wiki_structure_and_paths_contract",
        "path_generation_contract",
        "write_conflict_policy_contract",
        "rust_verifier_package_present",
        "rust_verifier_core_validation",
        "rust_verifier_path_safety",
        "package_cargo_test",
        "local_smoke_command_documented",
        "rust_verifier_fixture_coverage",
        "local_deterministic_verifier_boundary",
        "no_external_runtime_dependency",
        "codexarium_taxonomy_contract",
        "codexarium_manifest_compact_contract",
        "codexarium_fixture_scenario_coverage",
        "codexarium_local_runtime_contract",
        "codexarium_explicit_wiki_root_contract",
        "codexarium_synthetic_fixture_boundary",
        "codexarium_reference_documentation_contract",
        "downstream_verifier_acceptance_gate",
    }
)
_ZERO_HASH = "0" * 64


@dataclass
class AcceptanceCoveragePlanItem(SchemaModel):
    """One criterion-to-evidence mapping in the coverage plan."""

    criterion_id: str
    priority: str
    description: str
    test_method: str
    evidence_kind: str
    coverage_mode: str
    deterministic: bool
    verifier_check_id: str | None = None
    fixture_ref: str | None = None
    required_evidence_refs: list[str] = field(default_factory=list)
    qa_report_checks: list[str] = field(default_factory=list)
    manual_authority: str | None = None
    uncovered_reason: str | None = None
    source_coverage_status: str = "planned"
    schema_version: str = ACCEPTANCE_COVERAGE_PLAN_VERSION + ".item"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.criterion_id, "criterion_id")
        _require_enum(self.priority, "priority", _PRIORITIES)
        _require_string(self.description, "description")
        _require_non_empty_str(self.test_method, "test_method")
        _require_non_empty_str(self.evidence_kind, "evidence_kind")
        _require_enum(self.coverage_mode, "coverage_mode", _COVERAGE_MODES)
        _require_bool(self.deterministic, "deterministic")
        _require_optional_non_empty_str(self.verifier_check_id, "verifier_check_id")
        _require_optional_non_empty_str(self.fixture_ref, "fixture_ref")
        _require_str_list(self.required_evidence_refs, "required_evidence_refs")
        _require_str_list(self.qa_report_checks, "qa_report_checks")
        _require_optional_non_empty_str(self.manual_authority, "manual_authority")
        _require_optional_non_empty_str(self.uncovered_reason, "uncovered_reason")
        _require_non_empty_str(self.source_coverage_status, "source_coverage_status")
        if self.coverage_mode == COVERAGE_MODE_VERIFIER_CHECK and not self.verifier_check_id:
            raise SchemaValidationError("verifier_check coverage requires verifier_check_id")
        if self.coverage_mode == COVERAGE_MODE_FIXTURE and not self.fixture_ref:
            raise SchemaValidationError("fixture coverage requires fixture_ref")
        if self.coverage_mode == COVERAGE_MODE_REQUIRED_EVIDENCE and not self.required_evidence_refs:
            raise SchemaValidationError("required_evidence coverage requires required_evidence_refs")
        if self.coverage_mode == COVERAGE_MODE_QA_REPORT_CHECK and not self.qa_report_checks:
            raise SchemaValidationError("qa_report_check coverage requires qa_report_checks")
        if self.coverage_mode == COVERAGE_MODE_UNCOVERED and not self.uncovered_reason:
            raise SchemaValidationError("uncovered coverage requires uncovered_reason")


@dataclass
class AcceptanceCoveragePlan(SchemaModel):
    """Deterministic coverage plan generated from frozen acceptance criteria."""

    plan_id: str
    job_id: str
    criteria_set_id: str
    acceptance_criteria_ref: str
    acceptance_criteria_hash: str
    items: list[AcceptanceCoveragePlanItem]
    created_at: str
    schema_version: str = ACCEPTANCE_COVERAGE_PLAN_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("AcceptanceCoveragePlan payload must be a JSON object")
        data = dict(payload)
        if "items" in data:
            if not isinstance(data["items"], list):
                raise SchemaValidationError("items must be a list")
            data["items"] = [AcceptanceCoveragePlanItem.from_dict(item) for item in data["items"]]
        instance = cls(**data)
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        for name in ("plan_id", "job_id", "criteria_set_id", "acceptance_criteria_ref", "created_at"):
            _require_non_empty_str(getattr(self, name), name)
        _require_sha256(self.acceptance_criteria_hash, "acceptance_criteria_hash")
        if not isinstance(self.items, list):
            raise SchemaValidationError("items must be a list")
        seen: set[str] = set()
        for index, item in enumerate(self.items):
            if not isinstance(item, AcceptanceCoveragePlanItem):
                raise SchemaValidationError(f"items[{index}] must be an AcceptanceCoveragePlanItem")
            item.validate()
            if item.criterion_id in seen:
                raise SchemaValidationError(f"duplicate criterion_id: {item.criterion_id}")
            seen.add(item.criterion_id)


@dataclass
class AcceptanceCoverageResultItem(SchemaModel):
    """Evaluation result for one planned acceptance criterion."""

    criterion_id: str
    priority: str
    status: str
    passed: bool
    coverage_mode: str
    deterministic: bool
    evidence_refs: list[str]
    failures: list[str]
    manual_authority: str | None = None
    verifier_check_id: str | None = None
    fixture_ref: str | None = None
    qa_report_checks: list[str] = field(default_factory=list)
    uncovered_reason: str | None = None
    schema_version: str = ACCEPTANCE_COVERAGE_RESULT_VERSION + ".item"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.criterion_id, "criterion_id")
        _require_enum(self.priority, "priority", _PRIORITIES)
        _require_enum(self.status, "status", _RESULT_STATUSES)
        _require_bool(self.passed, "passed")
        _require_enum(self.coverage_mode, "coverage_mode", _COVERAGE_MODES)
        _require_bool(self.deterministic, "deterministic")
        _require_str_list(self.evidence_refs, "evidence_refs")
        _require_str_list(self.failures, "failures")
        _require_optional_non_empty_str(self.manual_authority, "manual_authority")
        _require_optional_non_empty_str(self.verifier_check_id, "verifier_check_id")
        _require_optional_non_empty_str(self.fixture_ref, "fixture_ref")
        _require_str_list(self.qa_report_checks, "qa_report_checks")
        _require_optional_non_empty_str(self.uncovered_reason, "uncovered_reason")
        if self.status == COVERAGE_RESULT_STATUS_COVERED_PASS and not self.passed:
            raise SchemaValidationError("covered/pass result item must have passed=true")
        if self.status in {
            COVERAGE_RESULT_STATUS_COVERED_FAIL,
            COVERAGE_RESULT_STATUS_UNCOVERED,
        } and self.passed:
            raise SchemaValidationError(f"{self.status} result item must have passed=false")
        if self.status == COVERAGE_RESULT_STATUS_MANUAL_ONLY and not self.manual_authority:
            raise SchemaValidationError("manual_only result item requires manual_authority")


@dataclass
class AcceptanceCoverageResult(SchemaModel):
    """Deterministic acceptance coverage evidence consumed by QA and Registry."""

    result_id: str
    job_id: str
    plan_id: str
    acceptance_criteria_ref: str
    acceptance_criteria_hash: str
    coverage_plan_ref: str
    coverage_plan_hash: str
    qa_report_ref: str | None
    qa_report_hash: str | None
    verification_result_ref: str | None
    verification_result_hash: str | None
    package_hash: str
    passed: bool
    coverage_score: float
    must_total: int
    must_passed: int
    must_manual_only: int
    must_failed: int
    optional_total: int
    optional_failed: int
    items: list[AcceptanceCoverageResultItem]
    failures: list[str]
    provenance: dict[str, JsonValue]
    created_at: str
    schema_version: str = ACCEPTANCE_COVERAGE_RESULT_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("AcceptanceCoverageResult payload must be a JSON object")
        data = dict(payload)
        if "items" in data:
            if not isinstance(data["items"], list):
                raise SchemaValidationError("items must be a list")
            data["items"] = [AcceptanceCoverageResultItem.from_dict(item) for item in data["items"]]
        instance = cls(**data)
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        for name in (
            "result_id",
            "job_id",
            "plan_id",
            "acceptance_criteria_ref",
            "coverage_plan_ref",
            "created_at",
        ):
            _require_non_empty_str(getattr(self, name), name)
        for name in ("acceptance_criteria_hash", "coverage_plan_hash", "package_hash"):
            _require_sha256(getattr(self, name), name)
        _require_optional_non_empty_str(self.qa_report_ref, "qa_report_ref")
        _require_optional_sha256(self.qa_report_hash, "qa_report_hash")
        _require_optional_non_empty_str(self.verification_result_ref, "verification_result_ref")
        _require_optional_sha256(self.verification_result_hash, "verification_result_hash")
        _require_bool(self.passed, "passed")
        _require_finite_score(self.coverage_score, "coverage_score")
        for name in (
            "must_total",
            "must_passed",
            "must_manual_only",
            "must_failed",
            "optional_total",
            "optional_failed",
        ):
            _require_non_negative_int(getattr(self, name), name)
        if not isinstance(self.items, list):
            raise SchemaValidationError("items must be a list")
        for index, item in enumerate(self.items):
            if not isinstance(item, AcceptanceCoverageResultItem):
                raise SchemaValidationError(f"items[{index}] must be an AcceptanceCoverageResultItem")
            item.validate()
        _require_str_list(self.failures, "failures")
        _require_json_mapping(self.provenance, "provenance")


class AcceptanceCriteriaPlanner:
    """Create deterministic coverage plans from root acceptance criteria."""

    def plan(
        self,
        workspace: JobWorkspace | str | Path,
        *,
        acceptance_criteria_ref: str = ACCEPTANCE_CRITERIA_REF,
        output_ref: str = ACCEPTANCE_COVERAGE_PLAN_REF,
    ) -> AcceptanceCoveragePlan:
        """Read frozen criteria and write ``qa/acceptance_coverage_plan.json``."""

        job_workspace = _coerce_workspace(workspace)
        criteria_path = job_workspace.resolve_path(acceptance_criteria_ref, must_exist=True)
        criteria_set = AcceptanceCriteriaSet.read_yaml_file(criteria_path)
        criteria_hash = sha256_file(criteria_path)
        items = [_plan_item(criterion) for criterion in criteria_set.criteria]
        plan_id = "acp-" + sha256_json(
            {
                "job_id": job_workspace.job_id,
                "criteria_set_id": criteria_set.criteria_set_id,
                "acceptance_criteria_hash": criteria_hash,
                "items": [item.to_dict() for item in items],
            }
        )[:24]
        plan = AcceptanceCoveragePlan(
            plan_id=plan_id,
            job_id=job_workspace.job_id,
            criteria_set_id=criteria_set.criteria_set_id,
            acceptance_criteria_ref=acceptance_criteria_ref,
            acceptance_criteria_hash=criteria_hash,
            items=items,
            created_at=utc_now(),
        )
        plan.validate()

        output_path = _output_path(job_workspace, output_ref)
        plan.write_json_file(output_path)
        return plan


class AcceptanceCoverageEvaluator:
    """Evaluate a coverage plan against local QA, verifier, and package evidence."""

    def evaluate(
        self,
        workspace: JobWorkspace | str | Path,
        *,
        plan: AcceptanceCoveragePlan | Mapping[str, Any] | str | Path | None = None,
        plan_ref: str = ACCEPTANCE_COVERAGE_PLAN_REF,
        output_ref: str = ACCEPTANCE_COVERAGE_RESULT_REF,
    ) -> AcceptanceCoverageResult:
        """Write ``qa/acceptance_coverage_result.json`` with deterministic statuses."""

        job_workspace = _coerce_workspace(workspace)
        coverage_plan = _coerce_plan(job_workspace, plan, plan_ref)

        qa_report, qa_report_ref, qa_report_hash = _read_json_evidence(job_workspace, QA_REPORT_REF)
        verifier_result, verifier_result_ref, verifier_result_hash = _read_verifier_result(job_workspace)
        manual_record, manual_record_ref, manual_record_hash = _read_json_evidence(
            job_workspace,
            MANUAL_ACCEPTANCE_RECORD_REF,
        )
        package_hash, package_failures = _hash_package(job_workspace)
        plan_hash = sha256_file(job_workspace.resolve_path(plan_ref, must_exist=True))

        result_items = [
            _evaluate_plan_item(
                job_workspace,
                item,
                qa_report=qa_report,
                verifier_result=verifier_result,
                manual_acceptance_record=manual_record,
                manual_acceptance_record_ref=manual_record_ref,
                acceptance_criteria_hash=coverage_plan.acceptance_criteria_hash,
            )
            for item in coverage_plan.items
        ]
        for failure in package_failures:
            result_items.append(
                AcceptanceCoverageResultItem(
                    criterion_id="package",
                    priority="should",
                    status=COVERAGE_RESULT_STATUS_COVERED_FAIL,
                    passed=False,
                    coverage_mode=COVERAGE_MODE_REQUIRED_EVIDENCE,
                    deterministic=True,
                    evidence_refs=["package"],
                    failures=[f"package_hash: {failure}"],
                )
            )

        must_items = [item for item in result_items if item.priority == "must"]
        optional_items = [item for item in result_items if item.priority != "must"]
        must_failed_items = [
            item
            for item in must_items
            if item.status not in {
                COVERAGE_RESULT_STATUS_COVERED_PASS,
                COVERAGE_RESULT_STATUS_MANUAL_ONLY,
            }
        ]
        must_passed = len([item for item in must_items if item.status == COVERAGE_RESULT_STATUS_COVERED_PASS])
        must_manual_only = len([item for item in must_items if item.status == COVERAGE_RESULT_STATUS_MANUAL_ONLY])
        optional_failed = len(
            [
                item
                for item in optional_items
                if item.status
                in {
                    COVERAGE_RESULT_STATUS_COVERED_FAIL,
                    COVERAGE_RESULT_STATUS_UNCOVERED,
                }
            ]
        )
        coverage_score = _coverage_score(result_items)
        failures = [
            f"{item.criterion_id}: {'; '.join(item.failures) or item.status}"
            for item in must_failed_items
        ]
        passed = not must_failed_items
        provenance = ensure_json_compatible(
            {
                "acceptance_criteria": {
                    "ref": coverage_plan.acceptance_criteria_ref,
                    "sha256": coverage_plan.acceptance_criteria_hash,
                },
                "coverage_plan": {
                    "ref": plan_ref,
                    "plan_id": coverage_plan.plan_id,
                    "sha256": plan_hash,
                },
                "qa_report": {
                    "ref": qa_report_ref,
                    "sha256": qa_report_hash,
                    "present": qa_report is not None,
                },
                "verification_result": {
                    "ref": verifier_result_ref,
                    "sha256": verifier_result_hash,
                    "result_id": verifier_result.result_id if verifier_result is not None else None,
                    "passed": verifier_result.passed if verifier_result is not None else None,
                    "present": verifier_result is not None,
                },
                "manual_acceptance_record": {
                    "ref": manual_record_ref,
                    "sha256": manual_record_hash,
                    "decision": manual_record.get("decision") if isinstance(manual_record, Mapping) else None,
                    "present": manual_record is not None,
                },
                "package": {
                    "ref": "package",
                    "sha256": package_hash,
                },
            }
        )
        result_id = "acr-" + sha256_json(
            {
                "job_id": job_workspace.job_id,
                "plan_id": coverage_plan.plan_id,
                "coverage_plan_hash": plan_hash,
                "qa_report_hash": qa_report_hash,
                "verification_result_hash": verifier_result_hash,
                "package_hash": package_hash,
                "items": [item.to_dict() for item in result_items],
                "passed": passed,
            }
        )[:24]
        result = AcceptanceCoverageResult(
            result_id=result_id,
            job_id=job_workspace.job_id,
            plan_id=coverage_plan.plan_id,
            acceptance_criteria_ref=coverage_plan.acceptance_criteria_ref,
            acceptance_criteria_hash=coverage_plan.acceptance_criteria_hash,
            coverage_plan_ref=plan_ref,
            coverage_plan_hash=plan_hash,
            qa_report_ref=qa_report_ref,
            qa_report_hash=qa_report_hash,
            verification_result_ref=verifier_result_ref,
            verification_result_hash=verifier_result_hash,
            package_hash=package_hash,
            passed=passed,
            coverage_score=coverage_score,
            must_total=len(must_items),
            must_passed=must_passed,
            must_manual_only=must_manual_only,
            must_failed=len(must_failed_items),
            optional_total=len(optional_items),
            optional_failed=optional_failed,
            items=result_items,
            failures=failures,
            provenance=provenance,  # type: ignore[arg-type]
            created_at=utc_now(),
        )
        result.validate()

        output_path = _output_path(job_workspace, output_ref)
        result.write_json_file(output_path)
        return result


def _plan_item(criterion: AcceptanceCriterion) -> AcceptanceCoveragePlanItem:
    if _criterion_requests_manual_authority(criterion):
        return AcceptanceCoveragePlanItem(
            criterion_id=criterion.id,
            priority=criterion.priority,
            description=criterion.description,
            test_method=criterion.test_method,
            evidence_kind=criterion.evidence_kind,
            coverage_mode=COVERAGE_MODE_MANUAL_AUTHORITY,
            deterministic=False,
            manual_authority=criterion.manual_authority,
            uncovered_reason=None if criterion.manual_authority else "manual_authority_missing",
            source_coverage_status=criterion.coverage_status,
        )

    if criterion.coverage_status == "uncovered" or criterion.unverifiable_reason:
        return _uncovered_plan_item(
            criterion,
            criterion.unverifiable_reason or "criterion is explicitly marked uncovered",
        )

    if _criterion_uses_only_llm_judge(criterion):
        return _uncovered_plan_item(criterion, "llm_only_without_deterministic_evidence")

    verifier_check_id = _verifier_check_id_for_criterion(criterion)
    if verifier_check_id:
        return AcceptanceCoveragePlanItem(
            criterion_id=criterion.id,
            priority=criterion.priority,
            description=criterion.description,
            test_method=criterion.test_method,
            evidence_kind=criterion.evidence_kind,
            coverage_mode=COVERAGE_MODE_VERIFIER_CHECK,
            deterministic=True,
            verifier_check_id=verifier_check_id,
            source_coverage_status=criterion.coverage_status,
        )

    if criterion.fixture_ref:
        return AcceptanceCoveragePlanItem(
            criterion_id=criterion.id,
            priority=criterion.priority,
            description=criterion.description,
            test_method=criterion.test_method,
            evidence_kind=criterion.evidence_kind,
            coverage_mode=COVERAGE_MODE_FIXTURE,
            deterministic=True,
            fixture_ref=criterion.fixture_ref,
            source_coverage_status=criterion.coverage_status,
        )

    qa_checks = _qa_report_checks_for_criterion(criterion)
    if qa_checks:
        return AcceptanceCoveragePlanItem(
            criterion_id=criterion.id,
            priority=criterion.priority,
            description=criterion.description,
            test_method=criterion.test_method,
            evidence_kind=criterion.evidence_kind,
            coverage_mode=COVERAGE_MODE_QA_REPORT_CHECK,
            deterministic=True,
            qa_report_checks=qa_checks,
            source_coverage_status=criterion.coverage_status,
        )

    if criterion.required_evidence and criterion.evidence_kind in {"file", "command"}:
        return AcceptanceCoveragePlanItem(
            criterion_id=criterion.id,
            priority=criterion.priority,
            description=criterion.description,
            test_method=criterion.test_method,
            evidence_kind=criterion.evidence_kind,
            coverage_mode=COVERAGE_MODE_REQUIRED_EVIDENCE,
            deterministic=True,
            required_evidence_refs=list(criterion.required_evidence),
            source_coverage_status=criterion.coverage_status,
        )

    return _uncovered_plan_item(criterion, "no_deterministic_evidence_mapping")


def _uncovered_plan_item(criterion: AcceptanceCriterion, reason: str) -> AcceptanceCoveragePlanItem:
    return AcceptanceCoveragePlanItem(
        criterion_id=criterion.id,
        priority=criterion.priority,
        description=criterion.description,
        test_method=criterion.test_method,
        evidence_kind=criterion.evidence_kind,
        coverage_mode=COVERAGE_MODE_UNCOVERED,
        deterministic=False,
        uncovered_reason=reason,
        source_coverage_status=criterion.coverage_status,
    )


def _evaluate_plan_item(
    workspace: JobWorkspace,
    item: AcceptanceCoveragePlanItem,
    *,
    qa_report: Mapping[str, Any] | None,
    verifier_result: VerificationResult | None,
    manual_acceptance_record: Mapping[str, Any] | None,
    manual_acceptance_record_ref: str | None,
    acceptance_criteria_hash: str,
) -> AcceptanceCoverageResultItem:
    if item.coverage_mode == COVERAGE_MODE_UNCOVERED:
        return _result_item(
            item,
            status=COVERAGE_RESULT_STATUS_UNCOVERED,
            passed=False,
            evidence_refs=[],
            failures=[item.uncovered_reason or "uncovered"],
            uncovered_reason=item.uncovered_reason,
        )

    if item.coverage_mode == COVERAGE_MODE_MANUAL_AUTHORITY:
        return _evaluate_manual_authority(
            item,
            manual_acceptance_record=manual_acceptance_record,
            manual_acceptance_record_ref=manual_acceptance_record_ref,
            acceptance_criteria_hash=acceptance_criteria_hash,
        )

    if item.coverage_mode == COVERAGE_MODE_VERIFIER_CHECK:
        return _evaluate_verifier_check(workspace, item, verifier_result)

    if item.coverage_mode == COVERAGE_MODE_QA_REPORT_CHECK:
        return _evaluate_qa_report_check(item, qa_report)

    if item.coverage_mode == COVERAGE_MODE_FIXTURE:
        return _evaluate_file_refs(workspace, item, [item.fixture_ref] if item.fixture_ref else [])

    if item.coverage_mode == COVERAGE_MODE_REQUIRED_EVIDENCE:
        return _evaluate_file_refs(workspace, item, item.required_evidence_refs)

    return _result_item(
        item,
        status=COVERAGE_RESULT_STATUS_UNCOVERED,
        passed=False,
        evidence_refs=[],
        failures=[f"unsupported coverage_mode: {item.coverage_mode}"],
        uncovered_reason="unsupported_coverage_mode",
    )


def _evaluate_verifier_check(
    workspace: JobWorkspace,
    item: AcceptanceCoveragePlanItem,
    verifier_result: VerificationResult | None,
) -> AcceptanceCoverageResultItem:
    if verifier_result is None:
        return _result_item(
            item,
            status=COVERAGE_RESULT_STATUS_COVERED_FAIL,
            passed=False,
            evidence_refs=[VERIFICATION_RESULT_REF],
            failures=["verifier result is missing or invalid"],
        )
    checks = _checks_by_name(verifier_result.checks)
    check = checks.get(str(item.verifier_check_id))
    if check is None and item.verifier_check_id in _SYNTHETIC_VERIFIER_CHECK_IDS:
        return _evaluate_synthetic_verifier_check(workspace, item, checks)
    if check is None:
        return _result_item(
            item,
            status=COVERAGE_RESULT_STATUS_COVERED_FAIL,
            passed=False,
            evidence_refs=[VERIFICATION_RESULT_REF],
            failures=[f"verifier check {item.verifier_check_id!r} was not found"],
        )
    passed = check.get("passed") is True
    evidence_refs = [VERIFICATION_RESULT_REF]
    evidence_ref = check.get("evidence_ref")
    if isinstance(evidence_ref, str) and evidence_ref.strip():
        evidence_refs.append(evidence_ref)
    return _result_item(
        item,
        status=COVERAGE_RESULT_STATUS_COVERED_PASS if passed else COVERAGE_RESULT_STATUS_COVERED_FAIL,
        passed=passed,
        evidence_refs=_dedupe(evidence_refs),
        failures=[] if passed else [str(check.get("message") or "verifier check failed")],
    )


def _evaluate_synthetic_verifier_check(
    workspace: JobWorkspace,
    item: AcceptanceCoveragePlanItem,
    checks: Mapping[str, Mapping[str, Any]],
) -> AcceptanceCoverageResultItem:
    check_id = str(item.verifier_check_id)
    evidence_refs: list[str] = [VERIFICATION_RESULT_REF]
    failures: list[str] = []

    if check_id == "package_contract_present":
        _require_verifier_checks(checks, failures, "package_skill_md_present", "package_cargo_toml_present")
        _require_any_verifier_check(checks, failures, ("package_rust_sources_present",), "Rust source files")
        _require_paths(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/Cargo.toml",
        )
        _require_any_path(workspace, evidence_refs, failures, "Rust source file", ("package/src/lib.rs", "package/src/main.rs"))
        _require_any_glob(workspace, evidence_refs, failures, "documentation file", "package/docs/*.md")
        _require_any_glob(workspace, evidence_refs, failures, "test fixture file", "package/tests/fixtures/**/*")
        _require_any_text_group(
            _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md", "package/docs/security-boundary.md"),
            failures,
            "security boundary documentation",
            ("security boundary", "safety", "raw sensitive", "sensitive material"),
        )
    elif check_id == "skill_package_instruction_contract":
        _require_verifier_checks(checks, failures, "package_skill_md_present")
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md")
        _require_text_groups(
            text,
            failures,
            [
                ("skill name", ("name: codexarium", "# codexarium")),
                ("trigger guidance", ("when to use", "use this skill")),
                ("input requirements", ("inputs", "required inputs")),
                ("output structure", ("outputs", "primary outputs")),
                ("workflow", ("workflow",)),
                ("safety boundary", ("safety", "boundary")),
                ("confirmation gate", ("confirmation", "confirm", "wait for explicit user confirmation")),
                ("refusal conditions", ("refuse", "do not use", "stop")),
            ],
        )
    elif check_id == "skill_instruction_content":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md")
        _require_text_groups(
            text,
            failures,
            [
                ("trigger guidance", ("trigger phrases", "when to use")),
                ("non-trigger guidance", ("when not to use", "do not use")),
                ("evidence boundary", ("evidence manifest", "compact evidence", "evidence boundary")),
                ("confirmation gate", ("confirmation", "confirm", "wait for user")),
                ("write workflow", ("workflow", "write")),
                ("conflict policy", ("conflict", "no overwrite", "update", "append", "merge")),
                ("refusal or failure policy", ("refuse", "stop", "failure")),
                ("raw sensitive material policy", ("raw sensitive", "sensitive material", "do not save", "never save")),
            ],
        )
    elif check_id == "skill_clean_room_boundary":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md", "worker_input.md", "evidence/transcript.md")
        _require_text_groups(
            text,
            failures,
            [
                ("clean-room statement", ("clean-room", "clean room")),
                (
                    "existing implementation exclusion",
                    (
                        "does not depend",
                        "does not inspect",
                        "do not read",
                        "do not read, depend",
                        "existing local codexarium",
                        "existing local codexarium code",
                        "from the frozen skillfoundry inputs",
                        "frozen front desk sources",
                    ),
                ),
                ("current user-provided boundary", ("user-provided", "current user", "user-authorized", "user explicitly")),
            ],
        )
    elif check_id == "skill_scope_exclusion_boundary":
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/references/safety.md",
            "package/references/security-boundary.md",
        )
        _require_text_groups(
            text,
            failures,
            [
                ("chat backup excluded", ("chat backup", "chat logs")),
                (
                    "automatic collection excluded",
                    ("automatic collection", "background ingestion", "background collector", "background collection"),
                ),
                ("network sync excluded", ("network sync", "cloud publishing", "cloud sync")),
                ("full-disk scan excluded", ("full-disk", "full disk", "full-disk scanning", "full-disk scan")),
                ("database service excluded", ("database service", "databases")),
            ],
        )
    elif check_id == "skill_privacy_boundary":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md", "package/docs/security-boundary.md")
        _require_text_groups(
            text,
            failures,
            [
                ("explicit input boundary", ("user-provided", "explicitly", "approved")),
                ("JSON evidence manifest", ("json evidence manifest", "evidence manifest")),
                ("compact evidence", ("compact evidence", "compact collaboration evidence")),
                ("raw chat exclusion", ("raw chat", "chat logs")),
                ("terminal output exclusion", ("terminal output", "terminal-output", "stdout", "stderr", "command output")),
                (
                    "arbitrary scan exclusion",
                    ("arbitrary files", "whole-disk", "full-disk", "full disk", "automatic filesystem scan", "automatic collection"),
                ),
                (
                    "network/database/background exclusion",
                    ("network sync", "network services", "database service", "background ingestion", "daily reports"),
                ),
            ],
        )
    elif check_id == "skill_user_evidence_boundary":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md")
        _require_text_groups(
            text,
            failures,
            [
                ("user-provided JSON manifest", ("user-provided json evidence manifest", "json evidence manifest")),
                ("compact notes", ("compact evidence notes", "compact notes")),
                ("raw chat exclusion", ("raw chat", "raw conversations", "chat logs")),
                ("terminal/private/arbitrary exclusion", ("terminal output", "private paths", "arbitrary files")),
                (
                    "no scanning beyond supplied evidence",
                    (
                        "do not read or search beyond",
                        "never scan",
                        "refuse to scan",
                        "do not inspect",
                        "unprovided sources",
                        "do not discover it by scanning",
                        "do not authorize reading",
                    ),
                ),
            ],
        )
    elif check_id == "evidence_authorization_gate":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md")
        _require_text_groups(
            text,
            failures,
            [
                ("authorization confirmation", ("explicitly authorize", "explicit authorization", "authorized")),
                ("missing manifest stop", ("required fields are missing", "missing", "stop")),
                ("allowed_use enforcement", ("allowed_use",)),
                ("sensitivity enforcement", ("sensitivity",)),
                ("unknown evidence refusal", ("unknown evidence_id", "unknown `evidence_id`")),
                ("refuse or stop behavior", ("refuse", "stop")),
            ],
        )
    elif check_id == "evidence_references_contract":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md")
        _require_text_groups(
            text,
            failures,
            [
                ("evidence references required", ("evidence references", "evidence_id references", "evidence:<id>")),
                (
                    "known manifest IDs",
                    (
                        "known in the manifest",
                        "known `evidence_id`",
                        "known evidence",
                        "exist in the manifest",
                        "exists in the manifest",
                        "manifest-backed",
                        "manifest `evidence_id`",
                    ),
                ),
                ("allowed evidence use", ("allowed", "allowed_use")),
                ("candidate or wiki validation", ("candidate", "wiki")),
            ],
        )
    elif check_id == "manifest_schema_documented":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md", "package/docs/manifest-schema.md")
        _require_text_groups(
            text,
            failures,
            [
                ("JSON manifest", ("json",)),
                ("evidence_id", ("evidence_id",)),
                ("source_type", ("source_type",)),
                ("title", ("title",)),
                ("summary", ("summary",)),
                ("allowed_use", ("allowed_use",)),
                ("sensitivity", ("sensitivity",)),
                ("created_at", ("created_at",)),
                ("optional project", ("project",)),
                ("optional tags", ("tags",)),
                ("optional related_entries", ("related_entries",)),
            ],
        )
    elif check_id == "candidate_table_contract":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md")
        _require_text_groups(
            text,
            failures,
            [
                ("candidate table", ("candidate table",)),
                ("entry_type", ("entry_type",)),
                ("title", ("title",)),
                ("target wiki path", ("target wiki path", "target_path")),
                ("summary", ("summary",)),
                ("evidence references", ("evidence references", "evidence_refs")),
                ("related links", ("related links", "related_links")),
                ("uncertainty", ("uncertainty",)),
                ("before writing", ("before any write", "before writing", "before files are written")),
            ],
        )
    elif check_id == "candidate_entry_semantics":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md")
        _require_text_groups(
            text,
            failures,
            [
                ("project context", ("project context",)),
                ("decision", ("decision",)),
                ("principle", ("principle",)),
                ("lesson", ("lesson",)),
                ("open question", ("open question",)),
                ("experiment", ("experiment",)),
            ],
        )
    elif check_id == "wiki_structure_contract":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md", "package/docs/wiki-structure.md")
        _require_text_groups(
            text,
            failures,
            [
                ("index directory", ("index",)),
                ("projects directory", ("projects",)),
                ("concepts directory", ("concepts",)),
                ("decisions directory", ("decisions",)),
                ("experiments directory", ("experiments",)),
                ("retrospectives directory", ("retrospectives",)),
                ("open-questions directory", ("open-questions",)),
                ("principles directory", ("principles",)),
            ],
        )
    elif check_id == "wiki_structure_and_paths_contract":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md", "package/docs/wiki-structure.md")
        _require_text_groups(
            text,
            failures,
            [
                ("wiki structure described", ("wiki structure", "wiki taxonomy", "wiki root", "top-level directories", "directories")),
                ("decisions directory", ("decisions",)),
                ("projects directory", ("projects",)),
                ("open-questions directory", ("open-questions",)),
                ("principles directory", ("principles",)),
                ("research directory", ("research", "research-notes")),
                ("lessons directory", ("lessons",)),
                ("decision path example", ("decisions/<slug>.md", "decisions/")),
                ("project path example", ("projects/<project>/index.md", "projects/")),
            ],
        )
    elif check_id == "path_generation_contract":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md", "package/docs/wiki-structure.md")
        _require_text_groups(
            text,
            failures,
            [
                ("entry_type based path", ("entry_type", "entry type")),
                ("slug based path", ("slug",)),
                ("decision path example", ("decisions/<slug>.md", "decisions/")),
                ("project path example", ("projects/<project>/index.md", "projects/")),
            ],
        )
    elif check_id == "write_conflict_policy_contract":
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/references/safety.md",
            "package/references/schema.md",
        )
        text += "\n" + _read_glob_text(
            workspace,
            evidence_refs,
            failures,
            "package/src/*.rs",
            "package/tests/**/*.rs",
        )
        _require_text_groups(
            text,
            failures,
            [
                (
                    "no overwrite default",
                    ("no overwrite", "do not overwrite", "without overwrite", "not overwritten", "overwrites"),
                ),
                ("conflict proposal", ("conflict proposal", "proposal")),
                (
                    "non-destructive conflict behavior",
                    (
                        "not overwrite",
                        "no overwrite",
                        "not directly",
                        "instead of overwriting",
                        "stop before writing",
                        "without overwrite",
                        "conflicts require",
                        "conflict blocks writing",
                        "create_new",
                    ),
                ),
                ("confirmation before conflict write", ("confirm", "confirmation", "wait for user", "user decision")),
            ],
        )
    elif check_id == "rust_verifier_package_present":
        _require_verifier_checks(checks, failures, "package_cargo_toml_present", "package_rust_sources_present")
        _require_any_glob(workspace, evidence_refs, failures, "Rust verifier fixture file", "package/**/tests/fixtures/**/*")
        _require_any_glob(workspace, evidence_refs, failures, "Rust verifier test file", "package/**/tests/**/*.rs")
    elif check_id == "rust_verifier_core_validation":
        _require_verifier_checks(checks, failures, "package_cargo_test")
        text = _read_glob_text(
            workspace,
            evidence_refs,
            failures,
            "package/src/*.rs",
            "package/tests/**/*.rs",
            "package/**/src/*.rs",
            "package/**/tests/**/*.rs",
        )
        _require_text_groups(
            text,
            failures,
            [
                ("manifest validation", ("manifest",)),
                ("evidence_id validation", ("evidence_id",)),
                ("duplicate evidence rejection", ("duplicate",)),
                ("required wiki directory validation", ("required wiki", "required_wiki")),
                ("unknown evidence reference rejection", ("unknown evidence", "known evidence")),
                ("invalid fixture rejection", ("invalid", "fixture")),
            ],
        )
    elif check_id == "rust_verifier_path_safety":
        _require_verifier_checks(checks, failures, "package_cargo_test")
        text = _read_glob_text(
            workspace,
            evidence_refs,
            failures,
            "package/src/*.rs",
            "package/tests/**/*.rs",
            "package/**/src/*.rs",
            "package/**/tests/**/*.rs",
        )
        _require_text_groups(
            text,
            failures,
            [
                (
                    "target path validation",
                    (
                        "target path",
                        "target_path",
                        "destination path",
                        "destination paths",
                        "destination",
                        "relative_path",
                        "planned paths",
                        "write target",
                    ),
                ),
                ("absolute path rejection", ("absolute", "relative", "destination path")),
                ("parent traversal rejection", ("parent", "..", "parentdir")),
                ("unsafe path fixture", ("unsafe", "traversal")),
            ],
        )
    elif check_id == "package_cargo_test":
        _require_verifier_checks(checks, failures, "package_cargo_test")
        evidence_refs.append("verifier/cargo_test.log")
    elif check_id == "local_smoke_command_documented":
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/docs/smoke-verification.md",
            "package/references/runtime_and_tests.md",
        )
        has_cli_smoke = _text_has_any(text, ("cargo run", "validate-manifest", "validate-wiki", "validate-candidate"))
        has_cargo_test_smoke = _text_has_any(text, ("cargo test",))
        if not (has_cli_smoke or has_cargo_test_smoke):
            failures.append(
                "local smoke command: expected one of cargo test, cargo run, validate-manifest, "
                "validate-wiki, validate-candidate"
            )
        if has_cli_smoke:
            _require_text_groups(
                text,
                failures,
                [
                    ("manifest argument", ("manifest",)),
                    ("wiki argument", ("wiki",)),
                ],
            )
        if has_cargo_test_smoke:
            _require_verifier_checks(checks, failures, "package_cargo_test")
            _require_text_groups(
                text,
                failures,
                [
                    ("local test scope", ("local", "skill package root", "package/cargo.toml", "--manifest-path")),
                    ("verification expectation", ("verification", "expected evidence", "fixture", "test")),
                ],
            )
    elif check_id == "codexarium_taxonomy_contract":
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/references/codexarium_reference.md",
            "package/references/taxonomy.md",
        )
        _require_text_groups(
            text,
            failures,
            [
                ("fixed taxonomy", ("fixed taxonomy", "taxonomy")),
                ("projects category", ("projects", "project")),
                ("domain knowledge category", ("domain_knowledge", "domain knowledge", "domain")),
                ("workflows category", ("workflows", "workflow")),
                ("decisions category", ("decisions", "decision")),
                ("references/snippets category", ("references_or_snippets", "references", "snippets", "reference", "snippet")),
            ],
        )
    elif check_id == "codexarium_manifest_compact_contract":
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/references/codexarium_reference.md",
            "package/references/artifact-formats.md",
            "package/examples/manifest.cdxm",
            "package/examples/compact_note.cdxn",
        )
        _require_text_groups(
            text,
            failures,
            [
                ("manifest format", ("manifest format", "manifest_version", "manifest")),
                ("compact note format", ("compact note format", "compact_note_version", "compact note", "compact notes")),
                ("stable version", ("version", "v1")),
                ("entry path", ("path", "source_path")),
                ("summary", ("summary",)),
            ],
        )
    elif check_id == "codexarium_fixture_scenario_coverage":
        _require_verifier_checks(checks, failures, "package_cargo_test")
        _require_any_glob(workspace, evidence_refs, failures, "Codexarium fixture file", "package/**/fixtures/**/*")
        text = _read_glob_text(
            workspace,
            evidence_refs,
            failures,
            "package/**/fixtures/**/*",
            "package/references/*.md",
            "package/src/*.rs",
        )
        _require_text_groups(
            text,
            failures,
            [
                ("valid fixture", ("valid_wiki", "valid wiki", "valid fixture")),
                ("conflict fixture", ("conflict_wiki", "conflict")),
                ("path escape fixture", ("path_escape_wiki", "path-traversal", "path traversal", "parent traversal")),
                ("taxonomy error fixture", ("taxonomy_error_wiki", "bad-taxonomy", "taxonomy error", "invalid taxonomy", "taxonomy")),
                ("manifest or compact error fixture", ("bad_manifest_wiki", "bad-compact-note", "bad compact", "compact note", "manifest")),
            ],
        )
    elif check_id == "codexarium_local_runtime_contract":
        _require_verifier_checks(checks, failures, "package_cargo_test")
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/references/runtime_and_tests.md",
        )
        _require_text_groups(
            text,
            failures,
            [
                ("local runtime", ("local",)),
                ("cargo test", ("cargo test",)),
                ("no external services", ("external services", "no external service", "does not call external services")),
                ("workspace verification", ("workspace", "skill package root", "package/cargo.toml")),
            ],
        )
    elif check_id == "codexarium_explicit_wiki_root_contract":
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/references/codexarium_reference.md",
            "package/references/acceptance_coverage.md",
            "package/references/safety.md",
            "package/references/schema.md",
        )
        _require_text_groups(
            text,
            failures,
            [
                ("explicit wiki root", ("explicit wiki root", "wiki root", "wiki_root")),
                (
                    "user supplied root",
                    (
                        "user supplied",
                        "user-supplied",
                        "supplied by the user",
                        "provided by the user",
                        "user must supply",
                    ),
                ),
                ("do not guess root", ("do not guess", "must not guess", "not guess", "infer a wiki location")),
            ],
        )
    elif check_id == "codexarium_synthetic_fixture_boundary":
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/references/codexarium_reference.md",
            "package/references/acceptance_coverage.md",
            "package/references/safety.md",
            "package/references/schema.md",
        )
        text += "\n" + _read_glob_text(
            workspace,
            evidence_refs,
            failures,
            "package/**/fixtures/**/*",
            "package/tests/fixtures/**/*",
            "package/examples/**/*",
        )
        _require_text_groups(
            text,
            failures,
            [
                ("synthetic examples or fixtures", ("synthetic",)),
                (
                    "no existing Codexarium dependency",
                    ("existing codexarium", "existing local codexarium", "existing codexarium code", "does not rely"),
                ),
                ("no real user data", ("real user data", "not real user", "not user data", "user data")),
            ],
        )
        _require_any_glob(workspace, evidence_refs, failures, "synthetic fixture or example file", "package/**/fixtures/**/*")
    elif check_id == "codexarium_reference_documentation_contract":
        _require_any_glob(workspace, evidence_refs, failures, "reference documentation file", "package/references/*.md")
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/SKILL.md",
            "package/references/codexarium_reference.md",
            "package/references/acceptance_coverage.md",
            "package/references/schema.md",
            "package/references/safety.md",
        )
        text += "\n" + _read_glob_text(
            workspace,
            evidence_refs,
            failures,
            "package/tests/fixtures/**/*",
            "package/**/fixtures/**/*",
            "package/examples/**/*",
        )
        _require_text_groups(
            text,
            failures,
            [
                ("compact evidence or compact notes", ("compact evidence", "compact note", "compact notes")),
                ("JSON manifest", ("json evidence manifest", "evidence manifest", "manifest")),
                ("note drafts or markdown notes", ("note draft", "note drafts", "markdown note", "markdown notes")),
                ("expected write plan or output", ("expected write plan", "write plan", "expected output")),
                ("safety or error examples", ("safety", "error examples", "validation errors", "errors")),
            ],
        )
    elif check_id == "downstream_verifier_acceptance_gate":
        _require_verifier_checks(checks, failures, "package_skill_md_present")
        _require_any_verifier_check(checks, failures, ("package_cargo_test", "sandbox_smoke"), "downstream verifier gate")
        _require_paths(
            workspace,
            evidence_refs,
            failures,
            "verifier/verification_result.json",
            "qa/acceptance_coverage_plan.json",
        )
        text = _read_refs_text(
            workspace,
            evidence_refs,
            failures,
            "package/references/acceptance_coverage.md",
            "package/references/safety.md",
            "package/references/schema.md",
            "qa/acceptance_coverage_plan.json",
            "verifier/verification_result.json",
            "evidence/manifest.json",
        )
        _require_text_groups(
            text,
            failures,
            [
                (
                    "acceptance coverage",
                    (
                        "acceptance coverage",
                        "acceptance criteria",
                        "coverage",
                        "coverage_plan",
                        "acceptance_coverage",
                        "acceptance_coverage_plan",
                    ),
                ),
                (
                    "validation or verifier evidence",
                    ("verifier", "verification_result", "validation", "validation commands", "package_cargo_test"),
                ),
            ],
        )
    elif check_id == "rust_verifier_fixture_coverage":
        _require_verifier_checks(checks, failures, "package_cargo_test")
        valid_fixture_refs = _glob_refs(workspace, "package/**/tests/fixtures/valid/**/*")
        valid_fixture_refs.extend(_glob_refs(workspace, "package/**/tests/fixtures/**/*valid*"))
        valid_fixture_refs.extend(_glob_refs(workspace, "package/**/fixtures/valid*/**/*"))
        if valid_fixture_refs:
            evidence_refs.extend(_dedupe(valid_fixture_refs)[:8])
        else:
            failures.append(
                "valid fixture: no file matched package/**/tests/fixtures/valid/**/*, "
                "package/**/tests/fixtures/**/*valid*, or package/**/fixtures/valid*/**/*"
            )
        fixture_text = _read_glob_text(
            workspace,
            evidence_refs,
            failures,
            "package/**/tests/fixtures/**/*",
            "package/**/fixtures/**/*",
            "package/**/tests/**/*.rs",
            "package/src/*.rs",
        )
        _require_text_groups(
            fixture_text,
            failures,
            [
                ("missing field fixture", ("missing_field", "missing field", "missing required")),
                ("duplicate evidence fixture", ("duplicate",)),
                ("unknown evidence fixture", ("unknown", "missing evidence", "missing_evidence", "evidence references")),
                ("allowed_use fixture", ("allowed_use",)),
                ("sensitivity fixture", ("sensitivity",)),
                ("invalid slug/path fixture", ("invalid_target", "illegal slug", "path traversal", "target escape")),
                (
                    "missing directory fixture",
                    (
                        "missing_dir",
                        "missing required directory",
                        "missing required wiki dirs",
                        "missing_required_wiki_dirs",
                        "taxonomy directory",
                        "full fixed taxonomy",
                    ),
                ),
            ],
        )
    elif check_id == "local_deterministic_verifier_boundary":
        _require_verifier_checks(checks, failures, "package_cargo_test")
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md", "package/docs/security-boundary.md")
        _require_text_groups(
            text,
            failures,
            [
                ("local verifier", ("local verifier", "local rust verifier", "bundled verifier")),
                ("deterministic verifier", ("deterministic",)),
                ("network exclusion", ("no network", "does not perform networking", "networking", "network services")),
                ("scan/sync exclusion", ("scanning", "syncing", "broad filesystem scanning", "automatic filesystem scanning")),
                ("background service exclusion", ("background service", "background service behavior", "database work", "database service")),
            ],
        )
    elif check_id == "no_external_runtime_dependency":
        text = _read_refs_text(workspace, evidence_refs, failures, "package/SKILL.md", "package/docs/security-boundary.md")
        mentions_mcp = _text_has_any(text, ("mcp", "model context protocol"))
        mentions_cloud = _text_has_any(text, ("cloud", "cloud sync", "cloud synchronization", "cloud publishing"))
        groups: list[tuple[str, tuple[str, ...]]] = []
        if mentions_mcp:
            groups.append(("MCP not required", ("no mcp", "not require mcp", "do not require mcp", "without mcp")))
        groups.extend(
            [
                (
                    "database not required",
                    ("no database", "not require database", "do not require database", "without database", "database service"),
                ),
                (
                    "network not required",
                    (
                        "no network",
                        "not require network",
                        "do not require network",
                        "without network",
                        "network access",
                        "network sync",
                        "network synchronization",
                    ),
                ),
            ]
        )
        if mentions_cloud:
            groups.append(
                (
                    "cloud sync not required",
                    ("no cloud sync", "not require cloud sync", "do not require cloud sync", "cloud sync", "cloud synchronization"),
                )
            )
        groups.append(
            (
                "automatic scan not required",
                (
                    "no automatic",
                    "not require automatic",
                    "do not require automatic",
                    "automatic filesystem scan",
                    "automatic full-disk",
                    "full-disk scan",
                ),
            )
        )
        _require_text_groups(
            text,
            failures,
            groups,
        )
    else:
        failures.append(f"unsupported synthetic verifier check: {check_id}")

    passed = not failures
    return _result_item(
        item,
        status=COVERAGE_RESULT_STATUS_COVERED_PASS if passed else COVERAGE_RESULT_STATUS_COVERED_FAIL,
        passed=passed,
        evidence_refs=_dedupe(evidence_refs),
        failures=failures,
    )


def _evaluate_manual_authority(
    item: AcceptanceCoveragePlanItem,
    *,
    manual_acceptance_record: Mapping[str, Any] | None,
    manual_acceptance_record_ref: str | None,
    acceptance_criteria_hash: str,
) -> AcceptanceCoverageResultItem:
    if not item.manual_authority:
        return _result_item(
            item,
            status=COVERAGE_RESULT_STATUS_UNCOVERED,
            passed=False,
            evidence_refs=[],
            failures=["manual_authority metadata is required for manual-only coverage"],
            uncovered_reason=item.uncovered_reason or "manual_authority_missing",
        )
    if manual_acceptance_record is None:
        return _result_item(
            item,
            status=COVERAGE_RESULT_STATUS_UNCOVERED,
            passed=False,
            evidence_refs=[MANUAL_ACCEPTANCE_RECORD_REF],
            failures=["manual acceptance record is required for manual-only must criteria"],
            uncovered_reason="manual_acceptance_record_missing",
        )

    failures: list[str] = []
    if manual_acceptance_record.get("decision") != "approved":
        failures.append("manual acceptance record decision must be approved")
    for field_name in ("reviewer_id", "reviewer_role", "reason", "created_at"):
        value = manual_acceptance_record.get(field_name)
        if not isinstance(value, str) or not value.strip():
            failures.append(f"manual acceptance record {field_name} is required")
    covered_ids = manual_acceptance_record.get("covered_criterion_ids")
    if not isinstance(covered_ids, list) or item.criterion_id not in {str(value) for value in covered_ids}:
        failures.append(f"manual acceptance record does not cover criterion {item.criterion_id}")
    source_hash = manual_acceptance_record.get("source_hash")
    if source_hash != acceptance_criteria_hash:
        failures.append("manual acceptance record source_hash does not match acceptance criteria hash")

    passed = not failures
    return _result_item(
        item,
        status=COVERAGE_RESULT_STATUS_MANUAL_ONLY if passed else COVERAGE_RESULT_STATUS_UNCOVERED,
        passed=passed,
        evidence_refs=[manual_acceptance_record_ref or MANUAL_ACCEPTANCE_RECORD_REF],
        failures=failures,
        uncovered_reason=None if passed else "manual_acceptance_record_invalid",
    )


def _evaluate_qa_report_check(
    item: AcceptanceCoveragePlanItem,
    qa_report: Mapping[str, Any] | None,
) -> AcceptanceCoverageResultItem:
    if qa_report is None:
        return _result_item(
            item,
            status=COVERAGE_RESULT_STATUS_COVERED_FAIL,
            passed=False,
            evidence_refs=[QA_REPORT_REF],
            failures=["QA report is missing or invalid"],
        )
    checks_payload = qa_report.get("checks")
    checks = _checks_by_name(checks_payload if isinstance(checks_payload, list) else [])
    missing = [name for name in item.qa_report_checks if name not in checks]
    failed = [
        name
        for name in item.qa_report_checks
        if name in checks and checks[name].get("passed") is not True
    ]
    failures: list[str] = []
    failures.extend(f"QA check {name!r} was not found" for name in missing)
    failures.extend(
        f"QA check {name!r} failed: {checks[name].get('message') or 'no message'}"
        for name in failed
    )
    passed = not failures
    evidence_refs = [QA_REPORT_REF]
    for name in item.qa_report_checks:
        check = checks.get(name)
        if check is None:
            continue
        refs = check.get("evidence_refs")
        if isinstance(refs, list):
            evidence_refs.extend(str(ref) for ref in refs if str(ref).strip())
    return _result_item(
        item,
        status=COVERAGE_RESULT_STATUS_COVERED_PASS if passed else COVERAGE_RESULT_STATUS_COVERED_FAIL,
        passed=passed,
        evidence_refs=_dedupe(evidence_refs),
        failures=failures,
    )


def _evaluate_file_refs(
    workspace: JobWorkspace,
    item: AcceptanceCoveragePlanItem,
    refs: list[str],
) -> AcceptanceCoverageResultItem:
    failures: list[str] = []
    evidence_refs: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            failures.append("empty evidence ref")
            continue
        try:
            validate_relative_path(ref)
            path = workspace.resolve_path(ref, must_exist=True)
        except Exception as exc:
            failures.append(f"{ref}: missing or unsafe evidence ref: {exc}")
            continue
        if not path.is_file():
            failures.append(f"{ref}: evidence ref is not a file")
            continue
        evidence_refs.append(ref)
    passed = not failures and bool(refs)
    return _result_item(
        item,
        status=COVERAGE_RESULT_STATUS_COVERED_PASS if passed else COVERAGE_RESULT_STATUS_COVERED_FAIL,
        passed=passed,
        evidence_refs=evidence_refs,
        failures=failures or ([] if passed else ["no evidence refs were provided"]),
    )


def _result_item(
    item: AcceptanceCoveragePlanItem,
    *,
    status: str,
    passed: bool,
    evidence_refs: list[str],
    failures: list[str],
    uncovered_reason: str | None = None,
) -> AcceptanceCoverageResultItem:
    return AcceptanceCoverageResultItem(
        criterion_id=item.criterion_id,
        priority=item.priority,
        status=status,
        passed=passed,
        coverage_mode=item.coverage_mode,
        deterministic=item.deterministic,
        evidence_refs=evidence_refs,
        failures=failures,
        manual_authority=item.manual_authority,
        verifier_check_id=item.verifier_check_id,
        fixture_ref=item.fixture_ref,
        qa_report_checks=list(item.qa_report_checks),
        uncovered_reason=uncovered_reason,
    )


def _coerce_workspace(workspace: JobWorkspace | str | Path) -> JobWorkspace:
    if isinstance(workspace, JobWorkspace):
        return workspace
    root = Path(workspace)
    if not root.exists():
        raise FileNotFoundError(f"workspace does not exist: {root}")
    job_id = root.name
    manifest_path = root / "artifact_manifest.json"
    if manifest_path.exists():
        try:
            job_id = json.loads(manifest_path.read_text(encoding="utf-8")).get("job_id", job_id)
        except Exception:
            pass
    return JobWorkspace(root=root, job_id=str(job_id))


def _output_path(workspace: JobWorkspace, ref: str) -> Path:
    safe_ref = validate_relative_path(ref)
    parent = workspace.root.resolve(strict=True)
    for part in safe_ref.parts[:-1]:
        parent = parent / part
        if parent.exists() and parent.is_symlink():
            raise PathSecurityError(f"symlink component is not allowed: {ref}")
    parent.mkdir(parents=True, exist_ok=True)
    return resolve_under_root(workspace.root, ref)


def _coerce_plan(
    workspace: JobWorkspace,
    plan: AcceptanceCoveragePlan | Mapping[str, Any] | str | Path | None,
    plan_ref: str,
) -> AcceptanceCoveragePlan:
    if isinstance(plan, AcceptanceCoveragePlan):
        return plan
    if isinstance(plan, Mapping):
        return AcceptanceCoveragePlan.from_dict(plan)
    if plan is not None:
        return AcceptanceCoveragePlan.read_json_file(Path(plan))
    try:
        return AcceptanceCoveragePlan.read_json_file(workspace.resolve_path(plan_ref, must_exist=True))
    except Exception:
        return AcceptanceCriteriaPlanner().plan(workspace, output_ref=plan_ref)


def _read_json_evidence(
    workspace: JobWorkspace,
    ref: str,
) -> tuple[Mapping[str, Any] | None, str | None, str | None]:
    try:
        path = workspace.resolve_path(ref, must_exist=True)
        digest = sha256_file(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None
    if not isinstance(payload, Mapping):
        return None, ref, digest
    return payload, ref, digest


def _read_verifier_result(
    workspace: JobWorkspace,
) -> tuple[VerificationResult | None, str | None, str | None]:
    try:
        path = workspace.resolve_path(VERIFICATION_RESULT_REF, must_exist=True)
        digest = sha256_file(path)
        result = VerificationResult.read_json_file(path)
    except Exception:
        return None, None, None
    return result, VERIFICATION_RESULT_REF, digest


def _criterion_requests_manual_authority(criterion: AcceptanceCriterion) -> bool:
    return (
        criterion.coverage_status == "manual_only"
        or criterion.test_method in {"manual_check", "human_review"}
        or criterion.evidence_kind == "human_note"
    )


def _criterion_uses_only_llm_judge(criterion: AcceptanceCriterion) -> bool:
    if criterion.test_method != "llm_judge":
        return False
    has_non_model_ref = bool(criterion.verifier_check_id or criterion.fixture_ref)
    has_non_model_kind = criterion.evidence_kind != "model_judge"
    has_non_model_named_evidence = any(
        "llm" not in evidence.lower() and "model" not in evidence.lower()
        for evidence in criterion.required_evidence
    )
    return not (has_non_model_ref or has_non_model_kind or has_non_model_named_evidence)


def _verifier_check_id_for_criterion(criterion: AcceptanceCriterion) -> str | None:
    explicit = _normalize_machine_check_id(criterion.verifier_check_id)
    if explicit:
        return explicit
    if criterion.evidence_kind != "verifier_check":
        return None
    for evidence in criterion.required_evidence:
        evidence_check = _normalize_machine_check_id(evidence)
        if evidence_check:
            return evidence_check
    return _infer_synthetic_verifier_check_id(criterion)


def _normalize_machine_check_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    for prefix in ("verifier:", "verifier_check:", "check:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
    for prefix in ("verifier/verification_result.json#", "verifier/verification_result.json:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
    if normalized.startswith("/checks/"):
        normalized = normalized.rsplit("/", maxsplit=1)[-1]
    if _MACHINE_CHECK_ID_RE.match(normalized):
        return normalized
    return None


def _infer_synthetic_verifier_check_id(criterion: AcceptanceCriterion) -> str | None:
    text = _normalized_text(
        " ".join(
            [
                criterion.id,
                criterion.description,
                criterion.pass_condition,
                criterion.test_method,
                *criterion.required_evidence,
            ]
        )
    )
    if (
        "skill.md" in text
        and ("yaml frontmatter" in text or "valid yaml" in text)
        and (
            "overview" in text
            and "when to use" in text
            and "when not to use" in text
            and "inputs" in text
            and "outputs" in text
            and "workflow" in text
            and "safety" in text
        )
    ):
        return "package_skill_md_present"
    if (
        ("complete local codex skill package" in text or "complete local codex skill" in text)
        and "codexarium" in text
        and ("existing local codexarium" in text or "existing local" in text or "clean-room" in text)
    ):
        return "skill_clean_room_boundary"
    if "local codex skill package named codexarium" in text and "skill.md" in text:
        return "skill_package_instruction_contract"
    if (
        "existing local codexarium" in text
        and (
            "does not read" in text
            or "does not depend" in text
            or "copy" in text
            or "reference" in text
            or "implementation" in text
        )
    ):
        return "skill_clean_room_boundary"
    if (
        "skill.md" in text
        and ("trigger" in text or "non-trigger" in text or "non trigger" in text)
        and ("input" in text or "allowed inputs" in text)
        and ("output" in text or "expected outputs" in text)
        and "workflow" in text
        and ("safety" in text or "boundary" in text)
        and ("confirmation" in text or "confirm" in text)
        and ("refusal" in text or "refuse" in text)
        and not ("raw sensitive" in text or "sensitive materials" in text or "must not be saved" in text)
    ):
        return "skill_package_instruction_contract"
    if (
        "local and deterministic" in text
        and ("verifier" in text or "verification" in text)
        and ("networking" in text or "scanning" in text or "syncing" in text or "background service" in text)
    ):
        return "local_deterministic_verifier_boundary"
    if "smoke verification" in text or "smoke command" in text or "smoke" in text:
        return "local_smoke_command_documented"
    if "cargo test" in text:
        return "package_cargo_test"
    if (
        ("rust cargo project" in text or "cargo project" in text)
        and ("local cli" in text or "cli/helper" in text or "helper" in text)
    ):
        return "rust_verifier_package_present"
    if (
        "rust helper" in text
        and ("validates" in text or "validate" in text)
        and ("taxonomy" in text or "manifest" in text or "compact note" in text or "compact notes" in text)
    ):
        return "package_cargo_test"
    if (
        ("write plan" in text or "write plans" in text)
        and ("path traversal" in text or "outside the supplied wiki root" in text or "outside the wiki root" in text)
    ):
        return "rust_verifier_path_safety"
    if (
        "rust helper" in text
        and ("planned paths" in text or "path traversal" in text or "write target" in text)
        and ("wiki root" in text or "authorized wiki root" in text)
    ):
        return "rust_verifier_path_safety"
    if (
        "rust helper" in text
        and ("conflict proposal" in text or "conflicts" in text)
        and ("overwriting" in text or "overwrite" in text)
    ):
        return "write_conflict_policy_contract"
    if (
        ("markdown atomic notes" in text or "markdown notes" in text)
        and ("authorized wiki root" in text or "inside the wiki root" in text or "inside the authorized wiki root" in text)
    ):
        return "codexarium_explicit_wiki_root_contract"
    if (
        ("agent interface" in text or "何时使用" in text or "何时不使用" in text)
        and "skill.md" in text
        and ("输入" in text or "input" in text)
        and ("输出" in text or "output" in text)
    ):
        return "skill_package_instruction_contract"
    if (
        ("fixed taxonomy" in text or "固定 taxonomy" in text)
        and ("项目" in text or "projects" in text)
        and ("领域知识" in text or "domain" in text)
        and ("工作流" in text or "workflow" in text)
        and ("决策" in text or "decisions" in text)
    ):
        return "codexarium_taxonomy_contract"
    if (
        ("manifest" in text and ("compact notes" in text or "compact note" in text))
        and ("稳定格式" in text or "format" in text or "可检查示例" in text or "example" in text)
    ):
        return "codexarium_manifest_compact_contract"
    if (
        ("路径安全" in text or "path safety" in text)
        and ("路径穿越" in text or "traversal" in text or "root 外" in text or "outside" in text)
    ):
        return "rust_verifier_path_safety"
    if (
        ("不依赖外部服务" in text or "external services" in text or "external service" in text)
        and ("本地工作区" in text or "local workspace" in text or "locally" in text)
    ):
        return "codexarium_local_runtime_contract"
    if (
        ("explicit wiki root" in text or "wiki_root" in text or ("wiki root" in text and "user" in text))
        and ("guess" in text or "infer" in text or "real local path" in text or "local paths" in text)
    ):
        return "codexarium_explicit_wiki_root_contract"
    if (
        ("chat backup" in text or "chat-history" in text or "chat history" in text or "chat logs" in text)
        and ("automatic scanner" in text or "automatic scanning" in text or "full-disk" in text or "full disk" in text)
        and ("network sync" in text or "database service" in text or "background collector" in text)
    ):
        return "skill_scope_exclusion_boundary"
    if (
        ("synthetic" in text and ("fixtures" in text or "examples" in text))
        and ("existing codexarium" in text or "existing local codexarium" in text or "real user data" in text)
    ):
        return "codexarium_synthetic_fixture_boundary"
    if (
        (
            "references documentation" in text
            or "reference documentation" in text
            or "references documentation" in text
            or "references" in text
            or "package includes references" in text
        )
        and ("example input" in text or "example inputs" in text or "example output" in text or "example outputs" in text)
        and ("evidence manifest" in text or "evidence manifest example" in text)
    ):
        return "codexarium_reference_documentation_contract"
    if (
        (
            "references documentation" in text
            or "reference documentation" in text
            or "references documentation" in text
            or "references" in text
            or "package includes references" in text
        )
        and (
            "compact evidence" in text
            or "compact note" in text
            or "agent interface" in text
            or "runtime interface" in text
            or "example input" in text
            or "example inputs" in text
            or "example output" in text
            or "example outputs" in text
        )
        and (
            "json manifest" in text
            or "evidence manifest" in text
            or "evidence manifest example" in text
            or "example outputs" in text
            or "example output" in text
        )
        and (
            "write plan" in text
            or "expected output" in text
            or "safety boundaries" in text
            or "validation model" in text
        )
    ):
        return "codexarium_reference_documentation_contract"
    if (
        ("verifier" in text and "acceptance coverage" in text)
        and (
            "registry" in text
            or "approval" in text
            or "downstream" in text
            or "final package" in text
            or "final registration" in text
            or "before final registration" in text
        )
    ):
        return "downstream_verifier_acceptance_gate"
    if (
        "fixtures" in text
        and ("成功" in text or "valid" in text or "success" in text)
        and ("冲突" in text or "conflict" in text)
        and ("越界" in text or "escape" in text or "traversal" in text)
        and "taxonomy" in text
        and ("manifest" in text or "compact" in text)
    ):
        return "codexarium_fixture_scenario_coverage"
    if "rust verifier" in text and (
        "unsafe target" in text or "absolute path" in text or "parent-directory" in text or "traversal" in text
    ):
        return "rust_verifier_path_safety"
    if "rust verifier" in text and ("cargo.toml" in text or "tests/fixtures" in text):
        return "rust_verifier_package_present"
    if "rust verifier" in text or ("manifest shape" in text and "evidence_id" in text):
        return "rust_verifier_core_validation"
    if "valid fixture" in text and "invalid fixture" in text:
        return "rust_verifier_fixture_coverage"
    if "delivered package" in text or ("skill.md" in text and "rust project" in text):
        return "package_contract_present"
    if "trigger phrases" in text or (
        "skill.md" in text
        and "confirmation" in text
        and "conflict" in text
        and ("raw sensitive" in text or "sensitive materials" in text or "must not be saved" in text)
    ):
        return "skill_instruction_content"
    if (
        ("raw chat" in text or "terminal-output" in text or "terminal output" in text or "stdout/stderr" in text)
        and ("arbitrary file" in text or "whole-disk" in text or "full-disk" in text or "automatic collection" in text)
    ):
        return "skill_privacy_boundary"
    if (
        ("only user-explicitly-provided" in text or "user-explicitly-provided" in text or "user explicitly provided" in text)
        and "json evidence manifest" in text
        and "compact evidence notes" in text
    ):
        return "skill_user_evidence_boundary"
    if "manifest format" in text or ("evidence_id" in text and "source_type" in text and "allowed_use" in text):
        return "manifest_schema_documented"
    if "duplicate evidence_id" in text and ("verifier rejects" in text or "rejects duplicate" in text):
        return "rust_verifier_core_validation"
    if "candidate table" in text:
        return "candidate_table_contract"
    if "candidate entries" in text and ("open question" in text or "experiment" in text):
        return "candidate_entry_semantics"
    if "wiki taxonomy" in text and all(term in text for term in ("projects", "decisions", "open-questions", "principles")):
        return "wiki_structure_and_paths_contract"
    if (
        ("wiki structure" in text or "top-level directories" in text)
        and ("derived target paths" in text or "target paths" in text)
    ):
        return "wiki_structure_and_paths_contract"
    if "wiki structure" in text or "top-level directories" in text:
        return "wiki_structure_contract"
    if (
        ("target path" in text or "target-path" in text or "slug and target" in text or "path safety logic" in text)
        and (
            "绝对路径" in text
            or "父目录" in text
            or "非法 slug" in text
            or "absolute path" in text
            or "parent directory" in text
            or "outside the wiki root" in text
            or "backslashes" in text
        )
    ):
        return "rust_verifier_path_safety"
    if "target wiki paths" in text or ("entry_type" in text and "slug" in text) or (
        "target paths" in text and ("entry type" in text or "slug/project" in text)
    ):
        return "path_generation_contract"
    if (
        "authorization is unclear" in text
        or "authorization unclear" in text
        or ("allowed_use" in text and "sensitivity" in text and ("disallowed" in text or "duplicate evidence_id" in text))
        or ("unknown evidence" in text and ("stop" in text or "before processing" in text))
    ):
        return "evidence_authorization_gate"
    if "write conflict policy" in text or "no overwrite" in text or "no-overwrite" in text or (
        ("overwrite" in text or "overwrites" in text or "overwritten" in text)
        and "conflict" in text
        and ("update" in text or "append" in text or "merge" in text)
    ) or (
        "existing target" in text
        and ("update" in text or "append" in text or "merge" in text)
        and ("confirmation" in text or "confirms" in text)
    ) or (
        "never overwrite" in text
        or "never overwrites" in text
    ) or (
        "conflict proposal" in text
        and ("confirmation" in text or "confirm" in text or "before any conflicting write" in text)
    ):
        return "write_conflict_policy_contract"
    if "no mcp" in text or "cloud sync" in text or "database service" in text or "full-disk scan" in text:
        return "no_external_runtime_dependency"
    if ("skill 包包含" in text and "skill.md" in text) or "触发条件" in text:
        return "skill_package_instruction_contract"
    if "clean-room" in text or "既有 codexarium" in text:
        return "skill_clean_room_boundary"
    if "聊天记录备份" in text or "自动采集" in text or "联网同步" in text or "数据库服务" in text:
        return "skill_scope_exclusion_boundary"
    if "只允许处理用户提供" in text or "原始聊天" in text or "终端输出" in text or "任意文件" in text:
        return "skill_user_evidence_boundary"
    if "测试 fixtures" in text or "无效案例" in text:
        return "rust_verifier_fixture_coverage"
    if "必需字段" in text and "evidence_id" in text:
        return "manifest_schema_documented"
    if "明确授权" in text or "allowed_use/sensitivity" in text:
        return "evidence_authorization_gate"
    if "wiki 结构" in text and "target path" in text:
        return "wiki_structure_and_paths_contract"
    if "写入策略" in text or "默认不覆盖" in text:
        return "write_conflict_policy_contract"
    if (
        ("evidence references" in text or "evidence_id references" in text or "generated markdown" in text or "markdown wiki entries" in text)
        and ("known" in text or "manifest" in text or "review and reuse" in text or "substantive content" in text)
    ):
        return "evidence_references_contract"
    if "rust 本地 verifier" in text and "cargo.toml" in text:
        return "rust_verifier_package_present"
    if "rust verifier" in text and ("wiki/candidate" in text or "target path 安全" in text):
        return "rust_verifier_core_validation"
    return None


def _qa_report_checks_for_criterion(criterion: AcceptanceCriterion) -> list[str]:
    checks: list[str] = []
    if criterion.evidence_kind != "qa_report":
        return checks
    for evidence in criterion.required_evidence:
        normalized = _normalize_qa_check_name(evidence)
        if normalized:
            checks.append(normalized)
    return _dedupe(checks)


def _normalize_qa_check_name(value: str) -> str | None:
    normalized = value.strip()
    for prefix in ("qa:", "qa_report:", "quality_report:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
    for prefix in ("qa/quality_report.json#", "qa/quality_report.json:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
    if normalized.startswith("/checks/"):
        normalized = normalized.rsplit("/", maxsplit=1)[-1]
    if normalized in _QA_CHECK_NAMES:
        return normalized
    return normalized if normalized else None


def _checks_by_name(checks_payload: list[Any]) -> dict[str, Mapping[str, Any]]:
    checks: dict[str, Mapping[str, Any]] = {}
    for check in checks_payload:
        if not isinstance(check, Mapping):
            continue
        name = check.get("name")
        if isinstance(name, str) and name.strip() and name not in checks:
            checks[name] = check
    return checks


def _require_verifier_checks(
    checks: Mapping[str, Mapping[str, Any]],
    failures: list[str],
    *names: str,
) -> None:
    for name in names:
        check = checks.get(name)
        if check is None:
            failures.append(f"verifier check {name!r} was not found")
        elif check.get("passed") is not True:
            failures.append(f"verifier check {name!r} failed: {check.get('message') or 'no message'}")


def _require_any_verifier_check(
    checks: Mapping[str, Mapping[str, Any]],
    failures: list[str],
    names: tuple[str, ...],
    label: str,
) -> None:
    existing = [checks[name] for name in names if name in checks]
    if not existing:
        failures.append(f"no verifier check found for {label}")
        return
    if not any(check.get("passed") is True for check in existing):
        failures.append(f"no passing verifier check found for {label}")


def _require_paths(
    workspace: JobWorkspace,
    evidence_refs: list[str],
    failures: list[str],
    *refs: str,
) -> None:
    for ref in refs:
        try:
            path = workspace.resolve_path(ref, must_exist=True)
        except Exception as exc:
            failures.append(f"{ref}: missing or unsafe evidence ref: {exc}")
            continue
        if not path.is_file():
            failures.append(f"{ref}: expected file")
            continue
        evidence_refs.append(ref)


def _require_any_path(
    workspace: JobWorkspace,
    evidence_refs: list[str],
    failures: list[str],
    label: str,
    refs: tuple[str, ...],
) -> None:
    for ref in refs:
        try:
            path = workspace.resolve_path(ref, must_exist=True)
        except Exception:
            continue
        if path.is_file():
            evidence_refs.append(ref)
            return
    failures.append(f"{label}: no matching file found")


def _require_any_glob(
    workspace: JobWorkspace,
    evidence_refs: list[str],
    failures: list[str],
    label: str,
    pattern: str,
) -> None:
    refs = _glob_refs(workspace, pattern)
    if not refs:
        failures.append(f"{label}: no file matched {pattern}")
        return
    evidence_refs.extend(refs[:8])


def _read_refs_text(
    workspace: JobWorkspace,
    evidence_refs: list[str],
    failures: list[str],
    *refs: str,
) -> str:
    chunks: list[str] = []
    for ref in refs:
        try:
            path = workspace.resolve_path(ref, must_exist=True)
        except Exception:
            continue
        if not path.is_file():
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            evidence_refs.append(ref)
        except Exception as exc:
            failures.append(f"{ref}: could not read evidence text: {exc}")
    return _normalized_text("\n".join(chunks))


def _read_glob_text(
    workspace: JobWorkspace,
    evidence_refs: list[str],
    failures: list[str],
    *patterns: str,
) -> str:
    refs: list[str] = []
    for pattern in patterns:
        refs.extend(_glob_refs(workspace, pattern))
    chunks: list[str] = []
    for ref in _dedupe(refs)[:64]:
        try:
            path = workspace.resolve_path(ref, must_exist=True)
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            evidence_refs.append(ref)
        except Exception as exc:
            failures.append(f"{ref}: could not read evidence text: {exc}")
    return _normalized_text("\n".join(chunks))


def _glob_refs(workspace: JobWorkspace, pattern: str) -> list[str]:
    if pattern.startswith("/") or ".." in Path(pattern).parts:
        return []
    root = workspace.root.resolve()
    refs: list[str] = []
    for path in sorted(root.glob(pattern)):
        if not path.is_file():
            continue
        try:
            path.relative_to(root)
        except ValueError:
            continue
        refs.append(path.relative_to(root).as_posix())
    return refs


def _require_text_groups(
    text: str,
    failures: list[str],
    groups: list[tuple[str, tuple[str, ...]]],
) -> None:
    for label, alternatives in groups:
        _require_any_text_group(text, failures, label, alternatives)


def _require_any_text_group(
    text: str,
    failures: list[str],
    label: str,
    alternatives: tuple[str, ...],
) -> None:
    normalized_terms = [_normalized_text(term) for term in alternatives]
    if not any(term in text for term in normalized_terms):
        failures.append(f"{label}: expected one of {', '.join(alternatives)}")


def _text_has_any(text: str, alternatives: tuple[str, ...]) -> bool:
    normalized_terms = [_normalized_text(term) for term in alternatives]
    return any(term in text for term in normalized_terms)


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _coverage_score(items: list[AcceptanceCoverageResultItem]) -> float:
    if not items:
        return 100.0
    covered = len(
        [
            item
            for item in items
            if item.status
            in {
                COVERAGE_RESULT_STATUS_COVERED_PASS,
                COVERAGE_RESULT_STATUS_MANUAL_ONLY,
            }
        ]
    )
    return round((covered / len(items)) * 100.0, 2)


def _hash_package(workspace: JobWorkspace) -> tuple[str, list[str]]:
    entries: list[dict[str, JsonValue]] = []
    failures: list[str] = []
    try:
        package_root = workspace.resolve_path("package", must_exist=True).resolve(strict=True)
    except Exception as exc:
        return sha256_json({"package": "missing", "error": str(exc)}), [str(exc)]

    for path in sorted(package_root.rglob("*")):
        try:
            relative = path.relative_to(package_root).as_posix()
            validate_relative_path(relative)
        except Exception as exc:
            failures.append(f"{path}: {exc}")
            continue

        if path.is_symlink():
            entries.append({"path": relative, "kind": "symlink", "target": str(path.readlink())})
            failures.append(f"{relative}: symlink components are not allowed")
        elif path.is_file():
            entries.append({"path": relative, "kind": "file", "sha256": sha256_file(path), "size": path.stat().st_size})
        elif path.is_dir():
            entries.append({"path": relative, "kind": "dir"})
        else:
            entries.append({"path": relative, "kind": "other"})
            failures.append(f"{relative}: unsupported package path type")
    return sha256_json(entries), failures


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _require_non_empty_str(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")


def _require_optional_non_empty_str(value: Any, field_name: str) -> None:
    if value is not None:
        _require_non_empty_str(value, field_name)


def _require_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")


def _require_str_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list of strings")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(f"{field_name}[{index}] must be a non-empty string")


def _require_bool(value: Any, field_name: str) -> None:
    if not isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a boolean")


def _require_enum(value: Any, field_name: str, allowed: frozenset[str]) -> None:
    _require_non_empty_str(value, field_name)
    if value not in allowed:
        raise SchemaValidationError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")


def _require_sha256(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise SchemaValidationError(f"{field_name} must be a lowercase sha256 hex digest")


def _require_optional_sha256(value: Any, field_name: str) -> None:
    if value is not None:
        _require_sha256(value, field_name)


def _require_non_negative_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SchemaValidationError(f"{field_name} must be a non-negative integer")


def _require_finite_score(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be a finite number in [0.0, 100.0]")
    if float(value) < 0.0 or float(value) > 100.0:
        raise SchemaValidationError(f"{field_name} must be a finite number in [0.0, 100.0]")


def _require_json_mapping(value: Any, field_name: str) -> None:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{field_name} must be a JSON object")
    ensure_json_compatible(value, field_name)


__all__ = [
    "ACCEPTANCE_COVERAGE_PLAN_REF",
    "ACCEPTANCE_COVERAGE_PLAN_VERSION",
    "ACCEPTANCE_COVERAGE_RESULT_REF",
    "ACCEPTANCE_COVERAGE_RESULT_VERSION",
    "AcceptanceCriteriaPlanner",
    "AcceptanceCoverageEvaluator",
    "AcceptanceCoveragePlan",
    "AcceptanceCoveragePlanItem",
    "AcceptanceCoverageResult",
    "AcceptanceCoverageResultItem",
]
