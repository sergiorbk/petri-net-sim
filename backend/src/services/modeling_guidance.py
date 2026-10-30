"""Combine shared modeling knowledge with this application's tool bindings."""

from pathlib import Path

from petri_modeling_skills import modeling_guidance


def api_adapter() -> str:
    return (Path(__file__).parent / "agent" / "prompts" / "petri_api_adapter.md").read_text(encoding="utf-8")


def modeling_prompt() -> str:
    return f"{modeling_guidance()}\n\n{api_adapter()}"
