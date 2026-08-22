"""Pattern-aware hierarchical layout for Petri nets.

Pipeline (when ``pattern_instances`` is provided):

  1. Cluster map        — each node assigned to a pattern cluster or ``__raw``.
                          Single-input/single-output bridge transitions between
                          different patterns are detached and placed in a
                          post-pass instead of being lumped into ``__raw``.
  2. Intra-cluster      — for each cluster, identify "side" places (initial-
     layout                marked recycling/resource places) and pin them to
                          their gating transition. Remaining nodes go through
                          a deterministic bipartite mini-Sugiyama keyed off
                          the cluster's interface (input → ... → output).
  3. Super-graph        — clusters as super-nodes, super-edges from inter-
                          cluster arcs. DFS cycle reversal on the super graph.
  4. Layer assignment   — longest-path **from sinks** so terminators always
                          land in the highest x (LR) / y (TB) layer.
  5. Crossing minim.    — barycentric sort (4 sweeps) on super-graph ordering.
  6. Coordinate         — clusters placed in super-grid with explicit gutters.
     emission             Intra-cluster local coords are translated.
  7. Bridge placement   — transfer transitions placed midpoint between their
                          source-cluster right edge and target-cluster left
                          edge (LR), or between top/bottom (TB).
  8. Determinism        — every sort key is stable and content-derived.

When ``pattern_instances`` is empty the algorithm falls back to the original
flat Sugiyama, preserving backward compatibility for low-level-tool sessions.

Returned coordinates are top-left corners of node bounding boxes, matching
the frontend PlaceNode / TransitionNode convention.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from src.domain.models.net import PetriNet

# ── Node dimensions — must match frontend CSS ─────────────────────────────────
PLACE_W: float = 56.0
PLACE_H: float = 56.0
TRANS_W: float = 28.0
TRANS_H: float = 64.0

# ── Spacing ───────────────────────────────────────────────────────────────────
GRID_UNIT: float = 12.0
NODE_GAP: float = 36.0     # gap between consecutive nodes within the same layer
LAYER_GAP: float = 140.0   # gap between successive layers within a cluster
CLUSTER_GAP: float = 80.0  # gap between sibling clusters in the same super-layer
LAYER_GUTTER: float = 180.0  # gap between super-layers
MARGIN: float = 80.0       # outer canvas margin on both axes
#: Vertical room a node's caption takes up directly below its box. Mirrors
#: NODE_LABEL_H in services/petri/exporter/geometry.py and the frontend's
#: petri-geometry.ts. Layout has to reserve it: a caption drawn over the
#: node below it is as unreadable as two overlapping nodes.
LABEL_H: float = 26.0
#: Smallest separation left between a bridge transition and anything else,
#: caption bands included. Small on purpose -- a bridge belongs in the
#: middle of the edge it sits on, so it is nudged only as far as it must be.
BRIDGE_CLEARANCE: float = GRID_UNIT

RAW_CLUSTER = "__raw"


# ── Internal node representation ─────────────────────────────────────────────

@dataclass
class _Node:
    nid: str
    is_place: bool = True
    is_dummy: bool = False
    layer: int = 0
    tokens: int = 0

    @property
    def w(self) -> float:
        return 0.0 if self.is_dummy else (PLACE_W if self.is_place else TRANS_W)

    @property
    def h(self) -> float:
        return 0.0 if self.is_dummy else (PLACE_H if self.is_place else TRANS_H)


@dataclass
class _Cluster:
    """One pattern instance (or the __raw pseudo-cluster)."""
    name: str
    type: str
    place_ids: list[str] = field(default_factory=list)
    transition_ids: list[str] = field(default_factory=list)
    input_place_id: str | None = None
    output_place_id: str | None = None
    metadata: dict = field(default_factory=dict)
    # Filled by _layout_cluster:
    local_coords: dict[str, tuple[float, float]] = field(default_factory=dict)
    width: float = 0.0
    height: float = 0.0
    # Filled by super-graph layout:
    origin_x: float = 0.0
    origin_y: float = 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def layout(
    net: "PetriNet",
    direction: str = "LR",
    pattern_instances: dict[str, dict] | None = None,
) -> list[dict]:
    """Compute layout and return top-left coordinates per node."""
    result = _run(net, direction=direction, pattern_instances=pattern_instances)
    return result["positions"]


def layout_stats(
    net: "PetriNet",
    direction: str = "LR",
    pattern_instances: dict[str, dict] | None = None,
) -> dict:
    """Compute layout and return positions plus metadata.

    Keys:
      - positions: list[{id, x, y}]
      - layer_count: int (super-layer count when clustered, flat layer count
                     otherwise)
      - element_count: int
      - cluster_bounds: dict[str, {x, y, width, height, type}] — used for
                       frontend group rendering.
    """
    return _run(net, direction=direction, pattern_instances=pattern_instances)


# ── Top-level dispatcher ──────────────────────────────────────────────────────

def _run(
    net: "PetriNet",
    direction: str,
    pattern_instances: dict[str, dict] | None,
) -> dict:
    if not net.places and not net.transitions:
        return {"positions": [], "layer_count": 0, "element_count": 0, "cluster_bounds": {}}

    if direction not in ("LR", "TB"):
        raise ValueError(f"direction must be 'LR' or 'TB', got {direction!r}")

    # Flat fallback when no patterns: preserves the original behaviour for
    # raw low-level-tool sessions and for the existing unit tests that build
    # nets directly without patterns.
    if not pattern_instances:
        return _flat_layout(net, direction)

    return _cluster_layout(net, direction, pattern_instances)


# ── Flat (non-clustered) layout — backward compatibility ──────────────────────

def _flat_layout(net: "PetriNet", direction: str) -> dict:
    """Original flat Sugiyama. Used when there are no pattern instances."""
    nodes, succs, preds = _build_graph(net)
    _remove_cycles(nodes, succs, preds)
    layer_map = _assign_layers_longest_path(nodes, succs, preds)
    for nid, lyr in layer_map.items():
        nodes[nid].layer = lyr

    all_nodes = dict(nodes)
    all_succs = {nid: list(v) for nid, v in succs.items()}
    all_preds = {nid: list(v) for nid, v in preds.items()}
    _insert_dummies(nodes, all_nodes, all_succs, all_preds)

    layer_dict: dict[int, list[str]] = {}
    for nid, node in all_nodes.items():
        layer_dict.setdefault(node.layer, []).append(nid)
    max_layer = max(layer_dict) if layer_dict else 0
    ordered: list[list[str]] = [layer_dict.get(i, []) for i in range(max_layer + 1)]
    for lst in ordered:
        lst.sort()  # deterministic initial order

    for _ in range(2):
        for i in range(1, len(ordered)):
            _barycenter_sort(ordered[i], ordered[i - 1], all_preds, len(ordered[i - 1]))
        for i in range(len(ordered) - 2, -1, -1):
            _barycenter_sort(ordered[i], ordered[i + 1], all_succs, len(ordered[i + 1]))

    coords = _assign_flat_coords(all_nodes, ordered, direction)

    real_layer_count = sum(
        1 for lst in ordered if any(nid in nodes for nid in lst)
    )
    positions = [
        {"id": nid, "x": round(coords[nid][0], 2), "y": round(coords[nid][1], 2)}
        for nid in sorted(nodes)
        if nid in coords
    ]
    return {
        "positions": positions,
        "layer_count": real_layer_count,
        "element_count": len(positions),
        "cluster_bounds": {},
    }


# ── Cluster-aware layout ──────────────────────────────────────────────────────

def _cluster_layout(
    net: "PetriNet",
    direction: str,
    pattern_instances: dict[str, dict],
) -> dict:
    """Pattern-aware pipeline."""
    nodes, succs, preds = _build_graph(net)

    # 1. Build cluster map + identify bridge transitions
    clusters, node_cluster, bridges = _build_clusters(
        nodes, succs, preds, pattern_instances
    )

    # 2. Layout each cluster independently (intra-cluster sub-Sugiyama)
    for cluster in clusters.values():
        _layout_cluster(cluster, nodes, succs, preds, node_cluster, direction)

    # 3. Build super-graph
    super_succs, super_preds = _build_super_graph(
        clusters, node_cluster, succs, bridges
    )
    _remove_cycles_super(clusters, super_succs, super_preds)

    # 4. Layer assignment — longest-path FROM SOURCES on the cluster graph.
    # This is the cluster equivalent of "depth from the entry point": every
    # cluster sits one super-layer past whatever feeds it. Super-graphs of
    # real models are DAGs after _remove_cycles_super, so cycle-reversal
    # artefacts that motivated sinks-based layering in flat Sugiyama don't
    # apply here.
    super_layer = _assign_layers_super(clusters, super_succs, super_preds)
    # Terminators are then pulled out of that ranking and given a column of
    # their own at the end — see _align_terminators_last.
    _align_terminators_last(clusters, super_succs, super_layer)

    # 5. Initial super-layer ordering + crossing minimisation
    super_ordered = _order_super_layers(super_layer, clusters, super_succs, super_preds)

    # 6. Place clusters in super-grid (assigns origin_x / origin_y)
    _place_clusters(clusters, super_ordered, direction)

    # 7. Emit global coordinates
    coords: dict[str, tuple[float, float]] = {}
    for cluster in clusters.values():
        for nid, (lx, ly) in cluster.local_coords.items():
            coords[nid] = (cluster.origin_x + lx, cluster.origin_y + ly)

    # 8. Bridge placement post-pass
    _place_bridges(
        bridges, clusters, node_cluster, coords, nodes, succs, preds, direction
    )

    # 9. Round + emit
    positions = [
        {"id": nid, "x": round(coords[nid][0], 2), "y": round(coords[nid][1], 2)}
        for nid in sorted(coords)
    ]

    cluster_bounds = {
        c.name: {
            "x": round(c.origin_x, 2),
            "y": round(c.origin_y, 2),
            "width": round(c.width, 2),
            "height": round(c.height, 2),
            "type": c.type,
        }
        for c in clusters.values()
        if c.name != RAW_CLUSTER and c.local_coords  # don't surface empty / __raw
    }

    layer_count = max(super_layer.values()) + 1 if super_layer else 0
    return {
        "positions": positions,
        "layer_count": layer_count,
        "element_count": len(positions),
        "cluster_bounds": cluster_bounds,
    }


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph(
    net: "PetriNet",
) -> tuple[dict[str, _Node], dict[str, list[str]], dict[str, list[str]]]:
    nodes: dict[str, _Node] = {}
    for p in net.places:
        nodes[p.id] = _Node(p.id, is_place=True, tokens=getattr(p, "tokens", 0))
    for t in net.transitions:
        nodes[t.id] = _Node(t.id, is_place=False)

    succs: dict[str, list[str]] = {nid: [] for nid in nodes}
    preds: dict[str, list[str]] = {nid: [] for nid in nodes}
    for arc in net.arcs:
        s, t = arc.source_id, arc.target_id
        if s in nodes and t in nodes and t not in succs[s]:
            succs[s].append(t)
            preds[t].append(s)
    return nodes, succs, preds


# ── Cluster building ──────────────────────────────────────────────────────────

def _build_clusters(
    nodes: dict[str, _Node],
    succs: dict[str, list[str]],
    preds: dict[str, list[str]],
    pattern_instances: dict[str, dict],
) -> tuple[dict[str, _Cluster], dict[str, str], set[str]]:
    """Map nodes → cluster. Detect bridge transitions (placed post-hoc)."""
    node_cluster: dict[str, str] = {}
    clusters: dict[str, _Cluster] = {}

    # Walk patterns in deterministic order
    for name in sorted(pattern_instances):
        inst = pattern_instances[name]
        cluster = _Cluster(
            name=name,
            type=inst.get("type", "unknown"),
            place_ids=[pid for pid in inst.get("place_ids") or [] if pid in nodes],
            transition_ids=[tid for tid in inst.get("transition_ids") or [] if tid in nodes],
            input_place_id=inst.get("input_place_id"),
            output_place_id=inst.get("output_place_id"),
            metadata=dict(inst.get("metadata") or {}),
        )
        for nid in cluster.place_ids + cluster.transition_ids:
            # First-write wins (deterministic). Subsequent overlapping patterns
            # cannot claim the same node — they keep working but the node is
            # owned by the lexicographically-first pattern.
            node_cluster.setdefault(nid, name)
        clusters[name] = cluster

    # Detect bridge transitions: orphans (not in any cluster) with exactly one
    # producer place and one consumer place, where those places belong to
    # *different* clusters. These represent connect_patterns()-generated
    # transfer steps.
    bridges: set[str] = set()
    for nid, node in nodes.items():
        if node.is_place or nid in node_cluster:
            continue
        if len(preds[nid]) != 1 or len(succs[nid]) != 1:
            continue
        src = preds[nid][0]
        tgt = succs[nid][0]
        if not (nodes[src].is_place and nodes[tgt].is_place):
            continue
        src_cluster = node_cluster.get(src)
        tgt_cluster = node_cluster.get(tgt)
        if src_cluster and tgt_cluster and src_cluster != tgt_cluster:
            bridges.add(nid)

    # Everything else not yet assigned → __raw pseudo-cluster
    raw_place_ids: list[str] = []
    raw_transition_ids: list[str] = []
    for nid, node in nodes.items():
        if nid in node_cluster or nid in bridges:
            continue
        if node.is_place:
            raw_place_ids.append(nid)
        else:
            raw_transition_ids.append(nid)
        node_cluster[nid] = RAW_CLUSTER

    if raw_place_ids or raw_transition_ids:
        clusters[RAW_CLUSTER] = _Cluster(
            name=RAW_CLUSTER,
            type="raw",
            place_ids=sorted(raw_place_ids),
            transition_ids=sorted(raw_transition_ids),
        )

    return clusters, node_cluster, bridges


# ── Intra-cluster layout ──────────────────────────────────────────────────────

def _layout_cluster(
    cluster: _Cluster,
    nodes: dict[str, _Node],
    succs: dict[str, list[str]],
    preds: dict[str, list[str]],
    node_cluster: dict[str, str],
    direction: str,
) -> None:
    """Compute local coordinates for one cluster.

    Strategy:
      - Identify "side places" (initial-marked, not interface in/out) — these
        are recycling/resource places (Generator.Ready, Machine.Free,
        BoundedQueue.Capacity, Controller.Signal). They get pinned beside
        their gating transition rather than participating in the main flow.
      - Build pattern-internal arcs (excluding side-place arcs).
      - Run flat Sugiyama on the main flow.
      - Re-attach side places adjacent to their gating transition.
    """
    cluster_ids = set(cluster.place_ids) | set(cluster.transition_ids)
    if not cluster_ids:
        cluster.width = 0.0
        cluster.height = 0.0
        return

    interface_ids = {cluster.input_place_id, cluster.output_place_id}
    interface_ids.discard(None)
    # Merge metadata input/output places too (Assembly slots, BoundedQueue
    # reject_output, Merge input_place_ids — they're part of the main flow)
    for key in ("input_place_ids",):
        val = cluster.metadata.get(key)
        if isinstance(val, dict):
            interface_ids.update(val.values())
    for key in ("reject_output_id", "counter_place_id"):
        val = cluster.metadata.get(key)
        if isinstance(val, str):
            interface_ids.add(val)

    # Side place detection:
    #   side := (initial tokens > 0) AND (not an interface port) AND
    #           (no external arcs leaving the cluster). Gating transition is
    #           the place's first internal consumer.
    side_places: dict[str, str] = {}
    main_nodes: set[str] = set()

    for pid in cluster.place_ids:
        if pid not in nodes:
            continue
        place_node = nodes[pid]
        if pid in interface_ids:
            main_nodes.add(pid)
            continue
        external = any(n not in cluster_ids for n in (preds[pid] + succs[pid]))
        if external:
            main_nodes.add(pid)
            continue
        if place_node.tokens <= 0:
            main_nodes.add(pid)
            continue
        out_tids = [n for n in succs[pid] if n in cluster_ids and not nodes[n].is_place]
        if not out_tids:
            # No consumer at all — not a resource place; let main flow handle it
            main_nodes.add(pid)
            continue
        side_places[pid] = out_tids[0]

    # All transitions are main nodes
    for tid in cluster.transition_ids:
        if tid in nodes:
            main_nodes.add(tid)

    # Restrict graph to main_nodes + internal arcs
    sub_succs: dict[str, list[str]] = {nid: [] for nid in main_nodes}
    sub_preds: dict[str, list[str]] = {nid: [] for nid in main_nodes}
    for nid in main_nodes:
        for nbr in succs[nid]:
            if nbr in main_nodes:
                sub_succs[nid].append(nbr)
                sub_preds[nbr].append(nid)

    # Layout main flow with flat mini-Sugiyama (LR within cluster always)
    sub_nodes = {nid: nodes[nid] for nid in main_nodes}
    if sub_nodes:
        _remove_cycles(sub_nodes, sub_succs, sub_preds)
        layer_map = _assign_layers_longest_path(sub_nodes, sub_succs, sub_preds)
        for nid, lyr in layer_map.items():
            sub_nodes[nid].layer = lyr
        all_nodes = dict(sub_nodes)
        all_succs = {nid: list(v) for nid, v in sub_succs.items()}
        all_preds = {nid: list(v) for nid, v in sub_preds.items()}
        _insert_dummies(sub_nodes, all_nodes, all_succs, all_preds)

        layer_dict: dict[int, list[str]] = {}
        for nid, node in all_nodes.items():
            layer_dict.setdefault(node.layer, []).append(nid)
        max_layer = max(layer_dict) if layer_dict else 0
        ordered: list[list[str]] = [layer_dict.get(i, []) for i in range(max_layer + 1)]
        for lst in ordered:
            lst.sort()

        for _ in range(2):
            for i in range(1, len(ordered)):
                _barycenter_sort(ordered[i], ordered[i - 1], all_preds, len(ordered[i - 1]))
            for i in range(len(ordered) - 2, -1, -1):
                _barycenter_sort(ordered[i], ordered[i + 1], all_succs, len(ordered[i + 1]))

        local_coords = _assign_flat_coords(all_nodes, ordered, direction)
        # Restrict to real nodes only
        cluster.local_coords = {
            nid: local_coords[nid] for nid in sub_nodes if nid in local_coords
        }
    else:
        cluster.local_coords = {}

    # Place side places adjacent to their gating transition
    for pid, gating_tid in side_places.items():
        if gating_tid not in cluster.local_coords:
            # Should not happen, but fall back to (0, 0)
            cluster.local_coords[pid] = (0.0, 0.0)
            continue
        gx, gy = cluster.local_coords[gating_tid]
        # Place above the transition (smaller y); centred on transition x.
        side_x = gx + (TRANS_W - PLACE_W) / 2.0
        side_y = gy - (PLACE_H + NODE_GAP)
        # If another side place already occupies the slot above, push below.
        occupied = any(
            abs(x - side_x) < 1 and abs(y - side_y) < 1
            for x, y in cluster.local_coords.values()
        )
        if occupied:
            side_y = gy + TRANS_H + NODE_GAP
        cluster.local_coords[pid] = (side_x, side_y)

    # Normalise to top-left (0, 0) origin and compute bbox
    if not cluster.local_coords:
        cluster.width = 0.0
        cluster.height = 0.0
        return

    min_x = min(x for x, _ in cluster.local_coords.values())
    min_y = min(y for _, y in cluster.local_coords.values())
    cluster.local_coords = {
        nid: (x - min_x, y - min_y) for nid, (x, y) in cluster.local_coords.items()
    }

    max_x = 0.0
    max_y = 0.0
    for nid, (x, y) in cluster.local_coords.items():
        node = nodes[nid]
        max_x = max(max_x, x + node.w)
        max_y = max(max_y, y + node.h)
    cluster.width = max_x
    cluster.height = max_y


# ── Super-graph ───────────────────────────────────────────────────────────────

def _build_super_graph(
    clusters: dict[str, _Cluster],
    node_cluster: dict[str, str],
    succs: dict[str, list[str]],
    bridges: set[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    super_succs: dict[str, list[str]] = {name: [] for name in clusters}
    super_preds: dict[str, list[str]] = {name: [] for name in clusters}

    # Direct cluster-to-cluster arcs (skip bridges; they create their own
    # logical connection between src_cluster and tgt_cluster).
    for src, nbrs in succs.items():
        if src in bridges:
            continue
        src_cluster = node_cluster.get(src)
        if not src_cluster:
            continue
        for tgt in nbrs:
            if tgt in bridges:
                # Bridge transition: hop through it to its single output
                bridge_outs = succs.get(tgt, [])
                if not bridge_outs:
                    continue
                tgt_real = bridge_outs[0]
                tgt_cluster = node_cluster.get(tgt_real)
            else:
                tgt_cluster = node_cluster.get(tgt)
            if not tgt_cluster or tgt_cluster == src_cluster:
                continue
            if tgt_cluster not in super_succs[src_cluster]:
                super_succs[src_cluster].append(tgt_cluster)
                super_preds[tgt_cluster].append(src_cluster)

    return super_succs, super_preds


def _remove_cycles_super(
    clusters: dict[str, _Cluster],
    succs: dict[str, list[str]],
    preds: dict[str, list[str]],
) -> None:
    """Reverse back-edges on the super-graph (rare for real models)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {name: WHITE for name in clusters}

    for start in sorted(clusters):
        if color[start] != WHITE:
            continue
        stack: list[str] = [start]
        idx: list[int] = [0]
        color[start] = GRAY
        while stack:
            u = stack[-1]
            nbrs = succs[u]
            i = idx[-1]
            if i >= len(nbrs):
                color[u] = BLACK
                stack.pop()
                idx.pop()
                continue
            v = nbrs[i]
            idx[-1] = i + 1
            if color.get(v) == GRAY:
                nbrs.pop(i)
                idx[-1] = i
                if u in preds[v]:
                    preds[v].remove(u)
                succs[v].append(u)
                preds[u].append(v)
            elif color.get(v, WHITE) == WHITE:
                color[v] = GRAY
                stack.append(v)
                idx.append(0)


