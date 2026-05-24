import pytest

from skillfoundry.adaptive import (
    CapabilityStateEstimate,
    DecisionRecord,
    NextStepContract,
    ObservationReport,
    StateCorrection,
)
from skillfoundry.adaptive_workspace import (
    ADAPTIVE_CAPABILITY_STATE_REF,
    ADAPTIVE_CREATED_BY,
    ADAPTIVE_DECISION_LEDGER_REF,
    ADAPTIVE_DIR,
    adaptive_contract_ref,
    adaptive_correction_ref,
    adaptive_observation_ref,
    append_decision_record,
    initialize_adaptive_workspace,
    read_capability_state_estimate,
    read_decision_ledger,
    read_next_step_contract,
    read_observation_report,
    read_state_correction,
    write_capability_state_estimate,
    write_next_step_contract,
    write_observation_report,
    write_state_correction,
)
from skillfoundry.schema import SchemaValidationError
from skillfoundry.security import PathSecurityError
from skillfoundry.workspace import LockedInputTamperError, initialize_job_workspace


def make_workspace(tmp_path):
    return initialize_job_workspace(tmp_path / "runs", "demo-001")


def sample_state(iteration: int = 1) -> CapabilityStateEstimate:
    return CapabilityStateEstimate(
        job_id="demo-001",
        iteration=iteration,
        objective="Build a verified capability bundle.",
        current_phase="build",
        known_good=["Frozen spec exists."],
        known_bad=["Bundle manifest is missing."],
        known_unknowns=["Verifier policy is incomplete."],
        current_risks=["Worker claims may exceed evidence."],
        latest_verification_status="not_run",
        next_best_step="Generate the next-step contract.",
        confidence=0.55,
    )


def sample_contract(iteration: int = 1) -> NextStepContract:
    return NextStepContract(
        job_id="demo-001",
        iteration=iteration,
        current_state_ref=ADAPTIVE_CAPABILITY_STATE_REF,
        next_objective="Create the bundle manifest.",
        why_now="The verifier needs a machine-readable capability boundary.",
        risk_if_too_large="Combining manifest and verifier changes would obscure failures.",
        risk_if_too_small="A naming-only change would not reduce verification risk.",
        allowed_scope=["package", f"adaptive/attempts/{iteration:03d}"],
        visible_refs=["skill_spec.yaml", "verification_spec.yaml"],
        expected_outputs=["package/skillfoundry.bundle.json"],
        exit_criteria=["Manifest file exists and can be parsed."],
        stop_conditions=["Spec contradiction found."],
        estimated_followups=["Connect manifest validation to verifier."],
    )


def sample_observation(iteration: int = 1) -> ObservationReport:
    return ObservationReport(
        job_id="demo-001",
        iteration=iteration,
        contract_ref=adaptive_contract_ref(iteration),
        produced_artifacts=["package/skillfoundry.bundle.json"],
        changed_refs=["package/skillfoundry.bundle.json"],
        commands_run=["python -m pytest tests/test_bundle_manifest.py -q"],
        tests_run=["tests/test_bundle_manifest.py"],
        failures=[],
        worker_claims=["A manifest was written."],
        verifier_evidence=["adaptive/attempts/001/verifier_evidence.json"],
        new_unknowns=["Verifier integration remains."],
        recommended_next_steps=["Add verifier checks."],
    )


def sample_correction(iteration: int = 1) -> StateCorrection:
    return StateCorrection(
        job_id="demo-001",
        iteration=iteration,
        previous_state_ref=ADAPTIVE_CAPABILITY_STATE_REF,
        observation_ref=adaptive_observation_ref(iteration),
        corrected_state_ref=ADAPTIVE_CAPABILITY_STATE_REF,
        decision="continue",
        rationale="The manifest exists, so the next risk is verifier integration.",
        next_route="continue",
    )


def sample_decision(decision_id: str = "decision-001") -> DecisionRecord:
    return DecisionRecord(
        decision_id=decision_id,
        iteration=1,
        context="Manifest is missing.",
        options=["Create manifest first.", "Create verifier first."],
        chosen_option="Create manifest first.",
        rationale="Verifier checks need a stable schema.",
        risk="Manifest fields may change after verifier integration.",
        expected_evidence=["package/skillfoundry.bundle.json"],
        fallback="Patch manifest schema after verifier feedback.",
    )


def test_initialize_adaptive_workspace_creates_directory_and_empty_ledger(tmp_path):
    workspace = make_workspace(tmp_path)
    adaptive = initialize_adaptive_workspace(workspace)

    assert adaptive.root == workspace.resolve_path(ADAPTIVE_DIR, must_exist=True)
    assert workspace.resolve_path("adaptive/attempts", must_exist=True).is_dir()
    ledger = read_decision_ledger(adaptive)
    assert ledger.job_id == workspace.job_id
    assert ledger.decisions == []

    record = workspace.read_manifest().record_for_path(ADAPTIVE_DECISION_LEDGER_REF)
    assert record is not None
    assert record.kind == "adaptive_artifact"
    assert record.created_by == ADAPTIVE_CREATED_BY
    assert record.locked is False
    workspace.check_locked_inputs()


