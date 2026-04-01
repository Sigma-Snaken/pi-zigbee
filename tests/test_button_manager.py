import pytest
import pytest_asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.button_manager import ButtonManager


class FakeCommandQueue:
    def __init__(self):
        self.enqueue_calls = []
        self.cancel_calls = []

    async def enqueue(self, robot_id, action, params, button_id=None, trigger=None):
        self.enqueue_calls.append((robot_id, action, params))
        return {"ok": True, "queue_id": "fake-id", "position": 1}

    async def cancel_current(self, robot_id):
        self.cancel_calls.append(robot_id)
        return {"ok": True}


class FakeWSManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


@pytest_asyncio.fixture
async def setup(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    queue = FakeCommandQueue()
    ws = FakeWSManager()
    mgr = ButtonManager(db, queue, ws)
    yield mgr, db, queue, ws
    await disconnect()


@pytest.mark.asyncio
async def test_handle_device_joined(setup):
    mgr, db, _, ws = setup
    await mgr.handle_message({
        "type": "device_joined",
        "ieee_addr": "0x00124b00aaaaaa",
        "friendly_name": "0x00124b00aaaaaa",
    })
    async with db.execute("SELECT ieee_addr FROM buttons") as cursor:
        rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "0x00124b00aaaaaa"
    assert any(e[0] == "device_paired" for e in ws.events)


@pytest.mark.asyncio
async def test_handle_device_joined_duplicate(setup):
    mgr, db, _, _ = setup
    msg = {"type": "device_joined", "ieee_addr": "0x00124b00bbbbbb", "friendly_name": "test"}
    await mgr.handle_message(msg)
    await mgr.handle_message(msg)  # duplicate
    async with db.execute("SELECT COUNT(*) FROM buttons") as cursor:
        count = (await cursor.fetchone())[0]
    assert count == 1


@pytest.mark.asyncio
async def test_handle_button_action_with_binding(setup):
    mgr, db, queue, ws = setup
    # Setup: robot + button + binding
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, datetime('now'))",
        ("r1", "Robot", "1.2.3.4"),
    )
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0x00124b00cccccc", "Test Button"),
    )
    await db.execute(
        "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) "
        "VALUES (1, 'single', 'r1', 'return_home', '{}', 1, datetime('now'))"
    )
    await db.commit()

    await mgr.handle_message({
        "type": "button_action",
        "ieee_addr": "0x00124b00cccccc",
        "action": "single",
    })
    assert len(queue.enqueue_calls) == 1
    assert queue.enqueue_calls[0] == ("r1", "return_home", {})


@pytest.mark.asyncio
async def test_handle_button_action_no_binding(setup):
    mgr, db, queue, _ = setup
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0x00124b00dddddd", "Unbound"),
    )
    await db.commit()
    await mgr.handle_message({
        "type": "button_action",
        "ieee_addr": "0x00124b00dddddd",
        "action": "single",
    })
    assert len(queue.enqueue_calls) == 0


@pytest.mark.asyncio
async def test_handle_button_action_unknown_button(setup):
    mgr, _, queue, _ = setup
    await mgr.handle_message({
        "type": "button_action",
        "ieee_addr": "0x00124b00unknown",
        "action": "single",
    })
    assert len(queue.enqueue_calls) == 0
