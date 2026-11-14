"""Assemble the scoreboard document and append a history point."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from arena.scoring import counts, fidelity, latency_stats, round_ms

SERVICE_NAMES = {
    "s3": "S3",
    "dynamodb": "DynamoDB",
    "sqs": "SQS",
    "lambda": "Lambda",
    "iam": "IAM",
    "sts": "STS",
    "cloudformation": "CloudFormation",
    "organizations": "Organizations",
    "ce": "Cost Explorer",
    "budgets": "Budgets",
    "identitystore": "Identity Store",
    "sso-admin": "IAM Identity Center",
    "codebuild": "CodeBuild",
    "codepipeline": "CodePipeline",
    "logs": "CloudWatch Logs",
}


def service_name(service: str) -> str:
    return SERVICE_NAMES.get(service, service)


def _step_dict(step) -> dict:
    return {
        "title": step.title,
        "service": step.service,
        "service_name": service_name(step.service),
        "operation": step.operation,
        "outcome": step.outcome,
        "latency_ms": round_ms(step.latency_ms),
        "detail": step.detail,
        "http_status": step.http_status,
        "error_code": step.error_code,
    }


def _stats(samples) -> dict:
    raw = latency_stats(samples)
    return {key: (round_ms(value) if isinstance(value, float) else value) for key, value in raw.items()}


def build_scoreboard(*, meta: dict, scenarios: list, calls: list[dict]) -> dict:
    steps = [step for scenario in scenarios for step in scenario.steps]
    tally = counts(step.outcome for step in steps)
    score = fidelity(tally)
    by_service: dict[str, list] = {}
    for step in steps:
        by_service.setdefault(step.service, []).append(step)

    services = []
    for service, group in by_service.items():
        service_tally = counts(step.outcome for step in group)
        service_score = fidelity(service_tally)
        samples = [call["latency_ms"] for call in calls if call["service"] == service]
        services.append(
            {
                "service": service,
                "name": service_name(service),
                "fidelity": service_score,
                "fidelity_pct": _pct(service_score),
                **service_tally,
                "latency_ms": _stats(samples),
            }
        )
    services.sort(key=lambda row: (row["fidelity"] is None, row["fidelity"] if row["fidelity"] is not None else 1, row["name"]))

    wall = [
        {
            "scenario": scenario.slug,
            "scenario_title": scenario.title,
            "service": step.service,
            "service_name": service_name(step.service),
            "operation": step.operation,
            "title": step.title,
            "detail": step.detail,
        }
        for scenario in scenarios
        for step in scenario.steps
        if step.outcome == "not_implemented"
    ]
    divergences = [
        {
            "scenario": scenario.slug,
            "scenario_title": scenario.title,
            "service": step.service,
            "service_name": service_name(step.service),
            "operation": step.operation,
            "title": step.title,
            "detail": step.detail,
            "http_status": step.http_status,
            "error_code": step.error_code,
        }
        for scenario in scenarios
        for step in scenario.steps
        if step.outcome == "divergent"
    ]

    call_samples = [call["latency_ms"] for call in calls]
    scenario_rows = []
    for scenario in scenarios:
        scenario_tally = counts(step.outcome for step in scenario.steps)
        scenario_score = fidelity(scenario_tally)
        scenario_rows.append(
            {
                "slug": scenario.slug,
                "title": scenario.title,
                "summary": scenario.summary,
                "services": scenario.services,
                "service_names": [service_name(service) for service in scenario.services],
                "fidelity": scenario_score,
                "fidelity_pct": _pct(scenario_score),
                **scenario_tally,
                "steps": [_step_dict(step) for step in scenario.steps],
            }
        )

    return {
        "schema": 1,
        "generated_at": meta["generated_at"],
        "emulator": meta["emulator"],
        "summary": {
            "scenarios": len(scenarios),
            "steps": len(steps),
            **tally,
            "fidelity": score,
            "fidelity_pct": _pct(score),
            "latency_ms": _stats(call_samples),
        },
        "scenarios": scenario_rows,
        "services": services,
        "wall_of_501": wall,
        "divergences": divergences,
        "calls": [
            {
                "service": call["service"],
                "operation": call["operation"],
                "http_status": call["http_status"],
                "error_code": call["error_code"],
                "latency_ms": round_ms(call["latency_ms"]),
            }
            for call in calls
        ],
    }


def history_point(scoreboard: dict) -> dict:
    summary = scoreboard["summary"]
    emulator = scoreboard["emulator"]
    return {
        "generated_at": scoreboard["generated_at"],
        "emulator_version": emulator.get("version"),
        "emulator_commit": emulator.get("commit"),
        "fidelity": summary["fidelity"],
        "fidelity_pct": summary["fidelity_pct"],
        "steps": summary["steps"],
        "pass": summary["pass"],
        "not_implemented": summary["not_implemented"],
        "divergent": summary["divergent"],
        "blocked": summary["blocked"],
        "p50_ms": summary["latency_ms"]["p50"],
        "startup_ms": emulator.get("startup_ms"),
        "rss_mb": emulator.get("rss_mb"),
        "services": {row["service"]: row["fidelity_pct"] for row in scoreboard["services"]},
    }


def append_history(path: Path, point: dict, *, limit: int = 400) -> dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"runs": []}
    runs = list(data.get("runs") or [])
    runs.append(point)
    data = {"runs": runs[-limit:]}
    dump_json(path, data)
    return data


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _pct(score: float | None) -> int | None:
    if score is None:
        return None
    return int(round(score * 100))
