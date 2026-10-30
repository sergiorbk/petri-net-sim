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
