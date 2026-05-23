#!/usr/bin/env python3
"""Run the manual ForgeUnit real Codex exec pilot.

This runner is not used by default tests. It is a local integration probe for
checking whether a real Codex-compatible command can satisfy the ForgeUnit
boundary contract and then pass SkillFoundry verifier/registry gates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys
from typing import Any

from skillfoundry import initialize_job_workspace, run_forgeunit_command_bridge_pilot_graph


DEFAULT_JOB_ID = "forgeunit-real-codex-pilot-001"
DEFAULT_VERSION = "real-codex-pilot"
DEFAULT_WORKER_INPUT = """# Worker Input

Build a minimal Codex Skill package for a deterministic demo skill.

The package must satisfy the SkillFoundry verifier by including these sections:
Overview, When To Use, When Not To Use, Inputs, Outputs, Workflow, Safety.

Keep raw prompts, raw transcripts, and private worker input out of graph state.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a manual ForgeUnit real Codex exec pilot.")
    parser.add_argument("--runs-root", default="runs", help="SkillFoundry runs root.")
    parser.add_argument("--job-id", default=DEFAULT_JOB_ID, help="Pilot job id.")
    parser.add_argument("--registry-path", default=".local/forgeunit_codex_pilot_registry.json")
    parser.add_argument("--version", default=DEFAULT_VERSION, help="Registry version for the pilot package.")
    parser.add_argument("--codex-command", default=None, help="Override Codex-compatible command.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete the existing pilot workspace before running.",
    )
    args = parser.parse_args(argv)

    runs_root = Path(args.runs_root)
    workspace_root = runs_root / args.job_id
    if workspace_root.exists():
        if not args.overwrite:
            print(
                f"workspace already exists: {workspace_root}; rerun with --overwrite to replace this pilot workspace",
                file=sys.stderr,
            )
            return 2
        shutil.rmtree(workspace_root)

    registry_path = Path(args.registry_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    workspace = initialize_job_workspace(
        runs_root,
        args.job_id,
        worker_input=DEFAULT_WORKER_INPUT,
    )

    wrapper = Path(__file__).with_name("forgeunit_codex_exec_worker.py").resolve()
    command_parts = [shlex.quote(sys.executable), shlex.quote(wrapper.as_posix())]
    if args.codex_command:
        command_parts.extend(["--codex-command", shlex.quote(args.codex_command)])
    command = " ".join(command_parts)

    state = run_forgeunit_command_bridge_pilot_graph(
        runs_root,
        workspace.job_id,
        registry_path=registry_path,
        command=command,
        version=args.version,
    )
    print(json.dumps(_summary(state), indent=2, sort_keys=True))
    return 0


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    contextforge = state.get("contextforge") if isinstance(state.get("contextforge"), dict) else {}
    refs = state.get("refs") if isinstance(state.get("refs"), dict) else {}
    return {
        "job_id": state.get("job_id"),
        "stage": state.get("stage"),
        "status": state.get("status"),
        "last_verification_status": contextforge.get("last_verification_status"),
        "registry_approved": contextforge.get("registry_approved"),
        "registry_skill_id": contextforge.get("registry_skill_id"),
        "registry_version": contextforge.get("registry_version"),
        "refs": {
            key: refs.get(key)
            for key in (
                "forgeunit_summary",
                "skillfoundry_verification_result",
                "registry_decision",
                "registry_entry",
                "final_report",
            )
            if refs.get(key)
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
