import skillfoundry
import skillfoundry.feedback as feedback
import skillfoundry.frontdesk_goal_runtime as frontdesk_goal_runtime
import skillfoundry.goal_runtime as goal_runtime
import skillfoundry.graph_v2 as graph_v2
import skillfoundry.ops as ops
import skillfoundry.qa as qa


PACKAGE_ROOT_INTERNAL_DENYLIST = {
    "FrontDeskCoreNeedFakeWorker",
    "FrontDeskSolutionPlannerFakeWorker",
    "FrontDeskSpecAuditorFakeWorker",
    "FrontDeskCoreNeedGoalHarnessResult",
    "FrontDeskSolutionPlannerGoalHarnessResult",
    "FrontDeskSpecAuditorGoalHarnessResult",
    "GoalHarnessWorkerFactory",
    "SkillFoundryGoalHarnessResult",
    "VerifiedSkillFoundryGoalHarnessResult",
    "RepairSkillFoundryGoalHarnessResult",
    "VerifiedRepairSkillFoundryGoalHarnessResult",
    "DEFAULT_REQUIRED_VERSION_GATES",
    "FEEDBACK_RECORD_VERSION",
    "FEEDBACK_REPAIR_PLAN_VERSION",
    "FEEDBACK_VERSIONING_PROVENANCE_VERSION",
    "ROLLBACK_EVENT_VERSION",
    "VERSION_CHANGE_REPORT_VERSION",
    "FeedbackRecord",
    "FeedbackRepairPlan",
    "FeedbackVersionGateError",
    "FeedbackVersioningError",
    "RepairRegistrationResult",
    "SkillVersionManager",
    "HARD_CHECK_NAMES",
    "QA_LAB_VERSION",
    "QA_REPORT_VERSION",
    "QACheck",
    "QALab",
    "QAResult",
    "OPS_CLEANUP_REPORT_VERSION",
    "OPS_HEALTH_REPORT_VERSION",
    "OPS_OBSERVABILITY_REPORT_VERSION",
    "OPS_VERSION",
    "SkillFoundryOps",
    "GOAL_RUNTIME_LEDGER_REF",
    "GOAL_RUNTIME_RESULT_REF",
    "GOAL_RUNTIME_RESULT_SCHEMA_VERSION",
    "GOAL_RUNTIME_STATE_REF",
    "GOAL_RUNTIME_STATE_SCHEMA_VERSION",
    "VERIFIED_GOAL_RUNTIME_RESULT_REF",
    "VERIFIED_GOAL_RUNTIME_RESULT_SCHEMA_VERSION",
    "build_goal_harness_state",
    "build_repair_goal_harness_state",
    "run_offline_goal_harness",
    "run_repair_goal_harness",
    "run_verified_repair_goal_harness",
    "run_verified_offline_goal_harness",
    "GRAPH_V2_STATE_REF",
    "MAX_V2_INLINE_STRING_BYTES",
    "SkillFoundryV2State",
    "V2Route",
    "V2Stage",
    "V2StateValidationError",
    "V2Status",
    "build_offline_goal_harness_node",
    "build_human_review_node",
    "build_repair_goal_harness_node",
    "build_skillfoundry_v2_graph",
    "build_verified_goal_harness_node",
    "build_verified_repair_verification_node",
    "build_verified_registry_gate_node",
    "compile_skillfoundry_v2_graph",
    "route_after_repair",
    "route_after_verification",
    "run_verified_skillfoundry_v2_graph",
    "validate_v2_graph_state",
}


def test_public_api_keeps_current_entrypoints_and_explicit_compatibility():
    for name in [
        "SkillFoundryAPI",
        "FrontDeskConfig",
        "FrontDeskState",
        "ConversationTurn",
        "FrontDeskWorkspace",
        "initialize_frontdesk_workspace",
        "append_conversation_turn",
        "read_conversation_turns",
        "build_goal_contract",
        "build_agent_node_contract",
        "build_verification_gate",
        "seed_goal_harness_context",
        "Verifier",
        "LocalSkillRegistry",
        "JobWorkspace",
        "SkillSpec",
        "VerificationSpec",
        "VerificationResult",
        "BuildContract",
        "ArtifactManifest",
        "build_offline",
        "OfflineWorkerMode",
    ]:
        assert hasattr(skillfoundry, name), name
        assert name in skillfoundry.__all__


