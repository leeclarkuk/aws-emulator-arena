"""Discover scenarios, run them, and write the scoreboard."""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass

from arena import __version__
from arena.aws import FATAL, open_session
from arena.classify import classify
from arena.report import append_history, build_scoreboard, dump_json, history_point, utc_now
from arena.render import render_site
from arena.scenarios import ALL


@dataclass
class StepResult:
    title: str
    service: str
    operation: str
    outcome: str
    latency_ms: float
    detail: str
    http_status: int | None
    error_code: str | None


@dataclass
class ScenarioResult:
    slug: str
    title: str
    summary: str
    services: list
    steps: list


def attach_call_log(session, sink: list) -> None:
    """Record every SDK attempt. Latency is the wire call, not client construction."""

    def before(model, context, **kwargs):
        context["_arena_t0"] = time.perf_counter()

    def after(http_response, parsed, model, context, **kwargs):
        started = context.get("_arena_t0")
        if started is None:
            return
        error_code = None
        if isinstance(parsed, dict) and isinstance(parsed.get("Error"), dict):
            error_code = parsed["Error"].get("Code")
        sink.append(
            {
                "service": model.service_model.service_name,
                "operation": model.name,
                "http_status": getattr(http_response, "status_code", None),
                "error_code": error_code,
                "latency_ms": (time.perf_counter() - started) * 1000,
            }
        )

    # boto3.Session has no event bus. The botocore session underneath does,
    # and every client created from it shares that bus.
    session._session.register("before-call", before)
    session._session.register("after-call", after)


def run_scenario(scenario, aws, calls: list) -> ScenarioResult:
    from arena.scenario import State

    state = State(os.environ.get("ARENA_RUN_ID") or _run_id())
    results = []
    for step in scenario.steps:
        before = len(calls)
        started = time.perf_counter()
        caught = None
        try:
            step.fn(aws, state)
        except FATAL:
            raise
        except Exception as exc:
            caught = exc
        elapsed = (time.perf_counter() - started) * 1000
        outcome, detail, status, error_code = classify(caught, step.expect)
        step_calls = calls[before:]
        if step_calls:
            last = step_calls[-1]
            if status is None:
                status = last["http_status"]
            if error_code is None:
                error_code = last["error_code"]
        if outcome == "pass" and step.expect.kind == "error" and not detail:
            detail = error_code or ""
        results.append(
            StepResult(
                title=step.title,
                service=step.service,
                operation=step.operation,
                outcome=outcome,
                latency_ms=elapsed,
                detail=(detail or "")[:400],
                http_status=status,
                error_code=error_code,
            )
        )
    return ScenarioResult(
        slug=scenario.slug,
        title=scenario.title,
        summary=scenario.summary,
        services=list(scenario.services),
        steps=results,
    )


def emulator_meta(aws) -> dict:
    version, release_date, commit = _read_version()
    startup = _optional_float("ARENA_EMULATOR_STARTUP_MS")
    rss_kb = _optional_float("ARENA_EMULATOR_RSS_KB")
    return {
        "version": version,
        "release_date": release_date,
        "commit": commit,
        "endpoint": aws.endpoint,
        "account": aws.identity["account"],
        "caller_arn": aws.identity["arn"],
        "startup_ms": None if startup is None else round(startup, 1),
        "rss_mb": None if rss_kb is None else round(rss_kb / 1024, 1),
        "arena_version": __version__,
    }


def execute(only: list[str] | None = None) -> dict:
    selected = _select(only)
    aws = open_session()
    calls: list[dict] = []
    attach_call_log(aws.session, calls)
    # Identity was checked before the log was attached, on purpose.
    run_id = _run_id()
    os.environ["ARENA_RUN_ID"] = run_id
    print(f"arena {__version__}  emulator account {aws.identity['account']}  run {run_id}", flush=True)
    results = []
    for scenario in selected:
        print(f"  {scenario.slug} …", flush=True)
        result = run_scenario(scenario, aws, calls)
        results.append(result)
        passed = sum(1 for step in result.steps if step.outcome == "pass")
        print(f"  {scenario.slug}  {passed}/{len(result.steps)}", flush=True)
    scoreboard = build_scoreboard(
        meta={"generated_at": utc_now(), "emulator": emulator_meta(aws)},
        scenarios=results,
        calls=calls,
    )
    return scoreboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arena", description="Run AWS Emulator Arena and write the scoreboard.")
    parser.add_argument("--only", action="append", default=[], help="Run one scenario slug. Repeatable.")
    parser.add_argument("--out", default="scoreboard/latest.json")
    parser.add_argument("--history", default="scoreboard/history.json")
    parser.add_argument("--site", default="site")
    parser.add_argument("--list", action="store_true", help="List scenarios and exit.")
    args = parser.parse_args(argv)

    if args.list:
        for scenario in ALL:
            print(f"{scenario.slug:24} {scenario.title}")
        return 0

    try:
        scoreboard = execute(args.only)
    except KeyboardInterrupt:
        return 130

    from pathlib import Path

    out = Path(args.out)
    history_path = Path(args.history)
    dump_json(out, scoreboard)
    history = append_history(history_path, history_point(scoreboard))
    page = render_site(scoreboard, history, Path(args.site))
    summary = scoreboard["summary"]
    fidelity = summary["fidelity_pct"]
    latency = summary["latency_ms"]
    print(
        f"fidelity {fidelity if fidelity is not None else 'n/a'}%  "
        f"pass {summary['pass']}  501 {summary['not_implemented']}  "
        f"divergent {summary['divergent']}  blocked {summary['blocked']}  "
        f"p50 {latency['p50']}ms over {latency['n']} calls",
        flush=True,
    )
    print(f"wrote {out}  {history_path}  {page}", flush=True)
    return 0


def _select(only: list[str] | None):
    if not only:
        return list(ALL)
    wanted = set(only)
    found = [scenario for scenario in ALL if scenario.slug in wanted]
    missing = wanted - {scenario.slug for scenario in found}
    if missing:
        known = ", ".join(scenario.slug for scenario in ALL)
        raise SystemExit(f"Unknown scenario {', '.join(sorted(missing))}. Known: {known}")
    return found


def _run_id() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


def _optional_float(name: str):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _read_version() -> tuple[str | None, str | None, str | None]:
    return (
        os.environ.get("ARENA_EMULATOR_VERSION") or None,
        os.environ.get("ARENA_EMULATOR_RELEASE_DATE") or None,
        os.environ.get("ARENA_EMULATOR_COMMIT") or None,
    )
