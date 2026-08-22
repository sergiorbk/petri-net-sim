"""Tests for contract phase-2 part C: the Petri-objects guidance added to
the chat system prompt (petri_net_expert.md), the MCP server's top-level
instructions, and the two MCP prompt templates.

Content-only tests: no LLM call, no MCP server startup -- these just read
the files/strings the agent actually sees and check the new material is
present and, per the branch's own em-dash rule, free of a literal em dash
in the text this change wrote (pre-existing em dashes elsewhere in these
same files predate this change and are out of scope, exactly like phase 1's
own EXPLICIT_TOOL_NAMES-scoped em-dash sweep in test_agent_toolkit_catalog.py).
"""

from __future__ import annotations

from pathlib import Path

PETRI_NET_EXPERT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src" / "services" / "agent" / "prompts" / "petri_net_expert.md"
)


def _read_petri_net_expert() -> str:
    return PETRI_NET_EXPERT_PATH.read_text(encoding="utf-8")


def _petri_objects_section(full_text: str) -> str:
    """Slice out just the new section (from its header to the next
    ALL-CAPS header), so the em-dash check below is scoped to what this
    change actually wrote, not the whole pre-existing file."""
    start = full_text.index("PETRI-OBJECTS")
    end = full_text.index("PATTERN RECOGNITION")
    return full_text[start:end]


class TestPetriNetExpertPrompt:
    def test_petri_objects_section_exists(self):
        section = _petri_objects_section(_read_petri_net_expert())
        assert section.strip()

    def test_explains_what_an_object_is(self):
        section = _petri_objects_section(_read_petri_net_expert())
        assert "module with its own net" in section

    def test_explains_when_to_split_a_model(self):
        section = _petri_objects_section(_read_petri_net_expert())
        assert "SEPARATE subsystems" in section
        assert "stays flat" in section

    def test_explains_fusion_vs_transition_to_place(self):
        section = _petri_objects_section(_read_petri_net_expert())
        assert "placeFusion" in section
        assert "transitionToPlace" in section

    def test_explains_place_to_transition_retirement_as_fusion_plus_read_arc(self):
        section = _petri_objects_section(_read_petri_net_expert())
        assert "placeToTransition is retired" in section
        assert "read arc" in section

    def test_documents_the_recommended_flow(self):
        section = _petri_objects_section(_read_petri_net_expert())
        for tool in ("create_object", "link_objects", "validate_model", "run_simulation", "export_pnml"):
            assert tool in section

    def test_documents_the_active_object_rule(self):
        section = _petri_objects_section(_read_petri_net_expert())
        assert "ACTIVE-OBJECT RULE" in section
        assert "set_active_object" in section

    def test_section_is_em_dash_free(self):
        """C: the new content is written em-dash free (pre-existing em
        dashes in the intent-gate section above it predate this change)."""
        section = _petri_objects_section(_read_petri_net_expert())
        assert chr(0x2014) not in section


class TestMcpServerInstructions:
    def test_mentions_the_petri_object_workflow(self):
        from src.mcp.server import _MCP_INSTRUCTIONS

        assert "Petri-objects" in _MCP_INSTRUCTIONS
        assert "create_object" in _MCP_INSTRUCTIONS
        assert "link_objects" in _MCP_INSTRUCTIONS
        assert "validate_model" in _MCP_INSTRUCTIONS
        assert "set_active_object" in _MCP_INSTRUCTIONS

    def test_mentions_both_link_types(self):
        from src.mcp.server import _MCP_INSTRUCTIONS

        assert "placeFusion" in _MCP_INSTRUCTIONS
        assert "transitionToPlace" in _MCP_INSTRUCTIONS

    def test_instructions_are_em_dash_free(self):
        from src.mcp.server import _MCP_INSTRUCTIONS

        assert chr(0x2014) not in _MCP_INSTRUCTIONS


class TestMcpPromptTemplates:
    """The two @mcp.prompt() templates in petri_prompts.py, called directly
    as plain functions -- FastMCP's decorator returns a callable wrapper
    that still runs the original function body."""

    def _queueing_system_tip(self) -> str:
        from src.mcp.prompts.petri_prompts import register_petri_prompts

        captured: dict = {}

        class _FakeMcp:
            def prompt(self):
                def _decorator(fn):
                    captured[fn.__name__] = fn
                    return fn
                return _decorator

        register_petri_prompts(_FakeMcp())
        full = captured["build_queueing_system"]("5 items every 2 min")
        # Scope the em-dash check to the bullet this change added, not the
        # pre-existing "by place name -- names may merge" line above it.
        anchor = "If the description names genuinely separate subsystems"
        return full[full.index(anchor):]

    def _production_line_tip(self) -> str:
        from src.mcp.prompts.petri_prompts import register_petri_prompts

        captured: dict = {}

        class _FakeMcp:
            def prompt(self):
                def _decorator(fn):
                    captured[fn.__name__] = fn
                    return fn
                return _decorator

        register_petri_prompts(_FakeMcp())
        full = captured["build_production_line"]("a conveyor line")
        anchor = "If the line has genuinely separate modules"
        return full[full.index(anchor):]

    def test_build_queueing_system_mentions_petri_objects(self):
        tip = self._queueing_system_tip()
        assert "create_object" in tip
        assert "link_objects" in tip
        assert "validate_model" in tip

    def test_build_queueing_system_new_tip_is_em_dash_free(self):
        assert chr(0x2014) not in self._queueing_system_tip()

    def test_build_production_line_mentions_petri_objects(self):
        tip = self._production_line_tip()
        assert "create_object" in tip
        assert "link_objects" in tip
        assert "validate_model" in tip

    def test_build_production_line_new_tip_is_em_dash_free(self):
        assert chr(0x2014) not in self._production_line_tip()
