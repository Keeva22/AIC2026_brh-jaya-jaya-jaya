"""ORM table definitions for the QC scan data."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy import CheckConstraint
from sqlalchemy import JSON

from app.database import Base


class Scan(Base):
    """Single scan record — one row per device scan event."""

    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)

    # Indexed so filtering by board type stays fast on big datasets.
    object_type = Column(String, nullable=False, index=True)

    # DB-level check constraint enforces only "worthy"/"not_worthy" — see below.
    verdict = Column(
        String,
        nullable=False,
        index=True,
    )

    confidence = Column(Float, nullable=False)

    image_url = Column(String, nullable=True)

    # Flexible JSON array of missing component dicts; default=list avoids NULL on insert.
    missing_components = Column(JSON, nullable=True, default=list)

    # UTC-aware timestamp set by SQLAlchemy before insert.
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "verdict IN ('worthy', 'not_worthy')",
            name="ck_scans_verdict",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_scans_confidence",
        ),
    )
