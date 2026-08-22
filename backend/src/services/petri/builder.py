"""PetriNet Builder - orchestrates pattern composition."""

import inspect
from typing import List, Optional

from src.domain import ArcType, DistributionType, PetriNet
from src.domain.patterns import PatternResult
from src.domain.patterns.base import BasePattern
from src.domain.patterns.registry import get_registry
from src.domain.patterns.router import RoutingStrategy

# Node dimensions for bounding-box calculations (must match frontend CSS)
_PLACE_W: float = 56.0
_PLACE_H: float = 56.0
_TRANS_W: float = 28.0
_TRANS_H: float = 64.0

#: Patterns with non-standard param handling (list/dict params, or
#: rate/interval duality) that keep a hand-written add_X method below
#: instead of the generic one _make_builder_method would install. Hoisted
#: to module level (out of _install_builder_methods) so other layers,
#: notably agent_toolkit/catalog.py's signature-drift test, can cross-
#: check their own "which patterns are hand-written" list against this
#: one without duplicating it.
_EXPLICIT_METHODS = {
    "generator", "machine", "assembly", "router", "conveyor",
    "conveyor_workstation", "merge", "duplicate", "priority_choice",
    "multi_resource", "transport_agent", "nonstationary_generator",
    "fork_join", "resource_set",
}


