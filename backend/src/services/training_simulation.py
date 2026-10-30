"""Bounded runs of the exact reviewed PNML, with post-event time series."""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import asdict

from src.services.training_export import utc_now
from src.services.training_history import digest
from src.services.petri.importer import parse_pnml
from src.services.petri.composed_convert import net_data_to_composed_model
from src.services.simulation.composed_engine import build_composed_sim_net
from src.services.simulation.engine import PetriSimulator, SimulationLimitError


class EvidenceSimulator(PetriSimulator):
    def _find_active_transitions(self):
        self.input_checks += 1
        if self.input_checks > 100000 or time.monotonic() > self.deadline:
            raise SimulationLimitError("Review simulation reached its input or wall-clock limit")
        return super()._find_active_transitions()

    def _input_all(self, sequence=None):
        result = super()._input_all()
        self.observe(self._current_time, self._markings_snapshot(), self._buffers_snapshot())
        return result


def run_evidence(pnml, horizon, interval=1, source="automatic"):
    started = time.monotonic()
    record = {"source": source, "source_model_sha256": digest(pnml), "created_at": utc_now(),
              "status": "failed", "error": "", "start_time": 0, "horizon": horizon,
              "elapsed_ms": 0, "protocol": "", "protocol_truncated": False,
              "initial_state": [], "final_state": [], "random_seed": None,
              "randomness": "Unseeded built-in engine; exact stochastic replay is not guaranteed"}
    series = {"columns": [], "samples": [], "requested_interval": interval, "effective_interval": interval,
              "time_unit": "model-time", "semantics": "Post-event state held constant between events", "complete": False}
    record["trajectory"] = series
    sim = None
    try:
        net, warnings = parse_pnml(pnml.decode("utf-8"))
        if warnings:
            raise ValueError("The reviewed PNML cannot be simulated losslessly: " + "; ".join(w["message"] for w in warnings)[:2000])
        from src.services.simulation.limits import validate_simulation_request
        validate_simulation_request(net, horizon)
        model = net_data_to_composed_model(net)
        places, transitions = build_composed_sim_net(model)
        if any(not transition.in_places for transition in transitions):
            raise ValueError("A transition without consuming inputs can create unbounded channels")
        sim = EvidenceSimulator.from_sim_state(places, transitions, max_steps=10000, wall_clock_timeout_seconds=4)
        sim.input_checks, sim.deadline = 0, started + 4
        for kind, elements, metric in (("place", places, "tokens"), ("transition", transitions, "active_channels")):
            for number, element in enumerate(elements):
                owner = next((o for o in model.objects if any(n.id == element.id for n in (o.net.places if kind == "place" else o.net.transitions))), None)
                series["columns"].append({"object_index": owner.index if owner else 0, "object_name": owner.name if owner else net.get("name", ""),
                                          "id": element.id, "number": number, "name": element.name, "kind": kind, "metric": metric})
        effective = max(interval, horizon / max(1, min(19999, 1_000_000 // max(1, len(series["columns"]) + 1) - 1)))
        series["effective_interval"] = effective
        previous = [p.mark for p in places] + [t.buffer for t in transitions]
        tick, observed = 0, 0.0

        def observe(at, markings, buffers):
            nonlocal previous, tick, observed
            while tick * effective < at - 1e-9:
                series["samples"].append([tick * effective, *previous])
                tick += 1
            previous = [markings[p.id] for p in places] + [buffers[t.id] for t in transitions]
            observed = at

        sim.observe = observe
        record["initial_state"] = [{"places": [{"id": p.id, "name": p.name, "tokens": p.mark} for p in places],
                                     "transitions": [{"id": t.id, "name": t.name, "active_channels": t.buffer} for t in transitions]}]

        async def consume():
            async for _ in sim.run_streaming(horizon, snapshot_interval=1):
                pass

        try:
            asyncio.run(consume())
            # With no scheduled events the last state remains valid to the horizon.
            observe(horizon, sim._markings_snapshot(), sim._buffers_snapshot())
            record["status"] = "completed"
            series["complete"] = True
        finally:
            endpoint = horizon if series["complete"] else min(horizon, sim._current_time)
            if endpoint >= observed:
                observe(endpoint, sim._markings_snapshot(), sim._buffers_snapshot())
            series["samples"].append([endpoint, *previous])
            record["observed_until"] = endpoint
            record["final_state"] = [asdict(sim._collect_results())]
    except Exception as exc:
        record["status"] = "limit_reached" if isinstance(exc, SimulationLimitError) else "failed"
        record["error"] = str(exc)[:4000]
    record["elapsed_ms"] = max(0, round((time.monotonic() - started) * 1000))
    record["protocol"] = "Built-in Python simulation engine. " + (record["error"] or "Run completed.")
    return record


def simulation_evidence(pnml, review):
    reason = str(review.get("skip_simulation_reason", "")).strip()
    horizons = review.get("simulation_horizons", [] if reason else [100, 1000, 10000])
    interval = review.get("sampling_interval", 1)
    if reason and horizons:
        raise ValueError("Choose automatic simulation or a skip reason, not both")
    if not isinstance(horizons, list) or len(horizons) > 8 or any(isinstance(h, bool) or not isinstance(h, (int, float)) or not math.isfinite(h) or h <= 0 or h > 1_000_000 for h in horizons):
        raise ValueError("Choose up to eight positive simulation horizons")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
        raise ValueError("Sampling interval must be positive")
    if not horizons and not reason:
        raise ValueError("At least one simulation attempt or a reason for skipping is required")
    return {"policy": "attempt-or-reason", "source_model_sha256": digest(pnml), "skip_reason": reason,
            "automatic_runs": [] if reason else [run_evidence(pnml, h, interval) for h in horizons],
            "interactive_runs": review.get("interactive_runs", [])}
