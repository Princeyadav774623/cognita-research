import time
from unittest.mock import patch, MagicMock

import jwt
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from auth import get_current_user_id, verify_token


# =============================================
# verify_token / get_current_user_id unit tests
# =============================================

def _rsa_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_pem, public_key


class TestVerifyToken:
    @patch("auth._get_jwks_client")
    def test_verify_token_returns_claims_for_valid_token(self, mock_get_client):
        private_pem, public_key = _rsa_keypair()
        token = jwt.encode(
            {"sub": "user-123", "aud": "authenticated", "exp": int(time.time()) + 3600},
            private_pem,
            algorithm="RS256",
        )
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = MagicMock(key=public_key)
        mock_get_client.return_value = mock_client

        claims = verify_token(token)
        assert claims["sub"] == "user-123"

    @patch("auth._get_jwks_client")
    def test_verify_token_rejects_expired_token(self, mock_get_client):
        private_pem, public_key = _rsa_keypair()
        token = jwt.encode(
            {"sub": "user-123", "aud": "authenticated", "exp": int(time.time()) - 10},
            private_pem,
            algorithm="RS256",
        )
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = MagicMock(key=public_key)
        mock_get_client.return_value = mock_client

        with pytest.raises(jwt.ExpiredSignatureError):
            verify_token(token)

    @patch("auth._get_jwks_client")
    def test_verify_token_rejects_wrong_audience(self, mock_get_client):
        private_pem, public_key = _rsa_keypair()
        token = jwt.encode(
            {"sub": "user-123", "aud": "some-other-audience", "exp": int(time.time()) + 3600},
            private_pem,
            algorithm="RS256",
        )
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = MagicMock(key=public_key)
        mock_get_client.return_value = mock_client

        with pytest.raises(jwt.InvalidAudienceError):
            verify_token(token)


# =============================================
# get_current_user_id dependency, exercised via a real FastAPI app
# =============================================

def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    def protected(user_id: str = Depends(get_current_user_id)):
        return {"user_id": user_id}

    return app


class TestGetCurrentUserId:
    def test_rejects_missing_authorization_header(self):
        client = TestClient(_build_test_app())
        res = client.get("/protected")
        assert res.status_code == 401

    def test_rejects_malformed_authorization_header(self):
        client = TestClient(_build_test_app())
        res = client.get("/protected", headers={"Authorization": "NotBearer abc"})
        assert res.status_code == 401

    @patch("auth.verify_token")
    def test_accepts_valid_bearer_token(self, mock_verify):
        mock_verify.return_value = {"sub": "user-abc"}
        client = TestClient(_build_test_app())
        res = client.get("/protected", headers={"Authorization": "Bearer valid-token"})
        assert res.status_code == 200
        assert res.json()["user_id"] == "user-abc"

    @patch("auth.verify_token")
    def test_rejects_invalid_token(self, mock_verify):
        mock_verify.side_effect = jwt.InvalidTokenError("bad token")
        client = TestClient(_build_test_app())
        res = client.get("/protected", headers={"Authorization": "Bearer garbage"})
        assert res.status_code == 401

    @patch("auth.verify_token")
    def test_rejects_expired_token(self, mock_verify):
        mock_verify.side_effect = jwt.ExpiredSignatureError()
        client = TestClient(_build_test_app())
        res = client.get("/protected", headers={"Authorization": "Bearer expired"})
        assert res.status_code == 401
        assert "expired" in res.json()["detail"].lower()
