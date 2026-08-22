"""Simulation-time state objects for Petri net simulation.

These are mutable runtime wrappers — separate from the immutable Pydantic domain
model. Created once per simulation run from a domain PetriNet via build_sim_net().
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from src.core.logger import get_logger
from src.domain.models import Arc, ArcType, PetriNet

logger = get_logger("simulation")

INF_TIME = sys.float_info.max


@dataclass
class SimPlace:
    idx: int
    id: str
    name: str
    mark: int
    tag: str | None = None
    mean: float = 0.0
    observed_max: int = 0
    observed_min: int = 0

    def increase_mark(self, amount: int) -> None:
        self.mark += amount
        if self.mark > self.observed_max:
            self.observed_max = self.mark
        if self.mark < self.observed_min:
            self.observed_min = self.mark

    def decrease_mark(self, amount: int) -> None:
        self.mark -= amount
        if self.mark > self.observed_max:
            self.observed_max = self.mark
        if self.mark < self.observed_min:
            self.observed_min = self.mark

    def change_mean(self, dt_ratio: float) -> None:
        self.mean = self.mean + (self.mark - self.mean) * dt_ratio


@dataclass
class SimTransition:
    idx: int
    id: str
    name: str
    parameter: float
    deviation: float
    distribution: str | None
    priority: int
    probability: float
    # The owning ModelObject's own priority, for a composed model — 0 (and so
    # a no-op) for every transition of a flat, non-composed net. Conflict
    # resolution treats (object_priority, priority) as one combined key, not
    # two separate mechanisms — see PetriSimulator._find_active_transitions.
    # Java's PetriObjModel.go() keeps these as two genuinely separate
    # tie-breaks (an outer object-level scheduler, an inner per-object one),
    # which is why object priority there only ever matters when several
    # objects' NEXT SCHEDULED completions land on the exact same instant —
    # it does nothing for the far more common case of several objects each
    # having an immediate (zero-delay) transition ready to fire right now,
    # since each object's own cascade already ran to completion before the
    # outer scheduler ever compares objects against each other. Folding both
    # into one key here is a deliberate fix, not a straight port.
    object_priority: int = 0
    buffer: int = 0
    time_out: list[float] = field(default_factory=lambda: [INF_TIME])
    mean: float = 0.0
    observed_max: int = 0
    observed_min: int = 0
    in_places: list[int] = field(default_factory=list)
    in_quantities: list[int] = field(default_factory=list)
    inf_places: list[int] = field(default_factory=list)
    inf_quantities: list[int] = field(default_factory=list)
    out_places: list[int] = field(default_factory=list)
    out_quantities: list[int] = field(default_factory=list)
    _min_time: float = INF_TIME
    _min_channel: int = 0

    def min_event(self) -> None:
        self._min_time = INF_TIME
        self._min_channel = 0
        for i, t in enumerate(self.time_out):
            if t < self._min_time:
                self._min_time = t
                self._min_channel = i

    @property
    def min_time(self) -> float:
        self.min_event()
        return self._min_time

    @property
    def min_channel(self) -> int:
        return self._min_channel

    def change_mean(self, dt_ratio: float) -> None:
        self.mean = self.mean + (self.buffer - self.mean) * dt_ratio

    def condition(self, places: list[SimPlace]) -> bool:
        for i, p_idx in enumerate(self.in_places):
            if places[p_idx].mark < self.in_quantities[i]:
                return False
        for i, p_idx in enumerate(self.inf_places):
            if places[p_idx].mark < self.inf_quantities[i]:
                return False
        return True

    def act_in(self, places: list[SimPlace], current_time: float) -> None:
        from src.services.simulation.random import generate_delay

        if not self.condition(places):
            return
        for i, p_idx in enumerate(self.in_places):
            places[p_idx].decrease_mark(self.in_quantities[i])

        delay = generate_delay(self.distribution, self.parameter, self.deviation)
        scheduled = current_time + delay

        if self.buffer == 0:
            self.time_out[0] = scheduled
        else:
            self.time_out.append(scheduled)

        self.buffer += 1
        if self.buffer > self.observed_max:
            self.observed_max = self.buffer
        self.min_event()

    def act_out(self, places: list[SimPlace]) -> None:
        if self.buffer <= 0:
            return
        for j, p_idx in enumerate(self.out_places):
            places[p_idx].increase_mark(self.out_quantities[j])

        if self._min_channel == 0 and len(self.time_out) == 1:
            self.time_out[0] = INF_TIME
        else:
            self.time_out.pop(self._min_channel)

        self.buffer -= 1
        if self.buffer < self.observed_min:
            self.observed_min = self.buffer


def build_sim_net(
    net: PetriNet,
) -> tuple[list[SimPlace], list[SimTransition]]:
    place_index: dict[str, int] = {}
    sim_places: list[SimPlace] = []

    for i, p in enumerate(net.places):
        place_index[p.id] = i
        sim_places.append(
            SimPlace(
                idx=i,
                id=p.id,
                name=p.name,
                mark=p.tokens,
                tag=p.tag,
                observed_max=p.tokens,
                observed_min=p.tokens,
            )
        )

    transition_index: dict[str, int] = {}
    sim_transitions: list[SimTransition] = []

    for i, t in enumerate(net.transitions):
        transition_index[t.id] = i
        dist_str: str | None = None
        if t.distribution is not None:
            dist_str = t.distribution.value
            if dist_str == "det":
                dist_str = None

        sim_transitions.append(
            SimTransition(
                idx=i,
                id=t.id,
                name=t.name,
                parameter=t.mean_delay,
                deviation=t.standard_deviation,
                distribution=dist_str,
                priority=t.priority,
                probability=t.probability if t.probability is not None else 1.0,
            )
        )

    for arc in net.arcs:
        _wire_arc(arc, place_index, transition_index, sim_transitions)

    logger.debug(
        f"[BUILD-SIM-NET] places={len(sim_places)} transitions={len(sim_transitions)}"
    )
    for sp in sim_places:
        logger.trace(
            f"[BUILD-SIM-NET] place id={sp.id} name={sp.name!r} mark={sp.mark} tag={sp.tag!r}"
        )
    for st in sim_transitions:
        logger.trace(
            f"[BUILD-SIM-NET] transition id={st.id} name={st.name!r} "
            f"parameter(mean_delay)={st.parameter} deviation={st.deviation} "
            f"distribution={st.distribution!r} priority={st.priority} "
            f"probability={st.probability} in_places={st.in_places} "
            f"out_places={st.out_places} inf_places={st.inf_places}"
        )
    return sim_places, sim_transitions


def _wire_arc(
    arc: Arc,
    place_index: dict[str, int],
    transition_index: dict[str, int],
    sim_transitions: list[SimTransition],
) -> None:
    src_is_place = arc.source_id in place_index
    tgt_is_place = arc.target_id in place_index

    if src_is_place and not tgt_is_place:
        p_idx = place_index[arc.source_id]
        t_idx = transition_index[arc.target_id]
        tr = sim_transitions[t_idx]
        if arc.arc_type == ArcType.INHIBITOR or arc.arc_type == ArcType.READ:
            tr.inf_places.append(p_idx)
            tr.inf_quantities.append(arc.weight)
        else:
            tr.in_places.append(p_idx)
            tr.in_quantities.append(arc.weight)

    elif not src_is_place and tgt_is_place:
        t_idx = transition_index[arc.source_id]
        p_idx = place_index[arc.target_id]
        tr = sim_transitions[t_idx]
        tr.out_places.append(p_idx)
        tr.out_quantities.append(arc.weight)
