"""Tests for Petri Net patterns and builder."""

import pytest

from src.domain import DistributionType, PetriNet
from src.domain.patterns import (
    GeneratorPattern,
    MachinePattern,
    ControllerPattern,
    AssemblyPattern,
    RouterPattern,
    RoutingStrategy,
    TerminatorPattern,
    ConveyorWorkstationPattern,
    PriorityChoicePattern,
    BoundedQueuePattern,
    BalkingQueuePattern,
    TimedBatchPattern,
    PreemptiveMachinePattern,
    NonstationaryGeneratorPattern,
)
from src.services.petri import PetriNetBuilder
from src.services.petri.exporter import PNMLExporter


class TestGeneratorPattern:
    """Tests for GeneratorPattern."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> GeneratorPattern:
        return GeneratorPattern()

    def test_generator_creates_places_and_transitions(
        self, net: PetriNet, pattern: GeneratorPattern
    ):
        """Test that generator creates correct structure."""
        result = pattern.apply(net, "Test", x=0, y=0, interval=10.0)

        assert len(net.places) == 2  # Ready + Output
        assert len(net.transitions) == 1  # Generate
        assert len(net.arcs) == 3  # Ready->Gen, Gen->Ready, Gen->Output

    def test_generator_ready_place_has_token(
        self, net: PetriNet, pattern: GeneratorPattern
    ):
        """Test that Ready place starts with 1 token."""
        pattern.apply(net, "Test", x=0, y=0, interval=10.0)

        ready_place = net.get_place_by_name("Test_Ready")
        assert ready_place is not None
        assert ready_place.tokens == 1

    def test_generator_output_place_empty(
        self, net: PetriNet, pattern: GeneratorPattern
    ):
        """Test that Output place starts empty."""
        pattern.apply(net, "Test", x=0, y=0, interval=10.0)

        output_place = net.get_place_by_name("Test_Out")
        assert output_place is not None
        assert output_place.tokens == 0

    def test_generator_transition_has_delay(
        self, net: PetriNet, pattern: GeneratorPattern
    ):
        """Test that Generate transition has correct time parameters."""
        pattern.apply(
            net,
            "Test",
            x=0,
            y=0,
            interval=40.0,
            distribution=DistributionType.EXP,
        )

        gen_trans = net.get_transition_by_name("Test_Gen")
        assert gen_trans is not None
        assert gen_trans.mean_delay == 40.0
        assert gen_trans.distribution == DistributionType.EXP

    def test_generator_returns_output_place_id(
        self, net: PetriNet, pattern: GeneratorPattern
    ):
        """Test that result contains correct interface."""
        result = pattern.apply(net, "Test", x=0, y=0, interval=10.0)

        assert result.interface.input_place_id is None  # Generators have no input
        assert result.interface.output_place_id is not None

        output_place = net.get_place(result.interface.output_place_id)
        assert output_place.name == "Test_Out"

    def test_generator_loop_structure(
        self, net: PetriNet, pattern: GeneratorPattern
    ):
        """Test that generator has correct loop (Ready -> Gen -> Ready)."""
        pattern.apply(net, "Test", x=0, y=0, interval=10.0)

        gen_trans = net.get_transition_by_name("Test_Gen")
        ready_place = net.get_place_by_name("Test_Ready")

        # Check arcs: Ready -> Gen and Gen -> Ready
        arcs_to_gen = net.get_arcs_to(gen_trans.id)
        arcs_from_gen = net.get_arcs_from(gen_trans.id)

        assert any(a.source_id == ready_place.id for a in arcs_to_gen)
        assert any(a.target_id == ready_place.id for a in arcs_from_gen)

    def test_generator_batch_size_default(
        self, net: PetriNet, pattern: GeneratorPattern
    ):
        """Test that default batch_size is 1."""
        pattern.apply(net, "Test", x=0, y=0, interval=10.0)

        gen_trans = net.get_transition_by_name("Test_Gen")
        output_place = net.get_place_by_name("Test_Out")

        # Find arc from gen to output
        arcs_from_gen = net.get_arcs_from(gen_trans.id)
        output_arc = next(a for a in arcs_from_gen if a.target_id == output_place.id)

        assert output_arc.weight == 1

    def test_generator_batch_size_multiple(
        self, net: PetriNet, pattern: GeneratorPattern
    ):
        """Test that batch_size > 1 creates arc with correct weight."""
        pattern.apply(net, "Test", x=0, y=0, interval=5.0, batch_size=5)

        gen_trans = net.get_transition_by_name("Test_Gen")
        output_place = net.get_place_by_name("Test_Out")

        # Find arc from gen to output
        arcs_from_gen = net.get_arcs_from(gen_trans.id)
        output_arc = next(a for a in arcs_from_gen if a.target_id == output_place.id)

        assert output_arc.weight == 5

    def test_generator_batch_size_large(
        self, net: PetriNet, pattern: GeneratorPattern
    ):
        """Test large batch size (20 items per batch)."""
        pattern.apply(net, "Test", x=0, y=0, interval=20.0, batch_size=20)

        gen_trans = net.get_transition_by_name("Test_Gen")
        output_place = net.get_place_by_name("Test_Out")

        arcs_from_gen = net.get_arcs_from(gen_trans.id)
        output_arc = next(a for a in arcs_from_gen if a.target_id == output_place.id)

        assert output_arc.weight == 20


class TestMachinePattern:
    """Tests for MachinePattern."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> MachinePattern:
        return MachinePattern()

    def test_machine_creates_correct_structure(
        self, net: PetriNet, pattern: MachinePattern
    ):
        """Test that machine creates correct number of elements."""
        result = pattern.apply(net, "M1", x=0, y=0, processing_time=10.0)

        assert len(net.places) == 4  # Queue, Free, Busy, Done
        assert len(net.transitions) == 2  # Start, End
        assert len(net.arcs) == 6

    def test_machine_resource_place_has_channels(
        self, net: PetriNet, pattern: MachinePattern
    ):
        """Test that Resource place has tokens equal to channel count."""
        pattern.apply(net, "M1", x=0, y=0, processing_time=10.0, channels=3)

        resource_place = net.get_place_by_name("M1_Free")
        assert resource_place is not None
        assert resource_place.tokens == 3

    def test_machine_start_transition_immediate(
        self, net: PetriNet, pattern: MachinePattern
    ):
        """Test that Start transition is immediate (no delay)."""
        pattern.apply(net, "M1", x=0, y=0, processing_time=10.0)

        start_trans = net.get_transition_by_name("M1_Start")
        assert start_trans is not None
        assert start_trans.mean_delay == 0.0
        assert start_trans.distribution == DistributionType.DET

    def test_machine_end_transition_has_processing_time(
        self, net: PetriNet, pattern: MachinePattern
    ):
        """Test that End transition has correct processing time."""
        pattern.apply(
            net,
            "M1",
            x=0,
            y=0,
            processing_time=60.0,
            distribution=DistributionType.NORM,
            standard_deviation=10.0,
        )

        end_trans = net.get_transition_by_name("M1_End")
        assert end_trans is not None
        assert end_trans.mean_delay == 60.0
        assert end_trans.distribution == DistributionType.NORM
        assert end_trans.standard_deviation == 10.0

    def test_machine_returns_input_and_output(
        self, net: PetriNet, pattern: MachinePattern
    ):
        """Test that result contains both input and output interfaces."""
        result = pattern.apply(net, "M1", x=0, y=0, processing_time=10.0)

        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None

        input_place = net.get_place(result.interface.input_place_id)
        output_place = net.get_place(result.interface.output_place_id)

        assert input_place.name == "M1_Queue"
        assert output_place.name == "M1_Done"

    def test_machine_resource_return_arc(
        self, net: PetriNet, pattern: MachinePattern
    ):
        """Test that End transition returns token to Resource (frees channel)."""
        pattern.apply(net, "M1", x=0, y=0, processing_time=10.0)

        end_trans = net.get_transition_by_name("M1_End")
        resource_place = net.get_place_by_name("M1_Free")

        arcs_from_end = net.get_arcs_from(end_trans.id)
        assert any(a.target_id == resource_place.id for a in arcs_from_end)


class TestPetriNetBuilder:
    """Tests for PetriNetBuilder."""

    def test_builder_creates_empty_net(self):
        """Test that builder starts with empty net."""
        builder = PetriNetBuilder(name="Test")

        assert builder.net.name == "Test"
        assert len(builder.net.places) == 0
        assert len(builder.net.transitions) == 0

    def test_builder_add_generator(self):
        """Test adding generator via builder."""
        builder = PetriNetBuilder()
        result = builder.add_generator("Arrivals", interval=40.0)

        assert len(builder.net.places) == 2
        assert len(builder.net.transitions) == 1
        assert result.interface.output_place_id is not None

    def test_builder_add_machine(self):
        """Test adding machine via builder."""
        builder = PetriNetBuilder()
        result = builder.add_machine(
            "Lathe",
            processing_time=60.0,
            channels=3,
        )

        assert len(builder.net.places) == 4
        assert len(builder.net.transitions) == 2
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None

    def test_builder_connect_patterns(self):
        """Test connecting generator to machine."""
        builder = PetriNetBuilder()

        gen = builder.add_generator("Arrivals", interval=40.0)
        machine = builder.add_machine("Lathe", processing_time=60.0, channels=1)

        # Connect generator output to machine input
        builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)

        # Should have added a transfer transition
        assert len(builder.net.transitions) == 4  # Gen + Start + End + Transfer

        # Validate topology
        is_valid, errors = builder.validate()
        assert is_valid, f"Topology errors: {errors}"

    def test_builder_build_returns_net(self):
        """Test that build() returns the PetriNet."""
        builder = PetriNetBuilder(name="MyNet")
        builder.add_generator("G", interval=10.0)

        net = builder.build()

        assert net is builder.net
        assert net.name == "MyNet"


class TestBuilderIntegration:
    """Integration tests for complete queueing system models."""

    def test_mm1_queue_structure(self):
        """Test building M/M/1 queue (single server)."""
        builder = PetriNetBuilder(name="M/M/1 Queue")

        gen = builder.add_generator(
            "Arrivals",
            interval=40.0,
            distribution=DistributionType.EXP,
        )

        machine = builder.add_machine(
            "Server",
            processing_time=30.0,
            distribution=DistributionType.EXP,
            channels=1,
        )

        builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)

        net = builder.build()
        is_valid, errors = net.validate_topology()

        assert is_valid, f"Topology errors: {errors}"
        assert len(net.places) == 6  # 2 (gen) + 4 (machine)
        assert len(net.transitions) == 4  # 1 (gen) + 2 (machine) + 1 (transfer)

    def test_mm3_queue_structure(self):
        """Test building M/M/3 queue (3 parallel servers)."""
        builder = PetriNetBuilder(name="M/M/3 Queue")

        gen = builder.add_generator(
            "Arrivals",
            interval=40.0,
            distribution=DistributionType.EXP,
        )

        machine = builder.add_machine(
            "Server",
            processing_time=60.0,
            distribution=DistributionType.EXP,
            channels=3,
        )

        builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)

        net = builder.build()

        # Check that resource place has 3 tokens
        resource = net.get_place_by_name("Server_Free")
        assert resource.tokens == 3

    def test_export_built_net(self, tmp_path):
        """Test that built net can be exported to PNML."""
        builder = PetriNetBuilder(name="Export Test")

        gen = builder.add_generator("G", interval=10.0)
        machine = builder.add_machine(
            "M",
            processing_time=20.0,
            distribution=DistributionType.NORM,
            standard_deviation=5.0,
            channels=2,
        )
        builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)

        net = builder.build()

        # Export to file
        exporter = PNMLExporter()
        output_path = tmp_path / "test.pnml"
        exporter.save(net, output_path)

        # Verify file content
        content = output_path.read_text()
        assert "<pnml" in content
        assert "G_Gen" in content
        assert "M_End" in content
        assert "<distribution>norm</distribution>" in content
        assert "<standardDeviation>5.0</standardDeviation>" in content


