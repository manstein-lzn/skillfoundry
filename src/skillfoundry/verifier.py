"""WP4 independent verifier for SkillFoundry package workspaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from contextforge import ContextLedger

from .schema import (
    ArtifactManifest,
    ExecutionReport,
    JsonValue,
    VerificationResult,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
)
from .security import PathSecurityError, assert_under_root, validate_relative_path
from .workspace import JobWorkspace, LockedInputTamperError


VERIFIER_VERSION = "skillfoundry.verifier.wp4.v1"

DEFAULT_REQUIRED_SKILL_SECTIONS = (
    "Overview",
    "When To Use",
    "When Not To Use",
    "Inputs",
    "Outputs",
    "Workflow",
    "Safety",
)

_ZERO_HASH = "0" * 64
_CONTEXTFORGE_LEDGER_REF = "contextforge/ledger.sqlite3"
_CONTEXTFORGE_STATE_REF = "contextforge/goal_harness_state.json"
_RAW_FRONTDESK_CONVERSATION_REF = "frontdesk/conversation.jsonl"
_RAW_FRONTDESK_CONTEXT_ITEM_SUFFIX = ":raw_frontdesk_conversation"
_RAW_FRONTDESK_EXCLUSION_CHECK = "contextforge_raw_frontdesk_conversation_excluded"
_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class VerifierCheck:
    """Machine-readable verifier check record."""

    name: str
    passed: bool
    severity: str
    message: str
    evidence_ref: str

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "name": self.name,
                "passed": self.passed,
                "severity": self.severity,
                "message": self.message,
                "evidence_ref": self.evidence_ref,
            }
        )  # type: ignore[return-value]


@dataclass(frozen=True)
class _ExecutionReportEvidence:
    report: ExecutionReport | None
    ref: str | None
    created_at: str | None


class Verifier:
    """Deterministic local verifier for worker-produced Skill packages.

    ``ExecutionReport`` success is required evidence, but it is not acceptance.
    The package must independently pass manifest, static, path, hash, and smoke
    checks before the returned ``VerificationResult`` can pass.
    """

    def __init__(
        self,
        *,
        verifier_version: str = VERIFIER_VERSION,
        required_sections: tuple[str, ...] | list[str] = DEFAULT_REQUIRED_SKILL_SECTIONS,
        expected_package_hash: str | None = None,
        smoke_pass: bool | None = None,
        llm_judge_passed: bool | None = None,
        llm_judge_ref: str | None = None,
    ) -> None:
        self.verifier_version = verifier_version
        self.required_sections = tuple(required_sections)
        self.expected_package_hash = expected_package_hash
        self.smoke_pass = smoke_pass
        self.llm_judge_passed = llm_judge_passed
        self.llm_judge_ref = llm_judge_ref

    def verify(self, workspace: JobWorkspace, *, attempt_id: str | None = None) -> VerificationResult:
        """Verify ``workspace/package`` and write ``verifier/verification_result.json``."""

        verifier_dir = workspace.resolve_path("verifier", must_exist=True)
        package_ref = "package"
        package_hash, package_errors = _hash_package(workspace)
        verification_spec_hash = _hash_workspace_file(workspace, "verification_spec.yaml")
        checks: list[VerifierCheck] = []

        manifest = self._read_manifest(workspace, checks)
        self._check_locked_inputs(workspace, checks, manifest)
        self._check_manifest_paths_and_hashes(workspace, checks, manifest)

        report_evidence = self._check_execution_report(workspace, checks, attempt_id=attempt_id)
        static_evidence = self._check_static_package(workspace, checks)
        self._check_package_paths(workspace, checks, package_errors)
        self._check_declared_reference_paths(workspace, checks, static_evidence.skill_text)
        self._check_contextforge_raw_frontdesk_exclusion(workspace, checks)
        self._check_package_hash(checks, package_hash)
        self._check_sandbox_smoke(workspace, checks)
        llm_ref = self._record_llm_judge_signal(workspace, checks)

        created_at = report_evidence.created_at
        if created_at is None and manifest is not None:
            created_at = manifest.created_at
        if created_at is None:
            created_at = "1970-01-01T00:00:00Z"

        check_dicts = [check.to_dict() for check in checks]
        failed_primary = [check for check in checks if check.severity == "error" and not check.passed]
        failures = [f"{check.name}: {check.message}" for check in failed_primary]
        passed = not failed_primary

        static_report_ref = "verifier/static_report.json"
        sandbox_log_ref = "verifier/sandbox.log"
        evidence_refs = _dedupe_refs(
            [
                "artifact_manifest.json" if manifest is not None else None,
                "verification_spec.yaml",
                package_ref,
                static_report_ref,
                sandbox_log_ref,
                report_evidence.ref,
                llm_ref,
                *[str(check.evidence_ref) for check in checks if check.evidence_ref],
            ]
        )

        result_id = _result_id(
            job_id=workspace.job_id,
            package_hash=package_hash,
            verification_spec_hash=verification_spec_hash,
            checks=check_dicts,
            attempt_ref=report_evidence.ref,
            verifier_version=self.verifier_version,
        )
        result = VerificationResult(
            result_id=result_id,
            job_id=workspace.job_id,
            package_hash=package_hash,
            verification_spec_hash=verification_spec_hash,
            passed=passed,
            checks=check_dicts,
            failures=failures,
            evidence_refs=evidence_refs,
            verifier_version=self.verifier_version,
            created_at=created_at,
            llm_judge_ref=llm_ref,
        )
        result.validate()

        _write_json(
            verifier_dir / "static_report.json",
            {
                "schema_version": "skillfoundry.verifier.static_report.v1",
                "job_id": workspace.job_id,
                "package_hash": package_hash,
                "verification_spec_hash": verification_spec_hash,
                "passed": passed,
                "checks": check_dicts,
                "failures": failures,
                "evidence_refs": evidence_refs,
                "verifier_version": self.verifier_version,
                "created_at": created_at,
            },
        )
        (verifier_dir / "sandbox.log").write_text(_sandbox_log_text(checks), encoding="utf-8")
        result.write_json_file(verifier_dir / "verification_result.json")
        return result

    def _read_manifest(self, workspace: JobWorkspace, checks: list[VerifierCheck]) -> ArtifactManifest | None:
        try:
            manifest = workspace.read_manifest()
        except Exception as exc:
            checks.append(
                _check(
                    "artifact_manifest_present",
                    False,
                    f"artifact_manifest.json is missing or invalid: {exc}",
                    "artifact_manifest.json",
                )
            )
            return None

        checks.append(
            _check(
                "artifact_manifest_present",
                True,
                "artifact_manifest.json exists and validates as an ArtifactManifest",
                "artifact_manifest.json",
            )
        )
        if manifest.job_id == workspace.job_id:
            checks.append(
                _check(
                    "artifact_manifest_job_id",
                    True,
                    "artifact manifest job_id matches workspace",
                    "artifact_manifest.json",
                )
            )
        else:
            checks.append(
                _check(
                    "artifact_manifest_job_id",
                    False,
                    f"artifact manifest job_id {manifest.job_id!r} does not match workspace {workspace.job_id!r}",
                    "artifact_manifest.json",
                )
            )
        return manifest

    def _check_locked_inputs(
        self,
        workspace: JobWorkspace,
        checks: list[VerifierCheck],
        manifest: ArtifactManifest | None,
    ) -> None:
        if manifest is None:
            checks.append(
                _check(
                    "locked_input_integrity",
                    False,
                    "locked inputs cannot be checked without artifact_manifest.json",
                    "artifact_manifest.json",
                )
            )
            return
        try:
            workspace.check_locked_inputs()
        except LockedInputTamperError as exc:
            checks.append(_check("locked_input_integrity", False, str(exc), "artifact_manifest.json"))
        except Exception as exc:
            checks.append(
                _check(
                    "locked_input_integrity",
                    False,
                    f"locked input check failed: {type(exc).__name__}: {exc}",
                    "artifact_manifest.json",
                )
            )
        else:
            checks.append(
                _check(
                    "locked_input_integrity",
                    True,
                    "all locked manifest records exist and match their hashes",
                    "artifact_manifest.json",
                )
            )

    def _check_manifest_paths_and_hashes(
        self,
        workspace: JobWorkspace,
        checks: list[VerifierCheck],
        manifest: ArtifactManifest | None,
    ) -> None:
        if manifest is None:
            checks.append(
                _check(
                    "artifact_manifest_hashes",
                    False,
                    "manifest artifact hashes cannot be checked without artifact_manifest.json",
                    "artifact_manifest.json",
                )
            )
            return

        failures: list[str] = []
        seen_paths: set[str] = set()
        for record in manifest.artifacts:
            if record.path in seen_paths:
                failures.append(f"{record.path}: duplicate artifact path")
                continue
            seen_paths.add(record.path)
            try:
                path = workspace.resolve_path(record.path, must_exist=True)
            except Exception as exc:
                failures.append(f"{record.path}: {exc}")
                continue
            if not path.is_file():
                failures.append(f"{record.path}: manifest record does not point to a file")
                continue
            actual_hash = sha256_file(path)
            if actual_hash != record.sha256:
                failures.append(f"{record.path}: expected {record.sha256}, got {actual_hash}")

        if failures:
            checks.append(
                _check(
                    "artifact_manifest_hashes",
                    False,
                    "; ".join(failures),
                    "artifact_manifest.json",
                )
            )
        else:
            checks.append(
                _check(
                    "artifact_manifest_hashes",
                    True,
                    "all manifest artifact paths are confined files with matching hashes",
                    "artifact_manifest.json",
                )
            )

    def _check_execution_report(
        self,
        workspace: JobWorkspace,
        checks: list[VerifierCheck],
        *,
        attempt_id: str | None,
    ) -> _ExecutionReportEvidence:
        report_ref = _execution_report_ref(workspace, attempt_id)
        if report_ref is None:
            checks.append(
                _check(
                    "execution_report_present",
                    False,
                    "no attempt execution_report.json was found",
                    "attempts",
                )
            )
            checks.append(
                _check(
                    "execution_report_success",
                    False,
                    "execution report success cannot be checked without a valid report",
                    "attempts",
                )
            )
            return _ExecutionReportEvidence(report=None, ref=None, created_at=None)

        try:
            report = ExecutionReport.read_json_file(workspace.resolve_path(report_ref, must_exist=True))
        except Exception as exc:
            checks.append(
                _check(
                    "execution_report_present",
                    False,
                    f"execution report is missing or invalid: {exc}",
                    report_ref,
                )
            )
            checks.append(
                _check(
                    "execution_report_success",
                    False,
                    "execution report success cannot be checked without a valid report",
                    report_ref,
                )
            )
            return _ExecutionReportEvidence(report=None, ref=report_ref, created_at=None)

        identity_failures: list[str] = []
        if report.job_id != workspace.job_id:
            identity_failures.append(f"job_id {report.job_id!r} does not match workspace {workspace.job_id!r}")
        if attempt_id is not None and report.attempt_id != attempt_id:
            identity_failures.append(f"attempt_id {report.attempt_id!r} does not match requested {attempt_id!r}")
        if identity_failures:
            checks.append(
                _check(
                    "execution_report_present",
                    False,
                    "; ".join(identity_failures),
                    report_ref,
                )
            )
        else:
            checks.append(
                _check(
                    "execution_report_present",
                    True,
                    "execution report exists, validates, and matches workspace identity",
                    report_ref,
                )
            )

        success = report.status == "completed" and report.exit_status == "success"
        if success:
            checks.append(
                _check(
                    "execution_report_success",
                    True,
                    "worker reported completed/success; verifier still applies independent gates",
                    report_ref,
                )
            )
        else:
            checks.append(
                _check(
                    "execution_report_success",
                    False,
                    f"worker report status={report.status!r} exit_status={report.exit_status!r}",
                    report_ref,
                )
            )
        return _ExecutionReportEvidence(report=report, ref=report_ref, created_at=report.finished_at)

    def _check_static_package(self, workspace: JobWorkspace, checks: list[VerifierCheck]) -> "_StaticEvidence":
        skill_ref = "package/SKILL.md"
        try:
            skill_path = workspace.resolve_path(skill_ref, must_exist=True)
            skill_text = skill_path.read_text(encoding="utf-8")
        except Exception as exc:
            checks.append(_check("package_skill_md_present", False, f"package/SKILL.md is missing: {exc}", skill_ref))
            for section in self.required_sections:
                checks.append(
                    _check(
                        "skill_required_section",
                        False,
                        f"required section is missing because SKILL.md is unavailable: {section}",
                        skill_ref,
                    )
                )
            return _StaticEvidence(skill_text=None, sections={})

        checks.append(_check("package_skill_md_present", True, "package/SKILL.md exists and is readable", skill_ref))
        headings, sections = _parse_markdown_sections(skill_text)
        if any(level == 1 and title.strip() for level, title in headings):
            checks.append(_check("skill_title_heading", True, "SKILL.md contains a top-level title", skill_ref))
        else:
            checks.append(_check("skill_title_heading", False, "SKILL.md is missing a top-level title", skill_ref))

        normalized_sections = {key: value for key, value in sections.items()}
        for section in self.required_sections:
            normalized = _normalize_heading(section)
            content = normalized_sections.get(normalized)
            if content and _has_section_body(content):
                checks.append(
                    _check(
                        "skill_required_section",
                        True,
                        f"required section is present with body content: {section}",
                        skill_ref,
                    )
                )
            elif content is not None:
                checks.append(
                    _check(
                        "skill_required_section",
                        False,
                        f"required section has no body content: {section}",
                        skill_ref,
                    )
                )
            else:
                checks.append(
                    _check(
                        "skill_required_section",
                        False,
                        f"required section is missing: {section}",
                        skill_ref,
                    )
                )

        _section_fixture_check(
            checks,
            name="trigger_fixture_coverage",
            section="When To Use",
            sections=sections,
            evidence_ref=skill_ref,
            message="When To Use section provides trigger fixture coverage",
        )
        _section_fixture_check(
            checks,
            name="non_trigger_fixture_coverage",
            section="When Not To Use",
            sections=sections,
            evidence_ref=skill_ref,
            message="When Not To Use section provides non-trigger fixture coverage",
        )
        _section_fixture_check(
            checks,
            name="required_input_fixture_coverage",
            section="Inputs",
            sections=sections,
            evidence_ref=skill_ref,
            message="Inputs section provides required input fixture coverage",
        )
        _section_fixture_check(
            checks,
            name="expected_output_fixture_coverage",
            section="Outputs",
            sections=sections,
            evidence_ref=skill_ref,
            message="Outputs section provides expected output fixture coverage",
        )
        return _StaticEvidence(skill_text=skill_text, sections=sections)

    def _check_package_paths(
        self,
        workspace: JobWorkspace,
        checks: list[VerifierCheck],
        package_errors: list[str],
    ) -> None:
        failures = list(package_errors)
        try:
            package_dir = workspace.resolve_path("package", must_exist=True)
        except Exception as exc:
            failures.append(f"package: {exc}")
            package_dir = None

        if package_dir is not None:
            for path in sorted(package_dir.rglob("*")):
                try:
                    relative = path.relative_to(workspace.root.resolve(strict=True)).as_posix()
                    validate_relative_path(relative)
                    if not relative == "package" and not relative.startswith("package/"):
                        failures.append(f"{relative}: package traversal escaped package/")
                    if path.is_symlink():
                        failures.append(f"{relative}: symlink components are not allowed in package")
                        continue
                    resolved = path.resolve(strict=True)
                    assert_under_root(workspace.root, resolved)
                    assert_under_root(package_dir, resolved)
                except Exception as exc:
                    failures.append(f"{path}: {exc}")

        if failures:
            checks.append(_check("package_path_confinement", False, "; ".join(failures), "package"))
        else:
            checks.append(
                _check(
                    "package_path_confinement",
                    True,
                    "package tree contains no escaping paths or symlink components",
                    "package",
                )
            )

    def _check_declared_reference_paths(
        self,
        workspace: JobWorkspace,
        checks: list[VerifierCheck],
        skill_text: str | None,
    ) -> None:
        if skill_text is None:
            checks.append(
                _check(
                    "package_declared_path_safety",
                    False,
                    "declared reference/script paths cannot be checked without SKILL.md",
                    "package/SKILL.md",
                )
            )
            return

        frontmatter_error = _frontmatter_error(skill_text)
        if frontmatter_error is not None:
            checks.append(
                _check(
                    "skill_frontmatter_parse",
                    False,
                    f"SKILL.md frontmatter is invalid YAML: {frontmatter_error}",
                    "package/SKILL.md",
                )
            )
            return

        declared_paths = _extract_declared_paths(skill_text)
        failures: list[str] = []
        for declared_path in sorted(declared_paths):
            if _is_ignored_markdown_target(declared_path):
                continue
            package_relative = _package_relative_declared_path(declared_path)
            try:
                safe_path = validate_relative_path(package_relative)
            except PathSecurityError as exc:
                failures.append(f"{declared_path}: {exc}")
                continue
            if safe_path.parts and safe_path.parts[0] in {"references", "scripts"}:
                try:
                    workspace.resolve_path(f"package/{safe_path.as_posix()}", must_exist=True)
                except Exception as exc:
                    failures.append(f"{declared_path}: referenced package path is missing or unsafe: {exc}")

        if failures:
            checks.append(
                _check(
                    "package_declared_path_safety",
                    False,
                    "; ".join(failures),
                    "package/SKILL.md",
                )
            )
        else:
            checks.append(
                _check(
                    "package_declared_path_safety",
                    True,
                    "declared local reference/script paths are relative and confined",
                    "package/SKILL.md",
                )
            )

    def _check_contextforge_raw_frontdesk_exclusion(
        self,
        workspace: JobWorkspace,
        checks: list[VerifierCheck],
    ) -> None:
        """Verify raw Front Desk conversation stayed out of build-visible context."""

        raw_path = workspace.root.joinpath(*validate_relative_path(_RAW_FRONTDESK_CONVERSATION_REF).parts)
        if not raw_path.is_file():
            checks.append(
                _check(
                    _RAW_FRONTDESK_EXCLUSION_CHECK,
                    True,
                    "no raw Front Desk conversation artifact exists for this workspace",
                    _RAW_FRONTDESK_CONVERSATION_REF,
                )
            )
            return
        try:
            raw_path = workspace.resolve_path(_RAW_FRONTDESK_CONVERSATION_REF, must_exist=True)
        except Exception as exc:
            checks.append(
                _check(
                    _RAW_FRONTDESK_EXCLUSION_CHECK,
                    False,
                    f"raw Front Desk conversation artifact is present but unsafe: {exc}",
                    _RAW_FRONTDESK_CONVERSATION_REF,
                )
            )
            return

        state_ref = _CONTEXTFORGE_STATE_REF
        ledger_ref = _CONTEXTFORGE_LEDGER_REF
        try:
            state_payload = json.loads(workspace.resolve_path(state_ref, must_exist=True).read_text(encoding="utf-8"))
        except Exception as exc:
            checks.append(
                _check(
                    _RAW_FRONTDESK_EXCLUSION_CHECK,
                    False,
                    f"raw Front Desk conversation exists but ContextForge build state is missing or invalid: {exc}",
                    state_ref,
                )
            )
            return

        contextforge_state = state_payload.get("contextforge") if isinstance(state_payload, dict) else None
        context_view_id = (
            contextforge_state.get("last_context_view_id") if isinstance(contextforge_state, dict) else None
        )
        if not isinstance(context_view_id, str) or not context_view_id.strip():
            checks.append(
                _check(
                    _RAW_FRONTDESK_EXCLUSION_CHECK,
                    False,
                    "ContextForge build state does not reference last_context_view_id",
                    state_ref,
                )
            )
            return

        ledger_path = workspace.root.joinpath(*validate_relative_path(ledger_ref).parts)
        if not ledger_path.is_file():
            checks.append(
                _check(
                    _RAW_FRONTDESK_EXCLUSION_CHECK,
                    False,
                    "raw Front Desk conversation exists but ContextForge ledger is missing",
                    ledger_ref,
                )
            )
            return
        try:
            ledger_path = workspace.resolve_path(ledger_ref, must_exist=True)
        except Exception as exc:
            checks.append(
                _check(
                    _RAW_FRONTDESK_EXCLUSION_CHECK,
                    False,
                    f"ContextForge ledger path is present but unsafe: {exc}",
                    ledger_ref,
                )
            )
            return

        expected_item_id = f"{workspace.job_id}{_RAW_FRONTDESK_CONTEXT_ITEM_SUFFIX}"
        failures: list[str] = []
        try:
            ledger = ContextLedger.connect(ledger_path)
            try:
                context_view = ledger.get_context_view(context_view_id)
                prompt_view_id = context_view.prompt_view_id
                prompt_view = None
                prompt_blocks = []
                if prompt_view_id:
                    prompt_view, prompt_blocks = ledger.get_prompt_view(prompt_view_id)
            finally:
                ledger.close()
        except Exception as exc:
            checks.append(
                _check(
                    _RAW_FRONTDESK_EXCLUSION_CHECK,
                    False,
                    f"ContextForge raw conversation exclusion evidence could not be loaded: {exc}",
                    ledger_ref,
                )
            )
            return

        included = set(context_view.included_item_ids)
        forbidden = set(context_view.forbidden_item_ids)
        if expected_item_id not in forbidden:
            failures.append(f"{expected_item_id} was not recorded as forbidden")
        if expected_item_id in included:
            failures.append(f"{expected_item_id} entered ContextView.included_item_ids")
        if prompt_view is None:
            failures.append("ContextView does not reference a PromptView")
        else:
            prompt_source_ids = set(prompt_view.source_item_ids)
            if expected_item_id in prompt_source_ids:
                failures.append(f"{expected_item_id} entered PromptView.source_item_ids")
            if any(expected_item_id in block.source_item_ids for block in prompt_blocks):
                failures.append(f"{expected_item_id} entered PromptBlock.source_item_ids")
            raw_content = raw_path.read_text(encoding="utf-8").strip()
            if raw_content:
                prompt_text = "\n".join(
                    [
                        *(message.content for message in prompt_view.messages),
                        *(block.content for block in prompt_blocks),
                    ]
                )
                if raw_content in prompt_text:
                    failures.append("raw Front Desk conversation bytes appeared in rendered prompt evidence")

        if failures:
            checks.append(_check(_RAW_FRONTDESK_EXCLUSION_CHECK, False, "; ".join(failures), ledger_ref))
        else:
            checks.append(
                _check(
                    _RAW_FRONTDESK_EXCLUSION_CHECK,
                    True,
                    "raw Front Desk conversation was forbidden and absent from build PromptView evidence",
                    ledger_ref,
                )
            )

    def _check_package_hash(self, checks: list[VerifierCheck], package_hash: str) -> None:
        if self.expected_package_hash is None:
            checks.append(
                _check(
                    "package_hash_recorded",
                    True,
                    f"package hash recorded as {package_hash}",
                    "package",
                )
            )
            return

        if self.expected_package_hash == package_hash:
            checks.append(
                _check(
                    "expected_package_hash",
                    True,
                    "package hash matches expected verifier input",
                    "package",
                )
            )
        else:
            checks.append(
                _check(
                    "expected_package_hash",
                    False,
                    f"expected {self.expected_package_hash}, got {package_hash}",
                    "package",
                )
            )

    def _check_sandbox_smoke(self, workspace: JobWorkspace, checks: list[VerifierCheck]) -> None:
        fixture_ref = "package/tests/smoke.fail"
        fixture_path = workspace.resolve_path(fixture_ref)
        if self.smoke_pass is False:
            checks.append(
                _check(
                    "sandbox_smoke",
                    False,
                    "deterministic smoke fixture forced failure; no untrusted scripts were executed",
                    fixture_ref,
                )
            )
        elif fixture_path.exists():
            checks.append(
                _check(
                    "sandbox_smoke",
                    False,
                    "package/tests/smoke.fail requested deterministic smoke failure; no scripts were executed",
                    fixture_ref,
                )
            )
        else:
            checks.append(
                _check(
                    "sandbox_smoke",
                    True,
                    "deterministic smoke placeholder found no failure fixture; no untrusted scripts were executed",
                    "verifier/sandbox.log",
                )
            )

    def _record_llm_judge_signal(self, workspace: JobWorkspace, checks: list[VerifierCheck]) -> str | None:
        if self.llm_judge_passed is None and self.llm_judge_ref is None:
            return None

        llm_ref = self.llm_judge_ref or "verifier/llm_judge_signal.json"
        if self.llm_judge_ref is None:
            _write_json(
                workspace.resolve_path(llm_ref),
                {
                    "schema_version": "skillfoundry.verifier.llm_judge_signal.v1",
                    "passed": bool(self.llm_judge_passed),
                    "source": "deterministic verifier fixture",
                    "primary_gate": False,
                },
            )

        checks.append(
            VerifierCheck(
                name="llm_judge_signal",
                passed=bool(self.llm_judge_passed),
                severity="info",
                message="LLM judge signal is advisory only and cannot override primary verifier gates",
                evidence_ref=llm_ref,
            )
        )
        return llm_ref


def _frontmatter_error(skill_text: str) -> str | None:
    if not skill_text.startswith("---\n"):
        return None
    end = skill_text.find("\n---", 4)
    if end == -1:
        return "closing frontmatter delimiter is missing"
    try:
        yaml.safe_load(skill_text[4:end])
    except yaml.YAMLError as exc:
        return str(exc)
    return None


@dataclass(frozen=True)
class _StaticEvidence:
    skill_text: str | None
    sections: dict[str, str]


def _hash_workspace_file(workspace: JobWorkspace, relative_path: str) -> str:
    try:
        return sha256_file(workspace.resolve_path(relative_path, must_exist=True))
    except Exception:
        return _ZERO_HASH


def _hash_package(workspace: JobWorkspace) -> tuple[str, list[str]]:
    try:
        package_dir = workspace.resolve_path("package", must_exist=True)
    except Exception as exc:
        return sha256_json({"package": "missing", "error": str(exc)}), [f"package: {exc}"]

    entries: list[dict[str, JsonValue]] = []
    failures: list[str] = []
    for path in sorted(package_dir.rglob("*")):
        try:
            relative = path.relative_to(package_dir).as_posix()
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


def _check(name: str, passed: bool, message: str, evidence_ref: str) -> VerifierCheck:
    return VerifierCheck(name=name, passed=passed, severity="error", message=message, evidence_ref=evidence_ref)


def _execution_report_ref(workspace: JobWorkspace, attempt_id: str | None) -> str | None:
    if attempt_id is not None:
        return f"attempts/{attempt_id}/execution_report.json"

    attempts_dir = workspace.resolve_path("attempts", must_exist=True)
    candidates: list[tuple[int, str, str]] = []
    for child in attempts_dir.iterdir():
        if not child.is_dir() or not child.name.isdecimal():
            continue
        report = child / "execution_report.json"
        if report.exists():
            candidates.append((int(child.name), child.name, f"attempts/{child.name}/execution_report.json"))
    if not candidates:
        return None
    return sorted(candidates)[-1][2]


def _parse_markdown_sections(text: str) -> tuple[list[tuple[int, str]], dict[str, str]]:
    headings: list[tuple[int, str]] = []
    section_lines: dict[str, list[str]] = {}
    current_section: str | None = None
    current_level: int | None = None

    for line in text.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            level = len(match.group("level"))
            title = match.group("title").strip()
            headings.append((level, title))
            if level == 2:
                current_section = _normalize_heading(title)
                current_level = level
                section_lines.setdefault(current_section, [])
            elif current_level is not None and level <= current_level:
                current_section = None
                current_level = None
            continue
        if current_section is not None:
            section_lines[current_section].append(line)

    return headings, {key: "\n".join(value).strip() for key, value in section_lines.items()}


def _normalize_heading(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _has_section_body(content: str | None) -> bool:
    if not content:
        return False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("<!--"):
            return True
    return False


def _section_fixture_check(
    checks: list[VerifierCheck],
    *,
    name: str,
    section: str,
    sections: Mapping[str, str],
    evidence_ref: str,
    message: str,
) -> None:
    normalized = _normalize_heading(section)
    if _has_section_body(sections.get(normalized)):
        checks.append(_check(name, True, message, evidence_ref))
    else:
        checks.append(_check(name, False, f"{section} section is missing or empty", evidence_ref))


def _extract_declared_paths(skill_text: str) -> set[str]:
    declared: set[str] = set()
    for match in _MARKDOWN_LINK_RE.finditer(skill_text):
        declared.add(match.group("target").strip())

    frontmatter = _frontmatter_mapping(skill_text)
    for key, value in frontmatter.items():
        if _is_path_key(key):
            declared.update(_flatten_string_values(value))
    return declared


def _frontmatter_mapping(skill_text: str) -> dict[str, Any]:
    if not skill_text.startswith("---\n"):
        return {}
    end = skill_text.find("\n---", 4)
    if end == -1:
        return {}
    try:
        payload = yaml.safe_load(skill_text[4:end])
    except yaml.YAMLError:
        return {}
    if isinstance(payload, dict):
        return {str(key): value for key, value in payload.items()}
    return {}


def _is_path_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in {
        "reference",
        "references",
        "reference_material",
        "reference_materials",
        "script",
        "scripts",
        "script_path",
        "script_paths",
    }


def _flatten_string_values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_flatten_string_values(item))
        return result
    if isinstance(value, dict):
        result: set[str] = set()
        for item in value.values():
            result.update(_flatten_string_values(item))
        return result
    return set()


def _is_ignored_markdown_target(target: str) -> bool:
    if _WINDOWS_DRIVE_RE.match(target):
        return False
    return (
        target.startswith("#")
        or _URL_SCHEME_RE.match(target) is not None
        or target.startswith("mailto:")
        or target.startswith("data:")
    )


def _package_relative_declared_path(target: str) -> str:
    clean = target.split("#", 1)[0].split("?", 1)[0]
    if _WINDOWS_DRIVE_RE.match(clean):
        return clean
    clean = clean.replace("\\", "/")
    if clean.startswith("package/"):
        return clean[len("package/") :]
    return clean


def _dedupe_refs(values: list[str | None]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        refs.append(value)
        seen.add(value)
    return refs


def _result_id(
    *,
    job_id: str,
    package_hash: str,
    verification_spec_hash: str,
    checks: list[dict[str, JsonValue]],
    attempt_ref: str | None,
    verifier_version: str,
) -> str:
    digest = sha256_json(
        {
            "job_id": job_id,
            "package_hash": package_hash,
            "verification_spec_hash": verification_spec_hash,
            "checks": checks,
            "attempt_ref": attempt_ref,
            "verifier_version": verifier_version,
        }
    )
    return f"verification-{digest[:20]}"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    compatible = ensure_json_compatible(dict(payload))
    path.write_text(
        json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sandbox_log_text(checks: list[VerifierCheck]) -> str:
    smoke_checks = [check for check in checks if check.name == "sandbox_smoke"]
    lines = [
        "SkillFoundry WP4 sandbox smoke placeholder",
        "No package scripts were executed.",
    ]
    for check in smoke_checks:
        lines.append(f"passed={str(check.passed).lower()}")
        lines.append(f"message={check.message}")
    return "\n".join(lines) + "\n"
