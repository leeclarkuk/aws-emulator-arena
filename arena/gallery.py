"""Cards for divergent steps, and for 501s, with stable permalink anchors."""

from __future__ import annotations

import json
import re
from datetime import datetime

PUBLIC_BASE = "https://leeclarkuk.github.io/aws-emulator-arena"
_GALLERY_OUTCOMES = ("divergent", "not_implemented")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:80] or "step")


def anchor_id(scenario_slug: str, title: str) -> str:
    """Stable fragment for one step. Scenario slug plus the step title."""

    return f"{slugify(scenario_slug)}--{slugify(title)}"


def unique_anchor(scenario_slug: str, title: str, used: set[str]) -> str:
    base = anchor_id(scenario_slug, title)
    anchor = base
    suffix = 2
    while anchor in used:
        anchor = f"{base}-{suffix}"
        suffix += 1
    used.add(anchor)
    return anchor


def gallery_cards(scoreboard: dict, history: dict | None) -> list[dict]:
    """One card per divergent step, then the same shape for each 501."""

    cards = []
    for scenario in scoreboard.get("scenarios") or []:
        for step in scenario.get("steps") or []:
            if step.get("outcome") not in _GALLERY_OUTCOMES:
                continue
            seen = locate_first_seen(
                history,
                scoreboard,
                scenario.get("slug") or "",
                step.get("title") or "",
                step.get("outcome") or "",
            )
            cards.append(
                {
                    "anchor": step.get("anchor") or anchor_id(scenario.get("slug") or "", step.get("title") or ""),
                    "outcome": step.get("outcome"),
                    "scenario": scenario.get("slug") or "",
                    "scenario_title": scenario.get("title") or scenario.get("slug") or "",
                    "title": step.get("title") or "",
                    "service": step.get("service") or "",
                    "service_name": step.get("service_name") or step.get("service") or "",
                    "operation": step.get("operation") or "",
                    "aws_would": step.get("aws_would") or "",
                    "detail": step.get("detail") or "",
                    "observed": step.get("observed"),
                    "http_status": step.get("http_status"),
                    "error_code": step.get("error_code"),
                    "headline": response_headline(step.get("observed")),
                    "first": seen["first"],
                    "current": seen["current"],
                    "first_is_exact": seen["exact"],
                }
            )
    return cards


def locate_first_seen(history: dict | None, scoreboard: dict, scenario: str, title: str, outcome: str) -> dict:
    """Earliest recorded run where this step had this outcome.

    History points written before step outcomes were stored cannot name a
    step. In that case the earliest named record is the latest history
    point, whose timestamp does not move on a timing-only hour.
    """

    current = _appearance_from_scoreboard(scoreboard)
    first = None
    for run in (history or {}).get("runs") or []:
        for step in run.get("step_outcomes") or []:
            if step.get("scenario") == scenario and step.get("title") == title and step.get("outcome") == outcome:
                first = _appearance_from_run(run)
                break
        if first:
            break
    if first:
        return {"first": first, "current": current, "exact": True}
    runs = (history or {}).get("runs") or []
    if runs:
        fallback = _appearance_from_run(runs[-1])
        # The live scoreboard names the step. Prefer its version and commit,
        # and keep the timestamp of the last committed history point so a
        # timing-only hour does not move "first seen".
        fallback["emulator_version"] = current["emulator_version"] or fallback["emulator_version"]
        fallback["emulator_commit"] = current["emulator_commit"] or fallback["emulator_commit"]
        return {"first": fallback, "current": current, "exact": False}
    return {"first": current, "current": current, "exact": False}


def response_headline(observed) -> str | None:
    """A single line for the response people quote. None when there is nothing to pull out."""

    if not isinstance(observed, dict):
        return None
    if any(key in observed for key in ("buildStatus", "logs", "phases")):
        return _codebuild_headline(observed)
    if "EvalDecision" in observed:
        decision = observed.get("EvalDecision")
        action = observed.get("EvalActionName") or "the action"
        actual = observed.get("ListBuckets")
        if actual:
            return f"EvalDecision {decision} for {action}, and ListBuckets was {actual}"
        return f"EvalDecision {decision}"
    err = observed.get("Error")
    if isinstance(err, dict) and (err.get("Code") or err.get("Message")):
        code = err.get("Code") or "Error"
        message = err.get("Message") or ""
        if message:
            return f"{code}: {message}"
        return str(code)
    return None