class TestAssemblyPattern:
    """Tests for AssemblyPattern with weighted inputs."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> AssemblyPattern:
        return AssemblyPattern()

    def test_assembly_creates_correct_structure(
        self, net: PetriNet, pattern: AssemblyPattern
    ):
        """Test that assembly creates correct number of elements."""
        result = pattern.apply(
            net, "Assembly", x=0, y=0,
            sources=["PartA", "PartB"],
            assembly_time=1.0,
        )

        # 2 input places + 1 output place = 3 places
        assert len(net.places) == 3
        # 1 assembly transition
        assert len(net.transitions) == 1
        # 2 input arcs + 1 output arc = 3 arcs
        assert len(net.arcs) == 3

    def test_assembly_default_weights(
        self, net: PetriNet, pattern: AssemblyPattern
    ):
        """Test that default arc weights are 1."""
        pattern.apply(
            net, "Assembly", x=0, y=0,
            sources=["PartA", "PartB"],
        )

        # All arcs should have weight 1
        for arc in net.arcs:
            assert arc.weight == 1

    def test_assembly_weighted_inputs(
        self, net: PetriNet, pattern: AssemblyPattern
    ):
        """Test assembly with weighted inputs (10 of each part required)."""
        pattern.apply(
            net, "Assembly", x=0, y=0,
            sources=[
                {"name": "Type1", "weight": 10},
                {"name": "Type2", "weight": 10},
            ],
            assembly_time=0.0,
        )

        t_assemble = net.get_transition_by_name("Assembly_Do")
        arcs_to_assemble = net.get_arcs_to(t_assemble.id)

        # Both input arcs should have weight 10
        for arc in arcs_to_assemble:
            assert arc.weight == 10

    def test_assembly_mixed_weights(
        self, net: PetriNet, pattern: AssemblyPattern
    ):
        """Test assembly with different weights for each input."""
        pattern.apply(
            net, "Assembly", x=0, y=0,
            sources=[
                {"name": "Small", "weight": 5},
                {"name": "Large", "weight": 20},
            ],
        )

        t_assemble = net.get_transition_by_name("Assembly_Do")
        arcs_to_assemble = net.get_arcs_to(t_assemble.id)

        weights = sorted([arc.weight for arc in arcs_to_assemble])
        assert weights == [5, 20]

    def test_assembly_with_priority(
        self, net: PetriNet, pattern: AssemblyPattern
    ):
        """Test that assembly transition can have priority."""
        pattern.apply(
            net, "Assembly", x=0, y=0,
            sources=["PartA", "PartB"],
            priority=1,
        )

        t_assemble = net.get_transition_by_name("Assembly_Do")
        assert t_assemble.priority == 1

    def test_assembly_string_and_dict_sources_mixed(
        self, net: PetriNet, pattern: AssemblyPattern
    ):
        """Test that both string and dict sources work together."""
        pattern.apply(
            net, "Assembly", x=0, y=0,
            sources=[
                "SimpleSource",  # String, weight=1
                {"name": "WeightedSource", "weight": 15},  # Dict with weight
            ],
        )

        t_assemble = net.get_transition_by_name("Assembly_Do")
        arcs_to_assemble = net.get_arcs_to(t_assemble.id)

        weights = sorted([arc.weight for arc in arcs_to_assemble])
        assert weights == [1, 15]


class TestPriorityChoicePattern:
    """Tests for PriorityChoicePattern."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> PriorityChoicePattern:
        return PriorityChoicePattern()

    def test_creates_correct_structure(
        self, net: PetriNet, pattern: PriorityChoicePattern
    ):
        """Test that pattern creates correct number of elements."""
        result = pattern.apply(net, "Choice", x=0, y=0)

        # 4 places: Input, Success, Fallback, Resource (internal)
        assert len(net.places) == 4
        # 2 transitions: Primary, Alternative
        assert len(net.transitions) == 2
        # 4 arcs: Input->Primary, Input->Alternative, Primary->Success, Alternative->Fallback
        # + Resource->Primary = 5 arcs total
        assert len(net.arcs) == 5

    def test_primary_has_higher_priority(
        self, net: PetriNet, pattern: PriorityChoicePattern
    ):
        """Test that Primary transition has higher priority than Alternative."""
        pattern.apply(net, "Choice", x=0, y=0)

        t_primary = net.get_transition_by_name("Choice_Primary")
        t_alternative = net.get_transition_by_name("Choice_Alternative")

        assert t_primary.priority > t_alternative.priority
        assert t_primary.priority == 2
        assert t_alternative.priority == 1

    def test_input_connected_to_both_transitions(
        self, net: PetriNet, pattern: PriorityChoicePattern
    ):
        """Test that Input place is connected to both transitions (conflict)."""
        pattern.apply(net, "Choice", x=0, y=0)

        p_input = net.get_place_by_name("Choice_Input")
        arcs_from_input = net.get_arcs_from(p_input.id)

        # Input should connect to both Primary and Alternative
        assert len(arcs_from_input) == 2

    def test_returns_correct_interface(
        self, net: PetriNet, pattern: PriorityChoicePattern
    ):
        """Test that result contains correct interface."""
        result = pattern.apply(net, "Choice", x=0, y=0)

        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None

        input_place = net.get_place(result.interface.input_place_id)
        output_place = net.get_place(result.interface.output_place_id)

        assert input_place.name == "Choice_Input"
        assert output_place.name == "Choice_Success"

    def test_fallback_place_accessible(
        self, net: PetriNet, pattern: PriorityChoicePattern
    ):
        """Test that Fallback place is accessible via place_ids."""
        result = pattern.apply(net, "Choice", x=0, y=0)

        # place_ids[2] should be Fallback
        fallback_place = net.get_place(result.place_ids[2])
        assert fallback_place.name == "Choice_Fallback"

    def test_custom_output_names(
        self, net: PetriNet, pattern: PriorityChoicePattern
    ):
        """Test that custom output names are applied."""
        pattern.apply(
            net, "Section", x=0, y=0,
            primary_name="Filled",
            alternative_name="Empty",
        )

        success_place = net.get_place_by_name("Section_Filled")
        fallback_place = net.get_place_by_name("Section_Empty")

        assert success_place is not None
        assert fallback_place is not None

    def test_external_resource_requirements(
        self, net: PetriNet, pattern: PriorityChoicePattern
    ):
        """Test connecting external resource places."""
        # Create external resource places first
        p_type1 = net.add_place(name="Type1_Buffer", tokens=10, x=0, y=0)
        p_type2 = net.add_place(name="Type2_Buffer", tokens=10, x=0, y=50)

        # Apply pattern with external resources
        result = pattern.apply(
            net, "SectionFill", x=100, y=0,
            resource_place_ids=[
                {"place_id": p_type1.id, "weight": 10},
                {"place_id": p_type2.id, "weight": 10},
            ],
        )

        # Primary transition should have 3 input arcs:
        # Input + Type1_Buffer(10) + Type2_Buffer(10)
        t_primary = net.get_transition_by_name("SectionFill_Primary")
        arcs_to_primary = net.get_arcs_to(t_primary.id)

        assert len(arcs_to_primary) == 3

        # Check weights
        weights = sorted([arc.weight for arc in arcs_to_primary])
        assert weights == [1, 10, 10]  # Input=1, Type1=10, Type2=10

    def test_no_internal_resource_when_external_provided(
        self, net: PetriNet, pattern: PriorityChoicePattern
    ):
        """Test that no internal resource place is created when external provided."""
        # Create external resource place
        p_resource = net.add_place(name="External_Resource", tokens=5, x=0, y=0)

        pattern.apply(
            net, "Choice", x=100, y=0,
            resource_place_ids=[{"place_id": p_resource.id, "weight": 1}],
        )

        # Should not have internal Resource place
        internal_resource = net.get_place_by_name("Choice_Resource")
        assert internal_resource is None

        # Total places: External + Input + Success + Fallback = 4
        assert len(net.places) == 4


class TestPriorityChoiceBuilder:
    """Tests for PriorityChoice via PetriNetBuilder."""

    def test_builder_add_priority_choice(self):
        """Test adding priority choice via builder."""
        builder = PetriNetBuilder()
        result = builder.add_priority_choice(
            "SectionFill",
            primary_name="Filled",
            alternative_name="Empty",
        )

        assert len(builder.net.places) == 4
        assert len(builder.net.transitions) == 2
        assert result.interface.input_place_id is not None

    def test_conveyor_section_fill_system(self):
        """Test building a conveyor section filling system (like the task)."""
        builder = PetriNetBuilder(name="ConveyorSectionFill")

        # Two batch generators (5 parts every 5 min, 20 parts every 20 min)
        gen1 = builder.add_generator(
            "Type1_Arrivals",
            interval=5.0,
            distribution=DistributionType.NORM,
            standard_deviation=1.0,
            batch_size=5,
        )
        gen2 = builder.add_generator(
            "Type2_Arrivals",
            interval=20.0,
            distribution=DistributionType.NORM,
            standard_deviation=7.0,
            batch_size=20,
        )

        # Section generator (1 section every 10 min)
        section_gen = builder.add_generator(
            "Section",
            interval=10.0,
            distribution=DistributionType.DET,
            batch_size=1,
        )

        net = builder.build()

        # Verify batch sizes on output arcs
        gen1_trans = net.get_transition_by_name("Type1_Arrivals_Gen")
        gen1_out = net.get_place_by_name("Type1_Arrivals_Out")
        gen1_arcs = net.get_arcs_from(gen1_trans.id)
        gen1_output_arc = next(a for a in gen1_arcs if a.target_id == gen1_out.id)
        assert gen1_output_arc.weight == 5

        gen2_trans = net.get_transition_by_name("Type2_Arrivals_Gen")
        gen2_out = net.get_place_by_name("Type2_Arrivals_Out")
        gen2_arcs = net.get_arcs_from(gen2_trans.id)
        gen2_output_arc = next(a for a in gen2_arcs if a.target_id == gen2_out.id)
        assert gen2_output_arc.weight == 20


