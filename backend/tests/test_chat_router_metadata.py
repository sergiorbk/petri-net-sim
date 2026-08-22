"""Tests for openai_api/v1/routers/chat.py's metadata-resolution helpers:
net_style, agent_effort and layout_direction all read from
ChatCompletionRequest.metadata, degrading gracefully (never rejecting the
request) for a missing or unrecognized value -- the same convention
metadata.llm_credential_id already follows for a generic
OpenAI-compatible client.
"""

import pytest

from src.core.config import settings
from src.openai_api.v1.routers import chat as chat_router
from src.services.agent.nodes.chat_node import (
    DEFAULT_LAYOUT_DIRECTION,
    DEFAULT_NET_STYLE,
)


class TestResolveNetStyle:
    def test_missing_metadata_defaults(self):
        assert chat_router._resolve_net_style(None) == DEFAULT_NET_STYLE

    def test_missing_key_defaults(self):
        assert chat_router._resolve_net_style({}) == DEFAULT_NET_STYLE

    def test_unknown_value_defaults(self):
        assert chat_router._resolve_net_style({"net_style": "bogus"}) == DEFAULT_NET_STYLE

    def test_classical_is_honored(self):
        assert chat_router._resolve_net_style({"net_style": "classical"}) == "classical"

    def test_object_is_honored(self):
        assert chat_router._resolve_net_style({"net_style": "object"}) == "object"


class TestResolveRecursionLimit:
    def test_missing_metadata_defaults_to_standard(self):
        assert chat_router._resolve_recursion_limit(None) == settings.AGENT_RECURSION_LIMIT

    def test_unknown_value_defaults_to_standard(self):
        assert (
            chat_router._resolve_recursion_limit({"agent_effort": "bogus"})
            == settings.AGENT_RECURSION_LIMIT
        )

    def test_standard_maps_to_agent_recursion_limit(self):
        assert (
            chat_router._resolve_recursion_limit({"agent_effort": "standard"})
            == settings.AGENT_RECURSION_LIMIT
        )

    def test_thorough_maps_to_the_larger_budget(self):
        assert (
            chat_router._resolve_recursion_limit({"agent_effort": "thorough"})
            == settings.AGENT_RECURSION_LIMIT_THOROUGH
        )
        assert settings.AGENT_RECURSION_LIMIT_THOROUGH > settings.AGENT_RECURSION_LIMIT

    def test_reads_settings_live_not_at_import_time(self, monkeypatch):
        """An operator can retune either tier via env/settings without a
        code change taking a fresh deploy to pick up -- the resolver must
        not have captured the old value at module import."""
        monkeypatch.setattr(settings, "AGENT_RECURSION_LIMIT_THOROUGH", 999)
        assert chat_router._resolve_recursion_limit({"agent_effort": "thorough"}) == 999


class TestResolveUncappedEffort:
    """The workbench's iteration limit is OFF by default, and off means the
    turn runs to completion rather than stopping mid-build."""

    def test_uncapped_maps_to_the_backstop(self):
        assert (
            chat_router._resolve_recursion_limit({"agent_effort": "uncapped"})
            == settings.AGENT_RECURSION_LIMIT_UNCAPPED
        )

    def test_the_backstop_is_far_above_the_named_tiers(self):
        assert (
            settings.AGENT_RECURSION_LIMIT_UNCAPPED
            > settings.AGENT_RECURSION_LIMIT_THOROUGH
        )

    def test_a_client_that_sends_nothing_is_still_capped(self):
        """Absence of metadata is not a request to run unbounded: a plain
        OpenAI-compatible client never asked for one and must not get one."""
        assert chat_router._resolve_recursion_limit(None) == settings.AGENT_RECURSION_LIMIT
        assert chat_router._resolve_recursion_limit({}) == settings.AGENT_RECURSION_LIMIT


class TestResolveLayoutDirection:
    def test_missing_metadata_defaults(self):
        assert chat_router._resolve_layout_direction(None) == DEFAULT_LAYOUT_DIRECTION

    def test_missing_key_defaults(self):
        assert chat_router._resolve_layout_direction({}) == DEFAULT_LAYOUT_DIRECTION

    def test_unknown_value_defaults(self):
        assert (
            chat_router._resolve_layout_direction({"layout_direction": "sideways"})
            == DEFAULT_LAYOUT_DIRECTION
        )

    def test_lr_is_honored(self):
        assert chat_router._resolve_layout_direction({"layout_direction": "LR"}) == "LR"

    def test_tb_is_honored(self):
        assert chat_router._resolve_layout_direction({"layout_direction": "TB"}) == "TB"

    def test_the_values_are_the_layout_engine_own_tokens(self):
        """No translation layer between the toggle and Sugiyama: whatever
        this returns is passed to set_layout_direction unchanged, which
        validates against exactly these two."""
        from src.services.petri.builder import PetriNetBuilder

        builder = PetriNetBuilder()
        for value in ("LR", "TB"):
            builder.set_layout_direction(
                chat_router._resolve_layout_direction({"layout_direction": value})
            )
            assert builder.layout_direction == value
