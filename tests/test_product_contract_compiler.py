from pathlib import Path

from skillfoundry import (
    PRODUCT_ACCEPTANCE_MATRIX_REF,
    PRODUCT_CONTRACT_COMPILER_REPORT_REF,
    RISK_PROFILE_REF,
    DeliveryProfileContract,
    ProductAcceptanceMatrix,
    ProductContractCompiler,
    ProductContractCompilerReport,
    RiskProfile,
    SkillSpec,
    initialize_job_workspace,
)


def make_workspace(tmp_path: Path, skill_spec: SkillSpec, job_id: str = "compiler-001"):
    return initialize_job_workspace(tmp_path / "runs", job_id, skill_spec=skill_spec)


def codexarium_like_spec() -> SkillSpec:
    return SkillSpec(
        skill_id="codexarium-cleanroom",
        title="Codexarium clean-room wiki compactor",
        description=(
            "Build a Codex skill with a Rust runtime helper that validates JSON evidence manifests, "
            "compact evidence notes, and write plans before creating local Markdown wiki proposals."
        ),
        trigger_scenarios=["The user provides authorized compact evidence and asks for local wiki atomic notes."],
        non_trigger_scenarios=["Do not scan raw chat, whole computers, or unauthorized local files."],
        required_inputs=["JSON evidence manifest", "compact evidence notes", "explicit wiki root"],
        expected_outputs=["Conflict proposals and candidate Markdown notes without overwrite."],
        constraints=["No overwrite; detect conflicts; validation-only commands must not write files."],
        acceptance_criteria=["The runtime rejects unsafe target paths and duplicate write plan targets."],
        reference_materials=[],
        security_notes=["Respect privacy boundaries and explicit user authorization."],
    )


def prompt_only_spec() -> SkillSpec:
    return SkillSpec(
        skill_id="prompt-only",
        title="Prompt-only planning assistant",
        description="A Codex skill that gives structured planning guidance through instructions only.",
        trigger_scenarios=["The user asks for a planning checklist."],
        non_trigger_scenarios=["Requests requiring executable helpers."],
        required_inputs=["A short goal summary."],
        expected_outputs=["A concise planning checklist."],
        constraints=["Use only the text instructions in SKILL.md."],
        acceptance_criteria=["The skill has clear trigger and non-trigger guidance."],
        reference_materials=[],
        security_notes=["Do not request secrets."],
    )


def eda_like_spec() -> SkillSpec:
    return SkillSpec(
        skill_id="eda-reference-skill",
        title="EDA layout reference skill",
        description=(
            "Convert official semiconductor layout PDF documentation into a structured domain reference "
            "database with citation/source mapping for retrieval."
        ),
        trigger_scenarios=["The user needs help with EDA layout scripting based on official manuals."],
        non_trigger_scenarios=["General programming tasks outside the EDA layout domain."],
        required_inputs=["Official PDF manuals", "conversion logs", "domain examples"],
        expected_outputs=["Chunked Markdown references, indexed database assets, and factual QA samples."],
        constraints=["Every generated fact must map back to source documents."],
        acceptance_criteria=["Retrieval smoke tests and random factual citation checks pass."],
        reference_materials=["Official PDF documentation"],
        security_notes=["Do not invent unsupported domain facts."],
    )


def service_like_spec() -> SkillSpec:
    return SkillSpec(
        skill_id="local-service-skill",
        title="Local MCP service skill",
        description=(
            "Build a Codex skill that packages a long-running local server daemon with HTTP API startup, "
            "healthcheck, shutdown, and process cleanup instructions."
        ),
        trigger_scenarios=["The user wants to run a local background service from the skill package."],
        non_trigger_scenarios=["One-shot prompt-only guidance."],
        required_inputs=["Service config", "local port", "environment variables"],
        expected_outputs=["A packaged service bundle with startup and healthcheck docs."],
        constraints=["Document lifecycle boundaries and avoid unmanaged background processes."],
        acceptance_criteria=["Service startup, healthcheck, and shutdown smoke tests are documented."],
        reference_materials=[],
        security_notes=["Do not expose secrets through the service environment."],
    )


