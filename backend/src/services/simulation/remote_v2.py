"""Remote simulation backend (v2) — proxies composed Petri-object models to
petri-server's /api/v2 endpoints.

Mirrors src/services/simulation/remote.py's structure closely, including a
duplicated copy of _parse_sse_block, since that file is intentionally left
unmodified (it is the tested, working v1 path).

The remote server must expose:
    POST /api/v2/simulation/stream?simulationTime=...&timeStep=...
        &snapshotInterval=...&animationDelayMs=...
  Body: {"modelXml": "<multi-page PNML XML>"}
  Response: text/event-stream

    POST /api/v2/model/parse
  Body: {"modelXml": "<multi-page PNML XML>"}
  Response: parsed objects/links JSON

Event protocol is identical to v1 (see remote.py) — markings/buffers are
keyed by element id, unique across every object in the model, so the same
SimulationEvent shape covers both versions unchanged. That holds one level
down too: the markings/buffers carried inside each firing_sequence step are
model-wide and element-id keyed, not scoped to the object that fired, so the
frontend can highlight a link's far end from the same snapshot.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from src.domain.composed import ComposedModel
from src.services.petri.exporter import ComposedPNMLExporter
from src.services.petri.exporter.composed_document import _elect_shared_places, build_final_id_map
from src.services.simulation.engine import FiringStep, SimulationEvent

_log = logging.getLogger(__name__)

_exporter = ComposedPNMLExporter()

# The four highlight phases the frontend knows how to render. Anything else
# would reach it as an active_phase that highlights nothing, so it is dropped.
_PHASES = frozenset({"before_act_in", "after_act_in", "before_act_out", "after_act_out"})
_warned_unknown_phase = False


async def run_remote_streaming_v2(
    model: ComposedModel,
    base_url: str,
    simulation_time: float,
    time_step: float,
    snapshot_interval: int | None,
    animation_delay_ms: int,
) -> AsyncIterator[SimulationEvent]:
    """Stream simulation events for a composed model from a remote petri-server instance."""
    model_xml = _exporter.export(model)
    own_id = _own_id_map(model)
    fusion_alias = _fusion_alias_map(model)

    params: dict[str, str | int | float] = {
        "simulationTime": simulation_time,
        "timeStep": time_step,
        "animationDelayMs": animation_delay_ms,
    }
    if snapshot_interval is not None:
        params["snapshotInterval"] = snapshot_interval

    url = base_url.rstrip("/") + "/api/v2/simulation/stream"

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            url,
            params=params,
            json={"modelXml": model_xml},
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()

            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    event = _parse_sse_block(block)
                    if event is not None:
                        yield _restore_own_ids(event, own_id, fusion_alias)


def _own_id_map(model: ComposedModel) -> dict[str, str] | None:
    """document id -> the id the caller gave the element, or None when nothing
    was renamed.

    The exporter has to rename element ids when two objects share one, because
    a PNML id is document-scoped and two objects built from the same template
    collide by construction. petri-server then reports its markings under the
    renamed ids, which are ids the caller has never seen: it sent "p1" and would
    be answered about "o1_p1". Inverting the rename here is what keeps that an
    implementation detail of the wire format.

    Returns None for the far commoner case where no rename happened, so the
    per-frame translation can be skipped outright rather than copying every map
    to no effect.
    """
    renamed = {
        document_id: own_id
        for (_obj_index, own_id), document_id in build_final_id_map(model).items()
        if document_id != own_id
    }
    if not renamed:
        return None
    # The rename is undone faithfully, but it cannot undo the ambiguity that
    # made it necessary: two objects that both call a place "p1" get one "p1"
    # in the report, and the second value overwrites the first. The run itself
    # is unaffected, since the document petri-server sees keeps them apart.
    _log.warning(
        "Composed model '%s' has %d element id(s) shared between objects. The "
        "simulation is exact, but its markings are reported under those ids, so "
        "elements that share one cannot be told apart. Give them distinct ids.",
        model.name, len(set(renamed.values())),
    )
    return renamed


def _fusion_alias_map(model: ComposedModel) -> dict[str, str]:
    """Own id of every place fused away -> own id of the survivor holding its marking.

    A placeFusion group is exported as one real `<place>` (the survivor) plus
    a `<referencePlace>` for every other member (`_elect_shared_places`), so
    petri-server's snapshot only ever reports a marking under the survivor's
    document id — a fused-away member's own id never appears as a key at all,
    even though callers may reasonably look it up (the frontend already
    compensates for this client-side; other API consumers do not).

    Derives the groups the same way the exporter does, so a caller asking
    about ANY member of a fusion group gets the same value the survivor has.
    Keyed and valued by each place's own (pre-rename) id — the id callers
    use — not the document id, so this composes with `_own_id_map` as two
    independent rekeying passes in `_restore_own_ids`.
    """
    alias: dict[str, str] = {}
    for member_slot, survivor_slot in _elect_shared_places(model).items():
        member_obj = model.get_object(member_slot[0])
        survivor_obj = model.get_object(survivor_slot[0])
        member_id = member_obj.net.places[member_slot[1]].id
        survivor_id = survivor_obj.net.places[survivor_slot[1]].id
        alias[member_id] = survivor_id
    return alias


def _restore_own_ids(
    event: SimulationEvent,
    own_id: dict[str, str] | None,
    fusion_alias: dict[str, str] | None = None,
) -> SimulationEvent:
    """Re-key one event's markings, buffers and firing steps to the caller's
    ids, then fill in the marking of every place fused away into another.

    The two rewrites are independent and both keyed by the caller's own ids:
    a document-id rename can apply with no fusion in the model, and a fusion
    can apply with no id collision (`own_id is None`), so neither short-
    circuits the other's pass.
    """
    if own_id is not None:

        def rekey(values: dict[str, int]) -> dict[str, int]:
            return {own_id.get(key, key): value for key, value in values.items()}

        event.markings = rekey(event.markings)
        event.buffers = rekey(event.buffers)
        event.fired_transitions = [own_id.get(t, t) for t in event.fired_transitions]
        for step in event.firing_sequence:
            step.transition_id = own_id.get(step.transition_id, step.transition_id)
            step.markings = rekey(step.markings)
            step.buffers = rekey(step.buffers)

    if fusion_alias:

        def duplicate(markings: dict[str, int]) -> None:
            # Buffers are transition-only, place fusion never touches them.
            for member_id, survivor_id in fusion_alias.items():
                if survivor_id in markings:
                    markings[member_id] = markings[survivor_id]

        duplicate(event.markings)
        for step in event.firing_sequence:
            duplicate(step.markings)

    return event


async def parse_composed_model_remote(model: ComposedModel, base_url: str) -> dict[str, Any]:
    """POST /api/v2/model/parse — round-trips the exported PNML through the
    real Java parser without running a simulation. Used by the /preview
    route and to verify the exporter's schema against petri-server."""
    model_xml = _exporter.export(model)
    url = base_url.rstrip("/") + "/api/v2/model/parse"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json={"modelXml": model_xml})
        resp.raise_for_status()
        return resp.json()


