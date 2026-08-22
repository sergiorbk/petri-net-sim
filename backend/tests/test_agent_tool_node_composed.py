"""Chat dispatcher end-to-end test for Petri-objects (contract phase 2,
part E): builds a two-object fused model through real async tool_node()
calls -- the exact coroutine the chat graph runs, not the op_* functions
directly -- across three separate turns, asserting the resulting net_data
shape, that the chat service's own structural hash changes turn over turn,
and that a session rehydrated from nothing but the persisted net_data
(no shared PetriNetSession instance -- a later chat turn never gets one)
continues editing the SAME composed model rather than silently resetting
to flat.

Mirrors test_agent_tool_node.py's own helpers and style (phase-1 contract
E's chat dispatcher tests) so a reader familiar with that file recognizes
this one immediately.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.services.agent.nodes.tool_node import tool_node


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id}


def _ai_message(*calls: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=list(calls))


def _state(message: AIMessage, net_data: dict | None = None) -> dict:
    return {
        "messages": [message],
        "net_data": net_data or {},
        "conversation_id": "c1",
    }


def _assert_all_succeeded(messages: list[ToolMessage]) -> None:
    for msg in messages:
        assert getattr(msg, "status", "success") == "success", (
            f"tool call {msg.name!r} failed: {msg.content}"
        )


class TestComposedModelAcrossThreeTurns:
    """Turn 1: create_network, two objects (A, B), one place+transition
    each, an intra-object arc each. Turn 2: link_objects (placeFusion,
    B.PB -> A.PA) then validate_model, on net_data alone (no shared
    session). Turn 3: a fresh tool_node call adds another place to object
    A, proving the reload continues editing the SAME model."""

    @pytest.mark.asyncio
    async def test_turn_1_builds_two_objects(self):
        state = _state(_ai_message(
            _tool_call("create_network", {"name": "Composed"}, "t1"),
            _tool_call("create_object", {"name": "A"}, "t2"),
            _tool_call("add_place", {"name": "PA", "tokens": 1}, "t3"),
            _tool_call("add_transition", {"name": "TA"}, "t4"),
        ))
        result = await tool_node(state)
        _assert_all_succeeded(result["messages"])

        net_data = result["net_data"]
        assert net_data["name"] == "Composed"
        assert len(net_data["objects"]) == 1
        assert net_data["objects"][0]["name"] == "A"
        assert any(p["name"] == "PA" for p in net_data["places"])
        assert any(t["name"] == "TA" for t in net_data["transitions"])

    @pytest.mark.asyncio
    async def test_full_three_turn_flow(self):
        # --- Turn 1: object A with PA/TA, connected by a local arc ---
        turn1 = await tool_node(_state(_ai_message(
            _tool_call("create_network", {"name": "Composed"}, "t1"),
            _tool_call("create_object", {"name": "A"}, "t2"),
            _tool_call("add_place", {"name": "PA", "tokens": 1}, "t3"),
            _tool_call("add_transition", {"name": "TA"}, "t4"),
        )))
        _assert_all_succeeded(turn1["messages"])
        # add_arc needs the real ids the previous calls minted; look them
        # up from net_data rather than hardcoding p1/t1, matching how a
        # real LLM turn would read the previous tool results.
        pa_id = next(p["id"] for p in turn1["net_data"]["places"] if p["name"] == "PA")
        ta_id = next(t["id"] for t in turn1["net_data"]["transitions"] if t["name"] == "TA")

        turn1b = await tool_node(_state(
            _ai_message(
                _tool_call("add_arc", {"source_id": pa_id, "target_id": ta_id}, "t5"),
                _tool_call("create_object", {"name": "B"}, "t6"),
                _tool_call("add_place", {"name": "PB", "tokens": 0}, "t7"),
                _tool_call("add_transition", {"name": "TB"}, "t8"),
            ),
            net_data=turn1["net_data"],
        ))
        _assert_all_succeeded(turn1b["messages"])
        pb_id = next(p["id"] for p in turn1b["net_data"]["places"] if p["name"] == "PB")
        tb_id = next(t["id"] for t in turn1b["net_data"]["transitions"] if t["name"] == "TB")

        turn1c = await tool_node(_state(
            _ai_message(_tool_call("add_arc", {"source_id": pb_id, "target_id": tb_id}, "t9")),
            net_data=turn1b["net_data"],
        ))
        _assert_all_succeeded(turn1c["messages"])

        # --- Structural hash: turn 1's net_data is the "before" state ---
        from src.services.chat.openai_chat_service import _net_structure_hash
        before_link_hash = _net_structure_hash(turn1c["net_data"])

        # --- Turn 2: link_objects + validate_model, from net_data alone
        #     (a fresh PetriNetSession, exactly like a later chat turn) ---
        turn2 = await tool_node(_state(
            _ai_message(
                _tool_call(
                    "link_objects",
                    {
                        "link_type": "placeFusion",
                        "source_object": "B", "source_element": "PB",
                        "target_object": "A", "target_element": "PA",
                    },
                    "t10",
                ),
                _tool_call("validate_model", {}, "t11"),
            ),
            net_data=turn1c["net_data"],
        ))
        _assert_all_succeeded(turn2["messages"])
        validate_msg = turn2["messages"][1]
        assert "Composed model is valid" in validate_msg.content

        net_data = turn2["net_data"]
        # --- net_data shape assertions ---
        assert len(net_data["objects"]) == 2
        assert {o["name"] for o in net_data["objects"]} == {"A", "B"}
        assert len(net_data["links"]) == 1
        assert net_data["links"][0]["type"] == "placeFusion"
        object_ids = {o["id"] for o in net_data["objects"]}
        for place in net_data["places"]:
            assert place.get("objectId") in object_ids
        for trans in net_data["transitions"]:
            assert trans.get("objectId") in object_ids

        # --- Snapshot hash changed: the link_objects call is a real
        #     structural change even though no place/transition/arc in
        #     the flat lists moved. ---
        after_link_hash = _net_structure_hash(net_data)
        assert before_link_hash != after_link_hash

        # --- Turn 3: a brand new tool_node call, net_data only (no
        #     shared session instance) continues editing object A. ---
        turn3 = await tool_node(_state(
            _ai_message(
                _tool_call("set_active_object", {"name": "A"}, "t12"),
                _tool_call("add_place", {"name": "PA2", "tokens": 0}, "t13"),
            ),
            net_data=net_data,
        ))
        _assert_all_succeeded(turn3["messages"])

        final = turn3["net_data"]
        a_frame_id = next(o["id"] for o in final["objects"] if o["name"] == "A")
        b_frame_id = next(o["id"] for o in final["objects"] if o["name"] == "B")
        assert any(
            p["name"] == "PA2" and p.get("objectId") == a_frame_id
            for p in final["places"]
        )
        # The reload did not disturb object B or the fusion link.
        assert any(p["name"] == "PB" and p.get("objectId") == b_frame_id for p in final["places"])
        assert len(final["links"]) == 1
        assert final["links"][0]["type"] == "placeFusion"

    @pytest.mark.asyncio
    async def test_composed_run_simulation_through_the_dispatcher(self):
        """The composed local engine, reached the same way a real chat
        turn would: run_simulation as a normal catalog tool call, no
        session-level shortcut."""
        turn1 = await tool_node(_state(_ai_message(
            _tool_call("create_network", {"name": "Composed"}, "t1"),
            _tool_call("create_object", {"name": "A"}, "t2"),
            _tool_call("add_place", {"name": "PA", "tokens": 1}, "t3"),
            _tool_call("add_transition", {"name": "TA"}, "t4"),
        )))
        pa_id = next(p["id"] for p in turn1["net_data"]["places"] if p["name"] == "PA")
        ta_id = next(t["id"] for t in turn1["net_data"]["transitions"] if t["name"] == "TA")

        turn2 = await tool_node(_state(
            _ai_message(
                _tool_call("add_arc", {"source_id": pa_id, "target_id": ta_id}, "t5"),
                _tool_call("create_object", {"name": "B"}, "t6"),
                _tool_call("add_place", {"name": "PB", "tokens": 0}, "t7"),
                _tool_call("add_transition", {"name": "TB"}, "t8"),
            ),
            net_data=turn1["net_data"],
        ))
        pb_id = next(p["id"] for p in turn2["net_data"]["places"] if p["name"] == "PB")
        tb_id = next(t["id"] for t in turn2["net_data"]["transitions"] if t["name"] == "TB")

        turn3 = await tool_node(_state(
            _ai_message(
                _tool_call("add_arc", {"source_id": pb_id, "target_id": tb_id}, "t9"),
                _tool_call(
                    "link_objects",
                    {
                        "link_type": "placeFusion",
                        "source_object": "B", "source_element": "PB",
                        "target_object": "A", "target_element": "PA",
                    },
                    "t10",
                ),
            ),
            net_data=turn2["net_data"],
        ))
        _assert_all_succeeded(turn3["messages"])

        turn4 = await tool_node(_state(
            _ai_message(_tool_call("run_simulation", {"simulation_time": 10.0}, "t11")),
            net_data=turn3["net_data"],
        ))
        sim_msg = turn4["messages"][0]
        assert getattr(sim_msg, "status", "success") == "success"
        assert "Composed simulation across 3 object(s)" in sim_msg.content


class TestToolNodeSerializationGuard:
    """A session.to_net_data() failure after every tool call in the batch
    already succeeded must not discard the whole turn: previously this
    propagated straight out of tool_node, so the caller never even learned
    a tool ran and net_data went missing from the response entirely."""

    @pytest.mark.asyncio
    async def test_serialization_failure_keeps_previous_net_data_and_reports_an_error(
        self, monkeypatch,
    ):
        from src.services.petri.session import PetriNetSession

        def _boom(self):
            raise RuntimeError("boom")

        monkeypatch.setattr(PetriNetSession, "to_net_data", _boom)

        previous_net_data = {"name": "Previous", "places": [], "transitions": [], "arcs": []}
        state = _state(
            _ai_message(_tool_call("create_network", {"name": "New"}, "t1")),
            net_data=previous_net_data,
        )

        result = await tool_node(state)  # must not raise

        assert result["net_data"] == previous_net_data
        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert getattr(msg, "status", None) == "error"
        assert "failed to save" in msg.content
        assert "boom" in msg.content
        # The message still answers the SAME real tool_call -- never a
        # synthetic/orphaned id a later request to the model would reject
        # for not matching any tool_call the preceding AIMessage made.
        assert msg.tool_call_id == "t1"

    @pytest.mark.asyncio
    async def test_serialization_failure_amends_the_last_of_several_tool_messages(
        self, monkeypatch,
    ):
        from src.services.petri.session import PetriNetSession

        def _boom(self):
            raise RuntimeError("boom")

        monkeypatch.setattr(PetriNetSession, "to_net_data", _boom)

        state = _state(_ai_message(
            _tool_call("create_network", {"name": "New"}, "t1"),
            _tool_call("add_place", {"name": "P1", "tokens": 1}, "t2"),
        ))

        result = await tool_node(state)

        assert len(result["messages"]) == 2
        first, second = result["messages"]
        assert getattr(first, "status", "success") == "success"
        assert first.tool_call_id == "t1"
        assert getattr(second, "status", None) == "error"
        assert second.tool_call_id == "t2"
        assert "failed to save" in second.content
        # The original successful result text is preserved, not discarded.
        assert "Added place" in second.content
