"""
models.py
---------
Defines the database table structure using SQLAlchemy ORM.

"ORM" (Object-Relational Mapper) means we define our database tables as
Python classes. SQLAlchemy then handles generating the actual SQL statements
(CREATE TABLE, INSERT, SELECT, etc.) for us.

Each class here corresponds to one table in PostgreSQL.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy import CheckConstraint
from sqlalchemy import JSON

from app.database import Base


class Scan(Base):
    """
    Represents a single QC scan record in the 'scans' table.

    Each row in this table is one scan event from the hardware device:
    the device scanned an object, ran the AI model, got a verdict,
    and posted the result to our API.
    """

    # The name of the table in PostgreSQL.
    __tablename__ = "scans"

    # ---------- Columns ----------

    # Primary key: PostgreSQL will auto-increment this for each new row.
    id = Column(Integer, primary_key=True, index=True)

    # What kind of object was scanned (e.g. "PCB", "resistor").
    # 'index=True' creates a DB index on this column, making filtering
    # by object_type much faster on large datasets.
    object_type = Column(String, nullable=False, index=True)

    # The AI model's verdict. Constrained to only two values via CheckConstraint.
    # CheckConstraint is enforced by the DB itself, giving us a safety net even
    # if someone bypasses our API and inserts directly.
    verdict = Column(
        String,
        nullable=False,
        index=True,  # We'll filter by verdict frequently, so index it.
    )

    # The model's confidence in its verdict, from 0.0 (no confidence) to 1.0 (certain).
    confidence = Column(Float, nullable=False)

    # Optional URL to the scan image stored elsewhere (e.g. an S3 bucket).
    # nullable=True means this column can be left empty (NULL in the database).
    image_url = Column(String, nullable=True)

    # Optional list of missing component detections from the AI/CV model.
    # Stored as a JSON array so the schema is fully flexible — new optional
    # fields (e.g. bounding-box coords) can be added later without a migration.
    # Each element is a dict shaped like:
    #   { "name": str, "x": float|None, "y": float|None, "confidence": float|None }
    # 'default=list' ensures new rows get [] instead of NULL when the field
    # is omitted, and old rows already in the DB will return NULL (treated as
    # an empty list by the API layer).
    missing_components = Column(JSON, nullable=True, default=list)

    # Timestamp of when the scan record was created.
    # 'default' is applied by SQLAlchemy in Python before inserting the row.
    # We use timezone-aware UTC so there's no ambiguity when the frontend
    # is in a different timezone.
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,  # We'll filter by date range, so index this too.
    )

    # ---------- Table-level constraints ----------
    # These are extra rules enforced at the PostgreSQL level.
    __table_args__ = (
        # Verdict must be exactly "worthy" or "not_worthy" — nothing else.
        CheckConstraint(
            "verdict IN ('worthy', 'not_worthy')",
            name="ck_scans_verdict",
        ),
        # Confidence must be between 0 and 1 inclusive.
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_scans_confidence",
        ),
    )
