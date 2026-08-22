"""Tests for the v2 (composed model) remote simulation SSE parsing helper."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.simulation.remote_v2 import _parse_sse_block


def _generator_net(name: str):
    from src.domain.models import PetriNet

    net = PetriNet(name=name)
    p = net.add_place("P1", tokens=1, x=100, y=100)
    t = net.add_transition("T1", mean_delay=5.0, x=200, y=100)
    net.add_arc(p.id, t.id)
    net.add_arc(t.id, p.id)
    return net


class TestParseSseBlockV2:
    """Case-for-case mirror of TestParseSseBlock in test_simulation_remote.py,
    proving the duplicated parser behaves identically. Keep the two lists in
    lockstep — a case added on one side only is how the copies start to drift."""

    def test_session_event_returns_none(self):
        block = 'event: session\ndata: {"sessionId": "abc"}'
        assert _parse_sse_block(block) is None

    def test_done_sentinel_returns_none(self):
        assert _parse_sse_block("data: [DONE]") is None

    def test_no_data_returns_none(self):
        assert _parse_sse_block("event: ping\n") is None

    def test_malformed_json_returns_none(self):
        assert _parse_sse_block("data: {not valid json}") is None

    def test_valid_event_parsed(self):
        payload = {
            "current_time": 10.5,
            "step_number": 3,
            "markings": {"p1": 2, "p1obj2": 2},
            "buffers": {"t1": 0.5},
            "progress": 0.5,
        }
        block = f"data: {json.dumps(payload)}"
        result = _parse_sse_block(block)
        assert result is not None
        assert result.current_time == 10.5
        assert result.step_number == 3
        assert result.markings == {"p1": 2, "p1obj2": 2}
        assert result.buffers == {"t1": 0.5}
        assert result.progress == 0.5
        assert result.fired_transitions == []

    def test_named_event_with_data_still_parses(self):
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
        assert _parse_sse_block("") is None

    def test_firing_sequence_parsed(self):
        """Element ids inside a step are object-scoped and model-wide, exactly
        like the frame-level markings — one step describes the whole model."""
        payload = {
            "current_time": 1.5,
            "step_number": 2,
            "markings": {"p1": 1, "p1obj2": 0},
            "buffers": {"t1": 1, "t1obj2": 0},
            "progress": 0.15,
            "fired_transitions": ["t1"],
            "firing_sequence": [
                {
                    "transition_id": "t1",
                    "phase": "before_act_in",
                    "markings": {"p1": 2, "p1obj2": 0},
                    "buffers": {"t1": 0, "t1obj2": 0},
                    "time": 1.5,
                },
                {
                    "transition_id": "t1",
                    "phase": "after_act_in",
                    "markings": {"p1": 1, "p1obj2": 0},
                    "buffers": {"t1": 1, "t1obj2": 0},
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
        assert first.markings == {"p1": 2, "p1obj2": 0}
        assert first.buffers == {"t1": 0, "t1obj2": 0}
        assert first.time == 1.5

    def test_missing_new_fields_default_to_empty(self):
        """A petri-server predating the animation contract must still stream.

        This is the rollback guard: both new keys are read with .get(), so a
        frame carrying only the five original fields parses into empty lists
        rather than raising inside the streaming generator — which on this
        route would end the run outright, there being no local fallback.
        """
        payload = {
            "current_time": 10.5,
            "step_number": 3,
            "markings": {"p1": 2, "p1obj2": 2},
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
            "markings": {"p1": 1, "p1obj2": 1},
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
            "markings": {"p1": 1, "p1obj2": 0},
            "buffers": {"t1": 0},
            "progress": 0.4,
            "firing_sequence": [
                {
                    "transition_id": "t1",
                    "phase": "after_act_out",
                    "markings": {"p1": 0, "p1obj2": 1},
                    "buffers": {"t1": 0},
                }
            ],
        }
        result = _parse_sse_block(f"data: {json.dumps(payload)}")
        assert result is not None
        assert result.firing_sequence[0].time == 0.0


class TestOwnIdRestoration:
    """The exporter renames element ids when two objects share one, so the run
    must be translated back before the caller sees it: it asked about "p1" and
    would otherwise be answered about "o1_p1"."""

    @staticmethod
    def _twin_model():
        from src.domain.composed import ComposedModel, LinkType

        model = ComposedModel(name="Twins")
        model.add_object(_generator_net("Unit"), name="A")
        model.add_object(_generator_net("Unit"), name="B")
        model.add_link(LinkType.PLACE_FUSION, 0, 0, 1, 0)
        return model

    def test_no_rename_needs_no_translation(self):
        from src.domain.composed import ComposedModel
        from src.services.simulation.remote_v2 import _own_id_map

        model = ComposedModel(name="Distinct")
        model.add_object(_generator_net("A"), name="A")
        assert _own_id_map(model) is None

    def test_renamed_ids_are_restored_everywhere_they_appear(self):
        from src.services.simulation.engine import FiringStep, SimulationEvent
        from src.services.simulation.remote_v2 import _own_id_map, _restore_own_ids

        model = self._twin_model()
        own_id = _own_id_map(model)
        assert own_id, "two objects from the same net must collide"

        document_place = next(k for k in own_id if k.startswith("o0_") and "p" in own_id[k].lower())
        document_transition = next(
            k for k, v in own_id.items() if v == model.objects[0].net.transitions[0].id
        )
        expected_place = own_id[document_place]

        event = SimulationEvent(
            current_time=1.0,
            step_number=1,
            markings={document_place: 3},
            buffers={document_transition: 1},
            progress=0.5,
            fired_transitions=[document_transition],
            firing_sequence=[FiringStep(
                transition_id=document_transition,
                phase="after_act_in",
                markings={document_place: 3},
                buffers={document_transition: 1},
                time=1.0,
            )],
        )

        restored = _restore_own_ids(event, own_id)

        assert list(restored.markings) == [expected_place]
        assert restored.fired_transitions == [own_id[document_transition]]
        step = restored.firing_sequence[0]
        assert step.transition_id == own_id[document_transition]
        assert list(step.markings) == [expected_place]
        assert list(step.buffers) == [own_id[document_transition]]

    def test_an_unknown_key_is_passed_through_untouched(self):
        """petri-server may report an element the map has never heard of, and
        dropping it would be worse than showing it as it came."""
        from src.services.simulation.engine import SimulationEvent
        from src.services.simulation.remote_v2 import _own_id_map, _restore_own_ids

        own_id = _own_id_map(self._twin_model())
        event = SimulationEvent(
            current_time=0.0, step_number=0,
            markings={"surprise": 1}, buffers={}, progress=0.0,
        )
        assert _restore_own_ids(event, own_id).markings == {"surprise": 1}


class TestFusedMarkingDuplication:
    """A placeFusion group is exported as one real `<place>` (the survivor)
    plus a `<referencePlace>` for every other member, so petri-server's
    snapshot only ever reports a marking under the survivor's document id.
    `_restore_own_ids` must duplicate that value onto every fused-away
    member's own id too, or a caller asking about one gets nothing."""

    @staticmethod
    def _fusion_model_no_collision():
        """Two objects with distinct, explicit ids: object0's place fuses
        into object1's place, so object1's place ("pB") survives — a link
        makes its TARGET side the survivor (PetriObjModel.wire() semantics,
        see `_elect_shared_places`'s docstring)."""
        from src.domain.composed import ComposedModel, LinkType
        from src.domain.models import PetriNet

        a = PetriNet(name="A")
        pa = a.add_place("P1", tokens=1, place_id="pA")
        ta = a.add_transition("T1", mean_delay=1.0, transition_id="tA")
        a.add_arc(pa.id, ta.id, arc_id="arcA1")
        a.add_arc(ta.id, pa.id, arc_id="arcA2")

        b = PetriNet(name="B")
        pb = b.add_place("P1", tokens=0, place_id="pB")
        tb = b.add_transition("T1", mean_delay=1.0, transition_id="tB")
        b.add_arc(pb.id, tb.id, arc_id="arcB1")
        b.add_arc(tb.id, pb.id, arc_id="arcB2")

        model = ComposedModel(name="Fusion")
        model.add_object(a, name="A")
        model.add_object(b, name="B")
        model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=0,
                        target_object=1, target_element=0)
        return model

    def test_fusion_alias_map_points_fused_away_member_at_survivor(self):
        from src.services.simulation.remote_v2 import _fusion_alias_map

        model = self._fusion_model_no_collision()
        assert _fusion_alias_map(model) == {"pA": "pB"}

    def test_no_fusion_links_means_no_alias(self):
        from src.domain.composed import ComposedModel
        from src.domain.models import PetriNet
        from src.services.simulation.remote_v2 import _fusion_alias_map

        model = ComposedModel(name="NoLinks")
        model.add_object(PetriNet(name="Solo"))
        assert _fusion_alias_map(model) == {}

    def test_survivor_marking_is_duplicated_onto_fused_away_member(self):
        from src.services.simulation.engine import SimulationEvent
        from src.services.simulation.remote_v2 import _fusion_alias_map, _own_id_map, _restore_own_ids

        model = self._fusion_model_no_collision()
        own_id = _own_id_map(model)
        assert own_id is None  # explicit distinct ids, nothing collides

        fusion_alias = _fusion_alias_map(model)
        event = SimulationEvent(
            current_time=1.0, step_number=1,
            markings={"pB": 3}, buffers={"tB": 0}, progress=0.1,
        )
        restored = _restore_own_ids(event, own_id, fusion_alias)
        assert restored.markings == {"pB": 3, "pA": 3}
        # Buffers are transition-only, place fusion never touches them.
        assert restored.buffers == {"tB": 0}

    def test_duplication_also_applies_inside_firing_sequence_steps(self):
        from src.services.simulation.engine import FiringStep, SimulationEvent
        from src.services.simulation.remote_v2 import _fusion_alias_map, _own_id_map, _restore_own_ids

        model = self._fusion_model_no_collision()
        fusion_alias = _fusion_alias_map(model)
        event = SimulationEvent(
            current_time=1.0, step_number=1,
            markings={"pB": 2}, buffers={}, progress=0.1,
            firing_sequence=[FiringStep(
                transition_id="tB", phase="after_act_in",
                markings={"pB": 2}, buffers={"tB": 1}, time=1.0,
            )],
        )
        restored = _restore_own_ids(event, _own_id_map(model), fusion_alias)
        assert restored.firing_sequence[0].markings == {"pB": 2, "pA": 2}
        # Buffers inside a step are transition-only too.
        assert restored.firing_sequence[0].buffers == {"tB": 1}

    def test_survivor_absent_from_a_frame_leaves_member_absent_too(self):
        """A partial/mid-run snapshot that does not carry the survivor's
        marking must not manufacture one for the fused-away member either —
        there is nothing to duplicate."""
        from src.services.simulation.engine import SimulationEvent
        from src.services.simulation.remote_v2 import _fusion_alias_map, _own_id_map, _restore_own_ids

        model = self._fusion_model_no_collision()
        fusion_alias = _fusion_alias_map(model)
        event = SimulationEvent(
            current_time=1.0, step_number=1,
            markings={"unrelated": 1}, buffers={}, progress=0.1,
        )
        restored = _restore_own_ids(event, _own_id_map(model), fusion_alias)
        assert restored.markings == {"unrelated": 1}

    def test_composes_with_id_renaming_when_both_apply(self):
        """A fusion combined with an unrelated id collision elsewhere in the
        model still renames the fused places too (renaming is whole-
        document, all-or-nothing, see `build_final_id_map`), so the alias
        map must be resolved from the objects' OWN ids and applied AFTER
        `_own_id_map`'s rekeying, not instead of it."""
        from src.domain.composed import ComposedModel, LinkType
        from src.domain.models import PetriNet
        from src.services.simulation.engine import SimulationEvent
        from src.services.simulation.remote_v2 import _fusion_alias_map, _own_id_map, _restore_own_ids

        a = PetriNet(name="A")
        pa = a.add_place("P1", place_id="pA")
        ta = a.add_transition("T1", transition_id="tShared")
        a.add_arc(pa.id, ta.id, arc_id="arcA1")
        a.add_arc(ta.id, pa.id, arc_id="arcA2")

        b = PetriNet(name="B")
        pb = b.add_place("P1", place_id="pB")
        tb = b.add_transition("T1", transition_id="tB")
        b.add_arc(pb.id, tb.id, arc_id="arcB1")
        b.add_arc(tb.id, pb.id, arc_id="arcB2")

        c = PetriNet(name="C")
        pc = c.add_place("P1", place_id="pC")
        # Same transition id as object A, on an UNRELATED object: forces
        # whole-document renaming even though it has nothing to do with fusion.
        tc = c.add_transition("T1", transition_id="tShared")
        c.add_arc(pc.id, tc.id, arc_id="arcC1")
        c.add_arc(tc.id, pc.id, arc_id="arcC2")

        model = ComposedModel(name="M")
        model.add_object(a, name="A")
        model.add_object(b, name="B")
        model.add_object(c, name="C")
        model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=0,
                        target_object=1, target_element=0)

        own_id = _own_id_map(model)
        assert own_id is not None  # "tShared" collides across A and C

        fusion_alias = _fusion_alias_map(model)
        assert fusion_alias == {"pA": "pB"}

        document_survivor = next(k for k, v in own_id.items() if v == "pB")
        event = SimulationEvent(
            current_time=1.0, step_number=1,
            markings={document_survivor: 4}, buffers={}, progress=0.1,
        )
        restored = _restore_own_ids(event, own_id, fusion_alias)
        assert restored.markings == {"pB": 4, "pA": 4}


class TestRunRemoteStreamingV2:
    @pytest.mark.anyio
    async def test_run_remote_streaming_v2_processes_sse(self):
        """Mock httpx to simulate SSE streaming; assert the request targets
        /api/v2/simulation/stream with a modelXml body (not netXml)."""
        from src.domain.composed import ComposedModel
        from src.services.simulation.remote_v2 import run_remote_streaming_v2

        model = ComposedModel(name="TestModel")
        model.add_object(_generator_net("A"), name="A")
        model.add_object(_generator_net("B"), name="B")

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

        captured = {}

        def _capture_stream(method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            return mock_response

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(side_effect=_capture_stream)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.services.simulation.remote_v2.httpx.AsyncClient", return_value=mock_client
        ):
            events = []
            async for evt in run_remote_streaming_v2(
                model, "http://remote:8080", 10.0, 1.0, None, 0
            ):
                events.append(evt)

        assert len(events) == 1
        assert events[0].current_time == 5.0
        assert captured["url"] == "http://remote:8080/api/v2/simulation/stream"
        assert "modelXml" in captured["json"]
        assert "netXml" not in captured["json"]