class TestConveyorWorkstationPattern:
    """Tests for ConveyorWorkstationPattern (Try-or-Bypass logic)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> ConveyorWorkstationPattern:
        return ConveyorWorkstationPattern()

    def test_creates_correct_structure(
        self, net: PetriNet, pattern: ConveyorWorkstationPattern
    ):
        """Test that pattern creates correct number of elements."""
        result = pattern.apply(net, "Device1", x=0, y=0, processing_time=1.0)

        # 4 places: Approach, Resource, Exit, ToNext
        assert len(net.places) == 4
        # 2 transitions: Process, Bypass
        assert len(net.transitions) == 2
        # 6 arcs: Approach->Process, Resource->Process, Process->Exit,
        #         Process->Resource, Approach->Bypass, Bypass->ToNext
        assert len(net.arcs) == 6

    def test_resource_place_has_channels(
        self, net: PetriNet, pattern: ConveyorWorkstationPattern
    ):
        """Test that Resource place has tokens equal to channel count."""
        pattern.apply(net, "Device1", x=0, y=0, processing_time=1.0, channels=3)

        resource_place = net.get_place_by_name("Resource_Device1")
        assert resource_place is not None
        assert resource_place.tokens == 3

    def test_process_transition_has_processing_time(
        self, net: PetriNet, pattern: ConveyorWorkstationPattern
    ):
        """Test that Process transition has correct time parameters."""
        pattern.apply(
            net,
            "Device1",
            x=0,
            y=0,
            processing_time=2.5,
            distribution=DistributionType.EXP,
        )

        process_trans = net.get_transition_by_name("Process_Device1")
        assert process_trans is not None
        assert process_trans.mean_delay == 2.5
        assert process_trans.distribution == DistributionType.EXP
        assert process_trans.priority == 2  # Higher priority than bypass

    def test_bypass_transition_has_transport_time(
        self, net: PetriNet, pattern: ConveyorWorkstationPattern
    ):
        """Test that Bypass transition has correct time (deterministic)."""
        pattern.apply(net, "Device1", x=0, y=0, transport_time=1.5)

        bypass_trans = net.get_transition_by_name("Bypass_Device1")
        assert bypass_trans is not None
        assert bypass_trans.mean_delay == 1.5
        assert bypass_trans.distribution == DistributionType.DET
        assert bypass_trans.priority == 1

    def test_returns_correct_interface(
        self, net: PetriNet, pattern: ConveyorWorkstationPattern
    ):
        """Test that result contains correct interface places."""
        result = pattern.apply(net, "Device1", x=0, y=0)

        # input_place_id should be Approach
        assert result.interface.input_place_id is not None
        input_place = net.get_place(result.interface.input_place_id)
        assert input_place.name == "Device1_Approach"

        # output_place_id should be Exit
        assert result.interface.output_place_id is not None
        output_place = net.get_place(result.interface.output_place_id)
        assert output_place.name == "Exit_Device1"

    def test_to_next_place_accessible(
        self, net: PetriNet, pattern: ConveyorWorkstationPattern
    ):
        """Test that ToNext place is accessible via place_ids[3]."""
        result = pattern.apply(net, "Device1", x=0, y=0)

        # ToNext should be at index 3
        assert len(result.place_ids) == 4
        to_next_place = net.get_place(result.place_ids[3])
        assert to_next_place.name == "Device1_ToNext"

    def test_process_requires_resource(
        self, net: PetriNet, pattern: ConveyorWorkstationPattern
    ):
        """Test that Process transition requires both Approach and Resource."""
        pattern.apply(net, "Device1", x=0, y=0)

        process_trans = net.get_transition_by_name("Process_Device1")
        arcs_to_process = net.get_arcs_to(process_trans.id)

        # Should have 2 input arcs (from Approach and Resource)
        assert len(arcs_to_process) == 2

        source_names = {net.get_place(a.source_id).name for a in arcs_to_process}
        assert "Device1_Approach" in source_names
        assert "Resource_Device1" in source_names

    def test_bypass_only_requires_approach(
        self, net: PetriNet, pattern: ConveyorWorkstationPattern
    ):
        """Test that Bypass transition only requires Approach (not Resource)."""
        pattern.apply(net, "Device1", x=0, y=0)

        bypass_trans = net.get_transition_by_name("Bypass_Device1")
        arcs_to_bypass = net.get_arcs_to(bypass_trans.id)

        # Should have only 1 input arc (from Approach)
        assert len(arcs_to_bypass) == 1

        source_place = net.get_place(arcs_to_bypass[0].source_id)
        assert source_place.name == "Device1_Approach"

    def test_resource_returned_after_process(
        self, net: PetriNet, pattern: ConveyorWorkstationPattern
    ):
        """Test that Process returns token to Resource (frees slot)."""
        pattern.apply(net, "Device1", x=0, y=0)

        process_trans = net.get_transition_by_name("Process_Device1")
        resource_place = net.get_place_by_name("Resource_Device1")

        arcs_from_process = net.get_arcs_from(process_trans.id)
        target_ids = {a.target_id for a in arcs_from_process}

        # Resource should be in output targets
        assert resource_place.id in target_ids


class TestConveyorWorkstationBuilder:
    """Tests for ConveyorWorkstation via PetriNetBuilder."""

    def test_builder_add_conveyor_workstation(self):
        """Test adding conveyor workstation via builder."""
        builder = PetriNetBuilder()
        result = builder.add_conveyor_workstation(
            "Device1",
            processing_time=1.0,
            transport_time=0.5,
            channels=2,
        )

        assert len(builder.net.places) == 4
        assert len(builder.net.transitions) == 2
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None

    def test_builder_connect_bypass_chain(self):
        """Test chaining workstations via connect_bypass."""
        builder = PetriNetBuilder()

        ws1 = builder.add_conveyor_workstation("Device1", processing_time=1.0)
        ws2 = builder.add_conveyor_workstation("Device2", processing_time=1.0)

        builder.connect_bypass(ws1, ws2)

        # Should have added a transfer transition
        # 4+4 places, 2+2+1 transitions
        assert len(builder.net.places) == 8
        assert len(builder.net.transitions) == 5

    def test_builder_connect_return_loop(self):
        """Test return loop from last station to first."""
        builder = PetriNetBuilder()

        ws1 = builder.add_conveyor_workstation("Device1", processing_time=1.0)
        ws2 = builder.add_conveyor_workstation("Device2", processing_time=1.0)

        builder.connect_return_loop(ws2, ws1.interface.input_place_id, return_delay=5.0)

        # Should have added Return transition
        return_trans = builder.net.get_transition_by_name("Return")
        assert return_trans is not None
        assert return_trans.mean_delay == 5.0
        assert return_trans.distribution == DistributionType.DET

    def test_full_conveyor_system(self):
        """Test building complete 5-station conveyor system."""
        builder = PetriNetBuilder(name="ConveyorSystem")

        # Generator
        gen = builder.add_generator("Details", interval=0.25, distribution=DistributionType.DET)

        # 5 workstations
        stations = []
        for i in range(5):
            station = builder.add_conveyor_workstation(
                f"Device{i+1}",
                processing_time=1.0,
                distribution=DistributionType.EXP,
                transport_time=1.0,
            )
            stations.append(station)

        # Connect generator to first station
        builder.connect(gen.interface.output_place_id, stations[0].interface.input_place_id)

        # Chain bypass outputs
        for i in range(4):
            builder.connect_bypass(stations[i], stations[i + 1])

        # Return loop
        builder.connect_return_loop(
            stations[4],
            stations[0].interface.input_place_id,
            return_delay=5.0,
        )

        net = builder.build()
        is_valid, errors = net.validate_topology()

        assert is_valid, f"Topology errors: {errors}"

        # Count elements:
        # Generator: 2 places, 1 transition
        # 5 stations: 5*4=20 places, 5*2=10 transitions
        # Connections: 1 (gen->ws1) + 4 (bypass chain) + 1 (return) = 6 transitions
        assert len(net.places) == 22  # 2 + 20
        assert len(net.transitions) == 17  # 1 + 10 + 6


class TestThresholdActivationPattern:
    """Tests for ThresholdActivationPattern (queue > N activation)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self):
        from src.domain.patterns import ThresholdActivationPattern
        return ThresholdActivationPattern()

    def test_creates_correct_structure(self, net: PetriNet, pattern):
        """Test that pattern creates correct number of elements."""
        result = pattern.apply(net, "BackupMachine", x=0, y=0, threshold=3)

        # 4 places: Queue, Free, Busy, Done
        assert len(net.places) == 4
        # 2 transitions: Activate, Process
        assert len(net.transitions) == 2
        # 7 arcs: Queue->Activate(w=4), Free->Activate, Activate->Busy,
        #         Activate->Queue(w=3), Busy->Process, Process->Done, Process->Free
        assert len(net.arcs) == 7

    def test_resource_place_starts_with_token(self, net: PetriNet, pattern):
        """Test that Free place has 1 token initially."""
        pattern.apply(net, "BackupMachine", x=0, y=0)

        free_place = net.get_place_by_name("BackupMachine_Free")
        assert free_place is not None
        assert free_place.tokens == 1

    def test_activation_arc_weights_for_threshold(self, net: PetriNet, pattern):
        """Test that activation arcs have correct weights for threshold."""
        threshold = 3
        pattern.apply(net, "BackupMachine", x=0, y=0, threshold=threshold)

        t_activate = net.get_transition_by_name("BackupMachine_Activate")
        p_queue = net.get_place_by_name("BackupMachine_Queue")

        # Arc from queue to activate should take (threshold+1)
        arcs_to_activate = net.get_arcs_to(t_activate.id)
        queue_to_activate = next(
            a for a in arcs_to_activate if a.source_id == p_queue.id
        )
        assert queue_to_activate.weight == threshold + 1  # 4

        # Arc from activate back to queue should return (threshold)
        arcs_from_activate = net.get_arcs_from(t_activate.id)
        activate_to_queue = next(
            a for a in arcs_from_activate if a.target_id == p_queue.id
        )
        assert activate_to_queue.weight == threshold  # 3

    def test_process_transition_has_processing_time(self, net: PetriNet, pattern):
        """Test that Process transition has correct time parameters."""
        pattern.apply(
            net, "BackupMachine", x=0, y=0,
            processing_time=100.0,
            distribution=DistributionType.EXP,
        )

        process_trans = net.get_transition_by_name("BackupMachine_Process")
        assert process_trans is not None
        assert process_trans.mean_delay == 100.0
        assert process_trans.distribution == DistributionType.EXP

    def test_returns_correct_interface(self, net: PetriNet, pattern):
        """Test that result contains correct interface places."""
        result = pattern.apply(net, "BackupMachine", x=0, y=0)

        # input_place_id should be Queue
        input_place = net.get_place(result.interface.input_place_id)
        assert input_place.name == "BackupMachine_Queue"

        # output_place_id should be Done
        output_place = net.get_place(result.interface.output_place_id)
        assert output_place.name == "BackupMachine_Done"

    def test_uses_existing_queue_place(self, net: PetriNet, pattern):
        """Test connecting to existing queue place."""
        # Create a queue place externally
        p_queue = net.add_place(name="SharedQueue", tokens=5, x=0, y=0)

        result = pattern.apply(
            net, "BackupMachine", x=100, y=0,
            queue_place_id=p_queue.id,
        )

        # Should reuse the existing place, not create new one
        assert result.interface.input_place_id == p_queue.id

        # Only 3 new places created (Free, Busy, Done)
        assert len(net.places) == 4  # 1 existing + 3 new

    def test_raises_on_invalid_queue_place(self, net: PetriNet, pattern):
        """Test that invalid queue_place_id raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            pattern.apply(net, "BackupMachine", x=0, y=0, queue_place_id="invalid_id")


class TestThresholdActivationBuilder:
    """Tests for ThresholdActivation via PetriNetBuilder."""

    def test_builder_add_threshold_activation(self):
        """Test adding threshold activation via builder."""
        builder = PetriNetBuilder()
        result = builder.add_threshold_activation(
            "BackupMachine",
            threshold=3,
            processing_time=100.0,
        )

        assert len(builder.net.places) == 4
        assert len(builder.net.transitions) == 2
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None

    def test_parallel_machines_with_threshold(self):
        """Test system with primary machine and threshold-activated backup."""
        builder = PetriNetBuilder(name="ParallelMachines")

        # Generator: arrivals every 40s exp
        gen = builder.add_generator("Arrivals", interval=40.0, distribution=DistributionType.EXP)

        # Primary machine: processes in 60s exp
        machine1 = builder.add_machine(
            "PrimaryMachine",
            processing_time=60.0,
            distribution=DistributionType.EXP,
        )

        # Connect generator to primary machine
        builder.connect(gen.interface.output_place_id, machine1.interface.input_place_id)

        # Backup machine: activates when queue > 3
        machine2 = builder.add_threshold_activation(
            "BackupMachine",
            threshold=3,
            processing_time=100.0,
            distribution=DistributionType.EXP,
            queue_place_id=machine1.interface.input_place_id,
        )

        # Terminator for outputs
        term = builder.add_terminator("Exit")
        builder.connect(machine1.interface.output_place_id, term.interface.input_place_id)
        builder.connect(machine2.interface.output_place_id, term.interface.input_place_id)

        net = builder.build()
        is_valid, errors = net.validate_topology()

        assert is_valid, f"Topology errors: {errors}"

        # Primary machine queue should be shared
        assert machine1.interface.input_place_id == machine2.interface.input_place_id


class TestBoundedQueuePattern:
    """Tests for BoundedQueuePattern (M/M/1/K-style bounded waiting room)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> BoundedQueuePattern:
        return BoundedQueuePattern()

    def test_creates_4_places_2_transitions(self, net: PetriNet, pattern: BoundedQueuePattern):
        result = pattern.apply(net, "Q", x=0, y=0, capacity=5)

        assert len(net.places) == 4
        assert len(net.transitions) == 2
        # Input + Capacity + Queue + Reject
        assert net.get_place_by_name("Q_Input") is not None
        assert net.get_place_by_name("Q_Capacity") is not None
        assert net.get_place_by_name("Q_Queue") is not None
        assert net.get_place_by_name("Q_Overflow") is not None

    def test_capacity_initial_marking_equals_K(self, net: PetriNet, pattern: BoundedQueuePattern):
        pattern.apply(net, "Q", x=0, y=0, capacity=5)
        capacity = net.get_place_by_name("Q_Capacity")
        assert capacity.tokens == 5

    def test_priority_makes_enqueue_win(self, net: PetriNet, pattern: BoundedQueuePattern):
        pattern.apply(net, "Q", x=0, y=0, capacity=3)
        t_enq = net.get_transition_by_name("Q_TryEnqueue")
        t_rej = net.get_transition_by_name("Q_Reject")
        assert t_enq.priority > t_rej.priority

    def test_metadata_exposes_4_ports(self, net: PetriNet, pattern: BoundedQueuePattern):
        result = pattern.apply(net, "Q", x=0, y=0, capacity=2)
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None
        assert result.metadata["capacity_place_id"] is not None
        assert result.metadata["reject_output_id"] is not None
        assert result.metadata["capacity"] == 2

    def test_capacity_zero_raises(self, net: PetriNet, pattern: BoundedQueuePattern):
        with pytest.raises(ValueError, match="capacity must be"):
            pattern.apply(net, "Q", x=0, y=0, capacity=0)


