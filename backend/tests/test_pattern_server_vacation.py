"""Tests for ServerVacation (N-policy) pattern."""

import pytest

from src.domain import DistributionType, PetriNet
from src.domain.patterns import ServerVacationPattern
from src.services.petri.builder import PetriNetBuilder
from src.services.simulation.engine import PetriSimulator


def test_server_vacation_topology():
    net = PetriNet(name="test")
    result = ServerVacationPattern().apply(
        net, "Batch", 0, 0,
        threshold=5,
        processing_time=10.0,
    )

    assert result.interface.input_place_id is not None
    assert result.interface.output_place_id is not None
    # Queue + Vacation + Active + Processing + Done = 5 places
    assert len(result.place_ids) == 5
    # Activate + StartJob + FinishJob + Deactivate = 4 transitions
    assert len(result.transition_ids) == 4


def test_server_vacation_interface_contract():
    net = PetriNet(name="test")
    result = ServerVacationPattern().apply(net, "Proc", 0, 0, threshold=3, processing_time=5.0)

    assert "active_place_id" in result.metadata
    assert "vacation_place_id" in result.metadata

    active = net.get_place(result.metadata["active_place_id"])
    vacation = net.get_place(result.metadata["vacation_place_id"])
    assert active is not None
    assert vacation is not None


def test_server_vacation_starts_on_vacation_by_default():
    net = PetriNet(name="test")
    result = ServerVacationPattern().apply(net, "S", 0, 0, threshold=3, processing_time=1.0)

    vacation_place = net.get_place(result.metadata["vacation_place_id"])
    active_place = net.get_place(result.metadata["active_place_id"])
    assert vacation_place.tokens == 1
    assert active_place.tokens == 0


def test_server_vacation_starts_active():
    net = PetriNet(name="test")
    result = ServerVacationPattern().apply(
        net, "S", 0, 0,
        threshold=3,
        processing_time=1.0,
        starts_active=True,
    )

    vacation_place = net.get_place(result.metadata["vacation_place_id"])
    active_place = net.get_place(result.metadata["active_place_id"])
    assert active_place.tokens == 1
    assert vacation_place.tokens == 0


def test_server_vacation_threshold_validation():
    net = PetriNet(name="test")
    with pytest.raises(ValueError, match="threshold"):
        ServerVacationPattern().apply(net, "S", 0, 0, threshold=0, processing_time=1.0)


def test_server_vacation_transition_priorities():
    net = PetriNet(name="test")
    ServerVacationPattern().apply(net, "S", 0, 0, threshold=3, processing_time=1.0)

    transitions = {t.name.split("_", 1)[1]: t for t in net.transitions}
    assert transitions["StartJob"].priority == 2
    assert transitions["Deactivate"].priority == 1
    assert transitions["Activate"].priority == 2


def test_server_vacation_does_not_activate_below_threshold():
    """Server stays on vacation when queue < threshold."""
    builder = PetriNetBuilder()
    result = builder.add_server_vacation("Batch", threshold=5, processing_time=1.0)

    queue = builder.net.get_place(result.interface.input_place_id)
    queue.tokens = 3  # below threshold=5

    sim = PetriSimulator(builder.net).run(50.0)
    marks = {s.id: s.final_marking for s in sim.places}

    # Server should stay on vacation — nothing processed
    assert marks.get(result.interface.output_place_id, 0) == 0
    assert marks.get(result.metadata["vacation_place_id"], 0) == 1


def test_server_vacation_activates_at_threshold():
    """Server activates when queue reaches threshold and drains it."""
    builder = PetriNetBuilder()
    result = builder.add_server_vacation(
        "Batch", threshold=3,
        processing_time=1.0,
        distribution=DistributionType.DET,
    )

    queue = builder.net.get_place(result.interface.input_place_id)
    queue.tokens = 5  # above threshold=3

    sim = PetriSimulator(builder.net).run(200.0)
    marks = {s.id: s.final_marking for s in sim.places}

    # All 5 jobs should eventually be processed
    assert marks.get(result.interface.output_place_id, 0) == 5
    # Server returns to vacation when queue drains
    assert marks.get(result.metadata["vacation_place_id"], 0) == 1
    assert marks.get(result.metadata["active_place_id"], 0) == 0


def test_server_vacation_end_to_end():
    """End-to-end: slow generator -> server vacation (threshold=5) -> terminator."""
    builder = PetriNetBuilder()
    gen = builder.add_generator("Jobs", interval=5.0, distribution=DistributionType.DET)
    sv = builder.add_server_vacation(
        "BatchProc", threshold=5,
        processing_time=2.0,
        distribution=DistributionType.DET,
    )
    term = builder.add_terminator("Out")

    builder.connect(gen.interface.output_place_id, sv.interface.input_place_id)
    builder.connect(sv.interface.output_place_id, term.interface.input_place_id)

    is_valid, errors = builder.validate()
    assert is_valid, errors

    # Run long enough for multiple activation cycles
    sim = PetriSimulator(builder.net).run(500.0)

    throughput_stats = [t for t in sim.terminators if "Out" in t.name]
    assert len(throughput_stats) > 0
    assert throughput_stats[0].total_consumed > 0
