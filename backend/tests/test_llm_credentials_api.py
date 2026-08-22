"""Tests for /v1/llm-credentials/* endpoints."""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.services.crypto.factory import reset_cipher

DB_MODULE = "src.infrastructure.postgres.database"


def _create_test_app() -> FastAPI:
    """Minimal FastAPI app with auth + credentials routers (no lifespan)."""
    from src.api.shared.exceptions import ApiException
    from src.api.shared.handlers import api_exception_handler
    from src.api.versions.v1.routers.auth import router as auth_router
    from src.api.versions.v1.routers.llm_credentials import router as cred_router

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.add_exception_handler(ApiException, api_exception_handler)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(cred_router, prefix="/api/v1")
    return app


@pytest.fixture(autouse=True)
def _set_test_cipher(monkeypatch):
    monkeypatch.setattr(
        "src.services.crypto.factory.agent_settings.CREDENTIALS_CIPHER", "fernet"
    )
    monkeypatch.setattr(
        "src.services.crypto.factory.agent_settings.CREDENTIALS_MASTER_KEY",
        Fernet.generate_key().decode("utf-8"),
    )
    reset_cipher()
    yield
    reset_cipher()


@pytest.fixture
def app():
    return _create_test_app()


@pytest.fixture
def client(app, session_factory):
    with patch(f"{DB_MODULE}.AsyncSessionLocal", new=session_factory), patch(
        "src.infrastructure.postgres.database.get_postgres_session"
    ) as mock_get_session:

        async def _get_session():
            async with session_factory() as sess:
                yield sess

        mock_get_session.side_effect = _get_session

        from src.core.dependencies import get_postgres_session

        async def _override_session():
            async with session_factory() as sess:
                yield sess

        app.dependency_overrides[get_postgres_session] = _override_session

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

        app.dependency_overrides.clear()


def _signup(client, email: str = "u@example.com") -> str:
    """Sign up and return the access token."""
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Create ---


def test_create_credential_persists_and_masks_key(client):
    token = _signup(client)
    response = client.post(
        "/api/v1/llm-credentials",
        headers=_auth(token),
        json={
            "name": "My OpenAI",
            "provider": "openai",
            "api_key": "sk-proj-1234567890abcdefghij",
            "model": "gpt-4o",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "My OpenAI"
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o"
    # Preview must not contain the full secret
    assert data["api_key_preview"].startswith("sk-pro")
    assert "1234567890abcdefghij" not in data["api_key_preview"]
    assert "..." in data["api_key_preview"]


def test_create_rejects_openai_without_key(client):
    token = _signup(client)
    response = client.post(
        "/api/v1/llm-credentials",
        headers=_auth(token),
        json={"name": "X", "provider": "openai", "model": "gpt-4o"},
    )
    assert response.status_code == 400


def test_create_allows_ollama_without_key(client):
    token = _signup(client)
    response = client.post(
        "/api/v1/llm-credentials",
        headers=_auth(token),
        json={
            "name": "Local Llama",
            "provider": "ollama",
            "model": "llama3.2",
            "base_url": "http://localhost:11434",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "ollama"
    assert data["api_key_preview"] == ""


def test_create_rejects_unknown_provider(client):
    token = _signup(client)
    response = client.post(
        "/api/v1/llm-credentials",
        headers=_auth(token),
        json={"name": "X", "provider": "cohere", "api_key": "sk-x", "model": "x"},
    )
    assert response.status_code == 422


def test_create_duplicate_name_returns_409(client):
    token = _signup(client)
    payload = {
        "name": "dup",
        "provider": "openai",
        "api_key": "sk-1234567890",
        "model": "gpt-4o",
    }
    first = client.post(
        "/api/v1/llm-credentials", headers=_auth(token), json=payload
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/llm-credentials", headers=_auth(token), json=payload
    )
    assert second.status_code == 409


# --- List / Get ---


def test_list_returns_only_own_credentials(client):
    alice_token = _signup(client, "alice@example.com")
    bob_token = _signup(client, "bob@example.com")

    client.post(
        "/api/v1/llm-credentials",
        headers=_auth(alice_token),
        json={
            "name": "alice-key",
            "provider": "openai",
            "api_key": "sk-alice-1234567890",
            "model": "gpt-4o",
        },
    )
    client.post(
        "/api/v1/llm-credentials",
        headers=_auth(bob_token),
        json={
            "name": "bob-key",
            "provider": "anthropic",
            "api_key": "sk-bob-9876543210",
            "model": "claude-haiku-4-5-20251001",
        },
    )

    alice_list = client.get("/api/v1/llm-credentials", headers=_auth(alice_token))
    assert alice_list.status_code == 200
    alice_items = alice_list.json()["data"]
    assert len(alice_items) == 1
    assert alice_items[0]["name"] == "alice-key"


def test_get_other_users_credential_returns_404(client):
    alice_token = _signup(client, "alice@example.com")
    bob_token = _signup(client, "bob@example.com")

    created = client.post(
        "/api/v1/llm-credentials",
        headers=_auth(alice_token),
        json={
            "name": "alice-key",
            "provider": "openai",
            "api_key": "sk-alice-1234567890",
            "model": "gpt-4o",
        },
    )
    cred_id = created.json()["data"]["id"]

    response = client.get(
        f"/api/v1/llm-credentials/{cred_id}", headers=_auth(bob_token)
    )
    assert response.status_code == 404


# --- Update ---


def test_update_renames_and_swaps_key(client):
    token = _signup(client)
    created = client.post(
        "/api/v1/llm-credentials",
        headers=_auth(token),
        json={
            "name": "old",
            "provider": "openai",
            "api_key": "sk-original-1234567890",
            "model": "gpt-4o",
        },
    )
    cred_id = created.json()["data"]["id"]

    response = client.patch(
        f"/api/v1/llm-credentials/{cred_id}",
        headers=_auth(token),
        json={"name": "new", "api_key": "sk-rotated-9876543210"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["name"] == "new"
    assert body["api_key_preview"].startswith("sk-rot")
    assert "9876543210" not in body["api_key_preview"]


def test_update_404_for_missing(client):
    token = _signup(client)
    response = client.patch(
        "/api/v1/llm-credentials/00000000-0000-0000-0000-000000000000",
        headers=_auth(token),
        json={"name": "anything"},
    )
    assert response.status_code == 404


# --- Delete ---


def test_delete_soft_removes_credential(client):
    token = _signup(client)
    created = client.post(
        "/api/v1/llm-credentials",
        headers=_auth(token),
        json={
            "name": "doomed",
            "provider": "openai",
            "api_key": "sk-doomed-1234567890",
            "model": "gpt-4o",
        },
    )
    cred_id = created.json()["data"]["id"]

    deleted = client.delete(
        f"/api/v1/llm-credentials/{cred_id}", headers=_auth(token)
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True

    # Subsequent get returns 404
    fetched = client.get(
        f"/api/v1/llm-credentials/{cred_id}", headers=_auth(token)
    )
    assert fetched.status_code == 404


# --- Auth required ---


def test_unauthenticated_requests_rejected(client):
    response = client.get("/api/v1/llm-credentials")
    assert response.status_code == 401


def test_invalid_uuid_format(client):
    token = _signup(client)
    response = client.get(
        "/api/v1/llm-credentials/not-a-uuid", headers=_auth(token)
    )
    assert response.status_code == 400
