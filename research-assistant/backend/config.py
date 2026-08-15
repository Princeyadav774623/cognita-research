from pydantic_settings import BaseSettings
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

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    # Groq model selection
    groq_model_fast: str = "llama-3.1-8b-instant"          # fast, for simple tasks
    groq_model_smart: str = "llama-3.3-70b-versatile"       # smart, for reasoning

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
