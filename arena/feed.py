"""Atom and RSS feeds of step outcome changes and new emulator versions."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime

from arena.gallery import PUBLIC_BASE, anchor_id, slugify
from arena.report import service_name

_STEP_LINK_OUTCOMES = {"divergent", "not_implemented"}


def detect_transitions(history: dict | None) -> list[dict]:
    """Walk recorded runs in order.

    A step entry is emitted when the same step has a different outcome from
    the previous run that named its steps. A version entry is emitted the
    first time an emulator version appears after the baseline run. Runs that
    do not name steps leave the previous step snapshot in place, so a later
    named run can still be compared. They do not invent a change on their own.
    """

    events = []
    seen_versions: set[str] = set()
    previous: dict[tuple[str, str], dict] | None = None
    for run in (history or {}).get("runs") or []:
        version = run.get("emulator_version")
        if version and version not in seen_versions:
            if seen_versions and run.get("generated_at"):
                events.append(_version_event(run))
            seen_versions.add(version)
        steps = run.get("step_outcomes")
        if not steps or not run.get("generated_at"):
            continue
        current = {}
        for step in steps:
            scenario = step.get("scenario") or ""
            title = step.get("title") or ""
            if not scenario or not title or not step.get("outcome"):
                continue
            current[(scenario, title)] = step
        if previous is not None:
            for key in sorted(previous.keys() & current.keys()):
                before = previous[key].get("outcome")
                after = current[key].get("outcome")
                if before and after and before != after:
                    events.append(_step_event(run, current[key], before, after))
        previous = current
    return events


def render_atom(history: dict | None, *, anchors: set[str] | None = None, updated: str | None = None) -> str:
    events = _newest_first(detect_transitions(history))
    stamp = _feed_updated(events, history, updated)
    entries = "\n".join(_atom_entry(event, anchors) for event in events)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en-GB">
  <title>AWS Emulator Arena changes</title>
  <subtitle>Step outcome changes, and emulator versions the board had not seen before.</subtitle>
  <id>tag:leeclarkuk.github.io,2026:arena</id>
  <updated>{_xml(stamp)}</updated>
  <link rel="self" type="application/atom+xml" href="{PUBLIC_BASE}/feed.xml"/>
  <link rel="alternate" type="text/html" href="{PUBLIC_BASE}/"/>
  <author><name>AWS Emulator Arena</name></author>
{entries}
</feed>
"""


def render_rss(history: dict | None, *, anchors: set[str] | None = None, updated: str | None = None) -> str:
    events = _newest_first(detect_transitions(history))
    stamp = _feed_updated(events, history, updated)
    items = "\n".join(_rss_item(event, anchors) for event in events)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>AWS Emulator Arena changes</title>
    <link>{PUBLIC_BASE}/</link>
    <description>Step outcome changes, and emulator versions the board had not seen before.</description>
    <language>en-GB</language>
    <lastBuildDate>{_xml(_rfc822(stamp))}</lastBuildDate>
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" rel="self" type="application/rss+xml" href="{PUBLIC_BASE}/rss.xml"/>
{items}
  </channel>
