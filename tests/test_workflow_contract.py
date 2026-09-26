"""Drift tests: keep review.yml, prompts/review.md and gate.py in sync.

Regex-based (no YAML dependency) per the project's testing approach.
"""
from __future__ import annotations

import re
from pathlib import Path

import gate

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "review.yml"
PROMPT = ROOT / "prompts" / "review.md"

EXPECTED_PLACEHOLDERS = {"REPO", "PR_NUMBER", "REVIEW_MODE", "EXCLUDE_PATHS", "DIAGNOSTICS_PATH"}


def test_render_prompt_set_keys_match_placeholders_used_in_prompt():
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    keys = set(re.findall(r'--set "([A-Z_]+)=', workflow_text))

    assert keys == EXPECTED_PLACEHOLDERS

    prompt_text = PROMPT.read_text(encoding="utf-8")
    for key in keys:
        assert re.search(rf'\${re.escape(key)}(?![A-Za-z0-9_])', prompt_text), (
            f"${key} passed by review.yml but not referenced in prompts/review.md"
        )


def test_gate_invocation_flags_are_all_accepted_by_gate_parser():
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"scripts/gate\.py(.*?)\n\n", workflow_text, re.S)
    assert match, "could not find the gate.py invocation block in review.yml"
    invocation = match.group(1)

    flags = set(re.findall(r"--([a-z][a-z-]*)", invocation))
    assert flags, "no flags found in gate.py invocation"

    parser = gate.build_parser()
    accepted = {opt.lstrip("-") for action in parser._actions for opt in action.option_strings}

    for flag in flags:
        assert flag in accepted, f"--{flag} passed to gate.py but not accepted by gate._parse_args"
