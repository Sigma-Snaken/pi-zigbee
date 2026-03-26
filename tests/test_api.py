import pytest
import pytest_asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from asgi_lifespan import LifespanManager
from httpx import AsyncClient, ASGITransport
from main import app, _state


@pytest_asyncio.fixture
async def client(tmp_path):
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    os.environ["MQTT_HOST"] = ""  # Disable MQTT in tests
    async with LifespanManager(app) as manager:
        async with AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://test"
        ) as ac:
            yield ac
    _state.clear()
    os.environ.pop("DB_PATH", None)
    os.environ.pop("MQTT_HOST", None)


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_robots_crud(client):
    resp = await client.post("/api/robots", json={"id": "r1", "name": "Test Robot", "ip": "1.2.3.4"})
    assert resp.status_code == 201
    resp = await client.get("/api/robots")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    resp = await client.put("/api/robots/r1", json={"name": "Updated", "ip": "5.6.7.8"})
    assert resp.status_code == 200
    resp = await client.delete("/api/robots/r1")
    assert resp.status_code == 200
    resp = await client.get("/api/robots")
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_buttons_list_empty(client):
    resp = await client.get("/api/buttons")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_bindings_get_empty(client):
    db = _state["db"]
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0x00124b00aaaaaa", "Test"),
    )
    await db.commit()
    resp = await client.get("/api/bindings/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["button_id"] == 1
    assert data["bindings"]["single"] is None
    assert data["bindings"]["double"] is None
    assert data["bindings"]["long"] is None


@pytest.mark.asyncio
async def test_bindings_put(client):
    db = _state["db"]
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, datetime('now'))",
        ("r1", "Robot", "1.2.3.4"),
    )
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0x00124b00bbbbbb", "Btn"),
    )
    await db.commit()

    resp = await client.put("/api/bindings/1", json={
        "single": {"robot_id": "r1", "action": "return_home", "params": {}},
        "double": {"robot_id": "r1", "action": "speak", "params": {"text": "hi"}},
        "long": None,
    })
    assert resp.status_code == 200

    resp = await client.get("/api/bindings/1")
    data = resp.json()
    assert data["bindings"]["single"]["action"] == "return_home"
    assert data["bindings"]["double"]["action"] == "speak"
    assert data["bindings"]["long"] is None


@pytest.mark.asyncio
async def test_logs_empty(client):
    resp = await client.get("/api/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["logs"] == []
    assert data["total"] == 0
