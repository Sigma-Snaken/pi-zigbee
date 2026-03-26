import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from services.robot_manager import RobotService, RobotManager


class FakeConnection:
    def __init__(self, ip):
        self.ip = ip

    def ping(self):
        return {"ok": True, "serial": "KCK-TEST", "pose": {"x": 0, "y": 0, "theta": 0}}


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
