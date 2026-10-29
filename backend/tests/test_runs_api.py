import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seed_api import runs
from seed_api.config import Settings, get_settings
from seed_api.core.providers.base import ProviderError

from .fakes import ScriptedProvider, calls, reply


def parse_sse(text: str) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def use_provider(monkeypatch: pytest.MonkeyPatch, provider: ScriptedProvider) -> None:
    monkeypatch.setattr(runs, "make_provider", lambda _settings: provider)


def test_runs_require_auth(client: TestClient) -> None:
    r = client.post("/api/v1/runs", json={"model": "m", "prompt": "hi"})
    assert r.status_code == 401


def test_unconfigured_provider_is_a_typed_503(authed: TestClient) -> None:
    r = authed.post("/api/v1/runs", json={"model": "m", "prompt": "hi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "provider_not_configured"
    assert authed.get("/api/v1/models").json()["error"]["code"] == "provider_not_configured"


def test_run_streams_events_and_writes_workspace(
    authed: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    provider = ScriptedProvider(
        [
            calls(("write_file", {"path": "index.html", "content": "<p>hi</p>"})),
            reply("Made index.html"),
        ]
    )
    use_provider(monkeypatch, provider)
    authed.app.dependency_overrides[get_settings] = lambda: settings.model_copy(  # type: ignore[attr-defined]
        update={"workspace_root": str(tmp_path)}
    )
    r = authed.post(
        "/api/v1/runs",
        json={
            "model": "m",
            "prompt": "make a page",
            "history": [{"role": "user", "content": "earlier"}],
        },
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "run_id" and kinds[-1] == "run_finished"
    assert "tool_call" in kinds and "tool_result" in kinds and "text_delta" in kinds
    assert events[-1][1]["termination"] == "completed"
    run_id = events[0][1]["run_id"]
    assert (tmp_path / run_id / "index.html").read_text() == "<p>hi</p>"
    first = provider.requests[0].messages
    assert [m.role for m in first] == ["system", "user", "user"] and first[
        -1
    ].content == "make a page"
    assert provider.closed


def test_provider_failure_ends_run_with_typed_reason(
    authed: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_provider(monkeypatch, ScriptedProvider([ProviderError("fake", "auth", "bad key", 401)]))  # type: ignore[list-item]
    events = parse_sse(authed.post("/api/v1/runs", json={"model": "m", "prompt": "hi"}).text)
    assert events[-1] == ("run_finished", events[-1][1])
    assert events[-1][1]["termination"] == "provider_error" and "auth" in events[-1][1]["error"]


def test_run_request_is_validated(authed: TestClient) -> None:
    r = authed.post("/api/v1/runs", json={"model": "", "prompt": "hi"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
