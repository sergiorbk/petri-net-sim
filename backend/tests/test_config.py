"""Tests for configuration module."""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.core.config import Settings


class TestSettings:
    """Tests for Settings class."""

    def test_settings_default_values(self):
        """Test that default values are set correctly."""
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.APP_NAME == "Petri Net Sim"
        assert settings.APP_DEBUG is False
        assert settings.LOGGING_LEVEL == "INFO"
        assert settings.LOGGING_FILE is None
        assert settings.LOGGING_FORMAT == "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        assert settings.LOGGING_DATE_FORMAT == "%Y-%m-%d %H:%M:%S"

    def test_settings_from_env(self):
        """Test loading settings from environment variables."""
        env = {
            "APP_NAME": "CustomApp",
            "APP_DEBUG": "true",
            "LOGGING_LEVEL": "DEBUG",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = Settings(_env_file=None)

        assert settings.APP_NAME == "CustomApp"
        assert settings.APP_DEBUG is True
        assert settings.LOGGING_LEVEL == "DEBUG"

    def test_log_level_property(self):
        """Test LOG_LEVEL property alias."""
        with patch.dict("os.environ", {"LOGGING_LEVEL": "WARNING"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.LOG_LEVEL == "WARNING"
        assert settings.LOG_LEVEL == settings.LOGGING_LEVEL

    def test_log_file_property_none(self):
        """Test LOG_FILE property when LOGGING_FILE is not set."""
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.LOG_FILE is None

    def test_log_file_property_with_path(self):
        """Test LOG_FILE property converts string to Path."""
        with patch.dict("os.environ", {"LOGGING_FILE": "logs/app.log"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.LOG_FILE == Path("logs/app.log")
        assert isinstance(settings.LOG_FILE, Path)

    def test_debug_property(self):
        """Test DEBUG property alias."""
        with patch.dict("os.environ", {"APP_DEBUG": "true"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.DEBUG is True
        assert settings.DEBUG == settings.APP_DEBUG

    def test_cors_origins_wildcard(self):
        """Test cors_origins_list with wildcard."""
        with patch.dict("os.environ", {"CORS_ORIGINS": "*"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.cors_origins_list == ["*"]

    def test_cors_origins_list(self):
        """Test cors_origins_list parses comma-separated origins."""
        origins = "http://localhost:6200,http://localhost:6203"
        with patch.dict("os.environ", {"CORS_ORIGINS": origins}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.cors_origins_list == [
            "http://localhost:6200",
            "http://localhost:6203",
        ]

    def test_cors_methods_wildcard(self):
        """Test cors_methods_list with wildcard."""
        with patch.dict("os.environ", {"CORS_ALLOW_METHODS": "*"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.cors_methods_list == ["*"]

    def test_cors_methods_list(self):
        """Test cors_methods_list parses comma-separated methods."""
        with patch.dict("os.environ", {"CORS_ALLOW_METHODS": "GET,POST,PUT"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.cors_methods_list == ["GET", "POST", "PUT"]

    def test_cors_headers_wildcard(self):
        """Test cors_headers_list with wildcard."""
        with patch.dict("os.environ", {"CORS_ALLOW_HEADERS": "*"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.cors_headers_list == ["*"]

    def test_mcp_defaults(self):
        """Test MCP default values."""
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.MCP_ENABLED is True
        assert settings.MCP_PATH == "/mcp"
        assert settings.MCP_SESSION_TTL_SECONDS == 3600

    def test_mcp_disabled_via_env(self):
        """Test disabling MCP via environment variable."""
        with patch.dict("os.environ", {"MCP_ENABLED": "false"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.MCP_ENABLED is False

    def test_openai_enabled_default(self):
        """Test OPENAI_ENABLED default."""
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.OPENAI_ENABLED is True


class TestSimulationEngineChoice:
    """Which engine runs a model, and how that choice is made.

    A URL sitting in the environment used to be the whole decision: every run
    went to the external engine, and a deployment that had the address but not
    the service fell back on every single run.
    """

    def test_builtin_is_the_default_engine(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.SIMULATION_ENGINE == "builtin"
        assert settings.simulation_remote_target is None

    def test_a_url_alone_does_not_move_runs_off_the_builtin_engine(self):
        env = {"SIMULATION_REMOTE_URL": "http://petri-server:8080"}
        with patch.dict("os.environ", env, clear=True):
            settings = Settings(_env_file=None)

        assert settings.SIMULATION_ENGINE == "builtin"
        assert settings.simulation_remote_target is None

    def test_remote_engine_reports_its_url(self):
        env = {
            "SIMULATION_ENGINE": "remote",
            "SIMULATION_REMOTE_URL": "http://petri-server:8080",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = Settings(_env_file=None)

        assert settings.simulation_remote_target == "http://petri-server:8080"

    def test_remote_engine_without_a_url_fails_startup(self):
        env = {"SIMULATION_ENGINE": "remote"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValidationError, match="SIMULATION_REMOTE_URL"):
                Settings(_env_file=None)

    def test_remote_engine_with_a_blank_url_fails_startup(self):
        env = {"SIMULATION_ENGINE": "remote", "SIMULATION_REMOTE_URL": "   "}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValidationError, match="SIMULATION_REMOTE_URL"):
                Settings(_env_file=None)

    def test_an_unknown_engine_name_is_rejected(self):
        with patch.dict("os.environ", {"SIMULATION_ENGINE": "java"}, clear=True):
            with pytest.raises(ValidationError):
                Settings(_env_file=None)
