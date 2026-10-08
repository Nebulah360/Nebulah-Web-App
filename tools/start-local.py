#!/usr/bin/env python3
"""Cross-platform Nebulah Link launcher.

macOS and Linux run the local browser, saved-data store, and support UI.
Xbox 360 Neighborhood connection remains Windows-only.
"""
from __future__ import annotations

import argparse
import os
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def check_python() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10+ required. Install Python, then run start-local.sh again.")
    sqlite3.connect(":memory:").close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args, extra = parser.parse_known_args()
    check_python()
    if os.name == "nt":
        print("Windows launcher should use Start Nebulah Link.cmd.", file=sys.stderr)
        return 2
    if platform.system() not in {"Darwin", "Linux"}:
        print("Unsupported host. Use Windows, macOS, or Linux.", file=sys.stderr)
        return 2
    print(f"Nebulah Link local mode: {platform.system()}")
    print("Browser and saved data work locally. Xbox connection needs Windows Neighborhood.")
    command = [sys.executable, str(PROJECT / "bridge" / "server.py"),
               "--host", args.host, "--port", str(args.port), "--open-browser", *extra]
    return subprocess.call(command, cwd=PROJECT)


if __name__ == "__main__":
    raise SystemExit(main())
