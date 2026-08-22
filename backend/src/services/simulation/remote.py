"""Remote simulation backend — proxies to an external petri-net simulation server.

The remote server must expose:
    POST /api/v1/simulation/stream?simulationTime=...&timeStep=...
        &snapshotInterval=...&animationDelayMs=...
  Body: {"netXml": "<PNML XML>"}
  Response: text/event-stream

Event protocol (same as local engine):
  - First event: name=session, data={"sessionId":"..."}  (captured, not forwarded)
  - Subsequent: data=<SimulationFrame JSON>
  - Terminal:   data=[DONE]

SimulationFrame required fields: current_time, step_number, markings, buffers,
progress.  Two optional fields carry the animation detail the built-in engine
produces: fired_transitions (list[str]) and firing_sequence (a list of
{transition_id, phase, markings, buffers, time} objects, one per atomic
highlight step since the previous frame).  Both default to [] so a petri-server
build that predates them still streams — the animation simply degrades to one
snapshot per frame, which is what this proxy did before.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from src.domain.models import PetriNet
from src.services.petri.exporter.pnml_exporter import PNMLExporter
from src.services.simulation.engine import FiringStep, SimulationEvent

_log = logging.getLogger(__name__)

_exporter = PNMLExporter()

# The four highlight phases the frontend knows how to render. Anything else
# would reach it as an active_phase that highlights nothing, so it is dropped.
_PHASES = frozenset({"before_act_in", "after_act_in", "before_act_out", "after_act_out"})
_warned_unknown_phase = False


async def run_remote_streaming(
    net: PetriNet,
    base_url: str,
    simulation_time: float,
    time_step: float,
    snapshot_interval: int | None,
    animation_delay_ms: int,
) -> AsyncIterator[SimulationEvent]:
    """Stream simulation events from a remote petri-server instance."""
    net_xml = _exporter.export(net)

    params: dict[str, str | int | float] = {
        "simulationTime": simulation_time,
        "timeStep": time_step,
        "animationDelayMs": animation_delay_ms,
    }
    if snapshot_interval is not None:
        params["snapshotInterval"] = snapshot_interval

    url = base_url.rstrip("/") + "/api/v1/simulation/stream"

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            url,
            params=params,
            json={"netXml": net_xml},
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
                        yield event


def _parse_fired_transitions(raw: object) -> list[str]:
    """Keep only the string ids; anything else the remote sends is ignored."""
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, str)]


def _parse_firing_sequence(raw: object) -> list[FiringStep]:
    """Build the animation steps of one frame, discarding whatever does not fit.

    Deliberately unable to raise. This runs inside the async generator that
    feeds the SSE routers, where an exception becomes a generic error frame and
    ends the stream — and the composed-model route has no local engine to fall
    back to. A petri-server that is half-way through implementing the contract
    must therefore cost the caller its animation, never its simulation.
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
                _log.warning("Remote simulation: dropping firing step with unknown phase %r", phase)
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
    """Parse one SSE block into a SimulationEvent, or None to skip."""
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
        _log.warning("Remote simulation: malformed SSE data: %s", data)
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
