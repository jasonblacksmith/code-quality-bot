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
