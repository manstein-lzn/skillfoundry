"""Bridge SkillFoundry verifier evidence into ContextForge verification records."""

from __future__ import annotations

import json

from contextforge import (
    VERIFICATION_RESULT_SCHEMA as CONTEXTFORGE_VERIFICATION_RESULT_SCHEMA,
    ValidatorResult,
    VerificationGate,
    VerificationResult as ContextForgeVerificationResult,
    VerificationRunner,
    with_computed_hash,
)

from .acceptance import ACCEPTANCE_COVERAGE_RESULT_REF, AcceptanceCoverageResult
from .contracts import VERIFICATION_GATE_REF
from .schema import JsonValue, VerificationResult, ensure_json_compatible, sha256_file, sha256_json, utc_now
from .security import PathSecurityError, assert_under_root, validate_relative_path
from .workspace import JobWorkspace


CONTEXTFORGE_VERIFICATION_RESULT_REF = "contextforge/verification_result.json"
VERIFICATION_BRIDGE_VERSION = "skillfoundry.verification_bridge.v1"
SKILLFOUNDRY_VERIFICATION_RESULT_REF = "verifier/verification_result.json"


def bridge_skillfoundry_verification_result(
    workspace: JobWorkspace,
    verification_gate: VerificationGate,
    *,
    goal_run_id: str | None = None,
    worker_id: str | None = None,
    expected_gate_hash: str | None = None,
    require_acceptance_coverage: bool = True,
    output_ref: str | None = CONTEXTFORGE_VERIFICATION_RESULT_REF,
    created_at: str | None = None,
) -> ContextForgeVerificationResult:
    """Create a ContextForge result from SkillFoundry verifier and QA evidence."""

    timestamp = created_at or utc_now()
    validator_results: list[ValidatorResult] = []
    verifier_result, verifier_hash = _read_skillfoundry_verification_result(workspace, validator_results)
    coverage_result, coverage_hash = _read_acceptance_coverage_result(
        workspace,
        validator_results,
        required=require_acceptance_coverage,
    )
    current_package_hash, current_package_failures = _hash_current_package(workspace)
    current_verification_spec_hash = _hash_current_workspace_file(workspace, "verification_spec.yaml")
    _check_gate_hash(workspace, verification_gate, expected_gate_hash, validator_results)
    _check_required_evidence(workspace, verification_gate, validator_results)
    _check_verifier_result(verifier_result, validator_results)
    _check_verifier_freshness(
        workspace,
        verifier_result,
        validator_results,
        current_package_hash=current_package_hash,
        current_package_failures=current_package_failures,
        current_verification_spec_hash=current_verification_spec_hash,
    )
    _check_acceptance_coverage(coverage_result, validator_results, required=require_acceptance_coverage)
    _check_evidence_freshness(
        workspace,
        verifier_result,
        verifier_hash,
        coverage_result,
        validator_results,
        current_package_hash=current_package_hash,
        current_package_failures=current_package_failures,
        required=require_acceptance_coverage,
    )
    _check_worker_self_report_not_acceptance(workspace, validator_results)
    _check_unsupported_gate_fields(verification_gate, validator_results)
    contextforge_gate_result = _run_contextforge_gate(
        workspace,
        verification_gate,
        validator_results,
        goal_run_id=goal_run_id,
        worker_id=worker_id,
        created_at=timestamp,
    )
    bridge_validator_results = list(validator_results)
    if contextforge_gate_result is not None:
        validator_results.extend(contextforge_gate_result.validator_results)

    status = _status_for_bridge(bridge_validator_results, contextforge_gate_result)
    result = ContextForgeVerificationResult(
        schema=CONTEXTFORGE_VERIFICATION_RESULT_SCHEMA,
        version="0.1",
        verification_result_id=_contextforge_result_id(
            workspace=workspace,
            verification_gate=verification_gate,
            goal_run_id=goal_run_id,
            status=status,
            validator_results=validator_results,
            created_at=timestamp,
        ),
        verification_gate_id=verification_gate.verification_gate_id,
        goal_id=verification_gate.goal_id,
        goal_run_id=goal_run_id,
        status=status,  # type: ignore[arg-type]
        validator_results=validator_results,
        passed=status == "passed",
        created_at=timestamp,
        metadata={
            "bridge": VERIFICATION_BRIDGE_VERSION,
            "job_id": workspace.job_id,
            "worker_id": worker_id,
            "verification_gate_hash": verification_gate.gate_hash,
            "current_package_hash": current_package_hash,
            "current_verification_spec_hash": current_verification_spec_hash,
            "skillfoundry_verification_result_ref": SKILLFOUNDRY_VERIFICATION_RESULT_REF,
            "skillfoundry_verification_result_hash": verifier_hash,
            "acceptance_coverage_result_ref": ACCEPTANCE_COVERAGE_RESULT_REF,
            "acceptance_coverage_result_hash": coverage_hash,
            "contextforge_gate_runner_status": contextforge_gate_result.status
            if contextforge_gate_result is not None
            else None,
            "contextforge_gate_runner_result_id": contextforge_gate_result.verification_result_id
            if contextforge_gate_result is not None
            else None,
            "worker_self_report_is_not_acceptance": True,
        },
    )
    if output_ref is not None:
        _write_contextforge_result(workspace, output_ref, result)
    return result


