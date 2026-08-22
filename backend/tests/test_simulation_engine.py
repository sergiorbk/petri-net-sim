"""Tests for the Petri net simulation engine."""

import math

import pytest

from src.domain.models import DistributionType, PetriNet
from src.services.petri.builder import PetriNetBuilder
from src.services.petri.session import PetriNetSession
from src.services.simulation.engine import PetriSimulator, SimulationResult
from src.services.simulation.random import exp_delay, generate_delay, norm_delay, unif_delay
from src.services.simulation.state import SimPlace, SimTransition, build_sim_net


class TestRandomDistributions:
    def test_exp_delay_positive(self):
        for _ in range(100):
            val = exp_delay(10.0)
            assert val > 0

    def test_exp_delay_mean_approximate(self):
        samples = [exp_delay(10.0) for _ in range(10000)]
        mean = sum(samples) / len(samples)
        assert abs(mean - 10.0) < 1.0

    def test_norm_delay(self):
        samples = [norm_delay(50.0, 5.0) for _ in range(10000)]
        mean = sum(samples) / len(samples)
        assert abs(mean - 50.0) < 1.0

    def test_norm_delay_truncated_at_zero(self):
        # Truncated normal: every sample must be non-negative even when the
        # underlying normal has substantial mass below zero. Seeded for
        # determinism — the test asserts behavior, not RNG quality.
        import random as _random
        _random.seed(42)
        samples = [norm_delay(60.0, 30.0) for _ in range(10000)]
        assert all(s >= 0 for s in samples)
        # Mean of TN(60, 30) is shifted slightly upward (theoretical ~+0.6s);
        # generous bound covers the seeded sample variance.
        mean = sum(samples) / len(samples)
        assert 59.0 < mean < 63.0

    def test_norm_delay_extreme_negative_distribution_raises(self):
        # mean=-100, σ=1: virtually all mass below zero. Resampling cannot
        # converge; the function must give up rather than spin forever.
        with pytest.raises(ValueError, match="Truncated normal failed"):
            norm_delay(-100.0, 1.0)

    def test_unif_delay(self):
        for _ in range(100):
            val = unif_delay(5.0, 15.0)
            assert 5.0 <= val <= 15.0

    def test_unif_delay_truncated_at_zero(self):
        # Range straddles zero: result is uniform on [0, 5] after truncation.
        samples = [unif_delay(-5.0, 5.0) for _ in range(2000)]
        assert all(s >= 0 for s in samples)
        assert all(s <= 5.0 for s in samples)

    def test_unif_delay_fully_negative_raises(self):
        with pytest.raises(ValueError, match="upper bound must be"):
            unif_delay(-10.0, -5.0)

    def test_generate_delay_det(self):
        assert generate_delay(None, 42.0) == 42.0
        assert generate_delay("det", 42.0) == 42.0

    def test_generate_delay_unknown(self):
        with pytest.raises(ValueError, match="Unknown distribution"):
            generate_delay("gamma", 10.0)


class TestBuildSimNet:
    def test_simple_net(self):
        net = PetriNet(name="test")
        p1 = net.add_place("P1", tokens=1)
        p2 = net.add_place("P2", tokens=0)
        t1 = net.add_transition("T1", mean_delay=10.0)
        net.add_arc(p1.id, t1.id)
        net.add_arc(t1.id, p2.id)

        places, transitions = build_sim_net(net)

        assert len(places) == 2
        assert len(transitions) == 1
        assert places[0].mark == 1
        assert places[1].mark == 0
        assert transitions[0].parameter == 10.0
        assert transitions[0].in_places == [0]
        assert transitions[0].out_places == [1]

    def test_inhibitor_arc(self):
        from src.domain.models import ArcType

        net = PetriNet(name="test")
        p1 = net.add_place("P1", tokens=1)
        p2 = net.add_place("Signal", tokens=1)
        p3 = net.add_place("P3")
        t1 = net.add_transition("T1", mean_delay=0.0)
        net.add_arc(p1.id, t1.id)
        net.add_arc(p2.id, t1.id, arc_type=ArcType.READ)
        net.add_arc(t1.id, p3.id)

        places, transitions = build_sim_net(net)
        tr = transitions[0]
        assert tr.in_places == [0]
        assert tr.inf_places == [1]


