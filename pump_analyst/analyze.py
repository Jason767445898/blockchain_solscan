from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


LEGACY_ANALYZER = Path(__file__).with_name("analyze_entry&exit_conditions.py")


def _load_legacy_analyzer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pump_analyst._entry_exit_conditions", LEGACY_ANALYZER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load analyzer from {LEGACY_ANALYZER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    module = _load_legacy_analyzer()
    old_argv = sys.argv[:]
    try:
        if argv is not None:
            sys.argv = [str(LEGACY_ANALYZER), *argv]
        module.main()
    finally:
        sys.argv = old_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

