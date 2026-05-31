from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from statistics import mean
from typing import Any

import httpx


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def contains_expected_refs(actual: list[str], expected: list[str]) -> bool:
    return not expected or bool(set(actual) & set(expected))


def evaluate(dataset: dict[str, Any], base_url: str) -> dict[str, Any]:
    receipt_rows = []
    question_rows = []
    latencies = []
    with httpx.Client(base_url=base_url, timeout=90.0) as client:
        for case in dataset.get("receipts", []):
            started = time.perf_counter()
            response = client.post(
                "/api/evaluate/receipt",
                json={
                    "filename": case["filename"],
                    "content_type": case.get("content_type", "text/plain"),
                    "text": case["text"],
                    "employee": case.get("employee", {}),
                    "trip_purpose": case.get("trip_purpose", "Evaluation trip"),
                    "trip_dates": case.get("trip_dates", "2025-01-01 to 2025-01-02"),
                },
            )
            response.raise_for_status()
            payload = response.json()
            latencies.append(time.perf_counter() - started)
            references = [
                f'{finding["document_id"]} §{finding["section"]}'
                for finding in payload["findings"]
            ]
            expected_verdict = case.get("expected_verdict")
            receipt_rows.append(
                {
                    "id": case["id"],
                    "category_correct": payload["category"] == case.get("expected_category"),
                    "verdict_correct": payload["verdict"] == expected_verdict,
                    "expected_flag": expected_verdict == "flagged",
                    "predicted_flag": payload["verdict"] == "flagged",
                    "retrieval_hit": contains_expected_refs(
                        references, case.get("expected_policy_refs", [])
                    ),
                    "citation_faithful": all(
                        finding["citation_faithful"] for finding in payload["findings"]
                    ),
                    "extraction_complete": all(
                        payload["facts"].get(field) not in (None, "", [])
                        for field in case.get("required_fields", ["merchant", "total"])
                    ),
                }
            )
        for case in dataset.get("policy_questions", []):
            started = time.perf_counter()
            response = client.post("/api/policy/ask", json={"question": case["question"]})
            response.raise_for_status()
            payload = response.json()
            latencies.append(time.perf_counter() - started)
            references = [
                f'{citation["document_id"]} §{citation["section"]}'
                for citation in payload["citations"]
            ]
            question_rows.append(
                {
                    "question": case["question"],
                    "refusal_correct": payload["refused"] == case["expected_refused"],
                    "retrieval_hit": contains_expected_refs(
                        references, case.get("expected_policy_refs", [])
                    ),
                }
            )
    true_flags = sum(row["expected_flag"] for row in receipt_rows)
    false_flags = sum(row["predicted_flag"] and not row["expected_flag"] for row in receipt_rows)
    return {
        "receipt_cases": len(receipt_rows),
        "policy_question_cases": len(question_rows),
        "category_accuracy": ratio(sum(row["category_correct"] for row in receipt_rows), len(receipt_rows)),
        "verdict_accuracy": ratio(sum(row["verdict_correct"] for row in receipt_rows), len(receipt_rows)),
        "violation_recall": ratio(
            sum(row["expected_flag"] and row["predicted_flag"] for row in receipt_rows), true_flags
        ),
        "false_flag_rate": ratio(false_flags, len(receipt_rows)),
        "retrieval_recall_at_k": ratio(
            sum(row["retrieval_hit"] for row in [*receipt_rows, *question_rows]),
            len(receipt_rows) + len(question_rows),
        ),
        "citation_faithfulness": ratio(
            sum(row["citation_faithful"] for row in receipt_rows), len(receipt_rows)
        ),
        "out_of_scope_refusal_accuracy": ratio(
            sum(row["refusal_correct"] for row in question_rows), len(question_rows)
        ),
        "extraction_completeness": ratio(
            sum(row["extraction_complete"] for row in receipt_rows), len(receipt_rows)
        ),
        "mean_latency_seconds": round(mean(latencies), 4) if latencies else 0.0,
        "details": {"receipts": receipt_rows, "policy_questions": question_rows},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Northwind expense pre-review behavior.")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    print(json.dumps(evaluate(dataset, args.base_url.rstrip("/")), indent=2))


if __name__ == "__main__":
    main()