class PetriNetBuilder:
    """
    Builder for constructing Petri nets from high-level patterns.

    This class orchestrates the composition of patterns (Generator, Machine, etc.)
    into complete queueing system models. It handles:
    - Automatic Sugiyama hierarchical layout after each pattern addition
    - Pattern instance registry for group-level positioning
    - Connection between patterns

    Usage:
        builder = PetriNetBuilder()
        gen = builder.add_generator("Arrivals", interval=40.0)
        machine = builder.add_machine("Lathe", processing_time=60.0, channels=3)
        builder.connect(gen.output_place_id, machine.input_place_id)
        net = builder.build()
    """

    def __init__(self, name: str = "PetriNet") -> None:
        self._net = PetriNet(name=name)
        self._x_cursor: float = 100.0
        self._y_cursor: float = 200.0
        self._x_step: float = 500.0
        self._y_step: float = 150.0
        self._pattern_instances: dict[str, dict] = {}
        self._layout_direction: str = "LR"
        self._custom_layout_locked: bool = False
        # Cache of {pattern_name: {x, y, width, height, type}} populated by
        # the most recent auto_layout() call. Used by get_pattern_bounds()
        # and serialised through extra_state() so the frontend can render
        # group rectangles without re-running layout.
        self._cluster_bounds: dict[str, dict] = {}
        self._populate_patterns()
        self._install_builder_methods()

    def _populate_patterns(self) -> None:
        self._patterns: dict[str, BasePattern] = {
            name: cls() for name, cls in get_registry().items()
        }

    def _install_builder_methods(self) -> None:
        """Auto-generate add_X methods for standard patterns.

        Standard patterns have simple scalar params forwarded directly to
        apply(). Non-standard patterns (those with list/dict params, or
        rate/interval duality) keep explicit methods defined below.
        """
        for snake_name, pattern in self._patterns.items():
            if snake_name in _EXPLICIT_METHODS:
                continue
            if hasattr(self, f"add_{snake_name}"):
                continue

            method = _make_builder_method(snake_name, pattern)
            setattr(self, f"add_{snake_name}", method.__get__(self, type(self)))

    @property
    def net(self) -> PetriNet:
        """Access the underlying PetriNet."""
        return self._net

    def _advance_cursor(self, width: float = 500.0) -> tuple[float, float]:
        """Get current position and advance cursor."""
        x, y = self._x_cursor, self._y_cursor
        self._x_cursor += width
        return x, y

    def _apply_pattern(self, pattern: BasePattern, **kwargs) -> PatternResult:
        """Call one pattern's apply(), rolling the net back to exactly its
        prior state if apply() raises partway through.

        Every pattern builds several places/transitions/arcs in a fixed
        sequence with no transaction of its own (see e.g. MachinePattern.
        apply: place, place, transition, place, transition, place, then six
        arcs, each a separate net.add_* call). A failure partway through --
        typically a name collision on one of the LATER auto-derived names,
        like "{name}_Free" already existing from something else in the net
        -- used to leave every place/transition added before that point
        stranded: a real, reachable half-built "Foo_Queue" place with none
        of the rest of the pattern around it, visible to every later
        add_*/list_elements call and exported right along with everything
        else. Diffing ids before/after and undoing through the net's own
        remove_place/remove_transition (which already cascade-delete any
        arc touching what they remove) makes apply() all-or-nothing from
        every caller's point of view, exactly like a failed add_place/
        add_transition/add_arc already is on its own.
        """
        net = self._net
        before_places = {p.id for p in net.places}
        before_transitions = {t.id for t in net.transitions}
        before_arcs = {a.id for a in net.arcs}
        try:
            return pattern.apply(net=net, **kwargs)
        except Exception:
            for arc_id in [a.id for a in net.arcs if a.id not in before_arcs]:
                net.remove_arc(arc_id)
            for tid in [t.id for t in net.transitions if t.id not in before_transitions]:
                net.remove_transition(tid)
            for pid in [p.id for p in net.places if p.id not in before_places]:
                net.remove_place(pid)
            raise

    def _post_add(
        self,
        name: str,
        pattern_type: str,
        result: PatternResult,
    ) -> PatternResult:
        """Register pattern instance and trigger layout (unless locked)."""
        self._pattern_instances[name] = {
            "type": pattern_type,
            "place_ids": list(result.place_ids),
            "transition_ids": list(result.transition_ids),
            "input_place_id": result.interface.input_place_id,
            "output_place_id": result.interface.output_place_id,
            "metadata": dict(result.metadata),
        }
        if not self._custom_layout_locked:
            stats = self._net.auto_layout(
                direction=self._layout_direction,
                pattern_instances=self._pattern_instances,
            )
            self._cluster_bounds = stats.get("cluster_bounds") or {}
        return result

    # -------------------------------------------------------------------------
    # Explicit pattern methods (non-standard param handling)
    # -------------------------------------------------------------------------

    def add_generator(
        self,
        name: str,
        interval: float,
        distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        batch_size: int = 1,
    ) -> PatternResult:
        """Add a Generator (Source) pattern."""
        x, y = self._advance_cursor(width=300.0)
        result = self._apply_pattern(
            self._patterns["generator"], instance_name=name, x=x, y=y,
            interval=interval, distribution=distribution,
            standard_deviation=standard_deviation, batch_size=batch_size,
        )
        return self._post_add(name, "generator", result)

    def add_machine(
        self,
        name: str,
        processing_time: float,
        distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        channels: int = 1,
    ) -> PatternResult:
        """Add a Machine (Server) pattern."""
        x, y = self._advance_cursor(width=500.0)
        result = self._apply_pattern(
            self._patterns["machine"], instance_name=name, x=x, y=y,
            processing_time=processing_time, distribution=distribution,
            standard_deviation=standard_deviation, channels=channels,
        )
        return self._post_add(name, "machine", result)

    def add_assembly(
        self,
        name: str,
        inputs: List[str | dict],
        assembly_time: float = 1.0,
        distribution: DistributionType = DistributionType.DET,
        priority: int = 1,
    ) -> PatternResult:
        """Add an Assembly (Join) pattern."""
        x, y = self._advance_cursor(width=300.0)
        result = self._apply_pattern(
            self._patterns["assembly"], instance_name=name, x=x, y=y,
            inputs=inputs, assembly_time=assembly_time,
            distribution=distribution, priority=priority,
        )
        return self._post_add(name, "assembly", result)

    def add_router(
        self,
        name: str,
        routes: List[dict],
        strategy: RoutingStrategy = RoutingStrategy.PROBABILITY,
    ) -> PatternResult:
        """Add a Router (Splitter) pattern."""
        x, y = self._advance_cursor(width=300.0)
        result = self._apply_pattern(
            self._patterns["router"], instance_name=name, x=x, y=y,
            routes=routes, strategy=strategy,
        )
        return self._post_add(name, "router", result)

    def add_conveyor(
        self,
        name: str,
        stations: List[dict],
        transport_time: float = 5.0,
    ) -> PatternResult:
        """Add a Conveyor (Sequential Stations) pattern."""
        width = len(stations) * 600.0 + 200.0
        x, y = self._advance_cursor(width=width)
        result = self._apply_pattern(
            self._patterns["conveyor"], instance_name=name, x=x, y=y,
            stations=stations, transport_time=transport_time,
        )
        return self._post_add(name, "conveyor", result)

    def add_conveyor_workstation(
        self,
        name: str,
        processing_time: float = 1.0,
        distribution: DistributionType = DistributionType.EXP,
        transport_time: float = 1.0,
        channels: int = 1,
    ) -> PatternResult:
        """Add a ConveyorWorkstation (Try-or-Bypass) pattern."""
        x, y = self._advance_cursor(width=300.0)
        result = self._apply_pattern(
            self._patterns["conveyor_workstation"], instance_name=name, x=x, y=y,
            processing_time=processing_time, distribution=distribution,
            transport_time=transport_time, channels=channels,
        )
        return self._post_add(name, "conveyor_workstation", result)

    def add_transport_agent(
        self,
        name: str,
        grab_time: float = 8.0,
        grab_deviation: float = 1.0,
        grab_distribution: DistributionType = DistributionType.UNIF,
        move_time: float = 6.0,
        move_distribution: DistributionType = DistributionType.DET,
        release_time: float = 8.0,
        release_deviation: float = 1.0,
        release_distribution: DistributionType = DistributionType.UNIF,
        return_time: Optional[float] = None,
        return_distribution: DistributionType = DistributionType.DET,
    ) -> PatternResult:
        """Add a TransportAgent (cyclic resource) pattern."""
        x, y = self._advance_cursor(width=600.0)
        result = self._apply_pattern(
            self._patterns["transport_agent"], instance_name=name, x=x, y=y,
            grab_time=grab_time, grab_deviation=grab_deviation,
            grab_distribution=grab_distribution,
            move_time=move_time, move_distribution=move_distribution,
            release_time=release_time, release_deviation=release_deviation,
            release_distribution=release_distribution,
            return_time=return_time, return_distribution=return_distribution,
        )
        return self._post_add(name, "transport_agent", result)

    def add_priority_choice(
        self,
        name: str,
        resource_place_ids: List[dict] | None = None,
        primary_delay: float = 0.0,
        alternative_delay: float = 0.0,
        primary_name: str = "Success",
        alternative_name: str = "Fallback",
    ) -> PatternResult:
        """Add a PriorityChoice pattern for resource-dependent branching."""
        x, y = self._advance_cursor(width=300.0)
        result = self._apply_pattern(
            self._patterns["priority_choice"], instance_name=name, x=x, y=y,
            resource_place_ids=resource_place_ids,
            primary_delay=primary_delay, alternative_delay=alternative_delay,
            primary_name=primary_name, alternative_name=alternative_name,
        )
        return self._post_add(name, "priority_choice", result)

    def add_merge(
        self,
        name: str,
        inputs: List[str],
    ) -> PatternResult:
        """Add a Merge (OR-join) pattern."""
        x, y = self._advance_cursor(width=300.0)
        result = self._apply_pattern(
            self._patterns["merge"], instance_name=name, x=x, y=y, inputs=inputs,
        )
        return self._post_add(name, "merge", result)

    def add_duplicate(
        self,
        name: str,
        outputs: List[str],
    ) -> PatternResult:
        """Add a Duplicate (Broadcast) pattern."""
        x, y = self._advance_cursor(width=300.0)
        result = self._apply_pattern(
            self._patterns["duplicate"], instance_name=name, x=x, y=y, outputs=outputs,
        )
        return self._post_add(name, "duplicate", result)

    def add_multi_resource(
        self,
        name: str,
        resources: List[dict],
        processing_time: float,
        distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
    ) -> PatternResult:
        """Add a MultiResource (AND-Resource) pattern."""
        x, y = self._advance_cursor(width=500.0)
        result = self._apply_pattern(
            self._patterns["multi_resource"], instance_name=name, x=x, y=y,
            resources=resources, processing_time=processing_time,
            distribution=distribution, standard_deviation=standard_deviation,
        )
        return self._post_add(name, "multi_resource", result)

    def add_nonstationary_generator(
        self,
        name: str,
        schedule: List[dict],
        batch_size: int = 1,
    ) -> PatternResult:
        """Add a NonStationaryGenerator (time-varying arrivals) pattern."""
        width = len(schedule) * 200.0 + 400.0
        x, y = self._advance_cursor(width=width)
        result = self._apply_pattern(
            self._patterns["nonstationary_generator"], instance_name=name, x=x, y=y,
            schedule=schedule, batch_size=batch_size,
        )
        return self._post_add(name, "nonstationary_generator", result)

    def add_fork_join(
        self,
        name: str,
        n_branches: int = 2,
        branch_times: Optional[List[float]] = None,
        branch_distribution: DistributionType = DistributionType.EXP,
    ) -> PatternResult:
        """Add a ForkJoin (AND-split/AND-join) pattern for parallel branches."""
        if branch_times is None:
            branch_times = [30.0] * n_branches
        x, y = self._advance_cursor(width=800.0)
        result = self._apply_pattern(
            self._patterns["fork_join"], instance_name=name, x=x, y=y,
            n_branches=n_branches,
            branch_times=branch_times,
            branch_distribution=branch_distribution,
        )
        return self._post_add(name, "fork_join", result)

    def add_resource_set(
        self,
        name: str,
        resources: List[dict],
        standard_deviation: float = 0.0,
    ) -> PatternResult:
        """Add a ResourceSet — entity seizes first available alternative resource."""
        width = max(600.0, len(resources) * 250.0)
        x, y = self._advance_cursor(width=width)
        result = self._apply_pattern(
            self._patterns["resource_set"], instance_name=name, x=x, y=y,
            resources=resources,
            standard_deviation=standard_deviation,
        )
        return self._post_add(name, "resource_set", result)

    # -------------------------------------------------------------------------
    # Low-level element methods (custom topology)
    # -------------------------------------------------------------------------

    def add_raw_place(
        self,
        name: str,
        tokens: int = 0,
        tag: Optional[str] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
    ) -> str:
        """Add a single place directly. Returns the place ID."""
        if x is None or y is None:
            _x, _y = self._advance_cursor(width=100.0)
            x = x if x is not None else _x
            y = y if y is not None else _y
        place = self._net.add_place(name=name, tokens=tokens, tag=tag, x=x, y=y)
        return place.id

    def add_raw_transition(
        self,
        name: str,
        distribution: Optional[DistributionType] = None,
        mean_delay: float = 0.0,
        standard_deviation: float = 0.0,
        priority: int = 1,
        probability: Optional[float] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
    ) -> str:
        """Add a single transition directly. Returns the transition ID."""
        if x is None or y is None:
            _x, _y = self._advance_cursor(width=100.0)
            x = x if x is not None else _x
            y = y if y is not None else _y
        transition = self._net.add_transition(
            name=name,
            mean_delay=mean_delay,
            distribution=distribution,
            standard_deviation=standard_deviation,
            priority=priority,
            probability=probability,
            x=x,
            y=y,
        )
        return transition.id

    def add_raw_arc(
        self,
        source_id: str,
        target_id: str,
        weight: int = 1,
        arc_type: str = "normal",
    ) -> str:
        """Add an arc between a place and transition. Returns the arc ID."""
        from src.domain.models.arc import ArcType as ArcTypeEnum
        arc_type_enum = ArcTypeEnum(arc_type)
        arc = self._net.add_arc(
            source_id=source_id,
            target_id=target_id,
            weight=weight,
            arc_type=arc_type_enum,
        )
        return arc.id

    # -------------------------------------------------------------------------
    # Low-level update/remove methods
    # -------------------------------------------------------------------------

    def set_positions(self, positions: list[dict]) -> list[str]:
        """Update x,y coordinates for places and/or transitions. Returns updated IDs."""
        return self._net.set_element_positions(positions)

    def find_elements(
        self,
        name_pattern: str = "",
        element_type: Optional[str] = None,
    ) -> list[dict]:
        """Search elements by name substring and optional type filter."""
        return self._net.find_elements(name_pattern=name_pattern, element_type=element_type)

    def get_bounds(self) -> dict:
        """Return the bounding box of all elements in the net."""
        return self._net.get_bounds()

    def move_elements_by(self, element_ids: list[str], dx: float, dy: float) -> list[str]:
        """Shift elements by a relative (dx, dy) offset. Returns updated IDs."""
        return self._net.move_elements_by(element_ids=element_ids, dx=dx, dy=dy)

    def auto_layout(self, direction: Optional[str] = None) -> dict:
        """Re-layout the net using pattern-aware Sugiyama layout.

        If *direction* is given, also updates the stored layout direction and
        clears the custom-layout lock so subsequent add_X calls resume
        automatic layout.
        """
        if direction is not None:
            self._layout_direction = direction
            self._custom_layout_locked = False
        stats = self._net.auto_layout(
            direction=self._layout_direction,
            pattern_instances=self._pattern_instances,
        )
        self._cluster_bounds = stats.get("cluster_bounds") or {}
        return stats

    def modify_place(self, place_id: str, **kwargs) -> str:
        """Update fields on an existing place. Returns the place ID."""
        self._net.update_place(place_id, **kwargs)
        return place_id

    def modify_transition(self, transition_id: str, **kwargs) -> str:
        """Update fields on an existing transition. Returns the transition ID."""
        self._net.update_transition(transition_id, **kwargs)
        return transition_id

    def modify_arc(self, arc_id: str, **kwargs) -> str:
        """Update fields on an existing arc. Returns the arc ID."""
        self._net.update_arc(arc_id, **kwargs)
        return arc_id

    def remove_place(self, place_id: str) -> list[str]:
        """Remove a place and all its connected arcs. Returns warnings."""
        self._net.remove_place(place_id)
        self._purge_pattern_element(place_id)
        return self._orphan_warnings()

    def remove_transition(self, transition_id: str) -> list[str]:
        """Remove a transition and all its connected arcs. Returns warnings."""
        self._net.remove_transition(transition_id)
        self._purge_pattern_element(transition_id)
        return self._orphan_warnings()

    def remove_arc(self, arc_id: str) -> list[str]:
        """Remove a single arc. Returns warnings."""
        self._net.remove_arc(arc_id)
        return self._orphan_warnings()

    def _purge_pattern_element(self, element_id: str) -> None:
        """Remove *element_id* from any pattern instance registry entries."""
        for inst in self._pattern_instances.values():
            if element_id in inst.get("place_ids", []):
                inst["place_ids"].remove(element_id)
            if element_id in inst.get("transition_ids", []):
                inst["transition_ids"].remove(element_id)

    def _orphan_warnings(self) -> list[str]:
        """Detect orphaned/disconnected elements after a removal."""
        warnings = []
        for place in self._net.places:
            has_in = any(a.target_id == place.id for a in self._net.arcs)
            has_out = any(a.source_id == place.id for a in self._net.arcs)
            if not has_in and not has_out:
                warnings.append(
                    f"Place '{place.name}' ({place.id}) is now isolated (no arcs)"
                )
            elif not has_out:
                warnings.append(
                    f"Place '{place.name}' ({place.id}) is now a dead end (no outgoing arcs)"
                )
            elif not has_in:
                warnings.append(
                    f"Place '{place.name}' ({place.id}) is now unreachable (no incoming arcs)"
                )
        for trans in self._net.transitions:
            has_in = any(a.target_id == trans.id for a in self._net.arcs)
            has_out = any(a.source_id == trans.id for a in self._net.arcs)
            if not has_in:
                warnings.append(
                    f"Transition '{trans.name}' ({trans.id}) has no input arcs"
                )
            if not has_out:
                warnings.append(
                    f"Transition '{trans.name}' ({trans.id}) has no output arcs"
                )
        return warnings

    # -------------------------------------------------------------------------
    # Pattern instance management
    # -------------------------------------------------------------------------

    def get_pattern_bounds(self, name: str) -> dict:
        """Return the axis-aligned bounding box of a named pattern instance.

        Returns:
            Dict with min_x, max_x, min_y, max_y, width, height, center_x,
            center_y. All zeros when the pattern has no surviving elements.

        Raises:
            ValueError: if *name* is not registered.
        """
        instance = self._pattern_instances.get(name)
        if instance is None:
            raise ValueError(
                f"Pattern instance '{name}' not found. "
                f"Known instances: {list(self._pattern_instances)}"
            )

        xs_lo: list[float] = []
        xs_hi: list[float] = []
        ys_lo: list[float] = []
        ys_hi: list[float] = []

        for pid in instance.get("place_ids", []):
            p = self._net.get_place(pid)
            if p:
                xs_lo.append(p.graphics.x)
                xs_hi.append(p.graphics.x + _PLACE_W)
                ys_lo.append(p.graphics.y)
                ys_hi.append(p.graphics.y + _PLACE_H)

        for tid in instance.get("transition_ids", []):
            t = self._net.get_transition(tid)
            if t:
                xs_lo.append(t.graphics.x)
                xs_hi.append(t.graphics.x + _TRANS_W)
                ys_lo.append(t.graphics.y)
                ys_hi.append(t.graphics.y + _TRANS_H)

        if not xs_lo:
            return {
                "min_x": 0.0, "max_x": 0.0, "min_y": 0.0, "max_y": 0.0,
                "width": 0.0, "height": 0.0, "center_x": 0.0, "center_y": 0.0,
            }

        min_x, max_x = min(xs_lo), max(xs_hi)
        min_y, max_y = min(ys_lo), max(ys_hi)
        return {
            "min_x": min_x, "max_x": max_x,
            "min_y": min_y, "max_y": max_y,
            "width": max_x - min_x,
            "height": max_y - min_y,
            "center_x": (min_x + max_x) / 2.0,
            "center_y": (min_y + max_y) / 2.0,
        }

    def list_pattern_instances(self) -> list[dict]:
        """Return a list of all registered pattern instances with their bounds."""
        result = []
        for name, inst in self._pattern_instances.items():
            try:
                bounds = self.get_pattern_bounds(name)
            except ValueError:
                bounds = {}
            result.append({
                "name": name,
                "type": inst["type"],
                "place_ids": inst["place_ids"],
                "transition_ids": inst["transition_ids"],
                "input_place_id": inst.get("input_place_id"),
                "output_place_id": inst.get("output_place_id"),
                **bounds,
            })
        return result

    def arrange_patterns(self, placements: list[dict]) -> dict:
        """Move named pattern instances to desired top-left positions.

        Each placement is ``{"name": str, "x": float, "y": float}`` where
        ``x, y`` is the desired top-left corner of the pattern's bounding box.
        After this call, automatic layout is suspended — subsequent add_X
        calls will use cursor-based placement instead of re-running Sugiyama.
        Call ``auto_layout()`` or ``set_layout_direction()`` to resume.

        Returns:
            Dict with "arranged" (list of moved names) and "layout_locked" (True).

        Raises:
            ValueError: if any pattern name is not found.
        """
        arranged = []
        for pl in placements:
            name = pl["name"]
            target_x = float(pl["x"])
            target_y = float(pl["y"])

            bounds = self.get_pattern_bounds(name)
            dx = target_x - bounds["min_x"]
            dy = target_y - bounds["min_y"]

            instance = self._pattern_instances[name]
            all_ids = instance.get("place_ids", []) + instance.get("transition_ids", [])
            self._net.move_elements_by(all_ids, dx=dx, dy=dy)
            arranged.append(name)

        self._custom_layout_locked = True
        # Bounds from layout cache are now stale — clients should fall back
        # to the element-derived bounds via get_pattern_bounds().
        self._cluster_bounds = {}
        return {"arranged": arranged, "layout_locked": True}

    @property
    def pattern_instances(self) -> dict[str, dict]:
        """The patterns built in this net, by instance name, in creation
        order. Read-only copy: membership is maintained by `_post_add`."""
        return dict(self._pattern_instances)

    def adopt_pattern_instances(self, instances: dict[str, dict]) -> None:
        """Take over pattern registrations whose elements now live in this
        net, and re-run the layout so it is cluster-aware again.

        Used when a flat net is split into one Petri-object per pattern
        (PetriNetSession.ensure_patterns_in_objects): the elements move, and
        the registration that says which of them form one machine has to
        move with them, or the object's own net is just loose places and
        transitions to every later layout and pattern lookup.
        """
        self._pattern_instances = dict(instances)
        if not self._custom_layout_locked:
            self.auto_layout()

    def drop_pattern_instances(self, names: list[str]) -> None:
        """Forget pattern registrations whose elements have left this net."""
        for name in names:
            self._pattern_instances.pop(name, None)

    @property
    def layout_direction(self) -> str:
        """Which way this builder currently lays its net out: "LR" or "TB"."""
        return self._layout_direction

    def set_layout_direction(self, direction: str) -> dict:
        """Change the layout direction, clear the lock, and re-layout.

        Returns:
            Dict with "direction" and the layout stats from auto_layout().
        """
        if direction not in ("LR", "TB"):
            raise ValueError(f"direction must be 'LR' or 'TB', got {direction!r}")
        self._layout_direction = direction
        self._custom_layout_locked = False
        stats = self._net.auto_layout(
            direction=direction,
            pattern_instances=self._pattern_instances,
        )
        self._cluster_bounds = stats.get("cluster_bounds") or {}
        return {"direction": direction, **stats}

    def cluster_bounds(self) -> dict[str, dict]:
        """Return cached pattern-group bounding boxes from last auto_layout.

        Each entry is ``{"x", "y", "width", "height", "type"}`` keyed by
        pattern name. Empty dict when no layout has been performed since the
        last `arrange_patterns` call (manual layout invalidates the cache).
        """
        return dict(self._cluster_bounds)

    def extra_state(self) -> dict:
        """Return extra state fields for serialization into net_data."""
        return {
            "_pattern_instances": self._pattern_instances,
            "_layout_direction": self._layout_direction,
            "_custom_layout_locked": self._custom_layout_locked,
            "_cluster_bounds": self._cluster_bounds,
        }

    def list_elements(self) -> dict:
        """List all elements with their current parameters."""
        return {
            "places": [
                {
                    "id": p.id, "name": p.name, "tokens": p.tokens,
                    "tag": p.tag, "x": p.graphics.x, "y": p.graphics.y,
                }
                for p in self._net.places
            ],
            "transitions": [
                {
                    "id": t.id, "name": t.name,
                    "distribution": t.distribution.value if t.distribution else None,
                    "mean_delay": t.mean_delay,
                    "standard_deviation": t.standard_deviation,
                    "priority": t.priority,
                    "probability": t.probability,
                    "x": t.graphics.x, "y": t.graphics.y,
                }
                for t in self._net.transitions
            ],
            "arcs": [
                {
                    "id": a.id, "source_id": a.source_id,
                    "target_id": a.target_id, "weight": a.weight,
                    "arc_type": a.arc_type.value,
                }
                for a in self._net.arcs
            ],
        }

    # -------------------------------------------------------------------------
    # Connection methods
    # -------------------------------------------------------------------------

    def connect_schedule_gate(
        self,
        schedule_result: PatternResult,
        target_transition_id: str,
    ) -> None:
        """Gate a transition with a schedule's signal via READ arc."""
        signal_place_id = schedule_result.metadata.get("signal_place_id")
        if not signal_place_id:
            raise ValueError(
                "schedule_result is not a ScheduledAvailability "
                "(missing signal_place_id in metadata)"
            )
        self._net.add_arc(
            source_id=signal_place_id,
            target_id=target_transition_id,
            arc_type=ArcType.READ,
        )

    def connect(
        self,
        source_place_id: str,
        target_place_id: str,
    ) -> None:
        """Connect two patterns by merging output place into input place."""
        t_transfer = self._net.add_transition(
            name=f"Transfer_{len(self._net.transitions)}",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=(self._get_place_x(source_place_id) + self._get_place_x(target_place_id)) / 2,
            y=self._y_cursor + 50,
        )
        self._net.add_arc(source_id=source_place_id, target_id=t_transfer.id)
        self._net.add_arc(source_id=t_transfer.id, target_id=target_place_id)

    def connect_direct(
        self,
        output_place_id: str,
        input_transition_id: str,
    ) -> None:
        """Directly connect an output place to an input transition."""
        self._net.add_arc(source_id=output_place_id, target_id=input_transition_id)

    def connect_bypass(
        self,
        source_result: PatternResult,
        target_result: PatternResult,
    ) -> None:
        """Connect bypass output of one workstation to input of next."""
        to_next_id = source_result.place_ids[3]
        approach_id = target_result.interface.input_place_id
        t_transfer = self._net.add_transition(
            name=f"Transfer_{len(self._net.transitions)}",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=(self._get_place_x(to_next_id) + self._get_place_x(approach_id)) / 2,
            y=self._y_cursor + 50,
        )
        self._net.add_arc(source_id=to_next_id, target_id=t_transfer.id)
        self._net.add_arc(source_id=t_transfer.id, target_id=approach_id)

    def connect_return_loop(
        self,
        source_result: PatternResult,
        target_place_id: str,
        return_delay: float = 5.0,
    ) -> None:
        """Create return loop from last station bypass to first station."""
        to_next_id = source_result.place_ids[3]
        t_return = self._net.add_transition(
            name="Return",
            mean_delay=return_delay,
            distribution=DistributionType.DET,
            x=self._get_place_x(to_next_id) + 100,
            y=self._y_cursor + 100,
        )
        self._net.add_arc(source_id=to_next_id, target_id=t_return.id)
        self._net.add_arc(source_id=t_return.id, target_id=target_place_id)

    def connect_bounded_consumer(
        self,
        queue_result: PatternResult,
        consumer_result: PatternResult,
    ) -> None:
        """Wire capacity recycling between a BoundedQueue and its consumer."""
        capacity_place_id = queue_result.metadata.get("capacity_place_id")
        if not capacity_place_id:
            raise ValueError(
                "queue_result is not a BoundedQueue (missing capacity_place_id)"
            )
        consume_ids = consumer_result.metadata.get("consume_transition_ids") or []
        if not consume_ids:
            raise ValueError(
                "consumer pattern does not expose consume_transition_ids; "
                "cannot wire capacity recycling automatically. "
                "Add an arc from your consumer's start transition to "
                f"{capacity_place_id} manually."
            )
        self._net.add_arc(source_id=consume_ids[0], target_id=capacity_place_id)

    def connect_blocking_consumer(
        self,
        blocking_machine_result: PatternResult,
        downstream_result: PatternResult,
    ) -> None:
        """Wire capacity recycling for a BlockingMachine and its downstream consumer."""
        capacity_place_id = blocking_machine_result.metadata.get("capacity_place_id")
        if not capacity_place_id:
            raise ValueError(
                "blocking_machine_result is not a BlockingMachine "
                "(missing capacity_place_id in metadata)"
            )
        consume_ids = downstream_result.metadata.get("consume_transition_ids") or []
        if not consume_ids:
            raise ValueError(
                "downstream pattern does not expose consume_transition_ids; "
                "cannot wire capacity recycling automatically. "
                "Add an arc from your downstream's start transition to "
                f"{capacity_place_id} manually."
            )
        self._net.add_arc(source_id=consume_ids[0], target_id=capacity_place_id)

    def connect_wip_return(
        self,
        controller_result: PatternResult,
        exit_place_id: str,
    ) -> None:
        """Wire the WIP return arc."""
        wip_place_id = controller_result.metadata.get("wip_place_id")
        if not wip_place_id:
            raise ValueError(
                "controller_result is not a WIPController (missing wip_place_id)"
            )
        producer_transition_ids = {
            arc.source_id
            for arc in self._net.arcs
            if arc.target_id == exit_place_id
            and self._net.get_transition(arc.source_id) is not None
        }
        if not producer_transition_ids:
            raise ValueError(
                f"No transitions produce into exit_place_id={exit_place_id!r}. "
                "Wire the WIP-controlled section before calling connect_wip_return."
            )
        for trans_id in producer_transition_ids:
            self._net.add_arc(source_id=trans_id, target_id=wip_place_id)

    def _get_place_x(self, place_id: str) -> float:
        """Get X coordinate of a place."""
        place = self._net.get_place(place_id)
        return place.graphics.x if place else 0.0

    # -------------------------------------------------------------------------
    # Build methods
    # -------------------------------------------------------------------------

    def build(self) -> PetriNet:
        """Finalize and return the constructed PetriNet."""
        return self._net

    def validate(self) -> tuple[bool, list[str]]:
        """Validate the constructed net."""
        return self._net.validate_topology()


def _make_builder_method(snake_name: str, pattern: BasePattern):
    """Create an add_X method that delegates to pattern.apply() with cursor advance."""
    sig = inspect.signature(pattern.apply)
    user_params = {
        name: param for name, param in sig.parameters.items()
        if name not in ("self", "net", "instance_name", "x", "y")
    }

    def method(self, name: str, **kwargs) -> PatternResult:
        x, y = self._advance_cursor(width=pattern.tool_cursor_width)
        result = self._apply_pattern(
            self._patterns[snake_name], instance_name=name, x=x, y=y, **kwargs,
        )
        return self._post_add(name, snake_name, result)

    method.__name__ = f"add_{snake_name}"
    method.__qualname__ = f"PetriNetBuilder.add_{snake_name}"
    method.__doc__ = f"Add a {pattern.name} pattern."

    params = [
        inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter("name", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str),
    ]
    for pname, param in user_params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            params.append(param)
        else:
            params.append(inspect.Parameter(
                pname,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=param.annotation,
                default=param.default,
            ))
    method.__signature__ = inspect.Signature(params, return_annotation=PatternResult)

    return method