def test_compiler_infers_runtime_local_file_and_structured_profiles(tmp_path: Path):
    workspace = make_workspace(tmp_path, codexarium_like_spec())

    artifacts = ProductContractCompiler().compile(workspace)

    profiles = artifacts.delivery_profile.profiles
    risks = artifacts.risk_profile.risk_domains
    item_ids = {item.item_id for item in artifacts.acceptance_matrix.items}
    assert {"codex_skill", "runtime_helper_skill", "local_file_safety_skill", "structured_input_skill"}.issubset(profiles)
    assert {"filesystem_write", "privacy_boundary", "structured_json_input", "runtime_execution"}.issubset(risks)
    assert "PG-RUNTIME-SAME-PLAN-DUPLICATE-PATH" in item_ids
    assert "PG-RUNTIME-SAME-PLAN-DUPLICATE-TITLE" in item_ids
    assert "PG-STRUCTURED-TYPED-PARSER" in item_ids
    assert workspace.resolve_path(PRODUCT_ACCEPTANCE_MATRIX_REF, must_exist=True).is_file()
    assert ProductAcceptanceMatrix.read_json_file(workspace.resolve_path(PRODUCT_ACCEPTANCE_MATRIX_REF)).job_id == workspace.job_id


def test_compiler_keeps_prompt_only_specs_out_of_runtime_matrix(tmp_path: Path):
    workspace = make_workspace(tmp_path, prompt_only_spec(), job_id="compiler-prompt-only")

    artifacts = ProductContractCompiler().compile(workspace)

    assert artifacts.delivery_profile.profiles == ["codex_skill", "prompt_only_skill"]
    assert "runtime_helper_skill" not in artifacts.delivery_profile.profiles
    assert "local_file_safety_skill" not in artifacts.delivery_profile.profiles
    assert all(not item.item_id.startswith("PG-RUNTIME-") for item in artifacts.acceptance_matrix.items)


def test_compiler_infers_reference_heavy_data_conversion_profiles(tmp_path: Path):
    workspace = make_workspace(tmp_path, eda_like_spec(), job_id="compiler-eda")

    artifacts = ProductContractCompiler().compile(workspace)

    assert {"reference_heavy_skill", "data_conversion_skill", "knowledge_db_skill"}.issubset(
        artifacts.delivery_profile.profiles
    )
    assert {"external_document_ingestion", "domain_knowledge_reliability"}.issubset(
        artifacts.risk_profile.risk_domains
    )
    item_ids = {item.item_id for item in artifacts.acceptance_matrix.items}
    assert "PG-REFERENCE-SOURCE-INVENTORY" in item_ids
    assert "PG-REFERENCE-CONVERSION-PROVENANCE" in item_ids
    assert "PG-REFERENCE-CITATION-MAPPING" in item_ids


def test_compiler_infers_service_bundle_product_matrix_items(tmp_path: Path):
    workspace = make_workspace(tmp_path, service_like_spec(), job_id="compiler-service")

    artifacts = ProductContractCompiler().compile(workspace)

    assert "service_bundle_skill" in artifacts.delivery_profile.profiles
    assert "long_running_service" in artifacts.risk_profile.risk_domains
    item_ids = {item.item_id for item in artifacts.acceptance_matrix.items}
    assert "PG-SERVICE-STARTUP-CONTRACT" in item_ids
    assert "PG-SERVICE-HEALTHCHECK" in item_ids
    assert "PG-SERVICE-SHUTDOWN-BOUNDARY" in item_ids


def test_compiler_outputs_refs_only_artifacts_without_raw_conversation(tmp_path: Path):
    workspace = make_workspace(tmp_path, codexarium_like_spec(), job_id="compiler-refs-only")

    ProductContractCompiler().compile(workspace)

    delivery = DeliveryProfileContract.read_json_file(workspace.resolve_path("product_contract/delivery_profile.json"))
    risk = RiskProfile.read_json_file(workspace.resolve_path(RISK_PROFILE_REF))
    report = ProductContractCompilerReport.read_json_file(workspace.resolve_path(PRODUCT_CONTRACT_COMPILER_REPORT_REF))
    serialized = "\n".join([delivery.to_json(), risk.to_json(), report.to_json()])
    assert "conversation" not in serialized
    assert "raw_prompt" not in serialized
    assert "JSON evidence manifest" not in serialized
