# Contributing

## Branching (GitHub Flow)

- `main` is protected and always deployable. **No direct pushes.**
- Branch off `main` per task: `feat/…`, `fix/…`, `chore/…`.
- Open a PR, fill in the template, get CI green + one review, then squash-merge.

## Branch protection (set once in repo Settings → Branches)

- Require a pull request before merging (1 approval).
- Require status checks to pass: `backend`, `agent`, `frontend`.
- Require branches to be up to date before merging.
- Do not allow direct pushes to `main`.

## Commits

Conventional style is encouraged: `feat(backend): add role endpoint`.

## Before pushing

```bash
make lint
make test
pre-commit run --all-files   # optional but recommended
```
