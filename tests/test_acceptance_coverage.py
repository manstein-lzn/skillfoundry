from __future__ import annotations

import json

import pytest

import skillfoundry
from skillfoundry import (
    ACCEPTANCE_COVERAGE_PLAN_REF,
    ACCEPTANCE_COVERAGE_RESULT_REF,
    AcceptanceCriteriaPlanner,
    AcceptanceCoverageEvaluator,
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    LocalSkillRegistry,
    RegistryGateError,
    SkillSpec,
    Verifier,
    initialize_job_workspace,
    sha256_file,
)
from skillfoundry.qa import QALab
from skillfoundry.worker import WorkerAdapter, WorkerExecutionOutcome


GOOD_SKILL_MD = """---
name: acceptance-good-skill
description: Deterministic acceptance coverage fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# Acceptance Good Skill

## Overview

This package gives deterministic pytest repair triage with local evidence only.

## When To Use

- Use when a developer asks for deterministic pytest failure triage in a local repository.

## When Not To Use

- Do not use when the request requires deployment, live providers, or network debugging.

## Inputs

- A pytest failure log, repository path, and locked worker input manifest.

## Outputs

- A concise repair plan, changed-file summary, and verification command list.

## Workflow

1. Read the pytest failure log and repository path from the locked input manifest.
2. Compare the failing assertion with nearby source code and tests.
3. Return a repair plan with exact verification commands.

## Safety

- Do not run network commands or live providers during triage.
- Keep helper scripts under package/scripts.
"""


WEAK_SKILL_MD = """---
name: acceptance-weak-skill
description: Structurally valid but behaviorally weak fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# Acceptance Weak Skill

## Overview

This package has every required verifier section but avoids useful specifics.

## When To Use

- Use when needed.

## When Not To Use

- Do not use otherwise.

## Inputs

- Any input.

## Outputs

- Useful output.

## Workflow

Do it.

## Safety

Be safe.
"""


MANIFEST_SCHEMA_SKILL_MD = (
    GOOD_SKILL_MD
    + """

## Manifest Schema

The manifest format is JSON. Each evidence item requires evidence_id,
source_type, title, summary, allowed_use, sensitivity, and created_at.
Optional fields include project, tags, and related_entries.
"""
)


CODEXARIUM_DIALOG_014_STYLE_SKILL_MD = """---
name: codexarium
description: Controlled-evidence wiki distillation for user-provided JSON evidence manifests and compact evidence notes.
---

# codexarium

## Overview

Use this skill to turn explicitly authorized, compact collaboration evidence
into reviewable Markdown wiki entries. Operate from two user-provided inputs
only: a JSON evidence manifest and compact evidence notes.

The bundled local Rust verifier is deterministic. It does not perform
networking, broad filesystem scanning, syncing, background service behavior, or
database work.

## When To Use

Use this skill when the user wants codexarium wiki distillation from a JSON
evidence manifest and compact evidence notes. Confirm that the user explicitly
authorizes the supplied evidence for codexarium/wiki distillation.

## When Not To Use

Do not use this skill for raw chat scanning, terminal-output scanning,
arbitrary file reads, whole-disk scanning, automatic collection, network sync,
daily reporting, or database service behavior. Refuse or stop when the evidence
boundary is unclear.

## Inputs

The manifest format is JSON. Each evidence record requires evidence_id,
source_type, title, summary, allowed_use, sensitivity, and created_at. Optional
fields include project, tags, and related_entries. evidence_id values must be
unique. Every evidence_id referenced by compact notes, candidate entries, wiki
metadata, or proposals must exist in the manifest.

## Outputs

Generated Markdown entries or proposals include evidence_id references and
Evidence References sufficient for review and reuse. Tie every substantive
claim to allowed_use-compatible evidence references in candidate or wiki output.

Use this fixed wiki taxonomy with top-level directories:

- projects
- decisions
- research
- lessons
- open-questions
- principles

Derived target paths include decisions/<slug>.md,
projects/<project>/index.md, open-questions/<slug>.md,
principles/<slug>.md, research/<slug>.md, and lessons/<slug>.md.

## Workflow

1. Confirm authorization before processing.
2. Stop if required fields are missing, allowed_use or sensitivity is
   disallowed, evidence_id values are duplicated, or references point to
   unknown evidence_id values.
3. Derive target paths from entry_type plus slug or project. Reject absolute
   paths, parent directory traversal, backslashes, empty components, illegal
   slug values, and any resolved path outside the wiki root.
4. If an existing target file creates a conflict, default to no overwrite and
   produce update, append, or merge proposals with intended content and evidence
   references.
5. Wait for explicit user confirmation before modification.

## Safety

The local verifier checks manifest JSON structure, evidence_id uniqueness,
required wiki directories, evidence references, and target path safety.

Local smoke verification commands:

```bash
cargo test
cargo run -- verify --manifest tests/fixtures/valid/manifest.json --wiki-root tests/fixtures/valid/wiki-root --candidate tests/fixtures/valid/candidate.json
```
"""


class AcceptanceFixtureWorker:
    def __init__(self, skill_md: str = GOOD_SKILL_MD) -> None:
        self.skill_md = skill_md

    @property
    def worker_type(self) -> str:
        return "test:acceptance-fixture"

    def run(self, context):
        context.write_text("package/SKILL.md", self.skill_md)
        context.write_text("package/references/guide.md", "# Guide\n\nLocal deterministic guide.\n")
        context.write_text("package/scripts/helper.py", "def helper() -> str:\n    return 'ok'\n")
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="Acceptance fixture worker wrote a package candidate.",
            artifacts=[
                "package/SKILL.md",
                "package/references/guide.md",
                "package/scripts/helper.py",
            ],
            transcript_lines=["wrote acceptance fixture package"],
            usage_unavailable_reason="Acceptance fixture worker does not call model providers.",
        )


