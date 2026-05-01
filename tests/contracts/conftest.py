from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _pin_canonical_contracts_package() -> None:
    """Keep contracts tests from resolving scrapers/contracts in worktrees."""
    candidates = [
        Path.home(),
        Path(__file__).resolve().parents[3],
    ]
    for root in candidates:
        if (root / "contracts" / "odds.py").exists():
            root_str = str(root)
            if root_str in sys.path:
                sys.path.remove(root_str)
            sys.path.insert(0, root_str)
            importlib.import_module("contracts")
            return


_pin_canonical_contracts_package()
