from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import BASE_DIR
from app.db import Base, SessionLocal, engine, get_db
from app.models import Employee, Override, Receipt, Submission
from app.policy import citation_is_faithful
from app.rules import review_submission
from app.schemas import EvalReceiptRequest
from app.services import answer_policy_question, create_submission, initialize_database


def _safe_download_name(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "receipt"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        initialize_database(db)
    yield


app = FastAPI(title="Northwind Expense Pre-Review", version="1.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


def _submission_query():
    return select(Submission).options(
        selectinload(Submission.employee),
        selectinload(Submission.receipts).selectinload(Receipt.findings),
        selectinload(Submission.receipts).selectinload(Receipt.overrides),
    )


def _get_submission(db: Session, submission_id: int) -> Submission:
    submission = db.scalar(_submission_query().where(Submission.id == submission_id))
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    return submission


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    submissions = list(
        db.scalars(_submission_query().order_by(Submission.created_at.desc()).limit(12)).all()
    )
    counts = dict(db.execute(select(Submission.status, func.count()).group_by(Submission.status)).all())
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"submissions": submissions, "counts": counts, "title": "Dashboard"},
    )


@app.get("/submissions/new", response_class=HTMLResponse)
def new_submission(request: Request, db: Session = Depends(get_db)):
    employees = list(db.scalars(select(Employee).order_by(Employee.name)).all())
    return templates.TemplateResponse(
        request, "new_submission.html", {"employees": employees, "title": "New submission"}
    )


@app.post("/submissions")
async def submit_expenses(
    employee_pk: str = Form(""),
    employee_id: str = Form(""),
    name: str = Form(""),
    grade: int = Form(1),
    title: str = Form(""),
    department: str = Form(""),
    manager_id: str = Form(""),
    home_base: str = Form(""),
    trip_purpose: str = Form(...),
    trip_dates: str = Form(...),
    receipts: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, int(employee_pk)) if employee_pk else None
    if not employee:
        if not all([employee_id, name, title, department, manager_id, home_base]):
            raise HTTPException(status_code=400, detail="Complete the new employee fields.")
        employee = Employee(
            employee_id=employee_id.strip(),
            name=name.strip(),
            grade=grade,
            title=title.strip(),
            department=department.strip(),
            manager_id=manager_id.strip(),
            home_base=home_base.strip(),
        )
        db.add(employee)
        db.commit()
        db.refresh(employee)
    files = []
    for upload in receipts:
        files.append((upload.filename or "receipt", upload.content_type or "application/octet-stream", await upload.read()))
    try:
        submission = create_submission(db, employee, trip_purpose, trip_dates, files)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/submissions/{submission.id}", status_code=303)


@app.get("/submissions/{submission_id}", response_class=HTMLResponse)
def submission_detail(submission_id: int, request: Request, db: Session = Depends(get_db)):
    submission = _get_submission(db, submission_id)
    return templates.TemplateResponse(
        request, "submission.html", {"submission": submission, "title": f"Submission #{submission.id}"}
    )


@app.post("/receipts/{receipt_id}/override")
def override_receipt(
    receipt_id: int,
    verdict: str = Form(...),
    comment: str = Form(...),
    reviewer: str = Form("Finance reviewer"),
    db: Session = Depends(get_db),
):
    if verdict not in {"compliant", "flagged", "needs_review"}:
        raise HTTPException(status_code=400, detail="Invalid verdict")
    if not comment.strip():
        raise HTTPException(status_code=400, detail="Override comment is required")
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    db.add(Override(receipt=receipt, verdict=verdict, comment=comment.strip(), reviewer=reviewer.strip()))
    db.commit()
    review_submission(db, receipt.submission)
    return RedirectResponse(f"/submissions/{receipt.submission_id}#receipt-{receipt.id}", status_code=303)


@app.get("/receipts/{receipt_id}/download")
def download_receipt(receipt_id: int, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return Response(
        content=receipt.file_bytes,
        media_type=receipt.content_type,
        headers={"Content-Disposition": f'inline; filename="{_safe_download_name(receipt.filename)}"'},
    )


@app.get("/history", response_class=HTMLResponse)
def history(
    request: Request,
    employee: str = "",
    status: str = "",
    trip_date: str = "",
    db: Session = Depends(get_db),
):
    query = _submission_query().order_by(Submission.created_at.desc())
    if employee:
        query = query.join(Employee).where(Employee.name.ilike(f"%{employee}%"))
    if status:
        query = query.where(Submission.status == status)
    if trip_date:
        query = query.where(Submission.trip_dates.ilike(f"%{trip_date}%"))
    submissions = list(db.scalars(query).all())
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "submissions": submissions,
            "filters": {"employee": employee, "status": status, "trip_date": trip_date},
            "title": "Submission history",
        },
    )


@app.get("/policy-assistant", response_class=HTMLResponse)
def policy_assistant(request: Request):
    return templates.TemplateResponse(
        request, "policy_assistant.html", {"answer": None, "question": "", "title": "Policy assistant"}
    )


@app.post("/policy-assistant", response_class=HTMLResponse)
def ask_policy(request: Request, question: str = Form(...), db: Session = Depends(get_db)):
    answer = answer_policy_question(db, question)
    return templates.TemplateResponse(
        request,
        "policy_assistant.html",
        {"answer": answer, "question": question, "title": "Policy assistant"},
    )


@app.post("/api/policy/ask")
def ask_policy_api(payload: dict, db: Session = Depends(get_db)):
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    return answer_policy_question(db, question)


@app.post("/api/evaluate/receipt")
def evaluate_receipt(payload: EvalReceiptRequest, db: Session = Depends(get_db)):
    from app.extraction import extract_receipt
    from app.models import Receipt

    text, facts = extract_receipt(payload.filename, payload.content_type, payload.text.encode("utf-8"))
    receipt = Receipt(
        filename=payload.filename,
        content_type=payload.content_type,
        file_bytes=payload.text.encode("utf-8"),
        extracted_text=text,
        facts_json=facts.model_dump_json(),
    )
    submission = Submission(
        employee_id=0,
        trip_purpose=payload.trip_purpose,
        trip_dates=payload.trip_dates,
        receipts=[receipt],
    )
    review_submission(db, submission)
    return {
        "facts": facts.model_dump(),
        "verdict": receipt.verdict,
        "category": receipt.category,
        "findings": [
            {
                "rule_code": finding.rule_code,
                "severity": finding.severity,
                "document_id": finding.policy_document_id,
                "section": finding.policy_section,
                "quote": finding.policy_quote,
                "citation_faithful": citation_is_faithful(
                    db, finding.policy_document_id, finding.policy_quote
                ),
            }
            for finding in receipt.findings
        ],
    }