def test_adaptive_iteration_refs_are_stable_and_validate_input():
    assert adaptive_contract_ref(1) == "adaptive/next_step_contract_001.json"
    assert adaptive_observation_ref(12) == "adaptive/observation_report_012.json"
    assert adaptive_correction_ref(123) == "adaptive/state_correction_123.json"

    with pytest.raises(ValueError):
        adaptive_contract_ref(-1)
    with pytest.raises(ValueError):
        adaptive_observation_ref(True)


def test_write_and_read_adaptive_artifacts_update_manifest(tmp_path):
    workspace = make_workspace(tmp_path)
    adaptive = initialize_adaptive_workspace(workspace)

    state_record = write_capability_state_estimate(adaptive, sample_state())
    contract_record = write_next_step_contract(workspace, sample_contract())
    observation_record = write_observation_report(adaptive, sample_observation())
    correction_record = write_state_correction(workspace, sample_correction())

    assert state_record.path == ADAPTIVE_CAPABILITY_STATE_REF
    assert contract_record.path == adaptive_contract_ref(1)
    assert observation_record.path == adaptive_observation_ref(1)
    assert correction_record.path == adaptive_correction_ref(1)

    assert read_capability_state_estimate(workspace).to_dict() == sample_state().to_dict()
    assert read_next_step_contract(adaptive, 1).to_dict() == sample_contract().to_dict()
    assert read_observation_report(workspace, 1).to_dict() == sample_observation().to_dict()
    assert read_state_correction(adaptive, 1).to_dict() == sample_correction().to_dict()

    manifest_paths = {record.path for record in workspace.read_manifest().artifacts}
    assert {
        ADAPTIVE_CAPABILITY_STATE_REF,
        adaptive_contract_ref(1),
        adaptive_observation_ref(1),
        adaptive_correction_ref(1),
        ADAPTIVE_DECISION_LEDGER_REF,
    }.issubset(manifest_paths)
    workspace.check_locked_inputs()


def test_append_decision_record_preserves_history_and_updates_manifest(tmp_path):
    workspace = make_workspace(tmp_path)
    initialize_adaptive_workspace(workspace)

    append_decision_record(workspace, sample_decision("decision-001"))
    append_decision_record(workspace, sample_decision("decision-002"))

    ledger = read_decision_ledger(workspace)
    assert [decision.decision_id for decision in ledger.decisions] == ["decision-001", "decision-002"]
    assert workspace.read_manifest().record_for_path(ADAPTIVE_DECISION_LEDGER_REF) is not None


def test_append_decision_record_rejects_duplicate_ids_without_mutating_ledger(tmp_path):
    workspace = make_workspace(tmp_path)
    initialize_adaptive_workspace(workspace)
    append_decision_record(workspace, sample_decision("decision-001"))

    with pytest.raises(SchemaValidationError):
        append_decision_record(workspace, sample_decision("decision-001"))

    ledger = read_decision_ledger(workspace)
    assert [decision.decision_id for decision in ledger.decisions] == ["decision-001"]


@pytest.mark.parametrize("bad_path", ["../escape.json", "/tmp/escape.json", "adaptive/../escape.json", "adaptive//bad.json"])
def test_adaptive_workspace_rejects_unsafe_paths(tmp_path, bad_path):
    workspace = make_workspace(tmp_path)
    adaptive = initialize_adaptive_workspace(workspace)

    with pytest.raises(PathSecurityError):
        adaptive.resolve_path(bad_path)


def test_adaptive_workspace_rejects_forbidden_raw_fields(tmp_path):
    workspace = make_workspace(tmp_path)
    initialize_adaptive_workspace(workspace)
    state = sample_state()
    state.metadata["raw_transcript"] = "not allowed"

    with pytest.raises(SchemaValidationError):
        write_capability_state_estimate(workspace, state)


def test_locked_input_checks_still_pass_after_adaptive_writes(tmp_path):
    workspace = make_workspace(tmp_path)
    initialize_adaptive_workspace(workspace)
    write_capability_state_estimate(workspace, sample_state())

    workspace.check_locked_inputs()

    worker_input = workspace.resolve_path("worker_input.md", must_exist=True)
    worker_input.write_text(worker_input.read_text(encoding="utf-8") + "\nTampered.\n", encoding="utf-8")
    with pytest.raises(LockedInputTamperError):
        workspace.check_locked_inputs()
