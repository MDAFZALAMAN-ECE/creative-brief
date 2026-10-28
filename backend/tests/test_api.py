"""End-to-end API tests. Skipped automatically if FastAPI is not installed."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def auth(client, email="owner@acme.com", org="Acme"):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123", "org": org})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    assert client.get("/api/v1/health").json()["ok"] is True


def test_requires_authentication(client):
    assert client.get("/api/v1/contents").status_code == 401


def test_full_review_flow(client):
    h = auth(client)
    r = client.post("/api/v1/guidelines", headers=h, data={
        "collection": "terminology_tone", "source": "Glossary", "text": "avoid: cheap -> affordable"})
    assert r.status_code == 200
    created = client.post("/api/v1/contents", headers=h, data={"title": "Ad", "text": "Our cheap plans"}).json()
    cid = created["id"]
    ev = client.post(f"/api/v1/contents/{cid}/evaluate", headers=h).json()
    assert ev["findings_created"] >= 1
    findings = client.get(f"/api/v1/contents/{cid}/findings", headers=h).json()
    assert any(f["flag"] == "RED" for f in findings)
    fid = findings[0]["id"]
    assert client.post(f"/api/v1/findings/{fid}/review", headers=h, json={"action": "accept"}).status_code == 200
    assert client.post(f"/api/v1/contents/{cid}/approve", headers=h, json={"decision": "approved"}).status_code == 200


def test_tenant_isolation(client):
    a = auth(client, "a@one.com", "OrgOne")
    b = auth(client, "b@two.com", "OrgTwo")
    cid = client.post("/api/v1/contents", headers=a, data={"title": "Secret", "text": "x y z"}).json()["id"]
    assert client.get(f"/api/v1/contents/{cid}/findings", headers=b).status_code == 404
