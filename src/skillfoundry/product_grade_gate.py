"""Product-grade gate for generated SkillFoundry candidates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bundle_verifier import hash_package_tree
from .product_contract import (
    PRODUCT_ACCEPTANCE_MATRIX_REF,
    PRODUCT_GRADE_FAILING_SEVERITIES,
    PRODUCT_GRADE_GATE_VERSION,
    PRODUCT_GRADE_REPORT_REF,
    ProductAcceptanceMatrix,
    ProductGradeFinding,
    ProductGradeReport,
)
from .product_repair_loop import ProductRepairPlanner
from .product_runtime_checks import PRODUCT_RUNTIME_CHECK_RESULT_REF, ProductRuntimeCheckRunner
from .security import validate_relative_path
from .workspace import JobWorkspace


SCAN_DIRS = ("package/tests", "package/src", "package/runtime", "package/scripts", "package/fixtures", "package/examples")
SOURCE_DIRS = ("package/src", "package/runtime", "package/scripts")
SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", "target", "dist", "build", ".pytest_cache", ".mypy_cache"}
TEXT_SUFFIXES = {
    ".rs",
    ".py",
    ".js",
    ".ts",
    ".mjs",
    ".cjs",
    ".sh",
    ".md",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
}
MAX_SCAN_BYTES = 512 * 1024

DUPLICATE_PATH_MARKERS = (
    "same-plan duplicate path",
    "same plan duplicate path",
    "intra-plan duplicate path",
    "duplicate target path",
    "duplicate target_path",
    "duplicate_path",
    "duplicate-path",
    "repeated target path",
    "target path is duplicated",
)
DUPLICATE_TITLE_MARKERS = (
    "same-plan duplicate title",
    "same plan duplicate title",
    "intra-plan duplicate title",
    "duplicate title",
    "duplicate_title",
    "duplicate-title",
    "repeated title",
    "title is duplicated",
)
TYPED_STRUCTURED_PARSER_MARKERS = (
    "serde_json",
    "deserialize",
    "#[derive(deserialize",
    "pydantic",
    "basemodel",
    "jsonschema",
    "json_schema",
    "zod.",
    "z.object",
    "ajv",
    "json.parse",
    "json.loads",
)


@dataclass(frozen=True)
class ScannedFile:
    ref: str
    text: str


class ProductGradeGate:
    """Evaluate a generated package against the compiled product matrix."""

    def evaluate(self, workspace: JobWorkspace, matrix: ProductAcceptanceMatrix | None = None) -> ProductGradeReport:
        workspace.resolve_path("qa").mkdir(parents=True, exist_ok=True)
        findings: list[ProductGradeFinding] = []
        checked_item_ids: list[str] = []
        evidence_refs: list[str] = []

        try:
            matrix = matrix or ProductAcceptanceMatrix.read_json_file(
                workspace.resolve_path(PRODUCT_ACCEPTANCE_MATRIX_REF, must_exist=True)
            )
            evidence_refs.append(PRODUCT_ACCEPTANCE_MATRIX_REF)
        except Exception as exc:
            findings.append(
                ProductGradeFinding(
                    finding_id="P0-product-acceptance-matrix-missing",
                    severity="blocking",
                    title="Product acceptance matrix is missing",
                    message=f"ProductGradeGate requires {PRODUCT_ACCEPTANCE_MATRIX_REF}: {exc}",
                    affected_profiles=["codex_skill"],
                    affected_risk_domains=["distribution_package"],
                    required_fix="Run ProductContractCompiler before product-grade promotion.",
                    required_tests=["product contract compiler emits product_acceptance_matrix.json"],
                    evidence_refs=[],
                )
            )
            matrix = None

        scan_files = _scan_package_files(workspace)
        runtime_result_passed = False
        if matrix is not None:
            profiles = {item.profile for item in matrix.items}
            item_ids = {item.item_id for item in matrix.items}
            runtime_item_ids = sorted(item_id for item_id in item_ids if item_id.startswith("PG-RUNTIME-"))
            if runtime_item_ids:
                runtime_result = ProductRuntimeCheckRunner().run(workspace, required_item_ids=runtime_item_ids)
                checked_item_ids.extend(runtime_result.checked_item_ids)
                evidence_refs.append(PRODUCT_RUNTIME_CHECK_RESULT_REF)
                runtime_result_passed = runtime_result.passed
                if not runtime_result.passed:
                    findings.append(_runtime_matrix_finding(runtime_result))
            if {
                "PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH",
                "PG-RUNTIME-SAME-PLAN-DUPLICATE-TITLE",
            } & item_ids and not runtime_result_passed:
                checked_item_ids.extend(
                    item_id
                    for item_id in (
                        "PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH",
                        "PG-RUNTIME-SAME-PLAN-DUPLICATE-TITLE",
                    )
                    if item_id in item_ids
                )
                duplicate_finding = _evaluate_same_plan_duplicate_evidence(scan_files)
                if duplicate_finding is not None:
                    findings.append(duplicate_finding)
            if "structured_input_skill" in profiles and "PG-STRUCTURED-TYPED-PARSER" in item_ids:
                checked_item_ids.append("PG-STRUCTURED-TYPED-PARSER")
                parser_finding = _evaluate_typed_parser_evidence(scan_files)
                if parser_finding is not None:
                    findings.append(parser_finding)

        package_hash = hash_package_tree(workspace)
        product_grade = not any(finding.severity in PRODUCT_GRADE_FAILING_SEVERITIES for finding in findings)
        report = ProductGradeReport(
            job_id=workspace.job_id,
            product_grade=product_grade,
            package_hash=package_hash,
            matrix_ref=PRODUCT_ACCEPTANCE_MATRIX_REF,
            findings=findings,
            checked_item_ids=checked_item_ids,
            evidence_refs=_dedupe_refs(evidence_refs + [finding_ref for finding in findings for finding_ref in finding.evidence_refs]),
            gate_version=PRODUCT_GRADE_GATE_VERSION,
        )
        report.write_json_file(workspace.resolve_path(PRODUCT_GRADE_REPORT_REF))
        ProductRepairPlanner().plan(workspace, product_grade_report=report)
        return report


def run_product_grade_gate(workspace: JobWorkspace) -> ProductGradeReport:
    return ProductGradeGate().evaluate(workspace)


def _evaluate_same_plan_duplicate_evidence(scan_files: list[ScannedFile]) -> ProductGradeFinding | None:
    duplicate_path_refs = _refs_matching_duplicate_path(scan_files)
    duplicate_title_refs = _refs_matching_duplicate_title(scan_files)
    missing: list[str] = []
    if not duplicate_path_refs:
        missing.append("duplicate target path fixture or source behavior evidence")
    if not duplicate_title_refs:
        missing.append("duplicate title fixture or source behavior evidence")
    if not missing:
        return None
    return ProductGradeFinding(
        finding_id="P0-runtime-same-plan-conflict-coverage-missing",
        severity="blocking",
        title="Same-plan duplicate conflict coverage is missing",
        message="Runtime local-file safety requires same-plan duplicate path and title conflict handling before product-grade promotion.",
        affected_profiles=["runtime_helper_skill", "local_file_safety_skill"],
        affected_risk_domains=["filesystem_write"],
        required_fix="Detect duplicate target paths and duplicate titles within one write plan, return explicit conflicts, and avoid writing files.",
        required_tests=[
            "duplicate path fixture",
            "duplicate title fixture",
            "CLI conflict exit code",
            "no write on validation-only command",
        ],
        evidence_refs=_dedupe_refs(duplicate_path_refs + duplicate_title_refs),
        metadata={"missing_evidence": missing},
    )


def _runtime_matrix_finding(runtime_result) -> ProductGradeFinding:
    missing = list(runtime_result.missing_item_ids)
    failed = [
        check.check_id
        for check in runtime_result.checks
        if not check.passed
    ]
    return ProductGradeFinding(
        finding_id="P0-runtime-matrix-checks-failed",
        severity="blocking",
        title="Runtime product matrix checks failed",
        message="Runtime helper skills must declare and pass executable product matrix checks before product-grade promotion.",
        affected_profiles=["runtime_helper_skill", "local_file_safety_skill"],
        affected_risk_domains=["filesystem_write", "runtime_execution"],
        required_fix="Add or repair package/skillfoundry.runtime_checks.json so every required PG-RUNTIME item is covered by a passing command.",
        required_tests=missing or failed or ["runtime matrix command coverage"],
        evidence_refs=[PRODUCT_RUNTIME_CHECK_RESULT_REF],
        metadata={
            "missing_item_ids": missing,
            "failed_check_ids": failed,
            "failure_count": len(runtime_result.failures),
        },
    )


def _evaluate_typed_parser_evidence(scan_files: list[ScannedFile]) -> ProductGradeFinding | None:
    parser_refs = _refs_matching_typed_parser(scan_files)
    if parser_refs:
        return None
    return ProductGradeFinding(
        finding_id="P1-structured-parser-not-typed",
        severity="major",
        title="Structured input parser evidence is missing",
        message="Structured JSON inputs require a typed or equivalent structured parser with schema validation evidence.",
        affected_profiles=["structured_input_skill"],
        affected_risk_domains=["structured_json_input", "structured_data_validation"],
        required_fix="Use a typed/structured parser or equivalent schema validator and add malformed JSON, required-field, duplicate-ID, and referenced-ID tests.",
        required_tests=[
            "malformed JSON fixture",
            "required field fixture",
            "duplicate ID fixture",
            "unknown referenced ID fixture",
        ],
        evidence_refs=[],
    )


def _refs_matching_duplicate_path(scan_files: list[ScannedFile]) -> list[str]:
    refs: list[str] = []
    for scanned in scan_files:
        haystack = f"{scanned.ref}\n{scanned.text}".lower()
        if any(marker in haystack for marker in DUPLICATE_PATH_MARKERS):
            refs.append(scanned.ref)
            continue
        if "duplicate" in haystack and ("target_path" in haystack or "target path" in haystack) and "plan" in haystack:
            refs.append(scanned.ref)
    return _dedupe_refs(refs)


def _refs_matching_duplicate_title(scan_files: list[ScannedFile]) -> list[str]:
    refs: list[str] = []
    for scanned in scan_files:
        haystack = f"{scanned.ref}\n{scanned.text}".lower()
        if any(marker in haystack for marker in DUPLICATE_TITLE_MARKERS):
            refs.append(scanned.ref)
            continue
        if "duplicate" in haystack and "title" in haystack and "plan" in haystack:
            refs.append(scanned.ref)
    return _dedupe_refs(refs)


def _refs_matching_typed_parser(scan_files: list[ScannedFile]) -> list[str]:
    refs: list[str] = []
    for scanned in scan_files:
        if not any(scanned.ref.startswith(prefix + "/") or scanned.ref == prefix for prefix in SOURCE_DIRS):
            continue
        haystack = scanned.text.lower()
        if any(marker in haystack for marker in TYPED_STRUCTURED_PARSER_MARKERS):
            refs.append(scanned.ref)
    return _dedupe_refs(refs)


def _scan_package_files(workspace: JobWorkspace) -> list[ScannedFile]:
    result: list[ScannedFile] = []
    for scan_dir in SCAN_DIRS:
        root = _optional_workspace_path(workspace, scan_dir)
        if not root.exists():
            continue
        if root.is_file():
            files = [root]
        else:
            files = _iter_scan_files(root)
        for path in files:
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_SCAN_BYTES:
                    continue
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            ref = path.relative_to(workspace.root).as_posix()
            result.append(ScannedFile(ref=ref, text=text))
    return result


def _iter_scan_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


def _optional_workspace_path(workspace: JobWorkspace, ref: str) -> Path:
    safe = validate_relative_path(ref)
    return workspace.root.joinpath(*safe.parts)


def _dedupe_refs(refs: list[str]) -> list[str]:
    result: list[str] = []
    for ref in refs:
        if ref and ref not in result:
            result.append(ref)
    return result
