"""
main.py
-------
The entry point of the FastAPI application.

This file:
  1. Creates the FastAPI app instance.
  2. Adds middleware (CORS, etc.).
  3. Registers all routers (groups of related endpoints).
  4. Creates database tables on startup if they don't exist yet.
  5. Defines the /health endpoint.

Think of this file as the "glue" that assembles everything together.
"""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.routers import scans, stats
from app.schemas import HealthResponse

# ---------------------------------------------------------------------------
# Create / migrate database tables on startup
# ---------------------------------------------------------------------------
# Step 1 — Lightweight schema migration: add the missing_components column to
# the scans table if it does not already exist.  This handles the case where
# the container was already running with the old schema (before this column
# was added).  PostgreSQL's "IF NOT EXISTS" clause makes this statement a
# completely safe no-op on brand-new databases or after the first migration.
try:
    with engine.connect() as _conn:
        _conn.execute(
            text(
                "ALTER TABLE scans "
                "ADD COLUMN IF NOT EXISTS missing_components JSONB"
            )
        )
        _conn.commit()
except Exception:
    # The table may not exist yet on a fresh deployment — create_all below
    # will handle that case.  Any other error surfaces at request time.
    pass

# Step 2 — Create any tables that don't exist yet (CREATE TABLE IF NOT EXISTS).
Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Hardware QC Inspection API",
    description=(
        "Backend API for a hardware QC inspection dashboard. "
        "Receives scan results from a device/AI model, stores them in PostgreSQL, "
        "and serves live and historical data to a frontend dashboard."
    ),
    version="1.0.0",
    # The auto-generated API docs are available at:
    #   http://localhost:8000/docs    (Swagger UI — interactive)
    #   http://localhost:8000/redoc   (ReDoc — clean reference)
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS Middleware
# ---------------------------------------------------------------------------
# CORS (Cross-Origin Resource Sharing) is a browser security feature.
# Without this, a frontend at http://localhost:3000 would be BLOCKED from
# calling our API at http://localhost:8000 (different ports = different origin).
#
# allow_origins: which frontend origins are allowed. We allow all ("*")
#   for local development simplicity. In production, restrict this to your
#   specific frontend URL, e.g. ["https://dashboard.mycompany.com"].
#
# allow_methods / allow_headers: we allow everything for development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Allow all origins in dev. Restrict in production!
    allow_credentials=True,
    allow_methods=["*"],        # Allow GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],        # Allow all request headers.
)

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------
# Each router handles its own group of endpoints. Including them here
# "mounts" them into the main app.
app.include_router(scans.router)
app.include_router(stats.router)


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------
# This is a simple endpoint that a monitoring system (or Docker healthcheck)
# can call to verify the service is alive and the database is reachable.
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Service health check",
    description="Returns 'ok' if the API is running and connected to the database.",
)
def health_check(db: Session = Depends(get_db)):
    """
    Checks that:
      1. The FastAPI app is running (if we reach this code, it is).
      2. We can execute a trivial query against PostgreSQL.

    Returns a 200 OK either way, with a 'database' field indicating
    whether the DB connection succeeded or showing the error message.
    """
    try:
        # Send a minimal query to verify the connection is alive.
        # 'text()' is needed to execute a raw SQL string safely.
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return HealthResponse(status="ok", database=db_status)
