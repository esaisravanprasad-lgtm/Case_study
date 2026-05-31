from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

from openai import OpenAI
from pypdf import PdfReader

from app.config import settings
from app.schemas import FlightSegment, LineItem, ReceiptFacts


logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".txt"}
ALCOHOL_WORDS = {
    "beer",
    "wine",
    "hefeweizen",
    "ale",
    "lager",
    "vodka",
    "whiskey",
    "cocktail",
    "martini",
    "tequila",
    "seltzer",
}
CITY_RE = re.compile(
    r"\b(Boston|Chicago|Denver|Austin|Seattle|Atlanta|Dallas|Houston|Miami|Portland|"
    r"San Diego|Los Angeles|San Francisco|New York|Washington)\b",
    re.IGNORECASE,
)


def validate_upload(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file type. Upload PDF, JPG, PNG, or TXT receipts.")
    if not content:
        raise ValueError("The uploaded receipt is empty.")
    if len(content) > settings.max_upload_bytes:
        raise ValueError(f"{filename} exceeds the {settings.max_upload_bytes // 1024 // 1024} MB limit.")
    return extension


def extract_text(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension == ".txt":
        return content.decode("utf-8", errors="replace")
    if extension == ".pdf":
        try:
            return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
        except Exception:
            return ""
    return ""


def _amount(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
    if not matches:
        return None
    raw = matches[-1] if isinstance(matches[-1], str) else matches[-1][0]
    return float(raw.replace(",", ""))


def _clean_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not set(line.strip()) <= {"=", "-", "_"}
    ]


def _merchant(lines: list[str]) -> str | None:
    for line in lines[:6]:
        if line.lower().startswith(("electronic ticket", "booking reference", "confirmation")):
            continue
        return line.title() if line.isupper() else line
    return None


def _parse_date(text: str) -> str | None:
    patterns = [
        r"\b(\d{1,2}\s+[A-Z][a-z]{2}\s+20\d{2})\b",
        r"\b([A-Z][a-z]{2}\s+\d{1,2},\s+20\d{2})\b",
        r"\b(20\d{2}-\d{2}-\d{2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1)
            for format_string in ("%d %b %Y", "%b %d, %Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value, format_string).date().isoformat()
                except ValueError:
                    pass
    return None


def _category(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("airlines", "air lines", "e-ticket", "flight")):
        return "airfare"
    if any(word in lower for word in ("hotel", "marriott", "hyatt", "hilton", "nights:")):
        return "lodging"
    if any(word in lower for word in ("uber", "lyft", "taxi", "driver:")):
        return "ground_transportation"
    if any(word in lower for word in ("conference", "registration confirmation", "workshop add-on")):
        return "conference"
    if any(word in lower for word in ("grand total", "table ", "server:", "order #:")):
        return "meal"
    return "unknown"


def _line_items(text: str) -> list[LineItem]:
    items: list[LineItem] = []
    pattern = re.compile(r"^\s*\d+\s+(.+?)\s+\$([0-9,]+\.\d{2})\s*$", re.MULTILINE)
    for description, amount in pattern.findall(text):
        lower = description.lower()
        items.append(
            LineItem(
                description=description.strip(),
                amount=float(amount.replace(",", "")),
                quantity=1,
                is_alcohol=any(word in lower for word in ALCOHOL_WORDS),
            )
        )
    return items


def _meal_type(text: str, merchant: str | None) -> str:
    lower = f"{merchant or ''} {text}".lower()
    time_match = re.search(r"\b(\d{1,2}):\d{2}\s*(am|pm)\b", lower)
    if time_match:
        hour = int(time_match.group(1))
        meridiem = time_match.group(2)
        if meridiem == "am":
            return "breakfast" if hour <= 10 else "lunch"
        return "lunch" if hour <= 4 else "dinner"
    if any(word in lower for word in ("breakfast", "pancake", "a.m. eatery", "migas", "coffee")):
        return "breakfast"
    return "unknown"


def _flight_segments(text: str) -> list[FlightSegment]:
    segments: list[FlightSegment] = []
    route_pattern = re.compile(r"\b([A-Z]{3}\s*->\s*[A-Z]{3})\b")
    routes = route_pattern.findall(text)
    durations = [
        int(hours) * 60 + int(minutes)
        for hours, minutes in re.findall(r"Duration\s+(\d+)h\s+(\d+)m", text, re.IGNORECASE)
    ]
    cabin = None
    lower = text.lower()
    if "premium select" in lower or "premium economy" in lower:
        cabin = "premium economy"
    elif "business" in lower:
        cabin = "business"
    elif "first class" in lower:
        cabin = "first"
    elif "main cabin" in lower or "economy" in lower or "wanna get away" in lower:
        cabin = "economy"
    for index, route in enumerate(routes):
        segments.append(
            FlightSegment(
                route=re.sub(r"\s+", " ", route),
                duration_minutes=durations[index] if index < len(durations) else None,
                cabin=cabin if index == 0 else ("economy" if cabin == "premium economy" else cabin),
            )
        )
    return segments


def parse_text_receipt(text: str) -> ReceiptFacts:
    lines = _clean_lines(text)
    merchant = _merchant(lines)
    category = _category(text)
    total = _amount(r"(?:GRAND TOTAL|Total Charged|(?<!Grand )TOTAL)\s+\$?([0-9,]+\.\d{2})", text)
    tip = _amount(r"Tip(?:\s+\([^)]+\))?\s+\$?(-?[0-9,]+\.\d{2})", text)
    items = _line_items(text)
    alcohol_amount = sum(item.amount or 0.0 for item in items if item.is_alcohol)
    city_match = CITY_RE.search(text)
    nights_match = re.search(r"Nights:\s*(\d+)", text, re.IGNORECASE)
    included = []
    includes_match = re.search(r"Includes:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if includes_match:
        include_text = includes_match.group(1).lower()
        for meal in ("breakfast", "lunch", "reception"):
            if meal in include_text:
                included.append(meal)
    missing = []
    if not merchant:
        missing.append("merchant")
    if not _parse_date(text):
        missing.append("transaction_date")
    if total is None:
        missing.append("total")
    if not re.search(r"(?:Visa|Mastercard|Amex|Cash|Payment|Card|Method):?", text, re.IGNORECASE):
        missing.append("payment_method")
    confidence = max(0.15, 0.98 - len(missing) * 0.18)
    return ReceiptFacts(
        merchant=merchant,
        transaction_date=_parse_date(text),
        total=total,
        category=category,
        payment_method=(
            "Corporate card"
            if "corporate" in text.lower()
            else ("Card" if re.search(r"visa|card:", text, re.IGNORECASE) else None)
        ),
        card_last_four=(re.search(r"\*{4}(\d{4})", text).group(1) if re.search(r"\*{4}(\d{4})", text) else None),
        line_items=items,
        alcohol_amount=round(alcohol_amount, 2),
        tip_amount=tip,
        meal_type=_meal_type(text, merchant) if category == "meal" else None,
        city=city_match.group(1).title() if city_match else None,
        lodging_nights=int(nights_match.group(1)) if nights_match else None,
        booked_outside_concur="outside concur" in text.lower(),
        room_category=("standard" if "standard" in text.lower() else None),
        flight_segments=_flight_segments(text),
        conference_included_meals=included,
        attendees=re.findall(r"(?:Other attendees:|Attendees:)\s*(.+)", text, re.IGNORECASE),
        external_attendee_present="external" in text.lower() and "no external" not in text.lower(),
        confidence=confidence,
        missing_fields=missing,
    )


def _extract_with_openai(filename: str, content_type: str, content: bytes, text: str) -> ReceiptFacts:
    if not settings.openai_api_key:
        return ReceiptFacts(confidence=0.0, missing_fields=["openai_api_key"])
    client = OpenAI(api_key=settings.openai_api_key)
    instructions = (
        "Extract the receipt facts conservatively. Do not infer missing values. "
        "Use unknown categories and missing_fields when evidence is absent."
    )
    if text:
        user_content = [{"type": "input_text", "text": text}]
    else:
        encoded = base64.b64encode(content).decode("ascii")
        if content_type == "application/pdf":
            user_content = [
                {
                    "type": "input_file",
                    "filename": filename,
                    "file_data": f"data:application/pdf;base64,{encoded}",
                }
            ]
        else:
            user_content = [
                {"type": "input_image", "image_url": f"data:{content_type};base64,{encoded}"}
            ]
    response = client.responses.parse(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_content},
        ],
        text_format=ReceiptFacts,
    )
    return response.output_parsed


def extract_receipt(filename: str, content_type: str, content: bytes) -> tuple[str, ReceiptFacts]:
    validate_upload(filename, content)
    text = extract_text(filename, content)
    if text.strip():
        facts = parse_text_receipt(text)
        if facts.confidence >= 0.65:
            return text, facts
    try:
        return text, _extract_with_openai(filename, content_type, content, text)
    except Exception:
        logger.exception("Receipt model fallback failed for %s", filename)
        facts = parse_text_receipt(text) if text.strip() else ReceiptFacts()
        facts.confidence = min(facts.confidence, 0.45)
        facts.missing_fields = sorted(set([*facts.missing_fields, "model_fallback_failed"]))
        return text, facts
