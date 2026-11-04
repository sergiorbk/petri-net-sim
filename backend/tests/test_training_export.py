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
    assert name.startswith("Finite___service-r001-review000-") and name.endswith(".zip")
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
    assert "Finite_service-r001-review000-" in response.headers["content-disposition"]


@pytest.mark.parametrize("above", [True, False])
def test_vertical_transition_arrowhead_remains_visible_outside_target(above):
    net = PetriNet(name="Vertical arc")
    source = net.add_place("Source", x=0, y=0 if above else 360)
    target = net.add_transition("", x=14, y=180)
    net.add_arc(source.id, target.id)
    data, geometry = render_network(net.model_dump())
    image = Image.open(io.BytesIO(data))
    box = next(row["bounds"] for row in geometry["elements"] if row["id"] == target.id)
    center_x = round(box["x"] + box["width"] / 2)
    outside_y = round(box["y"] - 5 if above else box["y"] + box["height"] + 5)
    # A shaft alone is two pixels wide. Both wings must survive the later
    # filled-node drawing at the actual rectangular boundary.
    assert image.getpixel((center_x - 2, outside_y)) == (51, 65, 85)
    assert image.getpixel((center_x + 2, outside_y)) == (51, 65, 85)


def test_opaque_structured_access_tokens_are_redacted_but_markings_remain():
    opaque = "qP7Va3zxN1rM9bDtL5wH0sK6cJ2uF8eR4yA0oG9nBvX"
    calls = [{"tool": "request", "arguments": {"token": opaque, "mcp_token": opaque,
              "bearer_token": opaque, "nested": {"TOKEN": opaque}, "tokens": 6},
              "timestamp": "2026-10-30T00:00:00Z", "origin": "client-provided"}]
    conversation = [{"role": "user", "content": "6 tokens. " + " ".join(
        f'{key}={opaque}; "{key}": "{opaque}";' for key in ("token", "mcp_token", "bearer_token", "refresh_token")
    )}]
    data, _ = build_training_bundle(model(), "Token redaction", tool_calls=calls, tool_origin="client-provided",
                                    conversation=conversation, conversation_origin="client-provided")
    archive, _ = unpack(data)
    for name in archive.namelist():
        assert opaque.encode() not in archive.read(name)
    arguments = json.loads(archive.read("tool-calls.jsonl"))["arguments"]
    assert b"6 tokens" in archive.read("conversation.jsonl")
    assert arguments["tokens"] == 6
    assert arguments["token"] == arguments["mcp_token"] == arguments["bearer_token"] == "[REDACTED]"


