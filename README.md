# code-quality-bot

Reusable GitHub Actions workflow that reviews pull requests in .NET repos:

1. **Analyzers:** `dotnet build` with warnings treated as errors and code-style
   enforcement. Any error fails the check.
2. **Claude review:** `anthropics/claude-code-action` reads the diff, posts
   inline comments and a summary, and returns structured findings.
3. **Gate:** fails on analyzer errors, or on any `high` Claude finding unless
   the PR has the `review-override` label. The label never clears analyzer
   errors.

Each run uploads a `findings` artifact (`findings.json`) for the future
quality dashboard.

## Add it to a repo

1. Install the Claude GitHub App on the project repo: run `/install-github-app`
   in Claude Code, or install it from
   [github.com/apps/claude](https://github.com/apps/claude). Note that
   `code-quality-bot` itself must stay **public** — the reusable workflow
   checks it out, and a caller repo's token can't read a private repo.
2. Copy [`examples/code-review.yml`](examples/code-review.yml) to
   `.github/workflows/code-review.yml` and set `solution`. Keep its job-level
   `if:` and `concurrency:` — they stop unrelated label changes from creating
   a skipped (and therefore passing) gate check. If you change
   `override_label` from its default, update the caller's hard-coded
   `'review-override'` in that job `if:` to match.
3. Add a repo secret: `CLAUDE_CODE_OAUTH_TOKEN` (run `claude setup-token`) or
   `ANTHROPIC_API_KEY`.
4. Create a `review-override` label.
5. After the first green run, make **review / gate** a required status check
   in branch protection.

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `solution` | (required) | `.sln` to build |
| `dotnet_version` | `10.0.x` | SDK for `actions/setup-dotnet` |
| `exclude_paths` | bin/obj/generated/lock files | Globs Claude ignores |
| `max_diff_lines` | `2000` | Above this, summary-only review |
| `override_label` | `review-override` | Label that clears Claude blocks |
| `bot_ref` | `omega` | Ref of this repo to load prompt/scripts from |

`bot_ref` must equal the ref used in the caller's `uses:
jasonblacksmith/code-quality-bot/.github/workflows/review.yml@<ref>` line —
the two are loaded independently by GitHub Actions, so a mismatch silently
mixes workflow logic from one ref with prompt/scripts from another.

## Limits

- The Claude gate is advisory, not a security boundary, against a malicious
  PR author: diff content the model reads can attempt to steer its own
  review. The .NET analyzer checks still enforce independently of anything
  Claude reports.
- `-warnaserror` also promotes NuGet audit warnings (`NU190x`) to build
  errors, so a newly published CVE in a dependency can fail unrelated PRs
  until the dependency is updated or the advisory is suppressed.

## Develop

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
.venv/Scripts/actionlint
```

Design: [`docs/superpowers/specs/2026-09-24-pr-review-bot-design.md`](docs/superpowers/specs/2026-09-24-pr-review-bot-design.md)
