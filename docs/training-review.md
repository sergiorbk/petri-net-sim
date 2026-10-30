# Training archives and iterative review

The web application and PetriObjModelPaint 2.5.0 exchange the same portable
training ZIP. Open one using **File > Import**, **Review > Open training ZIP**,
Ctrl+O, or drop it on the editor. The archive is validated before replacing the
document. Imported profiles never replace your own contributor profile.

## Create, review and return

1. Build or correct the model on the normal editor canvas.
2. Use **AI > Export training data**. Add the task if available and download the
   ZIP. Return to the main canvas first when editing an object's own canvas.
3. The reviewer opens that ZIP and chooses **Review > Review saved network**.
4. Click an element with **Add finding**, or drag an area with **Mark an area**.
   The finding form opens immediately. **Inspect parameters** provides read-only
   model inputs. The canvas reuses the editor's graph builder and node/edge
   components; panning, zoom and object expansion do not edit the saved evidence.
5. Select a decision and write a summary. **Save reviewed ZIP** downloads the
   archive with a new revision and review. Pass it back for corrections, export
   again, and continue the same history in either application.

The workspace fills the browser by default and can be restored to a smaller
dialog. **History** lists previous reviews and compares two saved versions on
independent canvases. Comparison reports observed additions/removals and parameter
changes; it does not prove behavioral equivalence. Findings lock their target
version until removed. Reviewing an older revision never approves later edits.

## Simulation evidence

Before saving a review, automatic simulation defaults to horizons 100, 1000 and
10000 on fresh copies of the exact reviewed PNML. Configure horizons and sampling
interval in **Simulation**. Disabling automatic runs requires a nonblank reason.
At least an attempt or a reason is required; failed attempts are retained.

**Run selected version** collects another attempt and provides sample playback,
stepping and a monitor chart for any recorded place or transition. Place values
are tokens and transition values are active channels. Samples use the post-event
state, held constant between events, in model time. Automatic and manual review
runs are appended to the review. These review runs use the built-in Python engine
even when the ordinary simulator is configured for a remote engine.

Each attempt records its source PNML hash, settings, timestamp, elapsed time,
status/error, initial/final states and statistics, and trajectory. Runs are bounded
by 10000 event steps and four seconds; an input-loop guard also prevents runaway
channel creation. Sampling adapts to at most 20001 rows and about one million
scalar cells. Incomplete runs say so. Seeds are unavailable, so stochastic runs
are not claimed to reproduce exactly. A completed run is execution evidence,
not an assertion that the model satisfies its task.

## What stays in the ZIP

The shared `training-bundle` 1.1 and `training-history` 1.0 schemas define the
format. Older 1.0 snapshots without history can be opened and acquire history on
the next export. Every export captures a version, rather than every mouse action.

- PNML, task context, explicitly supplied conversation and observed tool calls.
- A complete expanded overview, a separate image of every object subtree at
  every depth, matching geometry, a view index and full model parameter tables.
- `dataset-history.json`, with a persistent bundle ID and revision/review chains.
- `history/revisions/<hash>/`, containing every previous snapshot and manifest.
- `history/reviews/<hash>.json`, with attribution, decision, findings, reviewed
  revision, result revision and available simulation evidence.

Imported history files remain byte-for-byte unchanged. The root manifest hashes
every payload; hashes detect corruption, not identity or reviewer authenticity.
Region annotations bind saved-image pixel coordinates to the exact image hash.
Geometry remains unverified until explicitly curated as training labels. External
clients' private conversations cannot be recovered by the application.

Filenames include counters such as `queue-r005-review003-<UTC timestamp>.zip`.
Renaming does not change lineage. The archive stays in browser memory during the
session and in downloaded ZIPs; save/download it before reloading or leaving the
editor. The server does not keep uploaded archives in a global archive directory.
The `SECURITY_MAX_BODY_BYTES_TRAINING` setting caps training and MCP requests
(including base64 overhead, 358000000 bytes by default). Reverse proxies must
allow the same upload size. Limits match the desktop: 10000 entries, 64 MiB per file, 256 MiB uncompressed.
Paths, duplicate entries, manifests, checksums and chains are checked without
extracting uploaded files. Rejected imports leave the document intact.

Set nickname, organization, study group and optional contacts under **Settings >
Profile > Contributor profile**. The account keeps a stable generated two-word
nickname until changed. The UI attributes reviews as human; agents declare
themselves through MCP. Exported contacts are part of the portable archive.

## MCP and HTTP

Read the installed `petri-training-review` shared guide and application bindings,
or use the `review_petri_model` MCP prompt.

| Tool | Purpose |
| --- | --- |
| `open_training_bundle` | Validate/load real `archive_base64`; replacing a model requires `replace_current=true` |
| `inspect_training_bundle` | Read saved context, revisions, reviews, geometry and view IDs |
| `training_bundle_image` | Download a saved view of a selected revision |
| `compare_training_revisions` | Compare saved left/right revision IDs |
| `run_training_simulation` | Record a bounded saved-version run and trajectory |
| `export_training_review` | Append a review and return filename, MIME type and base64 ZIP bytes |
| `export_training_data` | Capture a new snapshot while retaining the loaded archive |

Reviews accept `reviewer`, `reviewer_kind`, `decision`, `comment`, `findings`,
optional `revision_id`, `simulation_horizons`, `sampling_interval` and
`skip_simulation_reason`. Use actual geometry IDs, not assumed PNML IDs, for
findings. Omit the target or use `head` for the loaded version, `current` for the
new capture, or a saved hash. Decisions are `accepted`, `changes_requested` and
`rejected`. Never label agent feedback as a human review.

The same operations back authenticated `/api/v1/training/inspect`, `/compare`,
`/image`, `/run` and `/export`. The browser export endpoint derives human reviewer
attribution from the authenticated profile. Other users' archives are not exposed
by a server-side archive ID. Standard account/MCP integration switches still apply.

## Standalone image export

**File > Export > PNG** also offers ZIP output, complete/current canvas, object
subtrees or selected elements with internal arcs. Choose objects, overview,
parameter table, scale (up to 4), transparency and maximum dimension (up to 8192).
Multiple views require ZIP and include `images.json` geometry. At most 24 million
pixels are rendered per image. The renderer preserves model coordinates; it is
a model illustration, not a browser screenshot.

MCP `export_image` accepts the matching `options` object: `scope`, `format`,
`object_indices`, `element_ids`, `include_overview`, `include_parameters`, `scale`,
`transparent_background` and `max_dimension`.
