"""Serves a pre-built frontend (frontend/dist) as static files.

Used only by the all-in-one Docker image (deploy/allinone), which packages
frontend + backend + Postgres into a single container listening on a single
port. The normal multi-container stack does not use this -- nginx serves the
frontend there instead (see frontend/nginx.conf) -- so this stays inert
unless FRONTEND_STATIC_DIR is set.

``mount_static_frontend`` can attach to either a FastAPI app or a bare
Starlette app (the latter matters when MCP is enabled: the MCP server is
itself mounted at "/" on the outer FastAPI app -- see main.py -- so when
both features are on, the frontend routes are attached to that same mounted
sub-app instead of the outer one, since a second Mount("/", ...) on the
outer app would never be reached).
"""

from pathlib import Path
from typing import Any

from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from src.core import get_logger
from src.core.config import settings

logger = get_logger("api.static_frontend")

# Every prefix a real backend route can live under. A GET under one of these
# that reaches this fallback is a genuinely unmatched request (a typo, a
# removed endpoint), not a client-side route -- it must 404, not silently
# resolve to index.html the way a real frontend path does.
_RESERVED_PREFIXES = ("/api", "/health", "/docs", "/redoc", "/openapi.json", settings.MCP_PATH)


def mount_static_frontend(target: Any, static_dir: str) -> None:
    """Mount the built frontend onto ``target``.

    Serves hashed build assets under /assets directly via StaticFiles, and
    falls back to index.html for every other GET request so client-side
    routing (react-router-dom) resolves deep links correctly.

    Routes are appended directly to ``target.router.routes`` rather than via
    the `.get()`/`.route()` decorators, since those differ between FastAPI
    and plain Starlette apps while `.router.routes` is common to both.
    """
    root = Path(static_dir)
    index_file = root / "index.html"
    if not index_file.is_file():
        logger.warning(
            "FRONTEND_STATIC_DIR=%s has no index.html -- frontend will not be served.",
            static_dir,
        )
        return

    assets_dir = root / "assets"
    if assets_dir.is_dir():
        target.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    async def spa_fallback(request):
        request_path = request.url.path
        if any(
            request_path == prefix or request_path.startswith(f"{prefix}/")
            for prefix in _RESERVED_PREFIXES
        ):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        full_path = request.path_params.get("full_path", "")
        # Reject path traversal outside the static root before touching disk.
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and root.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index_file)

    target.router.routes.append(Route("/{full_path:path}", spa_fallback, methods=["GET"]))
    logger.info("Serving built frontend from %s", static_dir)
