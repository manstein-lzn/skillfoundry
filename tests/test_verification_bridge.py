from __future__ import annotations

import json
from pathlib import Path

from contextforge import (
    VerificationGate,
    VerificationResult as ContextForgeVerificationResult,
    with_computed_hash,
)

from skillfoundry.acceptance import (
    ACCEPTANCE_COVERAGE_RESULT_REF,
    ACCEPTANCE_COVERAGE_RESULT_VERSION,
    AcceptanceCoverageResult,
    AcceptanceCoverageResultItem,
    COVERAGE_MODE_VERIFIER_CHECK,
    COVERAGE_RESULT_STATUS_COVERED_FAIL,
    COVERAGE_RESULT_STATUS_COVERED_PASS,
)
from skillfoundry.contracts import build_goal_contract, build_verification_gate
from skillfoundry.schema import JsonValue, VerificationResult, sha256_file, sha256_json
from skillfoundry.verification_bridge import (
    CONTEXTFORGE_VERIFICATION_RESULT_REF,
    bridge_skillfoundry_verification_result,
)
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace


CREATED_AT = "2026-05-22T00:00:00Z"


def _workspace(tmp_path: Path, job_id: str = "bridge-001") -> JobWorkspace:
    workspace = initialize_job_workspace(tmp_path / "runs", job_id)
    workspace.resolve_path("package/SKILL.md").write_text("# Bridge Skill\n", encoding="utf-8")
    (workspace.root / "qa").mkdir()
    workspace.resolve_path("acceptance_criteria.yaml").write_text("- AC-1\n", encoding="utf-8")
    workspace.resolve_path("qa/acceptance_coverage_plan.json").write_text(
        json.dumps({"plan_id": "plan-1", "criteria": ["AC-1"]}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return workspace


def _gate(workspace: JobWorkspace):
    goal = build_goal_contract(workspace, created_at=CREATED_AT)
    return build_verification_gate(workspace, goal.goal_id)


def _gate_with_updates(gate: VerificationGate, **updates) -> VerificationGate:
    payload = gate.to_dict()
    payload.update(updates)
    return VerificationGate.from_dict(with_computed_hash(payload, "gate_hash"))


def _gate_without_acceptance_coverage(gate: VerificationGate) -> VerificationGate:
    required_evidence = [ref for ref in gate.required_evidence if ref != ACCEPTANCE_COVERAGE_RESULT_REF]
    validators = [
        validator.to_dict()
        for validator in gate.validators
        if validator.params.get("path") != ACCEPTANCE_COVERAGE_RESULT_REF
    ]
    return _gate_with_updates(gate, required_evidence=required_evidence, validators=validators)


def _package_hash(workspace: JobWorkspace) -> str:
    package_dir = workspace.resolve_path("package", must_exist=True)
    entries: list[dict[str, JsonValue]] = []
    for path in sorted(package_dir.rglob("*")):
        relative = path.relative_to(package_dir).as_posix()
        if path.is_file():
            entries.append(
                {"path": relative, "kind": "file", "sha256": sha256_file(path), "size": path.stat().st_size}
            )
        elif path.is_dir():
            entries.append({"path": relative, "kind": "dir"})
    return sha256_json(entries)


def _write_verifier_result(
    workspace: JobWorkspace,
    *,
    passed: bool = True,
    package_hash: str | None = None,
    job_id: str | None = None,
    verification_spec_hash: str | None = None,
) -> VerificationResult:
    result = VerificationResult(
        result_id=f"vr-{workspace.job_id}",
        job_id=job_id or workspace.job_id,
        package_hash=package_hash or _package_hash(workspace),
        verification_spec_hash=verification_spec_hash
        or sha256_file(workspace.resolve_path("verification_spec.yaml", must_exist=True)),
        passed=passed,
        checks=[
            {
                "name": "package_skill_md_present",
                "passed": passed,
                "severity": "error",
                "message": "package skill present" if passed else "package skill missing",
                "evidence_ref": "package/SKILL.md",
            }
        ],
        failures=[] if passed else ["package_skill_md_present: package skill missing"],
        evidence_refs=["package/SKILL.md", "verifier/static_report.json"],
        verifier_version="test-verifier",
        created_at=CREATED_AT,
    )
    result.write_json_file(workspace.resolve_path("verifier/verification_result.json"))
    return result


def _coverage_item(*, passed: bool = True) -> AcceptanceCoverageResultItem:
    return AcceptanceCoverageResultItem(
        criterion_id="AC-1",
        priority="must",
        status=COVERAGE_RESULT_STATUS_COVERED_PASS if passed else COVERAGE_RESULT_STATUS_COVERED_FAIL,
        passed=passed,
        coverage_mode=COVERAGE_MODE_VERIFIER_CHECK,
        deterministic=True,
        evidence_refs=["verifier/verification_result.json"],
        failures=[] if passed else ["verifier check failed"],
        verifier_check_id="package_skill_md_present",
    )


def _write_coverage_result(
    workspace: JobWorkspace,
    *,
    passed: bool = True,
    verification_result_hash: str | None = None,
    package_hash: str | None = None,
    job_id: str | None = None,
) -> AcceptanceCoverageResult:
    verifier_hash = verification_result_hash or sha256_file(
        workspace.resolve_path("verifier/verification_result.json", must_exist=True)
    )
    item = _coverage_item(passed=passed)
    result = AcceptanceCoverageResult(
        result_id=f"acr-{workspace.job_id}",
        job_id=job_id or workspace.job_id,
        plan_id="plan-1",
        acceptance_criteria_ref="acceptance_criteria.yaml",
        acceptance_criteria_hash=sha256_file(workspace.resolve_path("acceptance_criteria.yaml", must_exist=True)),
        coverage_plan_ref="qa/acceptance_coverage_plan.json",
        coverage_plan_hash=sha256_file(workspace.resolve_path("qa/acceptance_coverage_plan.json", must_exist=True)),
        qa_report_ref=None,
        qa_report_hash=None,
        verification_result_ref="verifier/verification_result.json",
        verification_result_hash=verifier_hash,
        package_hash=package_hash or _package_hash(workspace),
        passed=passed,
        coverage_score=1.0 if passed else 0.0,
        must_total=1,
        must_passed=1 if passed else 0,
        must_manual_only=0,
        must_failed=0 if passed else 1,
        optional_total=0,
        optional_failed=0,
        items=[item],
        failures=[] if passed else ["AC-1: verifier check failed"],
        provenance={"test": "verification_bridge"},
        created_at=CREATED_AT,
        schema_version=ACCEPTANCE_COVERAGE_RESULT_VERSION,
    )
    result.write_json_file(workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF))
    return result


def _validator(result: ContextForgeVerificationResult, validator_id: str):
    return next(item for item in result.validator_results if item.validator_id == validator_id)


def _bridge(
    workspace: JobWorkspace,
    gate: VerificationGate | None = None,
    **kwargs,
) -> ContextForgeVerificationResult:
    verification_gate = gate or _gate(workspace)
    kwargs.setdefault("expected_gate_hash", verification_gate.gate_hash)
    kwargs.setdefault("created_at", CREATED_AT)
    return bridge_skillfoundry_verification_result(workspace, verification_gate, **kwargs)


def test_bridge_passes_when_verifier_and_acceptance_coverage_pass(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_verifier_result(workspace, passed=True)
    _write_coverage_result(workspace, passed=True)

    result = _bridge(
        workspace,
        goal_run_id="goal-run-1",
    )

    assert result.status == "passed"
    assert result.passed is True
    assert _validator(result, "skillfoundry_verifier_passed").passed is True
    assert _validator(result, "acceptance_coverage_passed").passed is True
    assert _validator(result, "acceptance_coverage_fresh").passed is True
    assert ContextForgeVerificationResult.from_dict(result.to_dict()) == result
    payload = json.loads(workspace.resolve_path(CONTEXTFORGE_VERIFICATION_RESULT_REF, must_exist=True).read_text())
    assert payload["verification_result_id"] == result.verification_result_id


def test_bridge_fails_when_skillfoundry_verifier_fails(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_verifier_result(workspace, passed=False)
    _write_coverage_result(workspace, passed=True)

    result = _bridge(workspace)

    assert result.status == "failed"
    assert result.passed is False
    assert _validator(result, "skillfoundry_verifier_passed").passed is False


def test_bridge_fails_when_acceptance_coverage_fails_or_is_missing(tmp_path: Path) -> None:
    failed_workspace = _workspace(tmp_path, "bridge-coverage-fail")
    _write_verifier_result(failed_workspace, passed=True)
    _write_coverage_result(failed_workspace, passed=False)
    missing_workspace = _workspace(tmp_path, "bridge-coverage-missing")
    _write_verifier_result(missing_workspace, passed=True)

    failed = _bridge(failed_workspace)
    missing = _bridge(missing_workspace)

    assert failed.status == "failed"
    assert _validator(failed, "acceptance_coverage_passed").passed is False
    assert missing.status == "failed"
    assert _validator(missing, "acceptance_coverage_result_present").passed is False


def test_worker_self_report_cannot_substitute_for_verifier_or_acceptance(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    report_dir = workspace.root / "attempts" / "001"
    report_dir.mkdir()
    (report_dir / "worker_report.json").write_text(
        json.dumps(
            {
                "worker self-report": "approved",
                "passed": True,
                "summary": "worker claims the build is acceptable",
            }
        ),
        encoding="utf-8",
    )

    result = _bridge(workspace)

    assert result.status == "failed"
    assert _validator(result, "worker_self_report_not_acceptance").passed is True
    assert _validator(result, "skillfoundry_verification_result_present").passed is False


def test_bridge_fails_on_stale_gate_hash_or_stale_coverage_hash(tmp_path: Path) -> None:
    stale_gate_workspace = _workspace(tmp_path, "bridge-stale-gate")
    _write_verifier_result(stale_gate_workspace, passed=True)
    _write_coverage_result(stale_gate_workspace, passed=True)
    gate = _gate(stale_gate_workspace)

    stale_gate = bridge_skillfoundry_verification_result(
        stale_gate_workspace,
        gate,
        expected_gate_hash="sha256:" + "0" * 64,
        created_at=CREATED_AT,
    )

    stale_coverage_workspace = _workspace(tmp_path, "bridge-stale-coverage")
    _write_verifier_result(stale_coverage_workspace, passed=True)
    _write_coverage_result(stale_coverage_workspace, passed=True, verification_result_hash="0" * 64)
    stale_coverage = _bridge(stale_coverage_workspace)

    assert stale_gate.status == "failed"
    assert _validator(stale_gate, "verification_gate_hash_current").passed is False
    assert stale_coverage.status == "failed"
    assert _validator(stale_coverage, "acceptance_coverage_fresh").passed is False


def test_bridge_requires_gate_hash_baseline(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_verifier_result(workspace, passed=True)
    _write_coverage_result(workspace, passed=True)
    gate = _gate(workspace)

    result = bridge_skillfoundry_verification_result(workspace, gate, created_at=CREATED_AT)

    assert result.status == "failed"
    assert _validator(result, "verification_gate_hash_self_consistent").passed is True
    assert _validator(result, "verification_gate_hash_current").passed is False


def test_bridge_fails_on_stale_verifier_package_or_foreign_job_evidence(tmp_path: Path) -> None:
    tampered_workspace = _workspace(tmp_path, "bridge-tampered-package")
    _write_verifier_result(tampered_workspace, passed=True)
    _write_coverage_result(tampered_workspace, passed=True)
    tampered_workspace.resolve_path("package/SKILL.md").write_text("# Changed Skill\n", encoding="utf-8")

    foreign_workspace = _workspace(tmp_path, "bridge-foreign-job")
    _write_verifier_result(foreign_workspace, passed=True, job_id="foreign-job")
    _write_coverage_result(foreign_workspace, passed=True, job_id="foreign-job")

    tampered = _bridge(tampered_workspace)
    foreign = _bridge(foreign_workspace)

    assert tampered.status == "failed"
    assert _validator(tampered, "skillfoundry_verifier_fresh_for_workspace").passed is False
    assert _validator(tampered, "acceptance_coverage_fresh").passed is False
    assert foreign.status == "failed"
    assert _validator(foreign, "skillfoundry_verifier_fresh_for_workspace").passed is False
    assert _validator(foreign, "acceptance_coverage_fresh").passed is False


def test_bridge_runs_contextforge_gate_semantics(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_verifier_result(workspace, passed=True)
    _write_coverage_result(workspace, passed=True)
    gate = _gate_with_updates(_gate(workspace), forbidden_paths=["package/SKILL.md"])

    result = _bridge(workspace, gate)

    assert result.status == "failed"
    assert _validator(result, "contextforge_gate_runner_completed").passed is True
    assert _validator(result, "forbidden_path:package/SKILL.md").passed is False


def test_bridge_fails_closed_for_unsupported_metric_gates(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_verifier_result(workspace, passed=True)
    _write_coverage_result(workspace, passed=True)
    gate = _gate_with_updates(
        _gate(workspace),
        metric_gates=[{"metric": "coverage_score", "operator": ">=", "threshold": 1.0}],
    )

    result = _bridge(workspace, gate)

    assert result.status == "failed"
    assert _validator(result, "contextforge_gate_metric_gates_supported").passed is False


def test_bridge_local_failure_cannot_be_hidden_by_runner_validator_id_collision(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_verifier_result(workspace, passed=True)
    _write_coverage_result(workspace, passed=True)
    base_gate = _gate(workspace)
    gate = _gate_with_updates(
        base_gate,
        validators=[
            *[validator.to_dict() for validator in base_gate.validators],
            {
                "validator_id": "verification_gate_hash_current",
                "type": "file_exists",
                "mode": "executable",
                "severity": "blocking",
                "params": {"path": "package/SKILL.md"},
                "metadata": {"test": "validator_id_collision"},
            },
        ],
    )

    result = bridge_skillfoundry_verification_result(
        workspace,
        gate,
        expected_gate_hash="sha256:" + "0" * 64,
        created_at=CREATED_AT,
    )
    colliding_results = [
        item for item in result.validator_results if item.validator_id == "verification_gate_hash_current"
    ]

    assert result.status == "failed"
    assert [item.passed for item in colliding_results] == [False, True]


def test_bridge_allows_missing_coverage_only_when_gate_and_call_do_not_require_it(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_verifier_result(workspace, passed=True)
    gate = _gate_without_acceptance_coverage(_gate(workspace))

    result = _bridge(workspace, gate, require_acceptance_coverage=False)

    assert result.status == "passed"
    assert _validator(result, "acceptance_coverage_result_present").passed is True
    assert _validator(result, "acceptance_coverage_passed").passed is True
    assert _validator(result, "acceptance_coverage_fresh").passed is True
