"""Expose the installed shared modeling guides without copying their content."""

from mcp.server.fastmcp import FastMCP
from petri_modeling_skills import catalog, read_resource

from src.services.modeling_guidance import api_adapter

API_ADAPTER_URI = "petri://skills/petri-net-sim-api"


def register_modeling_resources(mcp: FastMCP) -> None:
    for resource in catalog():
        # FastMCP treats parameters as resource templates. Bind the URI in a
        # factory so each registered resource remains a zero-argument resource.
        def make_reader(uri: str):
            def read_shared_guide() -> str:
                return read_resource(uri)
            return read_shared_guide

        mcp.resource(resource["uri"], name=resource["name"],
                     description=resource["description"], mime_type="text/markdown")(
            make_reader(resource["uri"]))

    mcp.resource(API_ADAPTER_URI, name="Petri Net Sim tool bindings",
                 description="Application-specific operation and parameter bindings.",
                 mime_type="text/markdown")(api_adapter)
