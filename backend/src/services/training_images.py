"""Shared view selection for standalone images and complete training snapshots."""
import copy


def expanded_network(net):
    if sum(len(net.get(key, [])) for key in ("places", "transitions", "objects")) > 2000:
        raise ValueError("Network image exceeds the rendering limit")
    result = copy.deepcopy(net)
    frames = {o["id"]: o for o in result.get("objects", [])}
    def depth(frame):
        seen = set()
        while frame.get("objectId") in frames:
            if frame["id"] in seen:
                raise ValueError("Cyclic object hierarchy")
            seen.add(frame["id"])
            frame = frames[frame["objectId"]]
        return len(seen)
    for frame in sorted(frames.values(), key=depth, reverse=True):
        members = [e for e in [*result.get("places", []), *result.get("transitions", []), *frames.values()] if e.get("objectId") == frame["id"]]
        if members:
            boxes = [(e.get("graphics") or {}) for e in members]
            x = min(b.get("x", 0) for b in boxes) - 30
            y = min(b.get("y", 0) for b in boxes) - 45
            right = max(b.get("x", 0) + b.get("width", 50) for b in boxes) + 50
            bottom = max(b.get("y", 0) + b.get("height", 50) for b in boxes) + 50
            frame["graphics"] = {"x": x, "y": y, "width": right-x, "height": bottom-y}
        frame["collapsed"] = False
    return result


def subset(net, ids):
    result = {"name": net.get("name", "Network")}
    result.update({key: [copy.deepcopy(e) for e in net.get(key, []) if e["id"] in ids] for key in ("places", "transitions", "objects")})
    nodes = {e["id"] for e in [*result["places"], *result["transitions"]]}
    result["arcs"] = [copy.deepcopy(a) for a in net.get("arcs", []) if a["source_id"] in nodes and a["target_id"] in nodes]
    result["links"] = [copy.deepcopy(a) for a in net.get("links", []) if a["sourceId"] in nodes and a["targetId"] in nodes]
    return result


def object_ids(net, root):
    ids = {root}
    entries = [*net.get("objects", []), *net.get("places", []), *net.get("transitions", [])]
    for _ in range(len(net.get("objects", [])) + 1):
        larger = ids | {e["id"] for e in entries if e.get("objectId") in ids}
        if larger == ids:
            break
        ids = larger
    return ids


def network_views(net):
    expanded = expanded_network(net)
    indices = {obj["id"]: i for i, obj in enumerate(net.get("objects", []))}
    for i, obj in enumerate(net.get("objects", [])):
        vid = f"object-{i:04d}"
        yield {"id": vid, "name": obj.get("name", obj["id"]), "object_index": i,
               "parent_id": "main" if obj.get("objectId") not in indices else f'object-{indices[obj["objectId"]]:04d}',
               "image": "networks/" + vid + ".png", "geometry": "networks/" + vid + "-geometry.json", "scope": "object-subtree-expanded"}, subset(expanded, object_ids(expanded, obj["id"]))


def export_images(net, options=None):
    from src.services.training_export import render_network, json_bytes
    options = dict(options or {})
    scope = options.pop("scope", "document")
    selected = options.pop("element_ids", [])
    objects = options.pop("object_indices", None)
    overview = options.pop("include_overview", True)
    output_format = options.pop("format", "png")
    if output_format not in {"png", "zip"}:
        raise ValueError("Image format must be PNG or ZIP")
    as_zip = output_format == "zip"
    if set(options) - {"scale", "max_dimension", "transparent_background", "include_parameters"}:
        raise ValueError("Unknown image option")
    for key in ("transparent_background", "include_parameters"):
        if key in options and type(options[key]) is not bool:
            raise ValueError("Image switches must be boolean")
    if type(overview) is not bool or not isinstance(selected, list) or any(not isinstance(i, str) for i in selected):
        raise ValueError("Invalid view selection")
    if scope not in {"document", "active", "objects", "selection"}:
        raise ValueError("Unknown image scope")
    views = [("network", expanded_network(net))]
    if scope == "active":
        hidden = set()
        for frame in net.get("objects", []):
            if frame.get("collapsed"):
                hidden |= object_ids(net, frame["id"]) - {frame["id"]}
        visible = {e["id"] for key in ("places", "transitions", "objects") for e in net.get(key, [])} - hidden
        views = [("network", subset(net, visible))]
    if scope == "objects":
        count = len(net.get("objects", []))
        if objects is not None and any(type(i) is not int or i < 0 or i >= count for i in objects):
            raise ValueError("Unknown object index")
        views = (views if overview else []) + [(v["id"], model) for i, (v, model) in enumerate(network_views(net)) if objects is None or i in objects]
    elif scope == "selection":
        if not selected:
            raise ValueError("Select elements before exporting")
        ids = set(selected)
        for arc in net.get("arcs", []):
            if arc["id"] in ids:
                ids.remove(arc["id"])
                ids.update([arc["source_id"], arc["target_id"]])
        for link in net.get("links", []):
            if link["id"] in ids:
                ids.remove(link["id"])
                ids.update([link["sourceId"], link["targetId"]])
        for obj in net.get("objects", []):
            if obj["id"] in ids:
                ids |= object_ids(net, obj["id"])
        known = {e["id"] for key in ("places", "transitions", "objects") for e in net.get(key, [])}
        if not ids <= known:
            raise ValueError("Unknown selected element")
        views = [("selection", subset(expanded_network(net), ids))]
    if not views or (not as_zip and len(views) != 1):
        raise ValueError("Use ZIP for multiple image views")
    files, metadata = {}, []
    for name, model in views:
        png, geometry = render_network(model, **options)
        geometry["image"]["file"] = name + ".png"
        files[name + ".png"] = png
        metadata.append({"id": name, "geometry": geometry})
        if sum(map(len, files.values())) > 256 * 1024 * 1024:
            raise ValueError("Image archive exceeds the size limit")
    if not as_zip:
        return next(iter(files.values())), "image/png", ".png"
    files["images.json"] = json_bytes({"views": metadata})
    from src.services.training_history import encode_bundle
    return encode_bundle(files), "application/zip", ".zip"
