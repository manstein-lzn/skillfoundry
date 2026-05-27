"""Worker backend comparison helpers for PiWorker experiments."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal, Protocol

from .adaptive_graph import (
    AdaptiveGraphConfig,
    AdaptiveGraphResult,
    AdaptiveWorkUnit,
    adaptive_work_unit_result_ref,
    run_adaptive_graph,
)


WorkerBackendName = Literal["codex", "pi", "fake"]


class AdaptiveWorkerFactory(Protocol):
    def __call__(self, backend: WorkerBackendName) -> AdaptiveWorkUnit:
        """Return the worker callable for one backend name."""


@dataclass(frozen=True)
class WorkerBackendMetrics:
    backend: WorkerBackendName
    job_id: str
    status: str
    latest_route: str
    latest_decision: str
    iterations: int
    produced_ref_count: int
    changed_ref_count: int
    pi_event_ref_count: int
    pi_metric_ref_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "job_id": self.job_id,
            "status": self.status,
            "latest_route": self.latest_route,
            "latest_decision": self.latest_decision,
            "iterations": self.iterations,
            "produced_ref_count": self.produced_ref_count,
            "changed_ref_count": self.changed_ref_count,
            "pi_event_ref_count": self.pi_event_ref_count,
            "pi_metric_ref_count": self.pi_metric_ref_count,
        }


@dataclass(frozen=True)
class WorkerBackendComparison:
    scenario: str
    left: WorkerBackendMetrics
    right: WorkerBackendMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }


def run_worker_backend_comparison(
    runs_root: Path,
    *,
    scenario: str,
    left_backend: WorkerBackendName,
    right_backend: WorkerBackendName,
    worker_factory: AdaptiveWorkerFactory,
    max_iterations: int = 3,
) -> WorkerBackendComparison:
    """Run the same adaptive graph scenario with two worker backends."""

    left = _run_backend(
        runs_root,
        scenario=scenario,
        backend=left_backend,
        worker=worker_factory(left_backend),
        max_iterations=max_iterations,
    )
    right = _run_backend(
        runs_root,
        scenario=scenario,
        backend=right_backend,
        worker=worker_factory(right_backend),
        max_iterations=max_iterations,
    )
    return WorkerBackendComparison(scenario=scenario, left=left, right=right)


def worker_backend_comparison_report(comparison: WorkerBackendComparison) -> dict[str, object]:
    """Return a JSON-safe worker comparison report."""

    return {
        "schema_version": "forgeunit_skillfoundry.worker_backend_comparison.v1",
        "comparison_axis": "same_contract_same_verifier_different_worker_backend",
        "comparison": comparison.to_dict(),
    }


def write_worker_backend_comparison_report(path: Path, comparison: WorkerBackendComparison) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(worker_backend_comparison_report(comparison), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_backend(
    runs_root: Path,
    *,
    scenario: str,
    backend: WorkerBackendName,
    worker: AdaptiveWorkUnit,
    max_iterations: int,
) -> WorkerBackendMetrics:
    job_id = f"{scenario}-{backend}"
    result = run_adaptive_graph(
        AdaptiveGraphConfig(runs_root=runs_root, job_id=job_id, max_iterations=max_iterations),
        worker=worker,
    )
    return _collect_metrics(result, backend=backend)


def _collect_metrics(result: AdaptiveGraphResult, *, backend: WorkerBackendName) -> WorkerBackendMetrics:
    contextforge = result.state.get("contextforge", {})
    workspace_root = result.workspace_root
    iterations = int(contextforge.get("adaptive_latest_iteration", 0)) if isinstance(contextforge, dict) else 0
    produced_ref_count = 0
    changed_ref_count = 0
    for iteration in range(1, iterations + 1):
        result_path = workspace_root / adaptive_work_unit_result_ref(iteration)
        if not result_path.is_file():
            continue
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            produced_ref_count += _list_count(payload.get("produced_artifacts"))
            changed_ref_count += _list_count(payload.get("changed_refs"))
    return WorkerBackendMetrics(
        backend=backend,
        job_id=result.job_id,
        status=str(result.state.get("status", "")),
        latest_route=str(contextforge.get("adaptive_latest_route", "")) if isinstance(contextforge, dict) else "",
        latest_decision=str(contextforge.get("adaptive_latest_decision", "")) if isinstance(contextforge, dict) else "",
        iterations=iterations,
        produced_ref_count=produced_ref_count,
        changed_ref_count=changed_ref_count,
        pi_event_ref_count=len(list(workspace_root.glob("adaptive/attempts/*/pi_events.jsonl"))),
        pi_metric_ref_count=len(list(workspace_root.glob("adaptive/attempts/*/pi_metrics.json"))),
    )


def _list_count(value: object) -> int:
    if not isinstance(value, list):
        return 0
    return sum(1 for item in value if isinstance(item, str) and item)