def skill_spec(job_id: str) -> SkillSpec:
    return SkillSpec(
        skill_id=f"{job_id}-skill",
        title="Deterministic pytest repair triage",
        description="Acceptance coverage fixture SkillSpec.",
        trigger_scenarios=["A developer asks for deterministic pytest failure triage."],
        non_trigger_scenarios=["The request requires deployment, live providers, or network debugging."],
        required_inputs=["A pytest failure log and repository path."],
        expected_outputs=["A concise repair plan and verification command list."],
        constraints=["No network calls.", "No live provider calls."],
        acceptance_criteria=["Report concrete workflow, safety, and IO contract evidence."],
        reference_materials=[],
        security_notes=["Helper scripts must remain under package/scripts."],
    )


def criterion(criterion_id: str, **overrides) -> AcceptanceCriterion:
    payload = {
        "id": criterion_id,
        "description": f"{criterion_id} is deterministically covered.",
        "source_requirement": "Build a deterministic local skill.",
        "source_turn_ids": ["turn-001"],
        "requirement_id": f"REQ-{criterion_id}",
        "test_method": "static",
        "pass_condition": "The mapped deterministic evidence passes.",
        "failure_examples": ["Evidence is missing."],
        "required_evidence": [],
        "evidence_kind": "verifier_check",
        "priority": "must",
        "risk_tags": [],
        "data_sensitivity": "internal",
        "coverage_status": "planned",
        "verifier_check_id": "package_skill_md_present",
    }
    payload.update(overrides)
    return AcceptanceCriterion(**payload)


def write_criteria(workspace, criteria: list[AcceptanceCriterion]) -> None:
    AcceptanceCriteriaSet(criteria=criteria, job_id=workspace.job_id).write_yaml_file(
        workspace.resolve_path("acceptance_criteria.yaml")
    )


def make_workspace(
    tmp_path,
    *,
    job_id: str,
    skill_md: str = GOOD_SKILL_MD,
    criteria: list[AcceptanceCriterion] | None = None,
):
    workspace = initialize_job_workspace(
        tmp_path / "runs",
        job_id,
        skill_spec=skill_spec(job_id),
    )
    if criteria is not None:
        write_criteria(workspace, criteria)
    WorkerAdapter(AcceptanceFixtureWorker(skill_md)).invoke(workspace, "001")
    return workspace


def make_verified_qa_workspace(
    tmp_path,
    *,
    job_id: str,
    skill_md: str = GOOD_SKILL_MD,
    criteria: list[AcceptanceCriterion] | None = None,
):
    workspace = make_workspace(tmp_path, job_id=job_id, skill_md=skill_md, criteria=criteria)
    verification = Verifier().verify(workspace)
    assert verification.passed is True
    qa_result = QALab().evaluate(workspace)
    return workspace, verification, qa_result


def plan_and_evaluate(workspace):
    plan = AcceptanceCriteriaPlanner().plan(workspace)
    result = AcceptanceCoverageEvaluator().evaluate(workspace, plan=plan)
    return plan, result


