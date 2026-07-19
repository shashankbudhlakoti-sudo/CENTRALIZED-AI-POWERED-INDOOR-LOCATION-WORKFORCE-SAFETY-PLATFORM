import os
from fastapi import Header, HTTPException
from jose import jwt, JWTError

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "safety-platform")

TIER_3_4_ROLES = {"security_admin", "general_manager"}

# Shared with ml-service/app/security/auth.py - keep both in sync when
# adding new MFA methods. Only 'otp' is actually configured and tested in
# the realm right now.
MFA_METHODS = {"otp"}


class CurrentUser:
    def __init__(self, user_id: str, department: str, role: str, mfa: bool):
        self.user_id = user_id
        self.department = department
        self.role = role
        self.mfa = mfa


def get_current_user(authorization: str = Header(...)) -> CurrentUser:
    """
    Decodes and validates the Keycloak-issued JWT.
    NOTE: in production, fetch and cache the realm's JWKS from
    {KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs
    and verify signature properly. This skeleton decodes without
    signature verification for local dev only — replace before any
    real deployment (Phase 8 hardening).
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": {"code": "no_token", "message": "Missing bearer token"}})

    token = authorization.split(" ", 1)[1]

    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        raise HTTPException(status_code=401, detail={"error": {"code": "bad_token", "message": "Invalid token"}})

    roles = claims.get("realm_access", {}).get("roles", [])
    role = next((r for r in roles if r in {
        "hr_manager", "it_manager", "finance_manager", "security_admin", "general_manager"
    }), None)

    if not role:
        raise HTTPException(status_code=403, detail={"error": {"code": "no_role", "message": "No recognized role in token"}})

    # amr (Authentication Methods References) is a standard OIDC claim
    # listing which auth methods were actually used - e.g. ["pwd"] or
    # ["pwd", "otp"]. acr does NOT reliably contain the literal string
    # "mfa" (Keycloak emits numeric-string values like "0"/"1" by default),
    # so checking acr == "mfa" always evaluates False regardless of
    # whether OTP actually happened.
    #
    # CONFIRMED WORKING 2026-07-12: real OTP login produces amr: ["otp"],
    # verified against a fully-reset Keycloak volume (docker compose down -v
    # required - a plain `restart` reuses the old session/volume state and
    # will show stale/empty amr, which is what caused the false "broken
    # realm config" diagnosis earlier - the realm config is fine, the test
    # just needs a genuine fresh session against a genuinely fresh volume).
    #
    # If this claim comes back empty again: first confirm you did a full
    # `docker compose down -v` + fresh login in a private browser window
    # before assuming the realm itself is broken.
    amr = set(claims.get("amr", []))
    mfa = bool(amr & MFA_METHODS)

    if role in TIER_3_4_ROLES and not mfa:
        raise HTTPException(status_code=403, detail={"error": {"code": "mfa_required", "message": "MFA required for this role"}})

    return CurrentUser(
        user_id=claims.get("sub", ""),
        department=claims.get("department", ""),
        role=role,
        mfa=mfa,
    )


# Client IDs allowed to call service-to-service endpoints (anomalies, checkpoint match).
# These are machine credentials (client_credentials grant) — never subject to the
# human MFA check above, since there's no interactive login to complete MFA on.
ALLOWED_SERVICE_CLIENTS = {"ml-service", "corridor-camera"}


def get_service_caller(authorization: str = Header(...)) -> str:
    """
    Validates a token was issued to an approved service client (client_credentials
    grant), for machine-to-machine endpoints like POST /anomalies/detect and
    PATCH /checkpoints/{id}/match. Deliberately does NOT reuse get_current_user's
    human-role/MFA logic — a service account can never complete interactive MFA,
    so applying that check here would permanently lock the service out.

    Same production caveat as get_current_user: verify JWT signature via JWKS
    before real deployment, not just decode unverified claims.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": {"code": "no_token", "message": "Missing bearer token"}})

    token = authorization.split(" ", 1)[1]

    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        raise HTTPException(status_code=401, detail={"error": {"code": "bad_token", "message": "Invalid token"}})

    # "azp" (authorized party) identifies which client this token was issued to.
    client_id = claims.get("azp", "")
    if client_id not in ALLOWED_SERVICE_CLIENTS:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "not_a_service_client", "message": f"Client '{client_id}' is not an approved service caller"}},
        )

    return client_id