def _assign_layers_super(
    clusters: dict[str, _Cluster],
    succs: dict[str, list[str]],
    preds: dict[str, list[str]],
) -> dict[str, int]:
    """Longest path from super-sources on the cluster graph.

    Each cluster's layer = max(predecessor.layer) + 1. Sources get layer 0
    (leftmost), and every other cluster sits one step past whatever feeds
    it, so a branch that is three steps long draws three steps long.

    This ranks terminators by their own upstream depth too; pulling them
    back out into a single trailing column is a separate, deliberate pass
    (_align_terminators_last), kept apart from this one so the general
    "depth from the entry point" rule stays readable on its own.
    """
    in_deg: dict[str, int] = {name: len(preds[name]) for name in clusters}
    layer: dict[str, int] = {name: 0 for name in clusters}
    remaining: dict[str, int] = dict(in_deg)
    visited: set[str] = set()
    queue: deque[str] = deque(sorted(name for name in clusters if in_deg[name] == 0))

    while queue:
        u = queue.popleft()
        if u in visited:
            continue
        visited.add(u)
        for v in sorted(succs[u]):
            candidate = layer[u] + 1
            if candidate > layer[v]:
                layer[v] = candidate
            remaining[v] -= 1
            if remaining[v] <= 0 and v not in visited:
                queue.append(v)

    max_lyr = max(layer.values()) if layer else 0
    for name in clusters:
        if name not in visited:
            # Unreachable cluster (e.g. residual cycle member) — push past the
            # known frontier so it never overlaps a reachable cluster.
            layer[name] = max_lyr + 1
    return layer


