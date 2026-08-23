# CODEX.md

Read [AGENTS.md](AGENTS.md). It carries the project layout, the commands, and
the house rules for this repo, and it is the one file kept up to date.

Two things worth having in mind before the first edit:

- Backend commands run through `uv` from `backend/`; frontend commands through
  `npm` from `frontend/`. Both suites are fast enough to run in full.
- A change to a user-facing string touches both `en.json` and `uk.json`.
