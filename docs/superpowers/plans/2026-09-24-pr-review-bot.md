# PR Review Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reusable GitHub Actions workflow that runs .NET analyzers and a Claude review on every PR, posts inline comments, and blocks merges on analyzer errors or Claude `high` findings (Claude blocks clearable with a `review-override` label).

**Architecture:** Central repo `jasonblacksmith/code-quality-bot` holds a reusable workflow with three jobs: `analyzers` (dotnet build, warnings as errors), `claude` (`anthropics/claude-code-action@v1` with `--json-schema` structured output), and `gate` (a Python script applying the decision table and writing `findings.json`). Project repos call it with a ~20-line workflow.

**Tech Stack:** GitHub Actions, `anthropics/claude-code-action@v1`, .NET 10 SDK, Python 3.12+ (`jsonschema`, `pytest`), `actionlint`.

**Spec:** `docs/superpowers/specs/2026-09-24-pr-review-bot-design.md`

## Global Constraints

- Default .NET SDK: `10.0.x` (latest stable, LTS). Builds existing `net9.0` projects unchanged.
- Claude action pinned to `anthropics/claude-code-action@v1`.
- Override label default: `review-override`. It clears Claude-originated blocks only, never analyzer failures.
- `--max-turns 30`, claude job `timeout-minutes: 10`, summary-only review above `max_diff_lines` (default `2000`).
- Findings severities are exactly `low`, `medium`, `high`; categories exactly `bug`, `security`, `performance`, `maintainability`, `style`, `test`.
- Any failure mode fails the check; nothing passes silently.
- Python code must run on 3.12 (CI) and 3.14 (local).
- All local commands below are for Git Bash on Windows, run from the repo root `C:/Code/Source/PersonalGitHub/code-quality-bot`.

## Deviations from the spec (apply in Task 1)

1. **Analyzer output is a text file, not SARIF.** MSBuild's `-p:ErrorLog=` writes one file per build, so every project in a solution overwrites the same path. Instead, the workflow extracts `file(line,col): error CODE: message` lines from the build log into `analyzer-diagnostics.txt`.
2. **`code-quality-bot` must be a public repo.** The workflow checks out its own repo for the prompt and scripts. A caller repo's `GITHUB_TOKEN` can't read another private repo. The repo holds no secrets.
3. **Default `dotnet_version` is `10.0.x`.**
4. **Caller workflows must grant permissions** `contents: read`, `pull-requests: write`, `id-token: write`, because a reusable workflow can't have more permissions than its caller.
5. **The gate reads the override label from the event payload** (`github.event.pull_request.labels`), so it makes no extra API call.

## File Structure

```
code-quality-bot/
├── .gitignore
├── pyproject.toml                       pytest config (pythonpath = scripts)
├── requirements-dev.txt                 pytest, jsonschema, actionlint-py
├── README.md                            what it is + one-time setup
├── schema/findings.schema.json          Claude's structured-output schema
├── prompts/review.md                    review prompt template ($-placeholders)
├── scripts/gate.py                      decision table + findings.json + step summary
├── scripts/render_prompt.py             fills prompt template
├── examples/code-review.yml             caller workflow to copy into project repos
├── .github/workflows/review.yml         reusable workflow
└── tests/
    ├── samples/valid.json
    ├── samples/invalid_severity.json
    ├── samples/missing_fields.json
    ├── test_schema.py
    ├── test_gate_decide.py
    ├── test_gate_io.py
    └── test_render_prompt.py
```

---

### Task 1: Scaffold, findings schema, spec amendments

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `requirements-dev.txt`, `schema/findings.schema.json`, `tests/samples/valid.json`, `tests/samples/invalid_severity.json`, `tests/samples/missing_fields.json`, `tests/test_schema.py`
- Modify: `docs/superpowers/specs/2026-09-24-pr-review-bot-design.md`

**Interfaces:**
- Produces: `schema/findings.schema.json`, whose top-level object has `summary: str` and `findings: list[{file, line, severity, category, message, suggestion?}]`. Used by Tasks 2, 3, 5.

- [ ] **Step 1: Create project config files**

`.gitignore`:
```
.venv/
__pycache__/
.pytest_cache/
findings.json
```

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
pythonpath = ["scripts"]
testpaths = ["tests"]
```

`requirements-dev.txt`:
```
pytest>=8
jsonschema>=4.20
actionlint-py>=1.7
```

- [ ] **Step 2: Create venv and install**

Run:
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -q -r requirements-dev.txt
```
Expected: exits 0.

- [ ] **Step 3: Write the failing schema tests**

`tests/samples/valid.json`:
```json
{
  "summary": "One null-dereference risk in the parser.",
  "findings": [
    {
      "file": "src/MudSlinger/Parser.cs",
      "line": 42,
      "severity": "high",
      "category": "bug",
      "message": "token can be null when input is empty; Split() will throw.",
      "suggestion": "Return early when input is empty."
    },
    {
      "file": "src/MudSlinger/Parser.cs",
      "line": 10,
      "severity": "low",
      "category": "style",
      "message": "Name 'tmp' is unclear."
    }
  ]
}
```

