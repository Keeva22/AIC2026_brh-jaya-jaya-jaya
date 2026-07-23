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
# Create all database tables on startup
# ---------------------------------------------------------------------------
# This reads all SQLAlchemy models that inherit from 'Base' and issues
# CREATE TABLE IF NOT EXISTS statements for each one.
#
# This approach is simple and works well for this project. If you need
# to ALTER existing tables (e.g. add a new column to 'scans'), you would
# instead use Alembic migrations — but that's more complex to set up.
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
