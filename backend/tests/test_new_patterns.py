"""Tests for new patterns: Merge, Duplicate, Batch, Unbatch, Breakdown, ScheduledAvailability."""

import pytest

from src.domain import DistributionType, PetriNet
from src.domain.patterns import (
    BatchPattern,
    BreakdownPattern,
    DuplicatePattern,
    MergePattern,
    ScheduledAvailabilityPattern,
    UnbatchPattern,
)
from src.services.petri.builder import PetriNetBuilder
from src.services.simulation.engine import PetriSimulator


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def test_merge_creates_correct_topology():
    net = PetriNet(name="test")
    result = MergePattern().apply(net, "M", 0, 0, inputs=["A", "B", "C"])

    assert result.interface.input_place_id is None
    assert result.interface.output_place_id is not None
    assert len(result.metadata["input_place_ids"]) == 3
    assert set(result.metadata["input_place_ids"].keys()) == {"A", "B", "C"}
    # 1 output place + 3 input places = 4 places; 3 transitions
    assert len(result.place_ids) == 4
    assert len(result.transition_ids) == 3


def test_merge_fires_from_any_input():
    """Token from any single input reaches the shared output."""
    builder = PetriNetBuilder()
    result = builder.add_merge("Orders", inputs=["Web", "Phone"])
    ids = result.metadata["input_place_ids"]
    out_id = result.interface.output_place_id

    # Put a token only in Web input
    builder.net.get_place(ids["Web"]).tokens = 1

    sim_result = PetriSimulator(builder.net).run(10.0)
    final_marks = {s.id: s.final_marking for s in sim_result.places}
    assert final_marks.get(out_id, 0) == 1


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


def test_duplicate_creates_correct_topology():
    net = PetriNet(name="test")
    result = DuplicatePattern().apply(net, "D", 0, 0, outputs=["Warehouse", "Accounting"])

    assert result.interface.input_place_id is not None
    assert len(result.metadata["output_place_ids"]) == 2
    # 1 input + 2 outputs = 3 places; 1 transition
    assert len(result.place_ids) == 3
    assert len(result.transition_ids) == 1


def test_duplicate_produces_n_copies():
    """One input token produces one token in each output branch."""
    builder = PetriNetBuilder()
    result = builder.add_duplicate("Broadcast", outputs=["A", "B", "C"])

    # Seed one token in input
    builder.net.get_place(result.interface.input_place_id).tokens = 1

    sim_result = PetriSimulator(builder.net).run(10.0)
    final_marks = {s.id: s.final_marking for s in sim_result.places}

    out_ids = result.metadata["output_place_ids"]
    for branch_id in out_ids.values():
        assert final_marks.get(branch_id, 0) == 1, f"branch {branch_id} has no token"


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


def test_batch_holds_until_n():
    """N-1 tokens do not release; Nth token triggers release."""
    builder = PetriNetBuilder()
    result = builder.add_batch("Packer", batch_size=3)
    buf_id = result.metadata["buffer_place_id"]

    # Put 2 tokens in input (< batch_size)
    builder.net.get_place(result.interface.input_place_id).tokens = 2
    sim_result = PetriSimulator(builder.net).run(5.0)
    marks = {s.id: s.final_marking for s in sim_result.places}
    assert marks.get(result.interface.output_place_id, 0) == 0
    assert marks.get(buf_id, 0) == 2

    # Now put 3 tokens — release should fire once
    builder2 = PetriNetBuilder()
    r2 = builder2.add_batch("Packer2", batch_size=3)
    builder2.net.get_place(r2.interface.input_place_id).tokens = 3
    sim2 = PetriSimulator(builder2.net).run(5.0)
    m2 = {s.id: s.final_marking for s in sim2.places}
    assert m2.get(r2.interface.output_place_id, 0) == 1


def test_batch_invalid_size():
    with pytest.raises(ValueError):
        BatchPattern().apply(PetriNet(name="t"), "B", 0, 0, batch_size=1)


# ---------------------------------------------------------------------------
# Unbatch
# ---------------------------------------------------------------------------


def test_unbatch_expands_token():
    """One input token produces batch_size output tokens."""
    builder = PetriNetBuilder()
    result = builder.add_unbatch("Unpacker", batch_size=5)

    builder.net.get_place(result.interface.input_place_id).tokens = 1

    sim_result = PetriSimulator(builder.net).run(5.0)
    marks = {s.id: s.final_marking for s in sim_result.places}
    assert marks.get(result.interface.output_place_id, 0) == 5


