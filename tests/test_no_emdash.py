"""Fail if U+2014 (em dash) appears in any tracked text file."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = "\u2014"
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".js",
    ".css",
    ".html",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
    ".sh",
    ".json",
    ".svg",
    ".Dockerfile",
}
TEXT_NAMES = {
    "Dockerfile",
    "Makefile",
    "LICENSE",
    ".gitignore",
    ".dockerignore",
}


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [ROOT / name for name in result.stdout.decode().split("\0") if name]


def _is_text(path: Path) -> bool:
    if path.name in TEXT_NAMES:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def test_no_em_dash_in_tracked_text_files():
    offenders: list[str] = []
    for path in _tracked_files():
        if not _is_text(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if EM_DASH not in text:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                offenders.append(f"{rel}:{line_no}")
    assert not offenders, "em dash (U+2014) found in:\n" + "\n".join(offenders)