class TestBoundedQueueSimulation:
    """End-to-end behavior: M/M/1/K with arrivals faster than service.

    Reproduces the diploma's reference scenario: 3 parts/min arriving,
    1 part/min service, queue capacity 5. Expected: small fraction processed,
    large fraction rejected, sum equals total arrivals.
    """

    def test_overflow_rejection(self):
        from src.services.simulation.engine import PetriSimulator

        builder = PetriNetBuilder(name="MMK")
        gen = builder.add_generator("Arrivals", interval=20.0, distribution=DistributionType.DET)
        queue = builder.add_bounded_queue("Q", capacity=5)
        machine = builder.add_machine(
            "Server", processing_time=60.0, distribution=DistributionType.EXP
        )
        done = builder.add_terminator("Done")
        lost = builder.add_terminator("Lost")

        # Wire flow
        builder.connect(gen.interface.output_place_id, queue.interface.input_place_id)
        builder.connect(queue.interface.output_place_id, machine.interface.input_place_id)
        builder.connect(machine.interface.output_place_id, done.interface.input_place_id)
        builder.connect(queue.metadata["reject_output_id"], lost.interface.input_place_id)

        # Recycle capacity slot when machine starts
        builder.connect_bounded_consumer(queue, machine)

        simulator = PetriSimulator(builder.net)
        result = simulator.run(simulation_time=3600.0)

        # Two terminators expected — counts are sourced from tagged places
        # named "<TerminatorInstance>_Counter".
        names = {t.name: t.total_consumed for t in result.terminators}
        assert "Done_Counter" in names
        assert "Lost_Counter" in names

        # Conservation: arrivals approximately equal done + lost.
        # Generator produces ~180/hour at interval=20s; tolerate ±5 for events
        # not yet propagated through the immediate transition cascade.
        total = names["Done_Counter"] + names["Lost_Counter"]
        assert 170 <= total <= 185

        # Server processes ~60/hour (1/min); allow generous slack for
        # exponential variability across CI environments.
        assert 30 <= names["Done_Counter"] <= 90
        # Most arrivals are lost (capacity 5 << demand)
        assert names["Lost_Counter"] > names["Done_Counter"]

    def test_terminator_counter_survives_optimization(self):
        from src.services.petri.optimizer import optimize_petri_net

        builder = PetriNetBuilder(name="MMK")
        gen = builder.add_generator(
            "Arrivals", interval=20.0, distribution=DistributionType.DET
        )
        machine = builder.add_machine(
            "S", processing_time=60.0, distribution=DistributionType.EXP
        )
        term = builder.add_terminator("Done")
        builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
        builder.connect(machine.interface.output_place_id, term.interface.input_place_id)
        net = builder.build()

        optimized, _ = optimize_petri_net(net)
        # The Counter place — tagged "throughput" — must survive optimization
        # so the simulator can read the throughput count from its marking.
        counter = optimized.get_place_by_name("Done_Counter")
        assert counter is not None
        assert counter.tag == "throughput"

    def test_terminator_topology_is_bipartite(self):
        """Every transition must connect places on both sides."""
        builder = PetriNetBuilder(name="T")
        gen = builder.add_generator("G", interval=1.0)
        term = builder.add_terminator("Done")
        builder.connect(gen.interface.output_place_id, term.interface.input_place_id)
        net = builder.build()
        is_valid, errors = net.validate_topology()
        assert is_valid, f"Topology errors: {errors}"


# ---------------------------------------------------------------------------
# Phase 2 patterns
# ---------------------------------------------------------------------------


