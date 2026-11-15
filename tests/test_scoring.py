import ast

from arena.classify import Expectation, classify, error
from arena.report import build_scoreboard, history_point, is_meaningful_change
from arena.scenarios import ALL
from arena.scenarios.event_pipeline import _WORKER
from arena.scenarios.serverless_todo import _HANDLER
from arena.scoring import counts, fidelity, percentile


class _Step:
    def __init__(self, title, service, operation, outcome, detail="", latency_ms=1.0, http_status=200, error_code=None):
        self.title = title
        self.service = service
        self.operation = operation
        self.outcome = outcome
        self.detail = detail
        self.latency_ms = latency_ms
        self.http_status = http_status
        self.error_code = error_code


class _Scenario:
    def __init__(self, slug, steps):
        self.slug = slug
        self.title = slug
        self.summary = "summary"
        self.services = sorted({step.service for step in steps})
        self.steps = steps


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([], 50) is None
    assert percentile([8], 95) == 8


def test_fidelity_ignores_blocked():
    tally = counts(["pass", "pass", "not_implemented", "divergent", "blocked"])
    assert tally["blocked"] == 1
    assert fidelity(tally) == 2 / 4
    assert fidelity(counts(["blocked"])) is None


def test_classify_501_wins_over_an_expected_error():
    from botocore.exceptions import ClientError

    exc = ClientError(
        {"Error": {"Code": "NotImplemented", "Message": "nope"}, "ResponseMetadata": {"HTTPStatusCode": 501}},
        "ListAccounts",
    )
    outcome, detail, status, code = classify(exc, error("AccessDenied"))
    assert outcome == "not_implemented"
    assert status == 501
    assert code == "NotImplemented"
    assert "nope" in detail


def test_classify_expected_error_and_mismatch():
    from botocore.exceptions import ClientError

    denied = ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "explicit deny in an identity-based policy"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "ListBuckets",
    )
    assert classify(denied, error("AccessDenied", contains="explicit deny"))[0] == "pass"
    assert classify(denied, error("AccessDenied", contains="resource-based"))[0] == "divergent"
    assert classify(None, Expectation())[0] == "pass"
    assert classify(None, error("AccessDenied"))[0] == "divergent"
    assert classify(AssertionError("build stamped success"), Expectation())[0] == "divergent"


def test_scoreboard_wall_and_history_point():
    board = build_scoreboard(
        meta={
            "generated_at": "2026-11-14T00:00:00Z",
            "emulator": {"version": "1.0.364", "commit": "abc", "startup_ms": 10, "rss_mb": 1},
        },
        scenarios=[
            _Scenario(
                "demo",
                [
                    _Step("ok", "s3", "CreateBucket", "pass"),
                    _Step("missing", "ce", "GetCostAndUsage", "not_implemented", detail="scaffolded", http_status=501),
                    _Step("odd", "codebuild", "StartBuild", "divergent", detail="no logs"),
                    _Step("later", "s3", "DeleteBucket", "blocked", detail="needs bucket"),
                ],
            )
        ],
        calls=[{"service": "s3", "operation": "CreateBucket", "http_status": 200, "error_code": None, "latency_ms": 2.0}],
    )
    assert board["summary"]["fidelity_pct"] == 33
    assert board["summary"]["blocked"] == 1
    assert board["wall_of_501"][0]["operation"] == "GetCostAndUsage"
    assert board["divergences"][0]["operation"] == "StartBuild"
    by_name = {row["service"]: row for row in board["services"]}
    assert by_name["ce"]["fidelity_pct"] == 0
    assert by_name["s3"]["fidelity_pct"] == 100
    assert board["services"][0]["fidelity_pct"] == 0
    point = history_point(board)
    assert point["emulator_version"] == "1.0.364"
    assert point["not_implemented"] == 1
    assert point["step_outcomes"][2]["outcome"] == "divergent"
    assert point["step_outcomes"][2]["operation"] == "StartBuild"
    assert board["schema"] == 1
    assert board["summary"]["fidelity_pct"] == 33
    assert board["emulator"]["version"] == "1.0.364"


