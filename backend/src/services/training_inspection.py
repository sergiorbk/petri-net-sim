"""Read-only presentation and comparison of saved portable revisions."""
import json

from src.services.training_history import INDEX, digest, snapshot, revision_files
from src.services.petri.importer import parse_pnml


def inspect_bundle(files, revision_id=None):
    payload = revision_files(files, revision_id)
    net, warnings = parse_pnml(payload["model.pnml"].decode("utf-8"))
    geometry = json.loads(payload.get("model-geometry.json", b'{"elements":[]}'))
    mapping = {}
    transform = geometry.get("transform", {"origin_x": 0, "origin_y": 0, "scale": 1})
    from src.services.petri.exporter.geometry import PLACE_W, PLACE_H, TRANS_W, TRANS_H
    for kind, key, w, h in (("place", "places", PLACE_W, PLACE_H), ("transition", "transitions", TRANS_W, TRANS_H), ("object", "objects", 0, 0)):
        for item in net.get(key, []):
            candidates = [e for e in geometry["elements"] if e["kind"] == kind]
            direct = next((e for e in candidates if e["id"] == item["id"]), None)
            if direct:
                mapping[item["id"]] = direct["id"]
                continue
            g = item.get("graphics", {})
            x, y = g.get("x", 0) + g.get("width", w)/2, g.get("y", 0) + g.get("height", h)/2
            matches = [e for e in candidates if abs((e["bounds"]["x"]+e["bounds"]["width"]/2)/transform["scale"]+transform["origin_x"]-x)<.01
                       and abs((e["bounds"]["y"]+e["bounds"]["height"]/2)/transform["scale"]+transform["origin_y"]-y)<.01]
            if len(matches) == 1:
                mapping[item["id"]] = matches[0]["id"]
    return {"manifest": json.loads(files["manifest.json"]), "history": json.loads(files[INDEX]) if INDEX in files else {
        "schema_version": "1.0", "bundle_id": "", "head_revision_id": digest(snapshot(files)["manifest.json"]),
        "revisions": [{"id": digest(snapshot(files)["manifest.json"]), "parent_revision_id": "", "model_sha256": digest(files["model.pnml"])}], "reviews": []},
        "reviews": [json.loads(files["history/reviews/" + ref["id"] + ".json"]) for ref in json.loads(files.get(INDEX, b'{"reviews":[]}'))["reviews"]],
        "task": json.loads(payload.get("task.json", b"{}")), "net_data": net, "warnings": warnings,
        "revision_id": digest(payload["manifest.json"]), "network_views": json.loads(payload.get("network-views.json", b'{"views":[]}')),
        "geometry": geometry, "image_sha256": digest(payload["network.png"]) if "network.png" in payload else None,
        "source_element_map": mapping}


def compare_revisions(files, left, right, include_layout=False):
    import xml.etree.ElementTree as ET
    def elements(rid):
        root = ET.fromstring(revision_files(files, rid)["model.pnml"])
        result = {}
        for element in root.iter():
            kind = element.tag.rsplit("}", 1)[-1]
            identifier = element.get("id")
            if identifier and kind in {"place", "transition", "arc", "page", "referencePlace"}:
                fields = {}
                def walk(node, path):
                    tag = node.tag.rsplit("}", 1)[-1]
                    if not include_layout and tag in {"graphics", "position", "dimension"}:
                        return
                    key = path + "/" + tag
                    if node.text and node.text.strip():
                        fields[key] = node.text.strip()
                    for k, v in sorted(node.attrib.items()):
                        if not include_layout and tag == "petriObject" and k in {"x", "y", "width", "height", "collapsed", "autoFit"}:
                            continue
                        fields[key + "/@" + k] = v
                    for child in node:
                        if child.get("id") and child.tag.rsplit("}", 1)[-1] in {"place", "transition", "arc", "page", "referencePlace"}:
                            continue
                        walk(child, key)
                walk(element, "")
                name = next((v for k, v in fields.items() if k.endswith("/name/text")), identifier)
                result[identifier] = (kind, name, fields)
        return result
    before, after = elements(left), elements(right)
    changes = []
    for identifier in sorted(before.keys() | after.keys()):
        a, b = before.get(identifier), after.get(identifier)
        if a is None or b is None:
            item = b or a
            changes.append({"element_id": identifier, "name": item[1], "kind": item[0], "change": "added" if a is None else "removed"})
        else:
            for key in sorted(a[2].keys() | b[2].keys()):
                if a[2].get(key) != b[2].get(key):
                    changes.append({"element_id": identifier, "name": b[1], "kind": b[0], "change": "changed", "field": key, "before": a[2].get(key), "after": b[2].get(key)})
    return changes
