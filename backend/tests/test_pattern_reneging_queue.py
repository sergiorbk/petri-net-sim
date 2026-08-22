"""Tests for RenegingQueue pattern."""

import pytest

from src.domain import DistributionType, PetriNet
from src.domain.patterns import RenegingQueuePattern
from src.services.petri.builder import PetriNetBuilder
from src.services.simulation.engine import PetriSimulator


def test_reneging_queue_topology():
    net = PetriNet(name="test")
    result = RenegingQueuePattern().apply(
        net, "CQ", 0, 0,
        timeout=60.0,
        service_time=30.0,
        channels=2,
    )

    assert result.interface.input_place_id is not None
    assert result.interface.output_place_id is not None
    # 5 places: Queue, Free(c), Processing, Done, Abandoned
    assert len(result.place_ids) == 5
    # 3 transitions: Start, Finish, Renege
    assert len(result.transition_ids) == 3


def test_reneging_queue_interface_contract():
    net = PetriNet(name="test")
    result = RenegingQueuePattern().apply(net, "Q", 0, 0, timeout=10.0, service_time=5.0)

    assert "abandoned_place_id" in result.metadata
    assert "consume_transition_ids" in result.metadata
    assert len(result.metadata["consume_transition_ids"]) == 1

    abandoned = net.get_place(result.metadata["abandoned_place_id"])
    assert abandoned is not None
    assert abandoned.tag == "reneged"


def test_reneging_queue_channels_initialized():
    net = PetriNet(name="test")
    result = RenegingQueuePattern().apply(net, "Q", 0, 0, timeout=60.0, service_time=30.0, channels=3)
    # Free place holds 3 tokens (one per channel)
    free_place = net.get_place(result.place_ids[1])
    assert free_place.tokens == 3


def test_reneging_queue_transition_priorities():
    net = PetriNet(name="test")
    RenegingQueuePattern().apply(net, "Q", 0, 0, timeout=60.0, service_time=30.0)

    transitions = {t.name.split("_")[-1]: t for t in net.transitions}
    assert transitions["Start"].priority == 2
    assert transitions["Renege"].priority == 1


def test_reneging_queue_served_when_channel_free():
    """Customer is served when a channel is free (no reneging)."""
    builder = PetriNetBuilder()
    result = builder.add_reneging_queue(
        "Q",
        timeout=3600.0,    # very long timeout — nobody should renege
        service_time=1.0,
        channels=1,
    )

    # Inject one customer
    builder.net.get_place(result.interface.input_place_id).tokens = 1

    sim = PetriSimulator(builder.net).run(100.0)
    marks = {s.id: s.final_marking for s in sim.places}

    assert marks.get(result.interface.output_place_id, 0) == 1
    assert marks.get(result.metadata["abandoned_place_id"], 0) == 0


def test_reneging_queue_renege_when_busy():
    """Customer reneges when all channels are busy (server occupied)."""
    builder = PetriNetBuilder()
    result = builder.add_reneging_queue(
        "Q",
        timeout=1.0,       # very short timeout
        service_time=500.0,  # very long service — channel always busy
        channels=1,
    )

    queue = builder.net.get_place(result.interface.input_place_id)
    # First customer occupies the single channel
    queue.tokens = 2
    # Pre-occupy the channel so 2nd customer has no free server
    free_place = builder.net.get_place(result.place_ids[1])
    free_place.tokens = 0
    processing_place = builder.net.get_place(result.place_ids[2])
    processing_place.tokens = 1

    sim = PetriSimulator(builder.net).run(50.0)
    marks = {s.id: s.final_marking for s in sim.places}

    # Both customers in queue should renege (server never frees)
    assert marks.get(result.metadata["abandoned_place_id"], 0) >= 1


def test_reneging_queue_builder_end_to_end():
    """End-to-end: generator -> reneging queue with short timeout -> terminator."""
    builder = PetriNetBuilder()
    gen = builder.add_generator("Arrivals", interval=5.0)
    rq = builder.add_reneging_queue("Queue", timeout=8.0, service_time=20.0, channels=1)
    term = builder.add_terminator("Exit")

    builder.connect(gen.interface.output_place_id, rq.interface.input_place_id)
    builder.connect(rq.interface.output_place_id, term.interface.input_place_id)

    is_valid, errors = builder.validate()
    assert is_valid, errors

    sim = PetriSimulator(builder.net).run(300.0)
    marks = {s.id: s.final_marking for s in sim.places}

    # Some customers should be abandoned (timeout < service_time)
    assert marks.get(rq.metadata["abandoned_place_id"], 0) > 0
