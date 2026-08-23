"""DB engine + session setup."""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Pulled from env — Docker Compose injects this via docker-compose.yml.
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Make sure you're running via docker-compose or have a .env file loaded."
    )

# pool_pre_ping keeps stale connections from blowing up after a DB restart.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Manual commit/flush — we control when changes actually hit the DB.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# All ORM models inherit from this.
Base = declarative_base()


def get_db():
    """Yields a DB session per request; always closes it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
