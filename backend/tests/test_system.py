from fastapi.testclient import TestClient


def test_system_info_reports_real_host_values(authed: TestClient) -> None:
    data = authed.get("/api/v1/system").json()
    assert data["cpu_count"] >= 1
    assert data["memory_total_bytes"] is None or data["memory_total_bytes"] > 0
    assert data["uptime_seconds"] >= 0 and data["version"]
