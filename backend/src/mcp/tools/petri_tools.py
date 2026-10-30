"""MCP tools for building Petri Net models.

Every tool here is generated from the shared agent_toolkit catalog
(src/services/petri/agent_toolkit/catalog.py). This module owns only the
FastMCP-specific plumbing: resolving a PetriNetSession from ctx, calling
the catalog's op_* function, and rendering the str | ToolError result as
plain text -- a ToolError's "Error: ..." message becomes the tool's text
result with isError left False, the same soft-failure convention every
hand-written MCP tool used before this module was generated from the
catalog. No tool business logic lives here anymore; see
agent_toolkit/operations.py for that.
"""

from __future__ import annotations

import inspect
from typing import Callable, FrozenSet

from mcp.server.fastmcp import Context, FastMCP

from src.services.petri.agent_toolkit import ToolError, ToolSpec, build_catalog, effective_type
from src.services.petri.session import PetriNetSession


def _session_id(ctx: Context) -> str:
    return str(id(ctx.session)) if ctx.session else "default"


async def _get_session(ctx: Context) -> PetriNetSession:
    """Get or create PetriNetSession for the current MCP session."""
    store = ctx.request_context.lifespan_context.session_store
    return await store.get_or_create(_session_id(ctx))


async def _save_session(ctx: Context, session: PetriNetSession) -> None:
    """Persist session state (no-op for the in-memory store)."""
    store = ctx.request_context.lifespan_context.session_store
    await store.save(_session_id(ctx), session)


def _build_tool_fn(spec: ToolSpec) -> Callable:
    """Build one FastMCP tool function from a catalog ToolSpec.

    The returned closure resolves the session from ctx, calls
    spec.operation(session, **kwargs), persists the session, and returns
    the operation's result as plain text. This is the single replacement
    for the old hand-written `async def add_x(ctx, ...)` tool bodies and
    for `_make_mcp_tool`'s auto-generated closure: both now go through the
    catalog instead of duplicating operation logic here.
    """
    params = [
        inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context),
    ]
    for p in spec.params:
        params.append(inspect.Parameter(
            p.name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=effective_type(p),
            default=p.default,
        ))

    async def _impl(**kwargs):
        ctx = kwargs.pop("ctx")
        session = await _get_session(ctx)
        # Defense in depth against a hallucinated parameter name: FastMCP's
        # own arg model already validates against this same signature for a
        # real MCP client, but this function is also called directly (e.g.
        # test doubles) with arbitrary kwargs, and spec.operation(session,
        # **kwargs) would otherwise hard-fail with a TypeError naming the
        # internal op_* function instead of a clean tool result.
        known, dropped = spec.filter_kwargs(kwargs)
        if spec.name in {"export_training_data", "export_image", "export_training_review", "training_bundle_image", "open_training_bundle", "inspect_training_bundle", "compare_training_revisions", "run_training_simulation"}:
            from starlette.concurrency import run_in_threadpool
            result = await run_in_threadpool(spec.operation, session, **known)
        else:
            result = spec.operation(session, **known)
        if spec.name not in {"export_training_data", "export_image", "export_training_review", "training_bundle_image", "open_training_bundle", "inspect_training_bundle", "compare_training_revisions", "run_training_simulation"}:
            from src.services.training_export import sanitize, utc_now
            trace = getattr(session, "_export_tool_trace", [])
            trace.append(sanitize({"tool": spec.name, "arguments": known, "result": str(result),
                                   "timestamp": utc_now(), "origin": "application",
                                   "error": str(result) if isinstance(result, ToolError) else None}))
            # This ledger belongs only to this live MCP session and excludes
            # export payloads, credentials and protocol context.
            if len(trace) > 200:
                session._export_trace_truncated = True
            session._export_tool_trace = trace[-200:]
        await _save_session(ctx, session)
        text = str(result)
        if dropped and not isinstance(result, ToolError):
            text += f" Ignored unknown parameter(s): {', '.join(dropped)}."
        return text

    _impl.__signature__ = inspect.Signature(params, return_annotation=str)
    _impl.__annotations__ = {
        p.name: p.annotation
        for p in params
        if p.annotation is not inspect.Parameter.empty
    }
    _impl.__annotations__["return"] = str
    _impl.__name__ = spec.name
    _impl.__qualname__ = spec.name
    _impl.__doc__ = spec.description
    return _impl


#: Tool names registered by export_tools.py / simulation_tools.py instead
#: of register_petri_tools below -- defined here once so all three modules
#: agree on the split without hand-maintaining three copies of the list.
EXPORT_TOOL_NAMES: FrozenSet[str] = frozenset({"optimize_network", "export_pnml"})
SIMULATION_TOOL_NAMES: FrozenSet[str] = frozenset({"run_simulation", "get_simulation_results"})


def register_catalog_tools(mcp: FastMCP, names: FrozenSet[str]) -> None:
    """Register every catalog tool whose name is in *names* on *mcp*."""
    catalog = build_catalog()
    for name in names:
        mcp.tool()(_build_tool_fn(catalog[name]))


def register_petri_tools(mcp: FastMCP) -> None:
    """Register every catalog tool except the export/simulation ones.

    Those register themselves via register_export_tools /
    register_simulation_tools in the sibling modules, keeping the
    module-level registration split the existing tests rely on.
    """
    catalog = build_catalog()
    names = frozenset(catalog) - EXPORT_TOOL_NAMES - SIMULATION_TOOL_NAMES
    register_catalog_tools(mcp, names)