def read_json(workspace, ref: str):
    return json.loads(workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8"))


def write_manual_acceptance_record(workspace, criterion_ids: list[str], *, decision: str = "approved") -> None:
    payload = {
        "schema_version": "skillfoundry.manual_acceptance_record.v1",
        "reviewer_id": "qa-reviewer-001",
        "reviewer_role": "qa_lead",
        "decision": decision,
        "reason": "Manual acceptance reviewed the listed must criteria.",
        "covered_criterion_ids": criterion_ids,
        "source_hash": sha256_file(workspace.resolve_path("acceptance_criteria.yaml", must_exist=True)),
        "created_at": "2026-05-21T00:00:00Z",
    }
    path = workspace.resolve_path("qa/manual_acceptance_record.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def result_item(result, criterion_id: str):
    return next(item for item in result.items if item.criterion_id == criterion_id)


def write_fake_codexarium_verification_result(workspace) -> None:
    verifier_dir = workspace.resolve_path("verifier")
    verifier_dir.mkdir(parents=True, exist_ok=True)
    (verifier_dir / "cargo_test.log").write_text("cargo test passed\n", encoding="utf-8")
    payload = {
        "schema_version": "skillfoundry.verification_result.v1",
        "result_id": "verification-test-codexarium-014",
        "job_id": workspace.job_id,
        "package_hash": "0" * 64,
        "verification_spec_hash": "0" * 64,
        "passed": True,
        "checks": [
            {
                "name": "package_skill_md_present",
                "passed": True,
                "severity": "error",
                "message": "package/SKILL.md exists",
                "evidence_ref": "package/SKILL.md",
            },
            {
                "name": "package_cargo_toml_present",
                "passed": True,
                "severity": "error",
                "message": "package/Cargo.toml exists",
                "evidence_ref": "package/Cargo.toml",
            },
            {
                "name": "package_rust_sources_present",
                "passed": True,
                "severity": "error",
                "message": "Rust source files exist",
                "evidence_ref": "package/src",
            },
            {
                "name": "package_cargo_test",
                "passed": True,
                "severity": "error",
                "message": "cargo test passed",
                "evidence_ref": "verifier/cargo_test.log",
            },
        ],
        "failures": [],
        "evidence_refs": ["package/SKILL.md", "package/Cargo.toml", "package/src", "verifier/cargo_test.log"],
        "verifier_version": "skillfoundry.verifier.test",
        "created_at": "2026-05-24T00:00:00Z",
        "llm_judge_ref": None,
    }
    (verifier_dir / "verification_result.json").write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_workspace_text(workspace, ref: str, text: str) -> None:
    path = workspace.root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_acceptance_coverage_api_is_exported():
    assert skillfoundry.AcceptanceCriteriaPlanner is AcceptanceCriteriaPlanner
    assert skillfoundry.AcceptanceCoverageEvaluator is AcceptanceCoverageEvaluator
    assert skillfoundry.ACCEPTANCE_COVERAGE_PLAN_REF == ACCEPTANCE_COVERAGE_PLAN_REF
    assert skillfoundry.ACCEPTANCE_COVERAGE_RESULT_REF == ACCEPTANCE_COVERAGE_RESULT_REF


def test_planner_maps_every_criterion_to_one_plan_item(tmp_path):
    workspace = make_workspace(
        tmp_path,
        job_id="acceptance-plan",
        criteria=[
            criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present"),
            criterion(
                "AC-FIXTURE",
                test_method="fixture",
                evidence_kind="file",
                verifier_check_id=None,
                fixture_ref="qa/fixtures/input.md",
            ),
            criterion(
                "AC-EVIDENCE",
                evidence_kind="file",
                verifier_check_id=None,
                required_evidence=["qa/evidence/output.md"],
            ),
            criterion(
                "AC-QA",
                evidence_kind="qa_report",
                verifier_check_id=None,
                required_evidence=["workflow_actionability"],
            ),
            criterion(
                "AC-MANUAL",
                test_method="manual_check",
                evidence_kind="human_note",
                verifier_check_id=None,
                manual_authority="qa-lead",
            ),
            criterion(
                "AC-UNCOVERED",
                verifier_check_id=None,
                coverage_status="uncovered",
                unverifiable_reason="fixture not available",
            ),
        ],
    )

    plan = AcceptanceCriteriaPlanner().plan(workspace)
    payload = read_json(workspace, ACCEPTANCE_COVERAGE_PLAN_REF)

    assert payload["schema_version"] == skillfoundry.ACCEPTANCE_COVERAGE_PLAN_VERSION
    assert {item.criterion_id for item in plan.items} == {
        "AC-VERIFIER",
        "AC-FIXTURE",
        "AC-EVIDENCE",
        "AC-QA",
        "AC-MANUAL",
        "AC-UNCOVERED",
    }
    assert {item["criterion_id"] for item in payload["items"]} == {item.criterion_id for item in plan.items}
    assert len(plan.items) == 6


def test_planner_maps_natural_frontdesk_verifier_text_to_static_check(tmp_path):
    natural_text = (
        "The manifest format is JSON and requires at least evidence_id, source_type, "
        "title, summary, allowed_use, sensitivity, and created_at, with optional "
        "project, tags, and related_entries fields."
    )
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-natural-frontdesk",
        skill_md=MANIFEST_SCHEMA_SKILL_MD,
        criteria=[
            criterion(
                "AC-NATURAL-MANIFEST",
                verifier_check_id=None,
                description=natural_text,
                pass_condition=natural_text,
                required_evidence=[natural_text],
                evidence_kind="verifier_check",
            )
        ],
    )

    plan, result = plan_and_evaluate(workspace)

    assert plan.items[0].verifier_check_id == "manifest_schema_documented"
    assert result.passed is True
    item = result_item(result, "AC-NATURAL-MANIFEST")
    assert item.status == "covered/pass"
    assert "package/SKILL.md" in item.evidence_refs


def test_unknown_natural_verifier_text_remains_uncovered(tmp_path):
    natural_text = "The package should feel polished and delightful to future readers."
    workspace = make_workspace(
        tmp_path,
        job_id="acceptance-natural-uncovered",
        criteria=[
            criterion(
                "AC-NATURAL-UNKNOWN",
                verifier_check_id=None,
                description=natural_text,
                pass_condition=natural_text,
                required_evidence=[natural_text],
                evidence_kind="verifier_check",
            )
        ],
    )

    plan = AcceptanceCriteriaPlanner().plan(workspace)

    assert plan.items[0].coverage_mode == "uncovered"
    assert plan.items[0].uncovered_reason == "no_deterministic_evidence_mapping"


def test_planner_maps_chinese_frontdesk_verifier_text_to_static_checks(tmp_path):
    target_path_text = "target path 由 entry_type 和 slug/project 生成，且拒绝绝对路径、父目录穿越、反斜杠、空组件、非法 slug 和越界写入。"
    rust_package_text = "交付包含 Rust 本地 verifier 项目，至少包含 Cargo.toml、src、tests/fixtures。"
    fixture_text = "测试 fixtures 覆盖有效案例和关键无效案例，包括缺字段、重复 evidence_id、未知 evidence_id、allowed_use/sensitivity 不允许、非法 slug、路径穿越、越界写入、缺少必需目录。"
    workspace = make_workspace(
        tmp_path,
        job_id="acceptance-chinese-frontdesk",
        criteria=[
            criterion(
                "AC-CN-TARGET",
                verifier_check_id=None,
                description=target_path_text,
                pass_condition=target_path_text,
                required_evidence=[target_path_text],
                evidence_kind="verifier_check",
            ),
            criterion(
                "AC-CN-RUST-PACKAGE",
                verifier_check_id=None,
                description=rust_package_text,
                pass_condition=rust_package_text,
                required_evidence=[rust_package_text],
                evidence_kind="verifier_check",
            ),
            criterion(
                "AC-CN-FIXTURES",
                verifier_check_id=None,
                description=fixture_text,
                pass_condition=fixture_text,
                required_evidence=[fixture_text],
                evidence_kind="verifier_check",
            ),
        ],
    )

    plan = AcceptanceCriteriaPlanner().plan(workspace)
    by_id = {item.criterion_id: item.verifier_check_id for item in plan.items}

    assert by_id == {
        "AC-CN-TARGET": "rust_verifier_path_safety",
        "AC-CN-RUST-PACKAGE": "rust_verifier_package_present",
        "AC-CN-FIXTURES": "rust_verifier_fixture_coverage",
    }


def test_codexarium_dialog_014_style_natural_criteria_pass_with_deterministic_evidence(tmp_path):
    criteria_texts = [
        "A complete local Codex Skill package named codexarium is produced without using or depending on any existing local codexarium implementation.",
        "SKILL.md clearly defines triggers, non-triggers, input contract, outputs, workflow, safety boundaries, confirmation gates, conflict policy, refusal conditions, and local verification expectations.",
        "The Skill only processes a user-provided JSON evidence manifest plus compact evidence notes and explicitly refuses raw chat scanning, terminal-output scanning, arbitrary file reads, whole-disk scanning, automatic collection, network sync, daily reporting, and database service behavior.",
        "The manifest contract requires evidence_id, source_type, title, summary, allowed_use, sensitivity, and created_at, and supports optional project, tags, and related_entries.",
        "The Skill stops before processing when authorization is unclear, manifest fields are missing, allowed_use or sensitivity is disallowed, evidence_id values are duplicated, or references point to unknown evidence.",
        "The wiki structure uses fixed top-level directories and derived target paths for project pages and type entries, including decisions/<slug>.md, projects/<project>/index.md, open-questions/<slug>.md, and principles/<slug>.md, with coverage for research conclusions and lessons.",
        "Slug and target-path handling rejects absolute paths, parent directory traversal, backslashes, empty components, illegal slug values, and any resolved path outside the wiki root.",
        "Existing target files are never overwritten by default; conflicts produce update/append/merge proposals that show intended content and evidence references and require explicit user confirmation before modification.",
        "Generated Markdown entries or proposals include evidence_id references sufficient for review and reuse.",
        "A Rust verifier project is included with Cargo.toml, src, tests/fixtures, valid and invalid fixture cases, and cargo test coverage for manifest JSON structure, evidence_id uniqueness, required wiki directories, evidence references, and target path safety.",
        "The package documents at least one local smoke verification command, including cargo test and a verifier invocation against fixture data.",
        "The verifier is local and deterministic; it does not perform networking, scanning, syncing, or background service behavior.",
    ]
    workspace = make_workspace(
        tmp_path,
        job_id="acceptance-codexarium-014-style",
        skill_md=CODEXARIUM_DIALOG_014_STYLE_SKILL_MD,
        criteria=[
            criterion(
                f"AC-{index:03d}",
                verifier_check_id=None,
                description=text,
                pass_condition=text,
                required_evidence=[text],
                evidence_kind="verifier_check",
            )
            for index, text in enumerate(criteria_texts, start=1)
        ],
    )
    write_workspace_text(
        workspace,
        "worker_input.md",
        "Build a clean-room local Codex Skill package named codexarium from frozen Front Desk sources and current user-provided inputs.\n",
    )
    write_workspace_text(
        workspace,
        "evidence/transcript.md",
        "Task: Build a clean-room local Codex Skill package named codexarium from the frozen SkillFoundry inputs.\n",
    )
    write_workspace_text(workspace, "package/Cargo.toml", "[package]\nname = \"codexarium\"\nversion = \"0.1.0\"\nedition = \"2021\"\n")
    write_workspace_text(
        workspace,
        "package/src/lib.rs",
        "pub fn validate_target_path() { /* target_path absolute relative parent .. unsafe traversal */ }\n",
    )
    write_workspace_text(
        workspace,
        "package/tests/verifier.rs",
        "#[test]\nfn path_safety() { assert!(true); } // target path absolute parent traversal unsafe\n",
    )
    write_workspace_text(workspace, "package/tests/fixtures/valid/manifest.json", "{\"evidence\": []}\n")
    write_fake_codexarium_verification_result(workspace)

    plan, result = plan_and_evaluate(workspace)
    by_id = {item.criterion_id: item.verifier_check_id for item in plan.items}

    assert by_id == {
        "AC-001": "skill_clean_room_boundary",
        "AC-002": "skill_package_instruction_contract",
        "AC-003": "skill_privacy_boundary",
        "AC-004": "manifest_schema_documented",
        "AC-005": "evidence_authorization_gate",
        "AC-006": "wiki_structure_and_paths_contract",
        "AC-007": "rust_verifier_path_safety",
        "AC-008": "write_conflict_policy_contract",
        "AC-009": "evidence_references_contract",
        "AC-010": "package_cargo_test",
        "AC-011": "local_smoke_command_documented",
        "AC-012": "local_deterministic_verifier_boundary",
    }
    assert result.passed is True
    assert result.must_total == 12
    assert result.must_passed == 12


def test_codexarium_v1_frontdesk_criteria_pass_with_package_level_fixtures(tmp_path):
    criteria_texts = [
        "交付物包含一个完整的本地 Codex Skill 包，至少包括 SKILL.md、reference 文档、Rust helper/CLI、fixtures、manifest 示例、compact note 示例和测试/smoke 说明。",
        "SKILL.md 清楚定义 Agent Interface：何时使用、何时不使用、输入、输出、澄清策略、安全落盘策略和验证方式。",
        "reference 文档清楚定义固定 taxonomy，且 taxonomy 至少覆盖项目、领域知识、工作流、决策、参考资料/片段等常见知识单元。",
        "reference 文档清楚定义 manifest 与 compact notes 的稳定格式，并给出可检查示例。",
        "Rust helper/CLI 能对授权 wiki root 执行路径安全校验，阻止路径穿越或 root 外写入。",
        "写入行为默认不覆盖已有文件；当目标路径或条目冲突时，输出 conflict proposal，而不是直接修改或覆盖用户数据。",
        "Skill 和 helper 的运行说明不依赖外部服务，能在本地工作区完成验证。",
        "fixtures 至少覆盖一个成功创建/验证案例、一个已有文件冲突案例、一个路径越界案例、一个 taxonomy 错误案例，以及一个 manifest 或 compact notes 错误案例。",
        "验收可看到 cargo test 或等效 smoke 命令及其预期证据，证明路径安全、taxonomy、manifest、compact notes 和 conflict behavior 可被 deterministic 检查。",
        "交付过程和文档明确 clean-room 边界：不读取、不复用任何既有 Codexarium 实现代码或文件，不默认扫描 home，不访问真实敏感数据。",
    ]
    skill_md = """---
name: codexarium
description: Local clean-room Markdown wiki helper.
---

# Codexarium

## Overview
Codexarium is a local, clean-room Codex Skill with a deterministic Rust helper.
It does not read or reuse any existing Codexarium implementation and does not
depend on external services.

## When To Use
Use this skill when the user explicitly provides a user-authorized wiki root
and wants Codex to create, organize, validate, or cite Markdown knowledge.

## When Not To Use
Do not use it without a wiki root, for home scans, for existing implementation
reuse, or when the request should stop for safety.

## Inputs
Required inputs include wiki_root, task_goal, category, and write permission.

## Outputs
Outputs include Markdown entries, manifest updates, compact notes, validation
reports, and a conflict proposal.

## Workflow
Confirm the wiki root, classify by fixed taxonomy, validate target path, plan
with no overwrite behavior, present a conflict proposal, and wait for user
decision before writing.

## Safety
Root boundary is user-authorized only. Reject path traversal. No overwrite by
default. Do not scan home. Use cargo test for verification.
"""
    workspace = make_workspace(
        tmp_path,
        job_id="acceptance-codexarium-v1-frontdesk",
        skill_md=skill_md,
        criteria=[
            criterion(
                f"AC-{index:03d}",
                verifier_check_id=None,
                description=text,
                pass_condition=text,
                required_evidence=[text],
                evidence_kind="verifier_check",
            )
            for index, text in enumerate(criteria_texts, start=1)
        ],
    )
    write_workspace_text(
        workspace,
        "worker_input.md",
        "Build a clean-room Codexarium package from current user-provided FrontDesk inputs only.\n",
    )
    write_workspace_text(
        workspace,
        "evidence/transcript.md",
        "Clean-room build from user-authorized current user inputs. No existing implementation was read.\n",
    )
    write_workspace_text(
        workspace,
        "package/references/codexarium_reference.md",
        """
# Codexarium Reference
## Fixed Taxonomy
projects, domain_knowledge, workflows, decisions, references_or_snippets.
## Manifest Format
manifest_version: 1; entry path title summary.
## Compact Note Format
compact_note_version: 1; source_path summary points.
## Conflict Proposal
conflict proposal with no overwrite and user decision.
""".strip(),
    )
    write_workspace_text(
        workspace,
        "package/references/runtime_and_tests.md",
        "Local runtime in the skill package root. Run cargo test --manifest-path package/Cargo.toml. No external services are called.\n",
    )
    write_workspace_text(workspace, "package/examples/manifest.cdxm", "manifest_version: 1\nentry|id=a|category=projects|path=projects/a.md|title=A|summary=A\n")
    write_workspace_text(workspace, "package/examples/compact_note.cdxn", "compact_note_version: 1\nsource_path: projects/a.md\nsummary: A\n")
    write_workspace_text(workspace, "package/Cargo.toml", "[package]\nname = \"codexarium-helper\"\nversion = \"0.1.0\"\nedition = \"2021\"\n")
    write_workspace_text(
        workspace,
        "package/src/lib.rs",
        """
pub fn validate_target_path() {
    // target path validation rejects absolute paths, parent traversal via ..,
    // unsafe path traversal, and outside the wiki root targets.
}
pub const FIXTURES: &[&str] = &[
    "valid_wiki", "conflict_wiki", "path_escape_wiki", "taxonomy_error_wiki", "bad_manifest_wiki"
];
""".strip(),
    )
    write_workspace_text(workspace, "package/fixtures/valid_wiki/.codexarium/manifest.cdxm", "valid_wiki manifest\n")
    write_workspace_text(workspace, "package/fixtures/conflict_wiki/projects/existing.md", "conflict\n")
    write_workspace_text(workspace, "package/fixtures/path_escape_wiki/.codexarium/manifest.cdxm", "parent traversal\n")
    write_workspace_text(workspace, "package/fixtures/taxonomy_error_wiki/misc/bad.md", "taxonomy\n")
    write_workspace_text(workspace, "package/fixtures/bad_manifest_wiki/.codexarium/manifest.cdxm", "compact note manifest error\n")
    write_fake_codexarium_verification_result(workspace)

    plan, result = plan_and_evaluate(workspace)

    assert {item.criterion_id: item.verifier_check_id for item in plan.items} == {
        "AC-001": "local_smoke_command_documented",
        "AC-002": "skill_package_instruction_contract",
        "AC-003": "codexarium_taxonomy_contract",
        "AC-004": "codexarium_manifest_compact_contract",
        "AC-005": "rust_verifier_path_safety",
        "AC-006": "write_conflict_policy_contract",
        "AC-007": "codexarium_local_runtime_contract",
        "AC-008": "codexarium_fixture_scenario_coverage",
        "AC-009": "local_smoke_command_documented",
        "AC-010": "skill_clean_room_boundary",
    }
    assert result.passed is True
    assert result.must_passed == 10


def test_codexarium_v1_accepts_singular_taxonomy_and_hyphen_fixture_names(tmp_path):
    criteria_texts = [
        "reference 文档清楚定义固定 taxonomy，且 taxonomy 至少覆盖项目、领域知识、工作流、决策、参考资料/片段等常见知识单元。",
        "fixtures 至少覆盖一个成功创建/验证案例、一个已有文件冲突案例、一个路径越界案例、一个 taxonomy 错误案例，以及一个 manifest 或 compact notes 错误案例。",
    ]
    workspace = make_workspace(
        tmp_path,
        job_id="acceptance-codexarium-singular-taxonomy",
        criteria=[
            criterion(
                f"AC-{index:03d}",
                verifier_check_id=None,
                description=text,
                pass_condition=text,
                required_evidence=[text],
                evidence_kind="verifier_check",
            )
            for index, text in enumerate(criteria_texts, start=1)
        ],
    )
    write_workspace_text(
        workspace,
        "package/references/taxonomy.md",
        "Fixed taxonomy ids: project, domain, workflow, decision, reference, snippet.\n",
    )
    write_workspace_text(workspace, "package/fixtures/valid/.codexarium/manifest.txt", "valid fixture\n")
    write_workspace_text(workspace, "package/fixtures/conflict/.codexarium/manifest.txt", "conflict proposal fixture\n")
    write_workspace_text(
        workspace,
        "package/fixtures/path-traversal/.codexarium/manifest.txt",
        "parent traversal path-traversal fixture\n",
    )
    write_workspace_text(
        workspace,
        "package/fixtures/bad-taxonomy/.codexarium/manifest.txt",
        "invalid taxonomy bad-taxonomy fixture\n",
    )
    write_workspace_text(
        workspace,
        "package/fixtures/bad-compact-note/.codexarium/compact/bad.md",
        "bad compact note fixture\n",
    )
    write_workspace_text(workspace, "package/src/lib.rs", "pub fn fixture_names() {}\n")
    write_fake_codexarium_verification_result(workspace)

    plan, result = plan_and_evaluate(workspace)

    assert {item.criterion_id: item.verifier_check_id for item in plan.items} == {
        "AC-001": "codexarium_taxonomy_contract",
        "AC-002": "codexarium_fixture_scenario_coverage",
    }
    assert result.passed is True
    assert result.must_passed == 2


def test_planner_maps_codexarium_dialog_015_granular_criteria(tmp_path):
    criteria_texts = [
        "The generated package is a local Codex Skill package named codexarium and includes SKILL.md.",
        "The package does not read, depend on, copy, reference, or require any existing local codexarium code, documentation, or implementation.",
        "The Skill accepts only user-explicitly-provided JSON evidence manifests and compact evidence notes as inputs.",
        "The verifier rejects duplicate evidence_id values.",
        "The wiki taxonomy is fixed to projects, decisions, research, lessons, open-questions, and principles.",
        "The Skill derives target paths only from entry type plus slug/project using the documented allowed patterns.",
        "The path safety logic rejects absolute paths, parent traversal via .., backslashes, empty components, illegal slugs, and paths outside the wiki root.",
        "Markdown wiki entries and conflict proposals include evidence_id references for all substantive content.",
        "Existing target files are no-overwrite by default.",
        "When an existing target would be affected, the Skill outputs an update, append, or merge proposal showing intended content and evidence references, then waits for explicit user confirmation before modification.",
    ]
    workspace = make_workspace(
        tmp_path,
        job_id="acceptance-codexarium-015-granular",
        criteria=[
            criterion(
                f"AC-{index:03d}",
                verifier_check_id=None,
                description=text,
                pass_condition=text,
                required_evidence=[text],
                evidence_kind="verifier_check",
            )
            for index, text in enumerate(criteria_texts, start=1)
        ],
    )

    plan = AcceptanceCriteriaPlanner().plan(workspace)

    assert {item.criterion_id: item.verifier_check_id for item in plan.items} == {
        "AC-001": "skill_package_instruction_contract",
        "AC-002": "skill_clean_room_boundary",
        "AC-003": "skill_user_evidence_boundary",
        "AC-004": "rust_verifier_core_validation",
        "AC-005": "wiki_structure_and_paths_contract",
        "AC-006": "path_generation_contract",
        "AC-007": "rust_verifier_path_safety",
        "AC-008": "evidence_references_contract",
        "AC-009": "write_conflict_policy_contract",
        "AC-010": "write_conflict_policy_contract",
    }


def test_rust_verifier_fixture_coverage_accepts_valid_directory_and_granular_invalid_names(tmp_path):
    fixture_text = (
        "Invalid fixtures cover missing manifest fields, duplicate evidence_id, "
        "missing required wiki dirs, missing evidence references, and unsafe target paths."
    )
    workspace = make_workspace(
        tmp_path,
        job_id="acceptance-codexarium-fixture-coverage",
        criteria=[
            criterion(
                "AC-FIXTURES",
                verifier_check_id=None,
                description=fixture_text,
                pass_condition=fixture_text,
                required_evidence=[fixture_text],
                evidence_kind="verifier_check",
            )
        ],
    )
    write_workspace_text(workspace, "package/verifier/tests/fixtures/valid/basic_entry.json", "{}\n")
    write_workspace_text(
        workspace,
        "package/verifier/tests/fixtures/invalid/missing_evidence_references.json",
        "missing evidence references; allowed_use; sensitivity\n",
    )
    write_workspace_text(
        workspace,
        "package/verifier/tests/fixtures/invalid/missing_required_wiki_dirs.json",
        "missing taxonomy directory; full fixed taxonomy\n",
    )
    write_workspace_text(
        workspace,
        "package/verifier/tests/fixtures/invalid/missing_manifest_field.json",
        "missing required manifest field\n",
    )
    write_workspace_text(
        workspace,
        "package/verifier/tests/fixtures/invalid/duplicate_evidence_id.json",
        "duplicate evidence_id\n",
    )
    write_workspace_text(
        workspace,
        "package/verifier/tests/fixtures/invalid/unsafe_target_path.json",
        "illegal slug path traversal target escape\n",
    )
    write_workspace_text(
        workspace,
        "package/verifier/tests/fixtures.rs",
        "missing required manifest field duplicate evidence_id missing evidence references missing taxonomy directory illegal slug path traversal target escape allowed_use sensitivity\n",
    )
    write_fake_codexarium_verification_result(workspace)

    plan, result = plan_and_evaluate(workspace)

    assert plan.items[0].verifier_check_id == "rust_verifier_fixture_coverage"
    assert result.passed is True
    assert result_item(result, "AC-FIXTURES").status == "covered/pass"


def test_good_skill_with_qa_and_verifier_evidence_passes_must_criteria(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-good",
        criteria=[
            criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present"),
            criterion(
                "AC-QA",
                evidence_kind="qa_report",
                verifier_check_id=None,
                required_evidence=["workflow_actionability"],
            ),
        ],
    )

    _plan, result = plan_and_evaluate(workspace)
    payload = read_json(workspace, ACCEPTANCE_COVERAGE_RESULT_REF)

    assert result.passed is True
    assert payload["passed"] is True
    assert payload["must_total"] == 2
    assert payload["must_passed"] == 2
    assert all(item.status == "covered/pass" for item in result.items)


def test_bad_skill_fails_mapped_must_criterion(tmp_path):
    workspace, _verification, qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-bad",
        skill_md=WEAK_SKILL_MD,
        criteria=[
            criterion(
                "AC-QA-WORKFLOW",
                evidence_kind="qa_report",
                verifier_check_id=None,
                required_evidence=["workflow_actionability"],
            )
        ],
    )
    assert qa.passed is False

    _plan, result = plan_and_evaluate(workspace)

    assert result.passed is False
    assert result.must_failed == 1
    item = result_item(result, "AC-QA-WORKFLOW")
    assert item.status == "covered/fail"
    assert item.passed is False


