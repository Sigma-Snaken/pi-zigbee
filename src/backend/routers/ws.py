from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from main import _state

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    ws_manager = _state.get("ws_manager")
    if not ws_manager:
        await websocket.close()
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