def test_public_api_hides_internal_goal_runtime_types_from_package_root():
    leaked = [name for name in PACKAGE_ROOT_INTERNAL_DENYLIST if hasattr(skillfoundry, name)]
    assert leaked == []
    leaked_all = [name for name in PACKAGE_ROOT_INTERNAL_DENYLIST if name in skillfoundry.__all__]
    assert leaked_all == []


def test_internal_goal_runtime_types_remain_module_scoped_for_maintenance():
    for name in [
        "FrontDeskCoreNeedFakeWorker",
        "FrontDeskSolutionPlannerFakeWorker",
        "FrontDeskSpecAuditorFakeWorker",
        "FrontDeskCoreNeedGoalHarnessResult",
        "FrontDeskSolutionPlannerGoalHarnessResult",
        "FrontDeskSpecAuditorGoalHarnessResult",
    ]:
        assert hasattr(frontdesk_goal_runtime, name), name

    for name in [
        "GoalHarnessWorkerFactory",
        "SkillFoundryGoalHarnessResult",
        "VerifiedSkillFoundryGoalHarnessResult",
        "RepairSkillFoundryGoalHarnessResult",
        "VerifiedRepairSkillFoundryGoalHarnessResult",
    ]:
        assert hasattr(goal_runtime, name), name


def test_support_surfaces_remain_module_scoped_for_maintenance():
    for name in [
        "DEFAULT_REQUIRED_VERSION_GATES",
        "FEEDBACK_RECORD_VERSION",
        "FEEDBACK_REPAIR_PLAN_VERSION",
        "FEEDBACK_VERSIONING_PROVENANCE_VERSION",
        "ROLLBACK_EVENT_VERSION",
        "VERSION_CHANGE_REPORT_VERSION",
        "FeedbackRecord",
        "FeedbackRepairPlan",
        "FeedbackVersionGateError",
        "FeedbackVersioningError",
        "RepairRegistrationResult",
        "SkillVersionManager",
    ]:
        assert hasattr(feedback, name), name

    for name in [
        "HARD_CHECK_NAMES",
        "QA_LAB_VERSION",
        "QA_REPORT_VERSION",
        "QACheck",
        "QALab",
        "QAResult",
    ]:
        assert hasattr(qa, name), name

    for name in [
        "OPS_CLEANUP_REPORT_VERSION",
        "OPS_HEALTH_REPORT_VERSION",
        "OPS_OBSERVABILITY_REPORT_VERSION",
        "OPS_VERSION",
        "SkillFoundryOps",
    ]:
        assert hasattr(ops, name), name


def test_graph_and_goal_runtime_surfaces_remain_module_scoped_for_maintenance():
    for name in [
        "GOAL_RUNTIME_LEDGER_REF",
        "GOAL_RUNTIME_RESULT_REF",
        "GOAL_RUNTIME_RESULT_SCHEMA_VERSION",
        "GOAL_RUNTIME_STATE_REF",
        "GOAL_RUNTIME_STATE_SCHEMA_VERSION",
        "VERIFIED_GOAL_RUNTIME_RESULT_REF",
        "VERIFIED_GOAL_RUNTIME_RESULT_SCHEMA_VERSION",
        "build_goal_harness_state",
        "build_repair_goal_harness_state",
        "run_offline_goal_harness",
        "run_repair_goal_harness",
        "run_verified_repair_goal_harness",
        "run_verified_offline_goal_harness",
    ]:
        assert hasattr(goal_runtime, name), name

    assert hasattr(goal_runtime, "seed_goal_harness_context")
    assert hasattr(skillfoundry, "seed_goal_harness_context")
    assert "seed_goal_harness_context" in skillfoundry.__all__

    for name in [
        "GRAPH_V2_STATE_REF",
        "MAX_V2_INLINE_STRING_BYTES",
        "SkillFoundryV2State",
        "V2Route",
        "V2Stage",
        "V2StateValidationError",
        "V2Status",
        "build_offline_goal_harness_node",
        "build_human_review_node",
        "build_repair_goal_harness_node",
        "build_skillfoundry_v2_graph",
        "build_verified_goal_harness_node",
        "build_verified_repair_verification_node",
        "build_verified_registry_gate_node",
        "compile_skillfoundry_v2_graph",
        "route_after_repair",
        "route_after_verification",
        "run_verified_skillfoundry_v2_graph",
        "validate_v2_graph_state",
    ]:
        assert hasattr(graph_v2, name), name
