"""Build a standalone executable of the Discord backup GUI.

This helper wraps ``pyinstaller`` with the correct options for the project so
that contributors do not have to remember the exact command line.  The
resulting binary is written to the ``dist`` directory.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def ensure_pyinstaller() -> None:
    """Abort with a helpful message if ``pyinstaller`` is missing."""

    if shutil.which("pyinstaller") is None:
        print(
            "pyinstaller is required to build the executable.\n"
            "Install it with: python -m pip install pyinstaller"
        )
        sys.exit(1)


def build() -> None:
    """Run pyinstaller with the arguments we need."""

    command = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        "discord-backup-gui",
        "--specpath",
        str(PROJECT_ROOT / "build" / "pyinstaller"),
        str(PROJECT_ROOT / "discord_backup_gui.py"),
    ]

    subprocess.run(command, check=True, cwd=PROJECT_ROOT)


def main() -> None:
    ensure_pyinstaller()
    build()
    print("Executable written to dist/discord-backup-gui")


if __name__ == "__main__":
    main()
