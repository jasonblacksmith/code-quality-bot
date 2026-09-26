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
