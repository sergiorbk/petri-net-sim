"""Simulation session — wraps PetriSimulator with PetriNetSession integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator

from src.services.simulation.engine import (
    PetriSimulator,
    SimulationEvent,
    SimulationResult,
)

if TYPE_CHECKING:
    from src.services.petri.session import PetriNetSession


class SimulationSession:
    """Manages simulation lifecycle for a given PetriNetSession."""

    def __init__(self, petri_session: PetriNetSession) -> None:
        self._petri_session = petri_session
        self._last_result: SimulationResult | None = None

    def run(self, simulation_time: float) -> SimulationResult:
        net = self._petri_session.net
        if not net.places:
            raise ValueError("No network to simulate. Build a network first.")

        simulator = PetriSimulator(net)
        self._last_result = simulator.run(simulation_time)
        return self._last_result

    async def run_streaming(
        self,
        simulation_time: float,
        time_step: float | None = 1.0,
        snapshot_interval: int | None = None,
    ) -> AsyncIterator[SimulationEvent]:
        net = self._petri_session.net
        if not net.places:
            raise ValueError("No network to simulate. Build a network first.")

        simulator = PetriSimulator(net)
        async for event in simulator.run_streaming(
            simulation_time,
            time_step=time_step,
            snapshot_interval=snapshot_interval,
        ):
            yield event

        self._last_result = simulator._collect_results()

    @property
    def last_result(self) -> SimulationResult | None:
        return self._last_result

    def format_results(self, result: SimulationResult | None = None) -> str:
        r = result or self._last_result
        if r is None:
            return "No simulation results available. Run a simulation first."

        lines = [
            f"Simulation completed: {r.final_time:.2f} / {r.simulation_time:.2f} time units, {r.total_steps} steps",
            "",
            "Places:",
        ]
        for p in r.places:
            lines.append(
                f"  {p.name}: marking={p.final_marking}, "
                f"mean={p.mean_marking:.4f}, "
                f"min={p.observed_min}, max={p.observed_max}"
            )

        lines.append("")
        lines.append("Transitions:")
        for t in r.transitions:
            lines.append(
                f"  {t.name}: buffer={t.final_buffer}, "
                f"mean={t.mean_buffer:.4f}, "
                f"min={t.observed_min}, max={t.observed_max}"
            )

        if r.terminators:
            lines.append("")
            lines.append("Terminators (throughput):")
            for term in r.terminators:
                lines.append(f"  {term.name}: total_consumed={term.total_consumed}")

        if r.warnings:
            lines.append("")
            lines.append("⚠ Parameter warnings (likely cause of unexpected throughput):")
            for w in r.warnings:
                lines.append(f"  - {w}")

        return "\n".join(lines)
