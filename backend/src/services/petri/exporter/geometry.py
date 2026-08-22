"""Node footprint constants and rounding shared by every PNML export template.

On the wire, a node's `<position>`/`<coordinates>` is its CENTER; this app's
own domain model (`Place.graphics`/`Transition.graphics`) stores TOP-LEFT,
because that is what React Flow wants on the frontend. The conversion happens
at the export boundary, here, by adding half the node's own footprint before
rounding.

Mirrors `frontend/src/lib/petri-geometry.ts` (`PLACE_W`/`PLACE_H`/`TRANS_W`/
`TRANS_H`): both writers in this family have to agree on where a node's
center actually is, so keep the two files in sync if either changes.
"""

import math

PLACE_W = 56
PLACE_H = 56
TRANS_W = 28
TRANS_H = 64

#: Frame-geometry constants, mirrored from `frontend/src/lib/petri-geometry.ts`
#: (FRAME_HEADER_H / NODE_LABEL_H / FRAME_PADDING / FRAME_MIN_W / FRAME_MIN_H).
#: Used only by `services/petri/composed_convert.py`'s bounds auto-derivation
#: (an object frame whose x/y/width/height were never set explicitly gets a
#: box that clears its current members), the session-side analog of the
#: frontend's own `frameBoundsFor`/`refitFrame`. Keep both files in sync.
FRAME_HEADER_H = 28
NODE_LABEL_H = 26
FRAME_PADDING = 28
FRAME_MIN_W = 160
FRAME_MIN_H = 100


def round_half_up(v: float) -> int:
    """Round to the nearest integer, ties rounding up, matching JavaScript's
    `Math.round`.

    Python's builtin `round()` rounds half-to-even (banker's rounding) and
    Jinja's `|int` filter truncates toward zero, neither agrees with
    `Math.round` at a `.5` boundary, and the frontend exporter (`pnml-export.ts`
    / `pnml-export-composed.ts`) uses `Math.round` for every coordinate it
    writes. Both writers have to land on the identical integer for the
    identical input, so every coordinate site in every template goes through
    this helper (registered as the `round_half_up` Jinja filter) instead of
    `|int` or `round()`. Correct for the non-negative coordinate ranges this
    application actually produces; not a general-purpose round-half-up for
    arbitrary negative floats.
    """
    return int(math.floor(v + 0.5))
