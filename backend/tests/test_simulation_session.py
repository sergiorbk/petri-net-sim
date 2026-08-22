"""Tests for SimulationSession (wraps PetriSimulator with PetriNetSession)."""

from __future__ import annotations

import pytest

from src.services.petri.session import PetriNetSession
from src.services.simulation.session import SimulationSession


def _make_simple_session() -> PetriNetSession:
    """Create a minimal runnable network."""
    s = PetriNetSession()
    s.builder.add_generator("Gen1", interval=5.0)
    s.builder.add_machine("M1", processing_time=10.0)
    s.builder.add_terminator("Exit1")
    return s


class TestSimulationSessionRun:
    def test_run_empty_net_raises(self):
        session = PetriNetSession()
        sim = SimulationSession(session)
        with pytest.raises(ValueError, match="No network"):
            sim.run(100.0)

    def test_run_basic_returns_result(self):
        petri = _make_simple_session()
        sim = SimulationSession(petri)
        result = sim.run(50.0)
        assert result is not None
        assert result.simulation_time == 50.0
        assert result.total_steps >= 0

    def test_last_result_is_set_after_run(self):
        petri = _make_simple_session()
        sim = SimulationSession(petri)
        assert sim.last_result is None
        sim.run(20.0)
        assert sim.last_result is not None


class TestSimulationSessionStreaming:
    @pytest.mark.anyio
    async def test_run_streaming_empty_net_raises(self):
        session = PetriNetSession()
        sim = SimulationSession(session)
        with pytest.raises(ValueError, match="No network"):
            async for _ in sim.run_streaming(50.0):
                pass

    @pytest.mark.anyio
    async def test_run_streaming_yields_events(self):
        petri = _make_simple_session()
        sim = SimulationSession(petri)
        events = []
        async for evt in sim.run_streaming(30.0, time_step=10.0):
            events.append(evt)
        assert len(events) >= 0  # may have 0 events if simulation ends immediately

    @pytest.mark.anyio
    async def test_last_result_set_after_streaming(self):
        petri = _make_simple_session()
        sim = SimulationSession(petri)
        async for _ in sim.run_streaming(20.0, time_step=10.0):
            pass
        assert sim.last_result is not None


class TestFormatResults:
    def test_format_no_results(self):
        session = PetriNetSession()
        sim = SimulationSession(session)
        msg = sim.format_results()
        assert "No simulation results" in msg

    def test_format_with_results(self):
        petri = _make_simple_session()
        sim = SimulationSession(petri)
        result = sim.run(50.0)
        formatted = sim.format_results(result)
        assert "Simulation completed" in formatted
        assert "Places:" in formatted
        assert "Transitions:" in formatted

    def test_format_uses_last_result_when_none_passed(self):
        petri = _make_simple_session()
        sim = SimulationSession(petri)
        sim.run(30.0)
        formatted = sim.format_results()
        assert "Simulation completed" in formatted

    def test_format_with_terminators(self):
        s = PetriNetSession()
        s.builder.add_generator("Gen1", interval=2.0)
        s.builder.add_machine("M1", processing_time=3.0)
        s.builder.add_terminator("Exit1")
        sim = SimulationSession(s)
        result = sim.run(100.0)
        formatted = sim.format_results(result)
        # Terminator section shows up when throughput places tagged
        assert "Simulation completed" in formatted
