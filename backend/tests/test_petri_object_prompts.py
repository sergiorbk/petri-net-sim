"""Shared knowledge reaches chat and MCP through the installed package."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP
from petri_modeling_skills import catalog, modeling_guidance, read_resource

from src.mcp.prompts.petri_prompts import register_petri_prompts
from src.mcp.resources.modeling_resources import API_ADAPTER_URI, register_modeling_resources
from src.services.modeling_guidance import api_adapter, modeling_prompt


def test_chat_prompt_combines_shared_source_and_application_bindings():
    from src.services.agent.nodes.chat_node import SYSTEM_PROMPT

    assert SYSTEM_PROMPT == modeling_prompt()
    assert SYSTEM_PROMPT.startswith(modeling_guidance())
    assert SYSTEM_PROMPT.endswith(api_adapter())
    assert SYSTEM_PROMPT.count(modeling_guidance()) == 1


def test_prompt_composition_reads_the_shared_provider(monkeypatch):
    import src.services.modeling_guidance as guidance

    monkeypatch.setattr(guidance, "modeling_guidance", lambda: "changed shared knowledge")
    result = guidance.modeling_prompt()
    assert result.startswith("changed shared knowledge\n\n")
    assert result.endswith(api_adapter())


def test_mcp_initial_instructions_route_to_discoverable_guides():
    from src.mcp.server import _MCP_INSTRUCTIONS

    for resource in catalog():
        assert resource["uri"] in _MCP_INSTRUCTIONS
    assert API_ADAPTER_URI in _MCP_INSTRUCTIONS
    assert modeling_guidance() not in _MCP_INSTRUCTIONS


@pytest.mark.asyncio
async def test_mcp_resource_discovery_and_reads_match_shared_package():
    mcp = FastMCP("modeling-resource-test")
    register_modeling_resources(mcp)
    discovered = {str(resource.uri): resource for resource in await mcp.list_resources()}
    for resource in catalog():
        assert resource["uri"] in discovered
        assert discovered[resource["uri"]].mimeType == "text/markdown"
        response = list(await mcp.read_resource(resource["uri"]))
        assert len(response) == 1
        assert response[0].content == read_resource(resource["uri"])


@pytest.mark.asyncio
async def test_local_bindings_have_their_own_resource():
    mcp = FastMCP("modeling-bindings-test")
    register_modeling_resources(mcp)
    response = list(await mcp.read_resource(API_ADAPTER_URI))
    assert response[0].content == api_adapter()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["build_queueing_system", "build_production_line"])
async def test_task_prompts_keep_shared_guidance_and_requested_description(name):
    mcp = FastMCP("modeling-prompt-test")
    register_petri_prompts(mcp)
    requested = "Two parallel processing stations supplied from one queue"
    prompt = await mcp.get_prompt(name, {"description": requested})
    assert len(prompt.messages) == 1
    text = prompt.messages[0].content.text
    assert text.startswith(modeling_prompt())
    assert text.endswith(requested)
    assert text.count(modeling_guidance()) == 1
