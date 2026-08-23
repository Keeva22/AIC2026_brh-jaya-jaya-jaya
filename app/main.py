"""FastAPI app entry point — wires up middleware, routers, and DB tables."""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.routers import scans, stats
from app.schemas import HealthResponse

# Add missing_components column if it doesn't exist yet (safe no-op on fresh DBs).
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
    # Table might not exist yet — create_all below handles that.
    pass

# Create any missing tables.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Hardware QC Inspection API",
    description=(
        "Backend API for a hardware QC inspection dashboard. "
        "Receives scan results from a device/AI model, stores them in PostgreSQL, "
        "and serves live and historical data to a frontend dashboard."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow all origins in dev — lock this down to the real frontend URL in prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scans.router)
app.include_router(stats.router)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Service health check",
    description="Returns 'ok' if the API is running and connected to the database.",
)
def health_check(db: Session = Depends(get_db)):
    """Pings the DB with SELECT 1 and reports back whether it's reachable."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return HealthResponse(status="ok", database=db_status)

