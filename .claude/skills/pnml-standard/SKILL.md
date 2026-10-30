---
name: pnml-standard
description: Where the ISO/IEC 15909-2 PNML grammar lives in this repo and how exported documents are held to it. Use before changing anything about the shape of a PNML document, adding an element or attribute, touching the exporters, importer or golden fixtures, or when a conformance or schema test fails.
---

# PNML conformance in this application

Read the installed shared PNML guide for common document rules. From `backend/`:

```bash
uv run python -c "from petri_modeling_skills import read_resource; print(read_resource('petri://skills/pnml-standard'))"
```

The normal dependency installation supplies this package; no submodule is needed.

Repository-specific entry points:

- `backend/tests/schema/ptnet.pntd` and included RELAX NG files are the vendored
  standard grammar used by `backend/tests/test_pnml_rng_conformance.py`.
- Exporters live in `backend/src/services/petri/exporter/`; the composed
  exporter documents Petri-object reference-node handling.
- The browser has its own `frontend/src/lib/pnml-export.ts` and `pnml-import.ts`.
  Update both implementations when the exchanged document changes.
- Golden fixtures are `backend/tests/fixtures/composed_conformant_v21.pnml`
  and `frontend/src/lib/__fixtures__/composed_conformant_v21.pnml`. Regenerate
  them through the existing version scripts, then inspect the diff.

Run conformance, importer, exporter and invariant tests for any document-format
change. Keep the grammar fixtures and their copyright notices intact.