def render_gallery_page(scoreboard: dict, history: dict | None) -> str:
    cards = gallery_cards(scoreboard, history)
    emulator = scoreboard.get("emulator") or {}
    version = emulator.get("version") or "unknown"
    divergent = sum(1 for card in cards if card["outcome"] == "divergent")
    gaps = sum(1 for card in cards if card["outcome"] == "not_implemented")
    title = "Divergence gallery | AWS Emulator Arena"
    description = (
        f"AWS Emulator {version}: {divergent} divergent steps and {gaps} calls that came back 501."
    )
    body = "\n".join(
        [
            _header(scoreboard),
            _nav(current="gallery"),
            "<p class=\"lede gallery-lede\">",
            _html(
                "A divergent step got an answer, and the answer was not what AWS would do. "
                "A 501 means the emulator said the operation is not implemented. "
                "Each card has a stable link."
            ),
            "</p>",
            _section(
                "Divergent",
                "The emulator answered, and the answer was wrong.",
                [card for card in cards if card["outcome"] == "divergent"],
                empty="No divergent steps in this run.",
            ),
            _section(
                "501 Not Implemented",
                "The emulator refused the call.",
                [card for card in cards if card["outcome"] == "not_implemented"],
                empty="Nothing returned 501 in this run.",
            ),
            _footer(),
        ]
    )
    return _document(title=title, description=description, canonical=f"{PUBLIC_BASE}/gallery.html", body=body)


def _codebuild_headline(observed: dict) -> str | None:
    bits = []
    status = observed.get("buildStatus")
    if status:
        bits.append(str(status))
    if "logs" in observed:
        bits.append("logs null" if observed.get("logs") is None else "logs set")
    duration = _build_duration(observed)
    if duration is not None:
        unit = "second" if duration == 1 else "seconds"
        bits.append(f"BUILD phase {duration} {unit}")
    if not bits:
        return None
    return ", ".join(bits)


def _build_duration(observed: dict):
    phases = observed.get("phases")
    if isinstance(phases, list):
        for phase in phases:
            if isinstance(phase, dict) and phase.get("phaseType") == "BUILD":
                return phase.get("durationInSeconds")
    build = observed.get("BUILD")
    if isinstance(build, dict) and "durationInSeconds" in build:
        return build.get("durationInSeconds")
    if "durationInSeconds" in observed:
        return observed.get("durationInSeconds")
    return None


def _section(title: str, note: str, cards: list[dict], *, empty: str) -> str:
    parts = [
        "<section>",
        "<div class=\"section-head\">",
        f"<h2>{_html(title)}</h2>",
        f"<p>{_html(note)}</p>",
        "</div>",
    ]
    if not cards:
        parts.append(f"<p class=\"empty\">{_html(empty)}</p>")
    else:
        parts.append("<div class=\"gallery\">")
        parts.extend(_card(card) for card in cards)
        parts.append("</div>")
    parts.append("</section>")
    return "\n".join(parts)


def _card(card: dict) -> str:
    anchor = card["anchor"]
    badge = "501" if card["outcome"] == "not_implemented" else "divergent"
    badge_class = "badge gap" if card["outcome"] == "not_implemented" else "badge"
    observed = card.get("observed")
    observed_text = ""
    if observed is not None:
        observed_text = json.dumps(observed, indent=2, ensure_ascii=False)
    headline = card.get("headline") or ""
    detail = card.get("detail") or ""
    show_detail = bool(detail) and (not headline or (detail not in headline and headline not in detail))
    aws_would = card.get("aws_would") or "The scenario does not describe what AWS would do for this step yet."
    status_bits = []
    if card.get("http_status"):
        status_bits.append(f"HTTP {card['http_status']}")
    if card.get("error_code"):
        status_bits.append(str(card["error_code"]))
    where = card["scenario_title"]
    if status_bits:
        where = f"{where}, {', '.join(status_bits)}"
    parts = [
        f"<article class=\"note gallery-card\" id=\"{_attr(anchor)}\">",
        "<div class=\"card-kicker\">",
        f"<span class=\"{badge_class}\">{_html(badge)}</span>",
        f"<a class=\"permalink\" href=\"#{_attr(anchor)}\">Link to this card</a>",
        "</div>",
        f"<h3>{_html(card['title'])}</h3>",
        f"<p class=\"where\">{_html(where)}</p>",
        f"<p class=\"opname\">{_html(card['service_name'])} {_html(card['operation'])}</p>",
    ]
    if headline:
        parts.append(f"<p class=\"headline\">{_html(headline)}</p>")
    parts.append("<h4>What AWS would do</h4>")
    parts.append(f"<p class=\"msg\">{_html(aws_would)}</p>")
    parts.append("<h4>What the emulator returned</h4>")
    if show_detail:
        parts.append(f"<p class=\"finding\">{_html(detail)}</p>")
    if observed_text:
        parts.append(f"<pre class=\"observed\">{_html(observed_text)}</pre>")
    elif not show_detail:
        parts.append("<p class=\"finding\">The step did not record a response body.</p>")
    parts.append(f"<p class=\"seen\">{_seen_html(card)}</p>")
    parts.append("</article>")
    return "\n".join(parts)


def _seen_html(card: dict) -> str:
    first = card["first"]
    current = card["current"]
    if card["first_is_exact"]:
        sentence = "First seen " + _when(first.get("generated_at")) + " on " + _version_html(first) + "."
    else:
        sentence = (
            "On "
            + _version_html(first)
            + ", as of the scoreboard recorded "
            + _when(first.get("generated_at"))
            + ". Earlier runs did not name the step."
        )
    same = (first.get("emulator_version"), first.get("emulator_commit")) == (
        current.get("emulator_version"),
        current.get("emulator_commit"),
    )
    if same:
        return sentence
    return sentence + " Still present on " + _version_html(current) + "."


