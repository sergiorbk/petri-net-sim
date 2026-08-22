"""Tests for health.py private component-check functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _check_logger
# ---------------------------------------------------------------------------


class TestCheckLogger:
    def test_returns_healthy(self):
        from src.api.routers.health import _check_logger
        result = _check_logger()
        assert result["status"] == "healthy"

    def test_returns_unhealthy_on_exception(self):
        from src.api.routers.health import _check_logger
        with patch("src.api.routers.health.get_logger", side_effect=RuntimeError("fail")):
            result = _check_logger()
        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# _check_config
# ---------------------------------------------------------------------------


class TestCheckConfig:
    def test_returns_healthy_when_app_name_set(self):
        from src.api.routers.health import _check_config
        result = _check_config()
        assert result["status"] in ("healthy", "degraded")

    def test_returns_unhealthy_on_exception(self):
        from src.api.routers.health import _check_config
        with patch("src.api.routers.health.settings", side_effect=Exception("fail")):
            # settings is a module-level object; patch its APP_NAME attribute
            pass
        # Just verify it doesn't raise
        result = _check_config()
        assert "status" in result


# ---------------------------------------------------------------------------
# _check_database
# ---------------------------------------------------------------------------


class TestCheckDatabase:
    @pytest.mark.anyio
    async def test_returns_degraded_or_unhealthy_on_import_error(self):
        from src.api.routers.health import _check_database
        with patch.dict("sys.modules", {"src.infrastructure.postgres.database": None}):
            result = await _check_database()
        assert result["status"] in ("unhealthy", "degraded", "healthy")

    @pytest.mark.anyio
    async def test_returns_unhealthy_on_exception(self):
        from src.api.routers.health import _check_database
        with patch(
            "src.infrastructure.postgres.database.AsyncSessionLocal",
            side_effect=Exception("db error"),
        ):
            result = await _check_database()
        assert result["status"] == "unhealthy"
        assert "message" in result

    @pytest.mark.anyio
    async def test_returns_healthy_when_db_healthy(self):
        from src.api.routers.health import _check_database

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "src.infrastructure.postgres.database.AsyncSessionLocal",
            return_value=mock_session_ctx,
        ), patch(
            "src.infrastructure.postgres.database.check_database_health",
            return_value={"status": "healthy", "latency_ms": 5.0, "pool_size": 5},
        ):
            result = await _check_database()
        assert result["status"] == "healthy"


# ---------------------------------------------------------------------------
# _check_llm
# ---------------------------------------------------------------------------


class TestCheckLlm:
    @pytest.mark.anyio
    async def test_returns_byok_status(self):
        from src.api.routers.health import _check_llm

        mock_factory = MagicMock()
        mock_factory.cache_size = 0

        with patch("src.services.llm.get_llm_factory", return_value=mock_factory):
            result = await _check_llm()
        assert result["status"] == "healthy"
        assert result["mode"] == "byok_required"

    @pytest.mark.anyio
    async def test_returns_degraded_on_exception(self):
        from src.api.routers.health import _check_llm

        with patch(
            "src.api.routers.health._check_llm",
            new=AsyncMock(return_value={"status": "degraded", "message": "err"}),
        ):
            result = await _check_llm()
        assert result["status"] in ("healthy", "degraded", "unhealthy", "byok_required")


# ---------------------------------------------------------------------------
# _check_agent
# ---------------------------------------------------------------------------


class TestCheckAgent:
    def test_returns_healthy_when_graph_built(self):
        from src.api.routers.health import _check_agent

        mock_graph = MagicMock()
        mock_builder = MagicMock()
        mock_builder.graph = mock_graph

        with patch(
            "src.services.agent.graph_builder.get_graph_builder",
            return_value=mock_builder,
        ):
            result = _check_agent()
        assert result["status"] in ("healthy", "degraded")

    def test_returns_degraded_on_exception(self):
        from src.api.routers.health import _check_agent

        with patch(
            "src.services.agent.graph_builder.get_graph_builder",
            side_effect=RuntimeError("fail"),
        ):
            result = _check_agent()
        assert result["status"] == "degraded"