def _read_skillfoundry_verification_result(
    workspace: JobWorkspace,
    validator_results: list[ValidatorResult],
) -> tuple[VerificationResult | None, str | None]:
    try:
        path = workspace.resolve_path(SKILLFOUNDRY_VERIFICATION_RESULT_REF, must_exist=True)
        result = VerificationResult.read_json_file(path)
        digest = sha256_file(path)
    except Exception as exc:
        validator_results.append(
            _validator_result(
                "skillfoundry_verification_result_present",
                False,
                f"SkillFoundry verification result is missing or invalid: {exc}",
                {"ref": SKILLFOUNDRY_VERIFICATION_RESULT_REF},
            )
        )
        return None, None
    validator_results.append(
        _validator_result(
            "skillfoundry_verification_result_present",
            True,
            "SkillFoundry verification result exists and validates.",
            {"ref": SKILLFOUNDRY_VERIFICATION_RESULT_REF, "sha256": digest, "result_id": result.result_id},
        )
    )
    return result, digest


def _read_acceptance_coverage_result(
    workspace: JobWorkspace,
    validator_results: list[ValidatorResult],
    *,
    required: bool,
) -> tuple[AcceptanceCoverageResult | None, str | None]:
    try:
        path = workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF, must_exist=True)
        result = AcceptanceCoverageResult.read_json_file(path)
        digest = sha256_file(path)
    except Exception as exc:
        validator_results.append(
            _validator_result(
                "acceptance_coverage_result_present",
                not required,
                f"Acceptance coverage result is missing or invalid: {exc}",
                {"ref": ACCEPTANCE_COVERAGE_RESULT_REF, "required": required},
            )
        )
        return None, None
    validator_results.append(
        _validator_result(
            "acceptance_coverage_result_present",
            True,
            "Acceptance coverage result exists and validates.",
            {"ref": ACCEPTANCE_COVERAGE_RESULT_REF, "sha256": digest, "result_id": result.result_id},
        )
    )
    return result, digest


def _check_gate_hash(
    workspace: JobWorkspace,
    verification_gate: VerificationGate,
    expected_gate_hash: str | None,
    validator_results: list[ValidatorResult],
) -> None:
    recomputed_hash = str(with_computed_hash(verification_gate.to_dict(), "gate_hash")["gate_hash"])
    self_consistent = verification_gate.gate_hash == recomputed_hash
    validator_results.append(
        _validator_result(
            "verification_gate_hash_self_consistent",
            self_consistent,
            "Verification gate hash matches its payload."
            if self_consistent
            else "Verification gate hash does not match its payload.",
            {"recomputed_gate_hash": recomputed_hash, "actual_gate_hash": verification_gate.gate_hash},
        )
    )

    baseline_hash = expected_gate_hash
    baseline_source = "expected_gate_hash"
    if baseline_hash is None:
        baseline_hash, baseline_source = _read_persisted_gate_hash(workspace)

    if baseline_hash is None:
        passed = False
        message = "Verification gate hash cannot be proven current without an expected or persisted gate hash."
    else:
        passed = baseline_hash == verification_gate.gate_hash
        message = (
            "Verification gate hash matches the current baseline."
            if passed
            else "Verification gate hash is stale or mismatched."
        )
    validator_results.append(
        _validator_result(
            "verification_gate_hash_current",
            passed,
            message,
            {
                "baseline_source": baseline_source,
                "expected_gate_hash": baseline_hash,
                "actual_gate_hash": verification_gate.gate_hash,
            },
        )
    )