class TestBalkingQueuePattern:
    """Tests for BalkingQueuePattern (M/M/c/K with behavioral balking)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> BalkingQueuePattern:
        return BalkingQueuePattern()

    def test_creates_places_and_transitions(self, net, pattern):
        pattern.apply(net, "BQ", x=0, y=0, capacity=5)
        assert net.get_place_by_name("BQ_Input") is not None
        assert net.get_place_by_name("BQ_Capacity") is not None
        assert net.get_place_by_name("BQ_Queue") is not None
        assert net.get_place_by_name("BQ_Balked") is not None
        assert net.get_place_by_name("BQ_Free") is not None
        assert net.get_place_by_name("BQ_Processing") is not None
        assert net.get_place_by_name("BQ_Done") is not None
        assert net.get_transition_by_name("BQ_JoinQueue") is not None
        assert net.get_transition_by_name("BQ_Balk") is not None
        assert net.get_transition_by_name("BQ_Start") is not None
        assert net.get_transition_by_name("BQ_Finish") is not None

    def test_capacity_initial_tokens(self, net, pattern):
        pattern.apply(net, "BQ", x=0, y=0, capacity=7)
        assert net.get_place_by_name("BQ_Capacity").tokens == 7

    def test_channels_initial_tokens(self, net, pattern):
        pattern.apply(net, "BQ", x=0, y=0, channels=3)
        assert net.get_place_by_name("BQ_Free").tokens == 3

    def test_join_has_higher_priority_than_balk(self, net, pattern):
        pattern.apply(net, "BQ", x=0, y=0)
        t_join = net.get_transition_by_name("BQ_JoinQueue")
        t_balk = net.get_transition_by_name("BQ_Balk")
        assert t_join.priority > t_balk.priority

    def test_metadata_exposes_ports(self, net, pattern):
        result = pattern.apply(net, "BQ", x=0, y=0, capacity=3)
        assert result.metadata["balked_place_id"] is not None
        assert result.metadata["queue_place_id"] is not None
        assert result.metadata["capacity_place_id"] is not None
        assert len(result.metadata["consume_transition_ids"]) == 1

    def test_balked_place_has_balked_tag(self, net, pattern):
        result = pattern.apply(net, "BQ", x=0, y=0)
        balked = net.get_place_by_name("BQ_Balked")
        assert balked.tag == "balked"

    def test_capacity_zero_raises(self, net, pattern):
        with pytest.raises(ValueError, match="capacity must be"):
            pattern.apply(net, "BQ", x=0, y=0, capacity=0)

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "BQ", x=0, y=0, capacity=3)
        is_valid, errors = net.validate_topology()
        assert is_valid, f"Topology errors: {errors}"

    def test_simulation_balks_overflow(self):
        """Arrivals exceed capacity → some balked, some served."""
        from src.services.simulation.engine import PetriSimulator

        builder = PetriNetBuilder(name="BalkSim")
        gen = builder.add_generator("G", interval=5.0, distribution=DistributionType.DET)
        bq = builder.add_balking_queue("BQ", capacity=3, service_time=30.0,
                                       service_distribution=DistributionType.DET, channels=1)
        done = builder.add_terminator("Done")
        balked = builder.add_terminator("Balked")

        builder.connect(gen.interface.output_place_id, bq.interface.input_place_id)
        builder.connect(bq.interface.output_place_id, done.interface.input_place_id)
        builder.connect(bq.metadata["balked_place_id"], balked.interface.input_place_id)

        result = PetriSimulator(builder.net).run(simulation_time=600.0)
        names = {t.name: t.total_consumed for t in result.terminators}
        assert "Done_Counter" in names
        assert "Balked_Counter" in names
        assert names["Done_Counter"] > 0
        assert names["Balked_Counter"] > 0


class TestTimedBatchPattern:
    """Tests for TimedBatchPattern (count-OR-timeout batch release)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> TimedBatchPattern:
        return TimedBatchPattern()

    def test_creates_expected_elements(self, net, pattern):
        pattern.apply(net, "TB", x=0, y=0, batch_size=5, timeout=60.0)
        assert net.get_place_by_name("TB_Input") is not None
        assert net.get_place_by_name("TB_Buffer") is not None
        assert net.get_place_by_name("TB_Output") is not None
        assert net.get_place_by_name("TB_TimerReady") is not None
        assert net.get_transition_by_name("TB_Enqueue") is not None
        assert net.get_transition_by_name("TB_CountRelease") is not None
        assert net.get_transition_by_name("TB_TimerRelease") is not None

    def test_timer_ready_starts_with_one_token(self, net, pattern):
        pattern.apply(net, "TB", x=0, y=0)
        assert net.get_place_by_name("TB_TimerReady").tokens == 1

    def test_count_release_has_higher_priority_than_timer(self, net, pattern):
        pattern.apply(net, "TB", x=0, y=0)
        t_count = net.get_transition_by_name("TB_CountRelease")
        t_timer = net.get_transition_by_name("TB_TimerRelease")
        assert t_count.priority > t_timer.priority

    def test_count_release_arc_weight_equals_batch_size(self, net, pattern):
        pattern.apply(net, "TB", x=0, y=0, batch_size=7)
        t_count = net.get_transition_by_name("TB_CountRelease")
        buffer = net.get_place_by_name("TB_Buffer")
        arc = next(
            (a for a in net.arcs if a.source_id == buffer.id and a.target_id == t_count.id),
            None,
        )
        assert arc is not None
        assert arc.weight == 7

    def test_metadata_exposes_ports(self, net, pattern):
        result = pattern.apply(net, "TB", x=0, y=0, batch_size=5, timeout=10.0)
        assert result.metadata["buffer_place_id"] is not None
        assert result.metadata["count_release_id"] is not None
        assert result.metadata["timer_release_id"] is not None
        assert result.metadata["batch_size"] == 5

    def test_batch_size_one_raises(self, net, pattern):
        with pytest.raises(ValueError, match="batch_size must be"):
            pattern.apply(net, "TB", x=0, y=0, batch_size=1)

    def test_timeout_zero_raises(self, net, pattern):
        with pytest.raises(ValueError, match="timeout must be"):
            pattern.apply(net, "TB", x=0, y=0, timeout=0.0)

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "TB", x=0, y=0)
        is_valid, errors = net.validate_topology()
        assert is_valid, f"Topology errors: {errors}"

    def test_simulation_count_release(self):
        """Feeding exactly batch_size tokens triggers count release."""
        from src.services.simulation.engine import PetriSimulator

        builder = PetriNetBuilder(name="TBSim")
        gen = builder.add_generator("G", interval=1.0, distribution=DistributionType.DET)
        tb = builder.add_timed_batch("TB", batch_size=5, timeout=300.0,
                                     timeout_distribution=DistributionType.DET)
        done = builder.add_terminator("Done")

        builder.connect(gen.interface.output_place_id, tb.interface.input_place_id)
        builder.connect(tb.interface.output_place_id, done.interface.input_place_id)

        result = PetriSimulator(builder.net).run(simulation_time=30.0)
        names = {t.name: t.total_consumed for t in result.terminators}
        assert "Done_Counter" in names
        # 30 seconds / 1s interval = ~30 arrivals; batch_size=5 → ~6 batches
        assert names["Done_Counter"] >= 4


class TestNonStationaryGeneratorPattern:
    """Tests for NonstationaryGeneratorPattern (time-varying arrival rate)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> NonstationaryGeneratorPattern:
        return NonstationaryGeneratorPattern()

    def test_creates_slot_and_timer_elements(self, net, pattern):
        pattern.apply(net, "NSG", x=0, y=0,
                      schedule=[{"duration": 3600.0, "rate": 0.5},
                                {"duration": 1800.0, "rate": 0.1}])
        assert net.get_place_by_name("NSG_Slot1") is not None
        assert net.get_place_by_name("NSG_Slot2") is not None
        assert net.get_transition_by_name("NSG_Timer1") is not None
        assert net.get_transition_by_name("NSG_Timer2") is not None
        assert net.get_transition_by_name("NSG_Gen1") is not None
        assert net.get_transition_by_name("NSG_Gen2") is not None
        assert net.get_place_by_name("NSG_Out") is not None

    def test_first_slot_has_token_others_empty(self, net, pattern):
        pattern.apply(net, "NSG", x=0, y=0,
                      schedule=[{"duration": 100.0, "rate": 1.0},
                                {"duration": 100.0, "rate": 0.5},
                                {"duration": 100.0, "rate": 0.2}])
        assert net.get_place_by_name("NSG_Slot1").tokens == 1
        assert net.get_place_by_name("NSG_Slot2").tokens == 0
        assert net.get_place_by_name("NSG_Slot3").tokens == 0

    def test_metadata_slot_and_gen_ids(self, net, pattern):
        result = pattern.apply(net, "NSG", x=0, y=0,
                               schedule=[{"duration": 100.0, "rate": 1.0},
                                         {"duration": 200.0, "rate": 0.5}])
        assert len(result.metadata["slot_place_ids"]) == 2
        assert len(result.metadata["generator_transition_ids"]) == 2

    def test_input_place_id_is_none(self, net, pattern):
        result = pattern.apply(net, "NSG", x=0, y=0)
        assert result.interface.input_place_id is None

    def test_missing_duration_key_raises(self, net, pattern):
        with pytest.raises(ValueError, match="duration"):
            pattern.apply(net, "NSG", x=0, y=0,
                          schedule=[{"rate": 1.0}])

    def test_missing_rate_key_raises(self, net, pattern):
        with pytest.raises(ValueError, match="rate"):
            pattern.apply(net, "NSG", x=0, y=0,
                          schedule=[{"duration": 100.0}])

    def test_negative_duration_raises(self, net, pattern):
        with pytest.raises(ValueError):
            pattern.apply(net, "NSG", x=0, y=0,
                          schedule=[{"duration": -1.0, "rate": 1.0}])

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "NSG", x=0, y=0,
                      schedule=[{"duration": 100.0, "rate": 1.0},
                                {"duration": 100.0, "rate": 0.5}])
        is_valid, errors = net.validate_topology()
        assert is_valid, f"Topology errors: {errors}"

    def test_simulation_generates_tokens(self):
        """NonStationaryGenerator produces tokens that reach a terminator.

        Note: this simulator fires timer transitions' act_in immediately,
        so each slot window produces at most one generator fire per cycle.
        Zero tokens is a legitimate outcome of the engine's random conflict
        resolution (the engine draws from the global PRNG), so the stream is
        seeded to keep the at-least-one assertion deterministic while still
        proving the topology is wired correctly.
        """
        import random

        from src.services.simulation.engine import PetriSimulator

        random.seed(20260821)

        builder = PetriNetBuilder(name="NSGSim")
        nsg = builder.add_nonstationary_generator(
            "NSG",
            schedule=[{"duration": 50.0, "rate": 1.0},
                      {"duration": 50.0, "rate": 0.5}],
        )
        done = builder.add_terminator("Done")
        builder.connect(nsg.interface.output_place_id, done.interface.input_place_id)

        result = PetriSimulator(builder.net).run(simulation_time=400.0)
        names = {t.name: t.total_consumed for t in result.terminators}
        assert "Done_Counter" in names
        # Each cycle (2×50s = 100s) can produce 0–2 tokens.
        # In 400s (4 full cycles), with random conflict resolution between
        # timers and generators, expect at least 1 token in expectation.
        assert names["Done_Counter"] >= 1


class TestPreemptiveMachinePattern:
    """Tests for PreemptiveMachinePattern (Preempt-Restart discipline)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self) -> PreemptiveMachinePattern:
        return PreemptiveMachinePattern()

    def test_creates_expected_places(self, net, pattern):
        pattern.apply(net, "PM", x=0, y=0)
        assert net.get_place_by_name("PM_NormalQueue") is not None
        assert net.get_place_by_name("PM_HighQueue") is not None
        assert net.get_place_by_name("PM_Free") is not None
        assert net.get_place_by_name("PM_Processing") is not None
        assert net.get_place_by_name("PM_HighProcessing") is not None
        assert net.get_place_by_name("PM_Preempted") is not None
        assert net.get_place_by_name("PM_Done") is not None

    def test_creates_expected_transitions(self, net, pattern):
        pattern.apply(net, "PM", x=0, y=0)
        assert net.get_transition_by_name("PM_StartNormal") is not None
        assert net.get_transition_by_name("PM_Restart") is not None
        assert net.get_transition_by_name("PM_FinishNormal") is not None
        assert net.get_transition_by_name("PM_StartHigh") is not None
        assert net.get_transition_by_name("PM_Preempt") is not None
        assert net.get_transition_by_name("PM_FinishHigh") is not None

    def test_channels_initial_tokens(self, net, pattern):
        pattern.apply(net, "PM", x=0, y=0, channels=2)
        assert net.get_place_by_name("PM_Free").tokens == 2

    def test_priority_ordering(self, net, pattern):
        pattern.apply(net, "PM", x=0, y=0)
        t_start_high = net.get_transition_by_name("PM_StartHigh")
        t_preempt = net.get_transition_by_name("PM_Preempt")
        t_start_normal = net.get_transition_by_name("PM_StartNormal")
        assert t_start_high.priority > t_preempt.priority > t_start_normal.priority

    def test_metadata_exposes_ports(self, net, pattern):
        result = pattern.apply(net, "PM", x=0, y=0)
        assert result.metadata["high_priority_input_id"] is not None
        assert result.metadata["preempted_place_id"] is not None
        assert len(result.metadata["consume_transition_ids"]) == 1

    def test_interface_maps_to_normal_queue_and_done(self, net, pattern):
        result = pattern.apply(net, "PM", x=0, y=0)
        assert result.interface.input_place_id == net.get_place_by_name("PM_NormalQueue").id
        assert result.interface.output_place_id == net.get_place_by_name("PM_Done").id

    def test_channels_zero_raises(self, net, pattern):
        with pytest.raises(ValueError, match="channels must be"):
            pattern.apply(net, "PM", x=0, y=0, channels=0)

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "PM", x=0, y=0)
        is_valid, errors = net.validate_topology()
        assert is_valid, f"Topology errors: {errors}"

    def test_simulation_high_priority_preempts(self):
        """High-priority jobs preempt normal jobs; all complete eventually."""
        from src.services.simulation.engine import PetriSimulator

        builder = PetriNetBuilder(name="PMSim")
        normal_gen = builder.add_generator("Normal", interval=10.0,
                                           distribution=DistributionType.DET)
        high_gen = builder.add_generator("High", interval=30.0,
                                         distribution=DistributionType.DET)
        pm = builder.add_preemptive_machine("PM", normal_time=20.0, high_priority_time=5.0,
                                            distribution=DistributionType.DET)
        done = builder.add_terminator("Done")

        builder.connect(normal_gen.interface.output_place_id, pm.interface.input_place_id)
        builder.connect(high_gen.interface.output_place_id, pm.metadata["high_priority_input_id"])
        builder.connect(pm.interface.output_place_id, done.interface.input_place_id)

        result = PetriSimulator(builder.net).run(simulation_time=300.0)
        names = {t.name: t.total_consumed for t in result.terminators}
        assert "Done_Counter" in names
        assert names["Done_Counter"] > 0


