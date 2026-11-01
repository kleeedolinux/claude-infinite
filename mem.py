#!/usr/bin/env python3
"""Launcher: python mem.py <command>. Works from a checkout or ~/.claude/infinite."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here / "src") if (here / "src" / "infinite").exists() else str(here))
from infinite.cli import main  # noqa: E402

main()
