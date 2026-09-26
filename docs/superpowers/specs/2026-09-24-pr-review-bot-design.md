# PR Review Bot — Design

**Date:** 2026-09-24
**Status:** Draft, awaiting review
**Repo:** `jasonblacksmith/code-quality-bot` (new)
**Out of scope:** the quality dashboard (separate sub-project; consumes the `findings.json` artifacts this bot produces).

## Goal

Every pull request in `MudSlinger` and `infinite-dungeon` gets an automated review that combines deterministic .NET analyzer checks with a Claude review, posts inline comments, and blocks merging on serious problems — with a human override for Claude-originated blocks.

## Decisions

| Question | Decision |
|---|---|
| Delivery | GitHub Actions check on pull requests |
| Review engine | .NET analyzers **and** Claude |
| Blocking | Block on analyzer errors **or** Claude `high` findings; `review-override` label clears Claude blocks only |
| Hosting | One central repo with a reusable workflow; each project repo has a thin caller |
| Claude integration | `anthropics/claude-code-action@v1` |

## Repository layout

```
code-quality-bot/
├── .github/workflows/review.yml        reusable workflow (on: workflow_call)
├── prompts/review.md                   review instructions for Claude
├── schema/findings.schema.json         JSON Schema for Claude's structured output
├── scripts/gate.py                     pass/fail decision + writes findings.json
├── tests/                              pytest tests for gate.py + schema samples
└── docs/superpowers/specs/             this document
```

Each project repo adds `.github/workflows/code-review.yml`:

```yaml
name: Code review
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, labeled, unlabeled]
jobs:
  review:
    if: >-
      (github.event.action != 'labeled' && github.event.action != 'unlabeled') ||
      github.event.label.name == 'review-override'
    concurrency:
      group: code-review-${{ github.event.pull_request.number }}
      cancel-in-progress: true
    permissions:
      contents: read
      pull-requests: write
      id-token: write
    uses: jasonblacksmith/code-quality-bot/.github/workflows/review.yml@main
    with:
      solution: MudSlinger.sln
      exclude_paths: "**/bin/**,**/obj/**,**/*.g.cs,**/packages.lock.json"
    secrets: inherit
```

## Workflow inputs

| Input | Required | Default | Purpose |
|---|---|---|---|
| `solution` | yes | — | Path to the `.sln` to build |
| `dotnet_version` | no | `10.0.x` | Passed to `actions/setup-dotnet` |
| `exclude_paths` | no | bin/obj/generated/lock files | Globs Claude should ignore |
| `max_diff_lines` | no | `2000` | Above this, Claude does a summary-only review |
| `override_label` | no | `review-override` | Label that clears Claude blocks |

Secrets (via `secrets: inherit`): `CLAUDE_CODE_OAUTH_TOKEN` **or** `ANTHROPIC_API_KEY`. The workflow passes whichever is set to the action's `claude_code_oauth_token` / `anthropic_api_key` input.

## Flow

The reusable workflow has three jobs. All jobs skip for draft PRs. Irrelevant label events are filtered in the caller workflow's job `if:` (see caller example), never inside this workflow: a skipped `gate` would count as a passing required check and could override a failing one.

### Job 1 — `analyzers`

1. Checkout the PR merge ref (default for pull_request); `actions/setup-dotnet`.
2. `dotnet build <solution> -warnaserror -p:EnforceCodeStyleInBuild=true -p:AnalysisLevel=latest-recommended`, with the log saved to `build.log`.
3. Extract `: (warning|error) CODE:` lines from `build.log` into `analyzer-diagnostics.txt` (deduplicated) and upload it as an artifact regardless of outcome. SARIF isn't used because MSBuild's `ErrorLog` writes one file per build and projects overwrite each other.
4. The job fails if the build fails. The gate reads `needs.analyzers.result`.

### Job 2 — `claude` (needs: analyzers, runs even if analyzers failed)