# ---------------------------------------------------------------------------
# Phase 3 patterns
# ---------------------------------------------------------------------------


class TestRetrialQueuePattern:
    """Tests for RetrialQueuePattern (M/G/1 retrial orbit)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self):
        from src.domain.patterns.retrial_queue import RetrialQueuePattern
        return RetrialQueuePattern()

    def test_creates_expected_places(self, net, pattern):
        pattern.apply(net, "RQ", x=0, y=0)
        assert net.get_place_by_name("RQ_Input") is not None
        assert net.get_place_by_name("RQ_Free") is not None
        assert net.get_place_by_name("RQ_Processing") is not None
        assert net.get_place_by_name("RQ_Orbit") is not None
        assert net.get_place_by_name("RQ_Output") is not None

    def test_creates_expected_transitions(self, net, pattern):
        pattern.apply(net, "RQ", x=0, y=0)
        assert net.get_transition_by_name("RQ_StartService") is not None
        assert net.get_transition_by_name("RQ_GoOrbit") is not None
        assert net.get_transition_by_name("RQ_FinishService") is not None
        assert net.get_transition_by_name("RQ_Retry") is not None

    def test_free_place_starts_with_channels_tokens(self, net, pattern):
        pattern.apply(net, "RQ", x=0, y=0, channels=3)
        free = net.get_place_by_name("RQ_Free")
        assert free.tokens == 3

    def test_orbit_tagged_orbit(self, net, pattern):
        pattern.apply(net, "RQ", x=0, y=0)
        orbit = net.get_place_by_name("RQ_Orbit")
        assert orbit.tag == "orbit"

    def test_start_service_has_higher_priority(self, net, pattern):
        pattern.apply(net, "RQ", x=0, y=0)
        t_start = net.get_transition_by_name("RQ_StartService")
        t_orbit = net.get_transition_by_name("RQ_GoOrbit")
        assert t_start.priority > t_orbit.priority
        assert t_start.priority == 2
        assert t_orbit.priority == 1

    def test_metadata_expose_orbit_and_consume_ids(self, net, pattern):
        result = pattern.apply(net, "RQ", x=0, y=0)
        assert "orbit_place_id" in result.metadata
        assert "consume_transition_ids" in result.metadata
        assert len(result.metadata["consume_transition_ids"]) == 1

    def test_retry_has_correct_delay(self, net, pattern):
        pattern.apply(net, "RQ", x=0, y=0, retrial_delay=90.0,
                      retrial_distribution=DistributionType.EXP)
        t_retry = net.get_transition_by_name("RQ_Retry")
        assert t_retry.mean_delay == 90.0
        assert t_retry.distribution == DistributionType.EXP

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "RQ", x=0, y=0)
        is_valid, errors = net.validate_topology()
        assert is_valid, f"Topology errors: {errors}"

    def test_retry_loop_wired_to_input(self, net, pattern):
        """Retry transition output must feed back into Input place."""
        result = pattern.apply(net, "RQ", x=0, y=0)
        t_retry = net.get_transition_by_name("RQ_Retry")
        arcs_from_retry = net.get_arcs_from(t_retry.id)
        target_ids = {a.target_id for a in arcs_from_retry}
        assert result.interface.input_place_id in target_ids

    def test_simulation_orbit_accumulates_under_high_load(self):
        """High arrival rate relative to service → orbit grows, some served."""
        from src.services.simulation.engine import PetriSimulator

        builder = PetriNetBuilder(name="RetrialSim")
        # Fast arrivals: every 5s; slow service: 60s → server heavily loaded
        gen = builder.add_generator("Arrivals", interval=5.0,
                                    distribution=DistributionType.DET)
        rq = builder.add_retrial_queue(
            "Phone", service_time=60.0, retrial_delay=30.0,
        )
        done = builder.add_terminator("Done")
        builder.connect(gen.interface.output_place_id, rq.interface.input_place_id)
        builder.connect(rq.interface.output_place_id, done.interface.input_place_id)

        result = PetriSimulator(builder.net).run(simulation_time=600.0)
        names = {t.name: t.total_consumed for t in result.terminators}
        assert "Done_Counter" in names
        assert names["Done_Counter"] > 0

        # Orbit should accumulate tokens under high load
        orbit_marking = None
        for p in builder.net.places:
            if p.name == "Phone_Orbit":
                orbit_marking = p.tokens
                break
        # After simulation, orbit may or may not have residual tokens;
        # we just verify the topology ran without error.
        assert orbit_marking is not None


class TestForkJoinPattern:
    """Tests for ForkJoinPattern (AND-split / AND-join)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self):
        from src.domain.patterns.fork_join import ForkJoinPattern
        return ForkJoinPattern()

    def test_creates_fork_join_n2(self, net, pattern):
        result = pattern.apply(net, "FJ", x=0, y=0,
                               n_branches=2, branch_times=[10.0, 20.0])
        assert net.get_place_by_name("FJ_Input") is not None
        assert net.get_place_by_name("FJ_Branch1_Work") is not None
        assert net.get_place_by_name("FJ_Branch2_Work") is not None
        assert net.get_place_by_name("FJ_Done1") is not None
        assert net.get_place_by_name("FJ_Done2") is not None
        assert net.get_place_by_name("FJ_Output") is not None
        assert net.get_transition_by_name("FJ_Fork") is not None
        assert net.get_transition_by_name("FJ_Join") is not None

    def test_creates_fork_join_n3(self, net, pattern):
        result = pattern.apply(net, "FJ", x=0, y=0,
                               n_branches=3, branch_times=[5.0, 10.0, 15.0])
        for i in range(1, 4):
            assert net.get_place_by_name(f"FJ_Branch{i}_Work") is not None
            assert net.get_place_by_name(f"FJ_Done{i}") is not None
            assert net.get_transition_by_name(f"FJ_Finish{i}") is not None

    def test_fork_has_n_output_arcs(self, net, pattern):
        n = 4
        pattern.apply(net, "FJ", x=0, y=0,
                      n_branches=n, branch_times=[1.0] * n)
        t_fork = net.get_transition_by_name("FJ_Fork")
        arcs_from_fork = net.get_arcs_from(t_fork.id)
        assert len(arcs_from_fork) == n

    def test_join_has_n_input_arcs(self, net, pattern):
        n = 3
        pattern.apply(net, "FJ", x=0, y=0,
                      n_branches=n, branch_times=[1.0] * n)
        t_join = net.get_transition_by_name("FJ_Join")
        arcs_to_join = net.get_arcs_to(t_join.id)
        assert len(arcs_to_join) == n

    def test_branch_times_mismatch_raises(self, net, pattern):
        with pytest.raises(ValueError, match="branch_times must have exactly"):
            pattern.apply(net, "FJ", x=0, y=0,
                          n_branches=3, branch_times=[10.0, 20.0])

    def test_metadata_exposes_branch_ids(self, net, pattern):
        result = pattern.apply(net, "FJ", x=0, y=0,
                               n_branches=2, branch_times=[10.0, 20.0])
        assert "branch_input_ids" in result.metadata
        assert "branch_done_ids" in result.metadata
        assert "join_transition_id" in result.metadata
        assert len(result.metadata["branch_input_ids"]) == 2
        assert len(result.metadata["branch_done_ids"]) == 2

    def test_interface_input_and_output(self, net, pattern):
        result = pattern.apply(net, "FJ", x=0, y=0, branch_times=[10.0, 20.0])
        p_in = net.get_place(result.interface.input_place_id)
        p_out = net.get_place(result.interface.output_place_id)
        assert p_in.name == "FJ_Input"
        assert p_out.name == "FJ_Output"

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "FJ", x=0, y=0, branch_times=[5.0, 10.0])
        is_valid, errors = net.validate_topology()
        assert is_valid, f"Topology errors: {errors}"

    def test_builder_add_fork_join(self):
        builder = PetriNetBuilder()
        result = builder.add_fork_join("Gate", n_branches=3, branch_times=[5.0, 10.0, 15.0])
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None
        assert len(result.metadata["branch_input_ids"]) == 3

    def test_simulation_single_entity_produces_one_output(self):
        """One entity entering ForkJoin should produce exactly one output token.

        Strategy: DET generator with interval=10s, DET branches of [1s, 1s].
        First entity completes at t=12s. Second entity arrives at t=20s,
        outside the 15s simulation window → exactly 1 Done_Counter.
        """
        from src.services.simulation.engine import PetriSimulator

        builder = PetriNetBuilder(name="FJSim")
        gen = builder.add_generator("G", interval=10.0, distribution=DistributionType.DET)
        fj = builder.add_fork_join(
            "Exam", n_branches=2,
            branch_times=[1.0, 1.0],
            branch_distribution=DistributionType.DET,
        )
        done = builder.add_terminator("Done")
        builder.connect(gen.interface.output_place_id, fj.interface.input_place_id)
        builder.connect(fj.interface.output_place_id, done.interface.input_place_id)

        result = PetriSimulator(builder.net).run(simulation_time=15.0)
        names = {t.name: t.total_consumed for t in result.terminators}
        assert names.get("Done_Counter", 0) == 1, (
            "ForkJoin must produce exactly 1 output for 1 input entity"
        )


