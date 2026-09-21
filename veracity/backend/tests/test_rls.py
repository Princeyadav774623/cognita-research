"""Row-level security, verified by making Postgres refuse — not by reading policy.

The policies existing is not the same as the policies working. Cognita
documented "real defense-in-depth" for months while zero policies existed and
both connection strings named the same role. These tests are the difference.
"""
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db


class TestTenantIsolation:
    def test_a_user_sees_their_own_media(self, db, alice, alice_media):
        from app.db.session import app_session
        from app.db.models import MediaItem
        with app_session(alice) as s:
            assert s.query(MediaItem).count() == 1

    def test_another_tenant_sees_nothing(self, db, bob, alice_media):
        """An unfiltered SELECT by the wrong tenant returns zero rows, not a
        row it then has to remember to filter out in Python."""
        from app.db.session import app_session
        from app.db.models import MediaItem
        with app_session(bob) as s:
            assert s.query(MediaItem).count() == 0

    def test_a_session_with_no_tenant_fails_closed(self, db, alice_media):
        """Unset means nothing, not everything. current_setting(..., true)
        returns NULL and NULL never equals an id, so the policy matches no rows."""
        from app.db.session import AppSession
        s = AppSession()
        try:
            assert s.execute(text("SELECT count(*) FROM media_items")).scalar() == 0
        finally:
            s.close()

    def test_writing_under_another_tenants_id_is_refused(self, db, alice, bob):
        from app.db.session import app_session
        from app.db.models import MediaItem
        with pytest.raises(Exception) as exc:
            with app_session(alice) as s:
                s.add(MediaItem(user_id=bob, source_kind="upload",
                                original_filename="not-mine.mp4"))
        assert "policy" in str(exc.value).lower()

    def test_a_chunk_is_invisible_when_its_parent_is(self, db, bob, alice_media):
        """Chunks carry no user_id. Their policy is derived from the media item,
        so there is no second column to forget and no way for the two to
        disagree about who owns the row."""
        from app.db.session import app_session
        from app.db.models import TranscriptChunk
        with app_session(bob) as s:
            assert s.query(TranscriptChunk).count() == 0

    def test_the_owner_still_sees_everything(self, db, alice_media):
        """The worker has no user context when it claims work, so the owner
        must not be constrained by the policies."""
        from app.db.session import owner_session
        from app.db.models import MediaItem
        with owner_session() as s:
            assert s.query(MediaItem).count() >= 1

    def test_verify_reports_no_problems(self, db):
        from app.db import rls
        assert rls.verify() == []
