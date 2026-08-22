"""Cross-object link entity for composed Petri-object models."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class LinkType(str, Enum):
    """How two objects' elements are wired together.

    Names match petri-server's v2 wire format exactly (see
    docs/petri-object-models.md and PnmlModelParser in PetriObjModelPaint).
    """

    PLACE_FUSION = "placeFusion"
    TRANSITION_TO_PLACE = "transitionToPlace"
    PLACE_TO_TRANSITION = "placeToTransition"


#: Single source for the retirement wording every site that refuses a
#: placeToTransition link reuses verbatim: composed_document.py's own
#: export-time backstop (build_document_model, "Link {index} is a
#: {this}") and agent_toolkit/operations.py's create-time refusal
#: (link_objects, "Cannot create a {this}") both format this same string
#: into their own sentence rather than keeping their own independent copy
#: -- the two had drifted out of sync before this constant existed, one of
#: them silently no longer matching the other despite a comment claiming
#: they did.
PLACE_TO_TRANSITION_RETIRED_REASON = (
    "placeToTransition link, which PetriObjModelPaint retired: express the "
    "connection as a place fusion with a local read arc instead."
)


class ComposedLink(BaseModel):
    """
    A single link between two objects of a ComposedModel.

    Endpoints are addressed by (object index, element index) rather than by
    element id — element indices are positions in the target object's own
    places[]/transitions[] arrays, matching how petri-server's PNML exporter
    and parser both address them.

    - placeFusion: source_element and target_element are both place indices;
      the two places are treated as one shared token pool.
    - transitionToPlace: source_element is a transition index (the object
      that fires), target_element is a place index (where it delivers a
      token) — lets a transition produce into another object without owning
      a local output place of its own.
    - placeToTransition: source_element is a place index, target_element is
      a transition index — extends that transition's firing condition with
      an external input. `informational` makes it a test (non-consuming)
      input; only meaningful for this link type.
    """

    type: LinkType
    source_object: int = Field(..., ge=0)
    source_element: int = Field(..., ge=0)
    target_object: int = Field(..., ge=0)
    target_element: int = Field(..., ge=0)
    quantity: int = Field(default=1, ge=1)
    informational: bool = False

    @model_validator(mode="after")
    def _check_informational_scope(self) -> "ComposedLink":
        if self.informational and self.type != LinkType.PLACE_TO_TRANSITION:
            raise ValueError("informational is only valid for placeToTransition links")
        return self