def _read_persisted_gate_hash(workspace: JobWorkspace) -> tuple[str | None, str]:
    try:
        path = workspace.resolve_path(VERIFICATION_GATE_REF, must_exist=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        gate = VerificationGate.from_dict(payload)
    except Exception:
        return None, "missing_persisted_gate"
    return gate.gate_hash, VERIFICATION_GATE_REF


def _check_required_evidence(
    workspace: JobWorkspace,
    verification_gate: VerificationGate,
    validator_results: list[ValidatorResult],
) -> None:
    missing: list[str] = []
    present: list[str] = []
    for ref in verification_gate.required_evidence:
        try:
            workspace.resolve_path(ref, must_exist=True)
        except Exception:
            missing.append(ref)
        else:
            present.append(ref)
    validator_results.append(
        _validator_result(
            "verification_gate_required_evidence_present",
            not missing,
            "All required gate evidence exists." if not missing else "Required gate evidence is missing.",
            {"present": present, "missing": missing},
        )
    )


def _check_verifier_result(
    verifier_result: VerificationResult | None,
    validator_results: list[ValidatorResult],
) -> None:
    if verifier_result is None:
        validator_results.append(
            _validator_result(
                "skillfoundry_verifier_passed",
                False,
                "SkillFoundry verifier cannot pass without a valid verification result.",
                {},
            )
        )
        return
    validator_results.append(
        _validator_result(
            "skillfoundry_verifier_passed",
            verifier_result.passed,
            "SkillFoundry verifier passed." if verifier_result.passed else "SkillFoundry verifier failed.",
            {
                "result_id": verifier_result.result_id,
                "failures": list(verifier_result.failures),
                "package_hash": verifier_result.package_hash,
                "verification_spec_hash": verifier_result.verification_spec_hash,
            },
        )
    )


def _check_verifier_freshness(
    workspace: JobWorkspace,
    verifier_result: VerificationResult | None,
    validator_results: list[ValidatorResult],
    *,
    current_package_hash: str,
    current_package_failures: list[str],
    current_verification_spec_hash: str | None,
) -> None:
    if verifier_result is None:
        validator_results.append(
            _validator_result(
                "skillfoundry_verifier_fresh_for_workspace",
                False,
                "Cannot prove verifier freshness without a valid SkillFoundry verification result.",
                {"job_id": workspace.job_id},
            )
        )
        return

    failures: list[str] = []
    if verifier_result.job_id != workspace.job_id:
        failures.append("verifier job_id does not match current workspace job_id")
    if current_package_failures:
        failures.extend(f"current package hash failure: {failure}" for failure in current_package_failures)
    if verifier_result.package_hash != current_package_hash:
        failures.append("verifier package_hash does not match current package hash")
    if current_verification_spec_hash is None:
        failures.append("current verification_spec.yaml hash could not be computed")
    elif verifier_result.verification_spec_hash != current_verification_spec_hash:
        failures.append("verifier verification_spec_hash does not match current verification_spec.yaml")

    validator_results.append(
        _validator_result(
            "skillfoundry_verifier_fresh_for_workspace",
            not failures,
            "SkillFoundry verifier result is fresh for the current workspace."
            if not failures
            else "SkillFoundry verifier result is stale or belongs to a different workspace.",
            {
                "failures": failures,
                "workspace_job_id": workspace.job_id,
                "verifier_job_id": verifier_result.job_id,
                "current_package_hash": current_package_hash,
                "verifier_package_hash": verifier_result.package_hash,
                "current_verification_spec_hash": current_verification_spec_hash,
                "verifier_verification_spec_hash": verifier_result.verification_spec_hash,
            },
        )
    )


def _check_acceptance_coverage(
    coverage_result: AcceptanceCoverageResult | None,
    validator_results: list[ValidatorResult],
    *,
    required: bool,
) -> None:
    if coverage_result is None:
        validator_results.append(
            _validator_result(
                "acceptance_coverage_passed",
                not required,
                "Acceptance coverage is not required for this bridge call."
                if not required
                else "Acceptance coverage cannot pass without a valid coverage result.",
                {"required": required},
            )
        )
        return
    validator_results.append(
        _validator_result(
            "acceptance_coverage_passed",
            coverage_result.passed,
            "Acceptance coverage passed." if coverage_result.passed else "Acceptance coverage failed.",
            {
                "result_id": coverage_result.result_id,
                "failures": list(coverage_result.failures),
                "coverage_score": coverage_result.coverage_score,
                "must_failed": coverage_result.must_failed,
                "must_manual_only": coverage_result.must_manual_only,
            },
        )
    )


def _check_evidence_freshness(
    workspace: JobWorkspace,
    verifier_result: VerificationResult | None,
    verifier_hash: str | None,
    coverage_result: AcceptanceCoverageResult | None,
    validator_results: list[ValidatorResult],
    *,
    current_package_hash: str,
    current_package_failures: list[str],
    required: bool,
) -> None:
    if verifier_result is None or coverage_result is None:
        passed = verifier_result is not None and coverage_result is None and not required
        validator_results.append(
            _validator_result(
                "acceptance_coverage_fresh",
                passed,
                "Acceptance coverage is not required and is absent; freshness is not applicable."
                if passed
                else "Cannot prove acceptance coverage freshness without both verifier and coverage results.",
                {"required": required},
            )
        )
        return
    failures: list[str] = []
    if coverage_result.verification_result_hash != verifier_hash:
        failures.append("coverage verification_result_hash does not match current verifier result file")
    if coverage_result.verification_result_ref != SKILLFOUNDRY_VERIFICATION_RESULT_REF:
        failures.append("coverage verification_result_ref does not point to the SkillFoundry verifier result")
    if coverage_result.job_id != workspace.job_id:
        failures.append("coverage job_id does not match current workspace job_id")
    if coverage_result.package_hash != verifier_result.package_hash:
        failures.append("coverage package_hash does not match verifier package_hash")
    if current_package_failures:
        failures.extend(f"current package hash failure: {failure}" for failure in current_package_failures)
    if coverage_result.package_hash != current_package_hash:
        failures.append("coverage package_hash does not match current package hash")
    if coverage_result.job_id != verifier_result.job_id:
        failures.append("coverage job_id does not match verifier job_id")
    failures.extend(_hash_ref_freshness_failures(workspace, coverage_result.acceptance_criteria_ref, coverage_result.acceptance_criteria_hash))
    failures.extend(_hash_ref_freshness_failures(workspace, coverage_result.coverage_plan_ref, coverage_result.coverage_plan_hash))
    if coverage_result.qa_report_ref is not None:
        if coverage_result.qa_report_hash is None:
            failures.append("coverage qa_report_ref is set but qa_report_hash is missing")
        else:
            failures.extend(_hash_ref_freshness_failures(workspace, coverage_result.qa_report_ref, coverage_result.qa_report_hash))
    validator_results.append(
        _validator_result(
            "acceptance_coverage_fresh",
            not failures,
            "Acceptance coverage is fresh for the current verifier result."
            if not failures
            else "Acceptance coverage is stale or inconsistent.",
            {
                "failures": failures,
                "coverage_verification_result_hash": coverage_result.verification_result_hash,
                "actual_verification_result_hash": verifier_hash,
                "coverage_package_hash": coverage_result.package_hash,
                "verifier_package_hash": verifier_result.package_hash,
                "current_package_hash": current_package_hash,
                "coverage_job_id": coverage_result.job_id,
                "workspace_job_id": workspace.job_id,
                "verifier_job_id": verifier_result.job_id,
            },
        )
    )


def _hash_ref_freshness_failures(workspace: JobWorkspace, ref: str, expected_hash: str) -> list[str]:
    try:
        path = workspace.resolve_path(ref, must_exist=True)
        actual_hash = sha256_file(path)
    except Exception as exc:
        return [f"{ref}: referenced evidence is missing or unsafe: {exc}"]
    if actual_hash != expected_hash:
        return [f"{ref}: hash does not match coverage result"]
    return []


def _check_worker_self_report_not_acceptance(
    workspace: JobWorkspace,
    validator_results: list[ValidatorResult],
) -> None:
    report_refs = sorted(
        str(path.relative_to(workspace.root)) for path in (workspace.root / "attempts").glob("**/*report*.json")
    )
    validator_results.append(
        _validator_result(
            "worker_self_report_not_acceptance",
            True,
            "Worker self-report is recorded only as worker evidence and is never treated as acceptance.",
            {"worker_report_refs": report_refs},
        )
    )


def _check_unsupported_gate_fields(
    verification_gate: VerificationGate,
    validator_results: list[ValidatorResult],
) -> None:
    validator_results.append(
        _validator_result(
            "contextforge_gate_metric_gates_supported",
            not verification_gate.metric_gates,
            "Verification gate does not contain metric_gates."
            if not verification_gate.metric_gates
            else "Verification gate metric_gates are not evaluated by this bridge slice.",
            {"metric_gate_count": len(verification_gate.metric_gates)},
        )
    )


def _run_contextforge_gate(
    workspace: JobWorkspace,
    verification_gate: VerificationGate,
    validator_results: list[ValidatorResult],
    *,
    goal_run_id: str | None,
    worker_id: str | None,
    created_at: str,
) -> ContextForgeVerificationResult | None:
    try:
        gate_result = VerificationRunner(workspace.root, allow_commands=False).run(
            verification_gate,
            goal_run_id=goal_run_id,
            worker_id=worker_id,
            created_at=created_at,
        )
    except Exception as exc:
        validator_results.append(
            _validator_result(
                "contextforge_gate_runner_completed",
                False,
                f"ContextForge VerificationRunner failed: {exc}",
                {"verification_gate_id": verification_gate.verification_gate_id},
            )
        )
        return None

    validator_results.append(
        _validator_result(
            "contextforge_gate_runner_completed",
            True,
            "ContextForge VerificationRunner completed.",
            {
                "verification_result_id": gate_result.verification_result_id,
                "status": gate_result.status,
                "passed": gate_result.passed,
            },
        )
    )
    return gate_result


def _status_for_bridge(
    bridge_validator_results: list[ValidatorResult],
    contextforge_gate_result: ContextForgeVerificationResult | None,
) -> str:
    failed = [item for item in bridge_validator_results if item.severity == "blocking" and not item.passed]
    if failed:
        return "failed"
    if contextforge_gate_result is not None:
        return contextforge_gate_result.status
    return "failed"


def _hash_current_workspace_file(workspace: JobWorkspace, relative_path: str) -> str | None:
    try:
        return sha256_file(workspace.resolve_path(relative_path, must_exist=True))
    except Exception:
        return None


def _hash_current_package(workspace: JobWorkspace) -> tuple[str, list[str]]:
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


def _validator_result(
    validator_id: str,
    passed: bool,
    message: str,
    evidence: dict[str, JsonValue],
    *,
    validator_type: str | None = None,
    severity: str = "blocking",
    metadata: dict[str, JsonValue] | None = None,
) -> ValidatorResult:
    return ValidatorResult(
        validator_id=validator_id,
        type=validator_type or validator_id,
        mode="executable",
        severity=severity,  # type: ignore[arg-type]
        passed=passed,
        message=message,
        evidence=evidence,
        metadata=metadata or {},
    )


def _contextforge_result_id(
    *,
    workspace: JobWorkspace,
    verification_gate: VerificationGate,
    goal_run_id: str | None,
    status: str,
    validator_results: list[ValidatorResult],
    created_at: str,
) -> str:
    return "cf-verification-" + sha256_json(
        {
            "job_id": workspace.job_id,
            "verification_gate_id": verification_gate.verification_gate_id,
            "gate_hash": verification_gate.gate_hash,
            "goal_run_id": goal_run_id,
            "status": status,
            "validator_results": [item.to_dict() for item in validator_results],
            "created_at": created_at,
        }
    )[:24]


def _write_contextforge_result(
    workspace: JobWorkspace,
    output_ref: str,
    result: ContextForgeVerificationResult,
) -> None:
    payload = ensure_json_compatible(result.to_dict())
    if not isinstance(payload, dict):
        raise ValueError("ContextForge VerificationResult payload must be a JSON object")
    path = _resolve_output_path_for_write(workspace, output_ref)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _resolve_output_path_for_write(workspace: JobWorkspace, output_ref: str):
    relative = validate_relative_path(output_ref)
    root = workspace.root.resolve(strict=True)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise PathSecurityError(f"symlink components are not allowed: {current}")
            assert_under_root(root, current)
            if not current.is_dir():
                raise PathSecurityError(f"output parent is not a directory: {current}")
            continue
        current.mkdir()
    target = current / relative.name
    if target.exists() or target.is_symlink():
        if target.is_symlink():
            raise PathSecurityError(f"symlink output path is not allowed: {target}")
        assert_under_root(root, target)
    return target
