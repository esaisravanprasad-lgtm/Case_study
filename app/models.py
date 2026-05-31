from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    grade: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    department: Mapped[str] = mapped_column(String(160))
    manager_id: Mapped[str] = mapped_column(String(40))
    home_base: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    submissions: Mapped[list["Submission"]] = relationship(back_populates="employee")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    trip_purpose: Mapped[str] = mapped_column(Text)
    trip_dates: Mapped[str] = mapped_column(String(120))
    source_label: Mapped[Optional[str]] = mapped_column(String(160), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="processing", index=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    approval_route: Mapped[str] = mapped_column(String(160), default="Pending calculation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    employee: Mapped[Employee] = relationship(back_populates="submissions")
    receipts: Mapped[list["Receipt"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="Receipt.id"
    )


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    file_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    facts_json: Mapped[str] = mapped_column(Text, default="{}")
    category: Mapped[str] = mapped_column(String(60), default="unknown")
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(12), default="USD")
    verdict: Mapped[str] = mapped_column(String(40), default="needs_review", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    suggested_action: Mapped[str] = mapped_column(Text, default="")
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    submission: Mapped[Submission] = relationship(back_populates="receipts")
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="Finding.id"
    )
    overrides: Mapped[list["Override"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="Override.created_at"
    )

    @property
    def effective_verdict(self) -> str:
        return self.overrides[-1].verdict if self.overrides else self.verdict


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), index=True)
    rule_code: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    policy_document_id: Mapped[str] = mapped_column(String(40))
    policy_section: Mapped[str] = mapped_column(String(40))
    policy_quote: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    receipt: Mapped[Receipt] = relationship(back_populates="findings")


class Override(Base):
    __tablename__ = "overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), index=True)
    verdict: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(120), default="Finance reviewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    receipt: Mapped[Receipt] = relationship(back_populates="overrides")


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(40), index=True)
    document_title: Mapped[str] = mapped_column(String(255))
    section: Mapped[str] = mapped_column(String(40), index=True)
    heading: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    source_file: Mapped[str] = mapped_column(String(120))
    embedding_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PolicyQuestion(Base):
    __tablename__ = "policy_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