def _version_html(appearance: dict) -> str:
    version = appearance.get("emulator_version") or "an unknown version"
    commit = appearance.get("emulator_commit") or ""
    text = _html(f"emulator {version}")
    if not commit:
        return text
    shown = _html(commit[:12] if len(commit) > 12 else commit)
    url = _commit_url(commit)
    if url:
        return f"{text}, commit <a href=\"{_attr(url)}\">{shown}</a>"
    return f"{text}, commit {shown}"


def _commit_url(commit: str) -> str | None:
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", commit or ""):
        return f"https://github.com/aws/aws-emulator/commit/{commit}"
    return None


def _when(iso: str | None) -> str:
    if not iso:
        return "an unknown time"
    try:
        moment = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return _html(iso)
    return moment.strftime("%-d %b %Y, %H:%M UTC")


def _appearance_from_run(run: dict) -> dict:
    return {
        "generated_at": run.get("generated_at"),
        "emulator_version": run.get("emulator_version"),
        "emulator_commit": run.get("emulator_commit"),
    }


def _appearance_from_scoreboard(scoreboard: dict) -> dict:
    emulator = scoreboard.get("emulator") or {}
    return {
        "generated_at": scoreboard.get("generated_at"),
        "emulator_version": emulator.get("version"),
        "emulator_commit": emulator.get("commit"),
    }


def _header(scoreboard: dict) -> str:
    emulator = scoreboard.get("emulator") or {}
    summary = scoreboard.get("summary") or {}
    fidelity = summary.get("fidelity_pct")
    fidelity_text = "-" if fidelity is None else f"{fidelity}%"
    pills = [
        ("emulator", emulator.get("version") or "unknown"),
        ("fidelity", fidelity_text),
        ("ran", _ran(scoreboard.get("generated_at"))),
    ]
    pill_html = "".join(
        f"<span class=\"pill\">{_html(name)} <strong>{_html(str(value))}</strong></span>" for name, value in pills
    )
    return "\n".join(
        [
            "<header class=\"top\">",
            "<div class=\"brand\">",
            "<div class=\"mark\"></div>",
            "<div>",
            "<h1>AWS Emulator Arena</h1>",
            "<p>Divergence gallery</p>",
            "</div>",
            "</div>",
            f"<div class=\"pills\">{pill_html}</div>",
            "</header>",
        ]
    )


def _ran(iso: str | None) -> str:
    if not iso:
        return "-"
    return iso.replace("T", " ").replace("Z", " UTC")


def _nav(current: str) -> str:
    items = [
        ("index.html", "Scoreboard", "board"),
        ("gallery.html", "Divergence gallery", "gallery"),
        ("feed.xml", "Atom feed", "atom"),
        ("rss.xml", "RSS", "rss"),
    ]
    links = []
    for href, label, key in items:
        current_attr = " aria-current=\"page\"" if key == current else ""
        links.append(f"<a href=\"{_attr(href)}\"{current_attr}>{_html(label)}</a>")
    return "<nav class=\"board-nav\">" + "".join(links) + "</nav>"


def _footer() -> str:
    return "\n".join(
        [
            "<footer class=\"colophon\">",
            "<div>No AWS account. No real credentials. The emulator on 127.0.0.1 is the only thing under test.</div>",
            "<nav>",
            "<a href=\"index.html\">Scoreboard</a>",
            "<a href=\"feed.xml\">Atom feed</a>",
            "<a href=\"rss.xml\">RSS</a>",
            "<a href=\"https://github.com/leeclarkuk/aws-emulator-arena\">Arena source</a>",
            "</nav>",
            "</footer>",
        ]
    )


def _document(*, title: str, description: str, canonical: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html(title)}</title>
  <meta name="description" content="{_attr(description)}">
  <link rel="canonical" href="{_attr(canonical)}">
  <link rel="alternate" type="application/atom+xml" title="AWS Emulator Arena changes" href="feed.xml">
  <link rel="alternate" type="application/rss+xml" title="AWS Emulator Arena changes" href="rss.xml">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{_attr(title)}">
  <meta property="og:description" content="{_attr(description)}">
  <meta property="og:url" content="{_attr(canonical)}">
  <meta property="og:image" content="{PUBLIC_BASE}/og.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{_attr(title)}">
  <meta name="twitter:description" content="{_attr(description)}">
  <meta name="twitter:image" content="{PUBLIC_BASE}/og.png">
  <meta name="theme-color" content="#F7F7F7">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23F7F7F7'/%3E%3Ccircle cx='16' cy='16' r='6' fill='%230666EB'/%3E%3C/svg%3E">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;display=swap" rel="stylesheet">
  <link rel="stylesheet" href="arena.css">
</head>
<body>
  <div class="wrap">
{body}
  </div>
</body>
</html>
"""


def _html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _attr(text: str) -> str:
    return _html(text).replace('"', "&quot;")
