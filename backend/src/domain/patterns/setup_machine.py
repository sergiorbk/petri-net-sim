"""Setup Machine pattern - processing station with mandatory setup/changeover phase."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class SetupMachinePattern(BasePattern):
    """
    Setup Machine pattern.

    A two-phase processing station: each job first triggers a setup phase
    (machine configuration / changeover), then the actual processing phase.
    One channel token is seized at StartSetup and held until FinishProcess,
    so setup and processing are atomic per channel — no other job can use the
    channel during either phase.

    Structure:
        [Queue] + [Free(c)] -> [StartSetup (DET)] -> [SettingUp]
        [SettingUp] -> [FinishSetup (setup_dist)] -> [Ready]
        [Ready] -> [StartProcess (DET)] -> [Processing]
        [Processing] -> [FinishProcess (process_dist)] -> [Done] + [Free recycled]

    Use cases:
    - CNC machine: tool change (setup) then part machining
    - Printing press: plate change then print run
    - Paint line: solvent flush then painting
    - Batch reactor: clean + load then reaction
    """

    tool_cursor_width = 700.0

    @property
    def name(self) -> str:
        return "SetupMachine"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        setup_time: float = 30.0,
        setup_distribution: DistributionType = DistributionType.DET,
        processing_time: float = 60.0,
        processing_distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        channels: int = 1,
    ) -> PatternResult:
        """
        Apply the SetupMachine pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "CNC", "PrintPress")
            x, y: Base coordinates
            setup_time: Mean setup/changeover duration
            setup_distribution: Distribution for setup time (default: DET)
            processing_time: Mean processing time per job
            processing_distribution: Distribution for processing time (default: EXP)
            standard_deviation: Std dev for NORM/UNIF phases
            channels: Number of parallel machine channels (default: 1)

        Returns:
            PatternResult with:
              - interface.input_place_id: Queue
              - interface.output_place_id: Done
              - metadata["setup_place_id"]: SettingUp place
              - metadata["consume_transition_ids"]: [StartSetup]
        """
        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_queue = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_queue.id)

        p_free = net.add_place(
            name=f"{instance_name}_Free",
            tokens=channels,
            x=x + 100,
            y=y - 80,
        )
        place_ids.append(p_free.id)

        p_setting_up = net.add_place(
            name=f"{instance_name}_SettingUp",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_setting_up.id)

        p_ready = net.add_place(
            name=f"{instance_name}_Ready",
            tokens=0,
            x=x + 300,
            y=y,
        )
        place_ids.append(p_ready.id)

        p_processing = net.add_place(
            name=f"{instance_name}_Processing",
            tokens=0,
            x=x + 400,
            y=y,
        )
        place_ids.append(p_processing.id)

        p_done = net.add_place(
            name=f"{instance_name}_Done",
            tokens=0,
            x=x + 600,
            y=y,
        )
        place_ids.append(p_done.id)

        # StartSetup (DET, immediate): Queue + Free → SettingUp
        t_start_setup = net.add_transition(
            name=f"{instance_name}_StartSetup",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_start_setup.id)

        # FinishSetup: SettingUp → Ready
        t_finish_setup = net.add_transition(
            name=f"{instance_name}_FinishSetup",
            mean_delay=setup_time,
            distribution=setup_distribution,
            standard_deviation=standard_deviation,
            x=x + 250,
            y=y,
        )
        transition_ids.append(t_finish_setup.id)

        # StartProcess (DET, immediate): Ready → Processing
        t_start_process = net.add_transition(
            name=f"{instance_name}_StartProcess",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 350,
            y=y,
        )
        transition_ids.append(t_start_process.id)

        # FinishProcess: Processing → Done + Free recycled
        t_finish_process = net.add_transition(
            name=f"{instance_name}_FinishProcess",
            mean_delay=processing_time,
            distribution=processing_distribution,
            standard_deviation=standard_deviation,
            x=x + 500,
            y=y,
        )
        transition_ids.append(t_finish_process.id)

        # Setup phase
        net.add_arc(source_id=p_queue.id, target_id=t_start_setup.id)
        net.add_arc(source_id=p_free.id, target_id=t_start_setup.id)
        net.add_arc(source_id=t_start_setup.id, target_id=p_setting_up.id)
        net.add_arc(source_id=p_setting_up.id, target_id=t_finish_setup.id)
        net.add_arc(source_id=t_finish_setup.id, target_id=p_ready.id)

        # Process phase
        net.add_arc(source_id=p_ready.id, target_id=t_start_process.id)
        net.add_arc(source_id=t_start_process.id, target_id=p_processing.id)
        net.add_arc(source_id=p_processing.id, target_id=t_finish_process.id)
        net.add_arc(source_id=t_finish_process.id, target_id=p_done.id)
        net.add_arc(source_id=t_finish_process.id, target_id=p_free.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_queue.id,
                output_place_id=p_done.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "setup_place_id": p_setting_up.id,
                "consume_transition_ids": [t_start_setup.id],
            },
        )
