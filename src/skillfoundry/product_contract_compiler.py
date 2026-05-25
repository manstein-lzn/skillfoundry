"""Deterministic compiler from user-facing spec artifacts to product contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .product_contract import (
    DELIVERY_PROFILE_CONTRACT_REF,
    PRODUCT_ACCEPTANCE_MATRIX_REF,
    PRODUCT_CONTRACT_COMPILER_REPORT_REF,
    PRODUCT_CONTRACT_COMPILER_VERSION,
    PRODUCT_CONTRACT_DIR,
    RISK_PROFILE_REF,
    DeliveryProfileContract,
    ProductAcceptanceItem,
    ProductAcceptanceMatrix,
    ProductContractArtifacts,
    ProductContractCompilerReport,
    RiskProfile,
)
from .security import validate_relative_path
from .workspace import JobWorkspace


SOURCE_REFS = (
    "skill_spec.yaml",
    "acceptance_criteria.yaml",
    "frontdesk/core_need_brief.json",
    "frontdesk/solution_plan.json",
    "frontdesk/draft_skill_spec.yaml",
    "frontdesk/acceptance_criteria.yaml",
)

PROFILE_ORDER = (
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
)

RISK_ORDER = (
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
)

SIGNAL_KEYWORDS = {
    "runtime_helper": (
        "runtime",
        "cli",
        "command",
        "cargo",
        "rust",
        "python",
        "node",
        "binary",
        "compiled",
        "script",
        "api",
        "底层代码",
        "命令行",
        "脚本",
        "工具",
        "运行时",
    ),
    "local_file_safety": (
        "write",
        "writes",
        "wiki root",
        "target path",
        "target_path",
        "local file",
        "markdown",
        "overwrite",
        "no overwrite",
        "conflict",
        "proposal",
        "filesystem",
        "file system",
        "写入",
        "本地文件",
        "覆盖",
        "冲突",
        "提案",
        "路径",
    ),
    "structured_input": (
        "json",
        "schema",
        "manifest",
        "evidence",
        "compact note",
        "compact evidence",
        "write plan",
        "fixture",
        "structured input",
        "结构化",
        "清单",
        "证据",
        "数据格式",
    ),
    "privacy_boundary": (
        "privacy",
        "sensitive",
        "authorized",
        "authorization",
        "raw chat",
        "conversation",
        "do not scan",
        "whole computer",
        "whole-disk",
        "permission",
        "隐私",
        "敏感",
        "授权",
        "聊天记录",
        "不要扫描",
        "全盘",
    ),
    "reference_heavy": (
        "pdf",
        "official doc",
        "documentation",
        "manual",
        "specification",
        "datasheet",
        "论文",
        "官方文档",
        "参考资料",
        "手册",
        "文档",
    ),
    "data_conversion": (
        "parse",
        "convert",
        "extract",
        "transform",
        "ocr",
        "chunk",
        "index",
        "retrieval",
        "解析",
        "转换",
        "提取",
        "数据库",
        "索引",
        "检索",
    ),
    "domain_knowledge": (
        "eda",
        "semiconductor",
        "layout",
        "domain",
        "factual",
        "citation",
        "source mapping",
        "半导体",
        "版图",
        "领域",
        "事实",
        "引用",
    ),
    "mcp": ("mcp", "model context protocol"),
    "service": ("daemon", "server", "long-running service", "background service", "常驻服务"),
    "network": ("network", "http", "api", "sync", "webhook", "联网", "网络"),
}

NEGATION_SENSITIVE_SIGNALS = frozenset({"reference_heavy", "data_conversion", "domain_knowledge", "mcp", "service"})
NEGATION_MARKERS = (
    "do not",
    "does not",
    "must not",
    "should not",
    "never",
    "without",
    "no ",
    "不要",
    "禁止",
    "不得",
)


class ProductContractCompiler:
    """Compile frozen FrontDesk/spec artifacts into product-grade contracts."""

    def compile(self, workspace: JobWorkspace) -> ProductContractArtifacts:
        source_refs, combined_text = _collect_source_text(workspace)
        signals = _infer_signals(combined_text)
        profiles = _infer_profiles(signals)
        risks = _infer_risk_domains(profiles, signals)
        items = _build_acceptance_items(workspace.job_id, profiles, risks)

        delivery_profile = DeliveryProfileContract(
            job_id=workspace.job_id,
            profiles=profiles,
            source_refs=source_refs,
            profile_reasons={profile: _profile_reason(profile, signals) for profile in profiles},
        )
        risk_profile = RiskProfile(
            job_id=workspace.job_id,
            risk_domains=risks,
            source_refs=source_refs,
            risk_reasons={risk: _risk_reason(risk, profiles, signals) for risk in risks},
        )
        matrix = ProductAcceptanceMatrix(job_id=workspace.job_id, items=items)
        report = ProductContractCompilerReport(
            job_id=workspace.job_id,
            passed=True,
            profiles=profiles,
            risk_domains=risks,
            generated_refs=[
                DELIVERY_PROFILE_CONTRACT_REF,
                RISK_PROFILE_REF,
                PRODUCT_ACCEPTANCE_MATRIX_REF,
                PRODUCT_CONTRACT_COMPILER_REPORT_REF,
            ],
            source_refs=source_refs,
            matrix_item_count=len(items),
            warnings=[] if source_refs else ["no recognized source spec refs found"],
            compiler_version=PRODUCT_CONTRACT_COMPILER_VERSION,
        )

        contract_dir = workspace.resolve_path(PRODUCT_CONTRACT_DIR)
        contract_dir.mkdir(parents=True, exist_ok=True)
        delivery_profile.write_json_file(workspace.resolve_path(DELIVERY_PROFILE_CONTRACT_REF))
        risk_profile.write_json_file(workspace.resolve_path(RISK_PROFILE_REF))
        matrix.write_json_file(workspace.resolve_path(PRODUCT_ACCEPTANCE_MATRIX_REF))
        report.write_json_file(workspace.resolve_path(PRODUCT_CONTRACT_COMPILER_REPORT_REF))
        return ProductContractArtifacts(
            delivery_profile=delivery_profile,
            risk_profile=risk_profile,
            acceptance_matrix=matrix,
            compiler_report=report,
        )


def compile_product_contract(workspace: JobWorkspace) -> ProductContractArtifacts:
    return ProductContractCompiler().compile(workspace)


def _collect_source_text(workspace: JobWorkspace) -> tuple[list[str], str]:
    refs: list[str] = []
    parts: list[str] = []
    for ref in SOURCE_REFS:
        path = _optional_workspace_path(workspace, ref)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        refs.append(ref)
        parts.extend(_extract_structured_strings(path, text))
    return refs, "\n".join(parts).lower()


def _optional_workspace_path(workspace: JobWorkspace, ref: str) -> Path:
    safe = validate_relative_path(ref)
    return workspace.root.joinpath(*safe.parts)


def _extract_structured_strings(path: Path, text: str) -> list[str]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            payload = json.loads(text)
        elif suffix in {".yaml", ".yml"}:
            payload = yaml.safe_load(text)
        else:
            return [text]
    except Exception:
        return [text]
    return list(_iter_strings(payload))


def _iter_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_iter_strings(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(_iter_strings(item))
        return result
    return []


def _infer_signals(text: str) -> dict[str, bool]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: dict[str, bool] = {}
    for signal, keywords in SIGNAL_KEYWORDS.items():
        if signal in NEGATION_SENSITIVE_SIGNALS:
            result[signal] = any(
                keyword.lower() in line and not _line_has_negation(line)
                for keyword in keywords
                for line in lines
            )
        else:
            result[signal] = any(keyword.lower() in text for keyword in keywords)
    return result


def _line_has_negation(line: str) -> bool:
    return any(marker in line for marker in NEGATION_MARKERS)


def _infer_profiles(signals: dict[str, bool]) -> list[str]:
    selected: set[str] = {"codex_skill"}
    if signals["runtime_helper"]:
        selected.add("runtime_helper_skill")
    if signals["local_file_safety"]:
        selected.add("local_file_safety_skill")
    if signals["structured_input"]:
        selected.add("structured_input_skill")
    if signals["reference_heavy"]:
        selected.add("reference_heavy_skill")
    if signals["reference_heavy"] and (signals["data_conversion"] or signals["domain_knowledge"]):
        selected.add("knowledge_db_skill")
    if signals["data_conversion"]:
        selected.add("data_conversion_skill")
    if signals["mcp"]:
        selected.add("mcp_connector_skill")
    if signals["service"]:
        selected.add("service_bundle_skill")
    if signals["runtime_helper"] and any(signals[name] for name in ("data_conversion", "service", "mcp")):
        selected.add("toolchain_skill")
    if selected == {"codex_skill"}:
        selected.add("prompt_only_skill")
    return [profile for profile in PROFILE_ORDER if profile in selected]


def _infer_risk_domains(profiles: list[str], signals: dict[str, bool]) -> list[str]:
    selected: set[str] = {"distribution_package"}
    if "local_file_safety_skill" in profiles:
        selected.add("filesystem_write")
    if signals["privacy_boundary"]:
        selected.add("privacy_boundary")
        selected.add("privacy_sensitive_input")
    if "structured_input_skill" in profiles:
        selected.add("structured_json_input")
        selected.add("structured_data_validation")
    if "reference_heavy_skill" in profiles:
        selected.add("external_document_ingestion")
    if "knowledge_db_skill" in profiles or signals["domain_knowledge"]:
        selected.add("domain_knowledge_reliability")
    if signals["network"] or "mcp_connector_skill" in profiles:
        selected.add("network_boundary")
    if "runtime_helper_skill" in profiles or "toolchain_skill" in profiles:
        selected.add("runtime_execution")
    if "service_bundle_skill" in profiles:
        selected.add("long_running_service")
    return [risk for risk in RISK_ORDER if risk in selected]


def _profile_reason(profile: str, signals: dict[str, bool]) -> dict[str, JsonValue]:
    reason_signals = {
        "codex_skill": ["skillfoundry_delivery_target"],
        "prompt_only_skill": ["no_runtime_or_data_signals"],
        "runtime_helper_skill": ["runtime_helper"] if signals["runtime_helper"] else [],
        "local_file_safety_skill": ["local_file_safety"] if signals["local_file_safety"] else [],
        "structured_input_skill": ["structured_input"] if signals["structured_input"] else [],
        "reference_heavy_skill": ["reference_heavy"] if signals["reference_heavy"] else [],
        "knowledge_db_skill": [name for name in ("reference_heavy", "data_conversion", "domain_knowledge") if signals[name]],
        "data_conversion_skill": ["data_conversion"] if signals["data_conversion"] else [],
        "mcp_connector_skill": ["mcp"] if signals["mcp"] else [],
        "service_bundle_skill": ["service"] if signals["service"] else [],
        "toolchain_skill": [name for name in ("runtime_helper", "data_conversion", "service", "mcp") if signals[name]],
    }
    return {"signals": reason_signals.get(profile, [])}


def _risk_reason(risk: str, profiles: list[str], signals: dict[str, bool]) -> dict[str, JsonValue]:
    return {
        "profiles": [profile for profile in profiles if _profile_maps_to_risk(profile, risk)],
        "signals": [name for name, matched in signals.items() if matched and _signal_maps_to_risk(name, risk)],
    }


def _profile_maps_to_risk(profile: str, risk: str) -> bool:
    mapping = {
        "codex_skill": {"distribution_package"},
        "local_file_safety_skill": {"filesystem_write"},
        "structured_input_skill": {"structured_json_input", "structured_data_validation"},
        "reference_heavy_skill": {"external_document_ingestion"},
        "knowledge_db_skill": {"domain_knowledge_reliability"},
        "runtime_helper_skill": {"runtime_execution"},
        "toolchain_skill": {"runtime_execution"},
        "mcp_connector_skill": {"network_boundary"},
        "service_bundle_skill": {"long_running_service"},
    }
    return risk in mapping.get(profile, set())


def _signal_maps_to_risk(signal: str, risk: str) -> bool:
    mapping = {
        "local_file_safety": {"filesystem_write"},
        "structured_input": {"structured_json_input", "structured_data_validation"},
        "privacy_boundary": {"privacy_boundary", "privacy_sensitive_input"},
        "reference_heavy": {"external_document_ingestion"},
        "domain_knowledge": {"domain_knowledge_reliability"},
        "runtime_helper": {"runtime_execution"},
        "network": {"network_boundary"},
        "service": {"long_running_service"},
    }
    return risk in mapping.get(signal, set())


def _build_acceptance_items(job_id: str, profiles: list[str], risks: list[str]) -> list[ProductAcceptanceItem]:
    items: list[ProductAcceptanceItem] = []
    if "runtime_helper_skill" in profiles and "local_file_safety_skill" in profiles:
        items.extend(_runtime_local_file_items())
    if "structured_input_skill" in profiles:
        items.extend(_structured_input_items())
    if "codex_skill" in profiles:
        items.extend(_codex_skill_docs_items())
    if "reference_heavy_skill" in profiles or "data_conversion_skill" in profiles:
        items.extend(_reference_data_items(profiles))
    return [_with_job_metadata(item, job_id, profiles, risks) for item in items]


def _runtime_local_file_items() -> list[ProductAcceptanceItem]:
    requirements = [
        ("PG-RUNTIME-EXISTING-PATH-CONFLICT", "Detect conflicts with an existing target path.", "runtime_fixture_check"),
        ("PG-RUNTIME-EXISTING-TITLE-CONFLICT", "Detect conflicts with an existing wiki title.", "runtime_fixture_check"),
        ("PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH", "Detect duplicate target paths inside the same write plan.", "runtime_fixture_check"),
        ("PG-RUNTIME-SAME-PLAN-DUPLICATE-TITLE", "Detect duplicate titles inside the same write plan.", "runtime_fixture_check"),
        ("PG-RUNTIME-PATH-TRAVERSAL-REJECTED", "Reject parent-directory traversal in target paths.", "runtime_fixture_check"),
        ("PG-RUNTIME-ABSOLUTE-PATH-REJECTED", "Reject absolute target paths.", "runtime_fixture_check"),
        ("PG-RUNTIME-BACKSLASH-PATH-REJECTED", "Reject backslash target paths.", "runtime_fixture_check"),
        ("PG-RUNTIME-NON-MARKDOWN-TARGET-REJECTED", "Reject non-Markdown target paths.", "runtime_fixture_check"),
        ("PG-RUNTIME-SYMLINK-COMPONENT-REJECTED", "Reject target paths whose existing components contain symlinks.", "runtime_fixture_check"),
        ("PG-RUNTIME-NONEXISTENT-ROOT-HANDLED", "Handle nonexistent roots without broad filesystem scanning.", "runtime_command_check"),
        ("PG-RUNTIME-CONFLICT-PROPOSAL-OUTPUT", "Emit explicit conflict proposals instead of silently overwriting.", "runtime_command_check"),
        ("PG-RUNTIME-VALIDATION-ONLY-NO-WRITE", "Validation-only commands must not write candidate output.", "runtime_command_check"),
        ("PG-RUNTIME-CLI-OK-EXIT-CODE", "Document and test the successful CLI exit code.", "runtime_command_check"),
        ("PG-RUNTIME-CLI-INVALID-EXIT-CODE", "Document and test the invalid-input CLI exit code.", "runtime_command_check"),
        ("PG-RUNTIME-CLI-CONFLICT-EXIT-CODE", "Document and test the conflict CLI exit code.", "runtime_command_check"),
    ]
    return [
        _item(
            item_id,
            requirement,
            "local_file_safety_skill",
            "filesystem_write",
            check_kind,
            "blocking",
            ["runtime fixture", "runtime command evidence", "source behavior evidence"],
            "runtime_helper_local_file_safety_mvp",
        )
        for item_id, requirement, check_kind in requirements
    ]


def _structured_input_items() -> list[ProductAcceptanceItem]:
    requirements = [
        ("PG-STRUCTURED-TYPED-PARSER", "Use a typed or equivalent structured parser for JSON inputs."),
        ("PG-STRUCTURED-SCHEMA-VERSION", "Validate schema/version fields when structured inputs define them."),
        ("PG-STRUCTURED-REQUIRED-FIELDS", "Validate required structured input fields."),
        ("PG-STRUCTURED-DUPLICATE-ID", "Detect duplicate IDs in structured input collections."),
        ("PG-STRUCTURED-REFERENCED-ID-EXISTS", "Reject references to unknown IDs."),
        ("PG-STRUCTURED-DETERMINISTIC-JSON", "Serialize machine outputs as deterministic JSON."),
        ("PG-STRUCTURED-MALFORMED-JSON", "Reject malformed JSON with a clear error."),
    ]
    return [
        _item(
            item_id,
            requirement,
            "structured_input_skill",
            "structured_json_input",
            "source_code_behavior_check" if item_id == "PG-STRUCTURED-TYPED-PARSER" else "runtime_fixture_check",
            "major" if item_id == "PG-STRUCTURED-TYPED-PARSER" else "blocking",
            ["schema fixture", "negative fixture", "source parser evidence"],
            "structured_input_mvp",
        )
        for item_id, requirement in requirements
    ]


def _codex_skill_docs_items() -> list[ProductAcceptanceItem]:
    return [
        _item(
            "PG-CODEX-SKILL-INSTALL-DOCS",
            "Explain local installation, invocation, and package layout for the delivered Codex Skill.",
            "codex_skill",
            "distribution_package",
            "docs_static_check",
            "major",
            ["SKILL.md", "README or reference docs"],
            "codex_skill_distribution_mvp",
        ),
        _item(
            "PG-CODEX-SKILL-SAFETY-BOUNDARIES",
            "Document safety boundaries in terms a user can understand.",
            "codex_skill",
            "distribution_package",
            "docs_static_check",
            "major",
            ["SKILL.md safety section"],
            "codex_skill_distribution_mvp",
        ),
    ]


def _reference_data_items(profiles: list[str]) -> list[ProductAcceptanceItem]:
    items: list[ProductAcceptanceItem] = []
    if "reference_heavy_skill" in profiles:
        items.append(
            _item(
                "PG-REFERENCE-SOURCE-INVENTORY",
                "Record the inventory of source documents used to build reference assets.",
                "reference_heavy_skill",
                "external_document_ingestion",
                "required_evidence_check",
                "major",
                ["source inventory", "source hashes"],
                "reference_data_mvp",
            )
        )
    if "data_conversion_skill" in profiles:
        items.append(
            _item(
                "PG-REFERENCE-CONVERSION-PROVENANCE",
                "Record conversion commands, tool versions, and failed-source handling.",
                "data_conversion_skill",
                "external_document_ingestion",
                "required_evidence_check",
                "major",
                ["conversion provenance"],
                "reference_data_mvp",
            )
        )
    if "knowledge_db_skill" in profiles:
        items.append(
            _item(
                "PG-REFERENCE-CITATION-MAPPING",
                "Keep generated facts traceable to source documents or extracted chunks.",
                "knowledge_db_skill",
                "domain_knowledge_reliability",
                "required_evidence_check",
                "major",
                ["citation mapping", "retrieval smoke tests"],
                "reference_data_mvp",
            )
        )
    return items


def _item(
    item_id: str,
    requirement: str,
    profile: str,
    risk_domain: str,
    check_kind: str,
    severity: str,
    required_evidence: list[str],
    source_rule: str,
) -> ProductAcceptanceItem:
    return ProductAcceptanceItem(
        item_id=item_id,
        requirement=requirement,
        profile=profile,
        risk_domain=risk_domain,
        check_kind=check_kind,
        severity=severity,
        required_evidence=required_evidence,
        source_rule=source_rule,
    )


def _with_job_metadata(
    item: ProductAcceptanceItem,
    job_id: str,
    profiles: list[str],
    risks: list[str],
) -> ProductAcceptanceItem:
    item.metadata = {
        "job_id": job_id,
        "compiled_from_profiles": [profile for profile in profiles if profile == item.profile],
        "compiled_from_risk_domains": [risk for risk in risks if risk == item.risk_domain],
    }
    return item
