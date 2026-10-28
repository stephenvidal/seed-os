from fastapi.testclient import TestClient


def test_system_info_reports_real_host_values(client: TestClient) -> None:
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-horse"})
    data = client.get("/api/v1/system").json()
    assert data["cpu_count"] >= 1
    assert data["memory_total_bytes"] is None or data["memory_total_bytes"] > 0
    assert data["uptime_seconds"] >= 0 and data["version"]
