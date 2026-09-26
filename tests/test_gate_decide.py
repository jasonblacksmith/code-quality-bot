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
