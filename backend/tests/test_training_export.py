"""Training downloads preserve evidence and distinguish missing observations."""
import base64
import hashlib
import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.api.shared.exceptions import NotFoundException
from src.api.versions.v1.routers.sessions import export_session_training_data, TrainingExportRequest
from src.domain.models import PetriNet
from src.mcp.session_store import SessionStore
from src.mcp.tools.petri_tools import _build_tool_fn
from src.services.petri.agent_toolkit import build_catalog
from src.services.petri.session import PetriNetSession
from src.services.training_export import build_training_bundle, render_network, validate, sanitize


def model():
    net = PetriNet(name="Finite service")
    p = net.add_place("Source", tokens=6, x=-100, y=20)
    t = net.add_transition("Service", mean_delay=1, distribution="det", x=70, y=20)
    q = net.add_place("Completed", x=200, y=20, tag="throughput")
    net.add_arc(p.id, t.id, weight=2)
    net.add_arc(t.id, q.id)
    return net.model_dump()


def unpack(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert archive.testzip() is None
    manifest = json.loads(archive.read("manifest.json"))
    validate(manifest)
    assert set(archive.namelist()) == {"manifest.json"} | {row["name"] for row in manifest["files"]}
    for row in manifest["files"]:
        assert hashlib.sha256(archive.read(row["name"])).hexdigest() == row["sha256"]
    for name, definition in (("task.json", "task"), ("verification.json", "verification"), ("model-geometry.json", "modelGeometry")):
        validate(json.loads(archive.read(name)), definition)
    return archive, manifest


def test_archive_defaults_and_exact_renderer_geometry():
    data, name = build_training_bundle(model(), "Finite / service", context={"task": "Process six tokens"})
    archive, manifest = unpack(data)
    assert name == "Finite___service-training.zip"
    assert manifest["status"] == "unreviewed"
    assert manifest["capture_scope"] == {"conversation": "unavailable", "tool_calls": "unavailable"}
    assert archive.read("conversation.jsonl") == archive.read("tool-calls.jsonl") == b""
    assert json.loads(archive.read("verification.json")) == {"status": "unknown", "checks": [], "simulation": None}
    png = Image.open(io.BytesIO(archive.read("network.png")))
    geometry = json.loads(archive.read("model-geometry.json"))
    assert png.size == (geometry["image"]["width"], geometry["image"]["height"])
    assert {row["kind"] for row in geometry["elements"]} >= {"place", "transition", "arc", "label"}
    for row in geometry["elements"]:
        b = row["bounds"]
        assert 0 <= b["x"] <= b["x"]+b["width"] <= png.width
        assert 0 <= b["y"] <= b["y"]+b["height"] <= png.height
    source = next(p for p in model()["places"] if p["name"] == "Source")
    # IDs are generated, so locate this render's first place by kind.
    bound = next(row["bounds"] for row in geometry["elements"] if row["kind"] == "place")
    transform = geometry["transform"]
    assert bound["x"] == (source["graphics"]["x"]-transform["origin_x"])*transform["scale"]


def test_client_records_and_credentials_do_not_become_training_targets():
    net = model()
    net["places"][0]["name"] = "api_key=hidden_value"
    conversation = [{"role": "user", "content": "6 tokens, password=hidden_password Bearer hidden_bearer sk-1234567890abcdef"}]
    calls = [{"tool": "add_place", "arguments": {"tokens": 6, "api_key": "hidden_key", "config": {"secret": "hidden_config"}}, "result": "tokens=6", "timestamp": "2026-10-30T00:00:00Z", "origin": "client-provided"}]
    data, _ = build_training_bundle(net, "Private task", conversation=conversation, tool_calls=calls, conversation_origin="client-provided", tool_origin="client-provided")
    archive, manifest = unpack(data)
    combined = b"\n".join(archive.read(name) for name in archive.namelist() if not name.endswith(".png"))
    for secret in (b"hidden_value", b"hidden_password", b"hidden_bearer", b"hidden_key", b"hidden_config", b"sk-1234567890abcdef"):
        assert secret not in combined
    assert b'"tokens": 6' in combined
    assert manifest["capture_scope"]["tool_calls"] == "client-provided"
    assert net["places"][0]["name"] == "api_key=hidden_value", "Export must not mutate the live model"


def test_unknown_verification_cannot_claim_pass_without_checks():
    with pytest.raises(ValueError, match="verification"):
        build_training_bundle(model(), "Invalid", context={"verification": {"status": "passed", "checks": [], "simulation": None}})
    with pytest.raises(ValueError, match="conversationRecord"):
        build_training_bundle(model(), "Invalid", conversation=[{"role": "system", "content": "Not task data"}])


def test_render_records_object_frames_and_links():
    net = model()
    net["objects"] = [{"id": "frame", "name": "Module", "graphics": {"x": -130, "y": -30, "width": 450, "height": 200}}]
    net["links"] = [{"id": "fusion", "type": "placeFusion", "sourceId": net["places"][0]["id"], "targetId": net["places"][1]["id"]}]
    png, geometry = render_network(net)
    assert png.startswith(b"\x89PNG")
    assert next(row for row in geometry["elements"] if row["id"] == "frame")["kind"] == "object"
    assert next(row for row in geometry["elements"] if row["id"] == "fusion")["kind"] == "arc"


async def test_mcp_records_actual_calls_and_returns_real_zip_and_png():
    ctx = MagicMock()
    ctx.session = object()
    store = SessionStore()
    ctx.request_context.lifespan_context.session_store = store
    catalog = build_catalog()
    await _build_tool_fn(catalog["create_network"])(ctx=ctx, name="Finite service")
    await _build_tool_fn(catalog["add_place"])(ctx=ctx, name="Source", tokens=6)
    result = json.loads(await _build_tool_fn(catalog["export_training_data"])(ctx=ctx, title="Finite service"))
    archive, manifest = unpack(base64.b64decode(result["data_base64"]))
    records = [json.loads(row) for row in archive.read("tool-calls.jsonl").splitlines()]
    assert [row["tool"] for row in records] == ["create_network", "add_place"]
    assert all(row["origin"] == "application" for row in records)
    assert manifest["capture_scope"]["conversation"] == "unavailable"
    png = json.loads(await _build_tool_fn(catalog["export_image"])(ctx=ctx))
    assert Image.open(io.BytesIO(base64.b64decode(png["data_base64"]))).format == "PNG"


async def test_owner_route_rejects_another_users_session():
    instance = SimpleNamespace(user_id="owner", title="Finite service", net_data=model(), messages=[])
    repo = SimpleNamespace(get_by_id=AsyncMock(return_value=instance))
    with patch("src.api.versions.v1.routers.sessions.SessionRepository", return_value=repo):
        with pytest.raises(NotFoundException):
            await export_session_training_data("session", TrainingExportRequest(), SimpleNamespace(id="other"), None)
        response = await export_session_training_data("session", TrainingExportRequest(), SimpleNamespace(id="owner"), None)
        unpack(response.body)
        assert response.media_type == "application/zip"
        assert "Finite_service-training.zip" in response.headers["content-disposition"]
