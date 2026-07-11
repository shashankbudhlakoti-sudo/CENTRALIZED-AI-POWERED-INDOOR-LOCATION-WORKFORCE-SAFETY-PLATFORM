"""
Raspberry Pi gateway.

Subscribes to MQTT topics that ESP32 beacons/badges publish RSSI readings to,
and forwards resolved positions (or raw RSSI for later fingerprinting) to the
backend's ingestion endpoint: POST /api/v1/positions

Topic convention (agree with ESP32 firmware):
    safety/gateway/<gateway_id>/tag/<tag_uid>   payload: {"rssi": -67, "ts": 1720000000}

This file only does raw RSSI collection + forwarding. Actual trilateration /
Kalman filtering to (x, y) happens in Track B's /ml pipeline OR here as a
simple placeholder — see resolve_position() below, swap in the real filter
once it exists.
"""

import json
import os
import time
import requests
import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
GATEWAY_TOPIC_FILTER = "safety/gateway/+/tag/+"

# In-memory buffer of latest RSSI per tag per gateway, until enough
# gateways report in to resolve a position.
_rssi_buffer: dict[str, dict[str, float]] = {}


def resolve_position(tag_uid: str) -> tuple[float, float] | None:
    """
    PLACEHOLDER position resolver.
    Replace with real trilateration/fingerprinting (Track B, Phase 4).
    Returns None until at least 3 gateways have reported for this tag.
    """
    readings = _rssi_buffer.get(tag_uid, {})
    if len(readings) < 3:
        return None
    # naive centroid placeholder — NOT for production use
    return (0.0, 0.0)


def send_position(tag_uid: str, x: float, y: float):
    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/v1/positions",
            json={"tag_id": tag_uid, "floor": 1, "x": x, "y": y, "source": "raw"},
            timeout=3,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[gateway] failed to POST position for {tag_uid}: {e}")


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[gateway] connected to MQTT broker rc={rc}")
    client.subscribe(GATEWAY_TOPIC_FILTER)


def on_message(client, userdata, msg):
    try:
        parts = msg.topic.split("/")  # safety/gateway/<gw_id>/tag/<tag_uid>
        gateway_id, tag_uid = parts[2], parts[4]
        payload = json.loads(msg.payload.decode())
        rssi = payload.get("rssi")

        _rssi_buffer.setdefault(tag_uid, {})[gateway_id] = rssi

        pos = resolve_position(tag_uid)
        if pos:
            send_position(tag_uid, *pos)
    except (IndexError, json.JSONDecodeError, KeyError) as e:
        print(f"[gateway] malformed message on {msg.topic}: {e}")


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except (ConnectionRefusedError, OSError) as e:
            print(f"[gateway] MQTT connection failed ({e}), retrying in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    main()
