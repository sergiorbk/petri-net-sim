"""Unit tests for src/services/petri/agent_toolkit/errors.py.

The shared error envelope: ValueError/KeyError raised inside an operation
become a typed ToolError carrying "Error: <message>" text; anything else
propagates unchanged, since it's a bug rather than recognized bad input.
"""

from __future__ import annotations

import pytest

from src.services.petri.agent_toolkit.errors import ToolError, tool_operation


class TestToolError:
    def test_str_returns_message(self):
        err = ToolError("Error: Place 'p1' not found")
        assert str(err) == "Error: Place 'p1' not found"

    def test_is_frozen(self):
        err = ToolError("Error: boom")
        with pytest.raises(AttributeError):
            err.message = "changed"  # type: ignore[misc]

    def test_equality_by_value(self):
        assert ToolError("Error: x") == ToolError("Error: x")
        assert ToolError("Error: x") != ToolError("Error: y")


class TestToolOperationDecorator:
    def test_success_passes_through_unchanged(self):
        @tool_operation
        def op(x: int) -> str:
            return f"ok {x}"

        assert op(5) == "ok 5"

    def test_value_error_becomes_tool_error(self):
        @tool_operation
        def op() -> str:
            raise ValueError("Place 'p1' not found")

        result = op()
        assert isinstance(result, ToolError)
        assert result.message == "Error: Place 'p1' not found"

    def test_key_error_becomes_tool_error(self):
        @tool_operation
        def op() -> str:
            raise KeyError("missing")

        result = op()
        assert isinstance(result, ToolError)
        assert result.message.startswith("Error: ")

    def test_unexpected_exception_propagates(self):
        @tool_operation
        def op() -> str:
            raise RuntimeError("this is a bug, not bad input")

        with pytest.raises(RuntimeError, match="this is a bug"):
            op()

    def test_type_error_propagates(self):
        """A caller-side programming error (e.g. wrong kwarg) is not a ToolError."""
        @tool_operation
        def op(x: int) -> str:
            return str(x)

        with pytest.raises(TypeError):
            op(unexpected_kwarg=1)  # type: ignore[call-arg]

    def test_preserves_function_metadata(self):
        @tool_operation
        def op_named(x: int) -> str:
            """A docstring."""
            return str(x)

        assert op_named.__name__ == "op_named"
        assert op_named.__doc__ == "A docstring."

    def test_signature_is_introspectable_through_wrapper(self):
        """inspect.signature must see the ORIGINAL params, not (*args, **kwargs).

        catalog.py's _spec_from_operation relies on this to build each
        ToolSpec's param list straight from the decorated function.
        """
        import inspect

        @tool_operation
        def op(session, name: str, tokens: int = 0) -> str:
            return name

        sig = inspect.signature(op)
        assert list(sig.parameters) == ["session", "name", "tokens"]
        assert sig.parameters["tokens"].default == 0

    def test_passes_through_kwargs_and_args(self):
        @tool_operation
        def op(a, b, *, c=3) -> str:
            return f"{a}-{b}-{c}"

        assert op(1, 2, c=9) == "1-2-9"
