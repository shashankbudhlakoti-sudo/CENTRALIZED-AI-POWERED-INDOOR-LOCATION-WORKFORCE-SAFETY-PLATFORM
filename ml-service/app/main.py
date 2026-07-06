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
