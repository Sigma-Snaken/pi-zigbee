import json
from fastapi import APIRouter, Query

from main import _state

router = APIRouter()


@router.get("/logs")
async def get_logs(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200)):
    db = _state["db"]
    offset = (page - 1) * per_page

    async with db.execute("SELECT COUNT(*) FROM action_logs") as cursor:
        total = (await cursor.fetchone())[0]

    async with db.execute(
        "SELECT al.id, al.button_id, b.name as button_name, al.trigger, al.robot_id, "
        "al.action, al.params, al.result_ok, al.result_detail, al.executed_at "
        "FROM action_logs al LEFT JOIN buttons b ON al.button_id = b.id "
        "ORDER BY al.id DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    ) as cursor:
        rows = await cursor.fetchall()

    logs = [
        {
            "id": r[0], "button_id": r[1], "button_name": r[2], "trigger": r[3],
            "robot_id": r[4], "action": r[5],
            "params": json.loads(r[6]) if r[6] else {},
            "result_ok": bool(r[7]), "result_detail": r[8], "executed_at": r[9],
        }
        for r in rows
    ]
    return {"logs": logs, "total": total, "page": page, "per_page": per_page}
