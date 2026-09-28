# CLAUDE.md

The Aurifex Mentis code scanner: a reusable GitHub Actions workflow that reviews pull requests
with .NET analyzers and Claude, then applies a merge Gate. It is house tooling with its own
lifecycle, governed from the Bench in `aurifex-mentis`.

## How it's used

- Project repos call `.github/workflows/review.yml@omega` and load `prompts/` and `scripts/`
  from `omega` on every run, so **any change merged to `omega` takes effect on the next pull
  request in every enrolled repo.** Treat merges here as deploys.
- `examples/code-review.yml` is the caller template. Keep its job-level `if:` and
  `concurrency:`; they stop unrelated label changes from creating a skipped gate check, which
  counts as passing.

## Commands

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest -q
.venv/Scripts/actionlint && .venv/Scripts/actionlint examples/code-review.yml
```

Run the tests and both lint commands before every commit. `tests/test_workflow_contract.py`
fails if `review.yml`, `prompts/review.md` and `scripts/gate.py` drift apart.

## Rules

- **Fail closed.** Any failure mode must fail the Gate; nothing passes silently.
- **Never interpolate PR-controlled text into a shell.** Pass values through `env:`.
- `prompts/review.md` uses `string.Template`, so a literal `$` must be written `$$`.
- Keep GitHub Actions on their latest major versions, and read the release notes before bumping.

## House conventions

Follows `CONVENTIONS.md` and `TERMS.md` in `aurifex-mentis`: default branch `omega`, prefixed
commits (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`, …), changes by pull request.
**superpowers leads**: its documents live in `docs/superpowers/` and keep its own words.
House Concepts and Blueprints go in `docs/concepts/` and `docs/blueprints/`, with
`process: superpowers | house | mixed` in their front matter.
