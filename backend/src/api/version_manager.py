"""
API Version Management.

Handles version negotiation, deprecation warnings, and version lifecycle.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from fastapi import Header, Request
from pydantic import BaseModel, Field

from src.core import get_logger

logger = get_logger("api.version_manager")

_VERSION_PARAM = "version="


class VersionStatus(str, Enum):
    """API version lifecycle status"""

    BETA = "beta"  # In development, may change
    STABLE = "stable"  # Production-ready, recommended
    DEPRECATED = "deprecated"  # Still works, but scheduled for removal
    SUNSET = "sunset"  # No longer available


class VersionInfo(BaseModel):
    """API version information"""

    version: str = Field(description="Version identifier (e.g., 'v1', 'v2')")
    status: VersionStatus = Field(description="Version lifecycle status")
    release_date: Optional[datetime] = Field(
        default=None, description="When this version was released"
    )
    deprecation_date: Optional[datetime] = Field(
        default=None, description="When deprecation was announced"
    )
    sunset_date: Optional[datetime] = Field(
        default=None, description="When version will be removed"
    )
    documentation_url: Optional[str] = Field(
        default=None, description="Link to version documentation"
    )
    changelog_url: Optional[str] = Field(
        default=None, description="Link to version changelog"
    )


class VersionManager:
    """
    Manages API versions, deprecation warnings, and version negotiation.

    Usage:
        version_manager = VersionManager()
        version_manager.register_version(
            "v1",
            status=VersionStatus.STABLE,
            release_date=datetime(2024, 1, 1)
        )
    """

    def __init__(self, default_version: str = "v1"):
        self.default_version = default_version
        self._versions: dict[str, VersionInfo] = {}
        logger.info(f"VersionManager initialized with default version: {default_version}")

    def register_version(
        self,
        version: str,
        status: VersionStatus = VersionStatus.STABLE,
        release_date: Optional[datetime] = None,
        deprecation_date: Optional[datetime] = None,
        sunset_date: Optional[datetime] = None,
        documentation_url: Optional[str] = None,
        changelog_url: Optional[str] = None,
    ) -> None:
        """
        Register an API version with its lifecycle information.

        Args:
            version: Version identifier (e.g., 'v1', 'v2')
            status: Current lifecycle status
            release_date: When version was released
            deprecation_date: When deprecation was announced
            sunset_date: When version will be removed
            documentation_url: Link to documentation
            changelog_url: Link to changelog
        """
        version_info = VersionInfo(
            version=version,
            status=status,
            release_date=release_date,
            deprecation_date=deprecation_date,
            sunset_date=sunset_date,
            documentation_url=documentation_url,
            changelog_url=changelog_url,
        )
        self._versions[version] = version_info
        logger.info(f"Registered API version: {version} (status: {status})")

    def get_version_info(self, version: str) -> Optional[VersionInfo]:
        """Get information about a specific version"""
        return self._versions.get(version)

    def get_all_versions(self) -> dict[str, VersionInfo]:
        """Get all registered versions"""
        return self._versions.copy()

    def get_active_versions(self) -> list[str]:
        """Get list of active (non-sunset) versions"""
        return [
            v.version
            for v in self._versions.values()
            if v.status != VersionStatus.SUNSET
        ]

    def is_version_available(self, version: str) -> bool:
        """Check if version exists and is not sunset"""
        version_info = self._versions.get(version)
        return version_info is not None and version_info.status != VersionStatus.SUNSET

    def get_deprecation_headers(self, version: str) -> dict[str, str]:
        """
        Get deprecation warning headers for a version.

        Returns headers following RFC 8594 (Sunset HTTP Header).
        """
        version_info = self._versions.get(version)
        if not version_info:
            return {}

        headers = {}

        if version_info.status == VersionStatus.DEPRECATED:
            headers["Deprecation"] = "true"

            if version_info.deprecation_date:
                # RFC 7231 date format
                headers["Deprecation-Date"] = version_info.deprecation_date.strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                )

            if version_info.sunset_date:
                # RFC 8594 Sunset header
                headers["Sunset"] = version_info.sunset_date.strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                )

            # Add link to migration guide
            if version_info.documentation_url:
                headers["Link"] = (
                    f'<{version_info.documentation_url}>; rel="deprecation"; '
                    f'type="text/html"'
                )

            # Warning message
            latest_stable = self.get_latest_stable_version()
            if latest_stable:
                headers["Warning"] = (
                    f'299 - "API version {version} is deprecated. '
                    f'Please migrate to {latest_stable}"'
                )

        elif version_info.status == VersionStatus.BETA:
            headers["Warning"] = (
                f'299 - "API version {version} is in beta. '
                f"Breaking changes may occur.\""
            )

        return headers

    def get_latest_stable_version(self) -> Optional[str]:
        """Get the latest stable version"""
        stable_versions = [
            v for v in self._versions.values() if v.status == VersionStatus.STABLE
        ]
        if not stable_versions:
            return None

        # Sort by release date (newest first)
        stable_versions.sort(
            key=lambda v: v.release_date or datetime.min, reverse=True
        )
        return stable_versions[0].version

    def negotiate_version(
        self,
        requested_version: Optional[str] = None,
        accept_header: Optional[str] = None,
    ) -> str:
        """
        Negotiate API version based on request.

        Priority:
        1. Explicit version in path (/api/v1/...)
        2. Accept header (Accept: application/vnd.petri-net-sim.v1+json)
        3. Default version

        Args:
            requested_version: Version from URL path
            accept_header: Accept header value

        Returns:
            Negotiated version string
        """
        # Priority 1: Explicit version in path
        if requested_version and self.is_version_available(requested_version):
            return requested_version

        # Priority 2: Accept header
        if accept_header:
            version = self._parse_version_from_accept_header(accept_header)
            if version and self.is_version_available(version):
                return version

        # Priority 3: Default version
        return self.default_version

    def _parse_version_from_accept_header(self, accept_header: str) -> Optional[str]:
        """
        Parse version from Accept header.

        Supports formats:
        - application/vnd.petri-net-sim.v1+json
        - application/vnd.petri-net-sim+json; version=1
        """
        if "vnd.petri-net-sim" not in accept_header:
            return None

        # Format: application/vnd.petri-net-sim.v1+json
        if ".v" in accept_header:
            parts = accept_header.split(".v")
            if len(parts) >= 2:
                version_part = parts[1].split("+")[0].split(";")[0].strip()
                return f"v{version_part}"

        # Format: version=1
        if _VERSION_PARAM in accept_header:
            for part in accept_header.split(";"):
                if _VERSION_PARAM in part:
                    version_num = part.split(_VERSION_PARAM)[1].strip()
                    return f"v{version_num}"

        return None


# Global version manager instance
version_manager = VersionManager(default_version="v1")


def get_api_version(
    request: Request,
    accept: Optional[str] = Header(default=None),
) -> str:
    """
    FastAPI dependency to extract and validate API version.

    Can be used in endpoints to get the current API version:
        @router.get("/items")
        async def get_items(version: str = Depends(get_api_version)):
            ...
    """
    # Extract version from path if present
    path = request.url.path
    requested_version = None

    if "/api/v" in path:
        # Extract version from path like /api/v1/...
        parts = path.split("/api/v")
        if len(parts) > 1:
            version_num = parts[1].split("/")[0]
            requested_version = f"v{version_num}"

    # Negotiate version
    version = version_manager.negotiate_version(requested_version, accept)

    # Store in request state for middleware access
    request.state.api_version = version

    return version


__all__ = [
    "VersionManager",
    "VersionInfo",
    "VersionStatus",
    "version_manager",
    "get_api_version",
]