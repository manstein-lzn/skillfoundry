#!/usr/bin/env python3
"""Run a deterministic fresh-clone smoke for SkillFoundry.

The check intentionally uses a new virtualenv and the public dependency path
instead of the current checkout's .venv or local sibling ForgeUnit directory.
It never calls live Codex; the semantic eval runs with ``--fake-mode happy``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence


DEFAULT_REPO_URL = "git@github.com:manstein-lzn/skillfoundry.git"
DEFAULT_EVAL_ID = "phase10-fresh-clone-smoke"


class FreshCloneError(RuntimeError):
    """Raised when a fresh-clone readiness step fails."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--eval-id", default=DEFAULT_EVAL_ID)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args(argv)

    temp_root = args.work_root or Path(tempfile.mkdtemp(prefix="skillfoundry-fresh-clone-"))
    clone_dir = temp_root / "skillfoundry"
    try:
        if temp_root.exists() and args.work_root:
            shutil.rmtree(temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)

        run(["git", "clone", "--recurse-submodules", "--branch", args.branch, args.repo_url, str(clone_dir)])
        venv_dir = clone_dir / ".venv"
        run([args.python, "-m", "venv", str(venv_dir)])
        python = venv_dir / "bin" / "python"
        run([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=clone_dir)
        run([str(python), "-m", "pip", "install", "-e", "third_party/contextforge"], cwd=clone_dir)
        run([str(python), "-m", "pip", "install", "-e", ".[test,forgeunit]"], cwd=clone_dir)
        run(
            [
                str(python),
                "-m",
                "pytest",
                "tests/test_frontdesk_live_codex_eval_script.py",
                "-q",
            ],
            cwd=clone_dir,
        )

        runs_root = clone_dir / ".local" / "fresh_clone_gate_runs"
        run(
            [
                str(python),
                "scripts/run_frontdesk_live_codex_eval.py",
                "--runs-root",
                str(runs_root),
                "--eval-id",
                args.eval_id,
                "--registry-path",
                "registry.json",
                "--fake-mode",
                "happy",
                "--limit",
                str(args.limit),
                "--created-at",
                "2026-05-23T00:00:00Z",
                "--overwrite",
            ],
            cwd=clone_dir,
        )
        summary_path = runs_root / args.eval_id / "eval_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        totals = summary.get("totals")
        if not isinstance(totals, dict):
            raise FreshCloneError("fresh clone eval summary is missing totals")
        if totals.get("registered") != args.limit:
            raise FreshCloneError(f"fresh clone registered count mismatch: {totals.get('registered')!r}")
        if totals.get("semantic_fidelity_failed") != 0:
            raise FreshCloneError("fresh clone semantic fidelity failed")
        if totals.get("redaction_failures") != 0:
            raise FreshCloneError("fresh clone redaction check failed")

        if args.summary_out:
            args.summary_out.parent.mkdir(parents=True, exist_ok=True)
            args.summary_out.write_text(
                json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "clone_dir": str(clone_dir),
                    "summary_ref": str(summary_path),
                    "totals": totals,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except FreshCloneError as exc:
        print(f"fresh clone readiness failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if not args.keep and temp_root.exists():
            shutil.rmtree(temp_root)


def run(command: Sequence[str], *, cwd: Path | None = None) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True)
    if completed.returncode != 0:
        rendered = " ".join(command)
        raise FreshCloneError(f"command failed with exit {completed.returncode}: {rendered}")


if __name__ == "__main__":
    raise SystemExit(main())