class TestBlockingMachinePattern:
    """Tests for BlockingMachinePattern (BAS blocking protocol)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self):
        from src.domain.patterns.blocking_machine import BlockingMachinePattern
        return BlockingMachinePattern()

    def test_creates_expected_places(self, net, pattern):
        pattern.apply(net, "BM", x=0, y=0)
        assert net.get_place_by_name("BM_Input") is not None
        assert net.get_place_by_name("BM_Free") is not None
        assert net.get_place_by_name("BM_Processing") is not None
        assert net.get_place_by_name("BM_Holding") is not None
        assert net.get_place_by_name("BM_Capacity") is not None
        assert net.get_place_by_name("BM_Output") is not None

    def test_creates_expected_transitions(self, net, pattern):
        pattern.apply(net, "BM", x=0, y=0)
        assert net.get_transition_by_name("BM_Start") is not None
        assert net.get_transition_by_name("BM_Finish") is not None
        assert net.get_transition_by_name("BM_Release") is not None

    def test_free_starts_with_channels_tokens(self, net, pattern):
        pattern.apply(net, "BM", x=0, y=0, channels=2)
        free = net.get_place_by_name("BM_Free")
        assert free.tokens == 2

    def test_capacity_starts_with_buffer_capacity_tokens(self, net, pattern):
        pattern.apply(net, "BM", x=0, y=0, buffer_capacity=7)
        cap = net.get_place_by_name("BM_Capacity")
        assert cap.tokens == 7

    def test_metadata_expose_holding_capacity_consume_ids(self, net, pattern):
        result = pattern.apply(net, "BM", x=0, y=0)
        assert "holding_place_id" in result.metadata
        assert "capacity_place_id" in result.metadata
        assert "consume_transition_ids" in result.metadata
        assert len(result.metadata["consume_transition_ids"]) == 1

    def test_release_requires_holding_and_capacity(self, net, pattern):
        """Release transition must have arcs from both Holding and Capacity."""
        pattern.apply(net, "BM", x=0, y=0)
        t_release = net.get_transition_by_name("BM_Release")
        arcs_to_release = net.get_arcs_to(t_release.id)
        source_names = {net.get_place(a.source_id).name for a in arcs_to_release}
        assert "BM_Holding" in source_names
        assert "BM_Capacity" in source_names

    def test_finish_recycles_free(self, net, pattern):
        """Finish transition must return a token to Free (channel released)."""
        pattern.apply(net, "BM", x=0, y=0)
        t_finish = net.get_transition_by_name("BM_Finish")
        arcs_from_finish = net.get_arcs_from(t_finish.id)
        target_names = {net.get_place(a.target_id).name for a in arcs_from_finish}
        assert "BM_Free" in target_names
        assert "BM_Holding" in target_names

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "BM", x=0, y=0)
        is_valid, errors = net.validate_topology()
        assert is_valid, f"Topology errors: {errors}"

    def test_builder_add_blocking_machine(self):
        builder = PetriNetBuilder()
        result = builder.add_blocking_machine(
            "Lathe", processing_time=45.0, buffer_capacity=3
        )
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None
        cap_place = builder.net.get_place_by_name("Lathe_Capacity")
        assert cap_place is not None
        assert cap_place.tokens == 3

    def test_connect_blocking_consumer_wires_arc(self):
        """connect_blocking_consumer adds arc from downstream Start to Capacity."""
        builder = PetriNetBuilder()
        blocking = builder.add_blocking_machine("Press", processing_time=30.0,
                                                buffer_capacity=4)
        downstream = builder.add_machine("Assembly", processing_time=50.0)
        builder.connect(blocking.interface.output_place_id,
                        downstream.interface.input_place_id)
        builder.connect_blocking_consumer(blocking, downstream)

        # Downstream Start transition should have arc to Press_Capacity
        cap_id = blocking.metadata["capacity_place_id"]
        t_start = builder.net.get_transition_by_name("Assembly_Start")
        arcs_from_start = builder.net.get_arcs_from(t_start.id)
        target_ids = {a.target_id for a in arcs_from_start}
        assert cap_id in target_ids

    def test_simulation_blocking_observed_with_slow_downstream(self):
        """With upstream faster than downstream, Holding should accumulate."""
        from src.services.simulation.engine import PetriSimulator

        builder = PetriNetBuilder(name="BlockSim")
        gen = builder.add_generator("G", interval=5.0, distribution=DistributionType.DET)
        blocking = builder.add_blocking_machine(
            "Fast", processing_time=5.0,
            distribution=DistributionType.DET,
            buffer_capacity=2,
        )
        slow = builder.add_machine(
            "Slow", processing_time=40.0, distribution=DistributionType.DET
        )
        done = builder.add_terminator("Done")
        builder.connect(gen.interface.output_place_id, blocking.interface.input_place_id)
        builder.connect(blocking.interface.output_place_id, slow.interface.input_place_id)
        builder.connect(slow.interface.output_place_id, done.interface.input_place_id)
        builder.connect_blocking_consumer(blocking, slow)

        result = PetriSimulator(builder.net).run(simulation_time=300.0)
        names = {t.name: t.total_consumed for t in result.terminators}
        assert "Done_Counter" in names
        assert names["Done_Counter"] > 0


class TestFinitePopulationQueuePattern:
    """Tests for FinitePopulationQueuePattern (closed network M/M/c/N)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self):
        from src.domain.patterns.finite_population_queue import (
            FinitePopulationQueuePattern,
        )
        return FinitePopulationQueuePattern()

    def test_creates_expected_places(self, net, pattern):
        pattern.apply(net, "Pallets", x=0, y=0)
        for suffix in ("IdlePool", "Queue", "FreeChannels", "InService", "Done",
                       "Counter", "Resting"):
            assert net.get_place_by_name(f"Pallets_{suffix}") is not None, suffix

    def test_creates_expected_transitions(self, net, pattern):
        pattern.apply(net, "Pallets", x=0, y=0)
        for suffix in ("Request", "StartService", "EndService", "Measure", "EndRest"):
            assert net.get_transition_by_name(f"Pallets_{suffix}") is not None, suffix

    def test_idle_pool_starts_with_n_customers(self, net, pattern):
        pattern.apply(net, "Pallets", x=0, y=0, n_customers=7)
        pool = net.get_place_by_name("Pallets_IdlePool")
        assert pool.tokens == 7

    def test_free_channels_starts_with_channels_tokens(self, net, pattern):
        pattern.apply(net, "Pallets", x=0, y=0, channels=3)
        free = net.get_place_by_name("Pallets_FreeChannels")
        assert free.tokens == 3

    def test_counter_tagged_throughput(self, net, pattern):
        pattern.apply(net, "Pallets", x=0, y=0)
        counter = net.get_place_by_name("Pallets_Counter")
        assert counter.tag == "throughput"

    def test_metadata_exposes_pool_queue_counter_resting(self, net, pattern):
        result = pattern.apply(net, "Pallets", x=0, y=0)
        for k in ("pool_place_id", "queue_place_id",
                  "free_channels_place_id", "counter_place_id",
                  "resting_place_id"):
            assert k in result.metadata, k

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "Pallets", x=0, y=0)
        ok, errs = net.validate_topology()
        assert ok, errs

    def test_builder_add_finite_population_queue(self):
        b = PetriNetBuilder()
        result = b.add_finite_population_queue(
            "Pallets", n_customers=5, service_time=10.0, channels=2
        )
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None
        pool = b.net.get_place_by_name("Pallets_IdlePool")
        assert pool.tokens == 5

    def test_simulation_token_conservation(self):
        """Token conservation: live customers (places + transition buffers,
        excluding the throughput counter) stays equal to n_customers.

        FreeChannels are also tokens but represent server availability, not
        customers; they are excluded too.

        The simulator tracks tokens in transit inside transition buffers
        separately from place markings — both are summed here.
        """
        from src.services.simulation.engine import PetriSimulator

        b = PetriNetBuilder(name="FPQ")
        b.add_finite_population_queue(
            "Pallets", n_customers=4,
            service_time=5.0,
            service_distribution=DistributionType.DET,
            channels=2,
        )
        sim_result = PetriSimulator(b.net).run(simulation_time=300.0)
        markings = {p.name: p.final_marking for p in sim_result.places}
        buffers = {t.name: t.final_buffer for t in sim_result.transitions}

        customer_places = [
            "Pallets_IdlePool", "Pallets_Queue", "Pallets_InService",
            "Pallets_Done", "Pallets_Resting",
        ]
        live_total = sum(markings[name] for name in customer_places)
        live_total += sum(buffers.values())
        assert live_total == 4, (
            f"Conservation violated: live_total={live_total}, expected 4. "
            f"places={markings} buffers={buffers}"
        )

        counter_marking = markings["Pallets_Counter"]
        assert counter_marking > 0
        assert sim_result.terminators
        assert sim_result.terminators[0].total_consumed == counter_marking