#: Pattern types that end a flow rather than continue it. Kept as a set
#: because "which patterns are sinks" is a modelling fact (see
#: services/petri/patterns), not a property the layout can infer: a
#: terminator is recognisably an endpoint even when the graph would let it
#: sit mid-drawing.
TERMINATOR_TYPES: frozenset[str] = frozenset({"terminator"})


def _align_terminators_last(
    clusters: dict[str, _Cluster],
    succs: dict[str, list[str]],
    layer: dict[str, int],
) -> None:
    """Give every terminator the same final super-layer, past everything else.

    Depth-based layering alone ranks a terminator by the length of the chain
    that happens to feed it, so a counter behind a two-step branch lands in
    the same column as a machine on a four-step branch. That reads as a
    counter sitting in the MIDDLE of the drawing, and two counters on
    branches of different lengths never line up with each other.

    A terminator is where a flow ends, which is a fact about the model
    rather than about path lengths, so it is drawn where an ending belongs:
    one column past the last real step, all of them together. Within that
    column `_place_clusters` spreads siblings along the cross axis, which is
    what puts several counters one under another (LR) or side by side (TB).

    Only terminators that nothing follows are moved. One that feeds another
    cluster is not an ending in this model whatever its type says, and
    moving it would draw its own successor to its left.

    Never moves a terminator LEFT of where depth put it: the new column is
    one past the deepest non-terminator, which is at least as deep as any
    chain leading into a terminator.
    """
    endings = [
        name
        for name, cluster in clusters.items()
        if cluster.type in TERMINATOR_TYPES and not succs.get(name)
    ]
    if not endings:
        return
    rest = [lyr for name, lyr in layer.items() if name not in set(endings)]
    if not rest:
        return
    last = max(rest) + 1
    for name in endings:
        layer[name] = last