class TestAutomaticSimulationInTrainingExport:
    """A training ZIP is the review ZIP without the review: it carries the
    review flow's own automatic simulation attempts, produced by the same
    runner (`simulation_evidence`), so a reader gets evidence about the model
    without anybody having to run an iterative review first."""

    def _verification(self, data):
        archive, manifest = unpack(data)
        return archive, manifest, json.loads(archive.read("verification.json"))

    def test_off_by_default_so_existing_exports_are_unchanged(self):
        data, _ = build_training_bundle(model(), "Finite service")
        _, _, verification = self._verification(data)
        assert verification["simulation"] is None

    def test_runs_the_review_defaults_against_the_exported_model(self):
        data, _ = build_training_bundle(model(), "Finite service", simulate=True)
        archive, manifest, verification = self._verification(data)

        runs = verification["simulation"]["results"]["automatic_runs"]
        assert [run["horizon"] for run in runs] == [100, 1000, 10000]
        pnml_hash = hashlib.sha256(archive.read("model.pnml")).hexdigest()
        assert {run["source_model_sha256"] for run in runs} == {pnml_hash}
        assert all(run["trajectory"]["samples"] for run in runs)
        assert verification["simulation"]["parameters"]["automatic_horizons"] == [100, 1000, 10000]
        assert "review" in verification["simulation"]["provenance"]
        assert not any(row["artifact"] == "verification.json" for row in manifest["missing_data"])

    def test_the_runs_are_the_review_runners_output_not_a_second_implementation(self):
        from src.services.training_simulation import simulation_evidence

        data, _ = build_training_bundle(model(), "Finite service", simulate=True)
        archive, _, verification = self._verification(data)
        reference = simulation_evidence(archive.read("model.pnml"), {})["automatic_runs"]
        exported = verification["simulation"]["results"]["automatic_runs"]

        def shape(run):
            return {key: (type(value).__name__) for key, value in run.items()}

        assert [shape(r) for r in exported] == [shape(r) for r in reference]
        assert [r["status"] for r in exported] == [r["status"] for r in reference]
        assert [r["final_state"] for r in exported] == [r["final_state"] for r in reference]

    def test_stays_an_unreviewed_export_with_no_review_record(self):
        data, _ = build_training_bundle(model(), "Finite service", simulate=True)
        archive, manifest, _ = self._verification(data)
        assert manifest["status"] == "unreviewed"
        assert not [n for n in archive.namelist() if n.startswith("history/reviews/")]
        history = json.loads(archive.read("dataset-history.json"))
        assert history["reviews"] == []

    def test_keeps_what_the_caller_already_observed(self):
        observed = {"parameters": {"simulation_time": 50, "time_unit": "s"},
                    "results": {"summary": "seen by the agent"},
                    "provenance": "application: last observed simulation result"}
        data, _ = build_training_bundle(model(), "Finite service", simulation=observed, simulate=True)
        _, _, verification = self._verification(data)
        simulation = verification["simulation"]
        assert simulation["results"]["summary"] == "seen by the agent"
        assert simulation["parameters"]["simulation_time"] == 50
        assert len(simulation["results"]["automatic_runs"]) == 3
        assert simulation["provenance"].startswith("application: last observed simulation result")

    def test_an_explicit_verification_in_the_context_wins_and_no_runs_are_wasted(self):
        context = {"verification": {"status": "unknown", "checks": [], "simulation": None}}
        data, _ = build_training_bundle(model(), "Finite service", context=context, simulate=True)
        _, _, verification = self._verification(data)
        assert verification["simulation"] is None

    def test_an_empty_model_is_not_simulated_and_still_exports(self):
        empty = PetriNet(name="Empty").model_dump()
        data, _ = build_training_bundle(empty, "Empty", simulate=True)
        _, _, verification = self._verification(data)
        assert verification["simulation"] is None

    async def test_the_web_export_runs_them_only_when_asked(self):
        from src.api.versions.v1.routers.training import ExportBody, export

        user = SimpleNamespace(id="u1", metadata_={})
        plain = await export(ExportBody(net_data=model()), user)
        asked = await export(ExportBody(net_data=model(), include_simulation=True), user)
        assert json.loads(zipfile.ZipFile(io.BytesIO(plain.body)).read("verification.json"))["simulation"] is None
        simulation = json.loads(zipfile.ZipFile(io.BytesIO(asked.body)).read("verification.json"))["simulation"]
        assert len(simulation["results"]["automatic_runs"]) == 3

    async def test_a_review_request_does_not_also_run_the_export_defaults(self):
        """The review runs the attempts the reviewer chose, and only those."""
        from src.api.versions.v1.routers.training import ExportBody, export

        user = SimpleNamespace(id="u1", metadata_={})
        review = {"revision_id": "current", "decision": "accepted", "comment": "ok", "findings": [],
                  "simulation_horizons": [5], "sampling_interval": 1, "skip_simulation_reason": "", "interactive_runs": []}
        response = await export(ExportBody(net_data=model(), review=review, include_simulation=True), user)
        files = zipfile.ZipFile(io.BytesIO(response.body))
        assert json.loads(files.read("verification.json"))["simulation"] is None

    async def test_the_chat_download_carries_them_too(self):
        instance = SimpleNamespace(user_id="owner", title="Finite service", net_data=model(), messages=[])
        repo = SimpleNamespace(get_by_id=AsyncMock(return_value=instance))
        with patch("src.api.versions.v1.routers.sessions.SessionRepository", return_value=repo):
            response = await export_session_training_data("session", TrainingExportRequest(), SimpleNamespace(id="owner", metadata_={}), None)
        simulation = json.loads(zipfile.ZipFile(io.BytesIO(response.body)).read("verification.json"))["simulation"]
        assert len(simulation["results"]["automatic_runs"]) == 3

    async def test_the_mcp_export_carries_them_too(self):
        ctx = MagicMock()
        ctx.session = object()
        ctx.request_context.lifespan_context.session_store = SessionStore()
        catalog = build_catalog()
        await _build_tool_fn(catalog["create_network"])(ctx=ctx, name="Finite service")
        await _build_tool_fn(catalog["add_place"])(ctx=ctx, name="Source", tokens=6)
        result = json.loads(await _build_tool_fn(catalog["export_training_data"])(ctx=ctx, title="Finite service"))
        archive, _ = unpack(base64.b64decode(result["data_base64"]))
        simulation = json.loads(archive.read("verification.json"))["simulation"]
        assert simulation is not None and "automatic_runs" in simulation["results"]
