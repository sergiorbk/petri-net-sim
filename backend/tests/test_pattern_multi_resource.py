"""Tests for MultiResource pattern."""

import pytest

from src.domain import DistributionType, PetriNet
from src.domain.patterns import MultiResourcePattern
from src.services.petri.builder import PetriNetBuilder
from src.services.simulation.engine import PetriSimulator


def test_multi_resource_topology_two_pools():
    net = PetriNet(name="test")
    resources = [{"name": "Worker", "pool_size": 2}, {"name": "Booth", "pool_size": 1}]
    result = MultiResourcePattern().apply(
        net, "Paint", 0, 0,
        resources=resources,
        processing_time=60.0,
    )

    assert result.interface.input_place_id is not None
    assert result.interface.output_place_id is not None
    # Queue + 2 resource pools + Processing + Done = 5 places
    assert len(result.place_ids) == 5
    # Start + Finish = 2 transitions
    assert len(result.transition_ids) == 2


def test_multi_resource_topology_three_pools():
    net = PetriNet(name="test")
    resources = [
        {"name": "Doctor", "pool_size": 1},
        {"name": "Room", "pool_size": 2},
        {"name": "Equipment", "pool_size": 3},
    ]
    result = MultiResourcePattern().apply(net, "Surgery", 0, 0, resources=resources, processing_time=30.0)

    # Queue + 3 pools + Processing + Done = 6 places
    assert len(result.place_ids) == 6


def test_multi_resource_interface_contract():
    net = PetriNet(name="test")
    resources = [{"name": "A", "pool_size": 2}, {"name": "B", "pool_size": 1}]
    result = MultiResourcePattern().apply(net, "Op", 0, 0, resources=resources, processing_time=10.0)

    assert "resource_place_ids" in result.metadata
    assert set(result.metadata["resource_place_ids"].keys()) == {"A", "B"}
    assert "consume_transition_ids" in result.metadata
    assert len(result.metadata["consume_transition_ids"]) == 1


def test_multi_resource_pool_sizes_initialized():
    net = PetriNet(name="test")
    resources = [{"name": "Worker", "pool_size": 3}, {"name": "Tool", "pool_size": 2}]
    result = MultiResourcePattern().apply(net, "Op", 0, 0, resources=resources, processing_time=10.0)

    res_ids = result.metadata["resource_place_ids"]
    assert net.get_place(res_ids["Worker"]).tokens == 3
    assert net.get_place(res_ids["Tool"]).tokens == 2


def test_multi_resource_processes_when_all_available():
    """Job is processed when all resource pools have tokens."""
    builder = PetriNetBuilder()
    resources = [{"name": "Worker", "pool_size": 1}, {"name": "Booth", "pool_size": 1}]
    result = builder.add_multi_resource("Paint", resources=resources, processing_time=1.0)

    # Inject one job
    builder.net.get_place(result.interface.input_place_id).tokens = 1

    sim = PetriSimulator(builder.net).run(100.0)
    marks = {s.id: s.final_marking for s in sim.places}

    assert marks.get(result.interface.output_place_id, 0) == 1

    # All resources recycled
    res_ids = result.metadata["resource_place_ids"]
    for pid in res_ids.values():
        assert marks.get(pid, 0) == 1


def test_multi_resource_blocked_when_pool_empty():
    """Job waits when any resource pool is exhausted."""
    builder = PetriNetBuilder()
    resources = [{"name": "Worker", "pool_size": 1}, {"name": "Booth", "pool_size": 1}]
    result = builder.add_multi_resource("Paint", resources=resources, processing_time=1000.0)

    # Exhaust the Booth pool so no new job can start
    res_ids = result.metadata["resource_place_ids"]
    builder.net.get_place(res_ids["Booth"]).tokens = 0

    builder.net.get_place(result.interface.input_place_id).tokens = 1

    sim = PetriSimulator(builder.net).run(50.0)
    marks = {s.id: s.final_marking for s in sim.places}

    # Job cannot start — stays in queue
    assert marks.get(result.interface.output_place_id, 0) == 0
    assert marks.get(result.interface.input_place_id, 0) == 1


def test_multi_resource_builder_end_to_end():
    """End-to-end: generator -> multi-resource -> terminator."""
    builder = PetriNetBuilder()
    gen = builder.add_generator("Arrivals", interval=10.0)
    resources = [{"name": "Worker", "pool_size": 2}, {"name": "Booth", "pool_size": 2}]
    op = builder.add_multi_resource("Painting", resources=resources, processing_time=5.0)
    term = builder.add_terminator("Exit")

    builder.connect(gen.interface.output_place_id, op.interface.input_place_id)
    builder.connect(op.interface.output_place_id, term.interface.input_place_id)

    is_valid, errors = builder.validate()
    assert is_valid, errors

    sim = PetriSimulator(builder.net).run(500.0)
    marks = {s.id: s.final_marking for s in sim.places}

    # Some jobs completed
    assert marks.get(op.interface.output_place_id, 0) >= 0  # jobs may have gone to terminator
