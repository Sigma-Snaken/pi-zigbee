from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.buttons")
router = APIRouter()


class ButtonUpdate(BaseModel):
    name: str


@router.get("/buttons")
async def list_buttons():
    db = _state["db"]
    async with db.execute(
        "SELECT id, ieee_addr, name, paired_at, battery, last_seen FROM buttons ORDER BY id"
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {"id": r[0], "ieee_addr": r[1], "name": r[2], "paired_at": r[3], "battery": r[4], "last_seen": r[5]}
        for r in rows
    ]


@router.put("/buttons/{button_id}")
async def update_button(button_id: int, body: ButtonUpdate):
    db = _state["db"]
    await db.execute("UPDATE buttons SET name = ? WHERE id = ?", (body.name, button_id))
    await db.commit()
    return {"ok": True}


@router.delete("/buttons/{button_id}")
async def delete_button(button_id: int):
    db = _state["db"]
    await db.execute("DELETE FROM buttons WHERE id = ?", (button_id,))
    await db.commit()
    return {"ok": True}


@router.post("/buttons/pair")
async def start_pairing():
    mqtt = _state.get("mqtt_service")
    if not mqtt:
        raise HTTPException(503, "MQTT service not available")
    await mqtt.permit_join(True, time=120)
    ws = _state.get("ws_manager")
    if ws:
        await ws.broadcast("pair_started", {"timeout": 120})
    return {"ok": True, "timeout": 120}


@router.post("/buttons/pair/stop")
async def stop_pairing():
    mqtt = _state.get("mqtt_service")
    if not mqtt:
        raise HTTPException(503, "MQTT service not available")
    await mqtt.permit_join(False)
    ws = _state.get("ws_manager")
    if ws:
        await ws.broadcast("pair_stopped", {})
    return {"ok": True}
