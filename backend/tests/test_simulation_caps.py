"""Tests for simulation resource caps (CPU/memory-bomb protection)."""

import pytest
from fastapi import HTTPException

from src.services.simulation.limits import validate_simulation_request as _validate_simulation_request
from src.core.security_config import security_settings
from src.domain.models import PetriNet
from src.services.simulation.engine import PetriSimulator, SimulationLimitError


def _recycling_net() -> PetriNet:
    """A net that fires forever: T1 consumes from P1 and returns the token to P1."""
    net = PetriNet(name="recycle")
    p1 = net.add_place("P1", tokens=1)
    t1 = net.add_transition("T1", mean_delay=1.0)
    net.add_arc(p1.id, t1.id)
    net.add_arc(t1.id, p1.id)
    return net


# --- Request validation (pre-flight) ---


def test_validate_rejects_too_many_places(monkeypatch):
    monkeypatch.setattr(security_settings, "SIMULATION_MAX_PLACES", 3)
    net_data = {"places": [{} for _ in range(10)], "transitions": [], "arcs": []}
    with pytest.raises(HTTPException) as exc:
        _validate_simulation_request(net_data, simulation_time=10.0)
    assert exc.value.status_code == 422
    assert "places" in exc.value.detail


def test_validate_rejects_too_many_transitions(monkeypatch):
    monkeypatch.setattr(security_settings, "SIMULATION_MAX_TRANSITIONS", 2)
    net_data = {"places": [{}], "transitions": [{} for _ in range(5)], "arcs": []}
    with pytest.raises(HTTPException) as exc:
        _validate_simulation_request(net_data, simulation_time=10.0)
    assert exc.value.status_code == 422


def test_validate_rejects_simulation_time_over_max(monkeypatch):
    monkeypatch.setattr(security_settings, "SIMULATION_MAX_TIME", 1000.0)
    net_data = {"places": [{}], "transitions": [{}], "arcs": []}
    with pytest.raises(HTTPException) as exc:
        _validate_simulation_request(net_data, simulation_time=999_999.0)
    assert exc.value.status_code == 422
    assert "simulation_time" in exc.value.detail


def test_validate_accepts_small_net():
    net_data = {"places": [{}], "transitions": [{}], "arcs": [{}]}
    # Within all default caps — must not raise.
    _validate_simulation_request(net_data, simulation_time=3600.0)


# --- Engine caps ---


def test_run_step_cap_raises():
    sim = PetriSimulator(_recycling_net(), max_steps=10)
    with pytest.raises(SimulationLimitError, match="step count"):
        sim.run(simulation_time=1_000_000.0)


async def test_run_streaming_step_cap_raises():
    sim = PetriSimulator(_recycling_net(), max_steps=10)
    with pytest.raises(SimulationLimitError, match="step count"):
        async for _ in sim.run_streaming(1_000_000.0, time_step=1.0):
            pass


async def test_run_streaming_wall_clock_cap_raises():
    # Negative timeout → deadline already in the past → trips on first check.
    sim = PetriSimulator(
        _recycling_net(), max_steps=10_000_000, wall_clock_timeout_seconds=-1.0
    )
    with pytest.raises(SimulationLimitError, match="wall-clock"):
        async for _ in sim.run_streaming(1_000_000.0, time_step=1.0):
            pass


def test_normal_simulation_completes_within_caps():
    # A finite net must finish well within default caps.
    net = PetriNet(name="finite")
    p1 = net.add_place("P1", tokens=3)
    p2 = net.add_place("P2", tokens=0)
    t1 = net.add_transition("T1", mean_delay=1.0)
    net.add_arc(p1.id, t1.id)
    net.add_arc(t1.id, p2.id)
    sim = PetriSimulator(net)
    result = sim.run(simulation_time=100.0)
    assert result is not None
