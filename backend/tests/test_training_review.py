"""Portable review round trips, exact-version evidence and hostile ZIP rejection."""
import base64
import copy
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from src.services.training_export import build_training_bundle, _build_snapshot
from src.services.training_history import read_bundle, digest, snapshot, packed, encode_bundle, listing
from src.services.training_history import safe_name
from src.services.training_inspection import inspect_bundle, compare_revisions
from src.services.training_images import export_images
from src.services.training_simulation import run_evidence
from src.services.petri.agent_toolkit import build_catalog, ToolError
from src.services.petri.session import PetriNetSession
from src.api.versions.v1.routers.training import ArchiveBody, ExportBody, inspect, export


def net():
    return {"name": "Черга заявок", "places": [
        {"id": "p1", "name": "Джерело", "tokens": 6, "graphics": {"x": 0, "y": 0}},
        {"id": "p2", "name": "Виконано", "tokens": 0, "graphics": {"x": 400, "y": 0}}],
        "transitions": [{"id": "t1", "name": "Обслуговування", "mean_delay": 2, "distribution": "det", "priority": 0,
                         "standard_deviation": 0, "probability": 1, "graphics": {"x": 200, "y": 0}}],
        "arcs": [{"id": "a1", "source_id": "p1", "target_id": "t1", "weight": 1, "arc_type": "NORMAL"},
                 {"id": "a2", "source_id": "t1", "target_id": "p2", "weight": 1, "arc_type": "NORMAL"}]}


def review(**kwargs):
    return {"reviewer": "Рецензент", "reviewer_kind": "human", "decision": "changes_requested", "comment": "Перевірено",
            "findings": [], "simulation_horizons": [10], **kwargs}


def record(files):
    index = json.loads(files["dataset-history.json"])
    return json.loads(files["history/reviews/" + index["reviews"][-1]["id"] + ".json"])


def test_history_keeps_every_original_payload_and_targets_loaded_model():
    first, name = build_training_bundle(net(), "Черга", context={"task": "Обробити заявки"}, conversation=[{"role": "user", "content": "Шість заявок"}], conversation_origin="client-provided")
    f1 = read_bundle(first)
    changed = net()
    changed["places"][0]["tokens"] = 3
    second, name = build_training_bundle(changed, "Черга", archive=first, review=review(findings=[{"severity": "warning", "message": "Потрібна перевірка", "element_id": "p1", "view_id": "main"}]))
    f2 = read_bundle(second)
    assert "r002-review001" in name
    for key, value in f1.items():
        if key.startswith("history/"):
            assert f2[key] == value
    r = record(f2)
    assert r["revision_id"] == json.loads(f1["dataset-history.json"])["head_revision_id"]
    assert r["revision_id"] != r["result_revision_id"]
    assert r["simulation"]["source_model_sha256"] == digest(f1["model.pnml"])
    assert r["simulation"]["automatic_runs"][0]["status"] == "completed"
    assert json.loads(f2["task.json"])["task"] == "Обробити заявки"
    assert b"user" in f2["conversation.jsonl"]
    third, _ = build_training_bundle(changed, "Черга", archive=second, review=review(reviewer_kind="agent", decision="accepted"))
    f3 = read_bundle(third)
    for key, value in f2.items():
        if key.startswith("history/"):
            assert f3[key] == value
    assert len(json.loads(f3["dataset-history.json"])["reviews"]) == 2
    assert json.loads(f3["verification.json"])["status"] == "unknown"


def test_legacy_snapshot_acquires_history_without_losing_original():
    old, _ = _build_snapshot(net(), "Legacy")
    before = read_bundle(old)
    rid = digest(snapshot(before)["manifest.json"])
    new, _ = build_training_bundle(net(), "Legacy", archive=old, review=review(revision_id=rid))
    files = read_bundle(new)
    assert record(files)["revision_id"] == rid
    assert files["history/revisions/" + rid + "/model.pnml"] == before["model.pnml"]


