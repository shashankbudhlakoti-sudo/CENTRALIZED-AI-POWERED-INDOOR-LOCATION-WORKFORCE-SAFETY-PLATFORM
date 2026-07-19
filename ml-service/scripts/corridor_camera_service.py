"""
Corridor camera ingestion service — Phase 5, Stage 2.

Watches a video source (webcam / local file for testing, RTSP URL for the
real Bosch corridor camera once its stream is configured) for motion,
captures a frame on detection, and drives the full checkpoint pipeline:

    upload photo -> POST /api/v1/checkpoints -> /internal/checkpoint-verify

Authenticates as the "corridor-camera" Keycloak service client
(client_credentials grant) — confirmed working end-to-end this session.
Never authenticates as a human; there is no interactive login here.

Motion detection is deliberately simple (grayscale frame differencing) per
today's decision: the camera's own built-in detection is only usable via
its web UI, not exposed on the raw RTSP stream, so this service does its
own detection instead of depending on Bosch analytics.

Frame capture uses a threaded producer/consumer pattern so RTSP decoding
latency never blocks the detection loop — this is what "high fps, minimum
lag" requires; a single-threaded read-then-process loop would drop frames
under load.

USAGE (testing today, before real RTSP is available):
    python corridor_camera_service.py --source 0          # webcam
    python corridor_camera_service.py --source video.mp4   # local file

USAGE (once the real Bosch camera's RTSP is configured):
    python corridor_camera_service.py --source "rtsp://user:pass@camera-ip/stream"
"""
import argparse
import threading
import time
from dataclasses import dataclass
from queue import Queue, Full, Empty
from typing import Optional

import cv2
import httpx
import numpy as np

# ---------------------------------------------------------------------------
# Configuration — hardcoded here for the pilot; move to env vars before any
# real deployment (same pattern service_auth.py already uses for ml-service).
# ---------------------------------------------------------------------------
KEYCLOAK_TOKEN_URL = "http://localhost:8080/realms/safety-platform/protocol/openid-connect/token"
BACKEND_BASE_URL = "http://localhost:8000"
SERVICE_CLIENT_ID = "corridor-camera"
SERVICE_CLIENT_SECRET = "oRmQHGLKWFT7ACvGjQwNlGPvmu5WZIaI"

# Real zone IDs, confirmed live in the DB this session.
MEETING_ROOM_ZONE_ID = "a881c846-78c0-429a-ace8-a1682dfc7986"

# Motion detection tuning — starting points, not calibrated against the real
# camera yet. Revisit once real footage is available; a corridor with
# fluorescent lighting flicker or HVAC-driven curtain movement may need a
# higher threshold than a webcam test does.
MOTION_DIFF_THRESHOLD = 25       # pixel intensity difference to count as "changed"
MOTION_MIN_CHANGED_PIXELS = 5000  # how many changed pixels before we call it motion
TRIGGER_COOLDOWN_SECONDS = 5.0    # minimum gap between checkpoint triggers, so one
                                   # person walking through doesn't fire dozens of events


@dataclass
class ServiceToken:
    """Cached client-credentials token, refreshed shortly before expiry —
    same pattern as ml-service/app/security/service_auth.py."""
    _token: Optional[str] = None
    _expiry: float = 0.0

    def get(self) -> str:
        if self._token and time.time() < self._expiry:
            return self._token
        resp = httpx.post(
            KEYCLOAK_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": SERVICE_CLIENT_ID,
                "client_secret": SERVICE_CLIENT_SECRET,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Refresh 30s before actual expiry, not exactly at it.
        self._expiry = time.time() + data["expires_in"] - 30
        return self._token


_service_token = ServiceToken()


class FrameGrabber:
    """Producer thread: continuously reads frames from the video source into
    a small bounded queue. Consumer (main loop) always gets the *latest*
    frame, never a backlog — dropping old frames is correct here, since we
    care about "what does the corridor look like right now", not replaying
    every frame that was ever captured."""

    def __init__(self, source):
        self.source = source
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open video source: {source}")
        self.queue: Queue = Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if not ok:
                # For a looping test video file, restart; for a real RTSP
                # drop, this is where reconnect logic will eventually go.
                time.sleep(0.5)
                continue
            try:
                self.queue.get_nowait()  # drop stale frame if consumer is behind
            except Empty:
                pass
            try:
                self.queue.put_nowait(frame)
            except Full:
                pass

    def read(self, timeout: float = 1.0):
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            return None

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2.0)
        self.cap.release()


def detect_motion(prev_gray: np.ndarray, gray: np.ndarray) -> bool:
    diff = cv2.absdiff(prev_gray, gray)
    _, thresh = cv2.threshold(diff, MOTION_DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
    changed_pixels = int(np.count_nonzero(thresh))
    return changed_pixels >= MOTION_MIN_CHANGED_PIXELS


def upload_photo(frame: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("Failed to JPEG-encode frame")
    token = _service_token.get()
    resp = httpx.post(
        f"{BACKEND_BASE_URL}/api/v1/photos",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("capture.jpg", encoded.tobytes(), "image/jpeg")},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["photo_url"]


def create_checkpoint(zone_id: str, photo_url: str) -> str:
    token = _service_token.get()
    resp = httpx.post(
        f"{BACKEND_BASE_URL}/api/v1/checkpoints",
        headers={"Authorization": f"Bearer {token}"},
        json={"zone_id": zone_id, "photo_url": photo_url},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def verify_checkpoint(checkpoint_event_id: str, zone_id: str, photo_url: str) -> dict:
    # NOTE: /internal/checkpoint-verify currently requires a human token
    # (get_current_user with role security_admin), confirmed by direct
    # testing this session. The corridor-camera service client cannot call
    # this endpoint as-is — this is a real, not-yet-closed gap, flagged
    # here rather than worked around silently. Options: (a) add
    # get_service_caller support alongside get_current_user on this
    # endpoint (mirrors the create_checkpoint fix already made), or
    # (b) have a separate always-on process holding a human token refresh
    # loop, which is fragile and not recommended. Do not enable this call
    # in production until (a) is resolved.
    raise NotImplementedError(
        "checkpoint-verify does not yet accept the corridor-camera service "
        "token - see comment above. Resolve this before wiring the full "
        "pipeline end-to-end."
    )


def run(source):
    grabber = FrameGrabber(source).start()
    prev_gray = None
    last_trigger_time = 0.0

    print(f"Watching source: {source}")
    try:
        while True:
            frame = grabber.read()
            if frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_gray is not None:
                moved = detect_motion(prev_gray, gray)
                now = time.time()
                if moved and (now - last_trigger_time) > TRIGGER_COOLDOWN_SECONDS:
                    last_trigger_time = now
                    print("Motion detected - capturing checkpoint frame")
                    try:
                        photo_url = upload_photo(frame)
                        checkpoint_id = create_checkpoint(MEETING_ROOM_ZONE_ID, photo_url)
                        print(f"Checkpoint created: {checkpoint_id} photo={photo_url}")
                        # verify_checkpoint(checkpoint_id, MEETING_ROOM_ZONE_ID, photo_url)
                    except Exception as e:
                        print(f"Checkpoint pipeline failed: {e}")

            prev_gray = gray
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        grabber.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        required=True,
        help="Video source: webcam index (e.g. 0), local file path, or RTSP URL",
    )
    args = parser.parse_args()
    # argparse gives webcam indices as strings; cv2.VideoCapture needs an int.
    source = int(args.source) if args.source.isdigit() else args.source
    run(source)
