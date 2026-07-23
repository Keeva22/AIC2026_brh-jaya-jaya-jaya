"""
routers/stats.py
----------------
Handles all endpoints under /stats:
  - GET /stats/summary -> aggregate statistics (total scans, pass rate, etc.)
"""

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, cast, Date, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Scan
from app.schemas import DailyStat, SummaryStats

router = APIRouter(
    prefix="/stats",
    tags=["Statistics"],
)


# ---------------------------------------------------------------------------
# GET /stats/summary  — Aggregate QC statistics
# ---------------------------------------------------------------------------
@router.get(
    "/summary",
    response_model=SummaryStats,
    summary="Get aggregate scan statistics",
    description=(
        "Returns overall counts and pass rate. "
        "Optionally includes a per-day breakdown if 'group_by_day=true' is passed."
    ),
)
def get_summary(
    # Optional date range for filtering the stats window.
    date_from: Optional[date] = Query(
        default=None,
        description="Start of date range (inclusive). Format: YYYY-MM-DD.",
    ),
    date_to: Optional[date] = Query(
        default=None,
        description="End of date range (inclusive). Format: YYYY-MM-DD.",
    ),
    # If True, the response will include a day-by-day breakdown.
    group_by_day: bool = Query(
        default=False,
        description="If true, include a per-day breakdown in the response.",
    ),
    db: Session = Depends(get_db),
):
    """
    Computes aggregate statistics from the scans table.

    We use SQLAlchemy's 'func' to call SQL aggregate functions like COUNT()
    and SUM() directly in the database, which is much faster than loading
    all rows into Python and counting them there.

    The 'case()' construct is a SQL CASE WHEN statement — it lets us count
    only the rows that match a condition (e.g. count only "worthy" verdicts).
    """
    # Build a base query with optional date filtering.
    query = db.query(Scan)

    if date_from is not None:
        start_dt = datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
        query = query.filter(Scan.created_at >= start_dt)

    if date_to is not None:
        end_dt = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=timezone.utc)
        query = query.filter(Scan.created_at <= end_dt)

    # -----------------------------------------------------------------------
    # Overall aggregate query — a single SQL query that computes all counts.
    # -----------------------------------------------------------------------
    # func.count()  -> COUNT(*)        : total rows
    # func.sum(case(...))              : count rows where verdict = 'worthy'
    #
    # Equivalent SQL:
    #   SELECT
    #     COUNT(*) AS total,
    #     SUM(CASE WHEN verdict = 'worthy' THEN 1 ELSE 0 END) AS worthy_count
    #   FROM scans
    #   [WHERE created_at BETWEEN ...]
    aggregates = query.with_entities(
        func.count(Scan.id).label("total"),
        func.sum(
            case((Scan.verdict == "worthy", 1), else_=0)
        ).label("worthy_count"),
    ).one()  # .one() returns exactly one row (there's always one aggregate row).

    total_scans = aggregates.total or 0
    worthy_count = int(aggregates.worthy_count or 0)
    not_worthy_count = total_scans - worthy_count

    # Avoid division by zero when there are no scans yet.
    pass_rate = round(worthy_count / total_scans, 4) if total_scans > 0 else 0.0

    # -----------------------------------------------------------------------
    # Optional daily breakdown
    # -----------------------------------------------------------------------
    daily_breakdown = None

    if group_by_day:
        # Cast the timestamp to a date (drops the time component) so we can
        # GROUP BY day. This runs as a single SQL query:
        #
        #   SELECT
        #     DATE(created_at) AS day,
        #     COUNT(*) AS total,
        #     SUM(CASE WHEN verdict='worthy' THEN 1 ELSE 0 END) AS worthy
        #   FROM scans
        #   [WHERE ...]
        #   GROUP BY DATE(created_at)
        #   ORDER BY day ASC
        daily_rows = (
            query
            .with_entities(
                cast(Scan.created_at, Date).label("day"),
                func.count(Scan.id).label("total"),
                func.sum(
                    case((Scan.verdict == "worthy", 1), else_=0)
                ).label("worthy"),
            )
            .group_by(cast(Scan.created_at, Date))
            .order_by(cast(Scan.created_at, Date).asc())
            .all()
        )

        daily_breakdown = []
        for row in daily_rows:
            day_total = row.total or 0
            day_worthy = int(row.worthy or 0)
            day_not_worthy = day_total - day_worthy
            day_pass_rate = round(day_worthy / day_total, 4) if day_total > 0 else 0.0

            daily_breakdown.append(
                DailyStat(
                    date=str(row.day),  # Already a date object; str() gives "YYYY-MM-DD".
                    total=day_total,
                    worthy=day_worthy,
                    not_worthy=day_not_worthy,
                    pass_rate=day_pass_rate,
                )
            )

    return SummaryStats(
        total_scans=total_scans,
        worthy_count=worthy_count,
        not_worthy_count=not_worthy_count,
        pass_rate=pass_rate,
        daily_breakdown=daily_breakdown,
    )