Skipped when:
- the event is `labeled` and the label is `override_label` (override means Claude findings can't block, so re-running Claude is wasted cost), or
- no Claude secret is available (e.g. fork PRs). A job summary notice records "Claude review skipped: no credentials"; the gate treats this as *not reviewed* and passes on the Claude side only if the override label is present.

Otherwise:
1. Checkout the PR merge ref (default for pull_request) (fetch-depth 0) and checkout `code-quality-bot` into `.bot/` for the prompt and schema.
2. Download `analyzer-diagnostics.txt`.
3. Compute diff size; set `REVIEW_MODE=summary` if > `max_diff_lines`, else `inline`.
4. Run `anthropics/claude-code-action@v1` with:
   - `prompt`: contents of `.bot/prompts/review.md` with `REPO`, `PR_NUMBER`, `REVIEW_MODE`, `EXCLUDE_PATHS`, and the analyzer diagnostics path substituted.
   - `claude_args`:
     `--max-turns 30 --json-schema <contents of findings.schema.json> --allowedTools "Read,Grep,Glob,mcp__github_inline_comment__create_inline_comment,Bash(gh pr diff:*),Bash(gh pr view:*),Bash(gh pr comment:*)"`
   - `use_sticky_comment: true` (one summary comment, updated on each push).
   - `timeout-minutes: 10` on the job, with each Claude review step capped at `timeout-minutes: 4` so a hung attempt fails fast enough for the retry to still run within the job budget.
5. On failure, retry the step once (second step gated on `steps.claude1.outcome == 'failure'`).
6. Write the action's `structured_output` to `claude-findings.json` and upload as an artifact.

Using `--json-schema` means the findings come back as validated structured output from the action, not a file Claude has to remember to write.

### Job 3 — `gate` (needs: analyzers, claude; `if: always()`)

Runs `python .bot/scripts/gate.py` with: analyzer result, Claude job result (`success` / `failure` / `skipped`), path to `claude-findings.json` (may be absent), and whether the PR currently has `override_label`.

Decision table:

| Analyzers | Claude job | Findings | Override label | Result |
|---|---|---|---|---|
| failed | any | any | any | **fail** — "Analyzer errors (override does not apply)" |
| passed | success | no `high` | any | **pass** |
| passed | success | ≥1 `high` | absent | **fail** — lists the high findings |
| passed | success | ≥1 `high` | present | **pass** — "Overridden by label" |
| passed | failure / missing / invalid output | — | absent | **fail** — "Claude review didn't complete; re-run or add `review-override`" |
| passed | failure / missing / invalid output | — | present | **pass** — overridden |
| passed | skipped (override label event) | — | present | **pass** — overridden |
| passed | skipped (no credentials) | — | absent | **fail** — "Claude review not run" |
| passed | skipped (no credentials) | — | present | **pass** — overridden |

`gate.py` also writes the combined `findings.json` artifact (see schema below, plus `analyzers_passed`, `overridden`, `repo`, `pr`, `sha`, `timestamp`) for the future dashboard, and writes a Markdown table to `$GITHUB_STEP_SUMMARY`.

The `gate` job is the one to mark as a required status check in branch protection.

## Findings schema (`schema/findings.schema.json`)

```json
{
  "type": "object",
  "required": ["summary", "findings"],
  "properties": {
    "summary": { "type": "string" },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["file", "line", "severity", "category", "message"],
        "properties": {
          "file": { "type": "string" },
          "line": { "type": "integer", "minimum": 1 },
          "severity": { "enum": ["low", "medium", "high"] },
          "category": { "enum": ["bug", "security", "performance", "maintainability", "style", "test"] },
          "message": { "type": "string" },
          "suggestion": { "type": "string" }
        }
      }
    }
  }
}
```

## Review prompt (`prompts/review.md`) — requirements

- State repo, PR number, review mode, excluded paths.
- Read the diff with `gh pr diff`; read surrounding code with Read/Grep/Glob when needed.
- Read the `analyzer-diagnostics.txt` file and **do not repeat** anything the analyzers already reported.
- Before commenting, check existing review comments (`gh pr view --comments`) and don't duplicate them.
- Severity rubric (this is what drives blocking, so be explicit):
  - **high** — likely bug, data loss, security issue, crash, or broken public contract. Must cite the concrete failure scenario.
  - **medium** — probable problem or significant maintainability risk.
  - **low** — nits, naming, minor style.
- In `inline` mode, post each finding as an inline comment; in `summary` mode, only update the sticky summary.
- Return the structured output matching the schema; every inline comment must also appear in `findings`.

## Error handling summary

- Analyzer/build failure → check fails; errors in job summary; override does not apply.
- Claude API error/timeout → one retry, then gate fails with an override-able message.
- Missing/invalid structured output → treated as Claude failure (`show_full_output` is deliberately off: this repo's logs are public).
- Missing secret → Claude skipped with a notice; gate fails unless overridden.

## Cost & noise controls

- No runs on draft PRs or irrelevant label events.
- Override-label events skip Claude.
- `--max-turns 30`, 10-minute job timeout.
- Summary-only mode above `max_diff_lines`.
- Excluded paths per repo; one sticky summary comment.

## Setup (one-time, manual)

1. Create **public** GitHub repo `jasonblacksmith/code-quality-bot`. It has to be public because the reusable workflow checks out this repo for its prompt and scripts, and a caller repo's token can't read a private repo. It contains no secrets.
2. In each project repo, add secret `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) or `ANTHROPIC_API_KEY`.
3. Create the `review-override` label in each project repo.
4. After the first successful run, add the `gate` check as required in branch protection.

## Testing

- **Unit (pytest):** `gate.py` against every row of the decision table, plus: absent findings file, malformed JSON, schema-invalid findings, `findings.json` output shape.
- **Schema:** valid and invalid sample files in `tests/samples/` validated with `jsonschema`.
- **End-to-end:** in `MudSlinger`, open a PR with a planted analyzer violation and a planted logic bug. Expect: analyzers fail → gate fails. Fix the analyzer issue → Claude flags the bug `high` → gate fails. Add `review-override` → gate passes without re-running Claude.
- **Rollout:** tune `prompts/review.md` on the first few real MudSlinger PRs, then add the caller to `infinite-dungeon`.

## Future (not in this spec)

- Quality dashboard reading `findings.json` artifacts across repos.
- Non-.NET analyzer support (e.g. markdownlint for `AurifexMentis`).
