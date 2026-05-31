from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'northwind.db'}"
    )
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.4-mini-2026-03-17")
    embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    enable_embeddings: bool = os.getenv("ENABLE_EMBEDDINGS", "false").lower() == "true"
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
    seed_samples: bool = os.getenv("SEED_SAMPLES", "true").lower() == "true"
    seed_demo_submissions: bool = os.getenv("SEED_DEMO_SUBMISSIONS", "true").lower() == "true"


settings = Settings()
