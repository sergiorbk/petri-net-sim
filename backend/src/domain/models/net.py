"""PetriNet aggregate root for domain model."""

import collections
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, PrivateAttr

from .arc import Arc, ArcType
from .place import Place
from .transition import Transition
from .types import DistributionType, Graphics


class PetriNet(BaseModel):
    """
    Petri Net aggregate root.

    This is the main entry point for creating and manipulating Petri nets.
    All modifications should go through this class to ensure topological validity.

    Invariants enforced:
    - Arcs can only connect Place <-> Transition (bipartite graph)
    - All arc endpoints must reference existing nodes
    - IDs are unique within their type
    """

    name: str = Field(default="PetriNet", description="Net name")
    places: List[Place] = Field(default_factory=list)
    transitions: List[Transition] = Field(default_factory=list)
    arcs: List[Arc] = Field(default_factory=list)

    # Private indexes for fast lookups (not serialized)
    _node_index: Dict[str, str] = PrivateAttr(default_factory=dict)
    _name_index: Dict[str, str] = PrivateAttr(default_factory=dict)

    # Ids reserved for future auto-generated ids to skip, not serialized and
    # never visible to a lookup: consulted ONLY by add_place/add_transition/
    # add_arc's own "while f'p{n}' in ..." minting loops below, so a session
    # juggling several independent PetriNets (one per Petri-object, see
    # services/petri/session.py) can pre-register every OTHER net's ids here
    # and steer this net's next auto-generated id away from them, without
    # making those foreign ids look like real, present nodes to
    # _node_index.get/add_arc's existence check/validate_topology/get_place/
    # get_transition -- every one of those still only ever sees this net's
    # OWN places/transitions/arcs. See reserve_ids() below.
    _reserved_ids: set = PrivateAttr(default_factory=set)

    def model_post_init(self, __context) -> None:
        """Rebuild index after deserialization."""
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """Rebuild internal node indexes for topology and name validation."""
        self._node_index = {}
        self._name_index = {}
        for p in self.places:
            self._node_index[p.id] = "place"
            self._name_index[p.name] = "place"
        for t in self.transitions:
            self._node_index[t.id] = "transition"
            self._name_index[t.name] = "transition"

    def reserve_ids(self, ids: set) -> None:
        """Register *ids* as taken for the sole purpose of steering this
        net's OWN future auto-generated p{n}/t{n}/arc{n} ids away from them.

        Additive only (never clears previously reserved ids): a caller that
        wants a fresh snapshot re-computes the full set it wants reserved
        and calls this again, which is exactly what
        PetriNetSession._reserve_ids_everywhere does. Does not add a place,
        transition, or arc, and is invisible to every lookup and validation
        path (_node_index, get_place, get_transition, get_arc,
        validate_topology, model_dump/serialization) -- only the id-minting
        loops in add_place/add_transition/add_arc consult _reserved_ids, so
        an id reserved here can never be mistaken for a real, present node
        the way seeding _node_index directly used to (the bug this method
        replaces: _node_index.get(id) returning a truthy, non-"place"/
        "transition" sentinel defeated add_arc's own existence check for an
        id living in a DIFFERENT net entirely).
        """
        self._reserved_ids.update(ids)

    def _check_name_unique(self, name: str, exclude_id: Optional[str] = None) -> None:
        """Raise ValueError if name is already used by another element."""
        existing_type = self._name_index.get(name)
        if existing_type is None:
            return
        if exclude_id is not None:
            pool = self.places if existing_type == "place" else self.transitions
            for el in pool:
                if el.name == name and el.id == exclude_id:
                    return
        raise ValueError(
            f"Name '{name}' is already used by a {existing_type}. "
            "Place and transition names must be unique across the entire net "
            "(required by TINA and other PNML tools)."
        )

    # -------------------------------------------------------------------------
    # Place operations
    # -------------------------------------------------------------------------

    def add_place(
        self,
        name: str,
        tokens: int = 0,
        x: float = 0.0,
        y: float = 0.0,
        place_id: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> Place:
        """
        Add a new place to the net.

        Args:
            name: Human-readable name
            tokens: Initial token count
            x, y: Graphical coordinates
            place_id: Optional custom ID (auto-generated if None)
            tag: Semantic tag (e.g. "throughput") read by optimizer/simulator

        Returns:
            The created Place
        """
        if place_id:
            pid = place_id
        else:
            n = len(self.places) + 1
            while f"p{n}" in self._node_index or f"p{n}" in self._reserved_ids:
                n += 1
            pid = f"p{n}"

        if pid in self._node_index:
            raise ValueError(f"Node with ID '{pid}' already exists")

        self._check_name_unique(name)

        place = Place(
            id=pid,
            name=name,
            tokens=tokens,
            tag=tag,
            graphics=Graphics(x=x, y=y),
        )

        self.places.append(place)
        self._node_index[pid] = "place"
        self._name_index[name] = "place"
        return place

    def get_place(self, place_id: str) -> Optional[Place]:
        """Get place by ID."""
        for p in self.places:
            if p.id == place_id:
                return p
        return None

    def get_place_by_name(self, name: str) -> Optional[Place]:
        """Get place by name (first match)."""
        for p in self.places:
            if p.name == name:
                return p
        return None

    # -------------------------------------------------------------------------
    # Transition operations
    # -------------------------------------------------------------------------

    def add_transition(
        self,
        name: str,
        mean_delay: float = 0.0,
        distribution: Optional[DistributionType] = None,
        standard_deviation: float = 0.0,
        priority: int = 1,
        probability: Optional[float] = None,
        x: float = 0.0,
        y: float = 0.0,
        transition_id: Optional[str] = None,
    ) -> Transition:
        """
        Add a new transition to the net.

        Args:
            name: Human-readable name
            mean_delay: Mean delay for timed transitions
            distribution: Time distribution type
            standard_deviation: For NORM/UNIF distributions
            priority: Firing priority
            probability: Firing probability for stochastic branching (0.0-1.0)
            x, y: Graphical coordinates
            transition_id: Optional custom ID (auto-generated if None)

        Returns:
            The created Transition
        """
        if transition_id:
            tid = transition_id
        else:
            n = len(self.transitions) + 1
            while f"t{n}" in self._node_index or f"t{n}" in self._reserved_ids:
                n += 1
            tid = f"t{n}"

        if tid in self._node_index:
            raise ValueError(f"Node with ID '{tid}' already exists")

        self._check_name_unique(name)

        transition = Transition(
            id=tid,
            name=name,
            mean_delay=mean_delay,
            distribution=distribution,
            standard_deviation=standard_deviation,
            priority=priority,
            probability=probability,
            graphics=Graphics(x=x, y=y),
        )

        self.transitions.append(transition)
        self._node_index[tid] = "transition"
        self._name_index[name] = "transition"
        return transition

    def get_transition(self, transition_id: str) -> Optional[Transition]:
        """Get transition by ID."""
        for t in self.transitions:
            if t.id == transition_id:
                return t
        return None

    def get_transition_by_name(self, name: str) -> Optional[Transition]:
        """Get transition by name (first match)."""
        for t in self.transitions:
            if t.name == name:
                return t
        return None

    # -------------------------------------------------------------------------
    # Arc operations
    # -------------------------------------------------------------------------

    def add_arc(
        self,
        source_id: str,
        target_id: str,
        weight: int = 1,
        arc_type: ArcType = ArcType.NORMAL,
        arc_id: Optional[str] = None,
    ) -> Arc:
        """
        Add an arc connecting a place and transition.

        Enforces Petri net topology: arcs can only connect Place <-> Transition.

        Args:
            source_id: ID of source node
            target_id: ID of target node
            weight: Arc weight (tokens consumed/produced)
            arc_type: Type of arc (normal, inhibitor, read)
            arc_id: Optional custom ID (auto-generated if None)

        Returns:
            The created Arc

        Raises:
            ValueError: If topology constraint is violated
        """
        src_type = self._node_index.get(source_id)
        tgt_type = self._node_index.get(target_id)

        if not src_type:
            raise ValueError(f"Source node '{source_id}' not found in net")
        if not tgt_type:
            raise ValueError(f"Target node '{target_id}' not found in net")

        if src_type == tgt_type:
            raise ValueError(
                f"Invalid arc topology: cannot connect {src_type} to {tgt_type}. "
                f"Arcs must connect Place <-> Transition. "
                f"({source_id} -> {target_id})"
            )

        if arc_id:
            aid = arc_id
        else:
            existing_ids = {a.id for a in self.arcs}
            n = len(self.arcs) + 1
            while f"arc{n}" in existing_ids or f"arc{n}" in self._reserved_ids:
                n += 1
            aid = f"arc{n}"

        arc = Arc(
            id=aid,
            source_id=source_id,
            target_id=target_id,
            weight=weight,
            arc_type=arc_type,
        )

        self.arcs.append(arc)
        return arc

    def get_arc(self, arc_id: str) -> Optional[Arc]:
        """Get arc by ID."""
        for a in self.arcs:
            if a.id == arc_id:
                return a
        return None

    def get_arcs_from(self, node_id: str) -> List[Arc]:
        """Get all arcs originating from a node."""
        return [a for a in self.arcs if a.source_id == node_id]

    def get_arcs_to(self, node_id: str) -> List[Arc]:
        """Get all arcs pointing to a node."""
        return [a for a in self.arcs if a.target_id == node_id]

    # -------------------------------------------------------------------------
    # Update operations
    # -------------------------------------------------------------------------

    def update_place(self, place_id: str, **kwargs) -> Place:
        """Update fields on an existing place.

        Supported kwargs: name, tokens, tag.
        Only provided fields are updated; others remain unchanged.
        """
        place = self.get_place(place_id)
        if not place:
            raise ValueError(f"Place '{place_id}' not found")
        for key, value in kwargs.items():
            if key == "tokens" and value is not None:
                if value < 0:
                    raise ValueError(f"Tokens cannot be negative, got {value}")
            if key == "name" and value is not None:
                self._check_name_unique(value, exclude_id=place_id)
                old_name = place.name
                setattr(place, key, value)
                del self._name_index[old_name]
                self._name_index[value] = "place"
                continue
            if hasattr(place, key):
                setattr(place, key, value)
            else:
                raise ValueError(f"Unknown place attribute: '{key}'")
        return place

    def update_transition(self, transition_id: str, **kwargs) -> Transition:
        """Update fields on an existing transition.

        Supported kwargs: name, mean_delay, distribution, standard_deviation,
        priority, probability.
        Only provided fields are updated; others remain unchanged.
        """
        transition = self.get_transition(transition_id)
        if not transition:
            raise ValueError(f"Transition '{transition_id}' not found")
        for key, value in kwargs.items():
            if key == "name" and value is not None:
                self._check_name_unique(value, exclude_id=transition_id)
                old_name = transition.name
                setattr(transition, key, value)
                del self._name_index[old_name]
                self._name_index[value] = "transition"
                continue
            if hasattr(transition, key):
                setattr(transition, key, value)
            else:
                raise ValueError(f"Unknown transition attribute: '{key}'")
        transition.validate_distribution_params()
        return transition

    def update_arc(self, arc_id: str, **kwargs) -> Arc:
        """Update fields on an existing arc.

        Supported kwargs: weight, arc_type.
        Only provided fields are updated; others remain unchanged.
        """
        arc = self.get_arc(arc_id)
        if not arc:
            raise ValueError(f"Arc '{arc_id}' not found")
        for key, value in kwargs.items():
            if hasattr(arc, key):
                setattr(arc, key, value)
            else:
                raise ValueError(f"Unknown arc attribute: '{key}'")
        return arc

    def set_element_positions(self, positions: list[dict]) -> list[str]:
        """Update x,y coordinates for places and transitions by ID.

        Args:
            positions: list of {"id": str, "x": float, "y": float}

        Returns:
            List of updated element IDs.

        Raises:
            ValueError if an ID is not found in the net.
        """
        updated = []
        for entry in positions:
            eid = entry["id"]
            x = float(entry["x"])
            y = float(entry["y"])
            node_type = self._node_index.get(eid)
            if node_type == "place":
                place = self.get_place(eid)
                place.graphics.x = x
                place.graphics.y = y
                updated.append(eid)
            elif node_type == "transition":
                transition = self.get_transition(eid)
                transition.graphics.x = x
                transition.graphics.y = y
                updated.append(eid)
            else:
                raise ValueError(f"Element '{eid}' not found in net")
        return updated

    def find_elements(
        self,
        name_pattern: str = "",
        element_type: Optional[str] = None,
    ) -> List[dict]:
        """Search for places and/or transitions by name substring.

        Args:
            name_pattern: Case-insensitive substring to match against element names.
                          Empty string matches everything.
            element_type: Filter by "place", "transition", or None for both.

        Returns:
            List of dicts with keys: id, name, type, x, y, and type-specific fields
            (tokens, tag for places; distribution, mean_delay for transitions).
        """
        pattern_lower = name_pattern.lower()
        results: List[dict] = []

        if element_type != "transition":
            for p in self.places:
                if not pattern_lower or pattern_lower in p.name.lower():
                    results.append({
                        "id": p.id,
                        "name": p.name,
                        "type": "place",
                        "x": p.graphics.x,
                        "y": p.graphics.y,
                        "tokens": p.tokens,
                        "tag": p.tag,
                    })

        if element_type != "place":
            for t in self.transitions:
                if not pattern_lower or pattern_lower in t.name.lower():
                    results.append({
                        "id": t.id,
                        "name": t.name,
                        "type": "transition",
                        "x": t.graphics.x,
                        "y": t.graphics.y,
                        "distribution": t.distribution.value if t.distribution else None,
                        "mean_delay": t.mean_delay,
                    })

        return results

    def get_bounds(self) -> dict:
        """Return the axis-aligned bounding box of all elements.

        Returns:
            Dict with min_x, max_x, min_y, max_y, center_x, center_y,
            width, height, element_count. All zeros when the net is empty.
        """
        all_x = [p.graphics.x for p in self.places] + [t.graphics.x for t in self.transitions]
        all_y = [p.graphics.y for p in self.places] + [t.graphics.y for t in self.transitions]

        if not all_x:
            return {
                "min_x": 0.0, "max_x": 0.0,
                "min_y": 0.0, "max_y": 0.0,
                "center_x": 0.0, "center_y": 0.0,
                "width": 0.0, "height": 0.0,
                "element_count": 0,
            }

        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        return {
            "min_x": min_x, "max_x": max_x,
            "min_y": min_y, "max_y": max_y,
            "center_x": (min_x + max_x) / 2.0,
            "center_y": (min_y + max_y) / 2.0,
            "width": max_x - min_x,
            "height": max_y - min_y,
            "element_count": len(all_x),
        }

    def move_elements_by(
        self,
        element_ids: List[str],
        dx: float,
        dy: float,
    ) -> List[str]:
        """Shift elements by a relative offset (dx, dy).

        Useful for "move the generator 200px to the right" without querying
        current coordinates first.

        Args:
            element_ids: IDs of places and/or transitions to move.
            dx: Horizontal offset in canvas units (positive = right).
            dy: Vertical offset in canvas units (positive = down).

        Returns:
            List of updated element IDs.

        Raises:
            ValueError if any ID is not found in the net.
        """
        updated = []
        for eid in element_ids:
            node_type = self._node_index.get(eid)
            if node_type == "place":
                place = self.get_place(eid)
                place.graphics.x += dx
                place.graphics.y += dy
                updated.append(eid)
            elif node_type == "transition":
                transition = self.get_transition(eid)
                transition.graphics.x += dx
                transition.graphics.y += dy
                updated.append(eid)
            else:
                raise ValueError(f"Element '{eid}' not found in net")
        return updated

    def auto_layout(
        self,
        direction: str = "LR",
        pattern_instances: dict | None = None,
    ) -> dict:
        """Re-layout all elements using pattern-aware Sugiyama layering.

        Args:
            direction: "LR" for left-to-right flow (default) or "TB" for
                       top-to-bottom flow.
            pattern_instances: Optional pattern-instance registry from the
                builder. When provided, layout becomes cluster-aware: each
                pattern is rendered as a compact block with explicit gutters
                between blocks. When omitted, falls back to flat Sugiyama.

        Returns:
            Dict with "layers" (super-layer count when clustered, flat layer
            count otherwise), "element_count" and "cluster_bounds" (per-
            pattern bounding boxes; empty when there are no patterns).
        """
        from src.domain.layout.sugiyama import layout_stats

        stats = layout_stats(
            self,
            direction=direction,
            pattern_instances=pattern_instances,
        )
        if not stats["positions"]:
            return {"layers": 0, "element_count": 0, "cluster_bounds": {}}
        self.set_element_positions(stats["positions"])
        return {
            "layers": stats["layer_count"],
            "element_count": stats["element_count"],
            "cluster_bounds": stats.get("cluster_bounds", {}),
        }

    def find_free_position(
        self,
        near_element_id: str,
        direction: str = "right",
        min_dist: float = 90.0,
    ) -> tuple[float, float]:
        """Return canvas coordinates clear of existing elements near a given element.

        Tries the primary direction first, then doubles the step, then tries
        the two orthogonal directions before falling back to the raw offset.

        Args:
            near_element_id: ID of the place or transition to position near.
            direction: "above" | "below" | "left" | "right" (default "right",
                so nets flow left-to-right unless a caller asks for vertical).
            min_dist: Minimum pixel distance from any existing element centre.

        Returns:
            (x, y) tuple guaranteed not to overlap existing elements (best-effort).

        Raises:
            ValueError if near_element_id is not found.
        """
        node_type = self._node_index.get(near_element_id)
        if node_type == "place":
            anchor = self.get_place(near_element_id)
        elif node_type == "transition":
            anchor = self.get_transition(near_element_id)
        else:
            raise ValueError(f"Element '{near_element_id}' not found in net")

        ax, ay = anchor.graphics.x, anchor.graphics.y

        _deltas = {
            "above": (0.0, -min_dist),
            "below": (0.0, min_dist),
            "left":  (-min_dist * 1.3, 0.0),
            "right": (min_dist * 1.3, 0.0),
        }
        primary = _deltas.get(direction, _deltas["right"])
        orthogonals = [d for k, d in _deltas.items() if d != primary]

        all_pos = (
            [(p.graphics.x, p.graphics.y) for p in self.places] +
            [(t.graphics.x, t.graphics.y) for t in self.transitions]
        )

        def _is_free(cx: float, cy: float) -> bool:
            return all(
                (cx - ex) ** 2 + (cy - ey) ** 2 >= min_dist ** 2
                for ex, ey in all_pos
            )

        for scale in (1.0, 2.0):
            cx = ax + primary[0] * scale
            cy = ay + primary[1] * scale
            if _is_free(cx, cy):
                return cx, cy

        for dx, dy in orthogonals:
            cx, cy = ax + dx, ay + dy
            if _is_free(cx, cy):
                return cx, cy

        return ax + primary[0], ay + primary[1]

    # -------------------------------------------------------------------------
    # Remove operations
    # -------------------------------------------------------------------------

    def remove_place(self, place_id: str) -> None:
        """Remove a place and all its connected arcs."""
        if place_id not in self._node_index:
            raise ValueError(f"Place '{place_id}' not found")
        if self._node_index[place_id] != "place":
            raise ValueError(f"'{place_id}' is not a place")
        place = self.get_place(place_id)
        self.arcs = [
            a for a in self.arcs
            if a.source_id != place_id and a.target_id != place_id
        ]
        self.places = [p for p in self.places if p.id != place_id]
        del self._node_index[place_id]
        if place and place.name in self._name_index:
            del self._name_index[place.name]

    def remove_transition(self, transition_id: str) -> None:
        """Remove a transition and all its connected arcs."""
        if transition_id not in self._node_index:
            raise ValueError(f"Transition '{transition_id}' not found")
        if self._node_index[transition_id] != "transition":
            raise ValueError(f"'{transition_id}' is not a transition")
        transition = self.get_transition(transition_id)
        self.arcs = [
            a for a in self.arcs
            if a.source_id != transition_id and a.target_id != transition_id
        ]
        self.transitions = [t for t in self.transitions if t.id != transition_id]
        del self._node_index[transition_id]
        if transition and transition.name in self._name_index:
            del self._name_index[transition.name]

    def remove_arc(self, arc_id: str) -> None:
        """Remove a single arc."""
        arc = self.get_arc(arc_id)
        if not arc:
            raise ValueError(f"Arc '{arc_id}' not found")
        self.arcs = [a for a in self.arcs if a.id != arc_id]

    # -------------------------------------------------------------------------
    # Topology queries
    # -------------------------------------------------------------------------

    def get_input_places(self, transition_id: str) -> List[Place]:
        """Get all places connected as inputs to a transition."""
        input_arcs = self.get_arcs_to(transition_id)
        return [self.get_place(a.source_id) for a in input_arcs if self.get_place(a.source_id)]

    def get_output_places(self, transition_id: str) -> List[Place]:
        """Get all places connected as outputs from a transition."""
        output_arcs = self.get_arcs_from(transition_id)
        return [self.get_place(a.target_id) for a in output_arcs if self.get_place(a.target_id)]

    def get_input_transitions(self, place_id: str) -> List[Transition]:
        """Get all transitions connected as inputs to a place."""
        input_arcs = self.get_arcs_to(place_id)
        return [
            self.get_transition(a.source_id)
            for a in input_arcs
            if self.get_transition(a.source_id)
        ]

    def get_output_transitions(self, place_id: str) -> List[Transition]:
        """Get all transitions connected as outputs from a place."""
        output_arcs = self.get_arcs_from(place_id)
        return [
            self.get_transition(a.target_id)
            for a in output_arcs
            if self.get_transition(a.target_id)
        ]

    # -------------------------------------------------------------------------
    # Connectivity
    # -------------------------------------------------------------------------

    def find_connected_components(self) -> List[set]:
        """Return connected components of the net treated as an undirected graph.

        Each component is a set of place/transition IDs. A fully-connected net
        returns a single-element list. Multiple components mean the net has
        islands that cannot exchange tokens.
        """
        all_ids: set[str] = (
            {p.id for p in self.places} | {t.id for t in self.transitions}
        )
        if not all_ids:
            return []

        adjacency: Dict[str, List[str]] = {nid: [] for nid in all_ids}
        for arc in self.arcs:
            if arc.source_id in adjacency and arc.target_id in adjacency:
                adjacency[arc.source_id].append(arc.target_id)
                adjacency[arc.target_id].append(arc.source_id)

        visited: set[str] = set()
        components: List[set] = []

        for start in all_ids:
            if start in visited:
                continue
            component: set[str] = set()
            queue: collections.deque = collections.deque([start])
            while queue:
                node = queue.popleft()
                if node in visited:
                    continue
                visited.add(node)
                component.add(node)
                for neighbour in adjacency[node]:
                    if neighbour not in visited:
                        queue.append(neighbour)
            components.append(component)

        return components

    def _component_label(self, component: set) -> str:
        """Return a short human-readable label for a connected component."""
        names: List[str] = []
        for nid in component:
            place = self.get_place(nid)
            if place:
                names.append(place.name)
                continue
            trans = self.get_transition(nid)
            if trans:
                names.append(trans.name)
        names.sort()
        if len(names) <= 3:
            return ", ".join(names)
        return ", ".join(names[:3]) + f" … (+{len(names) - 3} more)"

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def validate_topology(self) -> Tuple[bool, List[str]]:  # NOSONAR
        """
        Validate the entire net topology.

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Check all arc endpoints exist and connect Place <-> Transition
        for arc in self.arcs:
            src_type = self._node_index.get(arc.source_id)
            tgt_type = self._node_index.get(arc.target_id)

            if not src_type:
                errors.append(f"Arc '{arc.id}': source '{arc.source_id}' not found")
            if not tgt_type:
                errors.append(f"Arc '{arc.id}': target '{arc.target_id}' not found")
            if src_type and tgt_type and src_type == tgt_type:
                errors.append(
                    f"Arc '{arc.id}': invalid connection {src_type} -> {tgt_type}"
                )

        # Check for duplicate IDs
        all_ids = [p.id for p in self.places] + [t.id for t in self.transitions]
        seen = set()
        for node_id in all_ids:
            if node_id in seen:
                errors.append(f"Duplicate node ID: '{node_id}'")
            seen.add(node_id)

        # Check for name conflicts across places and transitions (TINA requirement)
        place_names = {p.name for p in self.places}
        for t in self.transitions:
            if t.name in place_names:
                errors.append(
                    f"Name conflict: transition '{t.name}' ({t.id}) shares its name "
                    f"with a place — PNML tools require unique names across all elements"
                )

        # Behavioral invariant: every transition must be connected to places on
        # both sides (no dangling sinks/sources). Counter places — not counter
        # transitions — accumulate throughput in this codebase.
        for trans in self.transitions:
            has_input = any(a.target_id == trans.id for a in self.arcs)
            has_output = any(a.source_id == trans.id for a in self.arcs)
            if not has_input:
                errors.append(
                    f"Transition '{trans.name}' ({trans.id}) has no input arc — "
                    f"transitions must consume from at least one place"
                )
            if not has_output:
                errors.append(
                    f"Transition '{trans.name}' ({trans.id}) has no output arc — "
                    f"transitions must produce to at least one place"
                )

        # Connectivity invariant: all elements must form a single connected
        # component. Multiple components mean isolated sub-nets that can never
        # exchange tokens — simulation results would be misleading.
        components = self.find_connected_components()
        if len(components) > 1:
            labels = [self._component_label(c) for c in components]
            errors.append(
                f"Network has {len(components)} disconnected components — "
                f"connect them before simulating or exporting: "
                + " | ".join(f"[{lbl}]" for lbl in labels)
            )

        return len(errors) == 0, errors

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    @property
    def total_tokens(self) -> int:
        """Total number of tokens in all places."""
        return sum(p.tokens for p in self.places)

    def __repr__(self) -> str:
        return (
            f"PetriNet(name='{self.name}', "
            f"places={len(self.places)}, "
            f"transitions={len(self.transitions)}, "
            f"arcs={len(self.arcs)})"
        )
