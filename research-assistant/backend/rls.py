"""Row-Level Security policies — the database-side half of tenant isolation.

Application code already filters every query by user_id. These policies are the
second line: if a future query forgets its `.filter(user_id == ...)`, Postgres
returns nothing rather than another tenant's rows.

How the two roles fit together:

- DATABASE_URL is the owner role. It runs migrations, and it runs the Stripe
  webhook path in billing.py, which has no user JWT and must read across
  tenants to resolve a customer id. RLS is enabled but NOT forced, so the
  owner keeps bypassing it — that is deliberate, not an oversight.
- APP_DATABASE_URL is the runtime role. Every request-serving query goes
  through it, it does not own the tables, and it has no BYPASSRLS, so the
  policies below actually apply to it.

That distinction is the whole mechanism. If both URLs point at the same role,
every policy here is inert — so `apply_rls_policies` says so loudly rather than
leaving a reassuring log line that means nothing.

The tenant key is the `app.current_user_id` session variable, set by
db.tenant_session() on checkout. `current_setting(..., true)` returns NULL when
it was never set, and `user_id = NULL` is NULL, not true — so an unscoped
session sees zero rows. Failing closed is the point.
"""

import logging
from urllib.parse import urlsplit

from sqlalchemy import text

from config import get_settings
from db import engine

logger = logging.getLogger(__name__)
settings = get_settings()

TENANT_GUC = "app.current_user_id"

# Tables carrying user_id directly.
_DIRECT_TABLES = (
    "research_sessions",
    "rag_documents",
    "rag_conversations",
    "user_subscriptions",
    "research_jobs",
    # Carries user_id itself rather than deriving it from research_jobs: the
    # WebSocket polls this table several times a second per open run, and a
    # subquery per row on every poll is cost for no extra safety.
    "research_events",
)

# Tables that reach their owner through a parent row. Chunks and messages have
# no user_id of their own; deriving it from the parent keeps one source of
# truth for who owns what, instead of a denormalised column that can drift.
_DERIVED_TABLES = {
    "rag_chunks": ("document_id", "rag_documents", "id"),
    "rag_messages": ("conversation_id", "rag_conversations", "id"),
}


def _role_from_url(url: str) -> str | None:
    """The Postgres role a URL logs in as.

    Supabase's connection pooler takes the user as `<role>.<project-ref>` and
    strips the suffix itself, so the role is the part before the dot. Role
    names here never contain a dot, so this is a no-op for direct connections.
    """
    try:
        username = urlsplit(url).username
    except Exception:
        return None
    return username.split(".", 1)[0] if username else None


def _direct_predicate() -> str:
    return f"user_id = current_setting('{TENANT_GUC}', true)"


def _derived_predicate(table: str, fk: str, parent: str, parent_key: str) -> str:
    return (
        f"EXISTS (SELECT 1 FROM {parent} p "
        f"WHERE p.{parent_key} = {table}.{fk} "
        f"AND p.user_id = current_setting('{TENANT_GUC}', true))"
    )


def apply_rls_policies() -> None:
    """Enable RLS and (re)create one tenant policy per table. Idempotent."""
    app_role = _role_from_url(settings.app_database_url)
    owner_role = _role_from_url(settings.database_url)

    with engine.begin() as conn:
        if conn.dialect.name != "postgresql":
            logger.info("[RLS] Skipped — not a PostgreSQL connection")
            return

        for table in (*_DIRECT_TABLES, *_DERIVED_TABLES):
            if table in _DERIVED_TABLES:
                fk, parent, parent_key = _DERIVED_TABLES[table]
                predicate = _derived_predicate(table, fk, parent, parent_key)
            else:
                predicate = _direct_predicate()

            policy = f"{table}_tenant_isolation"

            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            # Dropped and recreated rather than guarded with IF NOT EXISTS
            # (which policies don't support) so an edited predicate actually
            # takes effect on redeploy instead of silently keeping the old one.
            conn.execute(text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
            conn.execute(text(
                f"CREATE POLICY {policy} ON {table} "
                f"FOR ALL USING ({predicate}) WITH CHECK ({predicate})"
            ))

            # The runtime role owns nothing, so it needs table privileges
            # granted explicitly. RLS narrows what these reach; it does not
            # grant anything on its own.
            if app_role and app_role != owner_role:
                conn.execute(text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {app_role}"
                ))

    if not app_role or app_role == owner_role:
        logger.warning(
            "[RLS] Policies are installed but INERT: APP_DATABASE_URL uses role %r, "
            "which owns these tables and therefore bypasses row-level security. "
            "Point APP_DATABASE_URL at a separate low-privilege role (see SETUP.md) "
            "for the policies to have any effect.",
            app_role or "<none>",
        )
    else:
        logger.info(
            "[RLS] Tenant isolation active on %d tables for role %r",
            len(_DIRECT_TABLES) + len(_DERIVED_TABLES), app_role,
        )
