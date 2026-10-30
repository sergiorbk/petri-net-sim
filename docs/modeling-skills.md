# Shared modeling skills

The modeling rules, pattern explanations and PNML guidance come from
[petri-modeling-skills](https://github.com/sergiorbk/petri-modeling-skills).
The submodule at `backend/vendor/petri-modeling-skills` pins the same source
that the Swing editor uses. Common knowledge is maintained there, not copied
into application prompts. The local `petri_api_adapter.md` only describes this
application's tools and parameters.

After cloning, run `git submodule update --init --recursive` before `uv sync`
in `backend/`. CI and Docker builds include the pinned package. No network
request is needed to read skills while the application runs.

To update, fetch the chosen shared commit in the submodule, check it out,
run `uv lock` and `uv sync --frozen --extra dev` in `backend/`, then run the
modeling integration tests. Commit the submodule pointer and lockfile together.
Coordinate the shared revision with the Swing editor.

Chat prompts load the common guides followed by the local tool bindings.
MCP clients can discover the same guides through `resources/list`, read them
with `resources/read`, or use the task prompts. The guides do not add tools
or grant permission to edit a model.

## Live application check

Build the frontend with `npm --prefix frontend run build` from the repository
root, then run `uv run python scripts/smoke_mcp_workflow.py` from `backend/`.
The script starts the real `main:app` process with the built frontend and a
temporary PostgreSQL Docker container. It uses HTTP MCP to build a finite net,
simulate it, export a PNML file, clear the model, import the file and simulate
again. Both runs must finish with exactly six completed tokens. It also reads
the shared guides and verifies that PostgreSQL checkpointing initialized.

The script prints the evidence directory containing the MCP transcript, saved
PNML files, logs and result summary. `--output PATH` selects that directory.
The temporary API key, application process and database container are cleaned
up when the check ends. No LLM key or existing database is used.

Place roles such as `throughput` are saved in the producer's optional
`toolspecific/semanticTag` element. Both Python and browser PNML readers and
writers preserve the role so reopening a model retains throughput statistics.
