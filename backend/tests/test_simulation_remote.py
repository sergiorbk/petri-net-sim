"""Tests for remote simulation SSE parsing helper."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.simulation.remote import _parse_sse_block


class TestParseSseBlock:
    def test_session_event_returns_none(self):
        block = "event: session\ndata: {\"sessionId\": \"abc\"}"
        result = _parse_sse_block(block)
        assert result is None

    def test_done_sentinel_returns_none(self):
        block = "data: [DONE]"
        result = _parse_sse_block(block)
        assert result is None

    def test_no_data_returns_none(self):
        block = "event: ping\n"
        result = _parse_sse_block(block)
        assert result is None

    def test_malformed_json_returns_none(self):
        block = "data: {not valid json}"
        result = _parse_sse_block(block)
        assert result is None

    def test_valid_event_parsed(self):
        payload = {
            "current_time": 10.5,
            "step_number": 3,
            "markings": {"p1": 2},
            "buffers": {"t1": 0.5},
            "progress": 0.5,
        }
        block = f"data: {json.dumps(payload)}"
        result = _parse_sse_block(block)
        assert result is not None
        assert result.current_time == 10.5
        assert result.step_number == 3
        assert result.markings == {"p1": 2}
        assert result.buffers == {"t1": 0.5}
        assert result.progress == 0.5
        assert result.fired_transitions == []

    def test_event_with_name_and_data(self):
        payload = {
            "current_time": 5.0,
            "step_number": 1,
            "markings": {},
            "buffers": {},
            "progress": 0.1,
        }
        block = f"event: frame\ndata: {json.dumps(payload)}"
        result = _parse_sse_block(block)
        assert result is not None
        assert result.current_time == 5.0

    def test_empty_block_returns_none(self):
        result = _parse_sse_block("")
        assert result is None

    def test_firing_sequence_parsed(self):
        payload = {
            "current_time": 1.5,
            "step_number": 2,
            "markings": {"p1": 1, "p2": 0},
            "buffers": {"t1": 1},
            "progress": 0.15,
            "fired_transitions": ["t1"],
            "firing_sequence": [
                {
                    "transition_id": "t1",
                    "phase": "before_act_in",
                    "markings": {"p1": 2, "p2": 0},
                    "buffers": {"t1": 0},
                    "time": 1.5,
                },
                {
                    "transition_id": "t1",
                    "phase": "after_act_in",
                    "markings": {"p1": 1, "p2": 0},
                    "buffers": {"t1": 1},
                    "time": 1.5,
                },
            ],
        }
        result = _parse_sse_block(f"data: {json.dumps(payload)}")
        assert result is not None
        assert result.fired_transitions == ["t1"]
        assert len(result.firing_sequence) == 2
        first = result.firing_sequence[0]
        assert first.transition_id == "t1"
        assert first.phase == "before_act_in"
        assert first.markings == {"p1": 2, "p2": 0}
        assert first.buffers == {"t1": 0}
        assert first.time == 1.5

    def test_missing_new_fields_default_to_empty(self):
        """A petri-server predating the animation contract must still stream.

        This is the rollback guard: both new keys are read with .get(), so a
        frame carrying only the five original fields parses into empty lists
        rather than raising inside the streaming generator.
        """
        payload = {
            "current_time": 10.5,
            "step_number": 3,
            "markings": {"p1": 2},
            "buffers": {"t1": 0},
            "progress": 0.5,
        }
        result = _parse_sse_block(f"data: {json.dumps(payload)}")
        assert result is not None
        assert result.fired_transitions == []
        assert result.firing_sequence == []

    def test_malformed_firing_sequence_is_ignored(self):
        """Every shape of garbage degrades to "no animation", never to a
        dropped frame — the phases are decoration, the markings are the data."""
        base = {
            "current_time": 1.0,
            "step_number": 1,
            "markings": {"p1": 1},
            "buffers": {"t1": 0},
            "progress": 0.1,
        }

        def parse(**overrides):
            block = f"data: {json.dumps({**base, **overrides})}"
            result = _parse_sse_block(block)
            assert result is not None, "the frame itself must survive a bad firing_sequence"
            return result

        assert parse(firing_sequence="nope").firing_sequence == []
        assert parse(firing_sequence=["t1", 42, None]).firing_sequence == []

        unknown_phase = parse(firing_sequence=[
            {"transition_id": "t1", "phase": "sideways", "markings": {}, "buffers": {}},
            {"transition_id": "t1", "phase": "after_act_in", "markings": {}, "buffers": {}},
        ])
        assert [fs.phase for fs in unknown_phase.firing_sequence] == ["after_act_in"]

        # Dropped, not defaulted to {}: the client shows a phase instead of the
        # frame's own snapshot, so an empty marking blanks the net.
        assert parse(
            firing_sequence=[{"transition_id": "t1", "phase": "before_act_in"}]
        ).firing_sequence == []

        # A non-scalar phase must not reach the set membership test, which hashes it.
        for unhashable in (["before_act_in"], {"name": "before_act_in"}):
            assert parse(firing_sequence=[
                {"transition_id": "t1", "phase": unhashable, "markings": {}, "buffers": {}},
            ]).firing_sequence == []

        # An integer too large for a float must not escape as OverflowError.
        huge_time = parse(firing_sequence=[{
            "transition_id": "t1", "phase": "after_act_out",
            "markings": {"p1": 1}, "buffers": {"t1": 0}, "time": 10 ** 400,
        }])
        assert huge_time.firing_sequence[0].time == 0.0

        assert parse(fired_transitions=["t1", 7, None]).fired_transitions == ["t1"]

    def test_firing_step_time_defaults_when_absent(self):
        payload = {
            "current_time": 4.0,
            "step_number": 1,
            "markings": {"p1": 1},
            "buffers": {"t1": 0},
            "progress": 0.4,
            "firing_sequence": [
                {
                    "transition_id": "t1",
                    "phase": "after_act_out",
                    "markings": {"p1": 0},
                    "buffers": {"t1": 0},
                }
            ],
        }
        result = _parse_sse_block(f"data: {json.dumps(payload)}")
        assert result is not None
        assert result.firing_sequence[0].time == 0.0


class TestRunRemoteStreaming:
    @pytest.mark.anyio
    async def test_run_remote_streaming_processes_sse(self):
        """Mock httpx to simulate SSE streaming."""
        from src.domain import PetriNet
        from src.services.simulation.remote import run_remote_streaming

        net = PetriNet(name="TestNet")
        p = net.add_place("P1", tokens=1, x=100, y=100)
        t = net.add_transition("T1", mean_delay=5.0, x=200, y=100)
        p2 = net.add_place("P2", tokens=0, x=300, y=100)
        net.add_arc(source_id=p.id, target_id=t.id)
        net.add_arc(source_id=t.id, target_id=p2.id)

        payload = json.dumps({
            "current_time": 5.0,
            "step_number": 1,
            "markings": {},
            "buffers": {},
            "progress": 1.0,
        })
        sse_data = f"data: {payload}\n\ndata: [DONE]\n\n"

        async def _mock_aiter_text():
            yield sse_data

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_text = _mock_aiter_text
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.services.simulation.remote.httpx.AsyncClient", return_value=mock_client):
            events = []
            async for evt in run_remote_streaming(
                net, "http://remote:8080", 10.0, 1.0, None, 0
            ):
                events.append(evt)

        assert len(events) == 1
        assert events[0].current_time == 5.0
