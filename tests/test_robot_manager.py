import asyncio
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from kachaka_core.connection import ConnectionState
from services.robot_manager import RobotService, RobotManager


class FakeConnection:
    def __init__(self, ip):
        self.ip = ip
        self.serial = "KCK-TEST"

    def ping(self):
        return {"ok": True, "serial": "KCK-TEST", "pose": {"x": 0, "y": 0, "theta": 0}}


class FakeConnectionWithMonitoring:
    """FakeConnection that also supports start_monitoring / stop_monitoring.

    state is DISCONNECTED so RobotController's _state_loop skips gRPC polling.
    """

    def __init__(self, ip):
        self.ip = ip
        self.serial = "KCK-MON"
        self.state = ConnectionState.DISCONNECTED
        self.client = type("FakeClient", (), {})()  # stub for sdk = conn.client
        self.monitoring_started = False
        self.monitoring_stopped = False
        self._on_state_change = None
        self._monitoring_interval = None

    def ping(self):
        return {"ok": True, "serial": "KCK-MON", "pose": {"x": 0, "y": 0, "theta": 0}}

    def start_monitoring(self, interval=5.0, on_state_change=None):
        if self.monitoring_started:
            return  # idempotent, like the real SDK
        self.monitoring_started = True
        self._monitoring_interval = interval
        self._on_state_change = on_state_change

    def stop_monitoring(self):
        self.monitoring_stopped = True

    def refresh_shortcuts(self):
        pass

    def refresh_maps(self):
        pass


class FakeCommands:
    def __init__(self, conn):
        self.conn = conn

    def move_to_location(self, name):
        return {"ok": True, "action": "move_to_location", "target": name}

    def return_home(self):
        return {"ok": True, "action": "return_home"}

    def speak(self, text):
        return {"ok": True, "action": "speak"}


class FakeQueries:
    def __init__(self, conn):
        self.conn = conn

    def list_locations(self):
        return {"ok": True, "locations": [{"name": "Kitchen", "id": "loc1"}]}

    def get_battery(self):
        return {"ok": True, "percentage": 85}


class FakeWSManager:
    """Records broadcast calls for assertion."""

    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, event: str, data: dict) -> None:
        self.broadcasts.append((event, data))


class FakeStreamer:
    """Minimal streamer with notify_state_change tracking."""

    def __init__(self):
        self.state_changes = []

    def notify_state_change(self, state):
        self.state_changes.append(state)


# ------------------------------------------------------------------
# Existing tests (unchanged)
# ------------------------------------------------------------------

def test_robot_service_init():
    svc = RobotService("test-1", "1.2.3.4")
    assert svc.robot_id == "test-1"
    assert svc.ip == "1.2.3.4"

def test_robot_manager_add_remove():
    mgr = RobotManager()
    mgr.add("r1", "1.2.3.4", connect_fn=lambda ip: FakeConnection(ip),
            commands_cls=FakeCommands, queries_cls=FakeQueries)
    assert mgr.get("r1") is not None
    assert "r1" in mgr.all_ids()
    mgr.remove("r1")
    assert mgr.get("r1") is None

def test_robot_manager_get_nonexistent():
    mgr = RobotManager()
    assert mgr.get("nonexistent") is None


# ------------------------------------------------------------------
# New monitoring tests
# ------------------------------------------------------------------

def test_monitoring_starts_on_connect():
    """connect() should call conn.start_monitoring()."""
    svc = RobotService("m1", "10.0.0.1")
    svc.connect(
        connect_fn=lambda ip: FakeConnectionWithMonitoring(ip),
        commands_cls=FakeCommands,
        queries_cls=FakeQueries,
    )
    assert svc.conn.monitoring_started is True
    assert svc.conn._monitoring_interval == 5.0
    assert svc.conn._on_state_change is not None
    # Verify it's our method (bound method equality)
    assert svc.conn._on_state_change == svc._on_state_change


def test_monitoring_stops_on_stop():
    """stop() should call conn.stop_monitoring()."""
    svc = RobotService("m2", "10.0.0.2")
    svc.connect(
        connect_fn=lambda ip: FakeConnectionWithMonitoring(ip),
        commands_cls=FakeCommands,
        queries_cls=FakeQueries,
    )
    svc.stop()
    assert svc.conn.monitoring_stopped is True


def test_state_change_broadcasts_websocket():
    """_on_state_change should schedule a WebSocket broadcast."""
    loop = asyncio.new_event_loop()
    ws = FakeWSManager()
    svc = RobotService("m3", "10.0.0.3", ws_manager=ws, loop=loop)
    svc.connect(
        connect_fn=lambda ip: FakeConnectionWithMonitoring(ip),
        commands_cls=FakeCommands,
        queries_cls=FakeQueries,
    )

    # Simulate a state change from the monitoring thread
    svc._on_state_change(ConnectionState.DISCONNECTED)

    # Drain the event loop so the scheduled coroutine executes
    loop.run_until_complete(asyncio.sleep(0))

    assert len(ws.broadcasts) == 1
    event, data = ws.broadcasts[0]
    assert event == "robot:connection"
    assert data["robot_id"] == "m3"
    assert data["state"] == "disconnected"
    loop.close()


def test_state_change_notifies_streamers():
    """_on_state_change should call notify_state_change on active streamers."""
    svc = RobotService("m4", "10.0.0.4")
    svc.connect(
        connect_fn=lambda ip: FakeConnectionWithMonitoring(ip),
        commands_cls=FakeCommands,
        queries_cls=FakeQueries,
    )

    front = FakeStreamer()
    back = FakeStreamer()
    svc.front_streamer = front
    svc.back_streamer = back

    svc._on_state_change(ConnectionState.DISCONNECTED)

    assert len(front.state_changes) == 1
    assert front.state_changes[0] == ConnectionState.DISCONNECTED
    assert len(back.state_changes) == 1
    assert back.state_changes[0] == ConnectionState.DISCONNECTED


def test_shelf_dropped_broadcasts_websocket():
    """_on_shelf_dropped should schedule a WebSocket broadcast."""
    loop = asyncio.new_event_loop()
    ws = FakeWSManager()
    svc = RobotService("m5", "10.0.0.5", ws_manager=ws, loop=loop)
    svc.connect(
        connect_fn=lambda ip: FakeConnectionWithMonitoring(ip),
        commands_cls=FakeCommands,
        queries_cls=FakeQueries,
    )

    svc._on_shelf_dropped("shelf-42")

    loop.run_until_complete(asyncio.sleep(0))

    assert len(ws.broadcasts) == 1
    event, data = ws.broadcasts[0]
    assert event == "robot:shelf_dropped"
    assert data["robot_id"] == "m5"
    assert data["shelf_id"] == "shelf-42"
    loop.close()


def test_manager_passes_ws_manager_and_loop():
    """RobotManager should forward ws_manager and loop to RobotService."""
    loop = asyncio.new_event_loop()
    ws = FakeWSManager()
    mgr = RobotManager(ws_manager=ws, loop=loop)
    mgr.add(
        "m6", "10.0.0.6",
        connect_fn=lambda ip: FakeConnectionWithMonitoring(ip),
        commands_cls=FakeCommands,
        queries_cls=FakeQueries,
    )
    svc = mgr.get("m6")
    assert svc._ws_manager is ws
    assert svc._loop is loop
    loop.close()
