"""The entrypoints' shared secret handling (scripts/manage_secrets.sh).

Auto-generation is a laptop convenience. In a deployed environment it mints a
different JWT secret and master key per container, which logs every user out
and makes stored BYOK credentials unreadable as soon as there is a second
replica or a replaced volume. These tests pin the refusal.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "manage_secrets.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("sh") is None, reason="POSIX sh not on PATH"
)


def _run(env: dict, secrets_file: str = "") -> subprocess.CompletedProcess:
    """Source the script and call ensure_secrets_file with a clean env."""
    base = {
        "PATH": __import__("os").environ["PATH"],
        "AUTH_JWT_SECRET_KEY": "",
        "CREDENTIALS_MASTER_KEY": "",
    }
    return subprocess.run(
        ["sh", "-c", f'. "$1"; ensure_secrets_file "$2"', "sh", str(SCRIPT), secrets_file],
        env={**base, **env},
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("app_env", ["prod", "production", "stage", "staging", "PROD"])
def test_refuses_to_generate_in_a_deployed_environment(app_env):
    result = _run({"APP_ENV": app_env})

    assert result.returncode == 1
    assert "REFUSING TO START" in result.stderr
    # The message has to say what to do, not just what went wrong.
    assert "AUTH_JWT_SECRET_KEY" in result.stderr
    assert "CREDENTIALS_MASTER_KEY" in result.stderr


@pytest.mark.parametrize("app_env", ["local", "dev", "development", ""])
def test_allows_generation_outside_a_deployed_environment(app_env):
    result = _run({"APP_ENV": app_env})

    assert result.returncode == 0
    assert "REFUSING TO START" not in result.stderr


def test_explicit_secrets_need_no_file_even_in_production(tmp_path):
    """The Kubernetes path: both values in the environment, no volume at all."""
    target = tmp_path / "app.env"

    result = _run(
        {
            "APP_ENV": "prod",
            "AUTH_JWT_SECRET_KEY": "a" * 64,
            "CREDENTIALS_MASTER_KEY": "b" * 44,
        },
        secrets_file=str(target),
    )

    assert result.returncode == 0
    assert not target.exists()


def test_one_secret_is_not_enough(tmp_path):
    """Half a pair still leaves the other to be invented per container."""
    result = _run({"APP_ENV": "prod", "AUTH_JWT_SECRET_KEY": "a" * 64})

    assert result.returncode == 1
    assert "REFUSING TO START" in result.stderr
