"""Core Petri net simulation engine.

Faithful port of ua.stetsenkoinna.PetriObj.PetriObjModel.go() — event-driven
discrete simulation with multi-channel transitions, priority/probability
conflict resolution, and incremental statistics.

The simulation loop follows the PetriObjModel pattern:
1. Initial input phase (fire all enabled transitions)
2. Find nearest event (minimum scheduled output time)
3. Collect statistics for the elapsed interval
4. Advance time to nearest event
5. Fire output for the event transition
6. Re-fire all inputs (new tokens may enable transitions)
7. Repeat from step 2
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from src.domain.models import PetriNet
from src.services.simulation.state import INF_TIME, SimPlace, SimTransition, build_sim_net

# Maximum consecutive steps allowed at the same simulation time.
# Immediate transitions (delay=0) that form a cycle would otherwise loop forever.
_MAX_ZERO_DT_STEPS = 10_000


class SimulationLimitError(RuntimeError):
    """Raised when a simulation hits a hard resource cap (steps or wall-clock).

    Subclasses RuntimeError so existing callers that catch RuntimeError (e.g.
    the precompute endpoint → HTTP 422) handle it without changes, while the
    streaming endpoint surfaces it as a graceful terminal error frame.
    """


@dataclass
class PlaceStatistics:
    id: str
    name: str
    final_marking: int
    mean_marking: float
    observed_min: int
    observed_max: int


@dataclass
class TransitionStatistics:
    id: str
    name: str
    final_buffer: int
    mean_buffer: float
    observed_min: int
    observed_max: int


@dataclass
class TerminatorStatistics:
    """Throughput counter sourced from a place tagged 'throughput'.

    `total_consumed` is the final marking of the counter place — the number
    of tokens that have accumulated in this exit point during the run, i.e.
    the canonical answer to "how many items completed?".
    """
    id: str
    name: str
    total_consumed: int


@dataclass
class SimulationResult:
    simulation_time: float
    final_time: float
    total_steps: int
    places: list[PlaceStatistics] = field(default_factory=list)
    transitions: list[TransitionStatistics] = field(default_factory=list)
    terminators: list[TerminatorStatistics] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class FiringStep:
    """One atomic animation step within a simulation snapshot.

    Phases mirror the Swing UI hooks (AnimRunPetriSim):
      before_act_in  — input places + input arcs highlighted; OLD markings
      after_act_in   — transition highlighted; markings updated (tokens consumed, buffer++)
      before_act_out — transition + output arcs highlighted; markings same as after_act_in
      after_act_out  — output places highlighted; markings updated (buffer--, tokens produced)
    """
    transition_id: str
    phase: str
    markings: dict[str, int]
    buffers: dict[str, int]
    time: float = 0.0


@dataclass
class SimulationEvent:
    current_time: float
    step_number: int
    markings: dict[str, int]
    buffers: dict[str, int]
    progress: float
    fired_transitions: list[str] = field(default_factory=list)
    firing_sequence: list[FiringStep] = field(default_factory=list)


class PetriSimulator:
    """Event-driven Petri net simulator (port of PetriObjModel.go())."""

    def __init__(
        self,
        net: PetriNet,
        max_steps: int | None = None,
        wall_clock_timeout_seconds: float | None = None,
    ) -> None:
        places, transitions = build_sim_net(net)
        self._init_state(places, transitions, max_steps, wall_clock_timeout_seconds)

    @classmethod
    def from_sim_state(
        cls,
        places: list[SimPlace],
        transitions: list[SimTransition],
        max_steps: int | None = None,
        wall_clock_timeout_seconds: float | None = None,
    ) -> "PetriSimulator":
        """Build a simulator from an already-wired (places, transitions) pool,
        bypassing build_sim_net(net) — the composed-model entry point, since a
        ComposedModel's global pool spans several objects with no single
        PetriNet to build from. See composed_engine.build_composed_sim_net.
        """
        self = cls.__new__(cls)
        self._init_state(places, transitions, max_steps, wall_clock_timeout_seconds)
        return self

    def _init_state(
        self,
        places: list[SimPlace],
        transitions: list[SimTransition],
        max_steps: int | None,
        wall_clock_timeout_seconds: float | None,
    ) -> None:
        self._places = places
        self._transitions = transitions
        self._current_time: float = 0.0
        self._simulation_time: float = 0.0
        self._steps: int = 0

        # Hard resource caps protect the worker from CPU-bomb nets (unbounded
        # firing loops). Default from settings; overridable for tests.
        from src.core.security_config import security_settings

        self._max_steps = (
            max_steps if max_steps is not None
            else security_settings.SIMULATION_MAX_STEPS
        )
        self._wall_clock_timeout = (
            wall_clock_timeout_seconds if wall_clock_timeout_seconds is not None
            else security_settings.SIMULATION_WALL_CLOCK_TIMEOUT_SECONDS
        )

    def _enforce_caps(self, deadline: float) -> None:
        """Raise SimulationLimitError when a hard resource cap is exceeded."""
        if self._steps >= self._max_steps:
            raise SimulationLimitError(
                f"Simulation exceeded the maximum step count ({self._max_steps}). "
                "The net likely produces unbounded firings — reduce simulation_time "
                "or check for runaway immediate-transition loops."
            )
        # monotonic() is cheap, but only check periodically to keep tight loops fast.
        if (self._steps & 0x7FF) == 0 and time.monotonic() > deadline:
            raise SimulationLimitError(
                f"Simulation exceeded the wall-clock limit "
                f"({self._wall_clock_timeout:.0f}s) at step {self._steps}, "
                f"sim-time {self._current_time:.6g}."
            )

    def _find_active_transitions(self) -> list[SimTransition]:
        active: list[SimTransition] = []
        for t in self._transitions:
            if t.condition(self._places) and t.probability != 0:
                active.append(t)
        if len(active) > 1:
            # (object_priority, priority): a flat net's transitions all share
            # object_priority=0, so this sorts identically to priority alone —
            # a composed model's transitions additionally rank by which
            # object owns them first. See SimTransition.object_priority.
            active.sort(key=lambda tr: (tr.object_priority, tr.priority), reverse=True)
        return active

    def _resolve_conflict(self, active: list[SimTransition]) -> SimTransition:
        if len(active) == 1:
            return active[0]

        top = active[0]
        top_key = (top.object_priority, top.priority)
        same_priority_count = 0
        for t in active:
            if (t.object_priority, t.priority) == top_key:
                same_priority_count += 1
            else:
                break

        if same_priority_count == 1:
            return top

        r = random.random()  # NOSONAR - simulation PRNG, not security-sensitive
        cumulative = 0.0
        for i in range(same_priority_count):
            t = active[i]
            prob = t.probability if not math.isclose(t.probability, 1.0) else 1.0 / same_priority_count
            cumulative += prob
            if r < cumulative:
                return t

        return active[same_priority_count - 1]

    def _markings_snapshot(self) -> dict[str, int]:
        return {p.id: p.mark for p in self._places}

    def _buffers_snapshot(self) -> dict[str, int]:
        return {t.id: t.buffer for t in self._transitions}

    def _input_all(self, sequence: list[FiringStep] | None = None) -> set[str]:
        """Fire all enabled transitions' inputs until none are active.

        Returns the set of transition IDs that fired their input in this call.
        When *sequence* is provided, appends before/after FiringSteps for each act_in.
        """
        fired: set[str] = set()
        active = self._find_active_transitions()
        if not active and self._is_buffer_empty():
            return fired
        while active:
            winner = self._resolve_conflict(active)
            if sequence is not None:
                sequence.append(FiringStep(
                    transition_id=winner.id,
                    phase="before_act_in",
                    markings=self._markings_snapshot(),
                    buffers=self._buffers_snapshot(),
                    time=self._current_time,
                ))
            winner.act_in(self._places, self._current_time)
            fired.add(winner.id)
            if sequence is not None:
                sequence.append(FiringStep(
                    transition_id=winner.id,
                    phase="after_act_in",
                    markings=self._markings_snapshot(),
                    buffers=self._buffers_snapshot(),
                    time=self._current_time,
                ))
            active = self._find_active_transitions()
        return fired

    def _find_event_min(self) -> tuple[SimTransition | None, float]:
        best: SimTransition | None = None
        best_time = INF_TIME
        for t in self._transitions:
            mt = t.min_time
            if mt < best_time:
                best_time = mt
                best = t
        return best, best_time

    def _is_buffer_empty(self) -> bool:
        return all(t.buffer == 0 for t in self._transitions)

    def _do_statistics(self, dt: float) -> None:
        if self._simulation_time <= 0 or dt <= 0:
            return
        if self._current_time + dt < self._simulation_time:
            ratio = dt / (self._current_time + dt)
        else:
            ratio = (self._simulation_time - self._current_time) / self._simulation_time
        for p in self._places:
            p.change_mean(ratio)
        for t in self._transitions:
            t.change_mean(ratio)

    def _output_event(self, transition: SimTransition, sequence: list[FiringStep] | None = None) -> None:
        if sequence is not None:
            sequence.append(FiringStep(
                transition_id=transition.id,
                phase="before_act_out",
                markings=self._markings_snapshot(),
                buffers=self._buffers_snapshot(),
                time=self._current_time,
            ))
        transition.act_out(self._places)
        if sequence is not None:
            sequence.append(FiringStep(
                transition_id=transition.id,
                phase="after_act_out",
                markings=self._markings_snapshot(),
                buffers=self._buffers_snapshot(),
                time=self._current_time,
            ))
        while transition.buffer > 0:
            transition.min_event()
            if transition._min_time == self._current_time:
                if sequence is not None:
                    sequence.append(FiringStep(
                        transition_id=transition.id,
                        phase="before_act_out",
                        markings=self._markings_snapshot(),
                        buffers=self._buffers_snapshot(),
                        time=self._current_time,
                    ))
                transition.act_out(self._places)
                if sequence is not None:
                    sequence.append(FiringStep(
                        transition_id=transition.id,
                        phase="after_act_out",
                        markings=self._markings_snapshot(),
                        buffers=self._buffers_snapshot(),
                        time=self._current_time,
                    ))
            else:
                break

    def run(self, simulation_time: float) -> SimulationResult:  # NOSONAR
        from src.core.logger import get_logger
        _log = get_logger("simulation")
        _log.debug(
            f"[SIM-RUN] simulation_time={simulation_time}s "
            f"places={len(self._places)} transitions={len(self._transitions)}"
        )
        self._simulation_time = simulation_time
        self._current_time = 0.0
        self._steps = 0

        if not self._transitions:
            _log.debug("[SIM-RUN] no transitions -- returning immediately")
            return self._collect_results()

        self._input_all()
        _log.trace(
            f"[SIM-RUN] after initial _input_all: markings={self._markings_snapshot()} "
            f"buffers={self._buffers_snapshot()}"
        )
        for t in self._transitions:
            _log.trace(
                f"[SIM-RUN] transition {t.name!r} after input: buffer={t.buffer} "
                f"min_time={t.min_time} (INF means no scheduled event)"
            )

        zero_dt_streak = 0
        deadline = time.monotonic() + self._wall_clock_timeout
        while self._current_time < simulation_time:
            self._enforce_caps(deadline)
            event_transition, event_time = self._find_event_min()

            if event_transition is None:
                _log.debug(
                    f"[SIM-RUN] step={self._steps} t={self._current_time}: "
                    f"no scheduled event -- breaking loop"
                )
                break

            _log.trace(
                f"[SIM-RUN] step={self._steps} t={self._current_time} "
                f"-> event_transition={event_transition.name!r} at event_time={event_time}"
            )
            dt = event_time - self._current_time
            if dt > 0:
                self._do_statistics(dt)
                zero_dt_streak = 0
            else:
                zero_dt_streak += 1
                if zero_dt_streak > _MAX_ZERO_DT_STEPS:
                    raise RuntimeError(
                        f"Simulation livelock: {_MAX_ZERO_DT_STEPS} consecutive zero-delay "
                        f"firings at t={self._current_time:.6g}. "
                        "Immediate transitions (delay=0) likely form a cycle."
                    )

            self._current_time = event_time

            if self._current_time > simulation_time:
                self._current_time = simulation_time
                break

            self._output_event(event_transition)

            for t in self._transitions:
                if t is not event_transition and t.buffer > 0:
                    t.min_event()
                    if t._min_time == self._current_time:
                        self._output_event(t)

            self._input_all()
            self._steps += 1

        _log.debug(
            f"[SIM-RUN] finished: total_steps={self._steps} final_time={self._current_time} "
            f"final_markings={self._markings_snapshot()}"
        )
        return self._collect_results()

    async def run_streaming(  # NOSONAR
        self,
        simulation_time: float,
        time_step: float | None = 1.0,
        snapshot_interval: int | None = None,
    ) -> AsyncIterator[SimulationEvent]:
        """Stream simulation snapshots with two modes:

        **Time-based** (default, ``time_step`` is set):
            Yields a snapshot every ``time_step`` simulation time units.
            The total number of snapshots equals ``simulation_time / time_step``,
            regardless of how many discrete events the net fires.  Combined with
            ``animation_delay`` on the endpoint this lets the frontend animate at
            a pace proportional to simulated time.

        **Step-based** (scientific mode, ``snapshot_interval`` is set):
            Yields a snapshot every ``snapshot_interval`` transition firings.
            Useful for inspecting individual events in dense nets.

        If both are provided, ``snapshot_interval`` takes precedence.
        """
        self._simulation_time = simulation_time
        self._current_time = 0.0
        self._steps = 0

        if not self._transitions:
            yield self._snapshot()
            return

        sequence: list[FiringStep] = []
        self._input_all(sequence)

        step_mode = snapshot_interval is not None
        next_snapshot_at = (time_step or 1.0)
        fired_since_last_snapshot: set[str] = set()
        zero_dt_streak = 0
        deadline = time.monotonic() + self._wall_clock_timeout

        while self._current_time < simulation_time:
            self._enforce_caps(deadline)
            event_transition, event_time = self._find_event_min()

            if event_transition is None:
                break

            dt = event_time - self._current_time
            if dt > 0:
                self._do_statistics(dt)
                zero_dt_streak = 0
            else:
                zero_dt_streak += 1
                if zero_dt_streak > _MAX_ZERO_DT_STEPS:
                    raise RuntimeError(
                        f"Simulation livelock: {_MAX_ZERO_DT_STEPS} consecutive zero-delay "
                        f"firings at t={self._current_time:.6g}. "
                        "Immediate transitions (delay=0) likely form a cycle."
                    )

            self._current_time = event_time

            if self._current_time > simulation_time:
                self._current_time = simulation_time
                break

            self._output_event(event_transition, sequence)
            fired_since_last_snapshot.add(event_transition.id)

            for t in self._transitions:
                if t is not event_transition and t.buffer > 0:
                    t.min_event()
                    if t._min_time == self._current_time:
                        self._output_event(t, sequence)
                        fired_since_last_snapshot.add(t.id)

            fired_since_last_snapshot |= self._input_all(sequence)
            self._steps += 1

            if step_mode:
                if self._steps % snapshot_interval == 0:  # type: ignore[operator]
                    yield self._snapshot(fired_since_last_snapshot, sequence)
                    fired_since_last_snapshot = set()
                    sequence = []
            else:
                if self._current_time >= next_snapshot_at:
                    yield self._snapshot(fired_since_last_snapshot, sequence)
                    fired_since_last_snapshot = set()
                    sequence = []
                    ts = time_step or 1.0
                    next_snapshot_at = (int(self._current_time / ts) + 1) * ts

        yield self._snapshot(fired_since_last_snapshot, sequence)

    def _snapshot(
        self,
        fired: set[str] | None = None,
        sequence: list[FiringStep] | None = None,
    ) -> SimulationEvent:
        progress = self._current_time / self._simulation_time if self._simulation_time > 0 else 1.0
        return SimulationEvent(
            current_time=self._current_time,
            step_number=self._steps,
            markings={p.id: p.mark for p in self._places},
            buffers={t.id: t.buffer for t in self._transitions},
            progress=min(progress, 1.0),
            fired_transitions=list(fired) if fired else [],
            firing_sequence=list(sequence) if sequence else [],
        )

    def _collect_results(self) -> SimulationResult:
        places = [
            PlaceStatistics(
                id=p.id,
                name=p.name,
                final_marking=p.mark,
                mean_marking=round(p.mean, 4),
                observed_min=p.observed_min,
                observed_max=p.observed_max,
            )
            for p in self._places
        ]
        transitions = [
            TransitionStatistics(
                id=t.id,
                name=t.name,
                final_buffer=t.buffer,
                mean_buffer=round(t.mean, 4),
                observed_min=t.observed_min,
                observed_max=t.observed_max,
            )
            for t in self._transitions
        ]
        terminators = [
            TerminatorStatistics(
                id=p.id,
                name=p.name,
                total_consumed=p.mark,
            )
            for p in self._places
            if p.tag == "throughput"
        ]
        warnings: list[str] = []
        for t in self._transitions:
            if t.distribution == "norm" and t.parameter > 0 and t.deviation > t.parameter / 3:
                warnings.append(
                    f"Transition '{t.name}' uses norm(mean={t.parameter:g}, "
                    f"stdev={t.deviation:g}): stdev is large relative to mean, so "
                    f"truncation-at-zero will shift the effective mean upward and "
                    f"reduce throughput. Likely cause: stdev was supplied in a "
                    f"different time unit than the mean. Check unit consistency "
                    f"(both must be in the same unit before time_unit conversion)."
                )
            elif t.distribution == "unif" and t.parameter - t.deviation < 0:
                warnings.append(
                    f"Transition '{t.name}' uses unif(low={t.parameter - t.deviation:g}, "
                    f"high={t.parameter + t.deviation:g}): lower bound is negative, "
                    f"so samples are truncated and the effective mean shifts upward. "
                    f"Check that deviation is in the same unit as the mean."
                )
        return SimulationResult(
            simulation_time=self._simulation_time,
            final_time=self._current_time,
            total_steps=self._steps,
            places=places,
            transitions=transitions,
            terminators=terminators,
            warnings=warnings,
        )
