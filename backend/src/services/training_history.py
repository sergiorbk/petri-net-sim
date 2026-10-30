"""Portable desktop/web ZIP history. Preserve imported evidence byte for byte."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import re
import uuid
import zipfile

from PIL import Image
from jsonschema import Draft202012Validator, FormatChecker
from petri_modeling_skills import read_schema

INDEX = "dataset-history.json"
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_FILES = 10000
PURPOSE = "Training evidence and preserved revision history"


def packed(value):
    # Matches Jackson's compact UTF-8 serialization used by the desktop history.
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def media(name):
    return next((value for suffix, value in ((".png", "image/png"), (".pnml", "application/xml"),
                (".jsonl", "application/x-ndjson"), (".json", "application/json")) if name.endswith(suffix)), "application/octet-stream")


def listing(files):
    return [{"name": name, "sha256": digest(data), "media_type": media(name), "purpose": PURPOSE}
            for name, data in files.items() if name != "manifest.json"]


def snapshot(files):
    result = {name: files[name] for name in sorted(files) if name != INDEX and not name.startswith("history/")}
    manifest = json.loads(result["manifest.json"])
    manifest["files"] = listing(result)
    result["manifest.json"] = packed(manifest)
    return result


def safe_name(name):
    if (not name or name.startswith("/") or any(c in name for c in "\\:")
            or any(ord(c) < 32 for c in name) or any(p in ("", ".", "..") for p in name.split("/"))):
        raise ValueError("Unsafe training ZIP path")


def schema_check(value, name, definition=None):
    schema = read_schema(name)
    if isinstance(schema, str):
        schema = json.loads(schema)
    if definition:
        schema = {"$defs": schema["$defs"], "$ref": "#/$defs/" + definition}
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise ValueError("Invalid " + name + (" " + definition if definition else "") + ": " + errors[0].message[:180])


def read_bundle(data):
    if len(data) > MAX_TOTAL:
        raise ValueError("Training ZIP exceeds 256 MiB")
    files, total = {}, 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > MAX_FILES:
                raise ValueError("Training ZIP contains too many files")
            for entry in archive.infolist():
                safe_name(entry.filename.rstrip("/") if entry.is_dir() else entry.filename)
                if entry.is_dir():
                    continue
                if entry.filename in files or entry.file_size > MAX_FILE:
                    raise ValueError("Duplicate or oversized ZIP entry")
                with archive.open(entry) as source:
                    value = source.read(MAX_FILE + 1)
                total += len(value)
                if len(value) > MAX_FILE or total > MAX_TOTAL:
                    raise ValueError("Training ZIP exceeds the size limit")
                files[entry.filename] = value
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ValueError("Invalid training ZIP") from exc
    validate_files(files)
    return files


def validate_snapshot(files):
    if not {"manifest.json", "model.pnml"} <= files.keys():
        raise ValueError("Training ZIP requires manifest.json and model.pnml")
    manifest = json.loads(files["manifest.json"])
    schema_check(manifest, "training-bundle")
    named = [item["name"] for item in manifest["files"]]
    if len(set(named)) != len(named) or set(named) != files.keys() - {"manifest.json"}:
        raise ValueError("Training ZIP contains duplicate, missing or unlisted files")
    for item in manifest["files"]:
        if digest(files[item["name"]]) != item["sha256"]:
            raise ValueError("Training ZIP checksum mismatch: " + item["name"])
    for name, data in files.items():
        if name.endswith(".png"):
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or max(image.size) > 8192 or image.width * image.height > 24_000_000:
                    raise ValueError("Training image exceeds the rendering limit")
    return manifest


def revision_files(files, revision_id=None):
    if revision_id in (None, "loaded", "head"):
        return snapshot(files)
    if not re.fullmatch("[a-f0-9]{64}", revision_id):
        raise ValueError("Unknown revision")
    prefix = "history/revisions/" + revision_id + "/"
    result = {name[len(prefix):]: data for name, data in files.items() if name.startswith(prefix)}
    if not result:
        if INDEX not in files and digest(snapshot(files)["manifest.json"]) == revision_id:
            return snapshot(files)
        raise ValueError("Unknown revision")
    return result


def validate_targets(review, files):
    views = {v["id"]: v for v in json.loads(files.get("network-views.json", b'{"views":[]}'))["views"]}
    views.setdefault("main", {"image": "network.png", "geometry": "model-geometry.json"})
    all_ids = {e["id"] for e in json.loads(files.get("model-geometry.json", b'{"elements":[]}'))["elements"]}
    for finding in review["findings"]:
        view = views.get(finding.get("view_id", "main"))
        if not view or (finding.get("element_id") and finding["element_id"] not in all_ids):
            raise ValueError("Finding targets an unknown element or view")
        if finding.get("element_id"):
            visible = {e["id"] for e in json.loads(files.get(view["geometry"], b'{"elements":[]}'))["elements"]}
            if finding["element_id"] not in visible:
                raise ValueError("Finding element is not in the selected view")
        if region := finding.get("region"):
            image = files.get(view["image"], b"")
            if digest(image) != region["image_sha256"]:
                raise ValueError("Finding region targets a different image")
            with Image.open(io.BytesIO(image)) as png:
                if region["x"] + region["width"] > png.width + .001 or region["y"] + region["height"] > png.height + .001:
                    raise ValueError("Finding region extends outside its image")


def validate_files(files):
    validate_snapshot(files)
    if INDEX not in files:
        if any(name.startswith("history/") for name in files):
            raise ValueError("History index is missing")
        return
    index = json.loads(files[INDEX])
    schema_check(index, "training-history")
    previous, seen, known = "", set(), set()
    for ref in index["revisions"]:
        rid = ref["id"]
        if rid in seen or ref["parent_revision_id"] != previous:
            raise ValueError("Invalid revision chain")
        payload = revision_files(files, rid)
        if INDEX in payload or any(n.startswith("history/") for n in payload):
            raise ValueError("Recursive history is not supported")
        validate_snapshot(payload)
        if digest(payload["manifest.json"]) != rid or digest(payload["model.pnml"]) != ref["model_sha256"]:
            raise ValueError("Revision checksum mismatch")
        previous = rid
        seen.add(rid)
        known.add(ref["model_sha256"])
    if previous != index["head_revision_id"] or digest(snapshot(files)["manifest.json"]) != previous:
        raise ValueError("History head does not match current files")
    previous, reviewed = "", set()
    for ref in index["reviews"]:
        rid = ref["id"]
        data = files.get("history/reviews/" + rid + ".json", b"")
        if rid in reviewed or digest(data) != rid:
            raise ValueError("Review checksum mismatch")
        review = json.loads(data)
        schema_check(review, "training-history", "reviewRecord")
        if review["revision_id"] not in seen or review["result_revision_id"] not in seen or review["previous_review_id"] != previous:
            raise ValueError("Invalid review chain")
        target = revision_files(files, review["revision_id"])
        validate_targets(review, target)
        if simulation := review.get("simulation"):
            if simulation["source_model_sha256"] != digest(target["model.pnml"]):
                raise ValueError("Simulation targets a different model")
            for group in ("automatic_runs", "interactive_runs"):
                for run in simulation[group]:
                    if run["source_model_sha256"] not in known or (group == "automatic_runs" and run["source_model_sha256"] != simulation["source_model_sha256"]):
                        raise ValueError("Simulation targets an unknown model")
                    trajectory = run["trajectory"]
                    last = -1
                    if len(trajectory["samples"]) > 20001:
                        raise ValueError("Too many simulation samples")
                    for row in trajectory["samples"]:
                        if len(row) != len(trajectory["columns"]) + 1 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in row) or row[0] < last:
                            raise ValueError("Invalid simulation samples")
                        last = row[0]
        previous = rid
        reviewed.add(rid)


def encode_bundle(files):
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_TOTAL or any(len(v) > MAX_FILE for v in files.values()):
        raise ValueError("Dataset history exceeds the ZIP size/file limit")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


def append_history(fresh, old=None, review=None):
    output = dict(fresh)
    index = copy.deepcopy(json.loads(old[INDEX])) if old and INDEX in old else {
        "schema_version": "1.0", "bundle_id": str(uuid.uuid4()), "revisions": [], "reviews": [], "head_revision_id": ""}
    if old:
        output.update({n: v for n, v in old.items() if n.startswith("history/")})

    def append(payload):
        rid = digest(payload["manifest.json"])
        if rid == index["head_revision_id"]:
            return rid
        if rid in {r["id"] for r in index["revisions"]}:
            raise ValueError("Cannot append a previous revision as a new head")
        output.update({"history/revisions/" + rid + "/" + n: v for n, v in payload.items()})
        index["revisions"].append({"id": rid, "parent_revision_id": index["head_revision_id"], "model_sha256": digest(payload["model.pnml"])})
        index["head_revision_id"] = rid
        return rid

    loaded_id = append(snapshot(old)) if old else None
    head = append(snapshot(fresh))
    if review is not None:
        review = dict(review)
        target = review.get("revision_id")
        review["revision_id"] = head if target == "current" or not old else loaded_id if target in (None, "head", "loaded") else target
        review["result_revision_id"] = head
        review["previous_review_id"] = index["reviews"][-1]["id"] if index["reviews"] else ""
        payload = revision_files(output, review["revision_id"])
        validate_targets(review, payload)
        schema_check(review, "training-history", "reviewRecord")
        value = packed(review)
        rid = digest(value)
        output["history/reviews/" + rid + ".json"] = value
        index["reviews"].append({"id": rid})
    output[INDEX] = packed(index)
    manifest = json.loads(fresh["manifest.json"])
    manifest["files"] = listing(output)
    output["manifest.json"] = packed(manifest)
    validate_files(output)
    return output
