import pytest

from skillfoundry.adaptive import (
    CapabilityStateEstimate,
    DecisionLedger,
    DecisionRecord,
    NextStepContract,
    ObservationReport,
    RoutePlan,
    StateCorrection,
)
from skillfoundry.schema import SchemaValidationError


def sample_state() -> CapabilityStateEstimate:
    return CapabilityStateEstimate(
        job_id="job-1",
        iteration=1,
        objective="Build a verified capability bundle.",
        current_phase="build",
        known_good=["Frozen spec exists."],
        known_bad=["No bundle manifest yet."],
        known_unknowns=["Runtime assets are not selected."],
        current_risks=["The next step may be too broad."],
        latest_verification_status="not_run",
        next_best_step="Create the bundle manifest contract.",
        confidence=0.65,
        metadata={"source": "test"},
    )


def sample_contract() -> NextStepContract:
    return NextStepContract(
        job_id="job-1",
        iteration=1,
        current_state_ref="adaptive/capability_state.json",
        next_objective="Create a bundle manifest draft.",
        why_now="The verifier needs a machine-readable capability boundary.",
        allowed_scope=["package", "adaptive/attempts/001"],
        visible_refs=["skill_spec.yaml", "verification_spec.yaml"],
        expected_outputs=["package/skillfoundry.bundle.json", "adaptive/attempts/001/notes.md"],
        exit_criteria=["Manifest validates against the MVP schema."],
        stop_conditions=["The spec contradicts the selected bundle profile."],
        route_plan_ref="adaptive/route_plan_000.json",
        estimated_followups=["Connect manifest checks to the verifier."],
        risk_if_too_large="Combining manifest and verifier work hides contract errors.",
        risk_if_too_small="Only naming fields without path checks would not reduce risk.",
        metadata={"policy": {"mode": "deterministic"}},
    )


def sample_observation() -> ObservationReport:
    return ObservationReport(
        job_id="job-1",
        iteration=1,
        contract_ref="adaptive/next_step_contract_001.json",
        produced_artifacts=["package/skillfoundry.bundle.json"],
        changed_refs=["package/skillfoundry.bundle.json"],
        commands_run=["python -m pytest tests/test_bundle_manifest.py -q"],
        tests_run=["tests/test_bundle_manifest.py"],
        failures=[],
        worker_claims=["Manifest schema was drafted."],
        verifier_evidence=["adaptive/attempts/001/verifier_evidence.json"],
        new_unknowns=["Verifier integration is not implemented."],
        recommended_next_steps=["Add bundle verifier checks."],
        metadata={"attempt_id": "001"},
    )


def sample_route_plan() -> RoutePlan:
    return RoutePlan(
        job_id="job-1",
        iteration=1,
        mission="Build a verified capability bundle.",
        current_strategy="Plan first, execute one bounded step, then revise from observation.",
        phase_plan=["Create entrypoint.", "Create bundle manifest.", "Verify closure."],
        plan_b=["Shrink to repair on failure.", "Escalate after repeated failure."],
        assumptions=["Refs are the durable handoff surface."],
        pivot_triggers=["Verifier failure.", "New unknown.", "Worker recommendation."],
        risk_register=["Worker self-report is not acceptance."],
        evidence_strategy=["Use verifier evidence refs."],
        authority_boundary=["Worker tactics stay inside allowed scope."],
        next_step_policy=["Issue one artifact-producing next-step contract."],
        based_on_observation_ref="adaptive/observation_report_001.json",
        previous_route_plan_ref="adaptive/route_plan_000.json",
        revision_reason="Observation changed the next-step policy.",
        metadata={"source": "test"},
    )


def sample_correction() -> StateCorrection:
    return StateCorrection(
        job_id="job-1",
        iteration=1,
        previous_state_ref="adaptive/capability_state_before.json",
        observation_ref="adaptive/observation_report_001.json",
        corrected_state_ref="adaptive/capability_state.json",
        decision="continue",
        rationale="The manifest contract exists and the next risk is verifier integration.",
        next_route="continue",
        metadata={"confidence_delta": 0.1},
    )


def sample_decision() -> DecisionRecord:
    return DecisionRecord(
        decision_id="decision-001",
        iteration=1,
        context="Bundle profile is known, but manifest checks are absent.",
        options=["Create manifest first.", "Create verifier first."],
        chosen_option="Create manifest first.",
        rationale="The verifier needs a stable manifest schema to check.",
        risk="The schema may need adjustment after verifier implementation.",
        expected_evidence=["package/skillfoundry.bundle.json"],
        fallback="Patch the manifest schema after verifier failures.",
        reviewer="deterministic-policy",
        metadata={"route": "continue"},
    )


def sample_ledger() -> DecisionLedger:
    return DecisionLedger(job_id="job-1", decisions=[sample_decision()], metadata={"owner": "adaptive-loop"})


@pytest.mark.parametrize(
    "obj",
    [
        sample_state(),
        sample_route_plan(),
        sample_contract(),
        sample_observation(),
        sample_correction(),
        sample_decision(),
        sample_ledger(),
    ],
)
def test_adaptive_schema_json_round_trip(obj):
    loaded = obj.__class__.from_json(obj.to_json())

    assert loaded.to_dict() == obj.to_dict()


