"""mount_static_frontend: hashed assets, SPA fallback, reserved API prefixes.

Only exercised when the all-in-one image sets FRONTEND_STATIC_DIR; the
normal multi-container stack never calls this (nginx serves the frontend
there instead), so these tests build a throwaway Starlette app rather than
going through the real backend app.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src.api.static_frontend import mount_static_frontend


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>spa shell</html>", encoding="utf-8")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    return root


@pytest.fixture
def client(static_dir: Path) -> TestClient:
    app = Starlette()
    mount_static_frontend(app, str(static_dir))
    return TestClient(app)


class TestHashedAssets:
    def test_serves_a_real_asset_file(self, client: TestClient):
        resp = client.get("/assets/index-abc123.js")
        assert resp.status_code == 200
        assert "console.log" in resp.text


class TestSpaFallback:
    def test_root_serves_index_html(self, client: TestClient):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "spa shell" in resp.text

    def test_a_client_side_route_also_serves_index_html(self, client: TestClient):
        resp = client.get("/nets/some-deep-link")
        assert resp.status_code == 200
        assert "spa shell" in resp.text

    def test_path_traversal_falls_back_to_index_instead_of_reading_outside_root(
        self, client: TestClient, tmp_path: Path
    ):
        secret = tmp_path / "outside.txt"
        secret.write_text("not servable", encoding="utf-8")
        resp = client.get("/../outside.txt")
        assert resp.status_code == 200
        assert "not servable" not in resp.text


class TestReservedPrefixes404InsteadOfServingTheShell:
    """A genuinely unmatched request under a real API prefix is a bug (a typo,
    a removed endpoint) that must surface as 404, not silently resolve to the
    SPA shell the way an actual client-side route does."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/nosuchendpoint",
            "/api/v1/nets/does-not-exist-either",
            "/health/nonexistent",
            "/docs/nonexistent",
            "/redoc/nonexistent",
            "/openapi.json",
            "/mcp/nonexistent",
        ],
    )
    def test_reserved_prefix_404s(self, client: TestClient, path: str):
        resp = client.get(path)
        assert resp.status_code == 404
        assert "spa shell" not in resp.text

    def test_a_path_that_merely_contains_a_reserved_word_still_falls_through_to_the_spa(
        self, client: TestClient
    ):
        # "/apidocs" is not "/api" or "/docs" (no prefix boundary), so it is a
        # legitimate client-side route, not a mistyped API call.
        resp = client.get("/apidocs")
        assert resp.status_code == 200
        assert "spa shell" in resp.text
