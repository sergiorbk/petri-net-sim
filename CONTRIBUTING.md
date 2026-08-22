# Contributing to Petri Net Sim

Thanks for considering a contribution. See [AGENTS.md](AGENTS.md) for the
full layout, commands and house rules. This file covers the parts specific
to outside contributions.

## Before you start

- Bug or small fix: open a pull request directly.
- New feature or behavior change: open an issue first to discuss the
  approach before investing time in an implementation.

## License of contributions

This project is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).
By submitting a pull request you agree that your contribution is licensed
under the same terms.

## Development setup

```bash
# Backend, from backend/
uv sync --extra dev
uv run pytest

# Frontend, from frontend/
npm ci
npm run typecheck
npm run test:run
```

`make dev` runs the whole stack with hot reload. See [AGENTS.md](AGENTS.md)
for the full command reference and the project layout.

A few conventions worth knowing before your first PR:

- Commits are conventional-commit prefixed (`feat(scope): ...`,
  `fix(scope): ...`), narrative in the body.
- Every user-facing string is a key in both
  `frontend/src/i18n/locales/en.json` and `uk.json`, never a literal in a
  component.
- Comments explain why, not what the code already says.

## Pull requests

This project is trunk-based: `main` is the only long-lived branch.

- Branch off `main`, keep it short-lived (days, not weeks).
- Open a pull request into `main`. CI must pass.
- Delete the branch once it merges.

## Reporting bugs

Open a [bug report issue](.github/ISSUE_TEMPLATE/bug_report.yml) with steps
to reproduce, expected vs. actual behavior, and which part of the stack is
affected. For security-relevant bugs, see [SECURITY.md](SECURITY.md) instead
of opening a public issue.
