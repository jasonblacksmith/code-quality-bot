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
