# Contributing

Thanks for contributing to workjournal.

## Branching

- Use `develop` for integration work.
- Keep `main` as stable sync branch.
- Create feature branches from `develop`.

## Local Setup

1. Create a virtual environment.
2. Copy `.env.example` to `.env` and fill credentials locally.
3. Never commit local secrets or personal data.

## Data Safety Rules

- Do not commit `.env`.
- Do not commit `cache/`, `compilation/`, raw incident exports, or transcript text.
- Remove or redact personal identifiers in any shared sample files.

## Change Workflow

1. Implement code/docs changes in a feature branch.
2. Run the relevant scripts locally to validate behavior.
3. Update `README.md` when commands or outputs change.
4. Merge to `develop`, then sync `main`.

## Commit Guidelines

- Keep commit messages imperative and concise.
- Prefer small, focused commits.
- Include documentation changes with behavior changes.