def _order_super_layers(
    super_layer: dict[str, int],
    clusters: dict[str, _Cluster],
    super_succs: dict[str, list[str]],
    super_preds: dict[str, list[str]],
) -> list[list[str]]:
    """Initial layer ordering + barycentric crossing reduction."""
    if not super_layer:
        return []
    max_layer = max(super_layer.values())
    ordered: list[list[str]] = [[] for _ in range(max_layer + 1)]
    for name, lyr in super_layer.items():
        ordered[lyr].append(name)
    for lst in ordered:
        lst.sort()  # deterministic

    for _ in range(2):
        for i in range(1, len(ordered)):
            _barycenter_sort(ordered[i], ordered[i - 1], super_preds, len(ordered[i - 1]))
        for i in range(len(ordered) - 2, -1, -1):
            _barycenter_sort(ordered[i], ordered[i + 1], super_succs, len(ordered[i + 1]))
    return ordered


# ── Coordinate placement ──────────────────────────────────────────────────────

def _place_clusters(
    clusters: dict[str, _Cluster],
    super_ordered: list[list[str]],
    direction: str,
) -> None:
    """Assign origin_x / origin_y to every cluster."""
    if not super_ordered:
        return

    main_offset = MARGIN
    for layer_names in super_ordered:
        if not layer_names:
            continue

        if direction == "LR":
            layer_thickness = max(
                (clusters[n].width for n in layer_names if clusters[n].width > 0),
                default=PLACE_W,
            )
        else:
            layer_thickness = max(
                (clusters[n].height for n in layer_names if clusters[n].height > 0),
                default=PLACE_H,
            )

        cross_offset = MARGIN
        for name in layer_names:
            c = clusters[name]
            if direction == "LR":
                main_size = c.width if c.width > 0 else PLACE_W
                cross_size = c.height if c.height > 0 else PLACE_H
                c.origin_x = main_offset + (layer_thickness - main_size) / 2.0
                c.origin_y = cross_offset
            else:
                main_size = c.height if c.height > 0 else PLACE_H
                cross_size = c.width if c.width > 0 else PLACE_W
                c.origin_x = cross_offset
                c.origin_y = main_offset + (layer_thickness - main_size) / 2.0
            cross_offset += cross_size + CLUSTER_GAP

        main_offset += layer_thickness + LAYER_GUTTER


