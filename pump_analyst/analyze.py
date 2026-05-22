from __future__ import annotations

import sys
from pathlib import Path

from . import cli


def main(argv: list[str] | None = None) -> int:
    old_argv = sys.argv[:]
    try:
        if argv is not None:
            sys.argv = [str(Path(__file__).parent / "cli.py"), *argv]
        cli.main()
    finally:
        sys.argv = old_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