@pytest.mark.parametrize("options", [{"simulation_horizons": []}, {"simulation_horizons": [], "skip_simulation_reason": "  "}, {"sampling_interval": 0}, {"simulation_horizons": [float("inf")]}])
def test_review_requires_valid_run_plan_or_reason(options):
    with pytest.raises(ValueError):
        build_training_bundle(net(), "Invalid", review=review(**options))


def test_skip_reason_and_exact_image_region_are_preserved():
    first, _ = build_training_bundle(net(), "Test")
    files = read_bundle(first)
    region = {"coordinate_system": "image-pixels", "image_sha256": digest(files["network.png"]), "x": 0, "y": 0, "width": 20, "height": 20}
    result, _ = build_training_bundle(net(), "Test", archive=first, review=review(simulation_horizons=[], skip_simulation_reason="Перевіряється структура", findings=[{"severity": "suggestion", "message": "Пояснити область", "view_id": "main", "region": region}]))
    r = record(read_bundle(result))
    assert r["findings"][0]["region"] == region
    assert r["simulation"]["automatic_runs"] == []
    assert r["simulation"]["skip_reason"] == "Перевіряється структура"
    with pytest.raises(ValueError, match="different image"):
        build_training_bundle(net(), "Test", archive=first, review=review(findings=[{"severity": "error", "message": "Wrong", "view_id": "main", "region": {**region, "image_sha256": "f"*64}}]))


def test_time_series_holds_post_event_state_at_each_unit():
    data, _ = build_training_bundle(net(), "Series")
    run = run_evidence(read_bundle(data)["model.pnml"], 5)
    assert run["status"] == "completed", run["error"]
    series = run["trajectory"]
    assert [r[0] for r in series["samples"]] == [0, 1, 2, 3, 4, 5]
    index = next(i for i, c in enumerate(series["columns"]) if c["id"] == "p2") + 1
    assert [r[index] for r in series["samples"]] == [0, 0, 6, 6, 6, 6]
    assert series["complete"]


def test_desktop_omitted_distribution_remains_deterministic():
    from src.services.petri.importer import parse_pnml
    xml = '<pnml><net id="n"><page id="page"><transition id="t"><toolspecific tool="PetriObjModel" version="2.5.0"><timeDelay>5</timeDelay></toolspecific></transition></page></net></pnml>'
    model, warnings = parse_pnml(xml)
    assert not warnings
    assert model["transitions"][0]["distribution"] == "det"
    assert model["transitions"][0]["mean_delay"] == 5
    assert model["transitions"][0]["priority"] == 0


def test_failed_simulation_is_recorded_and_does_not_claim_success():
    model = net()
    model["arcs"] = [model["arcs"][1]]
    data, _ = build_training_bundle(model, "Unbounded", review=review())
    run = record(read_bundle(data))["simulation"]["automatic_runs"][0]
    assert run["status"] == "failed"
    assert run["trajectory"]["complete"] is False