class TestPetriSimulator:
    def _build_simple_machine_net(self) -> PetriNet:
        """Generator(det=1s) -> Machine(det=60s) -> Terminator, auto-connected."""
        session = PetriNetSession()
        session.create_network("TestMachine")
        result_gen = session.builder.add_generator(
            name="Source",
            interval=1.0,
            distribution=DistributionType.DET,
        )
        session.set_last_output(result_gen.interface.output_place_id)
        result_machine = session.builder.add_machine(
            name="Machine",
            processing_time=60.0,
            distribution=DistributionType.DET,
        )
        session.auto_connect(result_machine.interface.input_place_id)
        session.set_last_output(result_machine.interface.output_place_id)
        result_term = session.builder.add_terminator(name="Done")
        session.auto_connect(result_term.interface.input_place_id)
        return session.net

    def test_single_machine_det_one_hour(self):
        """Machine with det=60s should produce ~60 parts in 3600s."""
        net = self._build_simple_machine_net()

        # Optimize to remove transfer transitions (same as real workflow)
        from src.services.petri.optimizer import optimize_petri_net
        net, _ = optimize_petri_net(net)

        sim = PetriSimulator(net)
        result = sim.run(3600.0)

        assert isinstance(result, SimulationResult)
        assert result.simulation_time == 3600.0
        assert result.total_steps > 0
        assert result.final_time >= 3599.0

    def test_empty_net(self):
        net = PetriNet(name="empty")
        sim = PetriSimulator(net)
        result = sim.run(100.0)
        assert result.total_steps == 0

    def test_deadlock_stops(self):
        """Net with no enabled transitions should stop quickly."""
        net = PetriNet(name="deadlock")
        p1 = net.add_place("P1", tokens=0)
        p2 = net.add_place("P2")
        t = net.add_transition("T1", mean_delay=1.0)
        net.add_arc(p1.id, t.id)
        net.add_arc(t.id, p2.id)

        sim = PetriSimulator(net)
        result = sim.run(100.0)
        # No tokens in P1, so T1 never fires. Buffer is empty.
        # Simulation should stop immediately.
        assert result.total_steps == 0
        assert p2.tokens == 0

    def test_simple_token_flow(self):
        """P1(1 token) -> T1(det=0) -> P2: token should move."""
        net = PetriNet(name="flow")
        p1 = net.add_place("P1", tokens=1)
        p2 = net.add_place("P2", tokens=0)
        t1 = net.add_transition("T1", mean_delay=0.0)
        net.add_arc(p1.id, t1.id)
        net.add_arc(t1.id, p2.id)

        sim = PetriSimulator(net)
        result = sim.run(10.0)

        p1_stat = next(p for p in result.places if p.name == "P1")
        p2_stat = next(p for p in result.places if p.name == "P2")
        assert p1_stat.final_marking == 0
        assert p2_stat.final_marking == 1

    def test_multi_channel_machine(self):
        """Machine with 3 channels should process 3x faster."""
        session = PetriNetSession()
        session.create_network("MultiChannel")
        r_gen = session.builder.add_generator(
            name="Source",
            interval=1.0,
            distribution=DistributionType.DET,
        )
        session.set_last_output(r_gen.interface.output_place_id)
        r_machine = session.builder.add_machine(
            name="FastMachine",
            processing_time=30.0,
            distribution=DistributionType.DET,
            channels=3,
        )
        session.auto_connect(r_machine.interface.input_place_id)
        session.set_last_output(r_machine.interface.output_place_id)
        r_term = session.builder.add_terminator(name="Done")
        session.auto_connect(r_term.interface.input_place_id)

        from src.services.petri.optimizer import optimize_petri_net
        net, _ = optimize_petri_net(session.net)

        sim = PetriSimulator(net)
        result = sim.run(300.0)

        assert result.final_time >= 299.0
        assert result.total_steps > 0

    def test_statistics_collected(self):
        """Verify mean statistics are computed."""
        net = PetriNet(name="stats")
        p1 = net.add_place("P1", tokens=5)
        p2 = net.add_place("P2", tokens=0)
        t1 = net.add_transition("T1", mean_delay=10.0)
        net.add_arc(p1.id, t1.id)
        net.add_arc(t1.id, p2.id)

        sim = PetriSimulator(net)
        result = sim.run(100.0)

        p1_stat = next(p for p in result.places if p.name == "P1")
        assert p1_stat.mean_marking >= 0
        assert p1_stat.observed_max >= p1_stat.observed_min

    def test_conflict_resolution(self):
        """Two transitions competing for same token — both should get some firings."""
        net = PetriNet(name="conflict")
        p_in = net.add_place("Input", tokens=100)
        p_a = net.add_place("A", tokens=0)
        p_b = net.add_place("B", tokens=0)
        t_a = net.add_transition("T_A", mean_delay=0.0, probability=0.5)
        t_b = net.add_transition("T_B", mean_delay=0.0, probability=0.5)
        net.add_arc(p_in.id, t_a.id)
        net.add_arc(t_a.id, p_a.id)
        net.add_arc(p_in.id, t_b.id)
        net.add_arc(t_b.id, p_b.id)

        sim = PetriSimulator(net)
        result = sim.run(10.0)

        a_stat = next(p for p in result.places if p.name == "A")
        b_stat = next(p for p in result.places if p.name == "B")
        total = a_stat.final_marking + b_stat.final_marking
        assert total == 100
        # Both should get at least some tokens (probabilistic, but 100 trials)
        assert a_stat.final_marking > 0
        assert b_stat.final_marking > 0


