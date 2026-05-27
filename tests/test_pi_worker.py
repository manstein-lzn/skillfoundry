from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Sequence

from forgeunit_skillfoundry.adaptive_graph import AdaptiveWorkUnitResult
from forgeunit_skillfoundry.adaptive_graph import AdaptiveGraphConfig, run_adaptive_graph
from forgeunit_skillfoundry.pi_worker import AdaptivePiWorker, _pi_worker_runtime_metadata_from_env
from forgeunit_skillfoundry.worker_comparison import (
    run_worker_backend_comparison,
    worker_backend_comparison_report,
)
from skillfoundry.adaptive import NextStepContract
from skillfoundry.adaptive_workspace import (
    adaptive_route_plan_ref,
    initialize_adaptive_workspace,
    read_next_step_contract,
    read_observation_report,
    read_route_plan,
    read_state_correction,
)
from skillfoundry.pi_worker import (
    PI_WORKER_INPUT_SCHEMA_VERSION,
    PI_WORKER_OUTPUT_SCHEMA_VERSION,
    PiWorker,
    PiWorkerCommandResult,
    PiWorkerConfig,
    PiWorkerError,
)
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace


def _valid_skill_markdown(title: str) -> str:
    return "\n".join(
        [
            f"# {title}",
            "",
            "## Overview",
            "A deterministic verifier-compatible skill fixture.",
            "",
            "## When To Use",
            "Use when validating PiWorker adapter behavior.",
            "",
            "## When Not To Use",
            "Do not use as a production skill package.",
            "",
            "## Inputs",
            "- Frozen workspace refs.",
            "",
            "## Outputs",
            "- Verified package artifacts.",
            "",
            "## Workflow",
            "1. Produce the requested adaptive artifact.",
            "",
            "## Safety",
            "- Keep writes inside the delegated package scope.",
            "",
        ]
    )


class FakePiWorkerRunner:
    def __init__(self, *, returncode: int = 0, write_output: bool = True) -> None:
        self.returncode = returncode
        self.write_output = write_output
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        input_path: Path,
        cwd: Path,
        timeout_seconds: int,
    ) -> PiWorkerCommandResult:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        self.calls.append(
            {
                "command": list(command),
                "input_path": input_path,
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
                "payload": payload,
            }
        )
        if self.returncode != 0:
            return PiWorkerCommandResult(returncode=self.returncode, stdout="runner stdout", stderr="runner stderr")
        if self.write_output:
            package_path = cwd / "package" / "SKILL.md"
            package_path.parent.mkdir(parents=True, exist_ok=True)
            package_path.write_text(_valid_skill_markdown("PiWorker Fixture"), encoding="utf-8")
            for ref, text in (
                (payload["session_ref"], '{"type":"session"}\n'),
                (payload["events_ref"], '{"type":"agent_start"}\n{"type":"agent_end"}\n'),
                (payload["metrics_ref"], json.dumps({"model_calls": 1, "tool_calls": 1}) + "\n"),
            ):
                path = cwd / ref
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            output = {
                "schema_version": PI_WORKER_OUTPUT_SCHEMA_VERSION,
                "job_id": payload["job_id"],
                "iteration": payload["iteration"],
                "status": "completed",
                "produced_artifacts": ["package/SKILL.md"],
                "changed_refs": [
                    "package/SKILL.md",
                    payload["session_ref"],
                    payload["events_ref"],
                    payload["metrics_ref"],
                ],
                "commands_run": ["pi-worker fake sidecar"],
                "tests_run": [],
                "failures": [],
                "worker_claims": ["Fake Pi runtime generated package/SKILL.md."],
                "verifier_evidence": ["package/SKILL.md", payload["events_ref"], payload["metrics_ref"]],
                "new_unknowns": [],
                "recommended_next_steps": ["Run SkillFoundry verifier."],
                "verification_status": "not_run",
                "input_ref": payload["input_ref"],
                "output_ref": payload["output_ref"],
                "session_ref": payload["session_ref"],
                "events_ref": payload["events_ref"],
                "metrics_ref": payload["metrics_ref"],
                "duration_ms": 1,
                "metrics": {"model_calls": 1, "tool_calls": 1},
            }
            (cwd / payload["output_ref"]).write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return PiWorkerCommandResult(returncode=0, stdout="ok")


