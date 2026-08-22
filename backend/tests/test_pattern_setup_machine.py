"""Tests for SetupMachine pattern."""

import pytest

from src.domain import DistributionType, PetriNet
from src.domain.patterns import SetupMachinePattern
from src.services.petri.builder import PetriNetBuilder
from src.services.simulation.engine import PetriSimulator


def test_setup_machine_topology():
    net = PetriNet(name="test")
    result = SetupMachinePattern().apply(
        net, "CNC", 0, 0,
        setup_time=15.0,
        processing_time=60.0,
        channels=2,
    )

    assert result.interface.input_place_id is not None
    assert result.interface.output_place_id is not None
    # Queue + Free(c) + SettingUp + Ready + Processing + Done = 6 places
    assert len(result.place_ids) == 6
    # StartSetup + FinishSetup + StartProcess + FinishProcess = 4 transitions
    assert len(result.transition_ids) == 4


def test_setup_machine_interface_contract():
    net = PetriNet(name="test")
    result = SetupMachinePattern().apply(net, "Press", 0, 0, setup_time=10.0, processing_time=30.0)

    assert "setup_place_id" in result.metadata
    assert "consume_transition_ids" in result.metadata
    assert len(result.metadata["consume_transition_ids"]) == 1

    setup_place = net.get_place(result.metadata["setup_place_id"])
    assert setup_place is not None
    assert "SettingUp" in setup_place.name


def test_setup_machine_channels_initialized():
    net = PetriNet(name="test")
    result = SetupMachinePattern().apply(net, "M", 0, 0, setup_time=5.0, processing_time=10.0, channels=3)
    free_place = net.get_place(result.place_ids[1])
    assert free_place.tokens == 3


def test_setup_machine_transition_names():
    net = PetriNet(name="test")
    SetupMachinePattern().apply(net, "CNC", 0, 0, setup_time=5.0, processing_time=10.0)
    names = {t.name for t in net.transitions}
    assert "CNC_StartSetup" in names
    assert "CNC_FinishSetup" in names
    assert "CNC_StartProcess" in names
    assert "CNC_FinishProcess" in names


def test_setup_machine_processes_single_job():
    """One job goes through setup then processing and reaches Done."""
    builder = PetriNetBuilder()
    result = builder.add_setup_machine(
        "CNC",
        setup_time=1.0,
        processing_time=1.0,
        setup_distribution=DistributionType.DET,
        processing_distribution=DistributionType.DET,
    )

    builder.net.get_place(result.interface.input_place_id).tokens = 1

    sim = PetriSimulator(builder.net).run(100.0)
    marks = {s.id: s.final_marking for s in sim.places}

    assert marks.get(result.interface.output_place_id, 0) == 1
    assert marks.get(result.metadata["setup_place_id"], 0) == 0


def test_setup_machine_channel_recycled():
    """Channel token is returned after processing completes."""
    builder = PetriNetBuilder()
    result = builder.add_setup_machine(
        "Press",
        setup_time=1.0,
        processing_time=1.0,
        channels=2,
    )

    builder.net.get_place(result.interface.input_place_id).tokens = 1

    sim = PetriSimulator(builder.net).run(100.0)
    marks = {s.id: s.final_marking for s in sim.places}

    # Free channels should be restored to 2 after the job completes
    free_place_id = result.place_ids[1]
    assert marks.get(free_place_id, 0) == 2


def test_setup_machine_throughput():
    """Multiple jobs processed sequentially through setup + process phases."""
    builder = PetriNetBuilder()
    gen = builder.add_generator("Jobs", interval=3.0, distribution=DistributionType.DET)
    sm = builder.add_setup_machine(
        "Machine",
        setup_time=1.0,
        processing_time=1.0,
        channels=1,
    )
    term = builder.add_terminator("Out")

    builder.connect(gen.interface.output_place_id, sm.interface.input_place_id)
    builder.connect(sm.interface.output_place_id, term.interface.input_place_id)

    is_valid, errors = builder.validate()
    assert is_valid, errors

    sim = PetriSimulator(builder.net).run(60.0)

    # At interval=3 and setup+process=2, expect ~20 jobs in 60 s
    throughput_stats = [t for t in sim.terminators if "Out" in t.name]
    assert len(throughput_stats) > 0
    assert throughput_stats[0].total_consumed > 0