def _boxes_clear(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    clearance: float,
) -> bool:
    """Whether two (x, y, w, h) boxes stay `clearance` apart on some axis."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    apart_x = bx - (ax + aw) >= clearance or ax - (bx + bw) >= clearance
    apart_y = by - (ay + ah) >= clearance or ay - (by + bh) >= clearance
    return apart_x or apart_y


def _place_bridges(
    bridges: set[str],
    clusters: dict[str, _Cluster],
    node_cluster: dict[str, str],
    coords: dict[str, tuple[float, float]],
    nodes: dict[str, _Node],
    succs: dict[str, list[str]],
    preds: dict[str, list[str]],
    direction: str,
) -> None:
    """Place bridge transitions midway between their endpoints, then slide
    each one off anything it would land on.

    The midpoint alone is not a position: two bridges joining the same pair
    of clusters have the SAME midpoint, and a bridge spanning a short edge
    lands inside the cluster node next to it. Both drew one transition on
    top of another, which is unreadable and, worse, looks like a single
    element that happens to have too many arcs.

    So the midpoint is an ideal rather than an answer: the bridge is nudged
    along the CROSS axis (down/up in LR, right/left in TB) in grid steps
    until it clears every node already placed, taking the smallest offset
    that works and alternating sides so it does not always drift the same
    way. The flow axis is left alone because that is the axis carrying the
    meaning "between these two".

    Caption bands count as part of a node here (see LABEL_H): a transition
    parked in the gap under a place would be covered by that place's own
    label, which is no more readable than an overlap of the boxes.
    """
    def footprint(nid: str) -> tuple[float, float, float, float]:
        x, y = coords[nid]
        node = nodes.get(nid)
        is_place = node.is_place if node is not None else False
        w = PLACE_W if is_place else TRANS_W
        h = (PLACE_H if is_place else TRANS_H) + LABEL_H
        return (x, y, w, h)

    placed: list[tuple[float, float, float, float]] = [
        footprint(nid) for nid in coords if nid not in bridges
    ]

    for bid in sorted(bridges):
        if not preds.get(bid) or not succs.get(bid):
            continue
        src_pid = preds[bid][0]
        tgt_pid = succs[bid][0]
        if src_pid not in coords or tgt_pid not in coords:
            continue
        sx, sy = coords[src_pid]
        tx, ty = coords[tgt_pid]
        # Centre at midpoint between source's right edge and target's left edge (LR)
        if direction == "LR":
            mid_x = (sx + PLACE_W + tx) / 2.0 - TRANS_W / 2.0
            mid_y = (sy + ty) / 2.0 + (PLACE_H - TRANS_H) / 2.0
        else:
            mid_x = (sx + tx) / 2.0 + (PLACE_W - TRANS_W) / 2.0
            mid_y = (sy + PLACE_H + ty) / 2.0 - TRANS_H / 2.0

        box_w, box_h = TRANS_W, TRANS_H + LABEL_H
        chosen = (mid_x, mid_y)
        for step in range(0, 40):
            for sign in ((1,) if step == 0 else (1, -1)):
                offset = sign * step * GRID_UNIT
                x = mid_x if direction == "LR" else mid_x + offset
                y = mid_y + offset if direction == "LR" else mid_y
                if all(
                    _boxes_clear((x, y, box_w, box_h), other, BRIDGE_CLEARANCE)
                    for other in placed
                ):
                    chosen = (x, y)
                    break
            else:
                continue
            break

        coords[bid] = chosen
        placed.append((chosen[0], chosen[1], box_w, box_h))


# ── Flat-Sugiyama helpers (reused by both flat and intra-cluster paths) ───────

def _remove_cycles(
    nodes: dict[str, _Node],
    succs: dict[str, list[str]],
    preds: dict[str, list[str]],
) -> None:
    """Reverse back-edges (iterative DFS). Modifies succs/preds in place."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {nid: WHITE for nid in nodes}

    for start in sorted(nodes):
        if color[start] != WHITE:
            continue
        stack: list[str] = [start]
        idx: list[int] = [0]
        color[start] = GRAY
        while stack:
            u = stack[-1]
            nbrs = succs[u]
            i = idx[-1]
            if i >= len(nbrs):
                color[u] = BLACK
                stack.pop()
                idx.pop()
                continue
            v = nbrs[i]
            idx[-1] = i + 1
            if color.get(v) == GRAY:
                nbrs.pop(i)
                idx[-1] = i
                if u in preds[v]:
                    preds[v].remove(u)
                succs[v].append(u)
                preds[u].append(v)
            elif color.get(v, WHITE) == WHITE:
                color[v] = GRAY
                stack.append(v)
                idx.append(0)


