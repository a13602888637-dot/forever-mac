"""Absolute-path stdio entry point for Codex, Claude Code and Cursor."""
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.chdir(PROJECT)

if __name__ == "__main__":
    from backend.cli import main
    sys.argv.insert(1, "mcp-serve")
    main()
