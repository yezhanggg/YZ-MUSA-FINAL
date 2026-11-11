"""Fail when a change adds a file that must not be pushed.

Checks the files added or changed between two commits:
- nothing over 5 MB (data stays on the drive)
- no .env file (.env.example is fine)
- nothing under no-push/

    python .github/scripts/guard.py BASE HEAD
    python .github/scripts/guard.py --files a.txt b.txt   (pre-commit style, paths given)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
ZERO = "0" * 40


def _exists(rev: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"], capture_output=True).returncode == 0


def changed(base: str, head: str) -> list[str]:
    # A new branch has no base, and a force push can leave the old base out of history.
    if not base or base == ZERO or not _exists(base):
        cmd = ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--diff-filter=AMR", "--root", head]
    else:
        cmd = ["git", "diff", "--name-only", "--diff-filter=AMR", f"{base}...{head}"]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return [f for f in out.splitlines() if f]


def size_at(path: str, head: str | None) -> int:
    if head is None:
        return Path(path).stat().st_size
    out = subprocess.run(["git", "cat-file", "-s", f"{head}:{path}"], capture_output=True, text=True)
    return int(out.stdout.strip() or 0) if out.returncode == 0 else 0


def problems(files: list[str], head: str | None) -> list[str]:
    bad = []
    for f in files:
        name = Path(f).name
        if f == "no-push" or f.startswith("no-push/") or "/no-push/" in f:
            bad.append(f"{f}: under no-push/")
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            bad.append(f"{f}: environment file with keys")
        size = size_at(f, head)
        if size > MAX_BYTES:
            bad.append(f"{f}: {size / 1e6:.1f} MB is over 5 MB")
    return bad


def main(argv: list[str]) -> int:
    if argv[:1] == ["--files"]:
        files, head = [f for f in argv[1:] if Path(f).exists()], None
    elif len(argv) == 2:
        files, head = changed(argv[0], argv[1]), argv[1]
    else:
        print(__doc__)
        return 2
    bad = problems(files, head)
    for b in bad:
        print(f"blocked: {b}")
    print(f"{len(files)} changed files checked, {len(bad)} blocked")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
