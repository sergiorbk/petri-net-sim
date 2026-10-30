"""Shared pre-flight safety limits for simulation requests.

Extracted from the standalone ``/simulate`` router so the session-scoped
simulation endpoints (`sessions.py`) can apply the identical net-size and
``simulation_time`` ceilings without a router→router import. The in-loop step
cap and wall-clock deadline live in the engine (`PetriSimulator`); this module
covers only the cheap up-front rejection of obviously oversized inputs.
"""

import logging
from typing import Any

from fastapi import HTTPException

from src.core.security_config import security_settings

_log = logging.getLogger(__name__)

# Backend-internal side-channel keys that never belong in a net payload sent to
# the simulator. Kept here so both routers strip the same set before counting
# elements / constructing the net.
INTERNAL_NET_KEYS = frozenset({
    "_last_pnml_export",
    "_last_output_place_id",
    "_last_simulation_result_text",
    # Which object add_*/modify_* tool calls were targeting when a
    # PetriNetSession last serialized (session.py's to_net_data) -- pure
    # tool-dispatch bookkeeping for the NEXT chat/MCP turn, meaningless
    # (and previously leaked verbatim) to any GET /net response, a
    # share/public snapshot view, or a simulate request body.
    "_active_object_id",
    "_training_archive_base64",
    "_training_interactive_runs",
})


def clean_net_data(raw: dict[str, Any]) -> dict[str, Any]:
    """Strip backend-internal side-channel keys from a net_data dict."""
    return {k: v for k, v in raw.items() if k not in INTERNAL_NET_KEYS}


def validate_simulation_request(net_data: dict[str, Any], simulation_time: float) -> None:
    """Reject CPU/memory-bomb inputs before constructing the net or simulating.

    Raises ``HTTPException`` 422 with a clear message when the net or requested
    simulation horizon exceeds the configured safety caps. Limits are sourced
    from ``SecuritySettings`` so they remain centrally tunable.
    """
    s = security_settings
    n_places = len(net_data.get("places") or [])
    n_transitions = len(net_data.get("transitions") or [])
    n_arcs = len(net_data.get("arcs") or [])

    problems: list[str] = []
    if n_places > s.SIMULATION_MAX_PLACES:
        problems.append(f"places={n_places} (max {s.SIMULATION_MAX_PLACES})")
    if n_transitions > s.SIMULATION_MAX_TRANSITIONS:
        problems.append(f"transitions={n_transitions} (max {s.SIMULATION_MAX_TRANSITIONS})")
    if n_arcs > s.SIMULATION_MAX_ARCS:
        problems.append(f"arcs={n_arcs} (max {s.SIMULATION_MAX_ARCS})")
    if simulation_time > s.SIMULATION_MAX_TIME:
        problems.append(f"simulation_time={simulation_time} (max {s.SIMULATION_MAX_TIME})")

    if problems:
        _log.warning("Rejected oversized simulation request: %s", ", ".join(problems))
        raise HTTPException(
            status_code=422,
            detail="Simulation request exceeds safety limits: " + ", ".join(problems),
        )