def test_uncovered_must_criterion_fails_overall(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-uncovered",
        criteria=[
            criterion(
                "AC-UNCOVERED",
                verifier_check_id=None,
                coverage_status="uncovered",
                unverifiable_reason="no deterministic artifact exists",
            )
        ],
    )

    _plan, result = plan_and_evaluate(workspace)

    assert result.passed is False
    assert result_item(result, "AC-UNCOVERED").status == "uncovered"


def test_manual_only_must_criterion_requires_manual_authority_metadata(tmp_path):
    missing_authority, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-manual-missing",
        criteria=[
            criterion(
                "AC-MANUAL",
                test_method="manual_check",
                evidence_kind="human_note",
                verifier_check_id=None,
            )
        ],
    )
    _plan, missing_result = plan_and_evaluate(missing_authority)

    assert missing_result.passed is False
    assert result_item(missing_result, "AC-MANUAL").status == "uncovered"

    with_authority, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-manual-present",
        criteria=[
            criterion(
                "AC-MANUAL",
                test_method="manual_check",
                evidence_kind="human_note",
                verifier_check_id=None,
                manual_authority="human-qa-lead",
            )
        ],
    )
    _plan, present_result = plan_and_evaluate(with_authority)

    assert present_result.passed is False
    assert result_item(present_result, "AC-MANUAL").status == "uncovered"

    write_manual_acceptance_record(with_authority, ["AC-MANUAL"])
    _plan, approved_result = plan_and_evaluate(with_authority)

    assert approved_result.passed is True
    assert approved_result.must_manual_only == 1
    assert result_item(approved_result, "AC-MANUAL").status == "manual_only"
    assert result_item(approved_result, "AC-MANUAL").evidence_refs == ["qa/manual_acceptance_record.json"]


