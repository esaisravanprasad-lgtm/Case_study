from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, _normalize_database_url
from app.main import _safe_download_name, app
from app.models import Submission
from app.policy import citation_is_faithful


def test_seeded_samples_match_expected_review_pattern():
    with TestClient(app):
        with SessionLocal() as db:
            submissions = {
                row.source_label: row
                for row in db.scalars(select(Submission).order_by(Submission.id)).all()
            }
            assert submissions["01_clean_denver"].status == "compliant"
            assert submissions["02_clean_boston_conf"].status == "flagged"
            assert submissions["03_dinner_over_cap"].status == "flagged"
            assert submissions["04_alcohol_solo_travel"].status == "flagged"
            assert submissions["05_receipt_mismatch"].status == "flagged"
            assert all(
                citation_is_faithful(db, finding.policy_document_id, finding.policy_quote)
                for submission in submissions.values()
                for receipt in submission.receipts
                for finding in receipt.findings
            )


def test_dashboard_and_grounded_policy_assistant():
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        supported = client.post("/api/policy/ask", json={"question": "Are UberX airport rides reimbursable?"})
        assert supported.status_code == 200
        assert supported.json()["refused"] is False
        unsupported = client.post(
            "/api/policy/ask", json={"question": "How many vacation days do employees receive?"}
        )
        assert unsupported.status_code == 200
        assert unsupported.json()["refused"] is True


def test_eval_endpoint_returns_faithful_solo_alcohol_finding():
    with TestClient(app) as client:
        response = client.post(
            "/api/evaluate/receipt",
            json={
                "filename": "meal.txt",
                "text": "GRILL\n10 Jul 2025  8:10 PM\n  1  Burger $22.00\n  1  Beer $8.00\nGRAND TOTAL $32.00\nVisa ****1234",
                "employee": {},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["verdict"] == "flagged"
        assert payload["findings"][0]["document_id"] == "TEP-003"
        assert payload["findings"][0]["citation_faithful"] is True


def test_render_postgres_url_uses_psycopg3_dialect():
    assert (
        _normalize_database_url("postgresql://user:pass@host/db")
        == "postgresql+psycopg://user:pass@host/db"
    )


def test_download_filename_is_header_safe():
    assert _safe_download_name('receipt"\r\nunsafe.txt') == "receipt___unsafe.txt"
