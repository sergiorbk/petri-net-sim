"""A single named object inside a ComposedModel."""

from typing import List, Optional

from pydantic import BaseModel, Field

from src.domain.models import PetriNet


class ModelObject(BaseModel):
    """
    One Petri-object inside a composed model — an ordinary PetriNet plus the
    metadata petri-server's v2 PNML dialect attaches to a <page>: a canvas
    position, a firing priority, and (optionally) which template it was
    stamped from.

    `net` is a completely unmodified `PetriNet` — this class only wraps one,
    it never subclasses or monkeypatches it, so every existing PetriNet
    invariant/method keeps working exactly as it does for a standalone net.

    `width`/`height`/`collapsed`/`parent`/`auto_fit` mirror the web editor's
    object-canvas frame state (size, collapsed/expanded, nesting parent,
    whether the frame was hand-resized); the desktop writer never sets them.
    `free` marks an object the frontend has not placed on the canvas yet —
    the exporter drops its position/frame state entirely rather than write
    coordinates nobody chose (see `_build_object_doc`).
    """

    index: int = Field(..., ge=0)
    name: str
    priority: int = 0
    x: float = 0.0
    y: float = 0.0
    width: Optional[float] = None
    height: Optional[float] = None
    collapsed: bool = False
    parent: Optional[int] = None
    auto_fit: Optional[bool] = None
    free: bool = False
    net: PetriNet
    template_method: Optional[str] = None
    template_arguments: List[str] = Field(default_factory=list)
