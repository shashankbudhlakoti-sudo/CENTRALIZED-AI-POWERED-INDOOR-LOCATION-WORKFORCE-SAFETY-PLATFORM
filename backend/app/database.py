import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://safety:safety_dev_pw@localhost:5432/safety_platform"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency: yields a session, sets RLS session vars, closes after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def set_rls_context(db, department: str | None, role: str | None):
    """Call at the top of each request handler, after decoding the JWT,
    so Postgres row-level-security policies can enforce department isolation."""
    db.execute(text("SET app.current_department = :dept"), {"dept": department or ""})
    db.execute(text("SET app.current_role = :role"), {"role": role or ""})
