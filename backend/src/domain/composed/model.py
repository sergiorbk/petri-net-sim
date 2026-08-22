"""Composed Petri-object model aggregate."""

import re
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from src.domain.models import ArcType, PetriNet

from .link import ComposedLink, LinkType
from .model_object import ModelObject

#: Same ASCII under-approximation of the XML NCName grammar as
#: `services/petri/exporter/invariants.py`'s NCNAME_RE, duplicated rather
#: than imported: the domain layer must not depend on the export layer, and
#: this is the one place validate() needs it to report an id problem before
#: a model ever reaches an exporter.
_NCNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")


class ComposedModel(BaseModel):
    """
    Several named Petri-objects, each an ordinary PetriNet, wired together by
    links (shared places and/or cross-object arcs) — the Python-side
    counterpart to petri-server's v2 API and PNML dialect.

    Each object's own PetriNet is left completely unmodified: `add_object`
    does not call `PetriNet.validate_topology()`, because that check's
    "single connected component" and "every transition needs both a local
    input and a local output arc" rules are both wrong for an object
    designed to rely on cross-object links (docs/petri-object-models.md).
    `ComposedModel.validate()` below is the narrower, correct check for this
    context instead.
    """

    name: str = "ComposedModel"
    objects: List[ModelObject] = Field(default_factory=list)
    links: List[ComposedLink] = Field(default_factory=list)

    def add_object(
        self,
        net: PetriNet,
        name: Optional[str] = None,
        priority: int = 0,
        x: float = 0.0,
        y: float = 0.0,
        width: Optional[float] = None,
        height: Optional[float] = None,
        collapsed: bool = False,
        parent: Optional[int] = None,
        auto_fit: Optional[bool] = None,
        free: bool = False,
        template_method: Optional[str] = None,
        template_arguments: Optional[List[str]] = None,
    ) -> ModelObject:
        """Wrap an existing flat net as the next object in this model."""
        obj = ModelObject(
            index=len(self.objects),
            name=name or net.name,
            priority=priority,
            x=x,
            y=y,
            width=width,
            height=height,
            collapsed=collapsed,
            parent=parent,
            auto_fit=auto_fit,
            free=free,
            net=net,
            template_method=template_method,
            template_arguments=template_arguments or [],
        )
        self.objects.append(obj)
        return obj

    @classmethod
    def from_nets(
        cls, nets: List[Tuple[str, PetriNet]], name: str = "ComposedModel"
    ) -> "ComposedModel":
        """Convenience constructor: combine existing flat nets, no links yet."""
        model = cls(name=name)
        for obj_name, net in nets:
            model.add_object(net, name=obj_name)
        return model

    def add_link(
        self,
        link_type: LinkType,
        source_object: int,
        source_element: int,
        target_object: int,
        target_element: int,
        quantity: int = 1,
        informational: bool = False,
    ) -> ComposedLink:
        link = ComposedLink(
            type=link_type,
            source_object=source_object,
            source_element=source_element,
            target_object=target_object,
            target_element=target_element,
            quantity=quantity,
            informational=informational,
        )
        self.links.append(link)
        return link

    def get_object(self, index: int) -> ModelObject:
        for obj in self.objects:
            if obj.index == index:
                return obj
        raise ValueError(f"Composed model has no object at index {index}")

    def resolve_element_id(self, object_index: int, element_index: int, kind: str) -> str:
        """Position -> element id, within one object's own places/transitions.

        `kind` is "place" or "transition". Used by the exporter and tests;
        petri-server itself re-derives positions from document order on its
        own side, this is purely for round-tripping on the Python side.
        """
        obj = self.get_object(object_index)
        pool = obj.net.places if kind == "place" else obj.net.transitions
        if element_index >= len(pool):
            raise ValueError(
                f"Object {object_index} ('{obj.name}') has no {kind} at index {element_index}"
            )
        return pool[element_index].id

    def resolve_link_endpoint(self, link: ComposedLink, side: str) -> Tuple[str, str]:
        """Public (element id, kind) resolution for one side of a link.

        `side` is "source" or "target". Exists so external code, the
        composed PNML exporter, in particular, can place reference nodes
        and address `<link>` entries by id (ISO/IEC 15909-2 conformance, see
        docs/petri-object-models.md in the PetriObjModelPaint repository)
        without reaching into `_endpoint_kind`, which stays private because
        it is also an implementation detail of `_validate_link_endpoint`
        below.
        """
        obj_index = link.source_object if side == "source" else link.target_object
        el_index = link.source_element if side == "source" else link.target_element
        kind = self._endpoint_kind(link.type, side)
        return self.resolve_element_id(obj_index, el_index, kind), kind

    def validate(self) -> List[str]:
        """Structural validation appropriate to a composed model.

        Deliberately narrower than PetriNet.validate_topology(): does not
        require single connectivity or a local output arc per transition;
        both are legitimate to omit when an object relies on cross-object
        links (see class docstring). The one requirement kept mirrors the
        desktop engine's PetriNet.validateStructure(): every transition
        needs at least one input it actually CONSUMES from: a genuine,
        non-READ arc from a place IN ITS OWN OBJECT's net. This check only
        looks at each object's local arcs, never at links: a placeFusion
        place still satisfies it, because the fused place is itself one of
        the object's own places with an ordinary local arc into the
        transition; but no link, by itself, can stand in for that local
        arc. Read-only inputs (a local READ arc or an informational link)
        only test the marking and do not count, exactly like the desktop's
        hasConsumingInput().

        placeToTransition links are rejected outright (see _validate_link):
        PetriObjModelPaint retired the link type entirely, so there is no
        longer any mechanism for a transition to draw its sole consuming
        input from a link with no local arc of its own; a transition that
        would have relied on one now correctly reports "no consuming
        input" instead of silently passing validate() and only failing
        once simulation actually starts.

        Also reports every element id that is not a valid XML NCName: the
        exporter refuses these too (`assert_invariants`), but only once a
        simulation is already under way, and by then the message is either
        an opaque 500 (the /preview route, before that was fixed to catch
        it) or an SSE frame mislabeled "transport" instead of "model".
        Checking it here instead surfaces it at the one gate every composed
        request already passes through, worded in the model's own terms.
        """
        errors: List[str] = []

        if not self.objects:
            errors.append("Composed model has no objects")

        for obj in self.objects:
            for t in obj.net.transitions:
                has_consuming_local = any(
                    a.target_id == t.id and a.arc_type != ArcType.READ
                    for a in obj.net.arcs
                )
                if not has_consuming_local:
                    errors.append(
                        f"Object {obj.index} ('{obj.name}') transition "
                        f"'{t.name}' has no consuming input, neither a local "
                        f"arc nor an incoming link"
                    )
            errors.extend(self._check_element_ids(obj))

        for i, link in enumerate(self.links):
            errors.extend(self._validate_link(i, link))

        return errors

    def _validate_link(self, index: int, link: ComposedLink) -> List[str]:
        if link.type == LinkType.PLACE_TO_TRANSITION:
            return [
                f"Link {index}: placeToTransition links are not supported. "
                f"PetriObjModelPaint retired this link type — it gives a "
                f"transition a second, disconnected set of input places, "
                f"which contradicts what the transition's own arcs already "
                f"declare. Connect the place into the consuming object's "
                f"own net instead, wired with an ordinary or a read/test "
                f"arc, and share it there with a placeFusion."
            ]
        errors: List[str] = []
        errors.extend(self._validate_link_endpoint(index, link, "source"))
        errors.extend(self._validate_link_endpoint(index, link, "target"))
        return errors

    def _validate_link_endpoint(self, index: int, link: ComposedLink, side: str) -> List[str]:
        obj_index = link.source_object if side == "source" else link.target_object
        el_index = link.source_element if side == "source" else link.target_element

        matching_objects = [o for o in self.objects if o.index == obj_index]
        if not matching_objects:
            return [f"Link {index}: {side}_object {obj_index} does not exist"]
        obj = matching_objects[0]

        kind = self._endpoint_kind(link.type, side)
        pool = obj.net.places if kind == "place" else obj.net.transitions
        if el_index >= len(pool):
            return [
                f"Link {index}: {side}_element {el_index} is out of range for object "
                f"{obj_index} ('{obj.name}'), which has {len(pool)} {kind}(s)"
            ]
        # The endpoint resolves to a real element: name it by its own label,
        # not merely its position, and check the one thing that would still
        # sink this specific link even though it resolves (an id an
        # exporter cannot write). `_check_element_ids` below reports the same
        # problem for every element regardless of whether a link touches it;
        # this additionally ties it to which link and which side broke.
        element = pool[el_index]
        if not _NCNAME_RE.fullmatch(element.id):
            return [
                f"Link {index}: {side} {kind} '{element.name}' (element {el_index} of "
                f"object {obj_index} '{obj.name}') has id '{element.id}', which is not "
                f"a valid XML NCName"
            ]
        return []

    @staticmethod
    def _endpoint_kind(link_type: LinkType, side: str) -> str:
        """Whether a link's given side addresses a place or a transition."""
        if link_type == LinkType.PLACE_FUSION:
            return "place"
        if link_type == LinkType.TRANSITION_TO_PLACE:
            return "transition" if side == "source" else "place"
        # PLACE_TO_TRANSITION
        return "place" if side == "source" else "transition"

    @staticmethod
    def _check_element_ids(obj: ModelObject) -> List[str]:
        """Every place/transition/arc id in one object that is not a valid
        XML NCName, named by the object (index + name), the element kind,
        its visible name (an arc has none, so its own id doubles as its
        label) and the offending id itself.

        A model with a bad id used to pass validate() cleanly and only fail
        once export actually ran, differently depending on which of the
        local engine, the streaming route or /preview happened to handle the
        request (see `services/petri/exporter/invariants.py`, the export-
        time equivalent of this check).
        """
        errors: List[str] = []
        for p in obj.net.places:
            if not _NCNAME_RE.fullmatch(p.id):
                errors.append(
                    f"Object {obj.index} ('{obj.name}') place '{p.name}' has id "
                    f"'{p.id}', which is not a valid XML NCName"
                )
        for t in obj.net.transitions:
            if not _NCNAME_RE.fullmatch(t.id):
                errors.append(
                    f"Object {obj.index} ('{obj.name}') transition '{t.name}' has id "
                    f"'{t.id}', which is not a valid XML NCName"
                )
        for a in obj.net.arcs:
            if not _NCNAME_RE.fullmatch(a.id):
                errors.append(
                    f"Object {obj.index} ('{obj.name}') arc '{a.id}' has an id that "
                    f"is not a valid XML NCName"
                )
        return errors