def _assign_layers_longest_path(
    nodes: dict[str, _Node],
    succs: dict[str, list[str]],
    preds: dict[str, list[str]],
) -> dict[str, int]:
    """Longest-path layering from sources (used for flat & intra-cluster)."""
    in_deg: dict[str, int] = {nid: len(preds[nid]) for nid in nodes}
    layer: dict[str, int] = {nid: 0 for nid in nodes}
    remaining: dict[str, int] = dict(in_deg)
    visited: set[str] = set()
    queue: deque[str] = deque(sorted(nid for nid in nodes if in_deg[nid] == 0))
    while queue:
        u = queue.popleft()
        if u in visited:
            continue
        visited.add(u)
        for v in succs[u]:
            candidate = layer[u] + 1
            if candidate > layer[v]:
                layer[v] = candidate
            remaining[v] -= 1
            if remaining[v] <= 0 and v not in visited:
                queue.append(v)
    max_lyr = max(layer.values()) if layer else 0
    for nid in nodes:
        if nid not in visited:
            layer[nid] = max_lyr + 1
    return layer


def _insert_dummies(
    real: dict[str, _Node],
    all_nodes: dict[str, _Node],
    all_succs: dict[str, list[str]],
    all_preds: dict[str, list[str]],
) -> None:
    """Insert dummy chains on edges spanning >1 layer (modifies in place)."""
    counter = 0
    for src in sorted(real):
        for tgt in list(all_succs[src]):
            span = all_nodes[tgt].layer - all_nodes[src].layer
            if abs(span) <= 1:
                continue
            step = 1 if span > 0 else -1
            src_lyr = all_nodes[src].layer
            tgt_lyr = all_nodes[tgt].layer
            all_succs[src].remove(tgt)
            all_preds[tgt].remove(src)
            prev = src
            for lyr in range(src_lyr + step, tgt_lyr, step):
                counter += 1
                did = f"__d{counter}"
                dummy = _Node(did, is_dummy=True)
                dummy.layer = lyr
                all_nodes[did] = dummy
                all_succs[did] = []
                all_preds[did] = [prev]
                all_succs[prev].append(did)
                prev = did
            all_succs[prev].append(tgt)
            all_preds[tgt].append(prev)


