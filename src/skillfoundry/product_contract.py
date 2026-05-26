"""Product-grade contract schemas for SkillFoundry delivery gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Self

from .schema import (
    JsonValue,
    SchemaModel,
    SchemaValidationError,
    _reject_unknown_fields,
    _require_bool,
    _require_json_mapping,
    _require_non_empty_str,
    _require_non_negative_int,
    _require_sha256,
    _require_str_list,
    utc_now,
)
from .security import PathSecurityError, validate_relative_path


PRODUCT_CONTRACT_DIR = "product_contract"
DELIVERY_PROFILE_CONTRACT_REF = "product_contract/delivery_profile.json"
RISK_PROFILE_REF = "product_contract/risk_profile.json"
PRODUCT_ACCEPTANCE_MATRIX_REF = "product_contract/product_acceptance_matrix.json"
PRODUCT_CONTRACT_COMPILER_REPORT_REF = "product_contract/compiler_report.json"
PRODUCT_GRADE_REPORT_REF = "qa/product_grade_report.json"
PRODUCT_REVIEWER_REPORT_REF = "qa/product_reviewer_report.json"
PRODUCT_REPAIR_PACKET_REF = "qa/product_repair_packet.json"

PRODUCT_CONTRACT_COMPILER_VERSION = "skillfoundry.product_contract_compiler.v1"
PRODUCT_GRADE_GATE_VERSION = "skillfoundry.product_grade_gate.v1"
PRODUCT_REPAIR_PLANNER_VERSION = "skillfoundry.product_repair_planner.v1"

DELIVERY_PROFILES = frozenset(
    {
        "codex_skill",
        "prompt_only_skill",
        "runtime_helper_skill",
        "local_file_safety_skill",
        "structured_input_skill",
        "reference_heavy_skill",
        "knowledge_db_skill",
        "data_conversion_skill",
        "mcp_connector_skill",
        "service_bundle_skill",
        "toolchain_skill",
    }
)

RISK_DOMAINS = frozenset(
    {
        "filesystem_write",
        "privacy_boundary",
        "privacy_sensitive_input",
        "structured_json_input",
        "structured_data_validation",
        "external_document_ingestion",
        "domain_knowledge_reliability",
        "network_boundary",
        "runtime_execution",
        "long_running_service",
        "distribution_package",
    }
)

PRODUCT_ACCEPTANCE_CHECK_KINDS = frozenset(
    {
        "static_evidence",
        "runtime_fixture_check",
        "runtime_command_check",
        "source_code_behavior_check",
        "docs_static_check",
        "manual_review_check",
        "llm_reviewer_check",
        "required_evidence_check",
    }
)

PRODUCT_FINDING_SEVERITIES = frozenset({"info", "warning", "major", "blocking"})
PRODUCT_GRADE_FAILING_SEVERITIES = frozenset({"major", "blocking"})
PRODUCT_REPAIR_SOURCE_KINDS = frozenset({"product_gate", "reviewer_report"})

FORBIDDEN_PRODUCT_CONTRACT_FIELDS = frozenset(
    {
        "conversation",
        "conversation_turns",
        "messages",
        "prompt",
        "prompts",
        "raw_prompt",
        "model_output",
        "model_outputs",
        "raw_model_output",
        "raw_model_outputs",
        "transcript",
        "raw_transcript",
        "raw_user_text",
        "raw_worker_input",
    }
)


def _require_enum(value: Any, field_name: str, allowed: frozenset[str]) -> None:
    _require_non_empty_str(value, field_name)
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise SchemaValidationError(f"{field_name} must be one of: {allowed_values}")


def _require_unique_str_list(value: Any, field_name: str, *, allowed: frozenset[str] | None = None) -> None:
    _require_str_list(value, field_name)
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in value:
        if item in seen and item not in duplicates:
            duplicates.append(item)
        seen.add(item)
        if allowed is not None and item not in allowed:
            allowed_values = ", ".join(sorted(allowed))
            raise SchemaValidationError(f"{field_name} contains unknown value {item!r}; allowed: {allowed_values}")
    if duplicates:
        raise SchemaValidationError(f"{field_name} contains duplicate value(s): {', '.join(duplicates)}")


def _require_ref(value: Any, field_name: str) -> None:
    _require_non_empty_str(value, field_name)
    try:
        validate_relative_path(value)
    except PathSecurityError as exc:
        raise SchemaValidationError(f"{field_name} must be a safe relative artifact ref: {exc}") from exc


def _require_ref_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list of artifact refs")
    for index, item in enumerate(value):
        _require_ref(item, f"{field_name}[{index}]")


def _require_score(value: Any, field_name: str) -> None:
    _require_non_negative_int(value, field_name)
    if value > 100:
        raise SchemaValidationError(f"{field_name} must be between 0 and 100")


def _reject_forbidden_keys(value: Any, field_name: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_PRODUCT_CONTRACT_FIELDS:
                raise SchemaValidationError(f"{field_name} contains forbidden raw field: {key}")
            _reject_forbidden_keys(item, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_keys(item, f"{field_name}[{index}]")


def _require_safe_json_mapping(value: Any, field_name: str) -> None:
    _require_json_mapping(value, field_name)
    _reject_forbidden_keys(value, field_name)


@dataclass
class DeliveryProfileContract(SchemaModel):
    job_id: str
    profiles: list[str]
    source_refs: list[str]
    inference_policy: str = "deterministic_profile_rules_v1"
    profile_reasons: dict[str, JsonValue] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.delivery_profile_contract.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_unique_str_list(self.profiles, "profiles", allowed=DELIVERY_PROFILES)
        _require_ref_list(self.source_refs, "source_refs")
        _require_non_empty_str(self.inference_policy, "inference_policy")
        _require_safe_json_mapping(self.profile_reasons, "profile_reasons")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass
class RiskProfile(SchemaModel):
    job_id: str
    risk_domains: list[str]
    source_refs: list[str]
    inference_policy: str = "deterministic_risk_rules_v1"
    risk_reasons: dict[str, JsonValue] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.risk_profile.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_unique_str_list(self.risk_domains, "risk_domains", allowed=RISK_DOMAINS)
        _require_ref_list(self.source_refs, "source_refs")
        _require_non_empty_str(self.inference_policy, "inference_policy")
        _require_safe_json_mapping(self.risk_reasons, "risk_reasons")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass
class ProductAcceptanceItem(SchemaModel):
    item_id: str
    requirement: str
    profile: str
    risk_domain: str
    check_kind: str
    severity: str
    required_evidence: list[str]
    source_rule: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.product_acceptance_item.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.item_id, "item_id")
        _require_non_empty_str(self.requirement, "requirement")
        _require_enum(self.profile, "profile", DELIVERY_PROFILES)
        _require_enum(self.risk_domain, "risk_domain", RISK_DOMAINS)
        _require_enum(self.check_kind, "check_kind", PRODUCT_ACCEPTANCE_CHECK_KINDS)
        _require_enum(self.severity, "severity", PRODUCT_FINDING_SEVERITIES)
        _require_str_list(self.required_evidence, "required_evidence")
        _require_non_empty_str(self.source_rule, "source_rule")
        _require_safe_json_mapping(self.metadata, "metadata")


@dataclass
class ProductAcceptanceMatrix(SchemaModel):
    job_id: str
    items: list[ProductAcceptanceItem]
    delivery_profile_ref: str = DELIVERY_PROFILE_CONTRACT_REF
    risk_profile_ref: str = RISK_PROFILE_REF
    matrix_version: str = "runtime_helper_mvp.v1"
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.product_acceptance_matrix.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("ProductAcceptanceMatrix payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        missing = [name for name in ("job_id", "items") if name not in payload]
        if missing:
            raise SchemaValidationError(f"ProductAcceptanceMatrix missing required field(s): {', '.join(missing)}")
        if not isinstance(payload["items"], list):
            raise SchemaValidationError("items must be a list")
        instance = cls(
            job_id=payload["job_id"],
            items=[ProductAcceptanceItem.from_dict(item) for item in payload["items"]],
            delivery_profile_ref=payload.get("delivery_profile_ref", DELIVERY_PROFILE_CONTRACT_REF),
            risk_profile_ref=payload.get("risk_profile_ref", RISK_PROFILE_REF),
            matrix_version=payload.get("matrix_version", "runtime_helper_mvp.v1"),
            created_at=payload.get("created_at", utc_now()),
            schema_version=payload.get("schema_version", "skillfoundry.product_acceptance_matrix.v1"),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        if not isinstance(self.items, list):
            raise SchemaValidationError("items must be a list")
        seen: set[str] = set()
        for index, item in enumerate(self.items):
            if not isinstance(item, ProductAcceptanceItem):
                raise SchemaValidationError(f"items[{index}] must be a ProductAcceptanceItem")
            item.validate()
            if item.item_id in seen:
                raise SchemaValidationError(f"duplicate product acceptance item_id: {item.item_id}")
            seen.add(item.item_id)
        _require_ref(self.delivery_profile_ref, "delivery_profile_ref")
        _require_ref(self.risk_profile_ref, "risk_profile_ref")
        _require_non_empty_str(self.matrix_version, "matrix_version")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass
class ProductContractCompilerReport(SchemaModel):
    job_id: str
    passed: bool
    profiles: list[str]
    risk_domains: list[str]
    generated_refs: list[str]
    source_refs: list[str]
    matrix_item_count: int
    warnings: list[str] = field(default_factory=list)
    compiler_version: str = PRODUCT_CONTRACT_COMPILER_VERSION
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.product_contract_compiler_report.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_bool(self.passed, "passed")
        _require_unique_str_list(self.profiles, "profiles", allowed=DELIVERY_PROFILES)
        _require_unique_str_list(self.risk_domains, "risk_domains", allowed=RISK_DOMAINS)
        _require_ref_list(self.generated_refs, "generated_refs")
        _require_ref_list(self.source_refs, "source_refs")
        _require_non_negative_int(self.matrix_item_count, "matrix_item_count")
        _require_str_list(self.warnings, "warnings")
        _require_non_empty_str(self.compiler_version, "compiler_version")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass
class ProductGradeFinding(SchemaModel):
    finding_id: str
    severity: str
    title: str
    message: str
    affected_profiles: list[str]
    affected_risk_domains: list[str]
    required_fix: str
    required_tests: list[str]
    evidence_refs: list[str]
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.product_grade_finding.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.finding_id, "finding_id")
        _require_enum(self.severity, "severity", PRODUCT_FINDING_SEVERITIES)
        _require_non_empty_str(self.title, "title")
        _require_non_empty_str(self.message, "message")
        _require_unique_str_list(self.affected_profiles, "affected_profiles", allowed=DELIVERY_PROFILES)
        _require_unique_str_list(self.affected_risk_domains, "affected_risk_domains", allowed=RISK_DOMAINS)
        _require_non_empty_str(self.required_fix, "required_fix")
        _require_str_list(self.required_tests, "required_tests")
        _require_ref_list(self.evidence_refs, "evidence_refs")
        _require_safe_json_mapping(self.metadata, "metadata")


@dataclass
class ProductGradeReport(SchemaModel):
    job_id: str
    product_grade: bool
    package_hash: str
    matrix_ref: str
    findings: list[ProductGradeFinding]
    checked_item_ids: list[str]
    evidence_refs: list[str]
    gate_version: str = PRODUCT_GRADE_GATE_VERSION
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.product_grade_report.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("ProductGradeReport payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        missing = [
            name
            for name in ("job_id", "product_grade", "package_hash", "matrix_ref", "findings", "checked_item_ids", "evidence_refs")
            if name not in payload
        ]
        if missing:
            raise SchemaValidationError(f"ProductGradeReport missing required field(s): {', '.join(missing)}")
        if not isinstance(payload["findings"], list):
            raise SchemaValidationError("findings must be a list")
        instance = cls(
            job_id=payload["job_id"],
            product_grade=payload["product_grade"],
            package_hash=payload["package_hash"],
            matrix_ref=payload["matrix_ref"],
            findings=[ProductGradeFinding.from_dict(item) for item in payload["findings"]],
            checked_item_ids=payload["checked_item_ids"],
            evidence_refs=payload["evidence_refs"],
            gate_version=payload.get("gate_version", PRODUCT_GRADE_GATE_VERSION),
            created_at=payload.get("created_at", utc_now()),
            schema_version=payload.get("schema_version", "skillfoundry.product_grade_report.v1"),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_bool(self.product_grade, "product_grade")
        _require_sha256(self.package_hash, "package_hash")
        _require_ref(self.matrix_ref, "matrix_ref")
        if not isinstance(self.findings, list):
            raise SchemaValidationError("findings must be a list")
        seen: set[str] = set()
        for index, finding in enumerate(self.findings):
            if not isinstance(finding, ProductGradeFinding):
                raise SchemaValidationError(f"findings[{index}] must be a ProductGradeFinding")
            finding.validate()
            if finding.finding_id in seen:
                raise SchemaValidationError(f"duplicate finding_id: {finding.finding_id}")
            seen.add(finding.finding_id)
        _require_str_list(self.checked_item_ids, "checked_item_ids")
        _require_ref_list(self.evidence_refs, "evidence_refs")
        _require_non_empty_str(self.gate_version, "gate_version")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass
class ProductReviewerReport(SchemaModel):
    job_id: str
    reviewer_id: str
    findings: list[ProductGradeFinding]
    summary_score: int = 0
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.product_reviewer_report.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("ProductReviewerReport payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        missing = [name for name in ("job_id", "reviewer_id", "findings") if name not in payload]
        if missing:
            raise SchemaValidationError(f"ProductReviewerReport missing required field(s): {', '.join(missing)}")
        if not isinstance(payload["findings"], list):
            raise SchemaValidationError("findings must be a list")
        instance = cls(
            job_id=payload["job_id"],
            reviewer_id=payload["reviewer_id"],
            findings=[ProductGradeFinding.from_dict(item) for item in payload["findings"]],
            summary_score=payload.get("summary_score", 0),
            evidence_refs=payload.get("evidence_refs", []),
            created_at=payload.get("created_at", utc_now()),
            schema_version=payload.get("schema_version", "skillfoundry.product_reviewer_report.v1"),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_non_empty_str(self.reviewer_id, "reviewer_id")
        _require_score(self.summary_score, "summary_score")
        if not isinstance(self.findings, list):
            raise SchemaValidationError("findings must be a list")
        seen: set[str] = set()
        for index, finding in enumerate(self.findings):
            if not isinstance(finding, ProductGradeFinding):
                raise SchemaValidationError(f"findings[{index}] must be a ProductGradeFinding")
            finding.validate()
            if finding.finding_id in seen:
                raise SchemaValidationError(f"duplicate finding_id: {finding.finding_id}")
            seen.add(finding.finding_id)
        _require_ref_list(self.evidence_refs, "evidence_refs")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass
class ProductRepairItem(SchemaModel):
    finding_id: str
    severity: str
    title: str
    affected_profiles: list[str]
    affected_risk_domains: list[str]
    required_fix: str
    required_tests: list[str]
    evidence_refs: list[str]
    source_kind: str
    source_ref: str
    source_finding_id: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.product_repair_item.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.finding_id, "finding_id")
        _require_enum(self.severity, "severity", PRODUCT_FINDING_SEVERITIES)
        _require_non_empty_str(self.title, "title")
        _require_unique_str_list(self.affected_profiles, "affected_profiles", allowed=DELIVERY_PROFILES)
        _require_unique_str_list(self.affected_risk_domains, "affected_risk_domains", allowed=RISK_DOMAINS)
        _require_non_empty_str(self.required_fix, "required_fix")
        _require_str_list(self.required_tests, "required_tests")
        _require_ref_list(self.evidence_refs, "evidence_refs")
        _require_enum(self.source_kind, "source_kind", PRODUCT_REPAIR_SOURCE_KINDS)
        _require_ref(self.source_ref, "source_ref")
        _require_non_empty_str(self.source_finding_id, "source_finding_id")
        _require_safe_json_mapping(self.metadata, "metadata")


@dataclass
class ProductRepairPacket(SchemaModel):
    job_id: str
    repair_required: bool
    source_report_ref: str
    findings: list[ProductGradeFinding]
    repair_instructions: list[str]
    required_tests: list[str]
    repair_items: list[ProductRepairItem] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    trust_boundaries: dict[str, JsonValue] = field(
        default_factory=lambda: {
            "worker_self_report_is_not_acceptance": True,
            "raw_prompt_included": False,
            "raw_transcript_included": False,
            "raw_reviewer_text_included": False,
        }
    )
    planner_version: str = PRODUCT_REPAIR_PLANNER_VERSION
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.product_repair_packet.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("ProductRepairPacket payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        missing = [
            name
            for name in ("job_id", "repair_required", "source_report_ref", "findings", "repair_instructions", "required_tests")
            if name not in payload
        ]
        if missing:
            raise SchemaValidationError(f"ProductRepairPacket missing required field(s): {', '.join(missing)}")
        if not isinstance(payload["findings"], list):
            raise SchemaValidationError("findings must be a list")
        instance = cls(
            job_id=payload["job_id"],
            repair_required=payload["repair_required"],
            source_report_ref=payload["source_report_ref"],
            findings=[ProductGradeFinding.from_dict(item) for item in payload["findings"]],
            repair_instructions=payload["repair_instructions"],
            required_tests=payload["required_tests"],
            repair_items=[
                ProductRepairItem.from_dict(item)
                for item in payload.get("repair_items", [])
            ],
            source_refs=payload.get("source_refs", [payload["source_report_ref"]]),
            trust_boundaries=payload.get(
                "trust_boundaries",
                {
                    "worker_self_report_is_not_acceptance": True,
                    "raw_prompt_included": False,
                    "raw_transcript_included": False,
                    "raw_reviewer_text_included": False,
                },
            ),
            planner_version=payload.get("planner_version", PRODUCT_REPAIR_PLANNER_VERSION),
            created_at=payload.get("created_at", utc_now()),
            schema_version=payload.get("schema_version", "skillfoundry.product_repair_packet.v1"),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_bool(self.repair_required, "repair_required")
        _require_ref(self.source_report_ref, "source_report_ref")
        if not isinstance(self.findings, list):
            raise SchemaValidationError("findings must be a list")
        for index, finding in enumerate(self.findings):
            if not isinstance(finding, ProductGradeFinding):
                raise SchemaValidationError(f"findings[{index}] must be a ProductGradeFinding")
            finding.validate()
        _require_str_list(self.repair_instructions, "repair_instructions")
        _require_str_list(self.required_tests, "required_tests")
        if not isinstance(self.repair_items, list):
            raise SchemaValidationError("repair_items must be a list")
        seen: set[str] = set()
        for index, item in enumerate(self.repair_items):
            if not isinstance(item, ProductRepairItem):
                raise SchemaValidationError(f"repair_items[{index}] must be a ProductRepairItem")
            item.validate()
            if item.finding_id in seen:
                raise SchemaValidationError(f"duplicate repair finding_id: {item.finding_id}")
            seen.add(item.finding_id)
        _require_ref_list(self.source_refs, "source_refs")
        _require_safe_json_mapping(self.trust_boundaries, "trust_boundaries")
        _require_non_empty_str(self.planner_version, "planner_version")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass(frozen=True)
class ProductContractArtifacts:
    delivery_profile: DeliveryProfileContract
    risk_profile: RiskProfile
    acceptance_matrix: ProductAcceptanceMatrix
    compiler_report: ProductContractCompilerReport
