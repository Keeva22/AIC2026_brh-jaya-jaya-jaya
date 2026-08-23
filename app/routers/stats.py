"""Stats endpoints: GET /stats/summary."""

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
    date_from: Optional[date] = Query(
        default=None,
        description="Start of date range (inclusive). Format: YYYY-MM-DD.",
    ),
    date_to: Optional[date] = Query(
        default=None,
        description="End of date range (inclusive). Format: YYYY-MM-DD.",
    ),
    group_by_day: bool = Query(
        default=False,
        description="If true, include a per-day breakdown in the response.",
    ),
    db: Session = Depends(get_db),
):
    """Runs aggregate SQL queries and returns counts, pass rate, and optional daily breakdown."""
    query = db.query(Scan)

    if date_from is not None:
        start_dt = datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
        query = query.filter(Scan.created_at >= start_dt)

    if date_to is not None:
        end_dt = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=timezone.utc)
        query = query.filter(Scan.created_at <= end_dt)

    # Single query: COUNT(*) + SUM(CASE WHEN verdict='worthy' THEN 1 ELSE 0 END).
    aggregates = query.with_entities(
        func.count(Scan.id).label("total"),
        func.sum(
            case((Scan.verdict == "worthy", 1), else_=0)
        ).label("worthy_count"),
    ).one()

    total_scans = aggregates.total or 0
    worthy_count = int(aggregates.worthy_count or 0)
    not_worthy_count = total_scans - worthy_count

    pass_rate = round(worthy_count / total_scans, 4) if total_scans > 0 else 0.0

    daily_breakdown = None

    if group_by_day:
        # GROUP BY DATE(created_at) — truncates timestamp to day for bucketing.
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
                    date=str(row.day),
                    total=day_total,
                    worthy=day_worthy,
                    not_worthy=day_not_worthy,
                    pass_rate=day_pass_rate,
                )
            )

    # Sum missing component counts in Python — avoids DB-specific JSON unnesting SQL.
    from collections import Counter  # local import to keep top-level clean

    mc_rows = (
        query
        .with_entities(Scan.missing_components)
        .filter(Scan.missing_components.isnot(None))  # skip NULL rows (old records)
        .all()
    )

    component_counter: Counter = Counter()
    for (components,) in mc_rows:
        if components:  # skip empty lists
            for comp in components:
                name = comp.get("name") if isinstance(comp, dict) else getattr(comp, "name", None)
                qty = comp.get("count") if isinstance(comp, dict) else getattr(comp, "count", None)
                if name and isinstance(qty, int) and qty > 0:
                    component_counter[name] += qty

    # None means "no data" — field is omitted from the JSON response entirely.
    missing_component_counts = dict(component_counter) if component_counter else None

    return SummaryStats(
        total_scans=total_scans,
        worthy_count=worthy_count,
        not_worthy_count=not_worthy_count,
        pass_rate=pass_rate,
        daily_breakdown=daily_breakdown,
        missing_component_counts=missing_component_counts,
    )

