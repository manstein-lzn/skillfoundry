import pytest

import skillfoundry
from skillfoundry.schema import (
    ApprovalRecord,
    ArtifactManifest,
    ArtifactRecord,
    BuildContract,
    ExecutionReport,
    RegistryEntry,
    RepairAttempt,
    SchemaValidationError,
    SkillSpec,
    VerificationResult,
    VerificationSpec,
    WorkerInvocation,
    sha256_json,
    utc_now,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def sample_objects():
    record = ArtifactRecord(
        artifact_id="artifact-1",
        path="skill_spec.yaml",
        kind="locked_input",
        sha256=HASH_A,
        created_by="test",
        created_at=utc_now(),
        job_id="job-1",
        attempt_id=None,
        locked=True,
    )
    return [
        SkillSpec(
            skill_id="demo",
            title="Demo",
            description="Demo skill.",
            trigger_scenarios=["trigger"],
            non_trigger_scenarios=["non-trigger"],
            required_inputs=["input"],
            expected_outputs=["output"],
            constraints=["constraint"],
            acceptance_criteria=["acceptance"],
            reference_materials=["ref"],
            security_notes=["note"],
        ),
        BuildContract(
            job_id="job-1",
            skill_spec_ref="skill_spec.yaml",
            verification_spec_ref="verification_spec.yaml",
            workspace_root="runs/job-1",
            allowed_write_paths=["package", "attempts"],
            blocked_paths=[".."],
            timeout_seconds=300,
            attempt_limit=2,
            required_artifacts=["skill_spec.yaml"],
            locked_input_hashes={"skill_spec.yaml": HASH_A},
        ),
        VerificationSpec(
            spec_id="verification-1",
            job_id="job-1",
            required_checks=["schema"],
            artifact_requirements=["artifact_manifest.json"],
            path_policies=["reject_absolute_paths"],
            acceptance_criteria=["all checks pass"],
            verifier_version="test",
        ),
        WorkerInvocation(
            invocation_id="inv-1",
            job_id="job-1",
            attempt_id="001",
            worker_type="fake",
            adapter_version="test",
            input_manifest_hash=HASH_A,
            workspace_hash_before=HASH_B,
            workspace_hash_after=HASH_C,
            started_at=utc_now(),
            finished_at=utc_now(),
            duration_ms=1,
            usage_available=False,
            usage_unavailable_reason="fake worker has no usage data",
            transcript_ref="attempts/001/worker_transcript.log",
            execution_report_ref="attempts/001/execution_report.json",
            diff_ref="attempts/001/output_diff.patch",
            exit_status="success",
        ),
        ExecutionReport(
            report_id="report-1",
            invocation_id="inv-1",
            job_id="job-1",
            attempt_id="001",
            status="completed",
            started_at=utc_now(),
            finished_at=utc_now(),
            duration_ms=1,
            exit_status="success",
            summary="Completed.",
            artifacts=["package/SKILL.md"],
            failures=[],
        ),
        VerificationResult(
            result_id="result-1",
            job_id="job-1",
            package_hash=HASH_A,
            verification_spec_hash=HASH_B,
            passed=False,
            checks=[{"name": "schema", "passed": False}],
            failures=["missing SKILL.md"],
            evidence_refs=["verifier/static_report.json"],
            verifier_version="test",
            created_at=utc_now(),
        ),
        RepairAttempt(
            attempt_id="002",
            job_id="job-1",
            based_on_result_id="result-1",
            repair_instructions_ref="attempts/002/repair.md",
            status="planned",
            created_at=utc_now(),
            input_hashes={"verification_result.json": HASH_A},
            output_refs=["attempts/002/execution_report.json"],
        ),
        record,
        ArtifactManifest(job_id="job-1", artifacts=[record], created_at=utc_now()),
        RegistryEntry(
            skill_id="demo",
            version="0.1.0",
            package_path="package",
            package_hash=HASH_A,
            build_job_id="job-1",
            worker_invocation_id="inv-1",
            verification_spec_hash=HASH_B,
            verification_result_hash=HASH_C,
            artifact_manifest_hash=HASH_A,
            verifier_version="test",
            approval_status="pending",
            review_status="not_reviewed",
            created_at=utc_now(),
            provenance={"job_id": "job-1"},
            quarantine_status="none",
        ),
        ApprovalRecord(
            approval_id="approval-1",
            registry_entry_ref="registry/demo/0.1.0",
            status="pending",
            reviewer="test",
            reason="test fixture",
            created_at=utc_now(),
            evidence_refs=["verifier/verification_result.json"],
        ),
    ]


def test_package_imports():
    assert skillfoundry.SkillSpec is SkillSpec


@pytest.mark.parametrize("obj", sample_objects())
def test_schema_json_round_trip(obj):
    loaded = obj.__class__.from_json(obj.to_json())
    assert loaded.to_dict() == obj.to_dict()


@pytest.mark.parametrize("obj", sample_objects())
def test_schema_yaml_round_trip(obj):
    loaded = obj.__class__.from_yaml(obj.to_yaml())
    assert loaded.to_dict() == obj.to_dict()


def test_canonical_json_hash_is_stable():
    left = {"b": [2, 1], "a": {"x": True}}
    right = {"a": {"x": True}, "b": [2, 1]}
    assert sha256_json(left) == sha256_json(right)


def test_missing_required_field_raises_validation_error():
    payload = sample_objects()[0].to_dict()
    payload.pop("title")
    with pytest.raises(SchemaValidationError):
        SkillSpec.from_dict(payload)


def test_non_json_payload_raises_validation_error():
    obj = sample_objects()[0]
    obj.reference_materials = [{"not-json-compatible"}]  # type: ignore[list-item]
    with pytest.raises(SchemaValidationError):
        obj.to_dict()
