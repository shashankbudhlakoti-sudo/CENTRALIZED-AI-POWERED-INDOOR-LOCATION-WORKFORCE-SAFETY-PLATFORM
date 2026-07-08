"""
Turns a photo into a face embedding vector.

MODEL/LIBRARY CHOICE: InsightFace (buffalo_l, via onnxruntime), confirmed
with Shashank - chosen because the spec says "on-device" (rules out cloud
APIs like Rekognition/Azure Face). Confirmed working end-to-end on Windows
dev machines using a prebuilt community wheel (no official Windows wheel
exists, and building from source needs the MSVC C++ toolchain) - see
requirements.txt for the install command. License note: buffalo_l is
non-commercial-use only, fine for pilot/dev, revisit before real deployment.

If the team wants a different model, only this file needs to change -
callers depend on the EmbeddingGenerator interface, not on InsightFace
directly.
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
        # LICENSE NOTE (flagged by Shashank): buffalo_l is non-commercial-use
        # only. Fine for pilot/dev - confirm licensing terms before any real
        # deployment, and swap model_name if a commercially-licensed one is
        # needed instead.
        self._model_name = model_name
        self._det_threshold = det_threshold
        self._app = None  # lazy-loaded insightface.app.FaceAnalysis instance

    def _ensure_loaded(self):
        if self._app is not None:
            return
        from insightface.app import FaceAnalysis

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
    """Deterministic stand-in for tests and local dev - avoids needing
    real model weights loaded just to exercise the endpoint flow. Returns
    a fixed embedding derived from the byte content."""

    async def generate(self, photo_bytes: bytes) -> Optional[np.ndarray]:
        if not photo_bytes:
            return None
        seed = sum(photo_bytes) % (2**32)
        rng = np.random.default_rng(seed)
        vec = rng.normal(size=512)
        return vec / np.linalg.norm(vec)
