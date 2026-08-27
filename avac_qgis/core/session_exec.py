"""POSIX session launcher used only as the direct child of QProcess."""

from __future__ import annotations

import os
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: session_exec.py '<shell command>'")
    # This child becomes the session/process-group leader before replacing
    # itself with the plugin-owned shell.  Descendant make/xgeoclaw processes
    # remain in this unique group unless they explicitly create another one.
    os.setsid()
    os.execvpe("/bin/sh", ["/bin/sh", "-lc", sys.argv[1]], os.environ)


if __name__ == "__main__":
    main()
