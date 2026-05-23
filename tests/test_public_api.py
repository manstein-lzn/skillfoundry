import skillfoundry
import skillfoundry.frontdesk_goal_runtime as frontdesk_goal_runtime
import skillfoundry.goal_runtime as goal_runtime


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
