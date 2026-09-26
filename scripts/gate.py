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
