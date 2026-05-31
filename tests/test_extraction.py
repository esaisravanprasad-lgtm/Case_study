from dataclasses import replace

import app.extraction as extraction
from app.extraction import extract_receipt, parse_text_receipt, validate_upload


def test_dinner_with_coffee_uses_timestamp_before_keyword():
    facts = parse_text_receipt(
        "AVANTI\n15 Apr 2025  7:10 PM\n  1  Bowl $19.00\n  1  Cold Brew Coffee $5.00\n"
        "GRAND TOTAL $24.00\nVisa ****1234"
    )
    assert facts.category == "meal"
    assert facts.meal_type == "dinner"


def test_unsupported_upload_is_rejected():
    try:
        validate_upload("malware.exe", b"content")
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)
    else:
        raise AssertionError("Executable upload should be rejected")


def test_solo_alcohol_is_extracted_separately():
    facts = parse_text_receipt(
        "GRILL\n10 Jul 2025  8:10 PM\n  1  Burger $22.00\n  1  Beer $8.00\n"
        "GRAND TOTAL $32.00\nVisa ****1234"
    )
    assert facts.alcohol_amount == 8.0


def test_image_uploads_degrade_to_review_without_model(monkeypatch):
    monkeypatch.setattr(
        extraction, "settings", replace(extraction.settings, openai_api_key=None)
    )
    for filename, content_type in (("receipt.jpg", "image/jpeg"), ("receipt.png", "image/png")):
        text, facts = extract_receipt(filename, content_type, b"image-placeholder")
        assert text == ""
        assert facts.confidence == 0.0
        assert facts.missing_fields == ["openai_api_key"]


def test_model_error_is_not_exposed_in_review_output(monkeypatch):
    def fail_model(*_args, **_kwargs):
        raise RuntimeError("provider response with internal details")

    monkeypatch.setattr(extraction, "_extract_with_openai", fail_model)
    _text, facts = extract_receipt("receipt.png", "image/png", b"image-placeholder")
    assert facts.missing_fields == ["model_fallback_failed"]
