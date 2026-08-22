"""Tests for startup production-config validation (fail-fast hardening)."""

import logging

import pytest

from src.core.config import ProductionConfigError, settings, validate_production_settings


@pytest.fixture
def safe_prod_config(monkeypatch):
    """Apply a fully safe production configuration; tests flip one value bad."""
    from src.core.agent_config import agent_settings
    from src.core.auth_config import auth_settings

    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "APP_DEBUG", False)
    monkeypatch.setattr(settings, "CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setattr(settings, "CORS_ALLOW_CREDENTIALS", True)
    monkeypatch.setattr(settings, "DOCS_ENABLED", False)
    monkeypatch.setattr(auth_settings, "AUTH_JWT_SECRET_KEY", "a" * 48)
    monkeypatch.setattr(agent_settings, "CREDENTIALS_CIPHER", "fernet")
    monkeypatch.setattr(agent_settings, "CREDENTIALS_MASTER_KEY", "x" * 44)
    return monkeypatch


def test_safe_prod_config_passes(safe_prod_config):
    # Should not raise.
    validate_production_settings()


def test_default_jwt_secret_rejected(safe_prod_config):
    from src.core.auth_config import auth_settings

    safe_prod_config.setattr(
        auth_settings,
        "AUTH_JWT_SECRET_KEY",
        "change-me-in-production-use-strong-secret",
    )
    with pytest.raises(ProductionConfigError, match="AUTH_JWT_SECRET_KEY"):
        validate_production_settings()


def test_short_jwt_secret_rejected(safe_prod_config):
    from src.core.auth_config import auth_settings

    safe_prod_config.setattr(auth_settings, "AUTH_JWT_SECRET_KEY", "tooshort")
    with pytest.raises(ProductionConfigError, match="too short"):
        validate_production_settings()


def test_noop_cipher_rejected(safe_prod_config):
    from src.core.agent_config import agent_settings

    safe_prod_config.setattr(agent_settings, "CREDENTIALS_CIPHER", "noop")
    with pytest.raises(ProductionConfigError, match="noop"):
        validate_production_settings()


def test_fernet_without_master_key_rejected(safe_prod_config):
    from src.core.agent_config import agent_settings

    safe_prod_config.setattr(agent_settings, "CREDENTIALS_MASTER_KEY", "")
    with pytest.raises(ProductionConfigError, match="CREDENTIALS_MASTER_KEY"):
        validate_production_settings()


def test_debug_rejected(safe_prod_config):
    safe_prod_config.setattr(settings, "APP_DEBUG", True)
    with pytest.raises(ProductionConfigError, match="APP_DEBUG"):
        validate_production_settings()


def test_wildcard_cors_with_credentials_rejected(safe_prod_config):
    safe_prod_config.setattr(settings, "CORS_ORIGINS", "*")
    safe_prod_config.setattr(settings, "CORS_ALLOW_CREDENTIALS", True)
    with pytest.raises(ProductionConfigError, match="CORS wildcard"):
        validate_production_settings()


def test_dev_env_tolerates_insecure_config(monkeypatch):
    """In local/dev, insecure settings are advisory only — no raise."""
    from src.core.agent_config import agent_settings
    from src.core.auth_config import auth_settings

    monkeypatch.setattr(settings, "APP_ENV", "local")
    monkeypatch.setattr(settings, "APP_DEBUG", True)
    monkeypatch.setattr(
        auth_settings,
        "AUTH_JWT_SECRET_KEY",
        "change-me-in-production-use-strong-secret",
    )
    monkeypatch.setattr(agent_settings, "CREDENTIALS_CIPHER", "noop")
    # Must not raise despite multiple issues.
    validate_production_settings()


def test_single_user_mode_warns_but_does_not_abort_in_prod(safe_prod_config, caplog):
    """AUTH_MODE=single_user in prod is a deliberate, legitimate deployment
    choice (a private single-operator server) -- it must not fail startup,
    but it must say loudly that there is no login."""
    from src.core.auth_config import auth_settings

    safe_prod_config.setattr(auth_settings, "AUTH_MODE", "single_user")

    with caplog.at_level(logging.WARNING):
        validate_production_settings()  # must not raise

    assert "AUTH_MODE=single_user" in caplog.text
    assert "NO LOGIN" in caplog.text


def test_multi_mode_prod_has_no_single_user_warning(safe_prod_config, caplog):
    from src.core.auth_config import auth_settings

    safe_prod_config.setattr(auth_settings, "AUTH_MODE", "multi")

    with caplog.at_level(logging.WARNING):
        validate_production_settings()

    assert "NO LOGIN" not in caplog.text


def test_single_user_mode_no_special_warning_outside_prod(monkeypatch, caplog):
    """The banner is scoped to deployed environments -- single-user mode in
    local/dev is the expected, unremarkable case."""
    from src.core.auth_config import auth_settings

    monkeypatch.setattr(settings, "APP_ENV", "local")
    monkeypatch.setattr(auth_settings, "AUTH_MODE", "single_user")

    with caplog.at_level(logging.WARNING):
        validate_production_settings()

    assert "NO LOGIN" not in caplog.text


def test_is_production_property(monkeypatch):
    for env in ("prod", "production", "stage", "staging"):
        monkeypatch.setattr(settings, "APP_ENV", env)
        assert settings.is_production is True
    for env in ("local", "dev", "test"):
        monkeypatch.setattr(settings, "APP_ENV", env)
        assert settings.is_production is False
