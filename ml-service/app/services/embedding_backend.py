"""
Turns a photo into a face embedding vector.

MODEL CHOICE FLAGGED FOR TEAM CONFIRMATION: no face-embedding library was
already decided, so this defaults to InsightFace (ONNX runtime) - chosen
because the spec says "on-device" (rules out cloud APIs like Rekognition/
Azure Face), and dlib-based alternatives (e.g. the `face_recognition`
package) are painful to install on Windows dev machines (native compile
step via CMake/Visual Studio). InsightFace ships prebuilt ONNX models and
runs via onnxruntime with no compile step.

If the team picks something else, only this file needs to change - callers
depend on the EmbeddingGenerator interface, not on InsightFace directly.

NOT YET RUNNABLE END-TO-END: requires `pip install insightface onnxruntime`
(not yet in requirements.txt - add once the model choice is confirmed) and
downloads model weights on first run. The interface and the pure matching
logic in face_match.py are usable and tested today; this file is the piece
that needs the real dependency installed to exercise for real.
"""
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class EmbeddingGenerator(ABC):
    @abstractmethod
    async def generate(self, photo_bytes: bytes) -> Optional[np.ndarray]:
        """Returns an embedding vector, or None if no face was detected."""
        raise NotImplementedError


class InsightFaceEmbeddingGenerator(EmbeddingGenerator):
    """Real implementation - lazy-loads the model on first use so importing
    this module doesn't require the model weights to be present (e.g. in
    tests that only exercise the interface/matching logic)."""

    def __init__(self, model_name: str = "buffalo_l", det_threshold: float = 0.5):
        # LICENSE NOTE (flagged by Shashank): some InsightFace pretrained
        # models, including buffalo_l, are non-commercial-use only. Fine for
        # pilot/dev - confirm licensing terms before any real deployment,
        # and swap model_name if a commercially-licensed one is needed.
        self._model_name = model_name
        self._det_threshold = det_threshold
        self._app = None  # lazy-loaded insightface.app.FaceAnalysis instance

    def _ensure_loaded(self):
        if self._app is not None:
            return
        try:
            from insightface.app import FaceAnalysis
        except ImportError as exc:
            raise RuntimeError(
                "insightface is not installed. This is expected until the "
                "team confirms the embedding model and it's added to "
                "requirements.txt - see module docstring."
            ) from exc

        self._app = FaceAnalysis(name=self._model_name)
        self._app.prepare(ctx_id=0, det_thresh=self._det_threshold)

    async def generate(self, photo_bytes: bytes) -> Optional[np.ndarray]:
        import cv2  # comes with insightface's dependencies

        self._ensure_loaded()
        img_array = np.frombuffer(photo_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            return None

        faces = self._app.get(img)
        if not faces:
            return None

        # Multiple faces in frame (e.g. tailgating in progress) - take the
        # largest bounding box as the primary subject. Worth revisiting once
        # we see real checkpoint camera footage; a fixed gate camera may
        # have a more reliable way to pick "the person at the gate" than
        # largest-face heuristics.
        largest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return largest.normed_embedding


class StubEmbeddingGenerator(EmbeddingGenerator):
    """Deterministic stand-in for tests and local dev before InsightFace is
    wired up. Returns a fixed embedding derived from the byte content so
    tests can exercise the full endpoint flow without real model weights."""

    async def generate(self, photo_bytes: bytes) -> Optional[np.ndarray]:
        if not photo_bytes:
            return None
        seed = sum(photo_bytes) % (2**32)
        rng = np.random.default_rng(seed)
        vec = rng.normal(size=512)
        return vec / np.linalg.norm(vec)