def test_llm_only_must_criterion_cannot_be_registry_approved(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-llm-only",
        criteria=[
            criterion(
                "AC-LLM",
                test_method="llm_judge",
                evidence_kind="model_judge",
                verifier_check_id=None,
                required_evidence=["model_judge"],
            )
        ],
    )
    _plan, result = plan_and_evaluate(workspace)
    assert result.passed is False

    registry = LocalSkillRegistry(tmp_path / "registry.json")
    with pytest.raises(RegistryGateError) as exc_info:
        registry.add_verified(workspace, version="1.0.0")

    assert any("acceptance_coverage_result.passed" in failure for failure in exc_info.value.failures)


def test_qa_lab_report_includes_acceptance_coverage_summary_when_result_exists(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-qa-summary",
        criteria=[criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present")],
    )
    _plan, coverage = plan_and_evaluate(workspace)

    qa_result = QALab().evaluate(workspace)
    report = read_json(workspace, "qa/quality_report.json")

    assert qa_result.report["acceptance_coverage"]["result_id"] == coverage.result_id
    assert report["acceptance_coverage"]["passed"] is True
    assert report["acceptance_coverage"]["ref"] == ACCEPTANCE_COVERAGE_RESULT_REF
    assert report["acceptance_coverage"]["sha256"] == sha256_file(
        workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF, must_exist=True)
    )