def test_nested_images_and_standalone_selection_include_every_depth():
    model = net()
    model["objects"] = [{"id": "outer", "name": "Система", "priority": 0, "collapsed": True, "graphics": {"x": 0, "y": 0, "width": 20, "height": 20}},
                        {"id": "inner", "name": "Модуль", "priority": 1, "objectId": "outer", "graphics": {"x": 50, "y": 50, "width": 50, "height": 50}}]
    for key in ("places", "transitions"):
        for item in model[key]:
            item["objectId"] = "inner"
    before = copy.deepcopy(model)
    data, _ = build_training_bundle(model, "Nested")
    files = read_bundle(data)
    views = json.loads(files["network-views.json"])["views"]
    assert len(views) == 3
    for v in views:
        assert files[v["image"]].startswith(b"\x89PNG")
        geometry = json.loads(files[v["geometry"]])
        assert geometry["parameter_table_visible"]
        assert {"p1", "p2", "t1"} <= {e["id"] for e in geometry["elements"]}
    image, media, suffix = export_images(model, {"scope": "objects", "format": "zip", "include_overview": False, "object_indices": [1], "transparent_background": True, "include_parameters": True, "scale": 2})
    z = zipfile.ZipFile(io.BytesIO(image))
    assert set(z.namelist()) == {"object-0001.png", "images.json"}
    selected, _, _ = export_images(model, {"scope": "selection", "element_ids": ["p1", "t1"], "format": "zip"})
    geometry = json.loads(zipfile.ZipFile(io.BytesIO(selected)).read("images.json"))["views"][0]["geometry"]
    assert {"p1", "t1", "a1"} <= {e["id"] for e in geometry["elements"]}
    assert "p2" not in {e["id"] for e in geometry["elements"]}
    assert model == before
    active, _, _ = export_images(model, {"scope": "active", "format": "zip"})
    active_geometry = json.loads(zipfile.ZipFile(io.BytesIO(active)).read("images.json"))["views"][0]["geometry"]
    assert {e["id"] for e in active_geometry["elements"]} == {"outer"}
    arc, _, _ = export_images(model, {"scope": "selection", "element_ids": ["a1"], "format": "zip"})
    arc_geometry = json.loads(zipfile.ZipFile(io.BytesIO(arc)).read("images.json"))["views"][0]["geometry"]
    assert {"p1", "t1", "a1"} <= {e["id"] for e in arc_geometry["elements"]}


@pytest.mark.parametrize("entry", ["../model.pnml", "/bad", "C:/bad", "a\\b"])
def test_unsafe_paths_never_extract(entry):
    with pytest.raises(ValueError, match="Unsafe"):
        safe_name(entry)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr(entry, b"x")
    with pytest.raises(ValueError):
        read_bundle(data.getvalue())


def test_corruption_is_rejected_even_with_root_manifest_rehashed():
    data, _ = build_training_bundle(net(), "Original", review=review())
    files = read_bundle(data)
    path = next(n for n in files if n.startswith("history/revisions/") and n.endswith("model.pnml"))
    files[path] += b" "
    manifest = json.loads(files["manifest.json"])
    manifest["files"] = listing(files)
    files["manifest.json"] = packed(manifest)
    with pytest.raises(ValueError, match="checksum"):
        read_bundle(encode_bundle(files))


def test_mcp_continues_same_zip_and_invalid_open_leaves_model_unchanged():
    data, _ = build_training_bundle(net(), "Original")
    session = PetriNetSession()
    catalog = build_catalog()
    opened = catalog["open_training_bundle"].operation(session, archive_base64=base64.b64encode(data).decode())
    assert not isinstance(opened, ToolError)
    run = catalog["run_training_simulation"].operation(session, horizon=5)
    assert json.loads(run)["status"] == "completed"
    before = session.to_net_data()
    failed = catalog["open_training_bundle"].operation(session, archive_base64="broken", replace_current=True)
    assert isinstance(failed, ToolError)
    assert session.to_net_data() == before
    exported = catalog["export_training_review"].operation(session, reviewer="Review agent", decision="accepted", comment="Checked", simulation_horizons=[5])
    result = json.loads(exported)
    files = read_bundle(base64.b64decode(result["data_base64"]))
    assert record(files)["reviewer_kind"] == "agent"
    assert record(files)["simulation"]["automatic_runs"][0]["status"] == "completed"
    assert len(record(files)["simulation"]["interactive_runs"]) == 1


async def test_web_forces_human_attribution_and_does_not_accept_spoofed_reviewer():
    user = SimpleNamespace(id="test-user", metadata_={"contributor": {"nickname": "Рецензент", "group": "ІС-21"}})
    response = await export(ExportBody(net_data=net(), review=review(reviewer="Impersonated", reviewer_kind="agent")), user)
    files = read_bundle(response.body)
    assert record(files)["reviewer"] == "Рецензент"
    assert record(files)["reviewer_kind"] == "human"
    assert record(files)["submitted_by"]["group"] == "ІС-21"
    info = await inspect(ArchiveBody(archive_base64=base64.b64encode(response.body).decode()), user)
    assert info["net_data"]["name"] == "Черга заявок"
