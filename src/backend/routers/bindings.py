import json
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from main import _state

router = APIRouter()
TRIGGERS = ["single", "double", "long"]


class BindingAction(BaseModel):
    robot_id: str
    action: str
    params: dict = {}


class BindingsUpdate(BaseModel):
    single: BindingAction | None = None
    double: BindingAction | None = None
    long: BindingAction | None = None


@router.get("/bindings/{button_id}")
async def get_bindings(button_id: int):
    db = _state["db"]
    result = {"button_id": button_id, "bindings": {t: None for t in TRIGGERS}}
    async with db.execute(
        "SELECT trigger, robot_id, action, params, enabled FROM bindings WHERE button_id = ?",
        (button_id,),
    ) as cursor:
        async for row in cursor:
            trigger, robot_id, action, params, enabled = row
            result["bindings"][trigger] = {
                "robot_id": robot_id, "action": action,
                "params": json.loads(params) if params else {},
                "enabled": bool(enabled),
            }
    return result


@router.put("/bindings/{button_id}")
async def update_bindings(button_id: int, body: BindingsUpdate):
    db = _state["db"]
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("DELETE FROM bindings WHERE button_id = ?", (button_id,))
    for trigger in TRIGGERS:
        binding = getattr(body, trigger)
        if binding:
            await db.execute(
                "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?)",
                (button_id, trigger, binding.robot_id, binding.action, json.dumps(binding.params), now),
            )
    await db.commit()
    return {"ok": True}
