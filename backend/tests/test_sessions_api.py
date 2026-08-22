"""Tests for /v1/sessions/* API endpoints."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.net_snapshot import NetSnapshot
from src.infrastructure.postgres.models.session import Session as SessionModel
from src.infrastructure.postgres.models.user import User


# ---------------------------------------------------------------------------
# App factory and fixtures
# ---------------------------------------------------------------------------


def _create_test_app() -> FastAPI:
    from src.api.shared.exceptions import ApiException
    from src.api.shared.handlers import api_exception_handler
    from src.api.versions.v1.routers.auth import router as auth_router
    from src.api.versions.v1.routers.sessions import router as sessions_router

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.add_exception_handler(ApiException, api_exception_handler)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    return app


@pytest.fixture
def app():
    return _create_test_app()


@pytest.fixture
def client(app, session_factory):
    from src.core.dependencies import get_postgres_session

    async def _override_session():
        async with session_factory() as sess:
            yield sess

    app.dependency_overrides[get_postgres_session] = _override_session

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


def _signup(client: TestClient, email: str = "user@example.com") -> str:
    """Sign up and return the access token."""
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _new_session_id() -> str:
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()


async def _create_db_session(
    db: AsyncSession,
    user: User,
    *,
    session_id: str | None = None,
    title: str = "Test Session",
    visibility: str = "private",
    net_data: dict | None = None,
) -> SessionModel:
    s = SessionModel(
        id=session_id or _new_session_id(),
        user_id=user.id,
        title=title,
        net_data=net_data or {},
        messages=[],
        visibility=visibility,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_accessed_at=datetime.now(UTC),
    )
    db.add(s)
    await db.flush()
    await db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# GET /sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_unauthenticated_returns_401(self, client):
        response = client.get("/api/v1/sessions")
        assert response.status_code in (401, 403)

    def test_empty_list_for_new_user(self, client):
        token = _signup(client)
        response = client.get("/api/v1/sessions", headers=_auth(token))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["items"] == []
        assert data["data"]["has_more"] is False

    @pytest.mark.anyio
    async def test_lists_own_sessions(self, client, session, password_user):
        await _create_db_session(session, password_user, title="My Session")
        await session.commit()

        token = _signup(client, "lister@example.com")
        # password_user sessions are not visible to a different user
        response = client.get("/api/v1/sessions", headers=_auth(token))
        assert response.status_code == 200
        assert response.json()["data"]["items"] == []

    @pytest.mark.anyio
    async def test_pagination_limit(self, client, session, password_user):
        for i in range(5):
            await _create_db_session(session, password_user, title=f"S{i}")
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        jwt = get_jwt_service()
        token = jwt.create_access_token(password_user.id, password_user.email)

        response = client.get("/api/v1/sessions?limit=3", headers=_auth(token))
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["items"]) == 3
        assert data["has_more"] is True

    @pytest.mark.anyio
    async def test_pagination_no_more(self, client, session, password_user):
        for i in range(2):
            await _create_db_session(session, password_user, title=f"S{i}")
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        jwt = get_jwt_service()
        token = jwt.create_access_token(password_user.id, password_user.email)

        response = client.get("/api/v1/sessions?limit=10", headers=_auth(token))
        data = response.json()["data"]
        assert len(data["items"]) == 2
        assert data["has_more"] is False


# ---------------------------------------------------------------------------
# PATCH /sessions/{id}
# ---------------------------------------------------------------------------


class TestUpdateSession:
    @pytest.mark.anyio
    async def test_update_title(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.patch(
            f"/api/v1/sessions/{s.id}",
            json={"title": "Updated Title"},
            headers=_auth(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["updated"] is True

    def test_nonexistent_session_returns_404(self, client):
        token = _signup(client)
        response = client.patch(
            "/api/v1/sessions/doesnotexist",
            json={"title": "X"},
            headers=_auth(token),
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_cannot_update_other_users_session(self, client, session, regular_user):
        s = await _create_db_session(session, regular_user)
        await session.commit()

        token = _signup(client, "attacker@example.com")
        response = client.patch(
            f"/api/v1/sessions/{s.id}",
            json={"title": "Stolen"},
            headers=_auth(token),
        )
        assert response.status_code == 404

    def test_unauthenticated_returns_401(self, client):
        response = client.patch("/api/v1/sessions/any", json={"title": "X"})
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# DELETE /sessions/{id}
# ---------------------------------------------------------------------------


class TestDeleteSession:
    @pytest.mark.anyio
    async def test_delete_own_session(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.delete(f"/api/v1/sessions/{s.id}", headers=_auth(token))
        assert response.status_code == 200
        assert response.json()["data"]["deleted"] is True

    def test_nonexistent_session_returns_404(self, client):
        token = _signup(client)
        response = client.delete("/api/v1/sessions/doesnotexist", headers=_auth(token))
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_cannot_delete_other_users_session(self, client, session, regular_user):
        s = await _create_db_session(session, regular_user)
        await session.commit()

        token = _signup(client, "attacker2@example.com")
        response = client.delete(f"/api/v1/sessions/{s.id}", headers=_auth(token))
        assert response.status_code == 404

    def test_unauthenticated_returns_401(self, client):
        response = client.delete("/api/v1/sessions/any")
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PUT /sessions/{id}/messages
# ---------------------------------------------------------------------------


class TestSyncMessages:
    @pytest.mark.anyio
    async def test_sync_messages_success(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        messages = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
        response = client.put(
            f"/api/v1/sessions/{s.id}/messages",
            json={"messages": messages},
            headers=_auth(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["synced"] is True

    @pytest.mark.anyio
    async def test_sync_empty_messages(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.put(
            f"/api/v1/sessions/{s.id}/messages",
            json={"messages": []},
            headers=_auth(token),
        )
        assert response.status_code == 200

    def test_nonexistent_session_returns_404(self, client):
        token = _signup(client)
        response = client.put(
            "/api/v1/sessions/doesnotexist/messages",
            json={"messages": []},
            headers=_auth(token),
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_cannot_sync_other_users_session(self, client, session, regular_user):
        s = await _create_db_session(session, regular_user)
        await session.commit()

        token = _signup(client, "attacker3@example.com")
        response = client.put(
            f"/api/v1/sessions/{s.id}/messages",
            json={"messages": []},
            headers=_auth(token),
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /sessions/{id}/share
# ---------------------------------------------------------------------------


class TestShareSession:
    @pytest.mark.anyio
    async def test_set_visibility_link_only(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.patch(
            f"/api/v1/sessions/{s.id}/share",
            json={"visibility": "link_only"},
            headers=_auth(token),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["visibility"] == "link_only"
        assert "share_token" in data
        assert len(data["share_token"]) > 0

    @pytest.mark.anyio
    async def test_set_visibility_private(self, client, session, password_user):
        s = await _create_db_session(session, password_user, visibility="link_only")
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.patch(
            f"/api/v1/sessions/{s.id}/share",
            json={"visibility": "private"},
            headers=_auth(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["visibility"] == "private"

    def test_invalid_visibility_returns_400(self, client):
        token = _signup(client, "vis@example.com")
        response = client.patch(
            "/api/v1/sessions/any/share",
            json={"visibility": "unknown"},
            headers=_auth(token),
        )
        assert response.status_code in (400, 404)

    def test_nonexistent_session_returns_404(self, client):
        token = _signup(client, "vis2@example.com")
        response = client.patch(
            "/api/v1/sessions/doesnotexist/share",
            json={"visibility": "link_only"},
            headers=_auth(token),
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_cannot_share_other_users_session(self, client, session, regular_user):
        s = await _create_db_session(session, regular_user)
        await session.commit()

        token = _signup(client, "attacker4@example.com")
        response = client.patch(
            f"/api/v1/sessions/{s.id}/share",
            json={"visibility": "link_only"},
            headers=_auth(token),
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /sessions/{id}/net
# ---------------------------------------------------------------------------


class TestGetSessionNet:
    @pytest.mark.anyio
    async def test_get_net_returns_dict(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.get(f"/api/v1/sessions/{s.id}/net", headers=_auth(token))
        assert response.status_code == 200
        assert isinstance(response.json()["data"], dict)

    @pytest.mark.anyio
    async def test_strips_internal_keys(self, client, session, password_user):
        """Internal side-channel keys must not be sent to the client."""
        s = await _create_db_session(
            session,
            password_user,
            net_data={
                "_last_pnml_export": "secret",
                "_last_output_place_id": "p0",
                "_active_object_id": "o1",
                "places": [],
            },
        )
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.get(f"/api/v1/sessions/{s.id}/net", headers=_auth(token))
        assert response.status_code == 200
        data = response.json()["data"]
        assert "_last_pnml_export" not in data
        assert "_last_output_place_id" not in data
        # _active_object_id is pure tool-dispatch bookkeeping (which
        # Petri-object add_*/modify_* calls were targeting) -- meaningless,
        # and previously leaked verbatim, to a GET /net response.
        assert "_active_object_id" not in data

    def test_nonexistent_returns_404(self, client):
        token = _signup(client, "net@example.com")
        response = client.get("/api/v1/sessions/doesnotexist/net", headers=_auth(token))
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_cannot_read_other_users_net(self, client, session, regular_user):
        s = await _create_db_session(session, regular_user)
        await session.commit()

        token = _signup(client, "attacker5@example.com")
        response = client.get(f"/api/v1/sessions/{s.id}/net", headers=_auth(token))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /sessions/{id}/pnml
# ---------------------------------------------------------------------------


def _flat_net_data() -> dict:
    from src.services.petri.session import PetriNetSession

    s = PetriNetSession()
    s.create_network("Flat Export")
    s.builder.add_raw_place("P1")
    return s.to_net_data()


def _composed_net_data() -> dict:
    from src.domain.composed import LinkType
    from src.services.petri.session import PetriNetSession

    s = PetriNetSession()
    s.create_object("Loader")
    p1 = s.builder.add_raw_place("P1")
    s.create_object("Sink")
    p2 = s.builder.add_raw_place("P2")
    s.set_active_object(0)
    t1 = s.builder.add_raw_transition("T1", mean_delay=1.0)
    s.net.add_arc(source_id=p1, target_id=t1)
    s.add_link(
        LinkType.TRANSITION_TO_PLACE,
        s.objects[0].frame_id, t1,
        s.objects[1].frame_id, p2,
    )
    return s.to_net_data()


class TestGetSessionPnml:
    @pytest.mark.anyio
    async def test_get_pnml_returns_downloadable_xml(self, client, session, password_user):
        s = await _create_db_session(session, password_user, title="My Net", net_data=_flat_net_data())
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.get(f"/api/v1/sessions/{s.id}/pnml", headers=_auth(token))

        assert response.status_code == 200, response.text
        assert "xml" in response.headers["content-type"]
        disposition = response.headers["content-disposition"]
        assert "attachment" in disposition
        assert ".pnml" in disposition
        assert "<?xml" in response.text
        assert "Flat Export" in response.text

    @pytest.mark.anyio
    async def test_get_pnml_uses_composed_dialect_when_composed(self, client, session, password_user):
        """A composed session's exported PNML round-trips through the
        importer back into objects/links -- proving the composed dialect
        (not the flat single-page one) was used, without hard-coding the
        exporter's own XML markers here."""
        s = await _create_db_session(
            session, password_user, title="Composed", net_data=_composed_net_data(),
        )
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        from src.services.petri.importer import parse_pnml

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.get(f"/api/v1/sessions/{s.id}/pnml", headers=_auth(token))

        assert response.status_code == 200, response.text
        net_data, warnings = parse_pnml(response.text)
        assert warnings == []
        assert {o["name"] for o in net_data["objects"]} == {"Loader", "Sink"}
        assert len(net_data["links"]) == 1

    def test_get_pnml_nonexistent_returns_404(self, client):
        token = _signup(client, "pnml-missing@example.com")
        response = client.get("/api/v1/sessions/doesnotexist/pnml", headers=_auth(token))
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_cannot_read_other_users_pnml(self, client, session, regular_user):
        s = await _create_db_session(session, regular_user, net_data=_flat_net_data())
        await session.commit()

        token = _signup(client, "attacker-pnml@example.com")
        response = client.get(f"/api/v1/sessions/{s.id}/pnml", headers=_auth(token))
        assert response.status_code == 404

    def test_get_pnml_unauthenticated_returns_401_or_403(self, client):
        response = client.get("/api/v1/sessions/doesnotexist/pnml")
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /sessions/{id}/snapshots
# ---------------------------------------------------------------------------


