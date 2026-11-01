#!/usr/bin/env python3
"""Launcher: python mem.py <command>. Works from a checkout or ~/.claude/infinite."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here / "src") if (here / "src" / "infinite").exists() else str(here))

if len(sys.argv) > 2 and sys.argv[1] == "hook":
    # fast path: hooks skip argparse and the CLI module graph (startup is most of a hook's cost)
    from infinite import hooks  # noqa: E402

    hooks.run(sys.argv[2])
else:
    from infinite.cli import main  # noqa: E402

    main()
