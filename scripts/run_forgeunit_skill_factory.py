#!/usr/bin/env python3
"""Run the clean ForgeUnit SkillFactory graph from the command line."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from forgeunit_skillfoundry import (
    read_evidence_summary,
    run_codex_skill_factory,
)
from forgeunit_skillfoundry.product import prepare_skill_factory_workspace
from forgeunit_skillfoundry.testing import (
    INVALID_CODEX_SKILL,
    VALID_CODEX_SKILL,
    write_fake_codex_exec_command,
)
from skillfoundry.registry import DEFAULT_REGISTRY_VERSION
from skillfoundry.workspace import JobWorkspace


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    runs_root = Path(args.runs_root)
    registry_path = Path(args.registry)
    command = args.command
    repair_command = args.repair_command

    if args.fake_mode != "none":
        workspace = prepare_skill_factory_workspace(
            runs_root,
            args.job_id,
            worker_input=args.worker_input,
            overwrite=args.overwrite_workspace,
        )
        if args.fake_mode == "happy":
            script = write_fake_codex_exec_command(workspace.root, script_name="fake_cli_codex_exec.py")
            command = f"{sys.executable} {script.name}"
            repair_command = None
        elif args.fake_mode == "repair":
            bad_script = write_fake_codex_exec_command(
                workspace.root,
                skill_text=INVALID_CODEX_SKILL,
                script_name="fake_cli_bad_codex_exec.py",
            )
            fixed_script = write_fake_codex_exec_command(
                workspace.root,
                skill_text=VALID_CODEX_SKILL,
                script_name="fake_cli_repair_codex_exec.py",
            )
            command = f"{sys.executable} {bad_script.name}"
            repair_command = f"{sys.executable} {fixed_script.name}"
    if not isinstance(command, str) or not command.strip():
        parser.error("--command is required unless --fake-mode is happy or repair")

    result = run_codex_skill_factory(
        runs_root,
        args.job_id,
        registry_path=registry_path,
        command=command,
        repair_command=repair_command,
        worker_input=args.worker_input,
        attempt_limit=args.attempt_limit,
        version=args.version,
        created_at=args.created_at,
        overwrite_workspace=args.overwrite_workspace and args.fake_mode == "none",
    )
    print(json.dumps(read_evidence_summary(_workspace_for_result(result)), indent=2, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", default="runs", help="Directory containing SkillFoundry job workspaces.")
    parser.add_argument("--job-id", required=True, help="Safe SkillFoundry job id.")
    parser.add_argument("--registry", required=True, help="Path to the local SkillFoundry registry JSON file.")
    parser.add_argument("--command", help="Explicit ForgeUnit command-bridge worker command.")
    parser.add_argument("--repair-command", help="Optional explicit repair command-bridge worker command.")
    parser.add_argument("--worker-input", help="Optional worker_input.md body for newly created workspaces.")
    parser.add_argument("--attempt-limit", type=int, default=2, help="Maximum SkillFoundry attempts.")
    parser.add_argument("--version", default=DEFAULT_REGISTRY_VERSION, help="Registry version for the produced skill.")
    parser.add_argument("--created-at", help="Optional deterministic timestamp for artifacts.")
    parser.add_argument(
        "--overwrite-workspace",
        action="store_true",
        help="Overwrite an existing workspace during initialization.",
    )
    parser.add_argument(
        "--fake-mode",
        choices=("none", "happy", "repair"),
        default="none",
        help="Write deterministic local fake command workers for offline smoke tests.",
    )
    return parser


def _workspace_for_result(result: object) -> JobWorkspace:
    return JobWorkspace(root=result.workspace_root, job_id=result.job_id)


if __name__ == "__main__":
    raise SystemExit(main())
