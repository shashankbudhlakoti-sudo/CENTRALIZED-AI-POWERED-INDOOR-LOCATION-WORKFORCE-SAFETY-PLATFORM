"""
ML service entry point.

Security posture:
- Every data-touching route requires a verified Keycloak JWT (app.security.auth).
- CORS is locked to the known frontend origin only - no wildcard.
- No route ever accepts a raw employee_id from the frontend for scope
  filtering; the JWT's own claims determine what a caller may query, and the
  backend has already scoped what it forwards here.
- Structured logging - no raw PII (photos, exact coordinates) ever hits logs.
"""

import logging
import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pathlib import Path

from app.security.auth import AuthenticatedUser, get_current_user, require_role
from app.security.audit import log_action
from app.models.position_filter import PositionFilterRegistry
from app.models.train_mode import TrainingWalk, LabeledSample
from app.models.fingerprinting import FingerprintModel
from app.models.face_match import find_best_match, is_identity_mismatch
from app.services.embedding_backend import EmbeddingGenerator, InsightFaceEmbeddingGenerator
from app.services.enrolled_embeddings_repo import EnrolledEmbeddingsRepository, PostgresEnrolledEmbeddings
from app.services.checkpoint_client import patch_checkpoint_match
from typing import Optional
import httpx

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/data/models"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ml-service")

ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    raise RuntimeError("ALLOWED_ORIGINS must be set explicitly - refusing to default to '*'")