`tests/samples/invalid_severity.json`:
```json
{
  "summary": "x",
  "findings": [
    {"file": "a.cs", "line": 1, "severity": "critical", "category": "bug", "message": "m"}
  ]
}
```

`tests/samples/missing_fields.json`:
```json
{
  "summary": "x",
  "findings": [
    {"file": "a.cs", "severity": "high", "category": "bug", "message": "m"}
  ]
}
```

`tests/test_schema.py`:
```python
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schema" / "findings.schema.json").read_text(encoding="utf-8"))
SAMPLES = ROOT / "tests" / "samples"


def load(name):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def test_valid_sample_passes():
    jsonschema.validate(load("valid.json"), SCHEMA)


def test_empty_findings_passes():
    jsonschema.validate({"summary": "Looks good.", "findings": []}, SCHEMA)


@pytest.mark.parametrize("name", ["invalid_severity.json", "missing_fields.json"])
def test_invalid_samples_fail(name):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(load(name), SCHEMA)


def test_line_must_be_positive():
    bad = {"summary": "x", "findings": [
        {"file": "a.cs", "line": 0, "severity": "low", "category": "bug", "message": "m"}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)


def test_schema_has_no_single_quotes():
    # The workflow passes the schema inside single quotes in claude_args.
    assert "'" not in (ROOT / "schema" / "findings.schema.json").read_text(encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_schema.py -v`
Expected: errors with `FileNotFoundError` for `findings.schema.json`.

- [ ] **Step 5: Create the schema**

`schema/findings.schema.json`:
```json
{
  "type": "object",
  "required": ["summary", "findings"],
  "additionalProperties": false,
  "properties": {
    "summary": { "type": "string" },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["file", "line", "severity", "category", "message"],
        "additionalProperties": false,
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

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_schema.py -v`
Expected: 6 passed.

- [ ] **Step 7: Amend the spec**

In `docs/superpowers/specs/2026-09-24-pr-review-bot-design.md`:
- Workflow inputs table: change the `dotnet_version` default from `8.0.x` to `10.0.x`.
- Job 1 step 2: replace the `dotnet build ...` line with `dotnet build <solution> -warnaserror -p:EnforceCodeStyleInBuild=true -p:AnalysisLevel=latest-recommended`, with the log saved to `build.log`.
- Job 1 step 3: replace it with "Extract `: (warning|error) CODE:` lines from `build.log` into `analyzer-diagnostics.txt` (deduplicated) and upload it as an artifact regardless of outcome. SARIF isn't used because MSBuild's `ErrorLog` writes one file per build and projects overwrite each other."
- Job 1 step 4: replace it with "The job fails if the build fails. The gate reads `needs.analyzers.result`."
- Job 2: replace every mention of `analyzers.sarif` / "SARIF" with `analyzer-diagnostics.txt`.
- Setup step 1: replace it with "Create **public** GitHub repo `jasonblacksmith/code-quality-bot`. It has to be public because the reusable workflow checks out this repo for its prompt and scripts, and a caller repo's token can't read a private repo. It contains no secrets."
- Caller example: add a `permissions:` block (`contents: read`, `pull-requests: write`, `id-token: write`) to the `review` job.

- [ ] **Step 8: Commit**

```bash
git add .gitignore pyproject.toml requirements-dev.txt schema tests docs
git commit -m "feat: add findings schema and project scaffold

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Gate decision logic

**Files:**
- Create: `scripts/gate.py`
- Test: `tests/test_gate_decide.py`

**Interfaces:**
- Consumes: findings dict shape from Task 1.
- Produces (in `scripts/gate.py`):
  - `CLAUDE_STATUSES: tuple[str, ...] = ("success", "failure", "no-credentials", "skipped")`
  - `@dataclass Decision(passed: bool, reason: str, overridden: bool = False, high: list[dict] = [])`
  - `decide(analyzers_passed: bool, claude_status: str, findings: dict | None, override_label_present: bool) -> Decision`

- [ ] **Step 1: Write the failing tests (one per decision-table row)**

`tests/test_gate_decide.py`:
```python
import pytest

from gate import decide

HIGH = {"file": "a.cs", "line": 1, "severity": "high", "category": "bug", "message": "boom"}
LOW = {"file": "a.cs", "line": 2, "severity": "low", "category": "style", "message": "nit"}


def f(*items):
    return {"summary": "s", "findings": list(items)}


@pytest.mark.parametrize("status", ["success", "failure", "no-credentials", "skipped"])
@pytest.mark.parametrize("override", [True, False])
def test_analyzer_failure_always_fails(status, override):
    d = decide(False, status, f(), override)
    assert not d.passed
    assert "Analyzer" in d.reason
    assert not d.overridden


def test_success_no_high_passes():
    d = decide(True, "success", f(LOW), False)
    assert d.passed and not d.overridden
    assert d.high == []


def test_success_empty_findings_passes():
    assert decide(True, "success", f(), False).passed


def test_high_without_override_fails():
    d = decide(True, "success", f(HIGH, LOW), False)
    assert not d.passed
    assert d.high == [HIGH]
    assert "1 high" in d.reason


def test_high_with_override_passes_overridden():
    d = decide(True, "success", f(HIGH), True)
    assert d.passed and d.overridden
    assert d.high == [HIGH]