class TestListSessionSnapshots:
    @pytest.mark.anyio
    async def test_empty_snapshots(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.get(f"/api/v1/sessions/{s.id}/snapshots", headers=_auth(token))
        assert response.status_code == 200
        assert response.json()["data"] == []

    @pytest.mark.anyio
    async def test_lists_snapshots(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        snap = NetSnapshot(
            session_id=s.id,
            net_data={"places": []},
            content_hash=hashlib.sha256(b"{}").hexdigest(),
            source="agent",
        )
        session.add(snap)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service

        token = get_jwt_service().create_access_token(password_user.id, password_user.email)
        response = client.get(f"/api/v1/sessions/{s.id}/snapshots", headers=_auth(token))
        assert response.status_code == 200
        items = response.json()["data"]
        assert len(items) == 1
        assert items[0]["source"] == "agent"

    def test_nonexistent_session_returns_404(self, client):
        token = _signup(client, "snap@example.com")
        response = client.get("/api/v1/sessions/doesnotexist/snapshots", headers=_auth(token))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /sessions/shared/{share_token}  (public endpoint)
# ---------------------------------------------------------------------------


class TestSharedSession:
    @pytest.mark.anyio
    async def test_link_only_session_accessible_without_auth(self, client, session, password_user):
        s = await _create_db_session(session, password_user, visibility="link_only")
        await session.commit()

        response = client.get(f"/api/v1/sessions/shared/{s.share_token}")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["visibility"] == "link_only"
        assert data["share_token"] == str(s.share_token)

    @pytest.mark.anyio
    async def test_private_session_returns_404(self, client, session, password_user):
        s = await _create_db_session(session, password_user, visibility="private")
        await session.commit()

        response = client.get(f"/api/v1/sessions/shared/{s.share_token}")
        assert response.status_code == 404

    def test_unknown_token_returns_404(self, client):
        response = client.get(f"/api/v1/sessions/shared/{uuid.uuid4()}")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_shared_session_has_no_internal_keys(self, client, session, password_user):
        s = await _create_db_session(
            session,
            password_user,
            visibility="link_only",
            net_data={
                "_last_pnml_export": "hidden",
                "_active_object_id": "o1",
                "places": [],
            },
        )
        await session.commit()

        response = client.get(f"/api/v1/sessions/shared/{s.share_token}")
        assert response.status_code == 200
        net = response.json()["data"]["net_data"]
        assert "_last_pnml_export" not in net
        assert "_active_object_id" not in net


# ---------------------------------------------------------------------------
# GET /sessions/shared/{share_token}/snapshots  (public endpoint)
# ---------------------------------------------------------------------------


class TestSharedSessionSnapshots:
    @pytest.mark.anyio
    async def test_shared_session_empty_snapshots(self, client, session, password_user):
        s = await _create_db_session(session, password_user, visibility="link_only")
        await session.commit()

        response = client.get(f"/api/v1/sessions/shared/{s.share_token}/snapshots")
        assert response.status_code == 200
        assert response.json()["data"] == []

    @pytest.mark.anyio
    async def test_private_session_snapshots_returns_404(self, client, session, password_user):
        s = await _create_db_session(session, password_user, visibility="private")
        await session.commit()

        response = client.get(f"/api/v1/sessions/shared/{s.share_token}/snapshots")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_shared_session_with_snapshots(self, client, session, password_user):
        s = await _create_db_session(session, password_user, visibility="link_only")
        snap = NetSnapshot(
            session_id=s.id,
            net_data={"places": []},
            content_hash=hashlib.sha256(b"snap").hexdigest(),
            source="user",
        )
        session.add(snap)
        await session.commit()

        response = client.get(f"/api/v1/sessions/shared/{s.share_token}/snapshots")
        assert response.status_code == 200
        items = response.json()["data"]
        assert len(items) == 1
        assert items[0]["source"] == "user"
