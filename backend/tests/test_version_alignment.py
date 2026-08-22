"""Every place that states this product's release must agree.

Sibling to test_composed_pnml_exporter.py's
test_petri_net_sim_version_matches_the_web_application, which only checks
frontend/package.json against PETRI_NET_SIM_VERSION (the PNML toolspecific
constant). This test widens the same guarantee to the other two independent
copies of the version string -- backend/pyproject.toml and
Settings.APP_VERSION's default -- so a bump that only touches some of the
four sources fails CI instead of shipping a mismatched release.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from unittest.mock import patch

from src.core.config import Settings
from src.services.petri.exporter.toolspecific import PETRI_NET_SIM_VERSION

_REPO_ROOT = Path(__file__).parent.parent.parent


def _frontend_package_version() -> str:
    package_json = _REPO_ROOT / "frontend" / "package.json"
    return json.loads(package_json.read_text(encoding="utf-8"))["version"]


def _backend_pyproject_version() -> str:
    pyproject = _REPO_ROOT / "backend" / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def _app_version_default() -> str:
    """Settings.APP_VERSION with no environment override -- the field default."""
    with patch.dict("os.environ", {}, clear=True):
        return Settings(_env_file=None).APP_VERSION


class TestVersionAlignment:
    """package.json, pyproject.toml, APP_VERSION, and PETRI_NET_SIM_VERSION
    all state one release number. Any one of them drifting is a bug, so they
    are compared directly against each other rather than each against a
    literal -- the literal itself changes on every bump, this test should not
    need to."""

    def test_frontend_and_backend_package_versions_match(self):
        assert _frontend_package_version() == _backend_pyproject_version()

    def test_app_version_default_matches_the_web_application(self):
        assert _app_version_default() == _frontend_package_version()

    def test_pnml_toolspecific_version_matches_the_web_application(self):
        assert PETRI_NET_SIM_VERSION == _frontend_package_version()

    def test_all_four_sources_agree(self):
        versions = {
            "frontend/package.json": _frontend_package_version(),
            "backend/pyproject.toml": _backend_pyproject_version(),
            "Settings.APP_VERSION default": _app_version_default(),
            "PETRI_NET_SIM_VERSION": PETRI_NET_SIM_VERSION,
        }
        distinct = set(versions.values())
        assert len(distinct) == 1, f"version sources disagree: {versions}"