def _parse_fired_transitions(raw: object) -> list[str]:
    """Keep only the string ids; anything else the remote sends is ignored."""
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, str)]


def _parse_firing_sequence(raw: object) -> list[FiringStep]:
    """Build the animation steps of one frame, discarding whatever does not fit.

    Deliberately unable to raise. This runs inside the async generator that
    feeds /v1/simulate/composed, where an exception becomes a generic error
    frame and ends the stream — and that route has no local engine to fall back
    to. A petri-server that is half-way through implementing the contract must
    therefore cost the caller its animation, never its simulation.
    """
    global _warned_unknown_phase
    if not isinstance(raw, list):
        return []

    steps: list[FiringStep] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        transition_id = item.get("transition_id")
        phase = item.get("phase")
        if not isinstance(transition_id, str):
            continue
        # The type check is what keeps the membership test total: `in` on a set
        # hashes its left operand, and a JSON list or object is unhashable.
        if not isinstance(phase, str) or phase not in _PHASES:
            # Once per process: a phase name the two engines disagree on is a
            # deployment bug worth finding, but it repeats every single frame.
            if not _warned_unknown_phase:
                _warned_unknown_phase = True
                _log.warning(
                    "Remote simulation (v2): dropping firing step with unknown phase %r", phase
                )
            continue
        markings = item.get("markings")
        buffers = item.get("buffers")
        # A missing marking is not a harmless default. The client replaces the
        # frame's own snapshot with the phases it carries, so a step defaulted to
        # {} would blank the whole net for that frame instead of merely costing
        # it an animation — the step has to go, not its markings.
        if not isinstance(markings, dict) or not isinstance(buffers, dict):
            continue
        try:
            step_time = float(item.get("time") or 0.0)
        except (TypeError, ValueError, OverflowError):
            step_time = 0.0
        steps.append(FiringStep(
            transition_id=transition_id,
            phase=phase,
            markings=markings,
            buffers=buffers,
            time=step_time,
        ))
    return steps


def _parse_sse_block(block: str) -> SimulationEvent | None:
    """Parse one SSE block into a SimulationEvent, or None to skip.

    Identical to remote.py's _parse_sse_block — duplicated rather than
    imported, see module docstring. The same goes for the two firing-step
    helpers above it.
    """
    name: str | None = None
    data: str | None = None

    for line in block.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()

    if name == "session" or data is None:
        return None
    if data == "[DONE]":
        return None

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        _log.warning("Remote simulation (v2): malformed SSE data: %s", data)
        return None

    return SimulationEvent(
        current_time=payload["current_time"],
        step_number=payload["step_number"],
        markings=payload["markings"],
        buffers=payload["buffers"],
        progress=payload["progress"],
        # .get() rather than [] is what makes these two optional: an older
        # petri-server omits them entirely and the frame still parses.
        fired_transitions=_parse_fired_transitions(payload.get("fired_transitions")),
        firing_sequence=_parse_firing_sequence(payload.get("firing_sequence")),
    )
