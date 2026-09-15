"""Assert that Postgres itself refuses cross-tenant reads.

Runs in CI against a real database. The policies existing is not the same as
the policies working: if APP_DATABASE_URL ever points back at the owner role,
every policy is silently inert and application-layer filtering is all that
stands between tenants. This fails the build in that case.
"""
import sys

from sqlalchemy import text

from db import AppSessionLocal, init_db, save_session, tenant_session
from billing import init_billing_db
from rag.store import init_rag_db
from rls import apply_rls_policies

OWNER, INTRUDER = "rls-owner", "rls-intruder"
failures = []


def check(label: str, condition: bool) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)


def main() -> int:
    init_db(); init_billing_db(); init_rag_db(); apply_rls_policies()

    save_session("rls-probe-1", OWNER, "owned query", {"final_report": "r", "source_documents": []})

    with tenant_session(OWNER) as db:
        mine = db.execute(text("SELECT count(*) FROM research_sessions")).scalar()
    check("owner sees their own row", mine == 1)

    # The case that matters: a query that forgot its user_id filter.
    with tenant_session(INTRUDER) as db:
        leaked = db.execute(text("SELECT count(*) FROM research_sessions")).scalar()
    check("unfiltered read by another tenant returns nothing", leaked == 0)

    db = AppSessionLocal()
    try:
        unscoped = db.execute(text("SELECT count(*) FROM research_sessions")).scalar()
    finally:
        db.close()
    check("session with no tenant set fails closed", unscoped == 0)

    with tenant_session(INTRUDER) as db:
        try:
            db.execute(text(
                "INSERT INTO research_sessions (id, user_id, query) "
                "VALUES ('rls-forged', :owner, 'forged')"), {"owner": OWNER})
            db.commit()
            refused = False
        except Exception:
            db.rollback()
            refused = True
    check("writing a row under another tenant's id is refused", refused)

    if failures:
        print(f"\n{len(failures)} RLS check(s) failed — tenant isolation is not enforced.")
        return 1
    print("\nAll RLS checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
