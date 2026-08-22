"""Tests for VersionManager — version registration, negotiation, deprecation headers."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.api.version_manager import VersionManager, VersionStatus


@pytest.fixture
def vm() -> VersionManager:
    return VersionManager(default_version="v1")


# ---------------------------------------------------------------------------
# register_version / get_version_info / get_all_versions
# ---------------------------------------------------------------------------


class TestRegisterAndQuery:
    def test_get_version_info_returns_none_for_unknown(self, vm):
        assert vm.get_version_info("v99") is None

    def test_get_version_info_returns_registered(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE)
        info = vm.get_version_info("v1")
        assert info is not None
        assert info.version == "v1"
        assert info.status == VersionStatus.STABLE

    def test_get_all_versions_returns_copy(self, vm):
        vm.register_version("v1")
        all_v = vm.get_all_versions()
        assert "v1" in all_v
        # modifying the copy doesn't affect internals
        all_v["v99"] = None
        assert "v99" not in vm._versions


# ---------------------------------------------------------------------------
# get_active_versions / is_version_available
# ---------------------------------------------------------------------------


class TestActiveVersions:
    def test_active_excludes_sunset(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE)
        vm.register_version("v0", status=VersionStatus.SUNSET)
        active = vm.get_active_versions()
        assert "v1" in active
        assert "v0" not in active

    def test_is_version_available_true_for_stable(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE)
        assert vm.is_version_available("v1") is True

    def test_is_version_available_false_for_sunset(self, vm):
        vm.register_version("v0", status=VersionStatus.SUNSET)
        assert vm.is_version_available("v0") is False

    def test_is_version_available_false_for_unknown(self, vm):
        assert vm.is_version_available("v99") is False


# ---------------------------------------------------------------------------
# get_latest_stable_version
# ---------------------------------------------------------------------------


class TestGetLatestStable:
    def test_returns_none_when_no_stable(self, vm):
        vm.register_version("v0", status=VersionStatus.DEPRECATED)
        assert vm.get_latest_stable_version() is None

    def test_returns_newest_stable_by_release_date(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE, release_date=datetime(2023, 1, 1))
        vm.register_version("v2", status=VersionStatus.STABLE, release_date=datetime(2024, 1, 1))
        assert vm.get_latest_stable_version() == "v2"

    def test_returns_stable_with_no_release_date(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE)
        result = vm.get_latest_stable_version()
        assert result == "v1"


# ---------------------------------------------------------------------------
# get_deprecation_headers
# ---------------------------------------------------------------------------


class TestGetDeprecationHeaders:
    def test_returns_empty_for_unknown_version(self, vm):
        headers = vm.get_deprecation_headers("v99")
        assert headers == {}

    def test_stable_returns_no_deprecation_headers(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE)
        headers = vm.get_deprecation_headers("v1")
        assert "Deprecation" not in headers

    def test_deprecated_adds_deprecation_true(self, vm):
        vm.register_version("v0", status=VersionStatus.DEPRECATED)
        headers = vm.get_deprecation_headers("v0")
        assert headers.get("Deprecation") == "true"

    def test_deprecated_with_dates(self, vm):
        vm.register_version(
            "v0",
            status=VersionStatus.DEPRECATED,
            deprecation_date=datetime(2024, 6, 1),
            sunset_date=datetime(2025, 1, 1),
        )
        headers = vm.get_deprecation_headers("v0")
        assert "Deprecation-Date" in headers
        assert "Sunset" in headers

    def test_deprecated_with_docs_url_adds_link(self, vm):
        vm.register_version(
            "v0",
            status=VersionStatus.DEPRECATED,
            documentation_url="https://docs.example.com/migration",
        )
        headers = vm.get_deprecation_headers("v0")
        assert "Link" in headers
        assert "docs.example.com" in headers["Link"]

    def test_deprecated_with_stable_adds_warning(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE, release_date=datetime(2024, 1, 1))
        vm.register_version("v0", status=VersionStatus.DEPRECATED)
        headers = vm.get_deprecation_headers("v0")
        assert "Warning" in headers
        assert "v1" in headers["Warning"]

    def test_beta_adds_warning(self, vm):
        vm.register_version("v2", status=VersionStatus.BETA)
        headers = vm.get_deprecation_headers("v2")
        assert "Warning" in headers
        assert "beta" in headers["Warning"]


# ---------------------------------------------------------------------------
# negotiate_version
# ---------------------------------------------------------------------------


class TestNegotiateVersion:
    def test_returns_requested_if_available(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE)
        result = vm.negotiate_version(requested_version="v1")
        assert result == "v1"

    def test_ignores_unavailable_requested(self, vm):
        result = vm.negotiate_version(requested_version="v99")
        assert result == vm.default_version

    def test_accept_header_vnd_format(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE)
        result = vm.negotiate_version(
            accept_header="application/vnd.petri-net-sim.v1+json"
        )
        assert result == "v1"

    def test_accept_header_version_param_format(self, vm):
        vm.register_version("v1", status=VersionStatus.STABLE)
        result = vm.negotiate_version(
            accept_header="application/vnd.petri-net-sim+json; version=1"
        )
        assert result == "v1"

    def test_accept_header_non_matching_returns_default(self, vm):
        result = vm.negotiate_version(accept_header="application/json")
        assert result == vm.default_version

    def test_accept_header_unknown_version_falls_to_default(self, vm):
        result = vm.negotiate_version(
            accept_header="application/vnd.petri-net-sim.v99+json"
        )
        assert result == vm.default_version

    def test_falls_back_to_default_version(self, vm):
        result = vm.negotiate_version()
        assert result == "v1"


# ---------------------------------------------------------------------------
# _parse_version_from_accept_header
# ---------------------------------------------------------------------------


class TestParseVersionFromAcceptHeader:
    def test_non_vnd_returns_none(self, vm):
        result = vm._parse_version_from_accept_header("application/json")
        assert result is None

    def test_vnd_v_format(self, vm):
        result = vm._parse_version_from_accept_header("application/vnd.petri-net-sim.v2+json")
        assert result == "v2"

    def test_version_param_format(self, vm):
        result = vm._parse_version_from_accept_header(
            "application/vnd.petri-net-sim+json; version=3"
        )
        assert result == "v3"

    def test_vnd_without_version_part(self, vm):
        result = vm._parse_version_from_accept_header("application/vnd.petri-net-sim+json")
        assert result is None
