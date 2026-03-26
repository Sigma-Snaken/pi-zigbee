"""
Smoke test: verifies the full flow from MQTT message → DB lookup → action execution.
Does NOT require a real MQTT broker or Kachaka robot.
"""
import pytest
import pytest_asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.ws_manager import WSManager
from services.robot_manager import RobotManager, RobotService
from services.action_executor import ActionExecutor
from services.button_manager import ButtonManager
from services.mqtt_service import parse_zigbee_message


class FakeConnection:
    def __init__(self, ip):
        self.ip = ip
    def ping(self):
        return {"ok": True, "serial": "KCK-TEST"}


class FakeCommands:
    def __init__(self, conn):
        self.calls = []
    def move_to_location(self, name):
        self.calls.append(("move_to_location", name))
        return {"ok": True, "action": "move_to_location", "target": name}
    def return_home(self):
        self.calls.append(("return_home",))
        return {"ok": True, "action": "return_home"}
    def speak(self, text):
        self.calls.append(("speak", text))
        return {"ok": True, "action": "speak"}
    def start_shortcut(self, shortcut_id):
        self.calls.append(("start_shortcut", shortcut_id))
        return {"ok": True, "action": "start_shortcut"}


class FakeQueries:
    def __init__(self, conn):
        pass


class FakeWSManager:
    def __init__(self):
        self.events = []
    async def broadcast(self, event, data):
        self.events.append((event, data))


@pytest_asyncio.fixture
async def stack(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES ('r1', 'TestBot', '1.2.3.4', 1, datetime('now'))"
    )
    await db.commit()
    robot_mgr = RobotManager()
    robot_mgr.add("r1", "1.2.3.4", connect_fn=lambda ip: FakeConnection(ip),
                   commands_cls=FakeCommands, queries_cls=FakeQueries)
    executor = ActionExecutor(robot_mgr)
    ws = FakeWSManager()
    btn_mgr = ButtonManager(db, executor, ws)
    yield db, robot_mgr, btn_mgr, ws
    await disconnect()


@pytest.mark.asyncio
async def test_full_flow_button_press_to_robot_action(stack):
    db, robot_mgr, btn_mgr, ws = stack

    # 1. Simulate device join
    join_msg = parse_zigbee_message(
        "zigbee2mqtt/bridge/event",
        json.dumps({"type": "device_joined", "data": {"ieee_address": "0x00124b00test01", "friendly_name": "0x00124b00test01"}}),
    )
    await btn_mgr.handle_message(join_msg)

    async with db.execute("SELECT id FROM buttons WHERE ieee_addr = '0x00124b00test01'") as cursor:
        btn_row = await cursor.fetchone()
    assert btn_row is not None
    button_id = btn_row[0]

    # 2. Create binding
    await db.execute(
        "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) "
        "VALUES (?, 'single', 'r1', 'move_to_location', ?, 1, datetime('now'))",
        (button_id, json.dumps({"name": "Kitchen"})),
    )
    await db.commit()

    # 3. Simulate button press
    action_msg = parse_zigbee_message(
        "zigbee2mqtt/0x00124b00test01",
        json.dumps({"action": "single", "battery": 90}),
    )
    await btn_mgr.handle_message(action_msg)

    # 4. Verify
    svc = robot_mgr.get("r1")
    assert ("move_to_location", "Kitchen") in svc.commands.calls

    async with db.execute("SELECT action, result_ok FROM action_logs") as cursor:
        log = await cursor.fetchone()
    assert log[0] == "move_to_location"
    assert log[1] == 1

    event_types = [e[0] for e in ws.events]
    assert "device_paired" in event_types
    assert "action_executed" in event_types


@pytest.mark.asyncio
async def test_full_flow_three_triggers(stack):
    db, robot_mgr, btn_mgr, ws = stack

    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES ('0x00124b00test02', 'Test', datetime('now'))"
    )
    await db.execute(
        "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) VALUES "
        "(1, 'single', 'r1', 'move_to_location', '{\"name\":\"Kitchen\"}', 1, datetime('now')),"
        "(1, 'double', 'r1', 'speak', '{\"text\":\"hello\"}', 1, datetime('now')),"
        "(1, 'long', 'r1', 'return_home', '{}', 1, datetime('now'))"
    )
    await db.commit()

    for trigger in ["single", "double", "long"]:
        msg = parse_zigbee_message(
            "zigbee2mqtt/0x00124b00test02",
            json.dumps({"action": trigger}),
        )
        await btn_mgr.handle_message(msg)

    svc = robot_mgr.get("r1")
    assert ("move_to_location", "Kitchen") in svc.commands.calls
    assert ("speak", "hello") in svc.commands.calls
    assert ("return_home",) in svc.commands.calls

    async with db.execute("SELECT COUNT(*) FROM action_logs") as cursor:
        count = (await cursor.fetchone())[0]
    assert count == 3
