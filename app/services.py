from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.extraction import extract_receipt
from app.models import Employee, PolicyQuestion, Receipt, Submission
from app.policy import retrieval_is_supported, retrieve_chunks, seed_policy_chunks
from app.public_demo import PUBLIC_EMPLOYEES, PUBLIC_SUBMISSIONS
from app.rules import review_submission
from app.schemas import Citation, PolicyAnswer


def seed_employees(db: Session, submissions_dir: Path | None = None) -> None:
    submissions_dir = submissions_dir or BASE_DIR / "submissions"
    employee_infos = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(submissions_dir.glob("*/employee_info.json"))
    ]
    if not employee_infos:
        employee_infos = PUBLIC_EMPLOYEES
    for info in employee_infos:
        employee = db.scalar(select(Employee).where(Employee.employee_id == info["employee_id"]))
        if employee:
            continue
        db.add(
            Employee(
                employee_id=info["employee_id"],
                name=info["name"],
                grade=info["grade"],
                title=info["title"],
                department=info["department"],
                manager_id=info["manager_id"],
                home_base=info["home_base"],
            )
        )
    db.commit()


def add_receipt(
    db: Session,
    submission: Submission,
    filename: str,
    content_type: str,
    content: bytes,
) -> Receipt:
    extracted_text, facts = extract_receipt(filename, content_type, content)
    receipt = Receipt(
        submission=submission,
        filename=filename,
        content_type=content_type,
        file_bytes=content,
        extracted_text=extracted_text,
        facts_json=facts.model_dump_json(),
        category=facts.category,
        amount=facts.total,
        currency=facts.currency,
        confidence=facts.confidence,
    )
    db.add(receipt)
    return receipt


def create_submission(
    db: Session,
    employee: Employee,
    trip_purpose: str,
    trip_dates: str,
    files: list[tuple[str, str, bytes]],
    source_label: str | None = None,
) -> Submission:
    submission = Submission(
        employee=employee,
        trip_purpose=trip_purpose.strip(),
        trip_dates=trip_dates.strip(),
        source_label=source_label,
    )
    db.add(submission)
    db.flush()
    for filename, content_type, content in files:
        add_receipt(db, submission, filename, content_type, content)
    db.commit()
    db.refresh(submission)
    review_submission(db, submission)
    return submission


def seed_demo_submissions(db: Session, submissions_dir: Path | None = None) -> None:
    if not settings.seed_demo_submissions:
        return
    submissions_dir = submissions_dir or BASE_DIR / "submissions"
    folders = sorted(path for path in submissions_dir.iterdir() if path.is_dir()) if submissions_dir.exists() else []
    for folder in folders:
        source_label = folder.name
        if db.scalar(select(Submission).where(Submission.source_label == source_label)):
            continue
        info = json.loads((folder / "employee_info.json").read_text(encoding="utf-8"))
        employee = db.scalar(select(Employee).where(Employee.employee_id == info["employee_id"]))
        if not employee:
            continue
        files = []
        for path in sorted((folder / "receipts").iterdir()):
            files.append((path.name, "application/pdf", path.read_bytes()))
        create_submission(
            db,
            employee,
            info["trip_purpose"],
            info["trip_dates"],
            files,
            source_label=source_label,
        )
    if not folders:
        for demo in PUBLIC_SUBMISSIONS:
            if db.scalar(select(Submission).where(Submission.source_label == demo["source_label"])):
                continue
            employee = db.scalar(select(Employee).where(Employee.employee_id == demo["employee_id"]))
            files = [(name, "text/plain", text.encode("utf-8")) for name, text in demo["receipts"]]
            create_submission(
                db,
                employee,
                demo["trip_purpose"],
                demo["trip_dates"],
                files,
                source_label=demo["source_label"],
            )


def initialize_database(db: Session) -> None:
    seed_policy_chunks(db)
    seed_employees(db)
    seed_demo_submissions(db)


def answer_policy_question(db: Session, question: str) -> PolicyAnswer:
    matches = retrieve_chunks(db, question, limit=4)
    if not retrieval_is_supported(question, matches):
        answer = PolicyAnswer(
            answer=(
                "I could not find sufficiently relevant support in the Northwind policy library. "
                "Please ask about a documented company policy or route the question to a human reviewer."
            ),
            refused=True,
        )
    else:
        selected = matches[:3]
        citations = [
            Citation(document_id=chunk.document_id, section=chunk.section, quote=chunk.text)
            for chunk, _score in selected
        ]
        lead = selected[0][0]
        answer = PolicyAnswer(
            answer=(
                f"The most relevant policy is {lead.document_id} section {lead.section}, "
                f'"{lead.heading}". Review the quoted clauses below; they are returned directly '
                "from the indexed policy library so a finance reviewer can verify the answer."
            ),
            refused=False,
            citations=citations,
        )
    db.add(
        PolicyQuestion(
            question=question,
            answer=answer.answer,
            refused=answer.refused,
            citations_json=json.dumps([citation.model_dump() for citation in answer.citations]),
        )
    )
    db.commit()
    return answer
