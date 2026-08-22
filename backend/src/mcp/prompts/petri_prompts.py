"""MCP prompts for guiding Petri Net model creation."""

from mcp.server.fastmcp import FastMCP


def register_petri_prompts(mcp: FastMCP) -> None:
    """Register Petri Net prompt templates on the MCP server."""

    @mcp.prompt()
    def build_queueing_system(description: str) -> str:
        """Build a Petri net model from a queueing system description."""
        return (
            f"Build a Petri net model for the following queueing system:\n\n"
            f"{description}\n\n"
            "Follow these steps:\n"
            "1. Call create_network with an appropriate name\n"
            "2. Add generators for each arrival process (use appropriate distribution)\n"
            "3. Add machines for processing stations (set channels for parallel servers)\n"
            "4. Add terminators for system exits\n"
            "5. Connect patterns using connect_patterns where auto-connect didn't apply\n"
            "6. Call optimize_network to remove redundant elements\n"
            "7. Call export_pnml to get the PNML output\n\n"
            "Tips:\n"
            "- TIME UNITS: every timed tool accepts time_unit ('s'|'min'|'h'|'d').\n"
            "  Pass it EXPLICITLY whenever the user mentions minutes/hours/days.\n"
            "  '1 part per minute' -> rate=1, time_unit='min'. '2 hours processing'\n"
            "  -> processing_time=2, time_unit='h'. simulation_time MUST use the\n"
            "  same unit as the delays. Each tool's response echoes the value in\n"
            "  s/min/h/d so you can verify the interpretation matches intent.\n"
            "- Use 'exp' distribution for random arrivals (Poisson process)\n"
            "- Use 'det' for fixed/constant times\n"
            "- Use 'norm' when standard deviation is specified (e.g., '5+-1 min').\n"
            "  Negative samples are auto-truncated, so simulation never crashes.\n"
            "- For 'queue length max K, drop arrivals when full' use add_bounded_queue\n"
            "  followed by connect_bounded_consumer once the consumer is wired.\n"
            "- Patterns auto-connect sequentially, so add them in order\n"
            "- For parallel machines from the same queue, set auto_connect=False\n"
            "- ALWAYS connect by place_id from the previous tool's response, never\n"
            "  by place name - names may merge during optimize_network and break.\n"
            "- If the description names genuinely separate subsystems (not one\n"
            "  linear flow), consider Petri-objects instead of one flat net:\n"
            "  create_object per subsystem, build each with the usual add_*\n"
            "  tools, then link_objects to wire them (placeFusion for a shared\n"
            "  resource, transitionToPlace for a cross-object delivery), then\n"
            "  validate_model before run_simulation/export_pnml."
        )

    @mcp.prompt()
    def build_production_line(description: str) -> str:
        """Build a Petri net model for a production/manufacturing line."""
        return (
            f"Build a Petri net model for the following production line:\n\n"
            f"{description}\n\n"
            "Follow these steps:\n"
            "1. Call create_network with the production line name\n"
            "2. Add generators for raw material/parts arrivals\n"
            "3. For conveyor systems with bypass logic, use add_conveyor_line\n"
            "4. For regular processing stations, use add_machine\n"
            "5. For quality inspection, use add_quality_check\n"
            "6. For assembly/join points, use add_assembly\n"
            "7. For transport between stations, use add_transport_agent\n"
            "8. Add terminators for finished products\n"
            "9. Connect any remaining unconnected patterns\n"
            "10. Call optimize_network then export_pnml\n\n"
            "Tips:\n"
            "- Use add_conveyor_line (not add_conveyor_workstation) for multi-station conveyors\n"
            "- Use add_priority_choice for 'if resources available' logic\n"
            "- Use add_threshold_activation for 'activate backup when queue > N'\n"
            "- If the line has genuinely separate modules (e.g. a loader feeding\n"
            "  several independent lines, or a resource pool shared between\n"
            "  lines), use Petri-objects: create_object per module, build each\n"
            "  with the usual add_* tools, link_objects to wire them across\n"
            "  the module boundary, then validate_model before simulating or\n"
            "  exporting. A single linear line stays flat."
        )