def test_unbatch_invalid_size():
    with pytest.raises(ValueError):
        UnbatchPattern().apply(PetriNet(name="t"), "U", 0, 0, batch_size=1)


# ---------------------------------------------------------------------------
# Breakdown
# ---------------------------------------------------------------------------


def test_breakdown_topology_valid():
    builder = PetriNetBuilder()
    result = builder.add_breakdown(
        "Lathe",
        service_time=60.0,
        mean_time_between_failures=3600.0,
        mean_time_to_repair=600.0,
    )
    is_valid, errors = builder.net.validate_topology()
    assert is_valid, f"Topology invalid: {errors}"
    assert result.interface.input_place_id is not None
    assert result.interface.output_place_id is not None
    assert result.metadata.get("operational_place_id") is not None
    assert result.metadata.get("failed_place_id") is not None
    assert len(result.place_ids) == 5
    assert len(result.transition_ids) == 4


def test_breakdown_throughput_lower_than_reliable():
    """Machine with frequent failures produces fewer outputs than a reliable machine."""
    sim_time = 3600.0

    def build_reliable():
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=20.0, distribution=DistributionType.DET)
        mach = b.add_machine("M", processing_time=10.0, distribution=DistributionType.DET)
        b.connect(gen.interface.output_place_id, mach.interface.input_place_id)
        term = b.add_terminator("Exit")
        b.connect(mach.interface.output_place_id, term.interface.input_place_id)
        return b.net

    def build_unreliable():
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=20.0, distribution=DistributionType.DET)
        brk = b.add_breakdown(
            "M",
            service_time=10.0,
            mean_time_between_failures=300.0,
            mean_time_to_repair=120.0,
            service_dist=DistributionType.DET,
        )
        b.connect(gen.interface.output_place_id, brk.interface.input_place_id)
        term = b.add_terminator("Exit")
        b.connect(brk.interface.output_place_id, term.interface.input_place_id)
        return b.net

    res_rel = PetriSimulator(build_reliable()).run(sim_time)
    res_brk = PetriSimulator(build_unreliable()).run(sim_time)

    throughput_rel = sum(t.total_consumed for t in res_rel.terminators)
    throughput_brk = sum(t.total_consumed for t in res_brk.terminators)

    assert throughput_brk < throughput_rel, (
        f"Expected breakdown throughput ({throughput_brk}) < "
        f"reliable throughput ({throughput_rel})"
    )


# ---------------------------------------------------------------------------
# ScheduledAvailability
# ---------------------------------------------------------------------------


def test_scheduled_availability_topology_valid():
    builder = PetriNetBuilder()
    result = builder.add_scheduled_availability("Shift", on_duration=100.0, off_duration=50.0)
    is_valid, errors = builder.net.validate_topology()
    assert is_valid, f"Topology invalid: {errors}"
    assert result.metadata.get("signal_place_id") is not None
    assert len(result.place_ids) == 2
    assert len(result.transition_ids) == 2


def test_scheduled_availability_starts_available():
    net = PetriNet(name="test")
    result = ScheduledAvailabilityPattern().apply(
        net, "S", 0, 0, on_duration=100.0, off_duration=50.0, starts_available=True
    )
    active = net.get_place(result.metadata["signal_place_id"])
    assert active.tokens == 1


def test_scheduled_availability_starts_unavailable():
    net = PetriNet(name="test")
    result = ScheduledAvailabilityPattern().apply(
        net, "S", 0, 0, on_duration=100.0, off_duration=50.0, starts_available=False
    )
    active = net.get_place(result.metadata["signal_place_id"])
    assert active.tokens == 0


def test_connect_schedule_gate_adds_read_arc():
    from src.domain import ArcType

    builder = PetriNetBuilder()
    sched = builder.add_scheduled_availability("Shift", on_duration=100.0, off_duration=50.0)
    mach = builder.add_machine("Press", processing_time=10.0)

    # Find Start transition
    start_t = next(t for t in builder.net.transitions if t.name == "Press_Start")
    builder.connect_schedule_gate(sched, start_t.id)

    # Verify a READ arc was added
    signal_id = sched.metadata["signal_place_id"]
    read_arcs = [
        a for a in builder.net.arcs
        if a.source_id == signal_id and a.target_id == start_t.id and a.arc_type == ArcType.READ
    ]
    assert len(read_arcs) == 1