def _barycenter_sort(
    current: list[str],
    reference: list[str],
    adj: dict[str, list[str]],
    ref_len: int,
) -> None:
    """Stable barycentric sort of *current* by adjacents in *reference*."""
    ref_pos: dict[str, float] = {nid: float(i) for i, nid in enumerate(reference)}
    mid = ref_len / 2.0

    def bary(nid: str) -> float:
        nbrs = [ref_pos[n] for n in adj.get(nid, []) if n in ref_pos]
        return sum(nbrs) / len(nbrs) if nbrs else mid

    current.sort(key=lambda n: (bary(n), n))


def _assign_flat_coords(
    all_nodes: dict[str, _Node],
    ordered: list[list[str]],
    direction: str,
) -> dict[str, tuple[float, float]]:
    """Assign pixel coordinates within a flat layered drawing."""
    coords: dict[str, tuple[float, float]] = {}
    main_offset = MARGIN

    for layer_list in ordered:
        if not layer_list:
            continue
        if direction == "LR":
            thick = max((all_nodes[n].w for n in layer_list), default=0.0)
        else:
            thick = max((all_nodes[n].h for n in layer_list), default=0.0)

        cross_offset = MARGIN
        for nid in layer_list:
            node = all_nodes[nid]
            if direction == "LR":
                main_size = node.w
                cross_size = node.h
                x = main_offset + (thick - main_size) / 2.0
                y = cross_offset
            else:
                main_size = node.h
                cross_size = node.w
                x = cross_offset
                y = main_offset + (thick - main_size) / 2.0
            coords[nid] = (x, y)
            cross_offset += cross_size + NODE_GAP

        main_offset += thick + LAYER_GAP

    return coords
