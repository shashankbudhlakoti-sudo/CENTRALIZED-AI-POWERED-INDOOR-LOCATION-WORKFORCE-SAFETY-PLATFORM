"""
Raspberry Pi gateway.

Subscribes to MQTT topics that ESP32 beacons/badges publish RSSI readings to,
and forwards resolved positions (or raw RSSI for later fingerprinting) to the
backend's ingestion endpoint: POST /api/v1/positions

Topic convention (agree with ESP32 firmware):
    safety/gateway/<gateway_id>/tag/<tag_uid>   payload: {"rssi": -67, "ts": 1720000000}

Position resolution: raw RSSI from 3+ named gateways -> trilaterate() gives a
noisy raw (x, y) -> BadgeKalmanFilter smooths it into a stable estimate plus
an accuracy_m figure. See GATEWAY_POSITIONS below - this is the one thing
you MUST fill in with your real, measured gateway locations before this
produces anything meaningful.
"""

import json
import os
import time
import requests
import paho.mqtt.client as mqtt

from trilateration import rssi_to_distance, trilaterate
from position_filter import PositionFilterRegistry

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
GATEWAY_TOPIC_FILTER = "safety/gateway/+/tag/+"

# REQUIRED: fill in with your real, measured gateway locations (Step 1 of
# the setup guide) - same coordinate units as your floor plan
# (FLOORPLAN_BOUNDS is 1000x700 in the frontend). Trilateration is only
# as good as these numbers; get them from real measurement, not guesses.
GATEWAY_POSITIONS: dict[str, tuple[float, float]] = {
    "gw-sw": (0.0, 0.0),
    "gw-se": (4.45, 0.0),
    "gw-nw": (0.0, 4.11),
}

# In-memory buffer of latest RSSI per tag per gateway, until enough
# gateways report in to resolve a position.
_rssi_buffer: dict[str, dict[str, float]] = {}

# One Kalman filter instance per tag, smoothing raw trilaterated positions
# into stable estimates over time (see ml-service/app/models/position_filter.py -
# this is a straight copy of that module so the gateway can run standalone
# without importing across service boundaries; keep both in sync if you
# change the filter's tuning).
_position_filters = PositionFilterRegistry()


def resolve_position(tag_uid: str) -> tuple[float, float, float] | None:
    """
    Resolves a tag's smoothed (x, y, accuracy_m) from whatever gateways
    have reported RSSI for it so far.

    Returns None if fewer than 3 known gateways have reported - this is a
    hard geometric requirement (see trilateration.py), not a tunable
    threshold. Requires GATEWAY_POSITIONS to be filled in with real
    coordinates; unknown gateway_ids are silently ignored by trilaterate().
    """
    readings = _rssi_buffer.get(tag_uid, {})
    if not GATEWAY_POSITIONS:
        print("[gateway] GATEWAY_POSITIONS is empty - fill in real gateway coordinates first")
        return None

    distances = {gw_id: rssi_to_distance(rssi) for gw_id, rssi in readings.items()}
    raw = trilaterate(GATEWAY_POSITIONS, distances)
    if raw is None:
        return None  # fewer than 3 usable gateways reporting yet

    raw_x, raw_y = raw
    # Confidence scales with how many gateways contributed - a reading
    # triangulated from exactly 3 is trusted less than one from 4+.
    n_usable = len([g for g in readings if g in GATEWAY_POSITIONS])
    confidence = min(1.0, n_usable / max(len(GATEWAY_POSITIONS), 3))

    kalman = _position_filters.get(tag_uid)
    smoothed_x, smoothed_y, accuracy_m = kalman.update(raw_x, raw_y, t=time.time(), confidence=confidence)
    return smoothed_x, smoothed_y, accuracy_m


# Cache of tag_uid -> real database UUID, so we don't hit the lookup
# endpoint on every single reading.
_tag_id_cache: dict[str, str] = {}


def resolve_tag_id(tag_uid: str) -> str | None:
    """Looks up the real database UUID for a tag_uid label, caching the result.
    Returns None if the tag isn't registered yet (e.g. seed.sql wasn't run)."""
    if tag_uid in _tag_id_cache:
        return _tag_id_cache[tag_uid]

    try:
        resp = requests.get(f"{BACKEND_URL}/api/v1/tags/lookup/{tag_uid}", timeout=3)
        if resp.status_code == 404:
            print(f"[gateway] tag_uid '{tag_uid}' not registered in DB yet — run contracts/seed.sql")
            return None
        resp.raise_for_status()
        real_id = resp.json()["id"]
        _tag_id_cache[tag_uid] = real_id
        return real_id
    except requests.RequestException as e:
        print(f"[gateway] failed to resolve tag_id for {tag_uid}: {e}")
        return None


def send_position(tag_uid: str, x: float, y: float, accuracy_m: float):
    real_tag_id = resolve_tag_id(tag_uid)
    if real_tag_id is None:
        return  # can't post without a real tag_id — skip this reading

    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/v1/positions",
            json={
                "tag_id": real_tag_id,
                "floor": 1,
                "x": x,
                "y": y,
                "accuracy_m": accuracy_m,
                "source": "filtered",
            },
            timeout=3,
        )
        resp.raise_for_status()
        print(f"[gateway] posted position for {tag_uid} (tag_id={real_tag_id}) accuracy_m={accuracy_m:.2f}")
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
            x, y, accuracy_m = pos
            send_position(tag_uid, x, y, accuracy_m)
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