class FakeInvalidOutputPiWorkerRunner(FakePiWorkerRunner):
    def run(
        self,
        command: Sequence[str],
        *,
        input_path: Path,
        cwd: Path,
        timeout_seconds: int,
    ) -> PiWorkerCommandResult:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        self.calls.append(
            {
                "command": list(command),
                "input_path": input_path,
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
                "payload": payload,
            }
        )
        bad_output = {
            "schema_version": "wrong.schema",
            "job_id": payload["job_id"],
            "iteration": payload["iteration"],
        }
        (cwd / payload["output_ref"]).write_text(json.dumps(bad_output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return PiWorkerCommandResult(returncode=0, stdout="ok")


class _MockResponsesServer:
    def __init__(self, responses: list[dict[str, object]] | None = None) -> None:
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _MockResponsesHandler)
        self._server.requests = self.requests  # type: ignore[attr-defined]
        self._server.responses = responses if responses is not None else _mock_responses_payloads()  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _MockResponsesHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            }
        )
        index = len(self.server.requests) - 1  # type: ignore[attr-defined]
        responses = self.server.responses  # type: ignore[attr-defined]
        payload = responses[index] if index < len(responses) else responses[-1]
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


def _mock_responses_payloads() -> list[dict[str, object]]:
    return [
        {
            "id": "resp-live-1",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Writing the requested artifact."}],
                },
                {
                    "type": "function_call",
                    "call_id": "call-live-write",
                    "name": "write_workspace_artifact",
                    "arguments": json.dumps(
                        {
                            "path": "package/SKILL.md",
                            "content": "# Live PiWorker\n\nGenerated through mock live provider.\n",
                        }
                    ),
                },
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "input_tokens_details": {"cached_tokens": 40},
            },
        },
        {
            "id": "resp-live-2",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Completed package/SKILL.md."}],
                }
            ],
            "usage": {
                "input_tokens": 90,
                "output_tokens": 20,
                "total_tokens": 110,
                "input_tokens_details": {"cached_tokens": 20},
            },
        },
    ]