def test_registry_rejects_missing_or_failed_coverage_result_when_acceptance_exists(tmp_path):
    missing = make_workspace(
        tmp_path,
        job_id="acceptance-registry-missing",
        criteria=[criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present")],
    )
    Verifier().verify(missing)
    QALab().evaluate(missing)
    registry = LocalSkillRegistry(tmp_path / "registry-missing.json")

    with pytest.raises(RegistryGateError) as missing_exc:
        registry.add_verified(missing, version="1.0.0")
    assert any("acceptance_coverage_result" in failure for failure in missing_exc.value.failures)

    failed, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-registry-failed",
        criteria=[
            criterion(
                "AC-UNCOVERED",
                verifier_check_id=None,
                coverage_status="uncovered",
                unverifiable_reason="no deterministic artifact exists",
            )
        ],
    )
    _plan, failed_result = plan_and_evaluate(failed)
    assert failed_result.passed is False

    with pytest.raises(RegistryGateError) as failed_exc:
        LocalSkillRegistry(tmp_path / "registry-failed.json").add_verified(failed, version="1.0.0")
    assert any("acceptance_coverage_result.passed" in failure for failure in failed_exc.value.failures)


def test_registry_accepts_passed_coverage_result_and_stores_hash_provenance(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-registry-pass",
        criteria=[criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present")],
    )
    _plan, coverage = plan_and_evaluate(workspace)
    registry = LocalSkillRegistry(tmp_path / "registry-pass.json")

    entry = registry.add_verified(workspace, version="1.0.0")
    provenance = entry.provenance["acceptance_coverage_result"]

    assert coverage.passed is True
    assert provenance["ref"] == ACCEPTANCE_COVERAGE_RESULT_REF
    assert provenance["passed"] is True
    assert provenance["result_id"] == coverage.result_id
    assert provenance["sha256"] == sha256_file(workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF, must_exist=True))
    assert registry.verify_entry(entry).valid is True


