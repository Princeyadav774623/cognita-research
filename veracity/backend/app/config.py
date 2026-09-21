"""Configuration, read once from the environment.

Everything with a sensible default has one. The three that do not — the database
URL, the runtime role's URL, and the inference key — fail loudly at import
rather than at the first request, because a service that starts and then 500s on
every call is harder to diagnose than one that refuses to start.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _req(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return v


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    # ---- database -------------------------------------------------------
    # Two URLs on purpose. The owner runs migrations and anything with no user
    # context; the app role owns nothing and cannot bypass row-level security,
    # so the policies actually bind to it. Pointing both at the same role makes
    # every policy inert, which startup checks for and refuses.
    database_url: str = field(default_factory=lambda: _req("DATABASE_URL"))
    database_url_app: str = field(default_factory=lambda: _req("DATABASE_URL_APP"))

    # ---- inference ------------------------------------------------------
    groq_api_key: str = field(default_factory=lambda: _req("GROQ_API_KEY"))
    # Pinned, not resolved from a provider default: the account this runs on
    # does not expose every published family, and a fallback chain that assumes
    # otherwise fails at runtime on a machine where it was never tested.
    model_fast: str = os.getenv("MODEL_FAST", "openai/gpt-oss-20b")
    model_smart: str = os.getenv("MODEL_SMART", "openai/gpt-oss-120b")

    # ---- transcription --------------------------------------------------
    # "groq" needs no local model and no GPU. "faster-whisper" runs offline and
    # is the fallback when audio must not leave the deployment.
    asr_backend: str = os.getenv("ASR_BACKEND", "groq")
    asr_model: str = os.getenv("ASR_MODEL", "whisper-large-v3-turbo")
    asr_local_model: str = os.getenv("ASR_LOCAL_MODEL", "base.en")
    # Groq rejects uploads over 25 MB. 16 kHz mono FLAC is ~32 kB/s, so ~13
    # minutes per part; 10 keeps headroom for a variable-bitrate overshoot.
    asr_segment_seconds: int = _int("ASR_SEGMENT_SECONDS", 600)
    asr_max_upload_bytes: int = _int("ASR_MAX_UPLOAD_BYTES", 24 * 1024 * 1024)

    # A word the transcriber is unsure of must not become a fact-checked claim.
    # Below this, the span is reported as unclear instead.
    asr_min_word_confidence: float = _float("ASR_MIN_WORD_CONFIDENCE", 0.55)
    asr_min_claim_confidence: float = _float("ASR_MIN_CLAIM_CONFIDENCE", 0.70)

    # ---- media ----------------------------------------------------------
    media_root: str = os.getenv("MEDIA_ROOT", "/tmp/veracity-media")
    max_upload_bytes: int = _int("MAX_UPLOAD_BYTES", 2 * 1024 * 1024 * 1024)
    max_duration_seconds: int = _int("MAX_DURATION_SECONDS", 4 * 60 * 60)
    # Fetching from a third-party host is off unless switched on deliberately:
    # it is the feature most likely to breach a site's terms of service.
    allow_remote_fetch: bool = os.getenv("ALLOW_REMOTE_FETCH", "false").lower() == "true"

    # ---- chunking -------------------------------------------------------
    chunk_target_chars: int = _int("CHUNK_TARGET_CHARS", 1000)
    chunk_overlap_chars: int = _int("CHUNK_OVERLAP_CHARS", 150)
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    embedding_dim: int = _int("EMBEDDING_DIM", 384)

    # ---- jobs -----------------------------------------------------------
    job_lease_seconds: int = _int("JOB_LEASE_SECONDS", 900)
    job_max_attempts: int = _int("JOB_MAX_ATTEMPTS", 3)
    worker_poll_seconds: float = _float("WORKER_POLL_SECONDS", 2.0)

    # ---- auth -----------------------------------------------------------
    supabase_jwks_url: str = os.getenv("SUPABASE_JWKS_URL", "")
    # An alternative to JWKS for deployments with no Supabase. Symmetric, so
    # anything that can read this environment can mint a token for any user;
    # prefer the asymmetric path in production.
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    supabase_audience: str = os.getenv("SUPABASE_AUDIENCE", "authenticated")
    allow_guest: bool = os.getenv("ALLOW_GUEST", "false").lower() == "true"


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
