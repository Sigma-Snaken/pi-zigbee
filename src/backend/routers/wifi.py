from fastapi import APIRouter
from pydantic import BaseModel

from services.wifi_manager import WifiManager
from utils.logger import get_logger

logger = get_logger("routers.wifi")
router = APIRouter()
wifi = WifiManager()


class WifiConnectRequest(BaseModel):
    ssid: str
    password: str = ""


class HotspotRequest(BaseModel):
    ssid: str = "SIGMA-SETUP"
    password: str = "12345678"


@router.get("/wifi/status")
async def wifi_status():
    try:
        st = await wifi.status()
        return {"connected": st.connected, "ssid": st.ssid, "ip": st.ip,
                "signal": st.signal, "mode": st.mode}
    except Exception as e:
        return {"connected": False, "ssid": "", "ip": "", "signal": 0,
                "mode": "unknown", "error": str(e)}


@router.post("/wifi/scan")
async def wifi_scan():
    try:
        networks = await wifi.scan()
        return {"networks": [
            {"ssid": n.ssid, "signal": n.signal, "security": n.security,
             "in_use": n.in_use}
            for n in networks
        ]}
    except Exception as e:
        return {"networks": [], "error": str(e)}


@router.post("/wifi/connect")
async def wifi_connect(body: WifiConnectRequest):
    try:
        await wifi.connect_wifi(body.ssid, body.password)
        return {"ok": True, "message": f"正在連線至 {body.ssid}..."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/wifi/hotspot/start")
async def hotspot_start(body: HotspotRequest = HotspotRequest()):
    try:
        await wifi.start_hotspot(body.ssid, body.password)
        return {"ok": True, "message": f"AP 已啟動: {body.ssid}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/wifi/hotspot/stop")
async def hotspot_stop():
    try:
        await wifi.stop_hotspot()
        return {"ok": True, "message": "AP 已關閉"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