def _demo_board(**overrides):
    meta = {
        "generated_at": "2026-11-14T00:00:00Z",
        "emulator": {"version": "1.0.364", "commit": "abc", "startup_ms": 10, "rss_mb": 1},
    }
    meta.update({key: value for key, value in overrides.items() if key in ("generated_at",)})
    if "emulator" in overrides:
        meta["emulator"] = {**meta["emulator"], **overrides["emulator"]}
    steps = overrides.get(
        "steps",
        [
            _Step("ok", "s3", "CreateBucket", "pass", latency_ms=1.0),
            _Step("missing", "ce", "GetCostAndUsage", "not_implemented", detail="scaffolded", http_status=501),
        ],
    )
    calls = overrides.get(
        "calls",
        [{"service": "s3", "operation": "CreateBucket", "http_status": 200, "error_code": None, "latency_ms": 2.0}],
    )
    return build_scoreboard(
        meta=meta,
        scenarios=[_Scenario("demo", steps)],
        calls=calls,
    )


def test_meaningful_change_ignores_timing_only():
    base = _demo_board()
    later = _demo_board(
        generated_at="2026-11-14T01:00:00Z",
        emulator={"startup_ms": 99, "rss_mb": 42},
        calls=[{"service": "s3", "operation": "CreateBucket", "http_status": 200, "error_code": None, "latency_ms": 9.0}],
    )
    later["scenarios"][0]["steps"][0]["latency_ms"] = 9.0
    assert is_meaningful_change(None, base) is True
    assert is_meaningful_change(base, later) is False


def test_meaningful_change_detects_emulator_outcome_and_counts():
    base = _demo_board()
    assert is_meaningful_change(base, _demo_board(emulator={"version": "1.0.365"})) is True
    assert is_meaningful_change(base, _demo_board(emulator={"commit": "def"})) is True
    flipped = _demo_board(
        steps=[
            _Step("ok", "s3", "CreateBucket", "divergent", detail="wrong"),
            _Step("missing", "ce", "GetCostAndUsage", "not_implemented", detail="scaffolded", http_status=501),
        ]
    )
    assert is_meaningful_change(base, flipped) is True
    extra = _demo_board(
        steps=[
            _Step("ok", "s3", "CreateBucket", "pass"),
            _Step("missing", "ce", "GetCostAndUsage", "not_implemented", detail="scaffolded", http_status=501),
            _Step("later", "s3", "DeleteBucket", "blocked", detail="needs bucket"),
        ]
    )
    assert is_meaningful_change(base, extra) is True


def test_meaningful_change_ignores_gallery_fields():
    base = _demo_board()
    steps = [
        _Step("ok", "s3", "CreateBucket", "pass"),
        _Step("missing", "ce", "GetCostAndUsage", "not_implemented", detail="scaffolded", http_status=501),
    ]
    steps[1].aws_would = "On AWS this lists cost."
    steps[1].observed = {"Error": {"Code": "NotImplemented", "Message": "scaffolded"}, "SecretAccessKey": "hidden"}
    richer = build_scoreboard(
        meta={
            "generated_at": "2026-11-14T02:00:00Z",
            "emulator": {"version": "1.0.364", "commit": "abc", "startup_ms": 80, "rss_mb": 9},
        },
        scenarios=[_Scenario("demo", steps)],
        calls=[
            {
                "service": "ce",
                "operation": "GetCostAndUsage",
                "http_status": 501,
                "error_code": "NotImplemented",
                "latency_ms": 4.0,
                "parsed": {"SecretAccessKey": "should-not-land-in-calls"},
            }
        ],
    )
    assert is_meaningful_change(base, richer) is False
    assert richer["summary"]["fidelity_pct"] == base["summary"]["fidelity_pct"]
    assert richer["emulator"]["version"] == "1.0.364"
    step = richer["scenarios"][0]["steps"][1]
    assert step["aws_would"] == "On AWS this lists cost."
    assert step["observed"]["Error"]["Code"] == "NotImplemented"
    assert "parsed" not in richer["calls"][0]
    assert "should-not-land-in-calls" not in str(richer["calls"])


def test_scenarios_are_registered_and_handlers_parse():
    slugs = [scenario.slug for scenario in ALL]
    assert slugs == list(dict.fromkeys(slugs))
    assert "serverless-todo" in slugs
    assert "finops-cost-report" in slugs
    for scenario in ALL:
        assert scenario.steps, scenario.slug
        used = {step.service for step in scenario.steps}
        assert used == set(scenario.services), (scenario.slug, used, scenario.services)
    ast.parse(_HANDLER.format(table="arena-todos-abcd1234"))
    ast.parse(_WORKER.format(table="arena-orders-abcd1234"))
