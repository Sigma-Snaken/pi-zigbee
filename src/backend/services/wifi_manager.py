"""WiFi management via NetworkManager D-Bus API."""

import asyncio
from dataclasses import dataclass

from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Variant

from utils.logger import get_logger

logger = get_logger("services.wifi_manager")

NM_BUS = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_IFACE = "org.freedesktop.NetworkManager"
NM_SETTINGS_PATH = "/org/freedesktop/NetworkManager/Settings"
NM_SETTINGS_IFACE = "org.freedesktop.NetworkManager.Settings"
DEVICE_IFACE = "org.freedesktop.NetworkManager.Device"
WIRELESS_IFACE = "org.freedesktop.NetworkManager.Device.Wireless"
AP_IFACE = "org.freedesktop.NetworkManager.AccessPoint"
CONN_ACTIVE_IFACE = "org.freedesktop.NetworkManager.Connection.Active"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

# NM device types
NM_DEVICE_TYPE_WIFI = 2

# NM states
NM_STATE_CONNECTED_GLOBAL = 70


@dataclass
class WifiNetwork:
    ssid: str
    signal: int
    security: str
    in_use: bool


@dataclass
class WifiStatus:
    connected: bool
    ssid: str
    ip: str
    signal: int
    mode: str  # "client" | "ap"