@pytest.mark.parametrize("status,phrase", [
    ("failure", "didn't complete"),
    ("no-credentials", "no credentials"),
    ("skipped", "skipped"),
])
def test_claude_not_reviewed_without_override_fails(status, phrase):
    d = decide(True, status, None, False)
    assert not d.passed
    assert phrase in d.reason
    assert "override" in d.reason


@pytest.mark.parametrize("status", ["failure", "no-credentials", "skipped"])
def test_claude_not_reviewed_with_override_passes(status):
    d = decide(True, status, None, True)
    assert d.passed and d.overridden


def test_success_but_invalid_findings_fails():
    d = decide(True, "success", None, False)
    assert not d.passed
    assert "no valid findings" in d.reason


def test_success_but_invalid_findings_with_override_passes():
    d = decide(True, "success", None, True)
    assert d.passed and d.overridden


def test_unknown_status_rejected():
    with pytest.raises(ValueError):
        decide(True, "cancelled", None, False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_gate_decide.py -v`
Expected: `ModuleNotFoundError: No module named 'gate'`.

- [ ] **Step 3: Implement `decide`**

`scripts/gate.py`:
```python
"""Decide whether a PR review passes, and write the combined findings report."""
from __future__ import annotations

from dataclasses import dataclass, field

CLAUDE_STATUSES = ("success", "failure", "no-credentials", "skipped")

_NOT_REVIEWED = {
    "success": "Claude returned no valid findings",
    "failure": "Claude review didn't complete",
    "no-credentials": "Claude review not run (no credentials)",
    "skipped": "Claude review skipped",
}


@dataclass
class Decision:
    passed: bool
    reason: str
    overridden: bool = False
    high: list[dict] = field(default_factory=list)


def decide(analyzers_passed: bool, claude_status: str, findings: dict | None,
           override_label_present: bool) -> Decision:
    if claude_status not in CLAUDE_STATUSES:
        raise ValueError(f"unknown claude status: {claude_status!r}")
    if not analyzers_passed:
        return Decision(False, "Analyzer errors (override does not apply).")

    if claude_status == "success" and findings is not None:
        high = [item for item in findings["findings"] if item["severity"] == "high"]
        if not high:
            return Decision(True, "No high-severity findings.")
        if override_label_present:
            return Decision(True, f"{len(high)} high-severity finding(s), overridden by label.",
                            overridden=True, high=high)
        return Decision(False, f"{len(high)} high-severity finding(s).", high=high)

    problem = _NOT_REVIEWED[claude_status]
    if override_label_present:
        return Decision(True, f"{problem}; overridden by label.", overridden=True)
    return Decision(False, f"{problem}; re-run or add the override label.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_gate_decide.py -v`
Expected: 21 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/gate.py tests/test_gate_decide.py
git commit -m "feat: add gate decision table

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Gate I/O: loading findings, report, summary, CLI

**Files:**
- Modify: `scripts/gate.py`
- Test: `tests/test_gate_io.py`

**Interfaces:**
- Consumes: `decide`, `Decision`, `CLAUDE_STATUSES` (Task 2); schema (Task 1).
- Produces (in `scripts/gate.py`):
  - `SCHEMA_PATH: Path` (the repo's `schema/findings.schema.json`)
  - `load_findings(path: Path | None, schema_path: Path = SCHEMA_PATH) -> dict | None` returns `None` if the file is missing, empty, not JSON, or doesn't match the schema.
  - `build_report(decision, findings, *, analyzers_passed, claude_status, repo, pr, sha, now) -> dict`
  - `render_summary(report: dict) -> str` (Markdown)
  - `main(argv: list[str] | None = None) -> int` returns 0 on pass, 1 on fail.
  - CLI: `python scripts/gate.py --analyzers {passed,failed} --claude-status {success,failure,no-credentials,skipped} [--findings PATH] --override {true,false} --repo R --pr N --sha S [--out findings.json] [--summary PATH]`. `--summary` defaults to `$GITHUB_STEP_SUMMARY`.

- [ ] **Step 1: Write the failing tests**

`tests/test_gate_io.py`:
```python
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import gate

SAMPLES = Path(__file__).resolve().parent / "samples"


# --- load_findings ---------------------------------------------------------

def test_load_valid(tmp_path):
    p = tmp_path / "f.json"
    shutil.copy(SAMPLES / "valid.json", p)
    data = gate.load_findings(p)
    assert data["findings"][0]["severity"] == "high"


def test_load_none_path():
    assert gate.load_findings(None) is None


def test_load_missing_file(tmp_path):
    assert gate.load_findings(tmp_path / "nope.json") is None


def test_load_empty_file(tmp_path):
    p = tmp_path / "f.json"
    p.write_text("", encoding="utf-8")
    assert gate.load_findings(p) is None


def test_load_malformed_json(tmp_path):
    p = tmp_path / "f.json"
    p.write_text("{not json", encoding="utf-8")
    assert gate.load_findings(p) is None


def test_load_schema_invalid(tmp_path):
    p = tmp_path / "f.json"
    shutil.copy(SAMPLES / "invalid_severity.json", p)
    assert gate.load_findings(p) is None


# --- build_report / render_summary ----------------------------------------

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def test_build_report_shape():
    findings = json.loads((SAMPLES / "valid.json").read_text(encoding="utf-8"))
    decision = gate.decide(True, "success", findings, False)
    report = gate.build_report(decision, findings, analyzers_passed=True, claude_status="success",
                               repo="jasonblacksmith/MudSlinger", pr=7, sha="abc123", now=NOW)
    assert report == {
        "repo": "jasonblacksmith/MudSlinger",
        "pr": 7,
        "sha": "abc123",
        "timestamp": "2026-09-24T12:00:00+00:00",
        "analyzers_passed": True,
        "claude_status": "success",
        "passed": False,
        "overridden": False,
        "reason": "1 high-severity finding(s).",
        "summary": findings["summary"],
        "findings": findings["findings"],
    }


def test_build_report_without_findings():
    decision = gate.decide(True, "failure", None, False)
    report = gate.build_report(decision, None, analyzers_passed=True, claude_status="failure",
                               repo="r", pr=1, sha="s", now=NOW)
    assert report["summary"] is None
    assert report["findings"] == []


def test_render_summary_fail_lists_findings_and_escapes_pipes():
    report = {"passed": False, "reason": "1 high-severity finding(s).", "summary": "sum",
              "findings": [{"file": "a.cs", "line": 3, "severity": "high", "category": "bug",
                            "message": "a | b"}]}
    md = gate.render_summary(report)
    assert md.startswith("## Code review gate: FAIL")
    assert "1 high-severity finding(s)." in md
    assert "| high | a.cs | 3 | bug | a \\| b |" in md


def test_render_summary_pass_no_findings():
    md = gate.render_summary({"passed": True, "reason": "No high-severity findings.",
                              "summary": None, "findings": []})
    assert md.startswith("## Code review gate: PASS")
    assert "| Severity" not in md


# --- main ------------------------------------------------------------------

def run_main(tmp_path, *extra):
    out = tmp_path / "findings.json"
    summary = tmp_path / "summary.md"
    args = ["--repo", "r", "--pr", "5", "--sha", "s", "--out", str(out),
            "--summary", str(summary), *extra]
    code = gate.main(args)
    return code, json.loads(out.read_text(encoding="utf-8")), summary.read_text(encoding="utf-8")


def test_main_fails_on_high(tmp_path):
    code, report, summary = run_main(
        tmp_path, "--analyzers", "passed", "--claude-status", "success",
        "--findings", str(SAMPLES / "valid.json"), "--override", "false")
    assert code == 1
    assert report["passed"] is False
    assert "FAIL" in summary


def test_main_passes_with_override(tmp_path):
    code, report, _ = run_main(
        tmp_path, "--analyzers", "passed", "--claude-status", "success",
        "--findings", str(SAMPLES / "valid.json"), "--override", "true")
    assert code == 0
    assert report["overridden"] is True


def test_main_missing_findings_file_fails(tmp_path):
    code, report, _ = run_main(
        tmp_path, "--analyzers", "passed", "--claude-status", "success",
        "--findings", str(tmp_path / "absent.json"), "--override", "false")
    assert code == 1
    assert "no valid findings" in report["reason"]


def test_main_analyzers_failed(tmp_path):
    code, report, _ = run_main(
        tmp_path, "--analyzers", "failed", "--claude-status", "skipped", "--override", "true")
    assert code == 1
    assert report["analyzers_passed"] is False


def test_main_summary_appends(tmp_path):
    summary = tmp_path / "summary.md"
    summary.write_text("existing\n", encoding="utf-8")
    gate.main(["--repo", "r", "--pr", "1", "--sha", "s", "--out", str(tmp_path / "o.json"),
               "--summary", str(summary), "--analyzers", "passed",
               "--claude-status", "skipped", "--override", "true"])
    assert summary.read_text(encoding="utf-8").startswith("existing\n## Code review gate")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_gate_io.py -v`
Expected: FAIL with `AttributeError: module 'gate' has no attribute 'load_findings'`.

- [ ] **Step 3: Implement I/O and CLI**

Add these imports at the top of `scripts/gate.py`, replacing the existing `from dataclasses ...` line:
```python
import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "findings.schema.json"
```

Append to the end of `scripts/gate.py`:
```python
def load_findings(path: Path | None, schema_path: Path = SCHEMA_PATH) -> dict | None:
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)
    except (json.JSONDecodeError, jsonschema.ValidationError):
        return None
    return data


def build_report(decision: Decision, findings: dict | None, *, analyzers_passed: bool,
                 claude_status: str, repo: str, pr: int, sha: str, now: datetime) -> dict:
    return {
        "repo": repo,
        "pr": pr,
        "sha": sha,
        "timestamp": now.isoformat(),
        "analyzers_passed": analyzers_passed,
        "claude_status": claude_status,
        "passed": decision.passed,
        "overridden": decision.overridden,
        "reason": decision.reason,
        "summary": findings["summary"] if findings else None,
        "findings": findings["findings"] if findings else [],
    }


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_summary(report: dict) -> str:
    lines = [f"## Code review gate: {'PASS' if report['passed'] else 'FAIL'}", "", report["reason"], ""]
    if report["summary"]:
        lines += [report["summary"], ""]
    if report["findings"]:
        lines += ["| Severity | File | Line | Category | Message |", "|---|---|---|---|---|"]
        order = {"high": 0, "medium": 1, "low": 2}
        for item in sorted(report["findings"], key=lambda i: order[i["severity"]]):
            lines.append(f"| {item['severity']} | {_cell(item['file'])} | {item['line']} "
                         f"| {item['category']} | {_cell(item['message'])} |")
        lines.append("")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--analyzers", choices=["passed", "failed"], required=True)
    p.add_argument("--claude-status", choices=CLAUDE_STATUSES, required=True)
    p.add_argument("--findings", type=Path)
    p.add_argument("--override", choices=["true", "false"], required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--out", type=Path, default=Path("findings.json"))
    p.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY"))
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    analyzers_passed = args.analyzers == "passed"
    findings = load_findings(args.findings)
    decision = decide(analyzers_passed, args.claude_status, findings, args.override == "true")
    report = build_report(decision, findings, analyzers_passed=analyzers_passed,
                          claude_status=args.claude_status, repo=args.repo, pr=args.pr,
                          sha=args.sha, now=datetime.now(timezone.utc))
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(render_summary(report))
    print(("PASS: " if decision.passed else "FAIL: ") + decision.reason)
    return 0 if decision.passed else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run all tests**

Run: `.venv/Scripts/python -m pytest -v`
Expected: all pass (schema + decide + io).

- [ ] **Step 5: Smoke-test the CLI**

Run:
```bash
.venv/Scripts/python scripts/gate.py --analyzers passed --claude-status success --findings tests/samples/valid.json --override false --repo r --pr 1 --sha s --out "$TEMP/f.json"; echo "exit=$?"
```
Expected: `FAIL: 1 high-severity finding(s).` then `exit=1`.

- [ ] **Step 6: Commit**

```bash
git add scripts/gate.py tests/test_gate_io.py
git commit -m "feat: gate CLI writes findings report and step summary

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Review prompt and renderer

**Files:**
- Create: `prompts/review.md`, `scripts/render_prompt.py`
- Test: `tests/test_render_prompt.py`

**Interfaces:**
- Produces:
  - `render(template: str, values: dict[str, str]) -> str` raises `KeyError` if a placeholder has no value.
  - CLI: `python scripts/render_prompt.py TEMPLATE --set KEY=VALUE [--set ...]` prints the rendered prompt to stdout.
  - Placeholders used by `prompts/review.md` (the workflow in Task 5 must set exactly these): `REPO`, `PR_NUMBER`, `REVIEW_MODE`, `EXCLUDE_PATHS`, `DIAGNOSTICS_PATH`.

- [ ] **Step 1: Write the failing tests**

`tests/test_render_prompt.py`:
```python
from pathlib import Path

import pytest

from render_prompt import main, render

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "review.md"
KEYS = {"REPO": "o/r", "PR_NUMBER": "7", "REVIEW_MODE": "inline",
        "EXCLUDE_PATHS": "**/bin/**", "DIAGNOSTICS_PATH": "analyzer-diagnostics.txt"}


def test_render_substitutes():
    assert render("PR $PR_NUMBER in ${REPO}", {"PR_NUMBER": "3", "REPO": "o/r"}) == "PR 3 in o/r"


def test_render_missing_key_raises():
    with pytest.raises(KeyError):
        render("$REPO $PR_NUMBER", {"REPO": "o/r"})


def test_render_escaped_dollar():
    assert render("costs $$5", {}) == "costs $5"


def test_real_prompt_renders_with_workflow_keys():
    text = render(PROMPT.read_text(encoding="utf-8"), KEYS)
    for value in KEYS.values():
        assert value in text
    assert "$" not in text  # no leftover placeholders


def test_real_prompt_needs_every_key():
    template = PROMPT.read_text(encoding="utf-8")
    for key in KEYS:
        partial = {k: v for k, v in KEYS.items() if k != key}
        with pytest.raises(KeyError):
            render(template, partial)


def test_cli(capsys, tmp_path):
    t = tmp_path / "t.md"
    t.write_text("Review $REPO#$PR_NUMBER", encoding="utf-8")
    assert main([str(t), "--set", "REPO=o/r", "--set", "PR_NUMBER=9"]) == 0
    assert capsys.readouterr().out.strip() == "Review o/r#9"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_render_prompt.py -v`
Expected: `ModuleNotFoundError: No module named 'render_prompt'`.

- [ ] **Step 3: Implement the renderer**

`scripts/render_prompt.py`:
```python
"""Fill the review prompt template with values from the workflow."""
from __future__ import annotations

import argparse
import string
import sys
from pathlib import Path


def render(template: str, values: dict[str, str]) -> str:
    return string.Template(template).substitute(values)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("template", type=Path)
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    args = p.parse_args(argv)
    values = dict(item.split("=", 1) for item in args.set)
    sys.stdout.write(render(args.template.read_text(encoding="utf-8"), values) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write the prompt**

`prompts/review.md` (any literal dollar sign must be written `$$`):
```markdown
You are reviewing pull request #$PR_NUMBER in the GitHub repository $REPO.

REVIEW MODE: $REVIEW_MODE
- inline: post each finding as an inline comment on the changed line using
  mcp__github_inline_comment__create_inline_comment.
- summary: the diff is too large for line-by-line review. Do NOT post inline
  comments; review at the level of design and risk, and cite files and line
  numbers in your findings.

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

- Post inline comments (inline mode only). Each comment: the problem, why it
  matters, and a suggested fix.
- Return structured output matching the provided JSON schema. `summary` is
  2-4 sentences on the overall state of the PR. Every inline comment you post
  must also appear in `findings`, with the same file, line and severity.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_render_prompt.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add prompts scripts/render_prompt.py tests/test_render_prompt.py
git commit -m "feat: add review prompt and renderer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Reusable workflow

**Files:**
- Create: `.github/workflows/review.yml`

**Interfaces:**
- Consumes: `scripts/gate.py` CLI (Task 3), `scripts/render_prompt.py` CLI and placeholders (Task 4), `schema/findings.schema.json` (Task 1).
- Produces: `workflow_call` with inputs `solution` (required), `dotnet_version`, `exclude_paths`, `max_diff_lines`, `override_label`, `bot_ref`. Optional secrets `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY`. Artifacts `analyzer-diagnostics`, `claude-findings`, `findings`.

- [ ] **Step 1: Write the workflow**

`.github/workflows/review.yml`:
```yaml
name: PR review

on:
  workflow_call:
    inputs:
      solution:
        description: Path to the .sln to build
        type: string
        required: true
      dotnet_version:
        type: string
        default: "10.0.x"
      exclude_paths:
        description: Comma-separated globs Claude should ignore
        type: string
        default: "**/bin/**,**/obj/**,**/*.g.cs,**/*.Designer.cs,**/packages.lock.json"
      max_diff_lines:
        description: Above this many changed lines, Claude does a summary-only review
        type: number
        default: 2000
      override_label:
        type: string
        default: review-override
      bot_ref:
        description: Ref of code-quality-bot to load prompt and scripts from
        type: string
        default: main
    secrets:
      CLAUDE_CODE_OAUTH_TOKEN:
        required: false
      ANTHROPIC_API_KEY:
        required: false

jobs:
  analyzers:
    # Skip drafts and label events for labels other than the override label.
    if: >-
      github.event.pull_request.draft == false &&
      ((github.event.action != 'labeled' && github.event.action != 'unlabeled') ||
       github.event.label.name == inputs.override_label)
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-dotnet@v4
        with:
          dotnet-version: ${{ inputs.dotnet_version }}

      - name: Build with analyzers
        shell: bash
        run: |
          set -o pipefail
          dotnet build "${{ inputs.solution }}" \
            -warnaserror \
            -p:EnforceCodeStyleInBuild=true \
            -p:AnalysisLevel=latest-recommended \
            2>&1 | tee build.log

      - name: Extract diagnostics
        if: always()
        shell: bash
        run: |
          grep -E ': (warning|error) [A-Z]+[0-9]+:' build.log \
            | sed -E 's/ \[[^]]*\]$//' | sort -u > analyzer-diagnostics.txt || true
          echo "$(wc -l < analyzer-diagnostics.txt) diagnostic(s)"

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: analyzer-diagnostics
          path: analyzer-diagnostics.txt

  claude:
    needs: analyzers
    # Run even if analyzers failed (review is still useful). Skip when the
    # override label was just added: Claude findings can't block then.
    if: >-
      always() && needs.analyzers.result != 'skipped' &&
      github.event.action != 'labeled'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
      pull-requests: write
      id-token: write
    outputs:
      status: ${{ steps.result.outputs.status }}
    steps:
      - name: Check credentials
        id: creds
        env:
          OAUTH: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          if [ -n "$OAUTH" ] || [ -n "$KEY" ]; then
            echo "ok=true" >> "$GITHUB_OUTPUT"
          else
            echo "ok=false" >> "$GITHUB_OUTPUT"
            echo "::notice::Claude review skipped: no CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY secret."
          fi

      - uses: actions/checkout@v4
        if: steps.creds.outputs.ok == 'true'
        with:
          fetch-depth: 0

      - uses: actions/checkout@v4
        if: steps.creds.outputs.ok == 'true'
        with:
          repository: jasonblacksmith/code-quality-bot
          ref: ${{ inputs.bot_ref }}
          path: .bot

      - uses: actions/download-artifact@v4
        if: steps.creds.outputs.ok == 'true'
        continue-on-error: true
        with:
          name: analyzer-diagnostics

      - name: Prepare prompt and schema
        id: prep
        if: steps.creds.outputs.ok == 'true'
        env:
          ADDITIONS: ${{ github.event.pull_request.additions }}
          DELETIONS: ${{ github.event.pull_request.deletions }}
          MAX_LINES: ${{ inputs.max_diff_lines }}
          EXCLUDE: ${{ inputs.exclude_paths }}
          PR: ${{ github.event.pull_request.number }}
        run: |
          touch analyzer-diagnostics.txt
          if [ $((ADDITIONS + DELETIONS)) -gt "$MAX_LINES" ]; then mode=summary; else mode=inline; fi
          echo "Review mode: $mode ($((ADDITIONS + DELETIONS)) changed lines)"
          {
            echo "prompt<<PROMPT_EOF"
            python3 .bot/scripts/render_prompt.py .bot/prompts/review.md \
              --set "REPO=$GITHUB_REPOSITORY" --set "PR_NUMBER=$PR" \
              --set "REVIEW_MODE=$mode" --set "EXCLUDE_PATHS=$EXCLUDE" \
              --set "DIAGNOSTICS_PATH=analyzer-diagnostics.txt"
            echo "PROMPT_EOF"
            echo "schema=$(python3 -c 'import json;print(json.dumps(json.load(open(".bot/schema/findings.schema.json")),separators=(",",":")))')"
          } >> "$GITHUB_OUTPUT"

      - name: Claude review
        id: claude1
        if: steps.creds.outputs.ok == 'true'
        continue-on-error: true
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: ${{ steps.prep.outputs.prompt }}
          use_sticky_comment: true
          claude_args: >-
            --max-turns 30
            --json-schema '${{ steps.prep.outputs.schema }}'
            --allowedTools "Read,Grep,Glob,mcp__github_inline_comment__create_inline_comment,Bash(gh pr diff:*),Bash(gh pr view:*),Bash(gh pr comment:*)"

      - name: Claude review (retry)
        id: claude2
        if: steps.claude1.outcome == 'failure'
        continue-on-error: true
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: ${{ steps.prep.outputs.prompt }}
          use_sticky_comment: true
          claude_args: >-
            --max-turns 30
            --json-schema '${{ steps.prep.outputs.schema }}'
            --allowedTools "Read,Grep,Glob,mcp__github_inline_comment__create_inline_comment,Bash(gh pr diff:*),Bash(gh pr view:*),Bash(gh pr comment:*)"

      - name: Record result
        id: result
        if: always()
        env:
          CREDS: ${{ steps.creds.outputs.ok }}
          O1: ${{ steps.claude1.outcome }}
          O2: ${{ steps.claude2.outcome }}
          OUT1: ${{ steps.claude1.outputs.structured_output }}
          OUT2: ${{ steps.claude2.outputs.structured_output }}
        run: |
          if [ "$CREDS" != "true" ]; then status=no-credentials
          elif [ "$O1" = "success" ]; then status=success; printf '%s' "$OUT1" > claude-findings.json
          elif [ "$O2" = "success" ]; then status=success; printf '%s' "$OUT2" > claude-findings.json
          else status=failure; fi
          echo "status=$status" >> "$GITHUB_OUTPUT"
          echo "Claude status: $status"

      - uses: actions/upload-artifact@v4
        if: always() && steps.result.outputs.status == 'success'
        with:
          name: claude-findings
          path: claude-findings.json

  gate:
    needs: [analyzers, claude]
    if: always() && needs.analyzers.result != 'skipped'
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          repository: jasonblacksmith/code-quality-bot
          ref: ${{ inputs.bot_ref }}
          path: .bot

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: pip install -q "jsonschema>=4.20"

      - uses: actions/download-artifact@v4
        continue-on-error: true
        with:
          name: claude-findings

      - name: Gate
        env:
          ANALYZERS: ${{ needs.analyzers.result == 'success' && 'passed' || 'failed' }}
          CLAUDE_STATUS: ${{ needs.claude.outputs.status || (needs.claude.result == 'skipped' && 'skipped' || 'failure') }}
          OVERRIDE: ${{ contains(github.event.pull_request.labels.*.name, inputs.override_label) }}
          PR: ${{ github.event.pull_request.number }}
          SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          python .bot/scripts/gate.py \
            --analyzers "$ANALYZERS" --claude-status "$CLAUDE_STATUS" \
            --findings claude-findings.json --override "$OVERRIDE" \
            --repo "$GITHUB_REPOSITORY" --pr "$PR" --sha "$SHA" --out findings.json

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: findings
          path: findings.json
```

- [ ] **Step 2: Lint the workflow**

Run: `.venv/Scripts/actionlint .github/workflows/review.yml`
Expected: no output, exit 0. Fix any reported issue before continuing. Shellcheck warnings are reported only if `shellcheck` is installed, which is optional.

- [ ] **Step 3: Verify the schema one-liner locally**

Run:
```bash
.venv/Scripts/python -c 'import json;print(json.dumps(json.load(open("schema/findings.schema.json")),separators=(",",":")))'
```
Expected: a single line of JSON with no single quotes or newlines.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/review.yml
git commit -m "feat: add reusable PR review workflow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Caller example, README, CI for the bot itself

**Files:**
- Create: `examples/code-review.yml`, `README.md`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `review.yml` inputs (Task 5).

- [ ] **Step 1: Write the caller example**

`examples/code-review.yml`:
```yaml
# Copy to .github/workflows/code-review.yml in a project repo and set `solution`.
name: Code review

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, labeled, unlabeled]

concurrency:
  group: code-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    permissions:
      contents: read
      pull-requests: write
      id-token: write
    uses: jasonblacksmith/code-quality-bot/.github/workflows/review.yml@main
    with:
      solution: MudSlinger.sln
    secrets: inherit
```

- [ ] **Step 2: Write CI for the bot repo**

`.github/workflows/ci.yml`:
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -q -r requirements-dev.txt
      - run: python -m pytest -v
      - run: actionlint
```

- [ ] **Step 3: Write the README**

`README.md`:
````markdown
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

1. Copy [`examples/code-review.yml`](examples/code-review.yml) to
   `.github/workflows/code-review.yml` and set `solution`.
2. Add a repo secret: `CLAUDE_CODE_OAUTH_TOKEN` (run `claude setup-token`) or
   `ANTHROPIC_API_KEY`.
3. Create a `review-override` label.
4. After the first green run, make **review / gate** a required status check
   in branch protection.

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `solution` | (required) | `.sln` to build |
| `dotnet_version` | `10.0.x` | SDK for `actions/setup-dotnet` |
| `exclude_paths` | bin/obj/generated/lock files | Globs Claude ignores |
| `max_diff_lines` | `2000` | Above this, summary-only review |
| `override_label` | `review-override` | Label that clears Claude blocks |
| `bot_ref` | `main` | Ref of this repo to load prompt/scripts from |

## Develop

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
.venv/Scripts/actionlint
```

Design: [`docs/superpowers/specs/2026-09-24-pr-review-bot-design.md`](docs/superpowers/specs/2026-09-24-pr-review-bot-design.md)
````

- [ ] **Step 4: Lint and test everything**

Run: `.venv/Scripts/actionlint && .venv/Scripts/python -m pytest -q`
Expected: actionlint prints nothing; pytest reports all tests passed.

- [ ] **Step 5: Commit**

```bash
git add examples README.md .github/workflows/ci.yml
git commit -m "docs: add caller example, README and CI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Publish and end-to-end test on MudSlinger

**Every step in this task affects GitHub. Get the user's explicit approval before each one.**

**Files:**
- Create (in `mudslinger/`): `.github/workflows/code-review.yml` (copied from `examples/code-review.yml`)

- [ ] **Step 1: Check the analyzer baseline locally**

Run:
```bash
cd ../mudslinger && dotnet build MudSlinger.sln -warnaserror -p:EnforceCodeStyleInBuild=true -p:AnalysisLevel=latest-recommended 2>&1 | tail -20
```
Expected: `Build succeeded`. If it fails, **stop and show the user the errors.** Every PR would be blocked until they're fixed. Let the user choose: fix them first, add an `.editorconfig` that lowers the severity of specific rules, or turn off `-warnaserror` for now.

- [ ] **Step 2: Publish the bot repo (with user approval)**

```bash
gh repo create jasonblacksmith/code-quality-bot --public --source . --push
```
Expected: the repo is created and `main` is pushed. The `CI` workflow runs green (`gh run watch`).

- [ ] **Step 3: Add the caller to MudSlinger on a branch (with user approval)**

```bash
cd ../mudslinger
git checkout -b add-code-review
mkdir -p .github/workflows
cp ../code-quality-bot/examples/code-review.yml .github/workflows/code-review.yml
gh label create review-override --description "Clears Claude review blocks (not analyzer errors)" --color B60205
git add .github/workflows/code-review.yml
git commit -m "ci: add code-quality-bot PR review

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: User adds the secret**

The user runs `claude setup-token` and adds the result as the repo secret `CLAUDE_CODE_OAUTH_TOKEN`: `gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo jasonblacksmith/MudSlinger`. The agent never handles the token value.

- [ ] **Step 5: E2E scenario A, planted analyzer violation (with user approval)**

On `add-code-review`, add an unused variable to any method in `src/` (for example `var unused = 1;`, which triggers CS0219), commit, push, and open a draft PR. Then mark it ready: `gh pr ready`.
Expected: `analyzers` fails; `gate` fails with "Analyzer errors (override does not apply)". Add `review-override`, and `gate` still fails.

- [ ] **Step 6: E2E scenario B, planted logic bug**

Remove the unused variable. Plant an obvious bug, for example an off-by-one `for (int i = 0; i <= list.Count; i++)` indexing `list[i]`. Remove the label, then push.
Expected: `analyzers` passes. Claude posts an inline comment on the loop and a sticky summary. `gate` fails with "1 high-severity finding(s)." and the step summary table lists it.

- [ ] **Step 7: E2E scenario C, override**

Add the `review-override` label.
Expected: a new run starts. `claude` is skipped, and `gate` passes with "Claude review skipped; overridden by label." Download the `findings` artifact and confirm `overridden: true`.

- [ ] **Step 8: Clean up**

Revert the planted bug, remove the label, and push. Expected: `gate` passes cleanly. Ask the user whether to merge the PR, and whether to add `review / gate` as a required check.

- [ ] **Step 9: Tune and roll out**

Fix `prompts/review.md` based on the first few real PRs (noise, missed issues, severity calibration), committing to `code-quality-bot`. Then repeat Steps 1 and 3 for `infinite-dungeon` (`solution: OuroborosCube.sln`).
