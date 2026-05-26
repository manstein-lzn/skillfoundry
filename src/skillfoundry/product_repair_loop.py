"""Deterministic product repair planning for SkillFoundry product gates."""

from __future__ import annotations

from dataclasses import dataclass

from .product_contract import (
    PRODUCT_GRADE_FAILING_SEVERITIES,
    PRODUCT_GRADE_REPORT_REF,
    PRODUCT_REPAIR_PACKET_REF,
    PRODUCT_REPAIR_PLANNER_VERSION,
    PRODUCT_REVIEWER_REPORT_REF,
    ProductGradeFinding,
    ProductGradeReport,
    ProductRepairItem,
    ProductRepairPacket,
    ProductReviewerReport,
)
from .schema import SchemaValidationError
from .workspace import JobWorkspace


PRODUCT_REPAIR_TRUST_BOUNDARIES = {
    "worker_self_report_is_not_acceptance": True,
    "raw_prompt_included": False,
    "raw_transcript_included": False,
    "raw_reviewer_text_included": False,
}


@dataclass(frozen=True)
class _SourcedFinding:
    finding: ProductGradeFinding
    source_kind: str
    source_ref: str


class ProductRepairPlanner:
    """Compile product gate and reviewer findings into a refs-only repair packet."""

    def plan(
        self,
        workspace: JobWorkspace,
        *,
        product_grade_report: ProductGradeReport | None = None,
        reviewer_report: ProductReviewerReport | None = None,
    ) -> ProductRepairPacket:
        workspace.resolve_path("qa").mkdir(parents=True, exist_ok=True)
        sourced_findings: list[_SourcedFinding] = []
        source_refs: list[str] = []
        source_report_ref = PRODUCT_GRADE_REPORT_REF

        grade_report = product_grade_report or _read_optional_product_grade_report(workspace)
        if grade_report is None:
            sourced_findings.append(
                _SourcedFinding(
                    finding=_missing_product_grade_report_finding(),
                    source_kind="product_gate",
                    source_ref=PRODUCT_GRADE_REPORT_REF,
                )
            )
        else:
            _require_job_match(workspace, grade_report.job_id, PRODUCT_GRADE_REPORT_REF)
            source_refs.append(PRODUCT_GRADE_REPORT_REF)
            sourced_findings.extend(
                _SourcedFinding(finding=finding, source_kind="product_gate", source_ref=PRODUCT_GRADE_REPORT_REF)
                for finding in grade_report.findings
            )

        reviewer = reviewer_report or _read_optional_reviewer_report(workspace)
        if reviewer is not None:
            _require_job_match(workspace, reviewer.job_id, PRODUCT_REVIEWER_REPORT_REF)
            source_refs.append(PRODUCT_REVIEWER_REPORT_REF)
            if grade_report is None:
                source_report_ref = PRODUCT_REVIEWER_REPORT_REF
            sourced_findings.extend(
                _SourcedFinding(finding=finding, source_kind="reviewer_report", source_ref=PRODUCT_REVIEWER_REPORT_REF)
                for finding in reviewer.findings
            )

        repair_items = _compile_repair_items(sourced_findings)
        actionable_findings = [item.finding for item in sourced_findings if _is_actionable(item.finding)]
        packet_source_refs = _dedupe_strings(source_refs + [item.source_ref for item in repair_items])
        repair_packet = ProductRepairPacket(
            job_id=workspace.job_id,
            repair_required=bool(repair_items),
            source_report_ref=source_report_ref,
            findings=actionable_findings,
            repair_instructions=[
                f"{item.finding_id}: {item.required_fix}"
                for item in repair_items
            ],
            required_tests=_dedupe_strings(
                [test for item in repair_items for test in item.required_tests]
            ),
            repair_items=repair_items,
            source_refs=packet_source_refs or [source_report_ref],
            trust_boundaries=dict(PRODUCT_REPAIR_TRUST_BOUNDARIES),
            planner_version=PRODUCT_REPAIR_PLANNER_VERSION,
        )
        repair_packet.write_json_file(workspace.resolve_path(PRODUCT_REPAIR_PACKET_REF))
        return repair_packet


def plan_product_repair(
    workspace: JobWorkspace,
    *,
    product_grade_report: ProductGradeReport | None = None,
    reviewer_report: ProductReviewerReport | None = None,
) -> ProductRepairPacket:
    return ProductRepairPlanner().plan(
        workspace,
        product_grade_report=product_grade_report,
        reviewer_report=reviewer_report,
    )


def _read_optional_product_grade_report(workspace: JobWorkspace) -> ProductGradeReport | None:
    path = workspace.resolve_path(PRODUCT_GRADE_REPORT_REF)
    if not path.exists():
        return None
    return ProductGradeReport.read_json_file(path)


def _read_optional_reviewer_report(workspace: JobWorkspace) -> ProductReviewerReport | None:
    path = workspace.resolve_path(PRODUCT_REVIEWER_REPORT_REF)
    if not path.exists():
        return None
    return ProductReviewerReport.read_json_file(path)


def _require_job_match(workspace: JobWorkspace, actual_job_id: str, ref: str) -> None:
    if actual_job_id != workspace.job_id:
        raise SchemaValidationError(f"{ref}.job_id: expected {workspace.job_id}, got {actual_job_id}")


def _missing_product_grade_report_finding() -> ProductGradeFinding:
    return ProductGradeFinding(
        finding_id="P0-product-grade-report-missing",
        severity="blocking",
        title="Product grade report is missing",
        message="Product repair planning requires ProductGradeGate evidence before repair can be trusted.",
        affected_profiles=["codex_skill"],
        affected_risk_domains=["distribution_package"],
        required_fix="Run ProductGradeGate before invoking the product repair planner.",
        required_tests=["ProductGradeGate emits qa/product_grade_report.json"],
        evidence_refs=[],
    )


def _compile_repair_items(sourced_findings: list[_SourcedFinding]) -> list[ProductRepairItem]:
    items: list[ProductRepairItem] = []
    seen: set[str] = set()
    for sourced in sourced_findings:
        if not _is_actionable(sourced.finding):
            continue
        item = _repair_item_from_finding(sourced)
        if item.finding_id in seen:
            continue
        seen.add(item.finding_id)
        items.append(item)
    return items


def _repair_item_from_finding(sourced: _SourcedFinding) -> ProductRepairItem:
    finding = sourced.finding
    namespaced_finding_id = f"{sourced.source_kind}:{finding.finding_id}"
    metadata = dict(finding.metadata)
    metadata["source_schema_version"] = finding.schema_version
    return ProductRepairItem(
        finding_id=namespaced_finding_id,
        severity=finding.severity,
        title=finding.title,
        affected_profiles=list(finding.affected_profiles),
        affected_risk_domains=list(finding.affected_risk_domains),
        required_fix=finding.required_fix,
        required_tests=list(finding.required_tests),
        evidence_refs=list(finding.evidence_refs),
        source_kind=sourced.source_kind,
        source_ref=sourced.source_ref,
        source_finding_id=finding.finding_id,
        metadata=metadata,
    )


def _is_actionable(finding: ProductGradeFinding) -> bool:
    return finding.severity in PRODUCT_GRADE_FAILING_SEVERITIES


def _dedupe_strings(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result
