"""Composed Petri-object model — multiple named objects linked by shared
places and cross-object arcs. Deliberately not named "PetriObject", which
already names an unrelated reusable-subnet-template catalog elsewhere in
this codebase (src/infrastructure/postgres/models/petri_object.py)."""

from .link import ComposedLink, LinkType, PLACE_TO_TRANSITION_RETIRED_REASON
from .model import ComposedModel
from .model_object import ModelObject

__all__ = [
    "ComposedModel",
    "ModelObject",
    "ComposedLink",
    "LinkType",
    "PLACE_TO_TRANSITION_RETIRED_REASON",
]