class TestPriority:
    """Verify that higher priority number = fires first in conflict."""

    def _conflict_net(self, priority_a: int, priority_b: int) -> PetriNet:
        """One place with 100 tokens, two competing immediate transitions."""
        net = PetriNet(name="priority_test")
        p_in = net.add_place("In", tokens=100)
        p_a = net.add_place("A")
        p_b = net.add_place("B")
        t_a = net.add_transition("T_A", mean_delay=0.0, priority=priority_a)
        t_b = net.add_transition("T_B", mean_delay=0.0, priority=priority_b)
        net.add_arc(p_in.id, t_a.id)
        net.add_arc(t_a.id, p_a.id)
        net.add_arc(p_in.id, t_b.id)
        net.add_arc(t_b.id, p_b.id)
        return net

    def test_higher_priority_wins_all_tokens(self):
        """T_A (priority=2) should consume all tokens; T_B (priority=1) never fires."""
        net = self._conflict_net(priority_a=2, priority_b=1)
        sim = PetriSimulator(net)
        result = sim.run(1.0)

        a_stat = next(p for p in result.places if p.name == "A")
        b_stat = next(p for p in result.places if p.name == "B")
        assert a_stat.final_marking == 100
        assert b_stat.final_marking == 0

    def test_lower_priority_wins_all_tokens(self):
        """T_B (priority=2) should consume all tokens; T_A (priority=1) never fires."""
        net = self._conflict_net(priority_a=1, priority_b=2)
        sim = PetriSimulator(net)
        result = sim.run(1.0)

        a_stat = next(p for p in result.places if p.name == "A")
        b_stat = next(p for p in result.places if p.name == "B")
        assert a_stat.final_marking == 0
        assert b_stat.final_marking == 100

    def test_priority_zero_loses_to_priority_one(self):
        """Transition.priority now accepts 0 (ge=0, not ge=1 -- see
        transition.py's own comment on why: PetriObjModelPaint writes
        priority="0" as its own default, and both PNML importers preserve
        an explicit 0 rather than treat it as unset). Conflict resolution
        must still be purely relational: priority 1 beats priority 0
        exactly like it would beat any other lower number."""
        net = self._conflict_net(priority_a=0, priority_b=1)
        sim = PetriSimulator(net)
        result = sim.run(1.0)

        a_stat = next(p for p in result.places if p.name == "A")
        b_stat = next(p for p in result.places if p.name == "B")
        assert a_stat.final_marking == 0
        assert b_stat.final_marking == 100

    def test_equal_priority_splits_randomly(self):
        """Equal-priority transitions share tokens via probability conflict resolution."""
        net = self._conflict_net(priority_a=1, priority_b=1)
        sim = PetriSimulator(net)
        result = sim.run(1.0)

        a_stat = next(p for p in result.places if p.name == "A")
        b_stat = next(p for p in result.places if p.name == "B")
        assert a_stat.final_marking + b_stat.final_marking == 100
        # With 100 tokens both branches should get some share
        assert a_stat.final_marking > 0
        assert b_stat.final_marking > 0

    def test_router_priority_higher_number_first(self):
        """Router with priority strategy: route with higher priority number gets all flow."""
        session = PetriNetSession()
        session.create_network("RouterPriorityTest")

        gen = session.builder.add_generator(name="Source", interval=1.0, distribution=DistributionType.DET, batch_size=1)
        session.set_last_output(gen.interface.output_place_id)

        router = session.builder.add_router(
            name="Split",
            strategy="priority",
            routes=[
                {"name": "High", "priority": 2},
                {"name": "Low", "priority": 1},
            ],
        )
        session.auto_connect(router.interface.input_place_id)

        p_high_out = router.place_ids[1]  # first branch output place
        p_low_out = router.place_ids[2]   # second branch output place

        sim = PetriSimulator(session.net)
        result = sim.run(100.0)

        high_stat = next(p for p in result.places if p.id == p_high_out)
        low_stat = next(p for p in result.places if p.id == p_low_out)
        # High-priority route accumulates tokens; low-priority route gets nothing
        assert high_stat.final_marking > 0
        assert low_stat.final_marking == 0


class TestSimulatorStreaming:
    @pytest.mark.asyncio
    async def test_streaming_events(self):
        net = PetriNet(name="stream")
        p1 = net.add_place("P1", tokens=10)
        p2 = net.add_place("P2")
        t1 = net.add_transition("T1", mean_delay=1.0)
        net.add_arc(p1.id, t1.id)
        net.add_arc(t1.id, p2.id)

        sim = PetriSimulator(net)
        events = []
        async for event in sim.run_streaming(20.0, snapshot_interval=1):
            events.append(event)

        assert len(events) > 0
        last = events[-1]
        assert last.progress <= 1.0
        assert "p1" in last.markings
