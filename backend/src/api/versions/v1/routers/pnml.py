"""Standalone PNML parse endpoint -- no session required.

Lets a caller (a chat/MCP client sanity-checking a file before importing
it, or a plain API integration) see what parse_pnml makes of a PNML
document without touching any session state. import_pnml (the
agent_toolkit catalog operation, available through MCP and chat) is the
one that actually loads a parsed document INTO a session; this route is
read-only, mirroring how the standalone POST /simulate endpoint runs
without a session while the session-scoped one does the same work
against stored state.
"""

from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field

from src.api.shared.exceptions import BadRequestException
from src.api.shared.rate_limit import rate_limit
from src.core.dependencies import get_current_user
from src.core.security_config import security_settings
from src.infrastructure.postgres.models.user import User
from src.services.petri.importer import parse_pnml

router = APIRouter(prefix="/pnml", tags=["pnml"])

# Per-credential rate limit, sharing the same "simulate" budget/scope as the
# standalone POST /simulate route (src/api/versions/v1/routers/simulate.py):
# parsing an arbitrary PNML document is comparable CPU/memory work to running
# one, submitted through the same kind of unauthenticated-content body, so it
# gets the same ceiling rather than its own separate, unbounded one.
_parse_rate_limit = rate_limit(
    scope="simulate",
    max_requests=security_settings.RATE_LIMIT_SIMULATE_MAX,
    window_seconds=security_settings.RATE_LIMIT_SIMULATE_WINDOW,
    by="token",
)


class PnmlParseBody(BaseModel):
    """Request body for POST /pnml/parse."""

    xml: str = Field(description="Full PNML XML document text.")


@router.post(
    "/parse",
    summary="Parse a PNML document into net_data, without touching any session",
    dependencies=[Depends(_parse_rate_limit)],
)
async def parse_pnml_endpoint(
    body: PnmlParseBody = Body(...),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Parse *xml* (PNML, from PetriObjModelPaint or from this
    application's own export) into the frontend-shape net_data dict this
    application already reads and writes everywhere else, plus every
    non-fatal warning parse_pnml encountered along the way.

    Raises 400 for the two structural failures the reader cannot soft-fix
    around: a document with no <pnml> root, or a <pnml> with no <net>.
    Everything else it cannot make full sense of is downgraded to a
    warning in the response instead of failing the whole request.
    """
    try:
        net_data, warnings = parse_pnml(body.xml)
    except ValueError as exc:
        raise BadRequestException(str(exc)) from exc

    return {"net_data": net_data, "warnings": warnings}