def test_pi_worker_writes_input_and_maps_sidecar_output(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-success")
    contract = _contract(workspace.job_id)
    runner = FakePiWorkerRunner()
    worker = PiWorker(PiWorkerConfig(command=("node", "run_work_unit.js")), runner=runner)

    result = worker.invoke(workspace, contract)

    assert result.status == "completed"
    assert result.produced_artifacts == ["package/SKILL.md"]
    assert result.verification_status == "not_run"
    assert result.session_ref == "adaptive/attempts/001/pi_session.jsonl"
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    input_payload = runner.calls[0]["payload"]
    assert input_payload["schema_version"] == PI_WORKER_INPUT_SCHEMA_VERSION
    assert input_payload["contract"]["next_objective"] == "Create the PiWorker fixture skill."
    assert input_payload["output_ref"] == "adaptive/attempts/001/pi_worker_output.json"


def test_pi_worker_nonzero_exit_returns_failure_result(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-failure")
    contract = _contract(workspace.job_id)
    worker = PiWorker(
        PiWorkerConfig(command=("node", "run_work_unit.js")),
        runner=FakePiWorkerRunner(returncode=7),
    )

    result = worker.invoke(workspace, contract)

    assert result.status == "failed"
    assert result.verification_status == "failed"
    assert result.produced_artifacts == []
    assert "pi_worker exited with return code 7" in result.failures[0]
    assert result.output_ref == "adaptive/attempts/001/pi_worker_output.json"
    assert workspace.resolve_path(result.output_ref, must_exist=True).is_file()


def test_pi_worker_invalid_output_returns_failure_result(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-invalid-output")
    contract = _contract(workspace.job_id)
    worker = PiWorker(
        PiWorkerConfig(command=("node", "run_work_unit.js")),
        runner=FakeInvalidOutputPiWorkerRunner(),
    )

    result = worker.invoke(workspace, contract)

    assert result.status == "failed"
    assert result.verification_status == "failed"
    assert result.produced_artifacts == []
    assert "PiWorker output schema_version is unsupported" in result.failures[0]


def test_pi_worker_config_rejects_sensitive_runtime_metadata() -> None:
    try:
        PiWorkerConfig(command=("node", "run_work_unit.js"), metadata={"api_key": "do-not-persist"})
    except PiWorkerError as exc:
        assert "use PI_WORKER_API_KEY or OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("PiWorkerConfig accepted sensitive runtime metadata")


def test_pi_worker_runtime_metadata_prefers_specific_base_url(monkeypatch) -> None:
    monkeypatch.setenv("PI_WORKER_BASE_URL", "https://pi-worker.example/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://generic-openai.example/v1")

    assert _pi_worker_runtime_metadata_from_env()["base_url"] == "https://pi-worker.example/v1"


def test_adaptive_pi_worker_returns_adaptive_work_unit_result(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-adaptive")
    contract = _contract(workspace.job_id)
    pi_worker = PiWorker(
        PiWorkerConfig(command=("node", "run_work_unit.js")),
        runner=FakePiWorkerRunner(),
    )

    result = AdaptivePiWorker(pi_worker)(workspace, contract)

    assert isinstance(result, AdaptiveWorkUnitResult)
    assert result.produced_artifacts == ["package/SKILL.md"]
    assert result.worker_claims == ["Fake Pi runtime generated package/SKILL.md."]


def test_pi_worker_node_sidecar_smoke(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-node")
    contract = _contract(workspace.job_id)
    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    worker = PiWorker(PiWorkerConfig(command=("node", str(sidecar))))

    result = worker.invoke(workspace, contract)

    assert result.status == "completed"
    assert result.produced_artifacts == ["package/SKILL.md"]
    assert result.metrics["runtime"] == "pi-agent-faux"
    assert result.metrics["model_calls"] == 2
    assert result.metrics["tool_calls"] == 4
    assert result.metrics["visible_ref_count"] == 2
    assert result.metrics["allowed_scope_count"] == 2
    assert result.metrics["produced_artifact_count"] == 1
    assert workspace.resolve_path("adaptive/attempts/001/pi_worker_input.json", must_exist=True).is_file()
    assert workspace.resolve_path("adaptive/attempts/001/pi_worker_output.json", must_exist=True).is_file()
    session_path = workspace.resolve_path("adaptive/attempts/001/pi_session.jsonl", must_exist=True)
    events_path = workspace.resolve_path("adaptive/attempts/001/pi_events.jsonl", must_exist=True)
    assert workspace.resolve_path("adaptive/attempts/001/pi_metrics.json", must_exist=True).is_file()
    assert '"role":"assistant"' in session_path.read_text(encoding="utf-8")
    events_text = events_path.read_text(encoding="utf-8")
    assert '"type":"agent_start"' in events_text
    assert '"toolName":"list_workspace_refs"' in events_text
    assert '"toolName":"read_workspace_ref"' in events_text
    assert '"toolName":"write_workspace_artifact"' in events_text
    assert '"type":"tool_execution_start"' in events_text
    assert '"type":"agent_end"' in events_text


def test_pi_worker_node_sidecar_live_provider_uses_openai_compatible_responses(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = _workspace(tmp_path, "pi-worker-live-provider")
    contract = _contract(workspace.job_id)
    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    server = _MockResponsesServer()
    server.start()
    try:
        monkeypatch.setenv("PI_WORKER_API_KEY", "test-live-key")
        worker = PiWorker(
            PiWorkerConfig(
                command=("node", str(sidecar)),
                model_provider="live",
                model="gpt-5.5",
                metadata={
                    "base_url": f"{server.base_url}/v1",
                    "reasoning_effort": "xhigh",
                    "thinking_level": "xhigh",
                    "max_tokens": 2048,
                    "prompt_cache_key": workspace.job_id,
                },
            )
        )

        result = worker.invoke(workspace, contract)
    finally:
        server.stop()

    assert result.status == "completed"
    assert result.produced_artifacts == ["package/SKILL.md"]
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).read_text(encoding="utf-8").startswith(
        "# Live PiWorker"
    )
    assert result.metrics["runtime"] == "pi-agent-live"
    assert result.metrics["provider_mode"] == "live"
    assert result.metrics["model_provider"] == "pi-worker-live"
    assert result.metrics["model"] == "gpt-5.5"
    assert result.metrics["usage_source"] == "provider_reported"
    assert result.metrics["model_calls"] == 2
    assert result.metrics["tool_calls"] == 1
    assert result.metrics["input_tokens"] == 130
    assert result.metrics["cache_read_tokens"] == 60
    assert result.metrics["output_tokens"] == 40
    assert result.metrics["total_tokens"] == 230
    assert result.metrics["cache_hit_ratio"] == 60 / 190
    assert len(server.requests) == 2
    assert server.requests[0]["path"] == "/v1/responses"
    assert server.requests[0]["headers"]["authorization"] == "Bearer test-live-key"
    assert server.requests[0]["body"]["model"] == "gpt-5.5"
    assert "reasoning" not in server.requests[0]["body"]
    assert server.requests[0]["body"]["tool_choice"] == {"type": "function", "name": "write_workspace_artifact"}
    assert server.requests[0]["body"]["store"] is False
    assert server.requests[0]["body"]["prompt_cache_key"] == workspace.job_id
    assert server.requests[0]["body"]["max_output_tokens"] == 2048
    assert [tool["name"] for tool in server.requests[0]["body"]["tools"]] == [
        "list_workspace_refs",
        "read_workspace_ref",
        "write_workspace_artifact",
    ]
    assert all(tool["strict"] is True for tool in server.requests[0]["body"]["tools"])
    assert server.requests[1]["body"]["tool_choice"] == "none"
    assert server.requests[1]["body"]["reasoning"] == {"effort": "xhigh"}
    assert any(item.get("type") == "function_call_output" for item in server.requests[1]["body"]["input"])

    for ref in (result.input_ref, result.output_ref, result.session_ref, result.events_ref, result.metrics_ref):
        assert "test-live-key" not in workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8")


def test_pi_worker_node_sidecar_canonicalizes_bundle_manifest_writes(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path, "pi-worker-live-bundle-canonicalization")
    contract = _contract(workspace.job_id)
    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    server = _MockResponsesServer(
        responses=[
            {
                "id": "resp-live-1",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Writing the requested artifacts."}],
                    },
                    {
                        "type": "function_call",
                        "call_id": "call-live-write-skill",
                        "name": "write_workspace_artifact",
                        "arguments": json.dumps(
                            {
                                "path": "package/SKILL.md",
                                "content": "# Live PiWorker\n\nGenerated through mock live provider.\n",
                            }
                        ),
                    },
                    {
                        "type": "function_call",
                        "call_id": "call-live-write-bundle",
                        "name": "write_workspace_artifact",
                        "arguments": json.dumps(
                            {
                                "path": "package/skillfoundry.bundle.json",
                                "content": json.dumps(
                                    {
                                        "schema_version": "skillfoundry.bundle.v1",
                                        "bundle_id": workspace.job_id,
                                        "title": "draft bundle",
                                        "objective": "This should be normalized away.",
                                        "boundary": {"package_root": "package"},
                                    }
                                ),
                            }
                        ),
                    },
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "input_tokens_details": {"cached_tokens": 40},
                },
            },
            {
                "id": "resp-live-2",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Completed package/SKILL.md."}],
                    }
                ],
                "usage": {
                    "input_tokens": 90,
                    "output_tokens": 20,
                    "total_tokens": 110,
                },
            },
        ],
    )
    server.start()
    try:
        monkeypatch.setenv("PI_WORKER_API_KEY", "test-live-key")
        worker = PiWorker(
            PiWorkerConfig(
                command=("node", str(sidecar)),
                model_provider="live",
                model="gpt-5.5",
                metadata={
                    "base_url": f"{server.base_url}/v1",
                    "reasoning_effort": "xhigh",
                    "thinking_level": "xhigh",
                    "max_tokens": 2048,
                    "prompt_cache_key": workspace.job_id,
                },
            )
        )

        result = worker.invoke(workspace, contract)
    finally:
        server.stop()

    assert result.status == "completed"
    assert result.produced_artifacts == ["package/SKILL.md", "package/skillfoundry.bundle.json"]
    bundle = json.loads(workspace.resolve_path("package/skillfoundry.bundle.json", must_exist=True).read_text(encoding="utf-8"))
    assert bundle == {
        "schema_version": "skillfoundry.bundle.v1",
        "bundle_id": workspace.job_id,
        "bundle_type": "prompt_only",
        "entrypoint": "SKILL.md",
        "capability_surface": {},
        "runtime_assets": [],
        "data_assets": [],
        "references": [],
        "environment": {},
        "permissions": {},
        "verification": {},
        "distribution": {},
    }


def test_pi_worker_node_sidecar_streams_events_while_running(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-streaming-events")
    contract = _contract(workspace.job_id)
    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    input_ref = "adaptive/attempts/001/pi_worker_input.json"
    events_ref = "adaptive/attempts/001/pi_events.jsonl"
    input_path = workspace.root / input_ref
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps(
            {
                "schema_version": PI_WORKER_INPUT_SCHEMA_VERSION,
                "job_id": workspace.job_id,
                "iteration": 1,
                "workspace_root": str(workspace.root.resolve()),
                "created_at": "2026-05-27T00:00:00Z",
                "attempt_dir_ref": "adaptive/attempts/001",
                "input_ref": input_ref,
                "output_ref": "adaptive/attempts/001/pi_worker_output.json",
                "session_ref": "adaptive/attempts/001/pi_session.jsonl",
                "events_ref": events_ref,
                "metrics_ref": "adaptive/attempts/001/pi_metrics.json",
                "contract": contract.to_dict(),
                "runtime": {
                    "runtime_name": "pi-worker-test",
                    "command": ["node", str(sidecar)],
                    "timeout_seconds": 30,
                    "model_provider": None,
                    "model": None,
                    "metadata": {},
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["PI_WORKER_EVENT_APPEND_DELAY_MS"] = "100"
    process = subprocess.Popen(
        ["node", str(sidecar), str(input_path)],
        cwd=workspace.root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        events_path = workspace.root / events_ref
        deadline = time.monotonic() + 10
        events_text = ""
        while time.monotonic() < deadline:
            if events_path.is_file():
                events_text = events_path.read_text(encoding="utf-8")
                if '"type":"agent_start"' in events_text:
                    break
            time.sleep(0.02)

        assert '"type":"agent_start"' in events_text
        assert process.poll() is None
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 0, f"stdout={stdout}\nstderr={stderr}"
    final_events = workspace.resolve_path(events_ref, must_exist=True).read_text(encoding="utf-8")
    assert '"type":"agent_end"' in final_events


def test_pi_worker_node_sidecar_rejects_out_of_scope_writes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-scope")
    contract = NextStepContract(
        job_id=workspace.job_id,
        iteration=1,
        current_state_ref="adaptive/capability_state.json",
        next_objective="Try to write outside the allowed scope.",
        why_now="The PiWorker scoped tool shim must enforce the work-unit boundary.",
        risk_if_too_large="A broad write surface would hide permission bugs.",
        risk_if_too_small="A missing negative test would not prove scope enforcement.",
        allowed_scope=["adaptive/attempts/001"],
        visible_refs=["skill_spec.yaml"],
        expected_outputs=["package/SKILL.md"],
        exit_criteria=["Out-of-scope writes are reported as failure."],
        stop_conditions=["The sidecar writes outside allowed_scope."],
        estimated_followups=["Inspect PiWorker events."],
    )
    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    worker = PiWorker(PiWorkerConfig(command=("node", str(sidecar))))

    result = worker.invoke(workspace, contract)

    assert result.status == "failed"
    assert result.verification_status == "failed"
    assert result.produced_artifacts == []
    assert result.new_unknowns == ["package/SKILL.md"]
    assert "expected artifact was not produced: package/SKILL.md" in result.failures
    events_text = workspace.resolve_path(result.events_ref, must_exist=True).read_text(encoding="utf-8")
    assert "Ref is outside allowed write scope: package/SKILL.md" in events_text


def test_pi_worker_node_sidecar_rejects_empty_allowed_scope(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-empty-scope")
    contract = NextStepContract(
        job_id=workspace.job_id,
        iteration=1,
        current_state_ref="adaptive/capability_state.json",
        next_objective="Try to write without an allowed scope.",
        why_now="The PiWorker scoped tool shim must fail closed when no write scope is delegated.",
        risk_if_too_large="An empty write scope could accidentally mean full workspace access.",
        risk_if_too_small="A missing fail-closed check would leave the permission contract ambiguous.",
        allowed_scope=[],
        visible_refs=["skill_spec.yaml"],
        expected_outputs=["package/SKILL.md"],
        exit_criteria=["No artifact is written outside an explicit allowed_scope."],
        stop_conditions=["The sidecar writes with an empty allowed_scope."],
        estimated_followups=["Inspect PiWorker events."],
    )
    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    worker = PiWorker(PiWorkerConfig(command=("node", str(sidecar))))

    result = worker.invoke(workspace, contract)

    assert result.status == "failed"
    assert result.produced_artifacts == []
    assert not workspace.resolve_path("package/SKILL.md").exists()
    events_text = workspace.resolve_path(result.events_ref, must_exist=True).read_text(encoding="utf-8")
    assert "Ref is outside allowed write scope: package/SKILL.md" in events_text


def test_pi_worker_node_sidecar_treats_directory_expected_output_as_scope_hint(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-directory-output")
    contract = NextStepContract(
        job_id=workspace.job_id,
        iteration=1,
        current_state_ref="adaptive/capability_state.json",
        next_objective="Repair files under the package directory.",
        why_now="Product repair contracts may name a directory-level output scope.",
        risk_if_too_large="Writing the directory path itself would fail before useful repair work.",
        risk_if_too_small="A text-only repair note would not update the package.",
        allowed_scope=["package", "adaptive/attempts/001"],
        visible_refs=["skill_spec.yaml"],
        expected_outputs=["package"],
        exit_criteria=["Concrete files under package are written."],
        stop_conditions=["The sidecar tries to write package as a file."],
        estimated_followups=["Run ProductGradeGate."],
    )
    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    worker = PiWorker(PiWorkerConfig(command=("node", str(sidecar))))

    result = worker.invoke(workspace, contract)

    assert result.status == "completed"
    assert result.verification_status == "not_run"
    assert "package/SKILL.md" in result.produced_artifacts
    assert "adaptive/attempts/001/repair_evidence.md" in result.produced_artifacts
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert workspace.resolve_path("package", must_exist=True).is_dir()
    events_text = workspace.resolve_path(result.events_ref, must_exist=True).read_text(encoding="utf-8")
    assert "Target path is not a regular file: " not in events_text


def test_pi_worker_node_sidecar_rejects_symlink_write_target(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "pi-worker-symlink")
    contract = NextStepContract(
        job_id=workspace.job_id,
        iteration=1,
        current_state_ref="adaptive/capability_state.json",
        next_objective="Try to overwrite a symlink target.",
        why_now="The PiWorker tool shim should fail closed on symlinked write paths.",
        risk_if_too_large="A symlinked artifact path could escape the workspace policy.",
        risk_if_too_small="A missing symlink check would leave filesystem trust assumptions broken.",
        allowed_scope=["package"],
        visible_refs=["skill_spec.yaml"],
        expected_outputs=["package/SKILL.md"],
        exit_criteria=["Symlink writes are rejected."],
        stop_conditions=["The sidecar follows a symlink target."],
        estimated_followups=["Inspect PiWorker events."],
    )
    workspace.resolve_path("package").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("package/SKILL.md").symlink_to("SKILL-real.md")

    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    worker = PiWorker(PiWorkerConfig(command=("node", str(sidecar))))

    result = worker.invoke(workspace, contract)

    assert result.status == "failed"
    assert result.produced_artifacts == []
    events_text = workspace.resolve_path(result.events_ref, must_exist=True).read_text(encoding="utf-8")
    assert "Symlink path is not allowed" in events_text


def test_adaptive_graph_can_use_pi_worker_node_sidecar(tmp_path: Path) -> None:
    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    pi_worker = PiWorker(PiWorkerConfig(command=("node", str(sidecar))))

    result = run_adaptive_graph(
        AdaptiveGraphConfig(
            runs_root=tmp_path / "runs",
            job_id="pi-worker-graph",
            max_iterations=3,
            route_plan_steering=True,
        ),
        worker=AdaptivePiWorker(pi_worker),
    )

    assert result.state["status"] == "report_emitted"
    assert result.state["contextforge"]["adaptive_latest_route"] == "closure"
    assert result.state["contextforge"]["adaptive_current_route_plan_ref"] == adaptive_route_plan_ref(2)
    workspace = JobWorkspace(root=result.workspace_root, job_id=result.job_id)
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert workspace.resolve_path("package/skillfoundry.bundle.json", must_exist=True).is_file()
    assert workspace.resolve_path("adaptive/attempts/001/pi_events.jsonl", must_exist=True).is_file()
    assert workspace.resolve_path("adaptive/attempts/002/pi_events.jsonl", must_exist=True).is_file()

    first_contract = read_next_step_contract(workspace, 1)
    second_contract = read_next_step_contract(workspace, 2)
    first_input = json.loads(
        workspace.resolve_path("adaptive/attempts/001/pi_worker_input.json", must_exist=True).read_text(encoding="utf-8")
    )
    second_input = json.loads(
        workspace.resolve_path("adaptive/attempts/002/pi_worker_input.json", must_exist=True).read_text(encoding="utf-8")
    )
    first_metrics = json.loads(
        workspace.resolve_path("adaptive/attempts/001/pi_metrics.json", must_exist=True).read_text(encoding="utf-8")
    )
    second_observation = read_observation_report(workspace, 2)
    final_route_plan = read_route_plan(workspace, 2)

    assert first_contract.route_plan_ref == adaptive_route_plan_ref(0)
    assert second_contract.route_plan_ref == adaptive_route_plan_ref(1)
    assert first_input["contract"]["route_plan_ref"] == adaptive_route_plan_ref(0)
    assert second_input["contract"]["route_plan_ref"] == adaptive_route_plan_ref(1)
    assert adaptive_route_plan_ref(0) in first_input["contract"]["visible_refs"]
    assert adaptive_route_plan_ref(1) in second_input["contract"]["visible_refs"]
    assert first_metrics["visible_ref_count"] >= 4
    assert read_state_correction(workspace, 2).next_route == "closure"
    assert second_observation.produced_artifacts == ["package/skillfoundry.bundle.json"]
    assert second_observation.recommended_next_steps == ["Run SkillFoundry verifier on the PiWorker output."]
    assert final_route_plan.based_on_observation_ref == "adaptive/observation_report_002.json"
    assert final_route_plan.current_strategy.startswith("Verifier evidence supports closure")


def test_worker_backend_comparison_report_compares_fake_and_pi(tmp_path: Path) -> None:
    sidecar = Path(__file__).resolve().parents[1] / "pi_worker" / "src" / "run_work_unit.mjs"
    pi_worker = AdaptivePiWorker(PiWorker(PiWorkerConfig(command=("node", str(sidecar)))))

    def worker_factory(backend: str):
        if backend == "pi":
            return pi_worker
        return _fake_adaptive_worker

    comparison = run_worker_backend_comparison(
        tmp_path / "runs",
        scenario="prompt-only",
        left_backend="fake",
        right_backend="pi",
        worker_factory=worker_factory,
    )
    report = worker_backend_comparison_report(comparison)

    assert report["schema_version"] == "forgeunit_skillfoundry.worker_backend_comparison.v1"
    assert comparison.left.status == "report_emitted"
    assert comparison.right.status == "report_emitted"
    assert comparison.right.pi_event_ref_count >= 1


def _workspace(tmp_path: Path, job_id: str) -> JobWorkspace:
    workspace = initialize_job_workspace(tmp_path / "runs", job_id)
    initialize_adaptive_workspace(workspace)
    return workspace


def _contract(job_id: str) -> NextStepContract:
    return NextStepContract(
        job_id=job_id,
        iteration=1,
        current_state_ref="adaptive/capability_state.json",
        next_objective="Create the PiWorker fixture skill.",
        why_now="The PiWorker backend needs deterministic adapter coverage.",
        risk_if_too_large="A broad sidecar integration would hide protocol defects.",
        risk_if_too_small="A fake-only test without artifact mapping would not prove the boundary.",
        allowed_scope=["package", "adaptive/attempts/001"],
        visible_refs=["skill_spec.yaml", "verification_spec.yaml"],
        expected_outputs=["package/SKILL.md"],
        exit_criteria=["package/SKILL.md exists or a failure is recorded."],
        stop_conditions=["The sidecar cannot write normalized output."],
        estimated_followups=["Run SkillFoundry verifier."],
    )


def _fake_adaptive_worker(workspace: JobWorkspace, contract: NextStepContract) -> AdaptiveWorkUnitResult:
    produced: list[str] = []
    if "package/SKILL.md" in contract.expected_outputs:
        workspace.resolve_path("package/SKILL.md").write_text(_valid_skill_markdown("Fake Worker"), encoding="utf-8")
        produced.append("package/SKILL.md")
    if "package/skillfoundry.bundle.json" in contract.expected_outputs:
        workspace.resolve_path("package/skillfoundry.bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": "skillfoundry.bundle.v1",
                    "bundle_id": workspace.job_id,
                    "bundle_type": "prompt_only",
                    "entrypoint": "SKILL.md",
                    "capability_surface": {},
                    "runtime_assets": [],
                    "data_assets": [],
                    "references": [],
                    "environment": {},
                    "permissions": {},
                    "verification": {},
                    "distribution": {},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        produced.append("package/skillfoundry.bundle.json")
    return AdaptiveWorkUnitResult(
        produced_artifacts=produced,
        changed_refs=list(produced),
        verifier_evidence=list(produced),
        worker_claims=["Fake backend completed."],
        verification_status="not_run",
    )
