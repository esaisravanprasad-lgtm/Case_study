from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models import Finding, Receipt, Submission
from app.policy import exact_quote
from app.schemas import ReceiptFacts


TIER_1_CITIES = {
    "Boston",
    "Los Angeles",
    "New York",
    "San Francisco",
    "Seattle",
    "Washington",
}
TIER_2_CITIES = {
    "Atlanta",
    "Austin",
    "Chicago",
    "Dallas",
    "Denver",
    "Houston",
    "Miami",
    "Portland",
    "San Diego",
}
MEAL_CAPS = {"breakfast": 25.0, "lunch": 35.0, "dinner": 75.0}


@dataclass(frozen=True)
class RuleResult:
    code: str
    severity: str
    message: str
    document_id: str
    section: str
    quote_contains: str | None = None


def _facts(receipt: Receipt) -> ReceiptFacts:
    return ReceiptFacts.model_validate(json.loads(receipt.facts_json))


def _lodging_cap(city: str | None) -> float:
    if city in TIER_1_CITIES:
        return 350.0
    if city in TIER_2_CITIES:
        return 250.0
    return 175.0


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _base_rules(receipt: Receipt, facts: ReceiptFacts) -> list[RuleResult]:
    results: list[RuleResult] = []
    if facts.confidence < 0.65 or facts.missing_fields:
        results.append(
            RuleResult(
                "RECEIPT_EVIDENCE_INCOMPLETE",
                "needs_review",
                "Receipt extraction is incomplete or low confidence; a reviewer should verify the source document.",
                "TEP-007",
                "2",
                "A valid receipt must show",
            )
        )
    if facts.category == "meal" and facts.total is not None and facts.meal_type in MEAL_CAPS:
        cap = MEAL_CAPS[facts.meal_type]
        if facts.city in TIER_1_CITIES:
            cap *= 1.25
        if facts.total > cap:
            results.append(
                RuleResult(
                    "MEAL_CAP_EXCEEDED",
                    "flagged",
                    f"{facts.meal_type.title()} total ${facts.total:.2f} exceeds the applicable ${cap:.2f} cap.",
                    "TEP-002",
                    "2.2",
                    "Expenses above these caps",
                )
            )
    if facts.category == "meal" and facts.alcohol_amount > 0 and not facts.external_attendee_present:
        results.append(
            RuleResult(
                "SOLO_OR_TEAM_ALCOHOL",
                "flagged",
                f"${facts.alcohol_amount:.2f} of alcohol is not reimbursable without an external client present; review the food portion separately.",
                "TEP-003",
                "3.1",
                "Any alcoholic beverage purchased while traveling on business without external",
            )
        )
    if facts.category == "meal" and facts.tip_amount and facts.line_items:
        subtotal = sum(item.amount or 0.0 for item in facts.line_items)
        if subtotal > 0 and facts.tip_amount > subtotal * 0.2:
            results.append(
                RuleResult(
                    "TIP_CAP_EXCEEDED",
                    "flagged",
                    f"Tip ${facts.tip_amount:.2f} exceeds 20% of the itemized meal subtotal ${subtotal:.2f}.",
                    "TEP-002",
                    "3",
                    "Tips above 20%",
                )
            )
    if facts.category == "lodging" and facts.total is not None and facts.lodging_nights:
        nightly_rate = facts.total / facts.lodging_nights
        cap = _lodging_cap(facts.city)
        if nightly_rate > cap:
            results.append(
                RuleResult(
                    "LODGING_CAP_EXCEEDED",
                    "flagged",
                    f"Effective nightly lodging rate ${nightly_rate:.2f} exceeds the ${cap:.2f} city-tier cap.",
                    "TEP-004",
                    "3",
                    "Maximum reimbursable nightly rate",
                )
            )
        if facts.booked_outside_concur:
            results.append(
                RuleResult(
                    "OUTSIDE_CONCUR_LODGING",
                    "needs_review",
                    "Lodging was booked outside Concur; confirm manager approval and a brief justification.",
                    "TEP-004",
                    "2.1",
                    "Bookings outside the tool",
                )
            )
    if facts.category == "airfare":
        for segment in facts.flight_segments:
            if segment.cabin == "premium economy" and (
                segment.duration_minutes is None or segment.duration_minutes < 360
            ):
                results.append(
                    RuleResult(
                        "PREMIUM_FLIGHT_ELIGIBILITY",
                        "needs_review",
                        "Premium economy appears on a segment that is not proven to meet the six-hour threshold.",
                        "TEP-005",
                        "2.2",
                        "scheduled duration of 6 hours or more",
                    )
                )
                break
    if facts.category == "ground_transportation":
        text = receipt.extracted_text.lower()
        if "uber black" in text or "lyft lux" in text:
            results.append(
                RuleResult(
                    "PREMIUM_RIDESHARE",
                    "flagged",
                    "Premium rideshare is not reimbursable unless it was the only available option.",
                    "TEP-006",
                    "2.2",
                    "Premium categories",
                )
            )
    return results