</rss>
"""


def _version_event(run: dict) -> dict:
    return {
        "kind": "version",
        "generated_at": run.get("generated_at"),
        "emulator_version": run.get("emulator_version"),
        "emulator_commit": run.get("emulator_commit"),
        "fidelity_pct": run.get("fidelity_pct"),
        "pass": run.get("pass"),
        "not_implemented": run.get("not_implemented"),
        "divergent": run.get("divergent"),
    }


def _step_event(run: dict, step: dict, before: str, after: str) -> dict:
    scenario = step.get("scenario") or ""
    title = step.get("title") or ""
    return {
        "kind": "step",
        "generated_at": run.get("generated_at"),
        "emulator_version": run.get("emulator_version"),
        "emulator_commit": run.get("emulator_commit"),
        "scenario": scenario,
        "scenario_title": step.get("scenario_title") or scenario,
        "title": title,
        "service": step.get("service") or "",
        "operation": step.get("operation") or "",
        "from": before,
        "to": after,
        "anchor": anchor_id(scenario, title),
    }


def _atom_entry(event: dict, anchors: set[str] | None) -> str:
    title, summary = _copy(event, anchors)
    href = _href(event, anchors)
    return "\n".join(
        [
            "  <entry>",
            f"    <title>{_xml(title)}</title>",
            f"    <id>{_xml(_event_id(event))}</id>",
            f"    <updated>{_xml(event['generated_at'])}</updated>",
            f"    <link rel=\"alternate\" type=\"text/html\" href=\"{_xml(href)}\"/>",
            f"    <summary type=\"text\">{_xml(summary)}</summary>",
            "  </entry>",
        ]
    )


def _rss_item(event: dict, anchors: set[str] | None) -> str:
    title, summary = _copy(event, anchors)
    href = _href(event, anchors)
    guid = _event_id(event)
    return "\n".join(
        [
            "    <item>",
            f"      <title>{_xml(title)}</title>",
            f"      <link>{_xml(href)}</link>",
            f"      <guid isPermaLink=\"false\">{_xml(guid)}</guid>",
            f"      <pubDate>{_xml(_rfc822(event['generated_at']))}</pubDate>",
            f"      <description>{_xml(summary)}</description>",
            "    </item>",
        ]
    )


def _copy(event: dict, anchors: set[str] | None) -> tuple[str, str]:
    version = event.get("emulator_version") or "unknown"
    commit = event.get("emulator_commit") or "unknown"
    if event["kind"] == "version":
        title = f"Emulator {version} first appeared"
        fidelity = event.get("fidelity_pct")
        if fidelity is None:
            scored = "Fidelity was not scored."
        else:
            scored = (
                f"Fidelity was {fidelity}% "
                f"({event.get('pass', 0)} pass, {event.get('not_implemented', 0)} not implemented, "
                f"{event.get('divergent', 0)} divergent)."
            )
        summary = f"AWS Emulator {version} (commit {commit}) showed up on the board for the first time. {scored}"
        return title, summary
    before = _outcome_label(event.get("from"))
    after = _outcome_label(event.get("to"))
    title = f"{event.get('scenario_title')}: {event.get('title')} changed from {before} to {after}"
    operation = f"{service_name(event.get('service') or '')} {event.get('operation') or ''}".strip()
    summary = (
        f"{operation} changed from {before} to {after} on emulator {version} (commit {commit})."
    )
    href = _href(event, anchors)
    if event.get("to") in _STEP_LINK_OUTCOMES and "gallery.html#" in href:
        summary += f" Gallery card: {href}"
    return title, summary


def _href(event: dict, anchors: set[str] | None) -> str:
    if event["kind"] == "step" and event.get("to") in _STEP_LINK_OUTCOMES:
        anchor = event.get("anchor") or ""
        if anchors is None or anchor in anchors:
            return f"{PUBLIC_BASE}/gallery.html#{anchor}"
    return f"{PUBLIC_BASE}/"


def _event_id(event: dict) -> str:
    if event["kind"] == "version":
        return f"tag:leeclarkuk.github.io,2026:arena:version:{event.get('emulator_version')}:{event.get('generated_at')}"
    return (
        "tag:leeclarkuk.github.io,2026:arena:step:"
        f"{event.get('scenario')}:{event.get('operation')}:{slugify(event.get('title') or '')}:"
        f"{event.get('from')}:{event.get('to')}:{event.get('generated_at')}"
    )


def _outcome_label(outcome: str | None) -> str:
    if outcome == "not_implemented":
        return "501"
    if outcome == "divergent":
        return "divergent"
    if outcome == "blocked":
        return "blocked"
    if outcome == "pass":
        return "pass"
    return outcome or "unknown"


def _newest_first(events: list[dict]) -> list[dict]:
    # Stable, so events that share a timestamp keep their original order.
    return sorted(events, key=lambda event: event.get("generated_at") or "", reverse=True)


def _feed_updated(events: list[dict], history: dict | None, updated: str | None) -> str:
    if updated:
        return updated
    if events:
        return events[0]["generated_at"]
    runs = (history or {}).get("runs") or []
    if runs and runs[-1].get("generated_at"):
        return runs[-1]["generated_at"]
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rfc822(iso: str) -> str:
    try:
        moment = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return iso or ""
    return format_datetime(moment)


def _xml(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
