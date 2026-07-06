import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, SmallInteger,
    Float, ForeignKey, JSON, BigInteger, Text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Employee(Base):
    __tablename__ = "employees"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_code = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(200), nullable=False)
    department = Column(String(100), nullable=False)
    role_title = Column(String(100))
    email = Column(String(200), unique=True)
    keycloak_user_id = Column(String(100), unique=True)
    consent_given = Column(Boolean, default=False, nullable=False)
    consent_given_at = Column(DateTime(timezone=True))
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tag_uid = Column(String(100), unique=True, nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    battery_pct = Column(SmallInteger)
    last_seen_at = Column(DateTime(timezone=True))
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Zone(Base):
    __tablename__ = "zones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    department = Column(String(100))
    floor = Column(Integer, default=1, nullable=False)
    zone_type = Column(String(50), default="general", nullable=False)
    # geom column omitted here; managed via raw SQL / GeoAlchemy2 Geometry type
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class PositionEvent(Base):
    __tablename__ = "position_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tag_id = Column(UUID(as_uuid=True), ForeignKey("tags.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    floor = Column(Integer, default=1, nullable=False)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    rssi_raw = Column(JSON)
    accuracy_m = Column(Float)
    source = Column(String(20), default="filtered", nullable=False)
    recorded_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class CheckpointEvent(Base):
    __tablename__ = "checkpoint_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_id = Column(UUID(as_uuid=True), ForeignKey("zones.id"), nullable=False)
    tag_id = Column(UUID(as_uuid=True), ForeignKey("tags.id"))
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    photo_url = Column(Text, nullable=False)
    match_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    match_confidence = Column(Float)
    match_status = Column(String(20), default="pending", nullable=False)
    triggered_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at = Column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_type = Column(String(30), nullable=False)
    severity = Column(String(20), default="warning", nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    zone_id = Column(UUID(as_uuid=True), ForeignKey("zones.id"))
    details = Column(JSON)
    acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_by = Column(String(100))
    acknowledged_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id = Column(String(100), nullable=False)
    actor_role = Column(String(30), nullable=False)
    action = Column(String(50), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(Text)
    justification = Column(Text)
    grant_type = Column(String(20), default="normal", nullable=False)
    grant_expires_at = Column(DateTime(timezone=True))
    ip_address = Column(String(45))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
