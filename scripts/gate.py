"""Decide whether a PR review passes, and write the combined findings report."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "findings.schema.json"

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
