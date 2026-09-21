"""Migrations, against a genuinely empty database.

Autogenerating a migration while the tables already exist produces an empty one
— alembic diffs against what is there, finds no difference, and writes `pass`.
That mistake is invisible until someone installs from scratch, which is the one
time it has to work.
"""
import os
import subprocess
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text

pytestmark = pytest.mark.db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED = {"media_items", "transcript_segments", "transcript_chunks",
            "analyses", "claims", "jobs"}


@pytest.fixture
def empty_database():
    """A throwaway database, dropped however the test ends."""
    admin = create_engine(
        f"postgresql://{os.environ.get('USER', 'postgres')}@localhost:5432/postgres",
        isolation_level="AUTOCOMMIT")
    name = f"veracity_mig_{uuid.uuid4().hex[:8]}"
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = f"postgresql://{os.environ.get('USER', 'postgres')}@localhost:5432/{name}"
    try:
        yield url
    finally:
        engine = create_engine(url)
        engine.dispose()
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url, "DATABASE_URL_APP": url}
    return subprocess.run(
        [os.path.join(ROOT, "venv", "bin", "alembic"), *args],
        cwd=ROOT, env=env, capture_output=True, text=True)


class TestMigrations:
    def test_upgrade_builds_the_whole_schema_from_nothing(self, empty_database):
        out = _alembic(empty_database, "upgrade", "head")
        assert out.returncode == 0, out.stderr

        tables = set(inspect(create_engine(empty_database)).get_table_names())
        missing = EXPECTED - tables
        assert not missing, f"migration did not create {missing}"

    def test_the_vector_extension_is_created_before_the_tables_need_it(
            self, empty_database):
        """A table with a vector column cannot be created before the extension
        exists, and that failure only ever happens on a first install."""
        out = _alembic(empty_database, "upgrade", "head")
        assert out.returncode == 0, out.stderr
        with create_engine(empty_database).connect() as c:
            assert c.execute(text(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
            )).scalar() == 1

    def test_downgrade_removes_what_upgrade_added(self, empty_database):
        assert _alembic(empty_database, "upgrade", "head").returncode == 0
        out = _alembic(empty_database, "downgrade", "base")
        assert out.returncode == 0, out.stderr
        tables = set(inspect(create_engine(empty_database)).get_table_names())
        assert not (EXPECTED & tables), f"downgrade left {EXPECTED & tables}"

    def test_migrations_and_the_models_agree(self, empty_database):
        """The schema alembic builds must be the schema the code declares.

        These drift silently: someone edits a model, forgets the migration, and
        every environment except a fresh install keeps working.
        """
        assert _alembic(empty_database, "upgrade", "head").returncode == 0
        engine = create_engine(empty_database)
        inspector = inspect(engine)

        import sys
        sys.path.insert(0, ROOT)
        from app.db.models import Base

        for table in Base.metadata.sorted_tables:
            declared = {c.name for c in table.columns}
            built = {c["name"] for c in inspector.get_columns(table.name)}
            assert declared == built, (
                f"{table.name}: models and migration disagree — "
                f"only in models {declared - built}, "
                f"only in migration {built - declared}"
            )
