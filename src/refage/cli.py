"""CLI entrypoint for refage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import format_human, scan


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="refage",
        description=(
            "Offline CLI: flag 'recent/SOTA' wording near citations whose "
            "BibTeX years are older than --max-age."
        ),
    )
    p.add_argument(
        "drafts",
        nargs="+",
        type=Path,
        help="Markdown and/or LaTeX draft file(s)",
    )
    p.add_argument(
        "--bib",
        type=Path,
        required=True,
        help="BibTeX bibliography file",
    )
    p.add_argument(
        "--max-age",
        type=int,
        default=5,
        help="Max age in years before current calendar year (default: 5)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    p.add_argument(
        "--fail-on",
        choices=("findings", "never", "errors"),
        default="findings",
        help="When to exit 1: findings (default), never, or errors only",
    )
    p.add_argument(
        "--year",
        type=int,
        default=None,
        help=argparse.SUPPRESS,  # test override for current calendar year
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.max_age < 0:
        print("refage: --max-age must be >= 0", file=sys.stderr)
        return 2

    for d in args.drafts:
        if not d.is_file():
            print(f"refage: draft not found: {d}", file=sys.stderr)
            return 2
    if not args.bib.is_file():
        print(f"refage: bib not found: {args.bib}", file=sys.stderr)
        return 2

    result = scan(
        args.drafts,
        args.bib,
        max_age=args.max_age,
        current_year=args.year,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        sys.stdout.write(format_human(result))

    if result.errors and not result.files_scanned:
        return 2

    if args.fail_on == "never":
        return 0
    if args.fail_on == "errors":
        return 2 if result.errors else 0
    # findings
    if result.errors and not result.files_scanned:
        return 2
    return 1 if result.has_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
