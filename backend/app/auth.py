import os
from fastapi import Header, HTTPException
from jose import jwt, JWTError

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "safety-platform")

TIER_3_4_ROLES = {"hr_manager", "it_manager", "finance_manager", "security_admin", "general_manager"}
ALLOWED_SERVICE_CLIENTS = {"ml-service"}

class CurrentUser:
    def __init__(self, user_id: str, department: str, role: str, mfa: bool):
        self.user_id = user_id
        self.department = department
        self.role = role
        self.mfa = mfa

def get_current_user(authorization: str = Header(...)) -> CurrentUser:
    """
    Decodes and validates the Keycloak-issued JWT.
    Note: Replace with JWKS signature verification for production.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": {"code": "no_token", "message": "Missing bearer token"}})

    token = authorization.split(" ", 1)[1]

    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        raise HTTPException(status_code=401, detail={"error": {"code": "bad_token", "message": "Invalid token"}})

    roles = claims.get("realm_access", {}).get("roles", [])
    role = next((r for r in roles if r in TIER_3_4_ROLES), None)

    if not role:
        raise HTTPException(status_code=403, detail={"error": {"code": "no_role", "message": "No recognized role in token"}})

    # Check MFA - Using ACR as per Shashank's latest update
    mfa = claims.get("acr") == "mfa"
    
    if role in TIER_3_4_ROLES and not mfa:
        raise HTTPException(status_code=403, detail={"error": {"code": "mfa_required", "message": "MFA required for this role"}})

    return CurrentUser(
        user_id=claims.get("sub", ""),
        department=claims.get("department", ""),
        role=role,
        mfa=mfa,
    )

def get_service_caller(authorization: str = Header(...)) -> str:
    """
    Validates a token for machine-to-machine endpoints (e.g., ml-service).
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": {"code": "no_token", "message": "Missing bearer token"}})

    token = authorization.split(" ", 1)[1]

    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        raise HTTPException(status_code=401, detail={"error": {"code": "bad_token", "message": "Invalid token"}})

    client_id = claims.get("azp", "")
    if client_id not in ALLOWED_SERVICE_CLIENTS:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "not_a_service_client", "message": f"Client '{client_id}' is not an approved service caller"}},
        )

    return client_id