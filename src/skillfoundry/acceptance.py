"""WP16 acceptance criteria coverage planning and evaluation.

This module bridges frozen Front Desk acceptance criteria into deterministic
QA/Verifier evidence. It does not call providers, execute arbitrary commands,
or ask an LLM to decide acceptance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
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
        package_hash, package_failures = _hash_package(job_workspace)
        plan_hash = sha256_file(job_workspace.resolve_path(plan_ref, must_exist=True))

        result_items = [
            _evaluate_plan_item(
                job_workspace,
                item,
                qa_report=qa_report,
                verifier_result=verifier_result,
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

    verifier_check_id = criterion.verifier_check_id
    if verifier_check_id is None and criterion.evidence_kind == "verifier_check" and criterion.required_evidence:
        verifier_check_id = criterion.required_evidence[0].strip()
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
        if item.manual_authority:
            return _result_item(
                item,
                status=COVERAGE_RESULT_STATUS_MANUAL_ONLY,
                passed=True,
                evidence_refs=[],
                failures=[],
            )
        return _result_item(
            item,
            status=COVERAGE_RESULT_STATUS_UNCOVERED,
            passed=False,
            evidence_refs=[],
            failures=["manual_authority metadata is required for manual-only coverage"],
            uncovered_reason=item.uncovered_reason or "manual_authority_missing",
        )

    if item.coverage_mode == COVERAGE_MODE_VERIFIER_CHECK:
        return _evaluate_verifier_check(item, verifier_result)

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
