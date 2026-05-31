from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    amount: float | None = None
    quantity: int | None = None
    is_alcohol: bool = False


class FlightSegment(BaseModel):
    route: str
    duration_minutes: int | None = None
    cabin: str | None = None


class ReceiptFacts(BaseModel):
    merchant: str | None = None
    transaction_date: str | None = None
    total: float | None = None
    currency: str = "USD"
    category: Literal[
        "airfare",
        "lodging",
        "ground_transportation",
        "meal",
        "conference",
        "other",
        "unknown",
    ] = "unknown"
    payment_method: str | None = None
    card_last_four: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    alcohol_amount: float = 0.0
    tip_amount: float | None = None
    meal_type: Literal["breakfast", "lunch", "dinner", "unknown"] | None = None
    city: str | None = None
    lodging_nights: int | None = None
    booked_outside_concur: bool = False
    room_category: str | None = None
    flight_segments: list[FlightSegment] = Field(default_factory=list)
    conference_included_meals: list[str] = Field(default_factory=list)
    attendees: list[str] = Field(default_factory=list)
    external_attendee_present: bool = False
    confidence: float = 0.0
    missing_fields: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    document_id: str
    section: str
    quote: str


class PolicyAnswer(BaseModel):
    answer: str
    refused: bool
    citations: list[Citation] = Field(default_factory=list)


class EvalReceiptRequest(BaseModel):
    filename: str
    content_type: str = "text/plain"
    text: str
    employee: dict
    trip_purpose: str = "Evaluation trip"
    trip_dates: str = "2025-01-01 to 2025-01-02"

