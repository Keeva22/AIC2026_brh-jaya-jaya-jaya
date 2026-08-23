"""Pydantic schemas for request/response validation."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class ObjectTypeEnum(str, Enum):
    """Board types the AI/CV team supports — anything else gets a 422."""
    arduino_uno  = "arduino_uno"
    arduino_nano = "arduino_nano"
    esp32        = "esp32"
    raspberry_pi = "raspberry_pi"
    orange_pi    = "orange_pi"


class VerdictEnum(str, Enum):
    """Two valid verdicts; Pydantic rejects anything else."""
    worthy = "worthy"
    not_worthy = "not_worthy"


# ---------------------------------------------------------------------------
# Missing component schema
# ---------------------------------------------------------------------------

class ComponentLocation(BaseModel):
    """Optional location hint from the AI model — label, area, or both."""
    label: Optional[str] = Field(
        default=None,
        description="Exact silkscreen designator if visible on the board (e.g. 'R17', 'C3').",
        examples=["R17"],
    )
    area: Optional[str] = Field(
        default=None,
        description=(
            "Rough zone on the board described in Bahasa Indonesia, used when "
            "no exact label is available (e.g. 'kiri atas', 'dekat port USB')."
        ),
        examples=["kiri atas"],
    )

    model_config = {"extra": "ignore"}


class MissingComponent(BaseModel):
    """One missing component entry — name, how many, and where (optional)."""
    name: str = Field(
        ...,
        min_length=1,
        description="Label / name of the missing component, e.g. 'resistor'.",
        examples=["resistor"],
    )
    count: int = Field(
        ...,
        ge=1,
        description="How many of this component are missing (must be at least 1).",
        examples=[2],
    )
    location: Optional[ComponentLocation] = Field(
        default=None,
        description=(
            "Optional location hint for this missing component. "
            "Omit if the AI/CV model could not determine a position."
        ),
    )

    model_config = {
        # Extra fields (e.g. old x/y/confidence keys) are silently dropped.
        "extra": "ignore",
    }


# ---------------------------------------------------------------------------
# Scan schemas
# ---------------------------------------------------------------------------

class ScanCreate(BaseModel):
    """POST /scans body — fields the device sends; id/created_at are server-side."""
    object_type: ObjectTypeEnum = Field(
        ...,
        description=(
            "Type of PCB board scanned. Must be one of the supported board types: "
            "'arduino_uno', 'arduino_nano', 'esp32', 'raspberry_pi', 'orange_pi'. "
            "Any other value will be rejected with a 422 validation error."
        ),
        examples=["esp32"],
    )
    verdict: VerdictEnum = Field(
        ...,
        description="AI model verdict: 'worthy' or 'not_worthy'.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence score between 0.0 and 1.0.",
        examples=[0.97],
    )
    image_url: Optional[str] = Field(
        default=None,
        description="Optional URL pointing to the scan image.",
        examples=["https://storage.example.com/scans/abc123.jpg"],
    )
    missing_components: List[MissingComponent] = Field(
        default_factory=list,
        description=(
            "Optional list of missing components detected by the AI/CV model. "
            "Omit or pass an empty list if not available. Each item may include "
            "an optional 'location' object with a silkscreen label and/or area zone."
        ),
    )


class ScanRead(BaseModel):
    """Full scan record returned by the API, including server-generated fields."""
    id: int
    object_type: ObjectTypeEnum
    verdict: VerdictEnum
    confidence: float
    image_url: Optional[str]
    created_at: datetime
    missing_components: List[MissingComponent] = Field(
        default_factory=list,
        description=(
            "List of missing components, or empty list if none detected. "
            "Each item may include an optional 'location' object."
        ),
    )

    # Lets Pydantic read from SQLAlchemy ORM objects instead of plain dicts.
    model_config = {"from_attributes": True}

    @field_validator("missing_components", mode="before")
    @classmethod
    def coerce_none_to_empty_list(cls, v: Any) -> Any:
        """Old rows with NULL missing_components become [] instead of null."""
        return v if v is not None else []


class PaginatedScans(BaseModel):
    """Wrapper around a list of scans that also includes pagination metadata."""
    total: int = Field(description="Total number of scans matching the filters.")
    page: int = Field(description="Current page number (1-indexed).")
    page_size: int = Field(description="Number of items per page.")
    items: List[ScanRead]


# ---------------------------------------------------------------------------
# Stats schemas
# ---------------------------------------------------------------------------

class DailyStat(BaseModel):
    """Aggregate stats for a single day."""
    date: str = Field(description="Date in YYYY-MM-DD format.")
    total: int
    worthy: int
    not_worthy: int
    pass_rate: float = Field(description="Fraction of scans that were worthy (0.0–1.0).")


class SummaryStats(BaseModel):
    """GET /stats/summary response — overall counts plus optional daily breakdown."""
    total_scans: int
    worthy_count: int
    not_worthy_count: int
    pass_rate: float = Field(
        description="Fraction of total scans that passed (worthy / total). "
                    "Returns 0.0 if there are no scans yet."
    )
    daily_breakdown: Optional[List[DailyStat]] = None

    # Summed missing units per component name; None when no missing_components data exists.
    missing_component_counts: Optional[Dict[str, int]] = Field(
        default=None,
        description=(
            "Total number of missing units per component name, summed across all scans. "
            "e.g. {\"capacitor\": 12, \"resistor\": 5}. "
            "null when no scans have missing component data."
        ),
    )


# ---------------------------------------------------------------------------
# Health check schema
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Schema for GET /health response."""
    status: str = Field(description="'ok' when the service is healthy.")
    database: str = Field(description="'connected' or an error message.")

