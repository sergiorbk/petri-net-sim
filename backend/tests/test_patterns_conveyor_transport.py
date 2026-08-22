"""Tests for Conveyor and TransportAgent patterns."""

from __future__ import annotations

import pytest

from src.domain import PetriNet, DistributionType
from src.domain.patterns.conveyor import ConveyorPattern
from src.domain.patterns.transport_agent import TransportAgentPattern


class TestConveyorPattern:
    def _make_net(self) -> PetriNet:
        return PetriNet(name="TestNet")

    def test_default_stations_creates_three(self):
        net = self._make_net()
        pattern = ConveyorPattern()
        result = pattern.apply(net, "Line1", x=100, y=100)

        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None
        # 3 default stations → entry + 3×(station+buffer) + exit = 1+3*2+1 = 8 places
        assert len(result.place_ids) == 8

    def test_default_stations_transition_count(self):
        net = self._make_net()
        pattern = ConveyorPattern()
        result = pattern.apply(net, "Line1", x=100, y=100)
        # 3 stations × (transport + process) + 1 exit transport = 7 transitions
        assert len(result.transition_ids) == 7

    def test_custom_stations(self):
        net = self._make_net()
        stations = [
            {"name": "Cut", "time": 30.0, "distribution": "exp"},
            {"name": "Weld", "time": 45.0, "distribution": "det"},
        ]
        pattern = ConveyorPattern()
        result = pattern.apply(net, "Custom", x=0, y=0, stations=stations)

        # 2 custom stations → 1+2*2+1 = 6 places
        assert len(result.place_ids) == 6
        # 2 stations × 2 + 1 exit = 5 transitions
        assert len(result.transition_ids) == 5

    def test_custom_transport_time(self):
        net = self._make_net()
        pattern = ConveyorPattern()
        pattern.apply(net, "Fast", x=0, y=0, transport_time=2.0)
        # check that transport transitions use DET distribution
        transport_trans = [
            t for t in net.transitions if "To" in t.name
        ]
        for t in transport_trans:
            assert t.distribution == DistributionType.DET

    def test_input_is_entry_place(self):
        net = self._make_net()
        pattern = ConveyorPattern()
        result = pattern.apply(net, "Line", x=100, y=100)
        entry = net.get_place(result.interface.input_place_id)
        assert entry is not None
        assert "Entry" in entry.name

    def test_output_is_exit_place(self):
        net = self._make_net()
        pattern = ConveyorPattern()
        result = pattern.apply(net, "Line", x=100, y=100)
        exit_place = net.get_place(result.interface.output_place_id)
        assert exit_place is not None
        assert "Exit" in exit_place.name

    def test_station_distributions(self):
        net = self._make_net()
        stations = [
            {"name": "S1", "time": 10.0, "distribution": "exp"},
            {"name": "S2", "time": 20.0, "distribution": "det"},
        ]
        pattern = ConveyorPattern()
        pattern.apply(net, "Conveyor", x=0, y=0, stations=stations)
        process_trans = [t for t in net.transitions if "Process" in t.name]
        dists = {t.distribution for t in process_trans}
        assert DistributionType.EXP in dists
        assert DistributionType.DET in dists

    def test_arcs_connect_all_elements(self):
        net = self._make_net()
        pattern = ConveyorPattern()
        result = pattern.apply(net, "Line", x=100, y=100)
        # Should have arcs for: prev→transport→station→process→buffer chain × n_stations
        assert len(net.arcs) > 0

    def test_place_ids_all_valid(self):
        net = self._make_net()
        pattern = ConveyorPattern()
        result = pattern.apply(net, "Line", x=100, y=100)
        for pid in result.place_ids:
            assert net.get_place(pid) is not None


class TestTransportAgentPattern:
    def _make_net(self) -> PetriNet:
        return PetriNet(name="TestNet")

    def test_creates_six_places(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        result = pattern.apply(net, "Robot1", x=100, y=100)
        assert len(result.place_ids) == 6

    def test_creates_four_transitions(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        result = pattern.apply(net, "Robot1", x=100, y=100)
        assert len(result.transition_ids) == 4

    def test_input_is_queue_place(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        result = pattern.apply(net, "AGV", x=0, y=0)
        queue = net.get_place(result.interface.input_place_id)
        assert queue is not None
        assert "Queue" in queue.name

    def test_output_is_output_place(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        result = pattern.apply(net, "AGV", x=0, y=0)
        output = net.get_place(result.interface.output_place_id)
        assert output is not None
        assert "Output" in output.name

    def test_free_place_has_one_token(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        result = pattern.apply(net, "Forklift", x=0, y=0)
        free_place = next(
            p for p in net.places if "Free" in p.name and "Forklift" in p.name
        )
        assert free_place.tokens == 1

    def test_return_time_defaults_to_move_time(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        result = pattern.apply(net, "Robot", x=0, y=0, move_time=15.0)
        return_trans = next(
            t for t in net.transitions if "Return" in t.name
        )
        assert return_trans.mean_delay == 15.0

    def test_custom_return_time(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        pattern.apply(net, "Robot", x=0, y=0, move_time=6.0, return_time=12.0)
        return_trans = next(
            t for t in net.transitions if "Return" in t.name
        )
        assert return_trans.mean_delay == 12.0

    def test_grab_uses_unif_distribution_by_default(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        pattern.apply(net, "Robot", x=0, y=0)
        grab_trans = next(t for t in net.transitions if "Grab" in t.name)
        assert grab_trans.distribution == DistributionType.UNIF

    def test_move_uses_det_distribution_by_default(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        pattern.apply(net, "Robot", x=0, y=0)
        move_trans = next(t for t in net.transitions if "_Move" in t.name)
        assert move_trans.distribution == DistributionType.DET

    def test_all_place_ids_valid(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        result = pattern.apply(net, "Robot", x=0, y=0)
        for pid in result.place_ids:
            assert net.get_place(pid) is not None

    def test_all_transition_ids_valid(self):
        net = self._make_net()
        pattern = TransportAgentPattern()
        result = pattern.apply(net, "Robot", x=0, y=0)
        for tid in result.transition_ids:
            assert net.get_transition(tid) is not None
