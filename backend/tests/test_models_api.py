from fastapi.testclient import TestClient


def test_models_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/models").status_code == 401


def test_unconfigured_provider_is_a_typed_503(authed: TestClient) -> None:
    r = authed.get("/api/v1/models")
    assert r.status_code == 503 and r.json()["error"]["code"] == "provider_not_configured"


def test_in_request_runs_are_gone(authed: TestClient) -> None:
    """Chat runs as durable tasks now; the old streaming endpoint must not linger."""
    assert authed.post("/api/v1/runs", json={"model": "m", "prompt": "hi"}).status_code in (
        404,
        405,
    )
