from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from openai import OpenAI
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.models import PolicyChunk
from app.public_demo import PUBLIC_POLICY_SECTIONS


WORD_RE = re.compile(r"[a-z0-9]+")
DOCUMENT_RE = re.compile(r"(?m)^Document:\s+([A-Z]+(?:-[A-Z]+)?-\d+)\b")
SECTION_RE = re.compile(r"(?m)^(\d+(?:\.\d+)*)\.?\s+([^\n]+)$")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "company",
    "days",
    "do",
    "does",
    "employees",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "leave",
    "may",
    "my",
    "of",
    "on",
    "or",
    "policy",
    "receive",
    "the",
    "to",
    "travel",
    "what",
    "when",
    "with",
}


def _tokens(text: str) -> list[str]:
    return [word for word in WORD_RE.findall(text.lower()) if word not in STOPWORDS]


def _read_pdf(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _document_ranges(text: str) -> list[tuple[str, str, str]]:
    matches = list(DOCUMENT_RE.finditer(text))
    documents: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        previous_lines = text[:start].rstrip().splitlines()
        title = previous_lines[-1].strip() if previous_lines else match.group(1)
        documents.append((match.group(1), title, text[start:end].strip()))
    return documents


def _section_chunks(document_id: str, title: str, text: str, source_file: str) -> list[PolicyChunk]:
    matches = list(SECTION_RE.finditer(text))
    chunks: list[PolicyChunk] = []
    if not matches:
        return [
            PolicyChunk(
                document_id=document_id,
                document_title=title,
                section="0",
                heading=title,
                text=text,
                source_file=source_file,
            )
        ]
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunks.append(
            PolicyChunk(
                document_id=document_id,
                document_title=title,
                section=match.group(1),
                heading=match.group(2).strip(),
                text=text[start:end].strip(),
                source_file=source_file,
            )
        )
    return chunks


def seed_policy_chunks(db: Session, policy_dir: Path | None = None) -> None:
    if db.scalar(select(PolicyChunk.id).limit(1)):
        return
    policy_dir = policy_dir or BASE_DIR / "policies"
    pdf_paths = sorted(policy_dir.glob("*.pdf"))
    for pdf_path in pdf_paths:
        full_text = _read_pdf(pdf_path)
        for document_id, title, document_text in _document_ranges(full_text):
            db.add_all(_section_chunks(document_id, title, document_text, pdf_path.name))
    if not pdf_paths:
        for document_id, title, section, heading, text in PUBLIC_POLICY_SECTIONS:
            db.add(
                PolicyChunk(
                    document_id=document_id,
                    document_title=title,
                    section=section,
                    heading=heading,
                    text=text,
                    source_file="synthetic-public-demo",
                )
            )
    db.commit()
    embed_missing_chunks(db)


def embed_missing_chunks(db: Session) -> None:
    if not settings.openai_api_key or not settings.enable_embeddings:
        return
    chunks = list(
        db.scalars(select(PolicyChunk).where(PolicyChunk.embedding_json.is_(None))).all()
    )
    if not chunks:
        return
    client = OpenAI(api_key=settings.openai_api_key)
    batch_size = 64
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        try:
            response = client.embeddings.create(
                model=settings.embedding_model,
                input=[
                    f"{chunk.document_id} {chunk.section} {chunk.heading}\n{chunk.text}"
                    for chunk in batch
                ],
            )
        except Exception:
            # Lexical retrieval remains available if embedding initialization is unavailable.
            return
        for chunk, result in zip(batch, response.data):
            chunk.embedding_json = json.dumps(result.embedding)
        db.commit()


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _query_embedding(query: str) -> list[float] | None:
    if not settings.openai_api_key or not settings.enable_embeddings:
        return None
    try:
        response = OpenAI(api_key=settings.openai_api_key).embeddings.create(
            model=settings.embedding_model, input=query
        )
        return response.data[0].embedding
    except Exception:
        return None


def retrieve_chunks(db: Session, query: str, limit: int = 5) -> list[tuple[PolicyChunk, float]]:
    query_tokens = Counter(_tokens(query))
    query_vector = _query_embedding(query)
    document_mentions = {value.upper() for value in re.findall(r"[A-Za-z]+-\d+", query)}
    scored: list[tuple[PolicyChunk, float]] = []
    for chunk in db.scalars(select(PolicyChunk)).all():
        chunk_tokens = Counter(_tokens(f"{chunk.document_title} {chunk.heading} {chunk.text}"))
        overlap = sum(min(count, chunk_tokens[token]) for token, count in query_tokens.items())
        lexical = overlap / max(1, len(query_tokens))
        phrase_boost = 0.12 if query.lower() in chunk.text.lower() else 0.0
        document_boost = 0.3 if chunk.document_id in document_mentions else 0.0
        vector_score = 0.0
        if query_vector and chunk.embedding_json:
            vector_score = max(0.0, _cosine(query_vector, json.loads(chunk.embedding_json)))
        score = lexical * 0.72 + vector_score * 0.28 + phrase_boost + document_boost
        if score > 0:
            scored.append((chunk, score))
    return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]


def retrieval_is_supported(query: str, matches: list[tuple[PolicyChunk, float]]) -> bool:
    if not matches or matches[0][1] < 0.14:
        return False
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False
    evidence_tokens: set[str] = set()
    for chunk, _score in matches[:3]:
        evidence_tokens.update(_tokens(f"{chunk.document_title} {chunk.heading} {chunk.text}"))
    return len(query_tokens & evidence_tokens) / len(query_tokens) >= 0.6


def get_chunk(db: Session, document_id: str, section: str) -> PolicyChunk | None:
    return db.scalar(
        select(PolicyChunk).where(
            PolicyChunk.document_id == document_id, PolicyChunk.section == section
        )
    )


def exact_quote(db: Session, document_id: str, section: str, contains: str | None = None) -> str:
    chunk = get_chunk(db, document_id, section)
    if not chunk:
        return f"{document_id} section {section} was not indexed."
    if not contains:
        return chunk.text
    sentences = re.split(r"(?<=[.!?])\s+", chunk.text)
    for sentence in sentences:
        if contains.lower() in sentence.lower():
            return sentence.strip()
    return chunk.text


def citation_is_faithful(db: Session, document_id: str, quote: str) -> bool:
    return any(
        quote in chunk.text
        for chunk in db.scalars(
            select(PolicyChunk).where(PolicyChunk.document_id == document_id)
        ).all()
    )
