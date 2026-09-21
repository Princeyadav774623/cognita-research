"""Install row-level security, and refuse to pretend when it cannot work.

Two kinds of table. Some carry `user_id` and are filtered on it directly. The
rest carry only a parent reference, and their policy is derived from the
parent's — a chunk is visible exactly when its media item is. That is one fewer
column to forget on insert, and it removes any way for a row and its parent to
disagree about who owns them.

`jobs` is deliberately not policied. The worker has no user context when it
claims work; it runs as the owner and scopes itself per job.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.session import TENANT_GUC, owner_engine
from app.config import settings

log = logging.getLogger("rls")

# table -> its own user column
_DIRECT = ("media_items", "analyses")

# table -> (its fk column, parent table, parent key)
_DERIVED = {
    "transcript_segments": ("media_id", "media_items", "id"),
    "transcript_chunks": ("media_id", "media_items", "id"),
    "claims": ("analysis_id", "analyses", "id"),
}


def _app_role() -> str:
    from sqlalchemy.engine.url import make_url
    return make_url(settings().database_url_app).username or ""


def _owner_role() -> str:
    from sqlalchemy.engine.url import make_url
    return make_url(settings().database_url).username or ""


def install() -> None:
    app_role, owner_role = _app_role(), _owner_role()

    if app_role and app_role == owner_role:
        # Loudly, because the alternative is a reassuring line in the log and no
        # isolation at all. Cognita shipped exactly this for months.
        log.error(
            "[RLS] DATABASE_URL and DATABASE_URL_APP both use role %r. "
            "Policies will be installed and will have NO EFFECT, because the "
            "owner bypasses them. Create a low-privilege role.", app_role,
        )

    with owner_engine.begin() as conn:
        for table in _DIRECT:
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"DROP POLICY IF EXISTS {table}_tenant ON {table}"))
            # current_setting(..., true) returns NULL when unset, and NULL never
            # equals anything, so an unscoped session matches zero rows.
            conn.execute(text(
                f"CREATE POLICY {table}_tenant ON {table} "
                f"USING (user_id = current_setting('{TENANT_GUC}', true)) "
                f"WITH CHECK (user_id = current_setting('{TENANT_GUC}', true))"
            ))

        for table, (fk, parent, pk) in _DERIVED.items():
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"DROP POLICY IF EXISTS {table}_tenant ON {table}"))
            conn.execute(text(
                f"CREATE POLICY {table}_tenant ON {table} "
                f"USING (EXISTS (SELECT 1 FROM {parent} p "
                f"  WHERE p.{pk} = {table}.{fk})) "
                f"WITH CHECK (EXISTS (SELECT 1 FROM {parent} p "
                f"  WHERE p.{pk} = {table}.{fk}))"
            ))

        if app_role and app_role != owner_role:
            for table in (*_DIRECT, *_DERIVED, "jobs"):
                conn.execute(text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {app_role}"
                ))

    log.info("[RLS] policies installed on %d tables for role %r",
             len(_DIRECT) + len(_DERIVED), app_role or "(unset)")


def verify() -> list[str]:
    """Return a list of problems, empty when isolation is genuinely enforced.

    Checks that policies *work*, not that they exist. The two are different, and
    only the first is worth a green build.
    """
    problems: list[str] = []
    if _app_role() == _owner_role():
        problems.append(
            "DATABASE_URL and DATABASE_URL_APP use the same role, so every "
            "policy is bypassed"
        )
    with owner_engine.connect() as conn:
        for table in (*_DIRECT, *_DERIVED):
            enabled = conn.execute(text(
                "SELECT relrowsecurity FROM pg_class WHERE relname = :t"
            ), {"t": table}).scalar()
            if not enabled:
                problems.append(f"{table}: row-level security is not enabled")
    return problems
