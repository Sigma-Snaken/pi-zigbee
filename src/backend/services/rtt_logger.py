import asyncio
from datetime import datetime, timezone

import aiosqlite

from services.robot_manager import RobotManager
from utils.logger import get_logger

logger = get_logger("rtt_logger")


class RTTLogger:
    """Periodically records RTT + pose from RobotController to DB."""

    def __init__(self, db: aiosqlite.Connection, robot_manager: RobotManager, interval: float = 5.0):
        self._db = db
        self._rm = robot_manager
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._serials: dict[str, str] = {}  # robot_id -> serial

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info(f"RTT logger started (interval={self._interval}s)")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("RTT logger stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._record_all()
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"RTT logger error: {e}")
                await asyncio.sleep(self._interval)

    async def _record_all(self) -> None:
        for robot_id in self._rm.all_ids():
            svc = self._rm.get(robot_id)
            if not svc or not svc.controller:
                continue

            try:
                state = svc.controller.state
                if state is None:
                    continue

                # Get latest RTT from metrics
                metrics = svc.controller.metrics
                rtt_list = metrics.poll_rtt_list if hasattr(metrics, 'poll_rtt_list') else []
                if not rtt_list:
                    continue

                rtt_ms = rtt_list[-1]  # Latest RTT

                # Get pose + battery from state
                x = getattr(state, 'pose_x', None)
                y = getattr(state, 'pose_y', None)
                theta = getattr(state, 'pose_theta', None) or 0.0
                battery = getattr(state, 'battery_pct', None)
                if x is None or y is None:
                    continue

                # Get serial (cache it)
                serial = self._serials.get(robot_id)
                if not serial and svc.conn:
                    try:
                        ping = svc.conn.ping()
                        serial = ping.get("serial", "")
                        self._serials[robot_id] = serial
                    except Exception:
                        serial = ""

                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT INTO rtt_logs (robot_name, serial, x, y, theta, battery, rtt_ms, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (svc.robot_id, serial, x, y, theta, battery, rtt_ms, now),
                )
                await self._db.commit()
            except Exception as e:
                logger.warning(f"Failed to record RTT for {robot_id}: {e}")
