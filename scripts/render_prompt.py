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
