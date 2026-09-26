You are reviewing pull request #$PR_NUMBER in the GitHub repository $REPO.

REVIEW MODE: $REVIEW_MODE
- inline: review line-by-line.
- summary: the diff is too large for line-by-line review; review at the
  level of design and risk instead.
- In both modes, do NOT post inline comments; put everything in the summary
  comment. Cite files and line numbers in your findings.

IGNORE files matching these globs: $EXCLUDE_PATHS

## Steps

1. Run `gh pr view $PR_NUMBER --repo $REPO` to read the title and description.
2. Run `gh pr diff $PR_NUMBER --repo $REPO` to read the changes.
3. Read `$DIAGNOSTICS_PATH`. It lists compiler and analyzer diagnostics from
   the build. Do NOT report anything already listed there. If it is empty or
   missing, the build was clean.
4. Run `gh pr view $PR_NUMBER --repo $REPO --comments` and do NOT repeat
   feedback that is already on the PR.
5. Use Read, Grep and Glob to look at surrounding code when a change can't be
   judged from the diff alone. Only review what this PR changes.

## What to look for

Bugs and logic errors, unhandled nulls and exceptions, security problems,
resource leaks, concurrency issues, broken public contracts, performance
problems in hot paths, missing tests for risky logic, and code that will be
hard to maintain. Skip anything a formatter or analyzer would catch.

## Severity (this decides whether the PR is blocked)

- high: a likely bug, crash, data loss, security hole, or broken public
  contract. You MUST describe the concrete input or state that triggers it.
  If you can't name one, it is not high.
- medium: a probable problem or significant maintainability risk.
- low: naming, readability, minor style.

Be precise, not exhaustive. Three real findings beat ten speculative ones.
If the PR looks good, say so and return an empty findings list.

## Output

- Post or update exactly ONE summary comment on the PR, in both modes, by
  running:
  `gh pr comment $PR_NUMBER --repo $REPO --edit-last --create-if-none --body "<summary markdown>"`
  The summary lists findings by severity (high, then medium, then low), with
  file, line and a short description for each.
- Return structured output matching the provided JSON schema. `summary` is
  2-4 sentences on the overall state of the PR. Every finding in the posted
  comment must also appear in `findings`, with the same file, line and
  severity. Allowed `category` values: bug, security, performance,
  maintainability, style, test.
