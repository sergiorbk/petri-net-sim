"""Fork-Join pattern - parallel branch execution with synchronization barrier."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class ForkJoinPattern(BasePattern):
    """
    Fork-Join (AND-split / AND-join) pattern.

    A single entity enters, splits into N parallel branches processed
    independently, and continues only when ALL N branches have completed.
    This is qualitatively different from:
    - Assembly: waits for entities from *different arrival streams*
    - Duplicate: copies diverge and never rejoin

    Structure:
        [Input] --[Fork DET=0]--> [Branch1_Work] ... [BranchN_Work]
                                      |                    |
                                  [Finish1]           [FinishN]
                                      |                    |
                                  [Done1]             [DoneN]
                                      \\              /
                                       [Join DET=0]
                                             |
                                         [Output]

    Fork fires immediately (DET=0) producing one token in each Branch_i_Work.
    Join fires only when all N Done_i places hold a token.

    Use cases:
    - Hospital: blood test + X-ray + ECG → results available only when all done
    - Manufacturing: painting + QC + documentation → ship when all passed
    - Loan approval: credit check + identity check + income check → all clear
    """

    tool_cursor_width = 800.0

    @property
    def name(self) -> str:
        return "ForkJoin"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        n_branches: int = 2,
        branch_times: list[float] | None = None,
        branch_distribution: DistributionType = DistributionType.EXP,
    ) -> PatternResult:
        """
        Apply the ForkJoin pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "ParallelExam", "QualityGate")
            x, y: Base coordinates
            n_branches: Number of parallel branches (default: 2)
            branch_times: Mean processing time per branch.
                Length must equal n_branches. Default: [30.0, 30.0]
            branch_distribution: Distribution for all branch finish
                transitions. Default: EXP

        Returns:
            PatternResult with:
              - interface.input_place_id: Input (entity enters here)
              - interface.output_place_id: Output (entity exits after all branches)
              - metadata["branch_input_ids"]: list of Branch_i_Work place IDs
              - metadata["branch_done_ids"]: list of Done_i place IDs
              - metadata["join_transition_id"]: the Join transition ID
        """
        if branch_times is None:
            branch_times = [30.0] * n_branches
        if isinstance(branch_distribution, str):
            branch_distribution = DistributionType(branch_distribution)

        if len(branch_times) != n_branches:
            raise ValueError(
                f"branch_times must have exactly n_branches={n_branches} entries, "
                f"got {len(branch_times)}"
            )

        place_ids: list[str] = []
        transition_ids: list[str] = []

        # Input place
        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # Fork transition (DET=0): fires immediately, produces one token per branch
        t_fork = net.add_transition(
            name=f"{instance_name}_Fork",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_fork.id)
        net.add_arc(source_id=p_input.id, target_id=t_fork.id)

        branch_input_ids: list[str] = []
        branch_done_ids: list[str] = []

        spacing_y = 120.0
        start_y = y - ((n_branches - 1) * spacing_y) / 2.0

        for i in range(n_branches):
            branch_y = start_y + i * spacing_y

            # Branch work place (entity in progress on branch i)
            p_work = net.add_place(
                name=f"{instance_name}_Branch{i + 1}_Work",
                tokens=0,
                x=x + 250,
                y=branch_y,
            )
            place_ids.append(p_work.id)
            branch_input_ids.append(p_work.id)
            net.add_arc(source_id=t_fork.id, target_id=p_work.id)

            # Branch finish transition
            t_finish = net.add_transition(
                name=f"{instance_name}_Finish{i + 1}",
                mean_delay=branch_times[i],
                distribution=branch_distribution,
                x=x + 400,
                y=branch_y,
            )
            transition_ids.append(t_finish.id)

            # Done place (branch i completed)
            p_done = net.add_place(
                name=f"{instance_name}_Done{i + 1}",
                tokens=0,
                x=x + 550,
                y=branch_y,
            )
            place_ids.append(p_done.id)
            branch_done_ids.append(p_done.id)

            net.add_arc(source_id=p_work.id, target_id=t_finish.id)
            net.add_arc(source_id=t_finish.id, target_id=p_done.id)

        # Join transition: fires only when ALL Done_i hold a token
        t_join = net.add_transition(
            name=f"{instance_name}_Join",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 700,
            y=y,
        )
        transition_ids.append(t_join.id)
        for p_done_id in branch_done_ids:
            net.add_arc(source_id=p_done_id, target_id=t_join.id)

        # Output place
        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 850,
            y=y,
        )
        place_ids.append(p_output.id)
        net.add_arc(source_id=t_join.id, target_id=p_output.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "branch_input_ids": branch_input_ids,
                "branch_done_ids": branch_done_ids,
                "join_transition_id": t_join.id,
            },
        )