def _cross_receipt_rules(submission: Submission, receipt: Receipt, facts: ReceiptFacts) -> list[RuleResult]:
    if facts.category != "meal" or not facts.meal_type:
        return []
    meal_date = _parse_date(facts.transaction_date)
    results: list[RuleResult] = []
    for other in submission.receipts:
        other_facts = _facts(other)
        if other_facts.category != "conference":
            continue
        if facts.meal_type not in other_facts.conference_included_meals:
            continue
        if meal_date and str(meal_date.day) not in other.extracted_text:
            continue
        results.append(
            RuleResult(
                "CONFERENCE_INCLUDED_MEAL",
                "flagged",
                f"A separate {facts.meal_type} was claimed even though the conference registration indicates that meal is included.",
                "TEP-014",
                "5.1",
                "no separate reimbursement is available",
            )
        )
    return results


def review_submission(db: Session, submission: Submission) -> None:
    total = 0.0
    for receipt in submission.receipts:
        facts = _facts(receipt)
        total += facts.total or 0.0
        receipt.category = facts.category
        receipt.amount = facts.total
        receipt.currency = facts.currency
        receipt.confidence = facts.confidence
        receipt.findings.clear()
        results = [*_base_rules(receipt, facts), *_cross_receipt_rules(submission, receipt, facts)]
        for result in results:
            receipt.findings.append(
                Finding(
                    rule_code=result.code,
                    severity=result.severity,
                    message=result.message,
                    policy_document_id=result.document_id,
                    policy_section=result.section,
                    policy_quote=exact_quote(
                        db, result.document_id, result.section, result.quote_contains
                    ),
                )
            )
        severities = {result.severity for result in results}
        receipt.verdict = (
            "flagged"
            if "flagged" in severities
            else ("needs_review" if "needs_review" in severities else "compliant")
        )
        receipt.reasoning = (
            " ".join(result.message for result in results)
            if results
            else "No deterministic policy exception was found in the extracted evidence."
        )
        receipt.suggested_action = (
            "Review the cited policy exception before reimbursement."
            if receipt.verdict == "flagged"
            else (
                "Verify the source document or missing approval before final review."
                if receipt.verdict == "needs_review"
                else "Approve if the extracted facts match the receipt."
            )
        )
    submission.total_amount = round(total, 2)
    if total > 5000:
        submission.approval_route = "VP approval required (submission total above $5,000)"
    elif total > 1000:
        submission.approval_route = "Director approval required (submission total above $1,000)"
    else:
        submission.approval_route = "Direct manager approval"
    effective = {receipt.effective_verdict for receipt in submission.receipts}
    submission.status = (
        "flagged"
        if "flagged" in effective
        else ("needs_review" if "needs_review" in effective else "compliant")
    )
    db.commit()

