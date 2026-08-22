"""MCP scripted scenario test for Petri-objects (contract phase 2, part E):
create_object x2, add elements, link, validate, export -- run against the
REAL FastMCP server (create_mcp_server(), the same factory production uses)
through the real MCP protocol, using the mcp SDK's own in-memory
client/server test transport (mcp.shared.memory) rather than a MockFastMCP
double or calling tool functions directly. This is the layer
test_mcp_real_server_schema.py's own module docstring says a mock-based
test cannot see: registration wiring, FastMCP's own argument validation,
and (here) actual per-MCP-session state via the real session_store, end to
end across a whole multi-call scenario.

One `create_connected_server_and_client_session` block = one MCP client
session = one PetriNetSession (see src/mcp/tools/petri_tools.py's
_session_id: keyed off id(ctx.session)), so every call inside one `async
with` block shares state, exactly like a real MCP client's tool calls
across one connection.
"""

from __future__ import annotations

import re

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from src.mcp.server import create_mcp_server

_ID_RE = re.compile(r"id=(\w+)")


def _text(result) -> str:
    """The tool's plain-text result, same shape a real MCP client reads."""
    assert not result.isError, f"tool call reported isError: {result.content}"
    assert result.content, "tool call returned no content blocks"
    return result.content[0].text


def _extract_id(text: str) -> str:
    match = _ID_RE.search(text)
    assert match, f"no id=... found in: {text!r}"
    return match.group(1)


class TestMcpComposedScenario:
    @pytest.mark.anyio
    async def test_two_objects_build_link_validate_export(self):
        mcp = create_mcp_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            # --- create_network, then object A with a local place/transition/arc ---
            r = await client.call_tool("create_network", {"name": "Composed"})
            assert not r.isError

            r = await client.call_tool("create_object", {"name": "A"})
            text = _text(r)
            assert "'A'" in text
            assert "index=0" in text

            r = await client.call_tool("add_place", {"name": "PA", "tokens": 1})
            pa_id = _extract_id(_text(r))

            r = await client.call_tool("add_transition", {"name": "TA"})
            ta_id = _extract_id(_text(r))

            r = await client.call_tool("add_arc", {"source_id": pa_id, "target_id": ta_id})
            assert not r.isError

            # --- object B with its own local place/transition/arc ---
            r = await client.call_tool("create_object", {"name": "B"})
            text = _text(r)
            assert "'B'" in text
            assert "index=1" in text

            r = await client.call_tool("add_place", {"name": "PB", "tokens": 0})
            pb_id = _extract_id(_text(r))

            r = await client.call_tool("add_transition", {"name": "TB"})
            tb_id = _extract_id(_text(r))

            r = await client.call_tool("add_arc", {"source_id": pb_id, "target_id": tb_id})
            assert not r.isError

            # --- list_objects: both present, B active, no links yet ---
            r = await client.call_tool("list_objects", {})
            text = _text(r)
            assert "'A'" in text
            assert "'B' (active)" in text

            # --- link_objects: fuse B's PB into A's PA ---
            r = await client.call_tool("link_objects", {
                "link_type": "placeFusion",
                "source_object": "B", "source_element": "PB",
                "target_object": "A", "target_element": "PA",
            })
            text = _text(r)
            assert "placeFusion" in text
            assert "'B'.PB" in text
            assert "'A'.PA" in text

            r = await client.call_tool("list_links", {})
            text = _text(r)
            assert "=== Links (1) ===" in text

            # --- validate_model: the whole composed model, not validate_net ---
            r = await client.call_tool("validate_model", {})
            text = _text(r)
            assert "Composed model is valid" in text
            assert "1 link(s)" in text

            # --- export_pnml: composed session routes to the ISO composed
            #     dialect exporter (Part B), not the flat one -- raw XML
            #     comes straight back as the tool's plain text result on
            #     MCP (unlike chat's side-channel download-link convention). ---
            r = await client.call_tool("export_pnml", {})
            xml = _text(r)
            assert xml.startswith("<?xml")
            assert "<pnml" in xml
            # Two Petri-object pages plus the free pool's own page.
            assert xml.count("<page ") >= 2

            # --- run_simulation: composed local engine, reached the same
            #     way a real MCP client would call it. ---
            r = await client.call_tool("run_simulation", {"simulation_time": 10.0})
            text = _text(r)
            assert not r.isError
            assert "Composed simulation across 3 object(s)" in text

    @pytest.mark.anyio
    async def test_placetotransition_link_type_rejected_by_the_real_schema(self):
        """Part B narrowed link_type's JSON-schema enum to just
        ("placeFusion", "transitionToPlace") -- the retired type is
        excluded from the schema, not merely refused once it reaches
        op_link_objects (test_agent_toolkit_catalog.py's
        test_link_type_choices_exclude_the_retired_link_type checks this
        by inspecting the catalog's ToolParam directly; this is the same
        claim exercised end to end through FastMCP's own real argument
        validation on the live protocol surface). A real client is
        stopped by its own generated schema before this could ever reach
        op_link_objects's runtime retirement-message branch at all."""
        mcp = create_mcp_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            await client.call_tool("create_network", {"name": "Composed"})
            await client.call_tool("create_object", {"name": "A"})
            await client.call_tool("add_place", {"name": "PA"})
            await client.call_tool("create_object", {"name": "B"})
            await client.call_tool("add_transition", {"name": "TB"})

            r = await client.call_tool("link_objects", {
                "link_type": "placeToTransition",
                "source_object": "A", "source_element": "PA",
                "target_object": "B", "target_element": "TB",
            })
            assert r.isError
            text = r.content[0].text
            assert "placeFusion" in text
            assert "transitionToPlace" in text

            # No link was created by the rejected call.
            ok = await client.call_tool("list_links", {})
            assert "No links yet" in _text(ok)

    @pytest.mark.anyio
    async def test_each_client_session_gets_its_own_session_state(self):
        """Two independent MCP client sessions against the same server
        instance must not see each other's objects -- the real
        session_store keyed by id(ctx.session), not a module-level global."""
        mcp = create_mcp_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client_a:
            await client_a.call_tool("create_network", {"name": "OnlyA"})
            await client_a.call_tool("create_object", {"name": "A"})

        async with create_connected_server_and_client_session(mcp._mcp_server) as client_b:
            r = await client_b.call_tool("list_objects", {})
            text = _text(r)
            assert "This session is flat" in text
