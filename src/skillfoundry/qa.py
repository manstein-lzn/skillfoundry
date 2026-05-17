"""WP10 deterministic QA Lab for verifier-approved Skill packages."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from .schema import (
    ArtifactManifest,
    JsonValue,
    SkillSpec,
    VerificationResult,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .security import PathSecurityError, assert_under_root, validate_relative_path
from .workspace import JobWorkspace


QA_LAB_VERSION = "skillfoundry.qa.wp10.v1"
QA_REPORT_VERSION = "skillfoundry.qa.quality_report.v1"
QA_JUDGE_SIGNAL_VERSION = "skillfoundry.qa.judge_signal.v1"

HARD_CHECK_NAMES = (
    "verifier_passed",
    "trigger_fixture_coverage",
    "non_trigger_fixture_coverage",
    "io_contract_coverage",
    "workflow_actionability",
    "safety_actionability",
    "script_smoke",
)

_ZERO_HASH = "0" * 64
_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_LINE_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "when",
}

_GENERIC_QA_TERMS = {
    "all",
    "any",
    "careful",
    "data",
    "do",
    "done",
    "helpful",
    "input",
    "inputs",
    "needed",
    "otherwise",
    "output",
    "outputs",
    "process",
    "safe",
    "something",
    "stuff",
    "task",
    "thing",
    "things",
    "todo",
    "use",
    "useful",
    "work",
}

_SAFETY_MARKERS = (
    "avoid",
    "cannot",
    "confined",
    "credential",
    "credentials",
    "do not",
    "keep",
    "must",
    "network",
    "never",
    "no ",
    "path",
    "provider",
    "reject",
    "unsafe",
    "untrusted",
    "without",
)

_UNSAFE_SCRIPT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("subprocess", re.compile(r"\bsubprocess\b")),
    ("os_system", re.compile(r"\bos\.system\s*\(")),
    ("process_spawn", re.compile(r"\b(?:popen|spawn|execv|execve)\s*\(")),
    ("dynamic_eval", re.compile(r"\b(?:eval|exec)\s*\(")),
    ("network_socket", re.compile(r"\b(?:socket|http\.client|ftplib|paramiko)\b")),
    ("python_http_client", re.compile(r"\b(?:requests|urllib)\b")),
    ("shell_download", re.compile(r"\b(?:curl|wget|nc|netcat|ssh|scp)\b")),
    ("shell_interpreter", re.compile(r"\b(?:bash|sh|zsh|powershell)\s+-c\b")),
    ("destructive_shell", re.compile(r"\brm\s+-rf\b|\bdd\s+if=|\bmkfs\b|\bchmod\s+777\b|\bsudo\b")),
    ("dev_tcp", re.compile(r"/dev/tcp")),
)

_FAILURE_TAXONOMY = {
    "verifier_passed": (
        "verifier_gate_failure",
        "repair.verifier_gate",
        "Re-run the independent verifier and repair static, hash, path, or smoke failures before QA approval.",
    ),
    "trigger_fixture_coverage": (
        "trigger_fixture_missing",
        "repair.trigger_fixture_authoring",
        "Add concrete When To Use fixtures that represent the SkillSpec trigger scenarios.",
    ),
    "non_trigger_fixture_coverage": (
        "non_trigger_fixture_missing",
        "repair.non_trigger_fixture_authoring",
        "Add concrete When Not To Use fixtures that represent non-trigger scenarios and boundaries.",
    ),
    "io_contract_coverage": (
        "io_contract_missing",
        "repair.io_contract_authoring",
        "Describe concrete required inputs and expected outputs in the Inputs and Outputs sections.",
    ),
    "workflow_actionability": (
        "workflow_not_actionable",
        "repair.workflow_steps",
        "Rewrite the Workflow section as concrete, ordered steps a worker can execute.",
    ),
    "safety_actionability": (
        "safety_not_actionable",
        "repair.safety_constraints",
        "Add explicit safety constraints, rejected behaviors, path limits, or provider/network boundaries.",
    ),
    "script_smoke": (
        "script_smoke_failure",
        "repair.script_safety",
        "Keep declared scripts under package/scripts, make them exist, and remove unsafe process/network/shell patterns.",
    ),
}


@dataclass(frozen=True)
class QACheck:
    """Machine-readable QA check record."""

    name: str
    passed: bool
    severity: str
    message: str
    evidence_refs: list[str]
    hard: bool = True
    failure_class: str | None = None
    repair_class: str | None = None
    repair_hint: str | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "name": self.name,
                "passed": self.passed,
                "severity": self.severity,
                "hard": self.hard,
                "message": self.message,
                "evidence_refs": self.evidence_refs,
                "failure_class": self.failure_class,
                "repair_class": self.repair_class,
                "repair_hint": self.repair_hint,
            }
        )  # type: ignore[return-value]


@dataclass(frozen=True)
class QAResult:
    """Result returned by ``QALab.evaluate``."""

    job_id: str
    passed: bool
    quality_score: float
    report_path: Path
    report: dict[str, JsonValue]
    checks: list[QACheck]

    def to_dict(self) -> dict[str, JsonValue]:
        return self.report


@dataclass(frozen=True)
class _VerifierEvidence:
    result: VerificationResult | None
    ref: str | None
    sha256: str | None
    valid: bool
    error: str | None

    def to_report(self) -> dict[str, JsonValue] | None:
        if self.ref is None and self.sha256 is None and self.error is None:
            return None
        payload: dict[str, Any] = {
            "ref": self.ref,
            "sha256": self.sha256,
            "valid": self.valid,
            "error": self.error,
        }
        if self.result is not None:
            payload.update(
                {
                    "result_id": self.result.result_id,
                    "passed": self.result.passed,
                    "package_hash": self.result.package_hash,
                    "verification_spec_hash": self.result.verification_spec_hash,
                    "verifier_version": self.result.verifier_version,
                    "evidence_refs": self.result.evidence_refs,
                    "llm_judge_ref": self.result.llm_judge_ref,
                }
            )
        return ensure_json_compatible(payload)  # type: ignore[return-value]


class QALab:
    """Deterministic QA evaluation layer on top of the independent Verifier.

    QA Lab records richer quality evidence, but the hard pass decision still
    requires an existing verifier-passed result for the current package.
    Optional judge objects are auxiliary only and cannot override hard checks.
    """

    def __init__(self, *, judge: Any | None = None, qa_version: str = QA_LAB_VERSION) -> None:
        self.judge = judge
        self.qa_version = qa_version

    def evaluate(self, workspace: JobWorkspace | str | Path) -> QAResult:
        """Evaluate a job workspace and write ``qa/quality_report.json``."""

        job_workspace = _coerce_workspace(workspace)
        qa_dir = job_workspace.resolve_path("qa")
        qa_dir.mkdir(parents=False, exist_ok=True)

        package_hash, package_hash_failures = _hash_package(job_workspace)
        verification_spec_hash = _sha_if_exists(job_workspace, "verification_spec.yaml") or _ZERO_HASH
        verifier_evidence = _read_verifier_evidence(job_workspace)
        skill_spec, skill_spec_error = _read_skill_spec(job_workspace)
        skill_text, sections, frontmatter, skill_error = _read_skill_markdown(job_workspace)
        fixture_spec, fixture_spec_ref = _read_fixture_spec(job_workspace)
        expected = _expected_qa_inputs(skill_spec, fixture_spec)

        checks: list[QACheck] = [
            _verifier_passed_check(
                job_workspace=job_workspace,
                verifier_evidence=verifier_evidence,
                package_hash=package_hash,
                package_hash_failures=package_hash_failures,
                verification_spec_hash=verification_spec_hash,
            )
        ]

        trigger_results = _fixture_results(
            fixture_type="trigger",
            expected_items=expected["trigger_scenarios"],
            section_name="When To Use",
            section_text=sections.get(_normalize_heading("When To Use")),
            evidence_ref="package/SKILL.md",
            source_ref=expected["source_ref"],
            missing_reason=skill_spec_error or skill_error,
        )
        checks.append(
            _hard_check(
                "trigger_fixture_coverage",
                bool(trigger_results) and any(bool(item["passed"]) for item in trigger_results),
                _coverage_message("trigger fixture", trigger_results),
                ["package/SKILL.md", expected["source_ref"]],
            )
        )

        non_trigger_results = _fixture_results(
            fixture_type="non_trigger",
            expected_items=expected["non_trigger_scenarios"],
            section_name="When Not To Use",
            section_text=sections.get(_normalize_heading("When Not To Use")),
            evidence_ref="package/SKILL.md",
            source_ref=expected["source_ref"],
            missing_reason=skill_spec_error or skill_error,
        )
        checks.append(
            _hard_check(
                "non_trigger_fixture_coverage",
                bool(non_trigger_results) and any(bool(item["passed"]) for item in non_trigger_results),
                _coverage_message("non-trigger fixture", non_trigger_results),
                ["package/SKILL.md", expected["source_ref"]],
            )
        )

        input_contract_results = _contract_results(
            contract_type="required_input",
            expected_items=expected["required_inputs"],
            section_name="Inputs",
            section_text=sections.get(_normalize_heading("Inputs")),
            evidence_ref="package/SKILL.md",
            source_ref=expected["source_ref"],
            missing_reason=skill_spec_error or skill_error,
        )
        output_contract_results = _contract_results(
            contract_type="expected_output",
            expected_items=expected["expected_outputs"],
            section_name="Outputs",
            section_text=sections.get(_normalize_heading("Outputs")),
            evidence_ref="package/SKILL.md",
            source_ref=expected["source_ref"],
            missing_reason=skill_spec_error or skill_error,
        )
        io_results = input_contract_results + output_contract_results
        checks.append(
            _hard_check(
                "io_contract_coverage",
                bool(input_contract_results)
                and bool(output_contract_results)
                and all(bool(item["passed"]) for item in io_results),
                _coverage_message("input/output contract", io_results),
                ["package/SKILL.md", expected["source_ref"]],
            )
        )

        workflow_result = _workflow_actionability_result(
            sections.get(_normalize_heading("Workflow")),
            skill_error=skill_error,
        )
        checks.append(
            _hard_check(
                "workflow_actionability",
                bool(workflow_result["passed"]),
                str(workflow_result["message"]),
                ["package/SKILL.md"],
            )
        )

        safety_result = _safety_actionability_result(
            sections.get(_normalize_heading("Safety")),
            skill_error=skill_error,
        )
        checks.append(
            _hard_check(
                "safety_actionability",
                bool(safety_result["passed"]),
                str(safety_result["message"]),
                ["package/SKILL.md"],
            )
        )

        script_smoke = _script_smoke_result(
            job_workspace,
            skill_text=skill_text,
            frontmatter=frontmatter,
            frontmatter_error=skill_error if skill_error and "frontmatter" in skill_error else None,
        )
        checks.append(
            _hard_check(
                "script_smoke",
                bool(script_smoke["passed"]),
                str(script_smoke["message"]),
                ["package/SKILL.md", *[str(ref) for ref in script_smoke.get("evidence_refs", [])]],
            )
        )

        failed_hard_checks = [check for check in checks if check.hard and not check.passed]
        passed = not failed_hard_checks
        quality_score = _quality_score(checks)
        failure_taxonomy = _failure_taxonomy(failed_hard_checks)
        judge_signal = _judge_signal(
            self.judge,
            job_workspace,
            qa_dir=qa_dir,
            evidence={
                "schema_version": "skillfoundry.qa.judge_evidence.v1",
                "job_id": job_workspace.job_id,
                "package_hash": package_hash,
                "quality_score_before_judge": quality_score,
                "hard_checks": [
                    {
                        "name": check.name,
                        "passed": check.passed,
                        "failure_class": check.failure_class,
                        "repair_class": check.repair_class,
                    }
                    for check in checks
                ],
                "failed_hard_checks": [check.name for check in failed_hard_checks],
            },
        )

        report = ensure_json_compatible(
            {
                "schema_version": QA_REPORT_VERSION,
                "qa_version": self.qa_version,
                "job_id": job_workspace.job_id,
                "created_at": utc_now(),
                "package_hash": package_hash,
                "package_hash_failures": package_hash_failures,
                "verifier_result": verifier_evidence.to_report(),
                "verifier_result_ref": verifier_evidence.ref,
                "verifier_result_hash": verifier_evidence.sha256,
                "verification_spec_hash": verification_spec_hash,
                "passed": passed,
                "hard_gate_passed": passed,
                "quality_score": quality_score,
                "hard_checks_total": len(HARD_CHECK_NAMES),
                "hard_checks_passed": len([check for check in checks if check.hard and check.passed]),
                "checks": [check.to_dict() for check in checks],
                "fixture_sources": {
                    "skill_spec": _file_ref(job_workspace, "skill_spec.yaml"),
                    "qa_fixture_spec": fixture_spec_ref,
                    "selected_source_ref": expected["source_ref"],
                },
                "trigger_fixture_results": trigger_results,
                "non_trigger_fixture_results": non_trigger_results,
                "input_contract_results": input_contract_results,
                "output_contract_results": output_contract_results,
                "input_output_contract_results": {
                    "required_inputs": input_contract_results,
                    "expected_outputs": output_contract_results,
                },
                "workflow_actionability": workflow_result,
                "safety_actionability": safety_result,
                "script_smoke_results": script_smoke,
                "judge_signal": judge_signal,
                "failure_taxonomy": failure_taxonomy,
                "refs": {
                    "package": {"ref": "package", "sha256": package_hash},
                    "skill_spec": _file_ref(job_workspace, "skill_spec.yaml"),
                    "verification_spec": _file_ref(job_workspace, "verification_spec.yaml"),
                    "verifier_result": verifier_evidence.to_report(),
                    "quality_report": {"ref": "qa/quality_report.json"},
                },
            }
        )

        report_path = job_workspace.resolve_path("qa/quality_report.json")
        _write_json(report_path, report)
        return QAResult(
            job_id=job_workspace.job_id,
            passed=passed,
            quality_score=quality_score,
            report_path=report_path,
            report=report,  # type: ignore[arg-type]
            checks=checks,
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
            job_id = ArtifactManifest.read_json_file(manifest_path).job_id
        except Exception:
            pass
    return JobWorkspace(root=root, job_id=job_id)


def _read_verifier_evidence(workspace: JobWorkspace) -> _VerifierEvidence:
    ref = "verifier/verification_result.json"
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception as exc:
        return _VerifierEvidence(result=None, ref=None, sha256=None, valid=False, error=str(exc))
    digest = sha256_file(path)
    try:
        result = VerificationResult.read_json_file(path)
    except Exception as exc:
        return _VerifierEvidence(result=None, ref=ref, sha256=digest, valid=False, error=str(exc))
    return _VerifierEvidence(result=result, ref=ref, sha256=digest, valid=True, error=None)


def _read_skill_spec(workspace: JobWorkspace) -> tuple[SkillSpec | None, str | None]:
    try:
        return SkillSpec.read_yaml_file(workspace.resolve_path("skill_spec.yaml", must_exist=True)), None
    except Exception as exc:
        return None, f"skill_spec.yaml is missing or invalid: {exc}"


def _read_skill_markdown(
    workspace: JobWorkspace,
) -> tuple[str | None, dict[str, str], dict[str, Any], str | None]:
    ref = "package/SKILL.md"
    try:
        text = workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8")
    except Exception as exc:
        return None, {}, {}, f"package/SKILL.md is missing or unreadable: {exc}"
    frontmatter, frontmatter_error = _frontmatter_mapping(text)
    headings, sections = _parse_markdown_sections(text)
    if not any(level == 1 and title.strip() for level, title in headings):
        return text, sections, frontmatter, "package/SKILL.md is missing a top-level title"
    return text, sections, frontmatter, frontmatter_error


def _read_fixture_spec(workspace: JobWorkspace) -> tuple[dict[str, list[str]], dict[str, JsonValue] | None]:
    ref = "qa/fixtures.json"
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception:
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, _file_ref(workspace, ref)
    if not isinstance(payload, dict):
        return {}, _file_ref(workspace, ref)
    fixtures: dict[str, list[str]] = {}
    for key in ("trigger_scenarios", "non_trigger_scenarios", "required_inputs", "expected_outputs"):
        value = payload.get(key)
        if isinstance(value, list):
            fixtures[key] = [str(item).strip() for item in value if str(item).strip()]
    return fixtures, _file_ref(workspace, ref)


def _expected_qa_inputs(
    skill_spec: SkillSpec | None,
    fixture_spec: Mapping[str, list[str]],
) -> dict[str, Any]:
    source_ref = "qa/fixtures.json" if fixture_spec else "skill_spec.yaml"
    return {
        "source_ref": source_ref,
        "trigger_scenarios": list(
            fixture_spec.get("trigger_scenarios")
            or (skill_spec.trigger_scenarios if skill_spec is not None else [])
        ),
        "non_trigger_scenarios": list(
            fixture_spec.get("non_trigger_scenarios")
            or (skill_spec.non_trigger_scenarios if skill_spec is not None else [])
        ),
        "required_inputs": list(
            fixture_spec.get("required_inputs")
            or (skill_spec.required_inputs if skill_spec is not None else [])
        ),
        "expected_outputs": list(
            fixture_spec.get("expected_outputs")
            or (skill_spec.expected_outputs if skill_spec is not None else [])
        ),
    }


def _verifier_passed_check(
    *,
    job_workspace: JobWorkspace,
    verifier_evidence: _VerifierEvidence,
    package_hash: str,
    package_hash_failures: list[str],
    verification_spec_hash: str,
) -> QACheck:
    failures: list[str] = []
    evidence_refs = ["package", "verification_spec.yaml"]
    if verifier_evidence.ref is not None:
        evidence_refs.append(verifier_evidence.ref)

    result = verifier_evidence.result
    if result is None:
        failures.append(verifier_evidence.error or "verifier/verification_result.json is missing")
    else:
        if result.job_id != job_workspace.job_id:
            failures.append(f"verifier job_id {result.job_id!r} does not match workspace {job_workspace.job_id!r}")
        if not result.passed:
            failures.append("verifier_result.passed is false")
        if result.failures:
            failures.append("verifier_result.failures is non-empty")
        for index, check in enumerate(result.checks):
            if check.get("severity") == "error" and check.get("passed") is False:
                failures.append(f"verifier_result.checks[{index}] contains a failed error check")
                break
        if result.package_hash != package_hash:
            failures.append(f"verifier package_hash {result.package_hash} does not match current package {package_hash}")
        if result.verification_spec_hash != verification_spec_hash:
            failures.append(
                "verifier verification_spec_hash "
                f"{result.verification_spec_hash} does not match current spec {verification_spec_hash}"
            )
    failures.extend(f"package_hash: {failure}" for failure in package_hash_failures)
    if failures:
        return _hard_check("verifier_passed", False, "; ".join(failures), evidence_refs)
    return _hard_check(
        "verifier_passed",
        True,
        "existing verifier result passes and matches the current package and verification spec",
        evidence_refs,
    )


def _hard_check(name: str, passed: bool, message: str, evidence_refs: list[str]) -> QACheck:
    failure_class: str | None = None
    repair_class: str | None = None
    repair_hint: str | None = None
    if not passed:
        failure_class, repair_class, repair_hint = _FAILURE_TAXONOMY[name]
    return QACheck(
        name=name,
        passed=passed,
        severity="error",
        hard=True,
        message=message,
        evidence_refs=_dedupe_refs(evidence_refs),
        failure_class=failure_class,
        repair_class=repair_class,
        repair_hint=repair_hint,
    )


def _fixture_results(
    *,
    fixture_type: str,
    expected_items: list[str],
    section_name: str,
    section_text: str | None,
    evidence_ref: str,
    source_ref: str,
    missing_reason: str | None,
) -> list[dict[str, JsonValue]]:
    if not expected_items:
        return []
    actionable = _has_actionable_fixture(section_text)
    results: list[dict[str, JsonValue]] = []
    for item in expected_items:
        matched_terms = _matched_terms(item, section_text or "")
        direct_match = _represents_expected(item, section_text or "")
        passed = bool(section_text) and (actionable or direct_match)
        result = {
            "fixture_type": fixture_type,
            "expected": item,
            "source_ref": source_ref,
            "section": section_name,
            "passed": passed,
            "direct_match": direct_match,
            "actionable_section": actionable,
            "matched_terms": matched_terms,
            "evidence_ref": evidence_ref,
            "failure": None if passed else (missing_reason or f"{section_name} lacks an actionable fixture"),
        }
        results.append(ensure_json_compatible(result))  # type: ignore[arg-type]
    return results


def _contract_results(
    *,
    contract_type: str,
    expected_items: list[str],
    section_name: str,
    section_text: str | None,
    evidence_ref: str,
    source_ref: str,
    missing_reason: str | None,
) -> list[dict[str, JsonValue]]:
    if not expected_items:
        return []
    actionable = _has_actionable_fixture(section_text)
    results: list[dict[str, JsonValue]] = []
    for item in expected_items:
        matched_terms = _matched_terms(item, section_text or "")
        direct_match = _represents_expected(item, section_text or "")
        passed = bool(section_text) and (actionable or direct_match)
        result = {
            "contract_type": contract_type,
            "expected": item,
            "source_ref": source_ref,
            "section": section_name,
            "passed": passed,
            "direct_match": direct_match,
            "actionable_section": actionable,
            "matched_terms": matched_terms,
            "evidence_ref": evidence_ref,
            "failure": None if passed else (missing_reason or f"{section_name} lacks an actionable contract item"),
        }
        results.append(ensure_json_compatible(result))  # type: ignore[arg-type]
    return results


def _coverage_message(label: str, results: list[dict[str, JsonValue]]) -> str:
    if not results:
        return f"no {label} expectations were available from SkillSpec or QA fixtures"
    passed = len([item for item in results if item.get("passed") is True])
    if passed == len(results):
        return f"all {label} expectations are represented by actionable package sections"
    if passed:
        return f"{passed}/{len(results)} {label} expectations are represented"
    return f"0/{len(results)} {label} expectations are represented"


def _workflow_actionability_result(section_text: str | None, *, skill_error: str | None) -> dict[str, JsonValue]:
    if not section_text:
        return {
            "passed": False,
            "step_count": 0,
            "actionable_steps": [],
            "message": skill_error or "Workflow section is missing or empty",
            "evidence_ref": "package/SKILL.md",
        }
    steps = []
    for raw_line in section_text.splitlines():
        line = _strip_line_marker(raw_line)
        if _is_actionable_line(line, min_tokens=2) and (_LINE_MARKER_RE.match(raw_line) or _starts_with_action(line)):
            steps.append(line)
    passed = len(steps) >= 2
    return ensure_json_compatible(
        {
            "passed": passed,
            "step_count": len(steps),
            "actionable_steps": steps,
            "message": (
                "Workflow section contains multiple actionable steps"
                if passed
                else "Workflow section needs at least two concrete actionable steps"
            ),
            "evidence_ref": "package/SKILL.md",
        }
    )  # type: ignore[return-value]


def _safety_actionability_result(section_text: str | None, *, skill_error: str | None) -> dict[str, JsonValue]:
    if not section_text:
        return {
            "passed": False,
            "constraint_count": 0,
            "constraints": [],
            "message": skill_error or "Safety section is missing or empty",
            "evidence_ref": "package/SKILL.md",
        }
    constraints = []
    for raw_line in section_text.splitlines():
        line = _strip_line_marker(raw_line)
        lowered = line.lower()
        if _is_actionable_line(line, min_tokens=2) and any(marker in lowered for marker in _SAFETY_MARKERS):
            constraints.append(line)
    passed = bool(constraints)
    return ensure_json_compatible(
        {
            "passed": passed,
            "constraint_count": len(constraints),
            "constraints": constraints,
            "message": (
                "Safety section contains concrete constraints"
                if passed
                else "Safety section needs concrete constraints or rejected behaviors"
            ),
            "evidence_ref": "package/SKILL.md",
        }
    )  # type: ignore[return-value]


def _script_smoke_result(
    workspace: JobWorkspace,
    *,
    skill_text: str | None,
    frontmatter: Mapping[str, Any],
    frontmatter_error: str | None,
) -> dict[str, JsonValue]:
    if skill_text is None:
        return {
            "passed": False,
            "message": "script declarations cannot be checked without package/SKILL.md",
            "declared_count": 0,
            "scripts": [],
            "evidence_refs": ["package/SKILL.md"],
        }
    if frontmatter_error is not None:
        return {
            "passed": False,
            "message": frontmatter_error,
            "declared_count": 0,
            "scripts": [],
            "evidence_refs": ["package/SKILL.md"],
        }

    declared = sorted(_extract_declared_scripts(skill_text, frontmatter))
    scripts: list[dict[str, JsonValue]] = []
    evidence_refs = ["package/SKILL.md"]
    try:
        package_scripts_dir = workspace.resolve_path("package/scripts", must_exist=True)
    except Exception as exc:
        return {
            "passed": False,
            "message": f"package/scripts is missing or unsafe: {exc}",
            "declared_count": len(declared),
            "scripts": [],
            "evidence_refs": evidence_refs,
        }
    for script_ref in declared:
        script_result = _script_result(workspace, package_scripts_dir, script_ref)
        scripts.append(script_result)
        safe_ref = script_result.get("package_ref")
        if isinstance(safe_ref, str):
            evidence_refs.append(safe_ref)

    failures = [
        f"{item.get('declared_ref')}: {item.get('message')}"
        for item in scripts
        if item.get("passed") is False
    ]
    passed = not failures
    return ensure_json_compatible(
        {
            "passed": passed,
            "message": "declared scripts passed deterministic smoke checks" if passed else "; ".join(failures),
            "declared_count": len(declared),
            "scripts": scripts,
            "evidence_refs": _dedupe_refs(evidence_refs),
            "unsafe_patterns": [name for name, _pattern in _UNSAFE_SCRIPT_PATTERNS],
        }
    )  # type: ignore[return-value]


def _script_result(
    workspace: JobWorkspace,
    package_scripts_dir: Path,
    declared_ref: str,
) -> dict[str, JsonValue]:
    package_relative = _package_relative_declared_path(declared_ref)
    try:
        safe_path = validate_relative_path(package_relative)
    except PathSecurityError as exc:
        return _script_failure(declared_ref, None, str(exc))
    if not safe_path.parts or safe_path.parts[0] != "scripts":
        return _script_failure(declared_ref, None, "declared script is not under package/scripts")
    package_ref = f"package/{safe_path.as_posix()}"
    try:
        script_path = workspace.resolve_path(package_ref, must_exist=True)
        assert_under_root(package_scripts_dir, script_path)
    except Exception as exc:
        return _script_failure(declared_ref, package_ref, f"script is missing or not confined to package/scripts: {exc}")
    if not script_path.is_file():
        return _script_failure(declared_ref, package_ref, "declared script is not a file")
    try:
        content = script_path.read_text(encoding="utf-8")
    except Exception as exc:
        return _script_failure(declared_ref, package_ref, f"script is unreadable: {exc}")

    matches = [name for name, pattern in _UNSAFE_SCRIPT_PATTERNS if pattern.search(content)]
    if matches:
        return ensure_json_compatible(
            {
                "declared_ref": declared_ref,
                "package_ref": package_ref,
                "passed": False,
                "message": "unsafe script patterns detected",
                "unsafe_matches": matches,
                "sha256": sha256_file(script_path),
            }
        )  # type: ignore[return-value]
    return ensure_json_compatible(
        {
            "declared_ref": declared_ref,
            "package_ref": package_ref,
            "passed": True,
            "message": "script exists, is confined, and contains no blocked smoke patterns",
            "unsafe_matches": [],
            "sha256": sha256_file(script_path),
        }
    )  # type: ignore[return-value]


def _script_failure(declared_ref: str, package_ref: str | None, message: str) -> dict[str, JsonValue]:
    return {
        "declared_ref": declared_ref,
        "package_ref": package_ref,
        "passed": False,
        "message": message,
        "unsafe_matches": [],
        "sha256": None,
    }


def _judge_signal(
    judge: Any | None,
    workspace: JobWorkspace,
    *,
    qa_dir: Path,
    evidence: Mapping[str, Any],
) -> dict[str, JsonValue]:
    if judge is None:
        return {
            "present": False,
            "auxiliary": True,
            "passed": None,
            "score": None,
            "evidence_ref": None,
            "overrode_hard_checks": False,
        }

    try:
        if hasattr(judge, "evaluate"):
            raw_signal = judge.evaluate(workspace, ensure_json_compatible(dict(evidence)))
        elif callable(judge):
            raw_signal = judge(workspace, ensure_json_compatible(dict(evidence)))
        else:
            raw_signal = {"passed": False, "score": None, "summary": "judge object is not callable"}
    except Exception as exc:  # pragma: no cover - defensive auxiliary boundary
        raw_signal = {"passed": False, "score": None, "summary": f"judge failed: {type(exc).__name__}: {exc}"}
    if not isinstance(raw_signal, Mapping):
        raw_signal = {"passed": False, "score": None, "summary": "judge returned a non-mapping signal"}

    signal_payload = ensure_json_compatible(
        {
            "schema_version": QA_JUDGE_SIGNAL_VERSION,
            "job_id": workspace.job_id,
            "created_at": utc_now(),
            "auxiliary": True,
            "overrode_hard_checks": False,
            "governed_evidence": dict(evidence),
            "signal": dict(raw_signal),
        }
    )
    signal_path = qa_dir / "judge_signal.json"
    _write_json(signal_path, signal_payload)
    signal_hash = sha256_file(signal_path)
    passed = raw_signal.get("passed")
    score = raw_signal.get("score")
    summary = raw_signal.get("summary")
    return ensure_json_compatible(
        {
            "present": True,
            "auxiliary": True,
            "passed": passed if isinstance(passed, bool) else None,
            "score": score if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
            "summary": str(summary) if summary is not None else None,
            "evidence_ref": "qa/judge_signal.json",
            "evidence_hash": signal_hash,
            "overrode_hard_checks": False,
        }
    )  # type: ignore[return-value]


def _failure_taxonomy(failed_checks: list[QACheck]) -> dict[str, JsonValue]:
    failed = [
        {
            "check_name": check.name,
            "failure_class": check.failure_class,
            "repair_class": check.repair_class,
            "repair_hint": check.repair_hint,
            "evidence_refs": check.evidence_refs,
        }
        for check in failed_checks
    ]
    return ensure_json_compatible(
        {
            "schema_version": "skillfoundry.qa.failure_taxonomy.v1",
            "failed_checks": failed,
            "failure_classes": sorted({str(item["failure_class"]) for item in failed if item["failure_class"]}),
            "repair_classes": sorted({str(item["repair_class"]) for item in failed if item["repair_class"]}),
        }
    )  # type: ignore[return-value]


def _quality_score(checks: list[QACheck]) -> float:
    hard_checks = [check for check in checks if check.name in HARD_CHECK_NAMES and check.hard]
    if not hard_checks:
        return 0.0
    passed = len([check for check in hard_checks if check.passed])
    return round((passed / len(hard_checks)) * 100, 2)


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


def _frontmatter_mapping(skill_text: str) -> tuple[dict[str, Any], str | None]:
    if not skill_text.startswith("---\n"):
        return {}, None
    end = skill_text.find("\n---", 4)
    if end == -1:
        return {}, "SKILL.md frontmatter closing delimiter is missing"
    try:
        payload = yaml.safe_load(skill_text[4:end])
    except yaml.YAMLError as exc:
        return {}, f"SKILL.md frontmatter is invalid YAML: {exc}"
    if payload is None:
        return {}, None
    if not isinstance(payload, dict):
        return {}, "SKILL.md frontmatter must be a YAML mapping"
    return {str(key): value for key, value in payload.items()}, None


def _extract_declared_scripts(skill_text: str, frontmatter: Mapping[str, Any]) -> set[str]:
    declared: set[str] = set()
    for key, value in frontmatter.items():
        if _is_script_key(key):
            declared.update(_flatten_string_values(value))
    for match in _MARKDOWN_LINK_RE.finditer(skill_text):
        target = match.group("target").strip()
        if _is_ignored_markdown_target(target):
            continue
        package_relative = _package_relative_declared_path(target)
        if package_relative.startswith("scripts/") or package_relative.startswith("package/scripts/"):
            declared.add(target)
    return declared


def _is_script_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in {"script", "scripts", "script_path", "script_paths"}


def _flatten_string_values(value: Any) -> set[str]:
    if isinstance(value, str) and value.strip():
        return {value.strip()}
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
    return target.startswith("#") or _URL_SCHEME_RE.match(target) is not None


def _package_relative_declared_path(target: str) -> str:
    clean = target.split("#", 1)[0].split("?", 1)[0].replace("\\", "/")
    if _WINDOWS_DRIVE_RE.match(clean):
        return clean
    if clean.startswith("package/"):
        return clean[len("package/") :]
    return clean


def _has_actionable_fixture(section_text: str | None) -> bool:
    if not section_text:
        return False
    return any(_is_actionable_line(_strip_line_marker(line), min_tokens=3) for line in section_text.splitlines())


def _represents_expected(expected: str, section_text: str) -> bool:
    normalized_expected = " ".join(_TOKEN_RE.findall(expected.lower()))
    normalized_section = " ".join(_TOKEN_RE.findall(section_text.lower()))
    if normalized_expected and normalized_expected in normalized_section:
        return True
    expected_tokens = _meaningful_tokens(expected)
    if not expected_tokens:
        return False
    matched = set(expected_tokens) & set(_meaningful_tokens(section_text))
    required = min(2, len(set(expected_tokens)))
    return len(matched) >= required


def _matched_terms(expected: str, section_text: str) -> list[str]:
    return sorted(set(_meaningful_tokens(expected)) & set(_meaningful_tokens(section_text)))


def _is_actionable_line(line: str, *, min_tokens: int) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("<!--") or stripped in {"```", "---"}:
        return False
    lowered = stripped.lower()
    if lowered in {"tbd", "todo", "n/a", "na", "none", "various", "as needed"}:
        return False
    return len(_meaningful_tokens(stripped)) >= min_tokens


def _starts_with_action(line: str) -> bool:
    tokens = _meaningful_tokens(line)
    if not tokens:
        return False
    return tokens[0] in {
        "add",
        "build",
        "check",
        "collect",
        "compare",
        "emit",
        "generate",
        "inspect",
        "keep",
        "prepare",
        "produce",
        "read",
        "record",
        "reject",
        "return",
        "run",
        "summarize",
        "validate",
        "write",
    }


def _meaningful_tokens(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) > 2 and token not in _STOPWORDS and token not in _GENERIC_QA_TERMS
    ]


def _strip_line_marker(line: str) -> str:
    return _LINE_MARKER_RE.sub("", line).strip()


def _sha_if_exists(workspace: JobWorkspace, ref: str) -> str | None:
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception:
        return None
    if not path.is_file():
        return None
    return sha256_file(path)


def _file_ref(workspace: JobWorkspace, ref: str) -> dict[str, JsonValue] | None:
    try:
        path = workspace.resolve_path(ref, must_exist=True)
    except Exception:
        return None
    if not path.is_file():
        return None
    return {"ref": ref, "sha256": sha256_file(path)}


def _dedupe_refs(refs: list[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if not ref or ref in seen:
            continue
        result.append(ref)
        seen.add(ref)
    return result


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    compatible = ensure_json_compatible(dict(payload))
    path.write_text(
        json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "HARD_CHECK_NAMES",
    "QA_LAB_VERSION",
    "QA_REPORT_VERSION",
    "QACheck",
    "QALab",
    "QAResult",
]
