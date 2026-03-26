from services.robot_manager import RobotManager
from utils.logger import get_logger

logger = get_logger("action_executor")


class ActionExecutor:
    def __init__(self, robot_manager: RobotManager):
        self._robot_manager = robot_manager

    def execute(self, robot_id: str, action: str, params: dict) -> dict:
        svc = self._robot_manager.get(robot_id)
        if not svc:
            return {"ok": False, "error": f"Robot '{robot_id}' not found"}
        if not svc.commands:
            return {"ok": False, "error": f"Robot '{robot_id}' not connected"}

        cmds = svc.commands
        action_map = {
            "move_to_location": lambda: cmds.move_to_location(params["name"]),
            "return_home": lambda: cmds.return_home(),
            "speak": lambda: cmds.speak(params["text"]),
            "move_shelf": lambda: cmds.move_shelf(params["shelf"], params["location"]),
            "return_shelf": lambda: cmds.return_shelf(params.get("shelf")),
            "dock_shelf": lambda: cmds.dock_shelf(),
            "undock_shelf": lambda: cmds.undock_shelf(),
            "start_shortcut": lambda: cmds.start_shortcut(params["shortcut_id"]),
        }

        handler = action_map.get(action)
        if not handler:
            return {"ok": False, "error": f"Unknown action: {action}"}

        try:
            result = handler()
            logger.info(f"Executed {action} on {robot_id}: ok={result.get('ok')}")
            return result
        except Exception as e:
            logger.error(f"Failed to execute {action} on {robot_id}: {e}")
            return {"ok": False, "error": str(e)}
