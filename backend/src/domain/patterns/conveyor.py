"""Conveyor pattern - sequential stations with transport between them."""

from typing import List
from src.domain import DistributionType, PetriNet
from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class ConveyorPattern(BasePattern):
    """
    Conveyor (Sequential Stations) pattern.

    Creates a series of processing stations connected by transport.
    Each station processes items and passes them to the next.

    Structure:
        [P: In] -> [T: Transport1] -> [P: Station1] -> [T: Process1] -> [P: Buffer1]
                        -> [T: Transport2] -> [P: Station2] -> [T: Process2] -> ...
                                -> [P: Out]

    Use cases:
    - "5 sequential stations on a conveyor belt"
    - "Assembly line with multiple stages"
    - "Pipeline processing"
    """

    @property
    def name(self) -> str:
        return "Conveyor"

    def apply(
            self,
            net: PetriNet,
            instance_name: str,
            x: float,
            y: float,
            stations: List[dict] | None = None,
            transport_time: float = 5.0,
    ) -> PatternResult:
        """
        Apply the Conveyor pattern.

        Args:
            net: Target PetriNet
            instance_name: Name (e.g., "AssemblyLine", "Pipeline")
            x, y: Coordinates
            stations: Configuration for each station.
                [{"name": "Station1", "time": 60.0, "distribution": "exp"}, ...]
                If not provided, creates 3 default stations.
            transport_time: Time to move between stations. Default: 5.0.

        Returns:
            PatternResult.
            - input_place_id: Entry point to conveyor.
            - output_place_id: Exit point from conveyor.
        """
        stations_config = stations
        if not stations_config:
            stations_config = [
                {"name": "Stage1", "time": 10.0, "distribution": "exp"},
                {"name": "Stage2", "time": 15.0, "distribution": "exp"},
                {"name": "Stage3", "time": 10.0, "distribution": "exp"},
            ]

        place_ids = []
        transition_ids = []

        # Starting position
        current_x = x
        spacing_x = 150

        # 1. Entry place
        p_entry = net.add_place(
            name=f"{instance_name}_Entry",
            tokens=0,
            x=current_x,
            y=y,
        )
        place_ids.append(p_entry.id)
        current_x += spacing_x

        prev_place_id = p_entry.id

        # 2. Create each station
        for i, station in enumerate(stations_config):
            station_name = station.get("name", f"Station{i + 1}")
            station_time = station.get("time", 10.0)
            station_dist_str = station.get("distribution", "exp")
            station_dist = DistributionType(station_dist_str)

            # Transport transition to this station
            t_transport = net.add_transition(
                name=f"{instance_name}_To{station_name}",
                mean_delay=transport_time,
                distribution=DistributionType.DET,
                x=current_x,
                y=y,
            )
            transition_ids.append(t_transport.id)
            current_x += spacing_x

            # Station place (waiting at station)
            p_station = net.add_place(
                name=f"{instance_name}_{station_name}_Wait",
                tokens=0,
                x=current_x,
                y=y,
            )
            place_ids.append(p_station.id)
            current_x += spacing_x

            # Process transition at this station
            t_process = net.add_transition(
                name=f"{instance_name}_{station_name}_Process",
                mean_delay=station_time,
                distribution=station_dist,
                x=current_x,
                y=y,
            )
            transition_ids.append(t_process.id)
            current_x += spacing_x

            # Buffer after station (done at this station)
            p_buffer = net.add_place(
                name=f"{instance_name}_{station_name}_Done",
                tokens=0,
                x=current_x,
                y=y,
            )
            place_ids.append(p_buffer.id)
            current_x += spacing_x

            # Connect: prev -> transport -> station -> process -> buffer
            net.add_arc(source_id=prev_place_id, target_id=t_transport.id)
            net.add_arc(source_id=t_transport.id, target_id=p_station.id)
            net.add_arc(source_id=p_station.id, target_id=t_process.id)
            net.add_arc(source_id=t_process.id, target_id=p_buffer.id)

            prev_place_id = p_buffer.id

        # 3. Final transport to exit
        t_exit = net.add_transition(
            name=f"{instance_name}_ToExit",
            mean_delay=transport_time,
            distribution=DistributionType.DET,
            x=current_x,
            y=y,
        )
        transition_ids.append(t_exit.id)
        current_x += spacing_x

        # 4. Exit place
        p_exit = net.add_place(
            name=f"{instance_name}_Exit",
            tokens=0,
            x=current_x,
            y=y,
        )
        place_ids.append(p_exit.id)

        # Connect last buffer to exit
        net.add_arc(source_id=prev_place_id, target_id=t_exit.id)
        net.add_arc(source_id=t_exit.id, target_id=p_exit.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_entry.id,
                output_place_id=p_exit.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )
