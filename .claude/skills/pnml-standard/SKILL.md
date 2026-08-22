---
name: pnml-standard
description: Where the ISO/IEC 15909-2 PNML grammar lives in this repo and how exported documents are held to it. Use before changing anything about the shape of a PNML document, adding an element or attribute, touching the exporters, importer or golden fixtures, or when a conformance or schema test fails.
---

# PNML and the ISO/IEC 15909-2 standard

PNML is not this project's private format. Exported documents are validated
against the real standard grammar, and composed models are read by another
tool. Both of those make the document shape a contract, not a detail.

## The grammar files

Vendored from the pnml.org reference schema, under `backend/tests/schema/`:

| File | What it is |
|------|------------|
| `ptnet.pntd` | The Place/Transition net type. Start here: everything else is pulled in from it |
| `pnmlcoremodel.rng` | The core model: `<pnml>`, `<net>`, `<page>`, nodes, arcs, labels |
| `conventions.rng` | Label conventions and the shared value types |
| `anyElement.rng` | The escape hatch that lets `<toolspecific>` hold anything |

They are RELAX NG, they carry their own copyright, and they are test fixtures
rather than shipped code. Read them before inventing an element: the content
model for arcs, for example, allows no child besides an optional
`<inscription>`, which is why non-normal arc types live in `<toolspecific>`
and nowhere else.

## Where the code is

| Path | Role |
|------|------|
| `backend/src/services/petri/exporter/pnml_exporter.py` | Flat nets, one `<page>` |
| `backend/src/services/petri/exporter/composed_pnml_exporter.py` | Composed Petri-object models, version "2.1". Its module docstring is the normative note on reference nodes and on what petri-server actually parses |
| `backend/src/services/petri/exporter/composed_document.py` | Resolves links into `<referencePlace>` and `<referenceTransition>` |
| `backend/src/services/petri/exporter/invariants.py` | Cheap document-wide checks run at export time |
| `backend/src/services/petri/importer/pnml_importer.py` | Reading documents back, including other tools' |
| `frontend/src/lib/pnml-export.ts`, `pnml-import.ts` | The browser's own copy of the same contract |

Both halves write PNML. A change to the shape usually belongs in both.

## How conformance is enforced

`backend/tests/test_pnml_rng_conformance.py` validates real exporter output
against `ptnet.pntd` with `lxml.etree.RelaxNG`: a rich flat net, a rich
composed model, the backend golden fixture, and the frontend's copy of it.

A schema can only describe one element's content model. It cannot say "every
id is unique" or "an arc's endpoints are on its own page", so that module also
asserts the document-wide rules the grammar cannot express. Add a rule there
when you add a document-wide guarantee.

Neighbouring suites: `test_pnml_invariants.py`, `test_composed_pnml_exporter.py`,
`test_pnml_importer.py`, `test_pnml_importer_fixtures.py`, `test_pnml_parse_api.py`.

## The golden fixtures

Two copies of the same document, one per half:

```
backend/tests/fixtures/composed_conformant_v21.pnml
frontend/src/lib/__fixtures__/composed_conformant_v21.pnml
```

They are generated, not hand-edited, by the real exporters:

```bash
uv run python backend/scripts/bump_version.py --help   # regenerates both as part of a bump
npx tsx frontend/scripts/regenerate-composed-fixture.ts
```

If a change alters the document shape, regenerate both and read the diff. A
fixture diff you cannot explain is a contract change you did not intend.

## Rules that already cost someone time

- **The wire carries no toolspecific coordinates.** Positions belong in
  `<graphics>`.
- **`placeToTransition` links are refused,** not projected. PetriObjModelPaint
  retired that link type, so the exporter raises rather than write something
  the other side would misread.
- **`<petriObjectLinks>` is a courtesy, not a source of truth.** It exists for
  readers without reference-node support. A conformant reader uses the
  reference nodes.
- **petri-server matches `<toolspecific>` on `tool` alone, never on
  `version`.** That is why the version string can move without a lockstep
  deploy on the other side.
- **Each tool writes only its own toolspecific block.** Readers still accept
  the other's.

## When a conformance test fails

1. Read the RELAX NG error. It names the element and the content model it
   violated.
2. Open `ptnet.pntd` and follow its `<include>` to the rule.
3. Decide whether the document is wrong or the expectation is. The grammar is
   not wrong: it is the published standard.
4. If the shape genuinely had to change, regenerate both fixtures, update the
   semantic rules, and say in the commit what a reader on the other side will
   see differently.
