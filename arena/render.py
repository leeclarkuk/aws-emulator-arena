"""Write the static scoreboard. The page inlines its data, so it works on GitHub Pages at any base path."""

from __future__ import annotations

import json
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def render_site(scoreboard: dict, history: dict, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("arena.css", "arena.js"):
        (destination / name).write_text((WEB / name).read_text(encoding="utf-8"), encoding="utf-8")
    public = {key: value for key, value in scoreboard.items() if key != "calls"}
    fidelity = scoreboard["summary"]["fidelity_pct"]
    version = scoreboard["emulator"].get("version") or "unknown"
    title = f"{fidelity}% fidelity | AWS Emulator Arena" if fidelity is not None else "AWS Emulator Arena"
    description = (
        f"AWS Emulator {version}: {fidelity}% of arena steps behaved like AWS. "
        f"{scoreboard['summary']['not_implemented']} returned 501, "
        f"{scoreboard['summary']['divergent']} diverged."
        if fidelity is not None
        else "A fidelity scoreboard for the AWS Emulator."
    )
    html = (WEB / "index.html").read_text(encoding="utf-8")
    html = (
        html.replace("__TITLE__", _html(title))
        .replace("__DESCRIPTION__", _html(description))
        .replace("__REPORT__", _embed(public))
        .replace("__HISTORY__", _embed(history))
    )
    page = destination / "index.html"
    page.write_text(html, encoding="utf-8")
    return page


def _embed(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")


def _html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
