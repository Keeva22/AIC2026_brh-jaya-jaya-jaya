"""
routers/scans.py
----------------
Handles all endpoints under /scans:
  - POST /scans           -> create a new scan record
  - GET  /scans           -> list scans (paginated, filterable)
  - GET  /scans/latest    -> the most recent N scans (for frontend polling)
"""

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Scan
from app.schemas import ObjectTypeEnum, PaginatedScans, ScanCreate, ScanRead, VerdictEnum

# An APIRouter groups related endpoints together. We include this router
# in main.py with a shared prefix ("/scans"), so we don't need to repeat
# "/scans" in every route decorator here.
router = APIRouter(
    prefix="/scans",
    tags=["Scans"],  # Groups these endpoints under "Scans" in the auto-docs UI.
)


# ---------------------------------------------------------------------------
# POST /scans  — Create a new scan record
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=ScanRead,
    status_code=status.HTTP_201_CREATED,  # 201 is more correct than 200 for "created"
    summary="Submit a new scan result",
    description="Called by the hardware device or inference script to record a scan verdict.",
)
def create_scan(
    payload: ScanCreate,          # Pydantic validates the incoming JSON body.
    db: Session = Depends(get_db), # FastAPI injects a DB session for this request.
):
    """
    Creates a new row in the 'scans' table.

    1. Pydantic automatically validates the request body (types, ranges, etc.).
    2. We build a SQLAlchemy Scan object from the validated data.
    3. We add it to the session, commit, and return the created record.
    """
    # Build the ORM object from validated Pydantic data.
    # .model_dump() converts the entire payload (including nested MissingComponent
    # objects) to a plain Python dict — nested models become plain dicts, which
    # is exactly what the JSON column expects for storage.
    new_scan = Scan(**payload.model_dump())

    db.add(new_scan)    # Tell SQLAlchemy to track this new object.
    db.commit()         # Write the INSERT to PostgreSQL.
    db.refresh(new_scan)  # Reload the object from DB to get server-set values
                          # (like 'id' and 'created_at' if they were set by DB).

    return new_scan


# ---------------------------------------------------------------------------
# GET /scans/latest  — Most recent N scans (for frontend polling)
# ---------------------------------------------------------------------------
# IMPORTANT: This route must be defined BEFORE GET /scans/{id} (if we had one).
# FastAPI matches routes top-to-bottom, and "latest" would otherwise be
# treated as an {id} path parameter and cause a validation error.
@router.get(
    "/latest",
    response_model=list[ScanRead],
    summary="Get the most recent scans",
    description=(
        "Returns the N most recent scans, ordered newest-first. "
        "Intended to be polled by the frontend every few seconds."
    ),
)
def get_latest_scans(
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="How many recent scans to return (1–100, default 10).",
    ),
    db: Session = Depends(get_db),
):
    """
    Fetches the most recent 'limit' scans, ordered by created_at descending.
    Simple and fast — no pagination needed here.
    """
    scans = (
        db.query(Scan)
        .order_by(Scan.created_at.desc())
        .limit(limit)
        .all()
    )
    return scans


# ---------------------------------------------------------------------------
# GET /scans  — List scans with pagination and filters
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=PaginatedScans,
    summary="List scans",
    description="Returns a paginated list of scans. Supports filtering by verdict and date range.",
)
def list_scans(
    # --- Filter parameters ---
    verdict: Optional[VerdictEnum] = Query(
        default=None,
        description="Filter by verdict: 'worthy' or 'not_worthy'.",
    ),
    date_from: Optional[date] = Query(
        default=None,
        description="Start of date range (inclusive). Format: YYYY-MM-DD.",
    ),
    date_to: Optional[date] = Query(
        default=None,
        description="End of date range (inclusive). Format: YYYY-MM-DD.",
    ),
    # --- Pagination parameters ---
    page: int = Query(
        default=1,
        ge=1,
        description="Page number to retrieve (starts at 1).",
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=200,
        description="Number of results per page (1–200, default 20).",
    ),
    db: Session = Depends(get_db),
):
    """
    Lists scans with optional filtering and pagination.

    Pagination works like this:
      - page=1, page_size=20 → rows 1–20
      - page=2, page_size=20 → rows 21–40
      etc.

    We always return the total count alongside the items so the frontend
    can calculate how many pages exist.
    """
    # Start with a base query on the Scan table.
    query = db.query(Scan)

    # Apply filters only if the caller provided them.
    if verdict is not None:
        query = query.filter(Scan.verdict == verdict.value)

    if date_from is not None:
        # Convert the date to a timezone-aware datetime at the start of the day.
        start_dt = datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
        query = query.filter(Scan.created_at >= start_dt)

    if date_to is not None:
        # The end date is inclusive, so we go to the end of that day (23:59:59).
        end_dt = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=timezone.utc)
        query = query.filter(Scan.created_at <= end_dt)

    # Count the total matching rows BEFORE applying pagination.
    # This is needed so the frontend knows the total number of pages.
    total = query.count()

    # Apply ordering and pagination.
    # offset = how many rows to skip, limit = how many rows to return.
    offset = (page - 1) * page_size
    scans = (
        query
        .order_by(Scan.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return PaginatedScans(
        total=total,
        page=page,
        page_size=page_size,
        items=scans,
    )
