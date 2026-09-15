from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Groq
    groq_api_key: str

    # Tavily
    tavily_api_key: str

    # Cohere (optional — used for rerank, falls back gracefully if unset)
    cohere_api_key: str = ""

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "research-assistant"

    # Database
    database_url: str = ""

    # Low-privilege connection (no BYPASSRLS) used for all runtime queries,
    # so Postgres Row-Level Security actually applies as defense-in-depth on
    # top of application-layer tenant filtering. database_url (the owner
    # role) is used only for schema migrations at startup.
    app_database_url: str = ""

    # Auth — Supabase project URL, used to fetch its public JWKS for
    # verifying user JWTs. No secret needed (JWKS keys are public).
    supabase_url: str = ""

    # App
    env: str = "development"
    port: int = 8000
    cors_origins_raw: str = "http://localhost:3000"

    # Number of proxies in front of this app (nginx, Render, Fly = usually 1).
    # 0 means direct connections and X-Forwarded-For is ignored as untrusted.
    trusted_proxy_count: int = 0

    # Where rate-limit counters live. Empty = in-process memory, which is
    # correct for one instance and wrong for two: each process keeps its own
    # tally, so N instances multiply every published limit by N. Set to a
    # redis:// URL before scaling past one.
    rate_limit_storage_uri: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    # Billing — Stripe. Both empty by default; when unset the billing
    # endpoints stay in demo mode rather than failing at import time.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""

    # Groq model selection.
    # These must stay different. Pointing both at the 120B model means the
    # planner, query-rephrase and gap-analysis nodes — which only emit small
    # structured JSON — burn the same scarce tokens-per-minute budget as the
    # analyst and report nodes that actually need the reasoning. On a
    # rate-limited account that budget is the binding constraint on latency.
    groq_model_fast: str = "openai/gpt-oss-20b"    # structural JSON tasks
    groq_model_smart: str = "openai/gpt-oss-120b"  # synthesis and verification

    # Per-million-token rates used to turn measured token counts into a cost
    # estimate. The token counts themselves are exact; these are not — they are
    # settings rather than constants precisely so they can be corrected against
    # current Groq pricing without a code change. Verify before quoting the
    # resulting figure to anyone.
    price_smart_input_per_mtok: float = 0.15
    price_smart_output_per_mtok: float = 0.75
    price_fast_input_per_mtok: float = 0.10
    price_fast_output_per_mtok: float = 0.50

    # env_file is resolved relative to the process's working directory, which
    # is backend/ for both `uvicorn api.main:app` and `pytest` as documented
    # in SETUP.md.
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
