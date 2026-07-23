"""
database.py
-----------
Sets up the database engine and session factory.

SQLAlchemy works like this:
  1. An "engine" is the low-level connection to PostgreSQL.
  2. A "SessionLocal" is a factory that creates individual database sessions.
  3. Each request gets its own session (opened at the start, closed at the end).
     This is the standard pattern recommended by FastAPI and SQLAlchemy.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Database URL
# ---------------------------------------------------------------------------
# This reads DATABASE_URL from environment variables.
# Docker Compose will inject this via the 'environment' section in
# docker-compose.yml, e.g.:
#   postgresql://user:password@db:5432/qc_db
#
# The "db" hostname matches the service name defined in docker-compose.yml.
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Make sure you're running via docker-compose or have a .env file loaded."
    )

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# connect_args is needed only for SQLite (not PostgreSQL), but we include
# a comment here so you know where to put it if you ever switch databases.
# pool_pre_ping=True tells SQLAlchemy to test the connection before using it,
# which prevents "connection lost" errors after the DB restarts.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
# autocommit=False  -> we manually commit transactions (safer / more explicit)
# autoflush=False   -> we control when SQLAlchemy sends pending changes to the DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ---------------------------------------------------------------------------
# Base class for ORM models
# ---------------------------------------------------------------------------
# Every SQLAlchemy model (table definition) will inherit from this Base.
Base = declarative_base()


# ---------------------------------------------------------------------------
# Dependency function for FastAPI
# ---------------------------------------------------------------------------
def get_db():
    """
    FastAPI dependency that yields a database session per request.

    Usage in a router:
        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...

    The 'try / finally' block ensures the session is ALWAYS closed after the
    request finishes, even if an error occurs. This prevents connection leaks.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
