from kachaka_core.connection import KachakaConnection
from kachaka_core.commands import KachakaCommands
from kachaka_core.queries import KachakaQueries

from utils.logger import get_logger

logger = get_logger("robot_manager")


class RobotService:
    """Wraps kachaka_core components for a single robot."""

    def __init__(self, robot_id: str, ip: str):
        self.robot_id = robot_id
        self.ip = ip
        self.conn = None
        self.commands: KachakaCommands | None = None
        self.queries: KachakaQueries | None = None

    def connect(self, connect_fn=None, commands_cls=None, queries_cls=None) -> dict:
        _connect = connect_fn or KachakaConnection.get
        _cmds_cls = commands_cls or KachakaCommands
        _queries_cls = queries_cls or KachakaQueries
        self.conn = _connect(self.ip)
        self.commands = _cmds_cls(self.conn)
        self.queries = _queries_cls(self.conn)
        result = self.conn.ping()
        logger.info(f"Connected to robot {self.robot_id} at {self.ip}: {result.get('serial', 'unknown')}")
        return result

    def stop(self) -> None:
        logger.info(f"Stopped robot service for {self.robot_id}")


class RobotManager:
    """Manages multiple robot connections."""

    def __init__(self):
        self._robots: dict[str, RobotService] = {}

    def add(self, robot_id: str, ip: str, **kwargs) -> RobotService:
        svc = RobotService(robot_id, ip)
        svc.connect(**kwargs)
        self._robots[robot_id] = svc
        return svc

    def remove(self, robot_id: str) -> None:
        svc = self._robots.pop(robot_id, None)
        if svc:
            svc.stop()

    def get(self, robot_id: str) -> RobotService | None:
        return self._robots.get(robot_id)

    def all_ids(self) -> list[str]:
        return list(self._robots.keys())

    def stop_all(self) -> None:
        for svc in self._robots.values():
            svc.stop()
        self._robots.clear()