def test_registry_verifies_manual_acceptance_record_for_manual_only_must_criteria(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-registry-manual",
        criteria=[
            criterion(
                "AC-MANUAL",
                test_method="manual_check",
                evidence_kind="human_note",
                verifier_check_id=None,
                manual_authority="human-qa-lead",
            )
        ],
    )
    write_manual_acceptance_record(workspace, ["AC-MANUAL"])
    _plan, coverage = plan_and_evaluate(workspace)
    assert coverage.passed is True

    registry = LocalSkillRegistry(tmp_path / "registry-manual.json")
    entry = registry.add_verified(workspace, version="1.0.0")
    provenance = entry.provenance["acceptance_coverage_result"]["provenance"]["manual_acceptance_record"]
    assert provenance["ref"] == "qa/manual_acceptance_record.json"
    assert provenance["sha256"] == sha256_file(workspace.resolve_path("qa/manual_acceptance_record.json", must_exist=True))
    assert registry.verify_entry(entry).valid is True

    record_path = workspace.resolve_path("qa/manual_acceptance_record.json", must_exist=True)
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["decision"] = "rejected"
    record_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    report = registry.verify_entry(entry)

    assert report.valid is False
    assert any("manual_acceptance_record_hash" in failure for failure in report.failures)
    assert any("manual_acceptance_record.decision" in failure for failure in report.failures)


def test_registry_verify_fails_after_acceptance_coverage_result_tampering(tmp_path):
    workspace, _verification, _qa = make_verified_qa_workspace(
        tmp_path,
        job_id="acceptance-registry-tamper",
        criteria=[criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present")],
    )
    _plan, _coverage = plan_and_evaluate(workspace)
    registry = LocalSkillRegistry(tmp_path / "registry-tamper.json")
    entry = registry.add_verified(workspace, version="1.0.0")

    result_path = workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF, must_exist=True)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["passed"] = False
    result_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    report = registry.verify_entry(entry)

    assert report.valid is False
    assert any("acceptance_coverage_result_hash" in failure for failure in report.failures)
    assert any("acceptance_coverage_result.passed" in failure for failure in report.failures)
