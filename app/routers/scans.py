"""Scan endpoints: POST /scans, GET /scans, GET /scans/latest."""

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Scan
from app.schemas import ObjectTypeEnum, PaginatedScans, ScanCreate, ScanRead, VerdictEnum

router = APIRouter(
    prefix="/scans",
    tags=["Scans"],
)


@router.post(
    "/",
    response_model=ScanRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new scan result",
    description="Called by the hardware device or inference script to record a scan verdict.",
)
def create_scan(
    payload: ScanCreate,
    db: Session = Depends(get_db),
):
    """Inserts a validated scan payload into the DB and returns the created row."""
    # model_dump() converts nested Pydantic models to plain dicts, which is what the JSON column needs.
    new_scan = Scan(**payload.model_dump())

    db.add(new_scan)
    db.commit()
    db.refresh(new_scan)  # Reload to pick up any server-set values (e.g. id, created_at).

    return new_scan


# NOTE: must be declared before any /{id} route or "latest" gets matched as a path param.
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
    """Returns the most recent `limit` scans, newest first."""
    scans = (
        db.query(Scan)
        .order_by(Scan.created_at.desc())
        .limit(limit)
        .all()
    )
    return scans


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
    """Filtered + paginated scan list; total count included for frontend paging."""
    query = db.query(Scan)

    if verdict is not None:
        query = query.filter(Scan.verdict == verdict.value)

    if date_from is not None:
        start_dt = datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
        query = query.filter(Scan.created_at >= start_dt)

    if date_to is not None:
        # End of the given day, inclusive.
        end_dt = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=timezone.utc)
        query = query.filter(Scan.created_at <= end_dt)

    # Count before pagination so the frontend knows total pages.
    total = query.count()

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

