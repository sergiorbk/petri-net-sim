"""Tests for the application-layer security middlewares."""

import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from src.api.shared.security_middleware import (
    BodySizeLimitMiddleware,
    ConcurrencyLimitMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
)
from src.core.security_config import security_settings


def _make_request(path="/") -> StarletteRequest:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 9999),
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return StarletteRequest(scope)


# --- Body size limit ---


def test_body_size_limit_rejects_oversized(monkeypatch):
    monkeypatch.setattr(security_settings, "SECURITY_MAX_BODY_BYTES", 100)
    monkeypatch.setattr(security_settings, "SECURITY_LARGE_BODY_PATH_PREFIXES", "")

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)

    @app.post("/echo")
    async def echo(request: Request):
        body = await request.body()
        return {"len": len(body)}

    with TestClient(app, raise_server_exceptions=False) as client:
        ok = client.post("/echo", content=b"x" * 50)
        assert ok.status_code == 200
        assert ok.json()["len"] == 50

        too_big = client.post("/echo", content=b"x" * 500)
        assert too_big.status_code == 413
        assert too_big.json()["max_bytes"] == 100


def test_body_size_limit_large_prefix_gets_higher_cap(monkeypatch):
    monkeypatch.setattr(security_settings, "SECURITY_MAX_BODY_BYTES", 100)
    monkeypatch.setattr(security_settings, "SECURITY_MAX_BODY_BYTES_LARGE", 10_000)
    monkeypatch.setattr(security_settings, "SECURITY_LARGE_BODY_PATH_PREFIXES", "/big")

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)

    @app.post("/big")
    async def big(request: Request):
        body = await request.body()
        return {"len": len(body)}

    with TestClient(app, raise_server_exceptions=False) as client:
        # 500 bytes exceeds the default cap but is under the large-prefix cap.
        r = client.post("/big", content=b"x" * 500)
        assert r.status_code == 200


# --- Concurrency limit ---


@pytest.mark.parametrize("path", ["/mcp", "/api/v1/training/inspect"])
def test_archive_body_limit_is_enforced_for_http_and_mcp(monkeypatch, path):
    monkeypatch.setattr(security_settings, "SECURITY_MAX_BODY_BYTES", 100)
    monkeypatch.setattr(security_settings, "SECURITY_MAX_BODY_BYTES_TRAINING", 1000)
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)

    @app.post(path)
    async def receive(request: Request):
        return {"size": len(await request.body())}

    with TestClient(app) as client:
        assert client.post(path, content=b"x" * 500).status_code == 200
        assert client.post(path, content=b"x" * 1001).status_code == 413


async def test_concurrency_limit_sheds_when_saturated():
    mw = ConcurrencyLimitMiddleware(app=lambda: None, max_concurrent=1)
    mw._in_flight = 1  # simulate a request already in flight

    async def call_next(_request):
        return PlainTextResponse("ok")

    resp = await mw.dispatch(_make_request("/api/v1/chat/completions"), call_next)
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "1"


async def test_concurrency_limit_allows_under_cap():
    mw = ConcurrencyLimitMiddleware(app=lambda: None, max_concurrent=2)

    async def call_next(_request):
        return PlainTextResponse("ok")

    resp = await mw.dispatch(_make_request("/x"), call_next)
    assert resp.status_code == 200
    assert mw._in_flight == 0  # released after handling


async def test_concurrency_limit_skips_health():
    mw = ConcurrencyLimitMiddleware(app=lambda: None, max_concurrent=1)
    mw._in_flight = 5  # saturated

    async def call_next(_request):
        return PlainTextResponse("healthy")

    resp = await mw.dispatch(_make_request("/health"), call_next)
    assert resp.status_code == 200


# --- Request timeout ---


async def test_request_timeout_returns_504():
    mw = RequestTimeoutMiddleware(app=lambda: None, timeout_seconds=0.05)

    async def slow_call_next(_request):
        await asyncio.sleep(0.3)
        return PlainTextResponse("late")

    resp = await mw.dispatch(_make_request("/slow"), slow_call_next)
    assert resp.status_code == 504


async def test_request_timeout_skips_streaming(monkeypatch):
    monkeypatch.setattr(
        security_settings, "SECURITY_STREAMING_PATH_PREFIXES", "/api/v1/chat/completions"
    )
    mw = RequestTimeoutMiddleware(app=lambda: None, timeout_seconds=0.01)

    async def slow_call_next(_request):
        await asyncio.sleep(0.05)
        return PlainTextResponse("streamed")

    # Streaming path must not be timed out.
    resp = await mw.dispatch(
        _make_request("/api/v1/chat/completions"), slow_call_next
    )
    assert resp.status_code == 200


# --- Security headers ---


def test_security_headers_present():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    async def x():
        return {"ok": True}

    with TestClient(app) as client:
        r = client.get("/x")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "Content-Security-Policy" in r.headers


def test_csp_allows_inline_styles_but_not_inline_scripts():
    """React Flow writes a `style` attribute on every node it positions and
    Mermaid injects a stylesheet per diagram, neither of which is a fixed
    string a hash could cover. Without style-src those fell back to
    default-src 'self' and the browser dropped them, taking the canvas
    layout and every diagram with them. script-src stays strict: that is
    where the risk lives, and inline CSS cannot execute."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    async def x():
        return {"ok": True}

    with TestClient(app) as client:
        csp = client.get("/x").headers["Content-Security-Policy"]

    assert "style-src 'self' 'unsafe-inline'" in csp
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    assert "'unsafe-inline'" not in script_src


def test_csp_allows_locally_built_images_but_not_scripts_from_them():
    """The statistics panel exports a chart by serializing its SVG, loading
    that into an <img> through a data: URL and drawing it onto a canvas, then
    handing the PNG over as a blob: download. Both schemes fell back to
    default-src 'self', so the image never loaded and the export silently
    produced no file. Neither scheme reaches script-src, which is where a
    data: URL would actually be dangerous."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    async def x():
        return {"ok": True}

    with TestClient(app) as client:
        csp = client.get("/x").headers["Content-Security-Policy"]

    img_src = next(d for d in csp.split(";") if d.strip().startswith("img-src"))
    assert "data:" in img_src
    assert "blob:" in img_src

    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    assert "data:" not in script_src
    assert "blob:" not in script_src


def test_hsts_disabled_by_default(monkeypatch):
    monkeypatch.setattr(security_settings, "SECURITY_HSTS_ENABLED", False)
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    async def x():
        return {"ok": True}

    with TestClient(app) as client:
        r = client.get("/x")
        assert "Strict-Transport-Security" not in r.headers


def test_hsts_enabled(monkeypatch):
    monkeypatch.setattr(security_settings, "SECURITY_HSTS_ENABLED", True)
    monkeypatch.setattr(security_settings, "SECURITY_HSTS_MAX_AGE", 12345)
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    async def x():
        return {"ok": True}

    with TestClient(app) as client:
        r = client.get("/x")
        assert "max-age=12345" in r.headers["Strict-Transport-Security"]
