"""The tool identity a PNML document written here carries.

Every reader in this family selects a tool-specific block by its ``tool``
attribute alone. Neither this product's importer nor PetriObjModelPaint's
parser ever looks at ``version``, which states which release the vocabulary
belongs to rather than acting as a filter. That is what makes the readers'
CROSS-fallback safe: PetriObjModelPaint prefers its own block and falls back
to ours, this application prefers its own and falls back to PetriObjModelPaint's,
and neither filters on version, so a document written by only one of them
still opens fully in the other.

This writer states only its own identity, ``PetriNetSim``: mirroring the
other tool's block here (as this file used to) duplicated a payload the
reader-side fallback above already makes unnecessary, and it meant a document
in this family said the desktop's release number without the desktop ever
having produced it. PetriObjModelPaint's own writer mirrors this: it states
only ``PetriObjModel``, from its own pom.xml, and no longer knows this
application's version at all.

Mirrors ``TOOL_PETRI_NET_SIM`` in
``frontend/src/lib/pnml-export-composed.ts``, which also keeps
``TOOL_PETRI_OBJ_MODEL`` for its reader's fallback lookup; this backend never
parses a PNML document, so it has no reader-side use for that name and does
not carry it.
"""

TOOL_PETRI_NET_SIM = "PetriNetSim"

#: This product's own release. Must equal the version in
#: ``frontend/package.json``, which is where the web application states it;
#: ``test_composed_pnml_exporter`` reads that file and fails if the two drift.
PETRI_NET_SIM_VERSION = "1.3.0"

#: Rendered by the ``toolspecific`` template macro. A one-element tuple, kept
#: as a tuple (rather than a bare dict) so ``_toolspecific.pnml.j2``'s
#: ``{% for %}`` needs no special-casing now that there is only one identity.
TOOLSPECIFIC_IDENTITIES = ({"tool": TOOL_PETRI_NET_SIM, "version": PETRI_NET_SIM_VERSION},)
