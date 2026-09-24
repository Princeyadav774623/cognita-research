"""Token verification, tested against the forgeries that actually get used.

Most JWT vulnerabilities are the verifier's fault rather than the library's: it
trusts the algorithm named in the token's own header, or it skips the expiry, or
it accepts a token with no subject and treats the absence as a user. Each of
those has a test here because each has shipped in real products.
"""
import time

import jwt
import pytest
from fastapi import HTTPException

SECRET = "test-secret-for-symmetric-mode"
AUD = "authenticated"


@pytest.fixture(autouse=True)
def symmetric(monkeypatch):
    """Run auth in shared-secret mode so tokens can be minted in the test."""
    import dataclasses

    import app.api.auth as auth
    cfg = dataclasses.replace(auth.settings(), jwt_secret=SECRET,
                              allow_guest=False)
    monkeypatch.setattr(auth, "settings", lambda: cfg)
    return auth


def token(**overrides) -> str:
    claims = {"sub": "user-123", "email": "a@b.c", "aud": AUD,
              "exp": int(time.time()) + 3600}
    claims.update(overrides)
    return jwt.encode(claims, SECRET, algorithm="HS256")


class TestAccepts:
    def test_a_valid_token_identifies_the_user(self, symmetric):
        p = symmetric._verify(token())
        assert p.user_id == "user-123"
        assert p.email == "a@b.c"
        assert p.is_guest is False


class TestRejects:
    def test_an_expired_token(self, symmetric):
        with pytest.raises(HTTPException) as e:
            symmetric._verify(token(exp=int(time.time()) - 10))
        assert e.value.status_code == 401
        assert "expired" in e.value.detail

    def test_a_token_signed_with_the_wrong_key(self, symmetric):
        bad = jwt.encode({"sub": "x", "aud": AUD,
                          "exp": int(time.time()) + 60},
                         "not-the-secret", algorithm="HS256")
        with pytest.raises(HTTPException) as e:
            symmetric._verify(bad)
        assert e.value.status_code == 401

    def test_the_alg_none_forgery(self, symmetric):
        """The oldest JWT attack: strip the signature and set alg to none. A
        verifier that reads the algorithm out of the token accepts it."""
        forged = jwt.encode({"sub": "admin", "aud": AUD,
                             "exp": int(time.time()) + 60},
                            key="", algorithm="none")
        with pytest.raises(HTTPException) as e:
            symmetric._verify(forged)
        assert e.value.status_code == 401

    def test_a_token_with_no_subject_is_not_an_identity(self, symmetric):
        """Without this, `sub` missing yields Principal(user_id=None), which
        scopes the database session to nothing and fails open in the one place
        it must not."""
        claims = {"aud": AUD, "exp": int(time.time()) + 60}
        with pytest.raises(HTTPException) as e:
            symmetric._verify(jwt.encode(claims, SECRET, algorithm="HS256"))
        assert e.value.status_code == 401

    def test_a_token_for_another_audience(self, symmetric):
        with pytest.raises(HTTPException) as e:
            symmetric._verify(token(aud="some-other-service"))
        assert e.value.status_code == 401

    def test_the_rejection_reason_is_not_echoed_back(self, symmetric):
        """Telling a caller which part of their forged token failed tells them
        what to fix next."""
        with pytest.raises(HTTPException) as e:
            symmetric._verify(token(aud="wrong"))
        assert e.value.detail == "invalid token"


class TestGuestMode:
    def test_no_token_is_refused_when_guest_mode_is_off(self, symmetric):
        with pytest.raises(HTTPException) as e:
            symmetric.current_principal(authorization=None)
        assert e.value.status_code == 401
        assert e.value.headers["WWW-Authenticate"] == "Bearer"

    def test_guest_mode_hands_out_one_shared_identity(self, monkeypatch):
        """Worth asserting rather than assuming: in guest mode every request is
        the same tenant, so row-level security separates nothing. It is a
        development affordance and startup warns about it."""
        import dataclasses

        import app.api.auth as auth
        cfg = dataclasses.replace(auth.settings(), jwt_secret=SECRET,
                                  allow_guest=True)
        monkeypatch.setattr(auth, "settings", lambda: cfg)

        a = auth.current_principal(authorization=None)
        b = auth.current_principal(authorization=None)
        assert a.is_guest and a.user_id == b.user_id

    def test_a_bearer_token_still_wins_over_guest_mode(self, monkeypatch):
        import dataclasses

        import app.api.auth as auth
        cfg = dataclasses.replace(auth.settings(), jwt_secret=SECRET,
                                  allow_guest=True)
        monkeypatch.setattr(auth, "settings", lambda: cfg)

        p = auth.current_principal(authorization=f"Bearer {token()}")
        assert p.user_id == "user-123" and not p.is_guest
