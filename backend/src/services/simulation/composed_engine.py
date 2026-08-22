"""Local (Python-native) simulation engine for composed Petri-object models.

Builds one global (places, transitions) pool from a ComposedModel and hands
it straight to PetriSimulator — the whole composed model runs through the
exact same event loop as a flat net (see PetriSimulator.from_sim_state), it
just happens to have been fed a pool that spans several objects. This
mirrors ua.stetsenkoinna.petriobj.PetriObjModel.wire() in PetriObjModelPaint:
placeFusion aliases both places onto one shared global slot (so there is
nothing left to synchronize — they are the same slot), transitionToPlace
appends a cross-object output arc directly onto the firing transition. See
docs/petri-object-models.md for the model this ports.
"""

from __future__ import annotations

from src.domain.composed import ComposedModel, LinkType
from src.domain.models import ArcType
from src.services.petri.exporter.composed_document import _elect_shared_places, build_final_id_map
from src.services.simulation.state import SimPlace, SimTransition


class ComposedSimulationUnsupported(ValueError):
    """A composed model uses a feature the local engine cannot run.

    Distinct from a plain ValueError so the caller can tell "this model
    needs a feature the local engine doesn't have" apart from a genuine
    bug, and word the SSE error frame in the model's own vocabulary
    ("kind": "model") rather than as a transport failure.
    """


def build_composed_sim_net(
    model: ComposedModel,
) -> tuple[list[SimPlace], list[SimTransition]]:
    """One global (places, transitions) pool for the whole composed model.

    Assumes ``model.validate()`` has already been called (the router does
    this before reaching here) — this function does not re-check structural
    validity, only builds the runnable pool.

    Raises ComposedSimulationUnsupported if the model uses a placeToTransition
    link — retired in PetriObjModelPaint for giving a transition a second,
    disconnected set of input places (docs/petri-object-models.md), and not
    yet re-supported here either.
    """
    for link in model.links:
        if link.type == LinkType.PLACE_TO_TRANSITION:
            raise ComposedSimulationUnsupported(
                "placeToTransition links are not supported by the simulation "
                "engine. PetriObjModelPaint retired this link type for the "
                "same reason: it gives a transition a second, disconnected "
                "set of input places, which contradicts what the transition's "
                "own arcs already declare. Connect the place into the "
                "consuming object's own net instead — a placeFusion shares it "
                "there, wired with an ordinary or a read/test arc."
            )

    # (object_index, place_index) -> canonical (object_index, place_index),
    # present only for the non-surviving member of each fusion group. wire()
    # in PetriObjModelPaint keeps the link's TARGET side; _elect_shared_places
    # reproduces that exactly, chains included — see its own docstring.
    fusion_survivor = _elect_shared_places(model)
    # (object_index, element's own id) -> the id to report it under. Equal to
    # the element's own id unless two different objects mint the same id
    # (e.g. two instances of the same library template) — this is what lets
    # the caller receive markings/buffers keyed by ids it already knows,
    # with no translation step, in the common (no-collision) case.
    final_id = build_final_id_map(model)

    place_slot: dict[tuple[int, int], int] = {}
    sim_places: list[SimPlace] = []

    def place_global_index(object_index: int, local_index: int) -> int:
        canonical = fusion_survivor.get((object_index, local_index), (object_index, local_index))
        existing = place_slot.get(canonical)
        if existing is not None:
            return existing
        c_obj, c_local = canonical
        p = model.get_object(c_obj).net.places[c_local]
        idx = len(sim_places)
        sim_places.append(
            SimPlace(
                idx=idx,
                id=final_id[(c_obj, p.id)],
                name=p.name,
                mark=p.tokens,
                tag=p.tag,
                observed_max=p.tokens,
                observed_min=p.tokens,
            )
        )
        place_slot[canonical] = idx
        return idx

    # Every place gets a slot up front, fused or not — a place an object
    # leaves otherwise unwired (open interface, no local arc at all) still
    # needs to exist and report a marking.
    for obj in model.objects:
        for local_idx in range(len(obj.net.places)):
            place_global_index(obj.index, local_idx)

    transition_slot: dict[tuple[int, int], int] = {}
    sim_transitions: list[SimTransition] = []

    for obj in model.objects:
        for local_idx, t in enumerate(obj.net.transitions):
            dist_str: str | None = None
            if t.distribution is not None:
                dist_str = t.distribution.value
                if dist_str == "det":
                    dist_str = None
            idx = len(sim_transitions)
            sim_transitions.append(
                SimTransition(
                    idx=idx,
                    id=final_id[(obj.index, t.id)],
                    name=t.name,
                    parameter=t.mean_delay,
                    deviation=t.standard_deviation,
                    distribution=dist_str,
                    priority=t.priority,
                    probability=t.probability if t.probability is not None else 1.0,
                    object_priority=obj.priority,
                )
            )
            transition_slot[(obj.index, local_idx)] = idx

    # Each object's own internal arcs, exactly like state._wire_arc but
    # indexing into the global pool instead of a private per-object one —
    # this is what makes a place already aliased by a fusion link (above)
    # take effect: an ordinary arc drawn to/from a non-survivor place lands
    # on its survivor's slot instead, automatically.
    for obj in model.objects:
        place_index_by_id = {p.id: i for i, p in enumerate(obj.net.places)}
        transition_index_by_id = {t.id: i for i, t in enumerate(obj.net.transitions)}
        for arc in obj.net.arcs:
            src_is_place = arc.source_id in place_index_by_id
            tgt_is_place = arc.target_id in place_index_by_id
            if src_is_place and not tgt_is_place:
                p_global = place_global_index(obj.index, place_index_by_id[arc.source_id])
                tr = sim_transitions[transition_slot[(obj.index, transition_index_by_id[arc.target_id])]]
                if arc.arc_type in (ArcType.INHIBITOR, ArcType.READ):
                    tr.inf_places.append(p_global)
                    tr.inf_quantities.append(arc.weight)
                else:
                    tr.in_places.append(p_global)
                    tr.in_quantities.append(arc.weight)
            elif not src_is_place and tgt_is_place:
                tr = sim_transitions[transition_slot[(obj.index, transition_index_by_id[arc.source_id])]]
                p_global = place_global_index(obj.index, place_index_by_id[arc.target_id])
                tr.out_places.append(p_global)
                tr.out_quantities.append(arc.weight)

    # transitionToPlace: a genuine cross-object output arc, appended onto the
    # firing transition exactly where act_out() already looks for its normal
    # ones — this is ExternalArc/addExternalOutput in PetriObjModelPaint, and
    # it fires in the very same pass as local output arcs. placeFusion links
    # need no separate step here: place_global_index already aliased both
    # ends onto one shared slot above.
    for link in model.links:
        if link.type != LinkType.TRANSITION_TO_PLACE:
            continue
        tr = sim_transitions[transition_slot[(link.source_object, link.source_element)]]
        p_global = place_global_index(link.target_object, link.target_element)
        tr.out_places.append(p_global)
        tr.out_quantities.append(link.quantity)

    return sim_places, sim_transitions