app = FastAPI(title="Indoor Tracking ML Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

registry = PositionFilterRegistry()


@app.get("/health")
async def health():
    # Deliberately unauthenticated - used by Docker/orchestration health
    # checks only. Returns no data, just process liveness.
    return {"status": "ok"}


class RawPositionReading(BaseModel):
    tag_id: str = Field(..., max_length=64)
    x_meas: float
    y_meas: float
    timestamp: float
    confidence: float = Field(1.0, ge=0.0, le=1.0)


class FilteredPosition(BaseModel):
    tag_id: str
    x: float
    y: float
    accuracy_m: float  # estimated positioning error in meters, matches
    # position_events.accuracy_m. Distinct from checkpoint_events.match_confidence
    # (face-match score) - do not conflate the two.


@app.post("/internal/filter-position", response_model=FilteredPosition)
async def filter_position(
    reading: RawPositionReading,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Called by the ingestion pipeline (via the backend) with one raw
    trilaterated reading; returns the Kalman-smoothed position.

    Note: this endpoint is internal-service-to-service traffic (backend ->
    ML service), not something the React frontend calls directly. It still
    requires a verified token because the network boundary alone is never
    treated as sufficient authorization.
    """
    kf = registry.get(reading.tag_id)
    x, y, accuracy_m = kf.update(reading.x_meas, reading.y_meas, reading.timestamp, reading.confidence)
    logger.info("filtered position tag=%s accuracy_m=%.2f", reading.tag_id, accuracy_m)
    return FilteredPosition(tag_id=reading.tag_id, x=x, y=y, accuracy_m=accuracy_m)


# ---------------------------------------------------------------------------
# Fingerprinting (Section 5 - Train Mode)
# ---------------------------------------------------------------------------

class LabeledSampleIn(BaseModel):
    true_x: float
    true_y: float
    rssi: dict[str, float]
    timestamp: float
    badge_orientation: str = "unknown"


class TrainRequest(BaseModel):
    zone_id: str = Field(..., max_length=64)
    beacon_ids: list[str] = Field(..., min_length=1)
    samples: list[LabeledSampleIn] = Field(..., min_length=1)


class ValidationResult(BaseModel):
    n_train: int
    n_holdout: int
    mean_error_m: float
    p90_error_m: float
    max_error_m: float


@app.post(
    "/internal/fingerprint/train",
    response_model=ValidationResult,
    dependencies=[Depends(require_role("security_admin"))],
)
async def train_fingerprint_model(req: TrainRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """Retrains the positioning model for a zone from a freshly collected
    Train Mode walk. Restricted to security_admin: retraining changes
    positioning accuracy for every employee tracked in this zone, so it is
    not something any manager role should be able to trigger casually.

    The model is validated against a held-out slice of THIS SAME walk
    before it can be saved (see FingerprintModel.save) - an unvalidated
    model is never deployed, per Section 5's "defensible in a review"
    requirement.
    """
    walk = TrainingWalk(zone_id=req.zone_id, beacon_ids=req.beacon_ids)
    for s in req.samples:
        walk.add_sample(LabeledSample(**s.model_dump()))

    model = FingerprintModel(beacon_ids=sorted(req.beacon_ids))
    report = model.fit_and_validate(walk)
    model.save(MODEL_DIR / req.zone_id)

    logger.info(
        "fingerprint model retrained zone=%s mean_error_m=%.2f by=%s",
        req.zone_id, report.mean_error_m, user.sub,
    )
    # Retraining is a system-level action, not tied to one employee, so
    # resource_id is None - still logged so there's a record of who
    # changed the live positioning model and when. actor_role comes from
    # the verified JWT, matching the user_role enum in schema.sql exactly.
    await log_action(
        actor_user_id=user.sub,
        actor_role="security_admin",
        action="model_retrain",
        resource_type="model",
        resource_id=req.zone_id,
        justification="train_mode_walk",
    )

    return ValidationResult(**report.as_dict())


class PredictRequest(BaseModel):
    zone_id: str = Field(..., max_length=64)
    rssi: dict[str, float]


class PredictResult(BaseModel):
    x: float
    y: float


@app.post("/internal/fingerprint/predict", response_model=PredictResult)
async def predict_position(req: PredictRequest, user: AuthenticatedUser = Depends(get_current_user)):
    model_path = MODEL_DIR / req.zone_id
    if not model_path.exists():
        raise HTTPException(status_code=404, detail=f"No trained model for zone '{req.zone_id}' yet")
    model = FingerprintModel.load(model_path)
    x, y = model.predict(req.rssi)
    return PredictResult(x=x, y=y)


# ---------------------------------------------------------------------------
# Checkpoint verification (Section 5 / checkpoint_events)
#
# Backend owns creating the checkpoint_events row (zone_id, tag_id,
# employee_id, photo_url) with match_status='pending'. This service
# generates a face embedding from the photo, compares it against enrolled
# employees, and PATCHes the result back via the backend's
# PATCH /checkpoints/{id}/match - it never writes to Postgres directly for
# this table (same single-write-path pattern as position_events).
#
# OPEN QUESTION for Shashank: a confident match whose identity disagrees
# with the tag's claimed employee (see is_identity_mismatch) is the actual
# badge-sharing/tailgating signal that alert_type='checkpoint_mismatch' is
# for - but there's no alerts table schema or creation endpoint in this
# scaffold yet, so this endpoint only logs that condition (audit_log +
# structured log) rather than writing an alert. Need to know whether
# alert creation happens here, on the backend, or in the separate anomaly
# detection module before wiring that part up for real.
# ---------------------------------------------------------------------------

_embedding_generator: EmbeddingGenerator = InsightFaceEmbeddingGenerator()
_enrolled_repo: EnrolledEmbeddingsRepository = PostgresEnrolledEmbeddings()


class CheckpointVerifyRequest(BaseModel):
    checkpoint_event_id: str
    zone_id: str
    tag_id: Optional[str] = None
    claimed_employee_id: Optional[str] = None  # employee currently assigned to tag_id, if known
    photo_url: str


class CheckpointVerifyResult(BaseModel):
    checkpoint_event_id: str
    match_employee_id: Optional[str]
    match_confidence: Optional[float]
    match_status: str
    identity_mismatch: bool  # see OPEN QUESTION above - not yet wired to an alert


@app.post(
    "/internal/checkpoint-verify",
    response_model=CheckpointVerifyResult,
    dependencies=[Depends(require_role("security_admin"))],
)
async def checkpoint_verify(
    req: CheckpointVerifyRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    async with httpx.AsyncClient(timeout=10.0) as client:
        photo_resp = await client.get(req.photo_url)
        photo_resp.raise_for_status()
        photo_bytes = photo_resp.content

    query_embedding = await _embedding_generator.generate(photo_bytes)
    enrolled = await _enrolled_repo.fetch_all()
    result = find_best_match(query_embedding, enrolled)
    mismatch = is_identity_mismatch(result, req.claimed_employee_id)

    await patch_checkpoint_match(
        checkpoint_event_id=req.checkpoint_event_id,
        result=result,
        service_token=user.raw_token,
    )

    # Every checkpoint verification touches an individual's data - logged
    # before returning, per Section 8. resource_id is the checkpoint event,
    # not the matched employee, since match_employee_id may be None.
    await log_action(
        actor_user_id=user.sub,
        actor_role="security_admin",
        action="checkpoint_verify",
        resource_type="checkpoint_events",
        resource_id=req.checkpoint_event_id,
        justification=f"zone={req.zone_id} status={result.match_status}",
    )

    if mismatch:
        # Flagged loudly since there's no alert-creation path wired yet -
        # see OPEN QUESTION above. Do not let this disappear silently into
        # an info-level log line only.
        logger.warning(
            "checkpoint identity mismatch (tailgating signal) zone=%s "
            "checkpoint_event_id=%s claimed=%s matched=%s - NO ALERT CREATED, "
            "alert-creation path not yet implemented pending schema/ownership",
            req.zone_id, req.checkpoint_event_id, req.claimed_employee_id, result.match_employee_id,
        )

    return CheckpointVerifyResult(
        checkpoint_event_id=req.checkpoint_event_id,
        match_employee_id=result.match_employee_id,
        match_confidence=result.match_confidence,
        match_status=result.match_status,
        identity_mismatch=mismatch,
    )
