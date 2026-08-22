"""Shared helper behind the two /pnml GET download routes (sessions.py's
GET /sessions/{id}/pnml and nets.py's GET /nets/{id}/pnml).

Both a session's Petri net and a stored user net are exported the same
way: reconstruct a PetriNetSession from the stored net_data dict (this
alone is what picks the composed vs. flat dialect -- see
PetriNetSession.export_pnml/is_composed) and wrap the resulting XML in a
download response.
"""

from fastapi import Response

from src.api.shared.exceptions import BadRequestException
from src.services.petri.session import PetriNetSession


def _safe_filename_stem(name: str | None, fallback: str) -> str:
    """A Content-Disposition-safe filename stem: alphanumerics, '-', '_'
    only, never empty. A session/net title can contain quotes, slashes, or
    other characters that would otherwise corrupt the header or let a
    crafted title escape the intended attachment filename."""
    stem = "".join(c if (c.isalnum() or c in "-_") else "_" for c in (name or "").strip())
    stem = stem.strip("_")
    return stem or fallback


def net_data_pnml_response(net_data: dict, filename_stem: str) -> Response:
    """Export *net_data* to PNML XML and wrap it as a downloadable
    attachment response.

    Raises BadRequestException (400) for a model the exporter's own
    invariant checks refuse (an invalid or duplicate element id, a
    cross-page arc) instead of letting that ValueError escape as an
    unhandled 500 -- mirrors how simulate_composed.py's own export-time
    ValueError handling already treats the identical exception.
    """
    try:
        session = PetriNetSession.from_net_data(net_data or {})
        xml = session.export_pnml()
    except ValueError as exc:
        raise BadRequestException(
            "This net cannot be exported to PNML",
            details=[{"field": "model", "message": str(exc)}],
        ) from exc

    stem = _safe_filename_stem(filename_stem, "net")
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{stem}.pnml"'},
    )
