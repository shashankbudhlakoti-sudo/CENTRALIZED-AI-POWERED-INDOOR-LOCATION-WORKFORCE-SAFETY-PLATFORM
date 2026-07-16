"""
Laptop-based iBeacon scanner (BeaconScope-compatible).

Uses this machine's own Bluetooth adapter to scan for real nearby BLE
advertisements and, specifically, parse standard Apple iBeacon frames
(the format apps like BeaconScope broadcast: company ID 0x004C, a UUID,
a major, and a minor value). Matched beacons get their real RSSI
published to the exact MQTT topic gateway.py already consumes:

    safety/gateway/<gateway_id>/tag/<tag_uid>   payload: {"rssi": -67, "ts": 1720000000}

This replaces the previous version of this file, which was a stale,
mislabeled duplicate of an older gateway.py (subscriber logic, not a
scanner at all - it published nothing). This one actually scans and
publishes.

Why match on (uuid, major, minor) instead of the advertising MAC
address: iOS in particular randomizes the BLE MAC address per
advertising session/reboot, so a MAC captured today may not be the same
MAC tomorrow. The UUID/major/minor triple is what you configure in
BeaconScope directly and is what stays stable, so it's the right key
for KNOWN_BEACONS.

Purpose: exercise the full pipeline (real RSSI -> MQTT -> gateway.py ->
backend -> position_events) end-to-end with a single laptop, before real
ESP32 gateways / trilateration exist. gateway.py's resolve_position()
already has a TESTING NOTE lowering its threshold to 1 reading for
exactly this purpose - do not raise it back to >=3 until real multi-
gateway trilateration replaces the placeholder.

Usage:
    1. Install deps (adds bleak to requirements.txt):
         pip install -r requirements.txt

    2. Open BeaconScope on the tag-holder's phone and make sure it's
       actively broadcasting/advertising (not just installed - some
       iBeacon apps need the broadcast toggle explicitly turned on).

    3. Discover the real UUID/major/minor it's sending:
         python laptop_scanner.py --discover
       If BeaconScope is broadcasting a standard iBeacon frame, it'll
       show up under "iBeacon" with its real uuid/major/minor. If it
       only shows up under "other" instead, its BLE payload doesn't
       match the format this parser expects - flag that and the parser
       can be adjusted to match whatever it's actually sending.

    4. Fill in KNOWN_BEACONS below with the real (uuid, major, minor).

    5. Run for real:
         python laptop_scanner.py

Note: on macOS you may need to grant Bluetooth permission to your
terminal/Python the first time; on Linux, bluetoothd must be running
and your user needs adapter access (or run with sufficient privileges).
"""

import argparse
import asyncio
import json
import os
import time
import uuid as uuid_module

import paho.mqtt.client as mqtt
from bleak import BleakScanner

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
GATEWAY_ID = os.getenv("GATEWAY_ID", "laptop-01")
SCAN_INTERVAL_S = float(os.getenv("SCAN_INTERVAL_S", "2.0"))

APPLE_COMPANY_ID = 0x004C
IBEACON_TYPE = 0x02
IBEACON_DATA_LEN = 0x15  # 21 bytes: type+len already excluded from this count in the frame check below

# Fill in after running --discover once. Keys are (uuid, major, minor)
# exactly as BeaconScope is configured to broadcast and as printed by
# --discover; values are the tag_uid labels already seeded in
# contracts/seed.sql (kartikeya-tag / shashank-tag). Empty until a real
# beacon has been identified.
KNOWN_BEACONS: dict[tuple[str, int, int], str] = {
    ("2f234454-cf6d-4a0f-adf2-f4911ba9ffa6", 1, 1): "kartikeya-tag",  # ← no trailing space, real tag_uid
}


def parse_ibeacon(adv) -> tuple[str, int, int] | None:
    """Parse Apple iBeacon manufacturer data out of a BLE advertisement.
    Returns (uuid, major, minor) - uuid lowercased - or None if this
    advertisement isn't a standard iBeacon frame."""
    data = adv.manufacturer_data.get(APPLE_COMPANY_ID)
    if not data or len(data) != 23 or data[0] != IBEACON_TYPE or data[1] != IBEACON_DATA_LEN:
        return None
    beacon_uuid = str(uuid_module.UUID(bytes=bytes(data[2:18])))
    major = int.from_bytes(data[18:20], "big")
    minor = int.from_bytes(data[20:22], "big")
    return beacon_uuid, major, minor


async def discover(timeout: float = 8.0) -> None:
    """Scan once and print every real nearby BLE advertisement, parsing out
    iBeacon uuid/major/minor where present, so real values can be picked
    out and added to KNOWN_BEACONS."""
    print(f"[laptop_scanner] scanning for {timeout:.0f}s - make sure BeaconScope is broadcasting now...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    if not devices:
        print("[laptop_scanner] nothing found - check Bluetooth is on (laptop and phone) and try again")
        return
    print(f"[laptop_scanner] found {len(devices)} device(s):")
    found_ibeacon = False
    for address, (device, adv) in devices.items():
        parsed = parse_ibeacon(adv)
        if parsed:
            found_ibeacon = True
            beacon_uuid, major, minor = parsed
            print(f"  iBeacon  uuid={beacon_uuid}  major={major}  minor={minor}  rssi={adv.rssi:>5}  (mac={address})")
        else:
            name = device.name or adv.local_name or "(no name)"
            print(f"  other    mac={address}  rssi={adv.rssi:>5}  name={name}")
    if found_ibeacon:
        print("\nAdd the (uuid, major, minor) shown above to KNOWN_BEACONS.")
    else:
        print(
            "\nNo iBeacon frames seen. Confirm BeaconScope's broadcast toggle "
            "is on (not just the app open), and re-run. If it still doesn't "
            "show under 'iBeacon', its payload format differs from standard "
            "Apple iBeacon - flag that and the parser can be adjusted."
        )


def build_topic(gateway_id: str, tag_uid: str) -> str:
    return f"safety/gateway/{gateway_id}/tag/{tag_uid}"


def build_payload(rssi: int) -> str:
    return json.dumps({"rssi": rssi, "ts": int(time.time())})


def make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(client, userdata, flags, rc, properties=None):
        print(f"[laptop_scanner] connected to MQTT broker rc={rc}")

    client.on_connect = on_connect
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


def publish_rssi(client: mqtt.Client, tag_uid: str, rssi: int) -> None:
    topic = build_topic(GATEWAY_ID, tag_uid)
    payload = build_payload(rssi)
    result = client.publish(topic, payload)
    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        print(f"[laptop_scanner] published {topic} rssi={rssi}")
    else:
        print(f"[laptop_scanner] publish failed rc={result.rc} for {topic}")


async def run() -> None:
    if not KNOWN_BEACONS:
        print("[laptop_scanner] KNOWN_BEACONS is empty - run --discover first and fill it in.")
        return

    client = make_mqtt_client()
    try:
        while True:
            devices = await BleakScanner.discover(timeout=SCAN_INTERVAL_S, return_adv=True)
            for address, (device, adv) in devices.items():
                parsed = parse_ibeacon(adv)
                if parsed is None:
                    continue
                tag_uid = KNOWN_BEACONS.get(parsed)
                if tag_uid is None:
                    continue
                publish_rssi(client, tag_uid, adv.rssi)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discover", action="store_true", help="Scan and print nearby BLE/iBeacon advertisements, then exit.")
    parser.add_argument("--discover-timeout", type=float, default=8.0)
    args = parser.parse_args()

    if args.discover:
        asyncio.run(discover(args.discover_timeout))
    else:
        asyncio.run(run())


if __name__ == "__main__":
    main()
