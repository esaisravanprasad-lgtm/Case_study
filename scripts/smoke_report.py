from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Base, SessionLocal, engine
from app.models import Submission
from app.policy import citation_is_faithful
from app.services import initialize_database


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        initialize_database(db)
        for submission in db.scalars(select(Submission).order_by(Submission.id)).all():
            print(f"{submission.source_label}: {submission.status} (${submission.total_amount:.2f})")
            for receipt in submission.receipts:
                if receipt.verdict == "compliant":
                    continue
                print(f"  {receipt.filename}: {receipt.verdict}")
                for finding in receipt.findings:
                    faithful = citation_is_faithful(
                        db, finding.policy_document_id, finding.policy_quote
                    )
                    print(f"    {finding.rule_code} -> {finding.policy_document_id} §{finding.policy_section} faithful={faithful}")


if __name__ == "__main__":
    main()
