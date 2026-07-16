-- ============================================================
-- Indoor Location & Workforce Safety Platform
-- /contracts/schema.sql  — SHARED CONTRACT (Track A + Track B)
-- Postgres 15+ with PostGIS extension
-- ============================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector, compiled into the custom postgres/Dockerfile image

-- ------------------------------------------------------------
-- ENUM TYPES
-- ------------------------------------------------------------
CREATE TYPE user_role AS ENUM (
    'hr_manager', 'it_manager', 'finance_manager',
    'security_admin', 'general_manager'
);

CREATE TYPE alert_type AS ENUM (
    'zone_breach', 'fall_detected', 'inactivity',
    'panic_button', 'unauthorized_access', 'checkpoint_mismatch', 'tag_offline',
    'impossible_travel'
);

CREATE TYPE alert_severity AS ENUM ('info', 'warning', 'critical');

CREATE TYPE access_grant_type AS ENUM ('normal', 'break_glass', 'delegated');

-- ------------------------------------------------------------
-- EMPLOYEES
-- ------------------------------------------------------------
CREATE TABLE employees (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_code   VARCHAR(50) UNIQUE NOT NULL,
    full_name       VARCHAR(200) NOT NULL,
    department      VARCHAR(100) NOT NULL,
    role_title      VARCHAR(100),
    email           VARCHAR(200) UNIQUE,
    keycloak_user_id VARCHAR(100) UNIQUE, -- links to Keycloak identity
    consent_given   BOOLEAN NOT NULL DEFAULT FALSE,
    consent_given_at TIMESTAMPTZ,
    face_embedding  VECTOR(128), -- nullable until enrolled; written by hr_manager/security_admin enrollment flow
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- TAGS (BLE beacons / badges assigned to employees)
-- ------------------------------------------------------------
CREATE TABLE tags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tag_uid         VARCHAR(100) UNIQUE NOT NULL, -- MAC / beacon UUID
    employee_id     UUID REFERENCES employees(id) ON DELETE SET NULL,
    battery_pct     SMALLINT,
    last_seen_at    TIMESTAMPTZ,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- ZONES (polygons per floor, department-scoped for RLS)
-- ------------------------------------------------------------
CREATE TABLE zones (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(150) NOT NULL,
    department      VARCHAR(100), -- NULL = shared/common zone
    floor           INT NOT NULL DEFAULT 1,
    zone_type       VARCHAR(50) NOT NULL DEFAULT 'general', -- 'restricted','hazard','checkpoint','general'
    geom            GEOMETRY(POLYGON, 0) NOT NULL, -- local coordinate plane (meters), not lat/lon
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- POSITION EVENTS (raw + filtered BLE positions, high volume)
-- ------------------------------------------------------------
CREATE TABLE position_events (
    id              BIGSERIAL PRIMARY KEY,
    tag_id          UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    employee_id     UUID REFERENCES employees(id) ON DELETE SET NULL,
    floor           INT NOT NULL DEFAULT 1,
    x               DOUBLE PRECISION NOT NULL, -- meters, local plane
    y               DOUBLE PRECISION NOT NULL,
    rssi_raw        JSONB, -- {gateway_id: rssi, ...} snapshot used for fingerprinting
    accuracy_m      REAL,  -- estimated positioning error
    source          VARCHAR(20) NOT NULL DEFAULT 'filtered', -- 'raw' | 'filtered'
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Partition-friendly index; consider monthly partitioning at scale
CREATE INDEX idx_position_events_tag_time ON position_events (tag_id, recorded_at DESC);
CREATE INDEX idx_position_events_time ON position_events (recorded_at DESC);

-- ------------------------------------------------------------
-- CHECKPOINT EVENTS (camera fusion — shared feature, split seam)
-- ------------------------------------------------------------
CREATE TABLE checkpoint_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_id         UUID NOT NULL REFERENCES zones(id),
    tag_id          UUID REFERENCES tags(id),
    employee_id     UUID REFERENCES employees(id),
    photo_url       TEXT NOT NULL,            -- Track A: stores captured photo
    match_employee_id UUID REFERENCES employees(id), -- Track B: face-match result
    match_confidence REAL,                    -- Track B: face-match result
    match_status    VARCHAR(20) NOT NULL DEFAULT 'pending', -- 'pending','match','mismatch','no_face'
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

-- ------------------------------------------------------------
-- ALERTS
-- ------------------------------------------------------------
CREATE TABLE alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type      alert_type NOT NULL,
    severity        alert_severity NOT NULL DEFAULT 'warning',
    employee_id     UUID REFERENCES employees(id),
    zone_id         UUID REFERENCES zones(id),
    details         JSONB,
    acknowledged    BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_by UUID, -- keycloak_user_id of acknowledging user
    acknowledged_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_alerts_unacked ON alerts (created_at DESC) WHERE acknowledged = FALSE;

-- ------------------------------------------------------------
-- AUDIT LOG (every data access, compliance requirement)
-- ------------------------------------------------------------
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    actor_user_id   VARCHAR(100) NOT NULL, -- keycloak_user_id
    actor_role      user_role NOT NULL,
    action          VARCHAR(50) NOT NULL,  -- 'read','export','break_glass','delegate','delete'
    resource_type   VARCHAR(50) NOT NULL,  -- 'employee','position_events','alerts', etc.
    resource_id     TEXT,
    justification   TEXT, -- required for break_glass
    grant_type      access_grant_type NOT NULL DEFAULT 'normal',
    grant_expires_at TIMESTAMPTZ,
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_log_actor ON audit_log (actor_user_id, created_at DESC);

-- ------------------------------------------------------------
-- ROW-LEVEL SECURITY (department isolation, Phase 6)
-- Applied to Track A's backend; app connects with a role that
-- sets `app.current_department` and `app.current_role` per request.
-- ------------------------------------------------------------
ALTER TABLE employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE position_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE zones ENABLE ROW LEVEL SECURITY;
ALTER TABLE tags ENABLE ROW LEVEL SECURITY;

CREATE POLICY employees_department_isolation ON employees
    USING (
        current_setting('app.current_role', true) IN ('security_admin', 'general_manager')
        OR department = current_setting('app.current_department', true)
    );

CREATE POLICY zones_department_isolation ON zones
    USING (
        current_setting('app.current_role', true) IN ('security_admin', 'general_manager')
        OR department IS NULL
        OR department = current_setting('app.current_department', true)
    );

CREATE POLICY position_events_department_isolation ON position_events
    USING (
        current_setting('app.current_role', true) IN ('security_admin', 'general_manager')
        OR employee_id IN (
            SELECT id FROM employees
            WHERE department = current_setting('app.current_department', true)
        )
    );

CREATE POLICY tags_department_isolation ON tags
    USING (
        current_setting('app.current_role', true) IN ('security_admin', 'general_manager')
        OR employee_id IS NULL  -- unassigned tags (inventory) visible to everyone
        OR employee_id IN (
            SELECT id FROM employees
            WHERE department = current_setting('app.current_department', true)
        )
    );

-- ------------------------------------------------------------
-- ML SERVICE DATABASE ROLE
-- Direct-DB-access role for the ML service (position filtering,
-- anomaly detection, checkpoint face-match). Read-only on business
-- data, with a narrow write exception for its own audit logging.
-- ------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ml_service_ro') THEN
        CREATE ROLE ml_service_ro WITH LOGIN PASSWORD 'ml_service_dev_pw';
    END IF;
END
$$;

-- Revoke first, in case a broader grant was applied manually at some point
-- (e.g. GRANT SELECT ON ALL TABLES IN SCHEMA public) — always re-apply the
-- narrow, intentional grants below as the source of truth.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ml_service_ro;

GRANT SELECT ON zones, tags, employees, position_events, checkpoint_events TO ml_service_ro;
GRANT INSERT ON audit_log TO ml_service_ro;
GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO ml_service_ro;
-- Deliberately NOT granted: INSERT/UPDATE/DELETE on any table except
-- audit_log. If ml_service_ro is ever seen writing anywhere else,
-- that's a real bug — grants should be revisited, not the name changed.

-- ------------------------------------------------------------
-- RETENTION / AUTO-PURGE (compliance, 30-90 days, cron job calls this)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION purge_expired_position_events(retention_days INT DEFAULT 90)
RETURNS INT AS $$
DECLARE
    deleted_count INT;
BEGIN
    DELETE FROM position_events
    WHERE recorded_at < now() - (retention_days || ' days')::INTERVAL;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;