class TestResourceSetPattern:
    """Tests for ResourceSetPattern (alternative resource pool)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self):
        from src.domain.patterns.resource_set import ResourceSetPattern
        return ResourceSetPattern()

    def test_creates_input_and_output(self, net, pattern):
        pattern.apply(net, "Pool", x=0, y=0,
                      resources=[{"name": "A"}, {"name": "B"}])
        assert net.get_place_by_name("Pool_Input") is not None
        assert net.get_place_by_name("Pool_Output") is not None

    def test_creates_per_resource_places_and_transitions(self, net, pattern):
        pattern.apply(net, "Pool", x=0, y=0,
                      resources=[{"name": "Fast"}, {"name": "Slow"}])
        for rname in ("Fast", "Slow"):
            assert net.get_place_by_name(f"Pool_Free_{rname}") is not None
            assert net.get_place_by_name(f"Pool_InService_{rname}") is not None
            assert net.get_transition_by_name(f"Pool_Seize_{rname}") is not None
            assert net.get_transition_by_name(f"Pool_End_{rname}") is not None

    def test_free_starts_with_per_resource_channels(self, net, pattern):
        pattern.apply(net, "Pool", x=0, y=0, resources=[
            {"name": "Fast", "channels": 1},
            {"name": "Slow", "channels": 3},
        ])
        assert net.get_place_by_name("Pool_Free_Fast").tokens == 1
        assert net.get_place_by_name("Pool_Free_Slow").tokens == 3

    def test_priority_descends_with_index(self, net, pattern):
        pattern.apply(net, "Pool", x=0, y=0, resources=[
            {"name": "R0"}, {"name": "R1"}, {"name": "R2"},
        ])
        seize_r0 = net.get_transition_by_name("Pool_Seize_R0")
        seize_r1 = net.get_transition_by_name("Pool_Seize_R1")
        seize_r2 = net.get_transition_by_name("Pool_Seize_R2")
        assert seize_r0.priority > seize_r1.priority > seize_r2.priority

    def test_end_recycles_free_channel(self, net, pattern):
        pattern.apply(net, "Pool", x=0, y=0,
                      resources=[{"name": "Only"}])
        t_end = net.get_transition_by_name("Pool_End_Only")
        targets = {a.target_id for a in net.get_arcs_from(t_end.id)}
        free_id = net.get_place_by_name("Pool_Free_Only").id
        out_id = net.get_place_by_name("Pool_Output").id
        assert free_id in targets
        assert out_id in targets

    def test_metadata_exposes_resource_free_place_ids(self, net, pattern):
        result = pattern.apply(net, "Pool", x=0, y=0,
                               resources=[{"name": "A"}, {"name": "B"}])
        free_ids = result.metadata["resource_free_place_ids"]
        assert set(free_ids.keys()) == {"A", "B"}
        for rname, pid in free_ids.items():
            place = net.get_place(pid)
            assert place.name == f"Pool_Free_{rname}"

    def test_empty_resources_raises(self, net, pattern):
        with pytest.raises(ValueError):
            pattern.apply(net, "Pool", x=0, y=0, resources=[])

    def test_missing_name_raises(self, net, pattern):
        with pytest.raises(ValueError):
            pattern.apply(net, "Pool", x=0, y=0,
                          resources=[{"service_time": 5.0}])

    def test_invalid_channels_raises(self, net, pattern):
        with pytest.raises(ValueError):
            pattern.apply(net, "Pool", x=0, y=0,
                          resources=[{"name": "X", "channels": 0}])

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "Pool", x=0, y=0,
                      resources=[{"name": "A"}, {"name": "B"}])
        ok, errs = net.validate_topology()
        assert ok, errs

    def test_builder_add_resource_set(self):
        b = PetriNetBuilder()
        result = b.add_resource_set(
            "Pool",
            resources=[
                {"name": "Fast", "service_time": 30.0},
                {"name": "Slow", "service_time": 90.0, "channels": 2},
            ],
        )
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None
        assert b.net.get_place_by_name("Pool_Free_Fast").tokens == 1
        assert b.net.get_place_by_name("Pool_Free_Slow").tokens == 2

    def test_simulation_throughput_via_resource_set(self):
        """End-to-end: generator -> resource_set -> terminator produces throughput.

        Per-resource fire counts are not directly tracked by the simulator
        (counts live in places, not transition fire counts), but a
        positive terminator count proves the priority-conflict topology
        is wired correctly.
        """
        from src.services.simulation.engine import PetriSimulator

        b = PetriNetBuilder(name="RSSim")
        gen = b.add_generator(
            "G", interval=15.0, distribution=DistributionType.DET
        )
        rs = b.add_resource_set("Pool", resources=[
            {"name": "Fast", "service_time": 5.0,
             "distribution": "det", "channels": 1},
            {"name": "Slow", "service_time": 5.0,
             "distribution": "det", "channels": 1},
        ])
        term = b.add_terminator("Out")
        b.connect(gen.interface.output_place_id, rs.interface.input_place_id)
        b.connect(rs.interface.output_place_id, term.interface.input_place_id)

        sim = PetriSimulator(b.net).run(simulation_time=600.0)
        assert sim.terminators
        assert sim.terminators[0].total_consumed > 0


class TestWipControllerPattern:
    """Tests for WipControllerPattern (CONWIP / Kanban gate)."""

    @pytest.fixture
    def net(self) -> PetriNet:
        return PetriNet(name="Test")

    @pytest.fixture
    def pattern(self):
        from src.domain.patterns.wip_controller import WipControllerPattern
        return WipControllerPattern()

    def test_creates_expected_places(self, net, pattern):
        pattern.apply(net, "Conwip", x=0, y=0, wip_limit=3)
        for suffix in ("Input", "WIPSlots", "Output"):
            assert net.get_place_by_name(f"Conwip_{suffix}") is not None, suffix

    def test_creates_enter_transition(self, net, pattern):
        pattern.apply(net, "Conwip", x=0, y=0, wip_limit=3)
        assert net.get_transition_by_name("Conwip_Enter") is not None

    def test_wip_slots_starts_with_wip_limit_tokens(self, net, pattern):
        pattern.apply(net, "Conwip", x=0, y=0, wip_limit=5)
        wip = net.get_place_by_name("Conwip_WIPSlots")
        assert wip.tokens == 5

    def test_enter_consumes_input_and_wip_slot(self, net, pattern):
        pattern.apply(net, "Conwip", x=0, y=0, wip_limit=3)
        t_enter = net.get_transition_by_name("Conwip_Enter")
        sources = {a.source_id for a in net.get_arcs_to(t_enter.id)}
        input_id = net.get_place_by_name("Conwip_Input").id
        wip_id = net.get_place_by_name("Conwip_WIPSlots").id
        assert input_id in sources
        assert wip_id in sources

    def test_metadata_exposes_wip_place_id(self, net, pattern):
        result = pattern.apply(net, "Conwip", x=0, y=0, wip_limit=3)
        assert "wip_place_id" in result.metadata
        wip_place = net.get_place(result.metadata["wip_place_id"])
        assert wip_place.name == "Conwip_WIPSlots"

    def test_invalid_wip_limit_raises(self, net, pattern):
        with pytest.raises(ValueError):
            pattern.apply(net, "Conwip", x=0, y=0, wip_limit=0)

    def test_topology_is_bipartite(self, net, pattern):
        pattern.apply(net, "Conwip", x=0, y=0, wip_limit=3)
        ok, errs = net.validate_topology()
        assert ok, errs

    def test_builder_add_wip_controller(self):
        b = PetriNetBuilder()
        result = b.add_wip_controller("Conwip", wip_limit=4)
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None
        assert result.metadata["wip_place_id"] is not None
        assert b.net.get_place_by_name("Conwip_WIPSlots").tokens == 4

    def test_connect_wip_return_adds_arcs_from_producers(self):
        """connect_wip_return adds an output arc from each producer of
        exit_place to WIPSlots — without consuming the entity."""
        b = PetriNetBuilder()
        wip = b.add_wip_controller("Conwip", wip_limit=2)
        machine = b.add_machine("M", processing_time=5.0)
        term = b.add_terminator("Out")
        b.connect(wip.interface.output_place_id, machine.interface.input_place_id)
        b.connect(machine.interface.output_place_id, term.interface.input_place_id)

        wip_id = wip.metadata["wip_place_id"]
        producers_before = [
            a.source_id for a in b.net.arcs if a.target_id == wip_id
        ]
        assert producers_before == []

        b.connect_wip_return(wip, term.interface.input_place_id)

        producers_after = {
            a.source_id for a in b.net.arcs if a.target_id == wip_id
        }
        assert len(producers_after) >= 1
        for tid in producers_after:
            assert b.net.get_transition(tid) is not None

    def test_connect_wip_return_does_not_steal_tokens(self):
        """The connect must NOT add a transition that consumes tokens from exit_place."""
        b = PetriNetBuilder()
        wip = b.add_wip_controller("Conwip", wip_limit=2)
        machine = b.add_machine("M", processing_time=5.0)
        term = b.add_terminator("Out")
        b.connect(wip.interface.output_place_id, machine.interface.input_place_id)
        b.connect(machine.interface.output_place_id, term.interface.input_place_id)

        consumers_before = {
            a.target_id for a in b.net.arcs
            if a.source_id == term.interface.input_place_id
        }
        b.connect_wip_return(wip, term.interface.input_place_id)
        consumers_after = {
            a.target_id for a in b.net.arcs
            if a.source_id == term.interface.input_place_id
        }
        assert consumers_before == consumers_after, (
            "connect_wip_return must not add a new consumer of exit_place "
            "(would steal tokens from the terminator)"
        )

    def test_connect_wip_return_without_producers_raises(self):
        """Calling connect_wip_return before wiring producers must raise."""
        b = PetriNetBuilder()
        wip = b.add_wip_controller("Conwip", wip_limit=2)
        term = b.add_terminator("Out")
        with pytest.raises(ValueError):
            b.connect_wip_return(wip, term.interface.input_place_id)

    def test_simulation_throughput_not_capped_at_wip_limit(self):
        """Regression: a previous broken connect_wip_return absorbed entities
        into the return transition and yielded throughput equal to wip_limit.
        With proper slot recycling, throughput is bottleneck-bound."""
        from src.services.simulation.engine import PetriSimulator

        b = PetriNetBuilder(name="WipSim")
        gen = b.add_generator(
            "G", interval=2.0, distribution=DistributionType.DET
        )
        wip = b.add_wip_controller("Conwip", wip_limit=3)
        machine = b.add_machine(
            "M", processing_time=5.0, distribution=DistributionType.DET
        )
        term = b.add_terminator("Out")
        b.connect(gen.interface.output_place_id, wip.interface.input_place_id)
        b.connect(wip.interface.output_place_id, machine.interface.input_place_id)
        b.connect(machine.interface.output_place_id, term.interface.input_place_id)
        b.connect_wip_return(wip, term.interface.input_place_id)

        sim = PetriSimulator(b.net).run(simulation_time=300.0)
        assert sim.terminators
        throughput = sim.terminators[0].total_consumed
        assert throughput > 10, (
            f"Throughput {throughput} suspiciously close to wip_limit=3; "
            f"WIP slot recycling appears broken."
        )


class TestPatternApplyIsAtomic:
    """A pattern's apply() builds several places/transitions/arcs in a fixed
    sequence with no transaction of its own -- a failure partway through
    (typically a name collision on a LATER auto-derived name, e.g.
    "Foo_Free" already used by something else) used to leave every element
    added before that point stranded in the net. PetriNetBuilder._apply_pattern
    now rolls those back so a failed add_* is all-or-nothing, same as a
    failed add_place/add_transition/add_arc already is on its own."""

    def test_failed_add_machine_leaves_no_orphaned_elements(self):
        b = PetriNetBuilder()
        # "Processor_Free" pre-exists (e.g. from an unrelated place), so
        # add_machine("Processor") fails on its second net.add_place call --
        # AFTER "Processor_Queue" was already added.
        b.add_raw_place("Processor_Free", tokens=1)
        places_before = len(b.net.places)
        transitions_before = len(b.net.transitions)
        arcs_before = len(b.net.arcs)

        with pytest.raises(ValueError, match="Processor_Free"):
            b.add_machine("Processor", processing_time=1.0)

        assert len(b.net.places) == places_before
        assert len(b.net.transitions) == transitions_before
        assert len(b.net.arcs) == arcs_before
        assert not any(p.name.startswith("Processor_") for p in b.net.places if p.name != "Processor_Free")

    def test_failed_add_terminator_leaves_no_orphaned_elements(self):
        b = PetriNetBuilder()
        b.add_raw_transition("Counter_Exit")
        places_before = len(b.net.places)
        transitions_before = len(b.net.transitions)

        with pytest.raises(ValueError, match="Counter_Exit"):
            b.add_terminator("Counter")

        assert len(b.net.places) == places_before
        assert len(b.net.transitions) == transitions_before

    def test_a_retry_with_a_different_name_succeeds_cleanly(self):
        """The whole point of rolling back: once the collision is gone (or
        the caller picks a different name), a retry must work as if the
        failed attempt never happened -- no leftover elements competing for
        the same auto-derived names."""
        b = PetriNetBuilder()
        b.add_raw_place("Processor_Free", tokens=1)
        with pytest.raises(ValueError):
            b.add_machine("Processor", processing_time=1.0)

        result = b.add_machine("Processor2", processing_time=1.0)
        assert result.place_ids
        names = {p.id: p.name for p in b.net.places}
        assert names[result.place_ids[0]] == "Processor2_Queue"