class WifiManager:
    """Manage WiFi connections via NetworkManager D-Bus."""

    async def _get_bus(self) -> MessageBus:
        return await MessageBus(bus_type=BusType.SYSTEM).connect()

    async def _get_props(self, bus, path, iface):
        introspection = await bus.introspect(NM_BUS, path)
        obj = bus.get_proxy_object(NM_BUS, path, introspection)
        props = obj.get_interface(PROPS_IFACE)
        return props, obj

    async def _get_wifi_device_path(self, bus) -> str:
        introspection = await bus.introspect(NM_BUS, NM_PATH)
        nm = bus.get_proxy_object(NM_BUS, NM_PATH, introspection)
        nm_iface = nm.get_interface(NM_IFACE)
        devices = await nm_iface.call_get_devices()
        for dev_path in devices:
            props, _ = await self._get_props(bus, dev_path, DEVICE_IFACE)
            dev_type = await props.call_get(DEVICE_IFACE, "DeviceType")
            if dev_type.value == NM_DEVICE_TYPE_WIFI:
                return dev_path
        raise RuntimeError("No WiFi device found")

    async def scan(self) -> list[WifiNetwork]:
        """Scan for available WiFi networks."""
        bus = await self._get_bus()
        try:
            dev_path = await self._get_wifi_device_path(bus)
            introspection = await bus.introspect(NM_BUS, dev_path)
            dev = bus.get_proxy_object(NM_BUS, dev_path, introspection)
            wireless = dev.get_interface(WIRELESS_IFACE)

            # Request scan
            await wireless.call_request_scan({})
            await asyncio.sleep(3)

            # Get access points
            ap_paths = await wireless.call_get_access_points()

            # Get current active AP
            props, _ = await self._get_props(bus, dev_path, WIRELESS_IFACE)
            try:
                active_ap = await props.call_get(WIRELESS_IFACE, "ActiveAccessPoint")
                active_ap_path = active_ap.value
            except Exception:
                active_ap_path = "/"

            networks = []
            seen_ssids = set()
            for ap_path in ap_paths:
                props, _ = await self._get_props(bus, ap_path, AP_IFACE)
                ssid_bytes = await props.call_get(AP_IFACE, "Ssid")
                ssid = bytes(ssid_bytes.value).decode("utf-8", errors="ignore")
                if not ssid or ssid in seen_ssids:
                    continue
                seen_ssids.add(ssid)

                signal = await props.call_get(AP_IFACE, "Strength")
                flags = await props.call_get(AP_IFACE, "WpaFlags")
                rsn_flags = await props.call_get(AP_IFACE, "RsnFlags")

                if rsn_flags.value:
                    security = "WPA2"
                elif flags.value:
                    security = "WPA"
                else:
                    security = "Open"

                networks.append(WifiNetwork(
                    ssid=ssid,
                    signal=signal.value,
                    security=security,
                    in_use=(ap_path == active_ap_path),
                ))

            networks.sort(key=lambda n: (-n.in_use, -n.signal))
            return networks
        finally:
            bus.disconnect()

    async def status(self) -> WifiStatus:
        """Get current WiFi connection status."""
        bus = await self._get_bus()
        try:
            dev_path = await self._get_wifi_device_path(bus)
            props, _ = await self._get_props(bus, dev_path, DEVICE_IFACE)

            state = await props.call_get(DEVICE_IFACE, "State")
            ip4_path = await props.call_get(DEVICE_IFACE, "Ip4Config")

            ip = ""
            if ip4_path.value != "/":
                try:
                    ip4_props, _ = await self._get_props(
                        bus, ip4_path.value, "org.freedesktop.NetworkManager.IP4Config"
                    )
                    addr_data = await ip4_props.call_get(
                        "org.freedesktop.NetworkManager.IP4Config", "AddressData"
                    )
                    if addr_data.value:
                        ip = addr_data.value[0].get("address", Variant("s", "")).value
                except Exception:
                    pass

            ssid = ""
            signal = 0
            connected = state.value >= 100  # NM_DEVICE_STATE_ACTIVATED

            if connected:
                w_props, _ = await self._get_props(bus, dev_path, WIRELESS_IFACE)
                try:
                    active_ap = await w_props.call_get(WIRELESS_IFACE, "ActiveAccessPoint")
                    if active_ap.value != "/":
                        ap_props, _ = await self._get_props(bus, active_ap.value, AP_IFACE)
                        ssid_bytes = await ap_props.call_get(AP_IFACE, "Ssid")
                        ssid = bytes(ssid_bytes.value).decode("utf-8", errors="ignore")
                        sig = await ap_props.call_get(AP_IFACE, "Strength")
                        signal = sig.value
                except Exception:
                    pass

            # Detect AP mode
            try:
                w_props, _ = await self._get_props(bus, dev_path, WIRELESS_IFACE)
                mode_val = await w_props.call_get(WIRELESS_IFACE, "Mode")
                mode = "ap" if mode_val.value == 3 else "client"
            except Exception:
                mode = "client"

            return WifiStatus(
                connected=connected, ssid=ssid, ip=ip, signal=signal, mode=mode
            )
        finally:
            bus.disconnect()

    async def connect_wifi(self, ssid: str, password: str) -> bool:
        """Connect to a WiFi network."""
        bus = await self._get_bus()
        try:
            dev_path = await self._get_wifi_device_path(bus)

            conn_settings = {
                "connection": {
                    "type": Variant("s", "802-11-wireless"),
                    "id": Variant("s", ssid),
                    "autoconnect": Variant("b", True),
                },
                "802-11-wireless": {
                    "ssid": Variant("ay", ssid.encode("utf-8")),
                    "mode": Variant("s", "infrastructure"),
                },
                "ipv4": {"method": Variant("s", "auto")},
                "ipv6": {"method": Variant("s", "auto")},
            }

            if password:
                conn_settings["802-11-wireless-security"] = {
                    "key-mgmt": Variant("s", "wpa-psk"),
                    "psk": Variant("s", password),
                }

            introspection = await bus.introspect(NM_BUS, NM_PATH)
            nm = bus.get_proxy_object(NM_BUS, NM_PATH, introspection)
            nm_iface = nm.get_interface(NM_IFACE)

            await nm_iface.call_add_and_activate_connection(
                conn_settings, dev_path, "/"
            )
            logger.info(f"WiFi connection to '{ssid}' initiated")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to '{ssid}': {e}")
            raise
        finally:
            bus.disconnect()

    async def start_hotspot(
        self, ssid: str = "SIGMA-SETUP", password: str = "12345678"
    ) -> bool:
        """Start WiFi AP hotspot for provisioning."""
        bus = await self._get_bus()
        try:
            dev_path = await self._get_wifi_device_path(bus)

            conn_settings = {
                "connection": {
                    "type": Variant("s", "802-11-wireless"),
                    "id": Variant("s", ssid),
                    "autoconnect": Variant("b", False),
                },
                "802-11-wireless": {
                    "ssid": Variant("ay", ssid.encode("utf-8")),
                    "mode": Variant("s", "ap"),
                    "band": Variant("s", "bg"),
                    "channel": Variant("u", 6),
                },
                "802-11-wireless-security": {
                    "key-mgmt": Variant("s", "wpa-psk"),
                    "psk": Variant("s", password),
                },
                "ipv4": {
                    "method": Variant("s", "shared"),
                },
                "ipv6": {"method": Variant("s", "disabled")},
            }

            introspection = await bus.introspect(NM_BUS, NM_PATH)
            nm = bus.get_proxy_object(NM_BUS, NM_PATH, introspection)
            nm_iface = nm.get_interface(NM_IFACE)

            await nm_iface.call_add_and_activate_connection(
                conn_settings, dev_path, "/"
            )
            logger.info(f"Hotspot '{ssid}' started")
            return True
        except Exception as e:
            logger.error(f"Failed to start hotspot: {e}")
            raise
        finally:
            bus.disconnect()

    async def stop_hotspot(self) -> bool:
        """Stop the current hotspot and return to client mode."""
        bus = await self._get_bus()
        try:
            dev_path = await self._get_wifi_device_path(bus)

            introspection = await bus.introspect(NM_BUS, dev_path)
            dev = bus.get_proxy_object(NM_BUS, dev_path, introspection)
            dev_iface = dev.get_interface(DEVICE_IFACE)

            await dev_iface.call_disconnect()
            logger.info("Hotspot stopped, device disconnected")

            # Re-activate auto-connect
            await asyncio.sleep(1)
            introspection = await bus.introspect(NM_BUS, NM_PATH)
            nm = bus.get_proxy_object(NM_BUS, NM_PATH, introspection)
            nm_iface = nm.get_interface(NM_IFACE)
            await nm_iface.call_activate_connection("/", dev_path, "/")
            return True
        except Exception as e:
            logger.error(f"Failed to stop hotspot: {e}")
            raise
        finally:
            bus.disconnect()
