"""Petri Net Optimizer - simplifies networks by removing redundant elements.

This module implements classical Petri net reduction techniques to optimize
networks built from patterns. When patterns are connected, intermediate
"Transfer" transitions with zero delay are often created, which can be
eliminated to produce cleaner, equivalent networks.

Reduction techniques implemented:
1. Fusion of Series Transitions (FST) - merge sequential zero-delay transitions
2. Fusion of Series Places (FSP) - merge places connected via zero-delay transitions
3. Elimination of Redundant Places (ERP) - remove duplicate intermediate places
"""

import math
from dataclasses import dataclass, field
from typing import Optional

from src.domain import PetriNet, Place, Transition, Arc, DistributionType


@dataclass
class OptimizationStats:
    """Statistics about optimizations performed."""

    places_removed: int = 0
    transitions_removed: int = 0
    arcs_removed: int = 0
    arcs_redirected: int = 0
    fusions_performed: int = 0

    def __str__(self) -> str:
        return (
            f"Optimization: removed {self.places_removed} places, "
            f"{self.transitions_removed} transitions, {self.arcs_removed} arcs; "
            f"redirected {self.arcs_redirected} arcs; {self.fusions_performed} fusions"
        )


class PetriNetOptimizer:
    """
    Optimizes Petri nets by applying reduction rules.

    The optimizer preserves semantic equivalence while reducing the
    number of elements in the network. Key optimizations:

    1. Remove "pass-through" transitions:
       [P1] -> (T_zero) -> [P2] -> (T_next)
       becomes:
       [P1] -> (T_next)  (P2 is removed, arcs redirected)

    2. Merge sequential zero-delay transitions:
       [P1] -> (T1_zero) -> [P2] -> (T2_zero) -> [P3]
       becomes:
       [P1] -> (T_merged) -> [P3]

    3. Remove redundant intermediate places:
       Places that only serve as pass-through between transitions
       with no additional semantics (no initial tokens, single input/output)
    """

    def __init__(self, net: PetriNet, protected_ids: frozenset[str] = frozenset()):
        """
        Initialize optimizer with a Petri net.

        Args:
            net: The PetriNet to optimize (will be modified in-place)
            protected_ids: Elements this run must not remove or fuse away.
                Used to preserve a pattern's interface places, which are
                its ports rather than redundancy: fusing the place where
                one pattern hands off to the next merges the two into a
                single place, and that place is the seam a composed model
                would be cut along. Once it is gone the model can no longer
                be separated into Petri-objects at all -- see
                PetriNetSession.ensure_patterns_in_objects.
        """
        self.net = net
        self.stats = OptimizationStats()
        self._protected = frozenset(protected_ids)

    def optimize(self) -> OptimizationStats:
        """
        Run all optimization passes on the network.

        Returns:
            Statistics about optimizations performed
        """
        # Run multiple passes until no more optimizations possible
        changed = True
        max_iterations = 100  # Safety limit
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1

            # Try each optimization technique
            if self._fuse_series_places():
                changed = True

            if self._eliminate_duplicate_transitions():
                changed = True

            if self._eliminate_sink_transitions():
                changed = True

            if self._merge_duplicate_arcs():
                changed = True

        return self.stats

    def _is_immediate_transition(self, transition: Transition) -> bool:
        """Check if transition has zero delay (immediate)."""
        return is_immediate(transition)

    def _is_simple_intermediate_place(self, place: Place) -> bool:
        """
        Check if place is a simple intermediate (can be removed).

        A simple intermediate place:
        - Has no initial tokens
        - Has no semantic tag (tagged places are observable instrumentation)
        - Has exactly one input transition
        - Has exactly one output transition
        - Input/output arcs have weight 1
        """
        if place.tokens > 0:
            return False

        # Tagged places (e.g. throughput counters) must not be removed.
        if place.tag is not None:
            return False

        input_trans = self.net.get_input_transitions(place.id)
        output_trans = self.net.get_output_transitions(place.id)

        if len(input_trans) != 1 or len(output_trans) != 1:
            return False

        # Check arc weights
        input_arcs = self.net.get_arcs_to(place.id)
        output_arcs = self.net.get_arcs_from(place.id)

        if len(input_arcs) != 1 or len(output_arcs) != 1:
            return False

        if input_arcs[0].weight != 1 or output_arcs[0].weight != 1:
            return False

        return True

    def _is_sink_place(self, place: Place) -> bool:
        """
        Check if place is a sink (final accumulator with no outputs).

        Sink places should NOT be removed during optimization as they
        represent important storage points for completed items.
        """
        output_trans = self.net.get_output_transitions(place.id)
        return len(output_trans) == 0

    def _can_fuse_places(  # NOSONAR
        self,
        place1: Place,
        transition: Transition,
        place2: Place
    ) -> bool:
        """
        Check if two places connected via a transition can be fused.

        Fusion is valid when:
        - The transition is immediate (zero delay)
        - The transition has default priority (1)
        - place1 has exactly one output (this transition)
        - place2 has exactly one input (this transition)
        - place2 is NOT a sink place (final accumulator)
        - Arc weights are all 1
        - place2 has no initial tokens (tokens transfer to place1)
        """
        if not self._is_immediate_transition(transition):
            return False

        # A protected element is structure, not redundancy: fusing either
        # end of this pair, or dropping the transition between them, would
        # destroy a pattern boundary the caller asked to keep.
        if (
            place1.id in self._protected
            or place2.id in self._protected
            or transition.id in self._protected
        ):
            return False

        # Don't fuse if transition has non-default priority
        if transition.priority != 1:
            return False

        # IMPORTANT: Don't fuse if place2 is a sink (final accumulator)
        # Sink places are important storage points that should be preserved
        if self._is_sink_place(place2):
            return False

        # Tagged places (throughput counters) must not be fused away.
        if place1.tag is not None or place2.tag is not None:
            return False

        # place1 should have this transition as only output
        output_trans = self.net.get_output_transitions(place1.id)
        if len(output_trans) != 1 or output_trans[0].id != transition.id:
            return False

        # transition should have only place1 as input
        input_places = self.net.get_input_places(transition.id)
        if len(input_places) != 1 or input_places[0].id != place1.id:
            return False

        # transition should have only place2 as output
        output_places = self.net.get_output_places(transition.id)
        if len(output_places) != 1 or output_places[0].id != place2.id:
            return False

        # place2 should have this transition as only input
        input_trans = self.net.get_input_transitions(place2.id)
        if len(input_trans) != 1 or input_trans[0].id != transition.id:
            return False

        # Check arc weights
        arc_to_trans = self.net.get_arcs_from(place1.id)
        arc_from_trans = self.net.get_arcs_to(place2.id)

        if not arc_to_trans or not arc_from_trans:
            return False

        if arc_to_trans[0].weight != 1 or arc_from_trans[0].weight != 1:
            return False

        return True

    def _fuse_series_places(self) -> bool:
        """
        Fuse places connected by zero-delay transitions.

        Pattern: [P1] -> (T_zero) -> [P2]
        Result:  [P1] (absorbs P2's outputs, T removed)

        Returns:
            True if any fusion was performed
        """
        fused = False

        # Find candidates for fusion
        transitions_to_remove = []

        for trans in list(self.net.transitions):
            if not self._is_immediate_transition(trans):
                continue

            input_places = self.net.get_input_places(trans.id)
            output_places = self.net.get_output_places(trans.id)

            # Only handle simple 1-to-1 transfers
            if len(input_places) != 1 or len(output_places) != 1:
                continue

            place1 = input_places[0]
            place2 = output_places[0]

            if self._can_fuse_places(place1, trans, place2):
                # Perform fusion: redirect all outputs of place2 to place1
                self._fuse_place_into(place2, place1, trans)
                transitions_to_remove.append(trans)
                fused = True
                self.stats.fusions_performed += 1

        # Remove fused transitions
        for trans in transitions_to_remove:
            self._remove_transition(trans)

        return fused

    def _fuse_place_into(
        self,
        source_place: Place,
        target_place: Place,
        connecting_transition: Transition
    ) -> None:
        """
        Fuse source_place into target_place.

        All output arcs of source_place are redirected to start from target_place.
        The source_place and connecting_transition are marked for removal.
        """
        # Transfer tokens
        target_place.tokens += source_place.tokens

        # Redirect all output arcs from source_place to target_place
        output_arcs = self.net.get_arcs_from(source_place.id)
        for arc in output_arcs:
            arc.source_id = target_place.id
            self.stats.arcs_redirected += 1

        # Remove arcs to/from the connecting transition
        arcs_to_remove = []
        for arc in self.net.arcs:
            if arc.source_id == target_place.id and arc.target_id == connecting_transition.id:
                arcs_to_remove.append(arc)
            elif arc.source_id == connecting_transition.id and arc.target_id == source_place.id:
                arcs_to_remove.append(arc)

        for arc in arcs_to_remove:
            self._remove_arc(arc)

        # Remove source place
        self._remove_place(source_place)

    def _eliminate_sink_transitions(self) -> bool:  # NOSONAR
        """
        Eliminate sink transitions (zero-delay transitions with no outputs).

        These represent "terminator" patterns that just consume tokens.
        If the input place has only this transition as output, the place
        becomes a final storage (sink place) and the transition is removed.

        Returns:
            True if any elimination was performed
        """
        eliminated = False

        for trans in list(self.net.transitions):
            # Only process immediate transitions with no outputs
            if not self._is_immediate_transition(trans):
                continue

            output_arcs = self.net.get_arcs_from(trans.id)
            if len(output_arcs) > 0:
                continue  # Has outputs, not a sink

            # Skip transitions with non-default priority (they have semantic meaning)
            if trans.priority != 1:
                continue

            input_arcs = self.net.get_arcs_to(trans.id)

            # Handle dangling transitions with no inputs or outputs
            if len(input_arcs) == 0:
                self._remove_transition(trans)
                eliminated = True
                continue

            # Only handle simple single-input sink transitions
            if len(input_arcs) != 1:
                continue

            input_place = self.net.get_place(input_arcs[0].source_id)
            if not input_place:
                continue

            # Check if input place has only this transition as output
            place_outputs = self.net.get_output_transitions(input_place.id)
            if len(place_outputs) == 1 and place_outputs[0].id == trans.id:
                # This place becomes a final sink - just remove the transition
                self._remove_transition(trans)
                eliminated = True

        return eliminated

    def _eliminate_duplicate_transitions(self) -> bool:
        """
        Eliminate duplicate immediate transitions between same places.

        When two zero-delay transitions have the same inputs and outputs,
        keep only one.

        Returns:
            True if any elimination was performed
        """
        eliminated = False

        # Build signature for each immediate transition
        signatures = {}  # signature -> list of transitions

        for trans in self.net.transitions:
            if not self._is_immediate_transition(trans):
                continue

            input_arcs = sorted(
                [(a.source_id, a.weight) for a in self.net.get_arcs_to(trans.id)]
            )
            output_arcs = sorted(
                [(a.target_id, a.weight) for a in self.net.get_arcs_from(trans.id)]
            )

            sig = (tuple(input_arcs), tuple(output_arcs))

            if sig not in signatures:
                signatures[sig] = []
            signatures[sig].append(trans)

        # Remove duplicates
        for sig, transitions in signatures.items():
            if len(transitions) > 1:
                # Keep the first, remove the rest -- except that a protected
                # transition is always the one kept, never the one dropped.
                # sorted() is stable, so unprotected duplicates keep their
                # existing relative order behind it.
                ordered = sorted(
                    transitions, key=lambda t: t.id not in self._protected
                )
                for trans in ordered[1:]:
                    if trans.id in self._protected:
                        continue
                    self._remove_transition(trans)
                    eliminated = True

        return eliminated

    def _merge_duplicate_arcs(self) -> bool:
        """
        Merge duplicate arcs between same source and target.

        Returns:
            True if any merge was performed
        """
        merged = False
        seen = {}  # (source_id, target_id) -> arc

        arcs_to_remove = []

        for arc in self.net.arcs:
            key = (arc.source_id, arc.target_id)
            if key in seen:
                # Duplicate - merge weights into existing arc
                seen[key].weight += arc.weight
                arcs_to_remove.append(arc)
                merged = True
            else:
                seen[key] = arc

        for arc in arcs_to_remove:
            self._remove_arc(arc)

        return merged

    def _remove_place(self, place: Place) -> None:
        """Remove a place and all its connected arcs."""
        # Remove connected arcs
        arcs_to_remove = [
            arc for arc in self.net.arcs
            if arc.source_id == place.id or arc.target_id == place.id
        ]
        for arc in arcs_to_remove:
            self._remove_arc(arc)

        # Remove place
        self.net.places = [p for p in self.net.places if p.id != place.id]
        if place.id in self.net._node_index:
            del self.net._node_index[place.id]
        self.stats.places_removed += 1

    def _remove_transition(self, transition: Transition) -> None:
        """Remove a transition and all its connected arcs."""
        # Remove connected arcs
        arcs_to_remove = [
            arc for arc in self.net.arcs
            if arc.source_id == transition.id or arc.target_id == transition.id
        ]
        for arc in arcs_to_remove:
            self._remove_arc(arc)

        # Remove transition
        self.net.transitions = [t for t in self.net.transitions if t.id != transition.id]
        if transition.id in self.net._node_index:
            del self.net._node_index[transition.id]
        self.stats.transitions_removed += 1

    def _remove_arc(self, arc: Arc) -> None:
        """Remove an arc."""
        self.net.arcs = [a for a in self.net.arcs if a.id != arc.id]
        self.stats.arcs_removed += 1


