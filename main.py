#!/usr/bin/env python3
"""Standalone launcher for podharvest.

Run this file directly to use the app without installing it:

    python main.py                 # usage screen / optional GUI prompt
    python main.py fetch <url>     # harvest a feed from the command line
    python main.py hardware        # detect hardware, recommend an ASR model
    python main.py gui             # launch the wxPython desktop app

This script makes the repository importable regardless of the current
working directory, so it also works as a portable, double-click-friendly
entry point (e.g. via a .bat/.command wrapper) when bundled with its own
Python runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from podharvest.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
