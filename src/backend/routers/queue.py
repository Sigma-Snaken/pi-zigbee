from fastapi import APIRouter, HTTPException

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.queue")
router = APIRouter()


@router.get("/queue")
async def get_queue():
    queue = _state.get("command_queue")
    if not queue:
        return {"items": [], "enabled": True}
    return {"items": queue.get_all(), "enabled": queue.enabled}


@router.delete("/queue/{queue_id}")
async def remove_from_queue(queue_id: str):
    queue = _state.get("command_queue")
    if not queue:
        raise HTTPException(503, "Command queue not available")
    result = await queue.remove(queue_id)
    if not result["ok"]:
        raise HTTPException(404, result["error"])
    return result


@router.post("/queue/cancel/{robot_id}")
async def cancel_current(robot_id: str):
    queue = _state.get("command_queue")
    if not queue:
        raise HTTPException(503, "Command queue not available")
    return await queue.cancel_current(robot_id)
