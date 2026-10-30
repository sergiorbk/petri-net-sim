"""Portable, task-scoped training bundles and deterministic network renders."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import zipfile
from datetime import datetime, timezone
from importlib.metadata import version
from urllib.parse import quote

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from petri_modeling_skills import read_schema
from PIL import Image, ImageDraw, ImageFont

from src.services.petri.session import PetriNetSession
from src.services.petri.exporter.geometry import PLACE_W, PLACE_H, TRANS_W, TRANS_H

_SECRET_KEYS = re.compile(r"^(authorization|api[_-]?key|(?:access|refresh|mcp|bearer)[_-]?token|token|password|secret|credentials?|environment|config)$", re.I)
_SECRET_TEXT = re.compile(r"(?i)(?:Bearer\s+\S+|sk-[\w-]{12,}|eyJ[\w-]+\.[\w-]+\.[\w-]+|(?:api[_-]?key|password|secret|(?:access|refresh|mcp|bearer)[_-]?token|\btoken)[\"']?\s*[:=]\s*[^\s,;]+)")


def sanitize(value):
    """Remove credential-shaped values while retaining domain token counts."""
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if _SECRET_KEYS.match(str(k)) else sanitize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[REDACTED]", value, flags=re.S)
        return _SECRET_TEXT.sub("[REDACTED]", value)
    return value


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def validate(value, definition=None):
    schema = read_schema("training-bundle")
    if isinstance(schema, str):
        schema = json.loads(schema)
    if definition:
        schema = {"$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"}
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except ValidationError as exc:
        raise ValueError("Invalid training export " + (definition or "manifest")) from exc


def filename(title, suffix):
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in title).strip("_")[:100] or "petri-session"
    return stem + suffix


def attachment(data, name, media_type):
    from fastapi import Response
    return Response(data, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename=petri-export{'.zip' if media_type == 'application/zip' else '.png'}; filename*=UTF-8''{quote(name)}",
    })


def encoded_download(data, name, media_type):
    return json.dumps({"filename": name, "media_type": media_type, "data_base64": base64.b64encode(data).decode("ascii")})


def _font(size):
    for path in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def render_network(net_data):
    """Render model coordinates, recording bounds from the same drawing operations.

    This is a network illustration, not a capture of the editor viewport.
    """
    nodes = list(net_data.get("places", [])) + list(net_data.get("transitions", []))
    if len(nodes) > 2000 or len(net_data.get("arcs", [])) > 5000:
        raise ValueError("Network image exceeds the rendering limit")
    ids = [n["id"] for n in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("Network image requires unique node identifiers")
    place_ids = {n["id"] for n in net_data.get("places", [])}
    positions = {}
    for frame in net_data.get("objects", []):
        frame_graphics = frame.get("graphics") or frame
        if any(not math.isfinite(float(frame_graphics.get(key, default))) for key, default in (("x", 0), ("y", 0), ("width", 160), ("height", 100))):
            raise ValueError("Network frame coordinates must be finite")
    for node in nodes:
        g = node.get("graphics") or {}
        x, y = float(g.get("x", 0)), float(g.get("y", 0))
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Network coordinates must be finite")
        positions[node["id"]] = (x, y, PLACE_W if node["id"] in place_ids else TRANS_W, PLACE_H if node["id"] in place_ids else TRANS_H)
    # Label measurement participates in the crop, so long labels are never silently lost.
    font = _font(14)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    boxes = list(positions.values())
    for node in nodes:
        x, y, w, h = positions[node["id"]]
        box = measure.textbbox((x, y + h + 4), str(node.get("name", node["id"])), font=font)
        boxes.append((box[0], box[1], box[2] - box[0], box[3] - box[1]))
    for frame in net_data.get("objects", []):
        boxes.append((float((frame.get("graphics") or frame).get("x", 0)), float((frame.get("graphics") or frame).get("y", 0)), float((frame.get("graphics") or frame).get("width", 160)), float((frame.get("graphics") or frame).get("height", 100))))
    ox = min((b[0] for b in boxes), default=0) - 24
    oy = min((b[1] for b in boxes), default=0) - 24
    width = max((b[0] + b[2] for b in boxes), default=100) - ox + 24
    height = max((b[1] + b[3] for b in boxes), default=100) - oy + 24
    if not math.isfinite(width) or not math.isfinite(height) or max(width, height) > 10_000_000:
        raise ValueError("Network coordinates exceed the rendering range")
    scale = min(1.0, 2048 / max(width, height))
    width, height = max(1, math.ceil(width * scale)), max(1, math.ceil(height * scale))
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _font(max(8, round(14 * scale)))
    elements = []

    def pixels(box):
        x, y, w, h = box
        return ((x-ox)*scale, (y-oy)*scale, (x+w-ox)*scale, (y+h-oy)*scale)

    def record(identifier, kind, box):
        x, y, r, b = box
        clipped = x < 0 or y < 0 or r > width or b > height
        elements.append({"id": str(identifier), "kind": kind, "bounds": {"x": max(0, x), "y": max(0, y), "width": max(0, min(width, r)-max(0, x)), "height": max(0, min(height, b)-max(0, y))}, "clipped": clipped})

    for frame in net_data.get("objects", []):
        box = pixels((float((frame.get("graphics") or frame).get("x", 0)), float((frame.get("graphics") or frame).get("y", 0)), float((frame.get("graphics") or frame).get("width", 160)), float((frame.get("graphics") or frame).get("height", 100))))
        draw.rectangle(box, outline="#a0a9b2", width=1)
        record(frame["id"], "object", box)
    for arc in list(net_data.get("arcs", [])) + list(net_data.get("links", [])):
        source, target = arc.get("source_id", arc.get("sourceId")), arc.get("target_id", arc.get("targetId"))
        if source not in positions or target not in positions:
            raise ValueError("Network image has an unresolved arc or link endpoint")
        a, b = positions[source], positions[target]
        x1, y1 = (a[0]+a[2]/2-ox)*scale, (a[1]+a[3]/2-oy)*scale
        x2, y2 = (b[0]+b[2]/2-ox)*scale, (b[1]+b[3]/2-oy)*scale
        is_fusion = arc.get("type") == "placeFusion"
        color = "#9333ea" if is_fusion else "#334155"
        draw.line((x1, y1, x2, y2), fill=color, width=2)
        # Arrowhead at the target footprint, rather than hidden at its center.
        angle = math.atan2(y2-y1, x2-x1)
        dx, dy = math.cos(angle), math.sin(angle)
        rx, ry = b[2] * scale / 2, b[3] * scale / 2
        if target in place_ids:
            distance = 1 / math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
        else:
            distance = min(rx / abs(dx) if abs(dx) > 1e-12 else math.inf,
                           ry / abs(dy) if abs(dy) > 1e-12 else math.inf)
        ax, ay = x2-distance*math.cos(angle), y2-distance*math.sin(angle)
        triangle = [(ax, ay), (ax-8*math.cos(angle-.5), ay-8*math.sin(angle-.5)), (ax-8*math.cos(angle+.5), ay-8*math.sin(angle+.5))]
        if not is_fusion:
            draw.polygon(triangle, fill=color)
        weight = arc.get("weight", arc.get("quantity", 1))
        raw_type = arc.get("arc_type", "normal")
        arc_type = str(getattr(raw_type, "value", raw_type)).lower()
        label = (str(weight) if weight != 1 else "") + (" [" + arc_type + "]" if arc_type != "normal" else "")
        if is_fusion:
            label = "fusion"
        if label:
            at = ((x1+x2)/2, (y1+y2)/2)
            draw.text(at, label, font=font, fill=color)
            record(arc["id"]+":label", "label", draw.textbbox(at, label, font=font))
        xs, ys = [x1, x2]+[p[0] for p in triangle], [y1, y2]+[p[1] for p in triangle]
        record(arc["id"], "arc", (min(xs)-1, min(ys)-1, max(xs)+1, max(ys)+1))
    for node in nodes:
        box = pixels(positions[node["id"]])
        is_place = node["id"] in place_ids
        (draw.ellipse if is_place else draw.rectangle)(box, fill="white" if is_place else "#dbeafe", outline="#172554", width=2)
        record(node["id"], "place" if is_place else "transition", box)
        if is_place and node.get("tokens", 0):
            text = str(node["tokens"])
            draw.text(((box[0]+box[2])/2, (box[1]+box[3])/2), text, anchor="mm", font=font, fill="#172554")
        text = str(node.get("name", node["id"]))
        at = (box[0], box[3]+4*scale)
        label_box = draw.textbbox(at, text, font=font)
        draw.text(at, text, font=font, fill="#172554")
        record(node["id"]+":label", "label", label_box)
    output = io.BytesIO()
    image.save(output, format="PNG")
    geometry = {"coordinate_system": "image-pixels", "image": {"file": "network.png", "width": width, "height": height}, "transform": {"origin_x": ox, "origin_y": oy, "scale": scale}, "label_status": "renderer-derived", "elements": elements}
    validate(geometry, "modelGeometry")
    return output.getvalue(), geometry


def build_training_bundle(net_data, title, *, context=None, conversation=None, tool_calls=None, conversation_origin="unavailable", tool_origin="unavailable", simulation=None):
    context = sanitize(context or {})
    clean_net = sanitize(net_data)
    title = sanitize(title or "Petri session")
    task = {key: context.get(key, default) for key, default in (("task", None), ("clarifications", []), ("assumptions", []), ("acceptance", []))}
    validate(task, "task")
    verification = context.get("verification", {"status": "unknown", "checks": [], "simulation": sanitize(simulation)})
    validate(verification, "verification")
    conversation = sanitize(conversation or [])
    tool_calls = sanitize(tool_calls or [])
    for record in conversation:
        validate(record, "conversationRecord")
    for record in tool_calls:
        if tool_origin == "client-provided":
            record["origin"] = "client-provided"
        validate(record, "toolCallRecord")
    artifacts = {
        "task.json": (json_bytes(task), "application/json", "Task and explicit acceptance criteria"),
        "model.pnml": (PetriNetSession.from_net_data(clean_net).export_pnml().encode("utf-8"), "application/xml", "Final model with graphics"),
        "conversation.jsonl": (b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8")+b"\n" for row in conversation), "application/x-ndjson", "Actual task conversation"),
        "tool-calls.jsonl": (b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8")+b"\n" for row in tool_calls), "application/x-ndjson", "Observed or explicitly supplied tool calls"),
        "verification.json": (json_bytes(verification), "application/json", "Verification evidence without inferred acceptance"),
    }
    missing = []
    if task["task"] is None:
        missing.append({"artifact": "task.json", "reason": "No explicit task description was supplied"})
    for artifact, rows in (("conversation.jsonl", conversation), ("tool-calls.jsonl", tool_calls)):
        if not rows:
            missing.append({"artifact": artifact, "reason": "No task-scoped records are available to this application"})
    if context.get("trace_truncated"):
        missing.append({"artifact": "tool-calls.jsonl", "reason": "Only the latest 200 calls of this live MCP session are retained"})
    if not simulation and verification.get("simulation") is None:
        missing.append({"artifact": "verification.json", "reason": "No recorded simulation result is available"})
    try:
        png, geometry = render_network(clean_net)
        artifacts["network.png"] = (png, "image/png", "Network-only illustration from model coordinates")
        artifacts["model-geometry.json"] = (json_bytes(geometry), "application/json", "Bounds from the same network renderer; not detection labels")
    except ValueError as exc:
        missing.append({"artifact": "network.png", "reason": str(exc)})
    manifest = {"schema_version": "1.0", "title": title, "created_at": utc_now(), "app": {"name": "petri-net-sim", "version": version("petri-net-sim")}, "shared_skills": {"version": version("petri-modeling-skills"), "revision": None}, "status": context.get("status", "unreviewed"), "capture_scope": {"conversation": conversation_origin if conversation else "unavailable", "tool_calls": tool_origin if tool_calls else "unavailable"}, "files": [{"name": name, "media_type": media, "sha256": hashlib.sha256(data).hexdigest(), "purpose": purpose} for name, (data, media, purpose) in artifacts.items()], "missing_data": missing}
    validate(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json_bytes(manifest))
        for name, (data, _, _) in artifacts.items():
            archive.writestr(name, data)
    return output.getvalue(), filename(title, "-training.zip")