def is_immediate(transition: Transition) -> bool:
    """Whether a transition fires with no delay."""
    return math.isclose(transition.mean_delay, 0.0) and (
        transition.distribution is None
        or transition.distribution == DistributionType.DET
    )


def is_transfer_transition(net: PetriNet, transition: Transition) -> bool:
    """Whether a transition is a plain pass-through: no delay, default
    priority, exactly one input place and one output place, both arcs of
    weight 1.

    This is the shape `PetriNetBuilder.connect` synthesizes to wire two
    patterns together, and it carries no behaviour of its own -- which is
    what makes it safe to remove, either by fusing the two places
    (PetriNetOptimizer) or by replacing it with a place-fusion link
    between them (PetriNetSession.ensure_patterns_in_objects).
    """
    if not is_immediate(transition) or transition.priority != 1:
        return False
    input_arcs = net.get_arcs_to(transition.id)
    output_arcs = net.get_arcs_from(transition.id)
    if len(input_arcs) != 1 or len(output_arcs) != 1:
        return False
    return input_arcs[0].weight == 1 and output_arcs[0].weight == 1


def optimize_petri_net(
    net: PetriNet, protected_ids: frozenset[str] = frozenset()
) -> tuple[PetriNet, OptimizationStats]:
    """
    Optimize a Petri net by removing redundant elements.

    This function applies various reduction techniques to simplify
    the network while preserving its behavioral semantics.

    Args:
        net: The PetriNet to optimize
        protected_ids: Elements that must survive this run untouched --
            see PetriNetOptimizer's own docstring for why a pattern's
            interface places belong in here when the net is destined to
            become a composed model.

    Returns:
        Tuple of (optimized_net, statistics)
    """
    optimizer = PetriNetOptimizer(net, protected_ids)
    stats = optimizer.optimize()
    return net, stats