@pytest.mark.parametrize(
    "obj",
    [
        sample_state(),
        sample_route_plan(),
        sample_contract(),
        sample_observation(),
        sample_correction(),
        sample_decision(),
        sample_ledger(),
    ],
)
def test_adaptive_schema_unknown_fields_fail(obj):
    payload = obj.to_dict()
    payload["unexpected"] = True

    with pytest.raises(SchemaValidationError):
        obj.__class__.from_dict(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"metadata": {"prompt": "raw prompt must not be persisted"}},
        {"metadata": {"nested": {"messages": []}}},
        {"metadata": {"nested": [{"raw_model_output": "done"}]}},
    ],
)
def test_adaptive_schema_forbidden_raw_fields_fail(payload):
    data = sample_state().to_dict()
    data.update(payload)

    with pytest.raises(SchemaValidationError):
        CapabilityStateEstimate.from_dict(data)


@pytest.mark.parametrize(
    "payload",
    [
        {"metadata": {"prompt": "raw prompt must not be persisted"}},
        {"metadata": {"nested": {"messages": []}}},
        {"metadata": {"nested": [{"raw_model_output": "done"}]}},
    ],
)
def test_route_plan_forbidden_raw_fields_fail(payload):
    data = sample_route_plan().to_dict()
    data.update(payload)

    with pytest.raises(SchemaValidationError):
        RoutePlan.from_dict(data)


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("current_state_ref", "../adaptive/state.json"),
        ("current_state_ref", "/tmp/state.json"),
        ("route_plan_ref", "adaptive/../route_plan.json"),
        ("allowed_scope", ["package", "../outside"]),
        ("visible_refs", ["C:\\temp\\secret.txt"]),
        ("expected_outputs", ["package//bundle.json"]),
    ],
)
def test_next_step_contract_rejects_unsafe_refs(field_name, value):
    payload = sample_contract().to_dict()
    payload[field_name] = value

    with pytest.raises(SchemaValidationError):
        NextStepContract.from_dict(payload)


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("contract_ref", "../adaptive/contract.json"),
        ("produced_artifacts", ["/tmp/output.json"]),
        ("changed_refs", ["package/../bad"]),
        ("verifier_evidence", ["adaptive//evidence.json"]),
    ],
)
def test_observation_report_rejects_unsafe_refs(field_name, value):
    payload = sample_observation().to_dict()
    payload[field_name] = value

    with pytest.raises(SchemaValidationError):
        ObservationReport.from_dict(payload)


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("based_on_observation_ref", "../adaptive/observation.json"),
        ("previous_route_plan_ref", "/tmp/route_plan.json"),
    ],
)
def test_route_plan_rejects_unsafe_optional_refs(field_name, value):
    payload = sample_route_plan().to_dict()
    payload[field_name] = value

    with pytest.raises(SchemaValidationError):
        RoutePlan.from_dict(payload)


@pytest.mark.parametrize(
    "obj",
    [
        CapabilityStateEstimate(
            job_id="job-1",
            iteration=-1,
            objective="Build.",
            current_phase="build",
            next_best_step="Continue.",
        ),
        CapabilityStateEstimate(
            job_id="job-1",
            iteration=1,
            objective="Build.",
            current_phase="build",
            next_best_step="Continue.",
            confidence=1.01,
        ),
        StateCorrection(
            job_id="job-1",
            iteration=1,
            previous_state_ref="adaptive/old.json",
            observation_ref="adaptive/observation.json",
            corrected_state_ref="adaptive/new.json",
            decision="maybe",
            rationale="Unsupported route.",
            next_route="continue",
        ),
        StateCorrection(
            job_id="job-1",
            iteration=1,
            previous_state_ref="adaptive/old.json",
            observation_ref="adaptive/observation.json",
            corrected_state_ref="adaptive/new.json",
            decision="continue",
            rationale="Unsupported route.",
            next_route="maybe",
        ),
        NextStepContract(
            job_id="job-1",
            iteration=1,
            current_state_ref="adaptive/capability_state.json",
            next_objective="Create a bundle manifest draft.",
            why_now="The verifier needs a machine-readable capability boundary.",
            risk_if_too_large="",
            risk_if_too_small="Skipping the manifest would not reduce risk.",
            allowed_scope=["package"],
            visible_refs=["skill_spec.yaml"],
            expected_outputs=["package/skillfoundry.bundle.json"],
            exit_criteria=["Manifest exists."],
            stop_conditions=["Spec contradiction found."],
        ),
        RoutePlan(
            job_id="job-1",
            iteration=1,
            mission="Build.",
            current_strategy="",
            phase_plan=["Create entrypoint."],
            plan_b=["Repair on failure."],
            assumptions=["Refs are durable."],
            pivot_triggers=["Failure."],
            risk_register=["Scope drift."],
            evidence_strategy=["Verifier refs."],
            authority_boundary=["Stay in scope."],
            next_step_policy=["One step."],
        ),
    ],
)
def test_adaptive_schema_invalid_values_fail(obj):
    with pytest.raises(SchemaValidationError):
        obj.to_dict()


def test_decision_ledger_converts_nested_records_from_dict():
    payload = sample_ledger().to_dict()

    loaded = DecisionLedger.from_dict(payload)

    assert isinstance(loaded.decisions[0], DecisionRecord)
    assert loaded.to_dict() == payload


def test_decision_ledger_rejects_duplicate_decision_ids():
    decision = sample_decision()
    ledger = DecisionLedger(job_id="job-1", decisions=[decision, decision])

    with pytest.raises(SchemaValidationError):
        ledger.to_dict()


def test_decision_ledger_rejects_forbidden_nested_decision_metadata():
    payload = sample_ledger().to_dict()
    payload["decisions"][0]["metadata"] = {"raw_transcript": "not allowed"}

    with pytest.raises(SchemaValidationError):
        DecisionLedger.from_dict(payload)
