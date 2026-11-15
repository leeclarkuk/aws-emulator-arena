"""Feed generation, step transitions, and the divergence gallery."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from botocore.exceptions import ClientError

from arena.feed import detect_transitions, render_atom, render_rss
from arena.gallery import anchor_id, gallery_cards, render_gallery_page, response_headline
from arena.redact import public_copy
from arena.render import render_site
from arena.report import build_scoreboard, history_point, is_meaningful_change
from arena.runner import run_scenario
from arena.scenario import Scenario, State
from arena.scenarios import ALL
from arena.scenarios.cicd_control_plane import scenario as cicd

ROOT = Path(__file__).resolve().parents[1]
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def _run(version, when, steps):
    return {
        "generated_at": when,
        "emulator_version": version,
        "emulator_commit": "abc1234",
        "fidelity_pct": 50,
        "pass": 1,
        "not_implemented": 1,
        "divergent": 0,
        "step_outcomes": steps,
    }


def _step(scenario, title, outcome, service="codebuild", operation="BatchGetBuilds"):
    return {
        "scenario": scenario,
        "scenario_title": scenario,
        "title": title,
        "service": service,
        "operation": operation,
        "outcome": outcome,
    }


def test_public_copy_redacts_and_trims():
    copied = public_copy(
        {
            "buildStatus": "SUCCEEDED",
            "logs": None,
            "SecretAccessKey": "wJalrXUtnFEMI",
            "session_token": "tok",
            "ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": "abc"},
            "note": "x" * 300,
            "phases": list(range(12)),
        }
    )
    assert copied["buildStatus"] == "SUCCEEDED"
    assert copied["logs"] is None
    assert copied["SecretAccessKey"] == "[redacted]"
    assert copied["session_token"] == "[redacted]"
    assert "ResponseMetadata" not in copied
    assert copied["httpStatus"] == 200
    assert copied["note"].endswith("...")
    assert len(copied["note"]) == 243
    assert copied["phases"][-1] == "... 4 more"


def test_transitions_cover_outcome_changes_and_new_versions():
    history = {
        "runs": [
            _run(
                "1.0.1",
                "2026-11-14T00:00:00Z",
                [
                    _step("cicd-control-plane", "The build recorded the buildspec output", "pass"),
                    _step("finops-cost-report", "Ask Cost Explorer for the month", "not_implemented", "ce", "GetCostAndUsage"),
                ],
            ),
            _run(
                "1.0.1",
                "2026-11-14T01:00:00Z",
                [
                    _step("cicd-control-plane", "The build recorded the buildspec output", "pass"),
                    _step("finops-cost-report", "Ask Cost Explorer for the month", "not_implemented", "ce", "GetCostAndUsage"),
                ],
            ),
            _run(
                "1.0.2",
                "2026-11-14T02:00:00Z",
                [
                    _step("cicd-control-plane", "The build recorded the buildspec output", "divergent"),
                    _step("finops-cost-report", "Ask Cost Explorer for the month", "pass", "ce", "GetCostAndUsage"),
                ],
            ),
        ]
    }
    events = detect_transitions(history)
    kinds = [(event["kind"], event.get("emulator_version"), event.get("from"), event.get("to")) for event in events]
    assert kinds == [
        ("version", "1.0.2", None, None),
        ("step", "1.0.2", "pass", "divergent"),
        ("step", "1.0.2", "not_implemented", "pass"),
    ]
    codebuild = events[1]
    assert codebuild["anchor"] == anchor_id(
        "cicd-control-plane", "The build recorded the buildspec output"
    )
    assert codebuild["operation"] == "BatchGetBuilds"


def test_a_run_without_step_names_does_not_invent_transitions():
    named = [_step("demo", "List accounts", "not_implemented", "organizations", "ListAccounts")]
    history = {
        "runs": [
            {"generated_at": "2026-11-14T00:00:00Z", "emulator_version": "1.0.364", "emulator_commit": "a"},
            {"generated_at": "2026-11-14T01:00:00Z", "emulator_version": "1.0.365", "emulator_commit": "b"},
            _run("1.0.365", "2026-11-14T02:00:00Z", named),
            _run("1.0.366", "2026-11-14T03:00:00Z", [
                _step("demo", "List accounts", "pass", "organizations", "ListAccounts"),
            ]),
        ]
    }
    events = detect_transitions(history)
    assert [event["kind"] for event in events] == ["version", "version", "step"]
    assert events[0]["emulator_version"] == "1.0.365"
    assert events[1]["emulator_version"] == "1.0.366"
    assert events[2]["from"] == "not_implemented"
    assert events[2]["to"] == "pass"


def test_committed_history_emits_one_entry_per_new_version():
    history = json.loads((ROOT / "scoreboard" / "history.json").read_text(encoding="utf-8"))
    events = detect_transitions(history)
    seen = []
    for run in history["runs"]:
        version = run["emulator_version"]
        if version not in seen:
            seen.append(version)
    assert [event["emulator_version"] for event in events if event["kind"] == "version"] == seen[1:]
    assert all(event["kind"] != "step" for event in events)


def test_atom_and_rss_link_a_divergent_step_to_its_card():
    history = {
        "runs": [
            _run(
                "1.0.1",
                "2026-11-14T00:00:00Z",
                [_step("cicd-control-plane", "The build recorded the buildspec output", "pass")],
            ),
            _run(
                "1.0.2",
                "2026-11-14T02:00:00Z",
                [_step("cicd-control-plane", "The build recorded the buildspec output", "divergent")],
            ),
        ]
    }
    anchor = anchor_id("cicd-control-plane", "The build recorded the buildspec output")
    atom = render_atom(history, anchors={anchor}, updated="2026-11-14T02:00:00Z")
    rss = render_rss(history, anchors={anchor}, updated="2026-11-14T02:00:00Z")
    feed = ET.fromstring(atom)
    assert feed.tag == "{http://www.w3.org/2005/Atom}feed"
    entries = feed.findall("a:entry", ATOM)
    assert len(entries) == 2
    titles = [entry.findtext("a:title", namespaces=ATOM) for entry in entries]
    assert titles[0].startswith("Emulator 1.0.2")
    assert "changed from pass to divergent" in titles[1]
    link = entries[1].find("a:link", ATOM).attrib["href"]
    assert link.endswith(f"/gallery.html#{anchor}")
    assert "<script>" not in atom
    ids = [entry.findtext("a:id", namespaces=ATOM) for entry in entries]
    assert len(ids) == len(set(ids))

    channel = ET.fromstring(rss)
    assert channel.tag == "rss"
    assert channel.attrib["version"] == "2.0"
    items = channel.findall("./channel/item")
    assert len(items) == 2
    assert items[1].findtext("link").endswith(f"/gallery.html#{anchor}")
    assert "Gallery card:" in items[1].findtext("description")
    assert items[0].findtext("link").endswith("/")


def test_feed_escapes_markup_and_points_a_fixed_step_at_the_board():
    history = {
        "runs": [
            _run("1.0.1", "2026-11-14T00:00:00Z", [_step("demo", "Odd <tag>", "divergent", "s3", "GetObject")]),
            _run("1.0.2", "2026-11-14T01:00:00Z", [_step("demo", "Odd <tag>", "pass", "s3", "GetObject")]),
        ]
    }
    atom = render_atom(history, anchors=set(), updated="2026-11-14T01:00:00Z")
    assert "<tag>" not in atom
    assert "&lt;tag&gt;" in atom
    feed = ET.fromstring(atom)
    entry = feed.findall("a:entry", ATOM)[-1]
    assert entry.find("a:link", ATOM).attrib["href"].endswith("/")


def test_simulation_headline_names_the_decision_and_the_real_call():
    headline = response_headline(
        {
            "EvalActionName": "s3:ListAllMyBuckets",
            "EvalDecision": "implicitDeny",
            "ListBuckets": "allowed",
        }
    )
    assert headline == (
        "EvalDecision implicitDeny for s3:ListAllMyBuckets, and ListBuckets was allowed"
    )


def test_codebuild_card_shows_the_fake_success():
    step = next(item for item in cicd.steps if item.operation == "BatchGetBuilds" and "buildspec" in item.title)
    state = State("cf3164f1")
    state["marker"] = "arena-marker-cf3164f1"
    state["build"] = {
        "buildStatus": "SUCCEEDED",
        "logs": None,
        "phases": [
            {"phaseType": "SUBMITTED", "phaseStatus": "SUCCEEDED", "durationInSeconds": 0},
            {"phaseType": "BUILD", "phaseStatus": "SUCCEEDED", "durationInSeconds": 0},
        ],
    }
    try:
        step.fn(None, state)
    except AssertionError as exc:
        assert "logs=None" in str(exc)
        assert "durationInSeconds=0" in str(exc)
    else:
        raise AssertionError("the fake success should fail the step")
    assert state.observed["buildStatus"] == "SUCCEEDED"
    assert state.observed["logs"] is None
    assert state.observed["phases"][1]["durationInSeconds"] == 0
    assert response_headline(state.observed) == "SUCCEEDED, logs null, BUILD phase 0 seconds"
    assert "buildspec" in step.aws_would
    assert "\u2014" not in step.aws_would


def test_runner_keeps_observed_fields_only_when_the_step_does_not_pass():
    scenario = Scenario(slug="demo", title="Demo", summary="s", services=["codebuild"])

    @scenario.step(
        "The build recorded the buildspec output",
        service="codebuild",
        operation="BatchGetBuilds",
        aws_would="On AWS the BUILD phase runs.",
    )
    def build_logs(aws, state):
        state.observe(
            {
                "buildStatus": "SUCCEEDED",
                "logs": None,
                "phases": [{"phaseType": "BUILD", "durationInSeconds": 0}],
                "SecretAccessKey": "super-secret",
            }
        )
        raise AssertionError("build status is SUCCEEDED; BUILD durationInSeconds=0, logs=None")

    @scenario.step("List accounts", service="organizations", operation="ListAccounts", aws_would="On AWS, accounts come back.")
    def list_accounts(aws, state):
        raise ClientError(
            {
                "Error": {"Code": "NotImplemented", "Message": "operation ListAccounts is scaffolded"},
                "ResponseMetadata": {"HTTPStatusCode": 501},
            },
            "ListAccounts",
        )

    @scenario.step("Create a key", service="iam", operation="CreateAccessKey")
    def create_key(aws, state):
        state.observe({"SecretAccessKey": "should-not-stick"})

    result = run_scenario(scenario, aws=None, calls=[])
    divergent, missing, passed = result.steps
    assert divergent.outcome == "divergent"
    assert divergent.observed["buildStatus"] == "SUCCEEDED"
    assert divergent.observed["logs"] is None
    assert divergent.observed["phases"][0]["durationInSeconds"] == 0
    assert divergent.observed["SecretAccessKey"] == "[redacted]"
    assert missing.outcome == "not_implemented"
    assert missing.observed["Error"]["Code"] == "NotImplemented"
    assert missing.observed["httpStatus"] == 501
    assert passed.outcome == "pass"
    assert passed.observed is None


def test_gallery_permalink_and_first_seen():
    board = _board()
    history = {
        "runs": [
            {
                "generated_at": "2026-11-14T08:48:42Z",
                "emulator_version": "1.0.364",
                "emulator_commit": "7496e0fe6a47c52c476745eafdf5f7a45815a659",
                "step_outcomes": [
                    {
                        "scenario": "cicd-control-plane",
                        "title": "The build recorded the buildspec output",
                        "outcome": "divergent",
                    }
                ],
            }
        ]
    }
    cards = gallery_cards(board, history)
    codebuild = next(card for card in cards if card["operation"] == "BatchGetBuilds")
    assert codebuild["anchor"] == "cicd-control-plane--the-build-recorded-the-buildspec-output"
    assert codebuild["first_is_exact"] is True
    assert codebuild["first"]["emulator_version"] == "1.0.364"
    assert codebuild["headline"] == "SUCCEEDED, logs null, BUILD phase 0 seconds"
    gaps = [card for card in cards if card["outcome"] == "not_implemented"]
    assert gaps and gaps[0]["first_is_exact"] is False
    page = render_gallery_page(board, history)
    assert f'id="{codebuild["anchor"]}"' in page
    assert f'href="#{codebuild["anchor"]}"' in page
    assert "SUCCEEDED, logs null, BUILD phase 0 seconds" in page
    assert '"logs": null' in page
    assert "durationInSeconds" in page
    assert "What AWS would do" in page
    assert "On AWS, a build that reports SUCCEEDED" in page
    assert "14 Nov 2026, 08:48 UTC" in page
    assert "Earlier runs did not name the step." in page
    assert "type=\"application/atom+xml\"" in page
    assert "<script>alert" not in page


def test_gallery_fallback_timestamp_comes_from_history_not_the_live_clock():
    board = _board()
    board["generated_at"] = "2026-11-14T21:07:00Z"
    history = {
        "runs": [
            {
                "generated_at": "2026-11-14T20:08:11Z",
                "emulator_version": "1.0.385",
                "emulator_commit": "813af480bf7f16d5418b64e4f5644a74a7da11c5",
            }
        ]
    }
    cards = gallery_cards(board, history)
    assert all(card["first_is_exact"] is False for card in cards)
    assert all(card["first"]["generated_at"] == "2026-11-14T20:08:11Z" for card in cards)
    # A timing-only re-render must not count as a meaningful scoreboard change.
    again = json.loads(json.dumps(board))
    again["generated_at"] = "2026-11-14T22:07:00Z"
    again["emulator"] = {**again["emulator"], "startup_ms": 999, "rss_mb": 10}
    assert is_meaningful_change(board, again) is False


def test_render_writes_gallery_and_feeds(tmp_path):
    board = _board()
    board["scenarios"][0]["steps"][0]["detail"] = "</script><script>alert(1)</script>"
    history = {"runs": [history_point(board)]}
    # The second point is what makes a transition. Give the first a pass.
    history["runs"].insert(
        0,
        {
            "generated_at": "2026-11-14T00:00:00Z",
            "emulator_version": "1.0.364",
            "emulator_commit": "7496e0fe",
            "fidelity_pct": 100,
            "pass": 1,
            "not_implemented": 0,
            "divergent": 0,
            "step_outcomes": [
                {
                    "scenario": "cicd-control-plane",
                    "scenario_title": "CI control plane",
                    "title": "The build recorded the buildspec output",
                    "service": "codebuild",
                    "operation": "BatchGetBuilds",
                    "outcome": "pass",
                }
            ],
        },
    )
    render_site(board, history, tmp_path)
    html = (tmp_path / "gallery.html").read_text(encoding="utf-8")
    atom = (tmp_path / "feed.xml").read_text(encoding="utf-8")
    rss = (tmp_path / "rss.xml").read_text(encoding="utf-8")
    assert "<script>alert" not in html
    assert "&lt;/script&gt;" in html
    assert "changed from pass to divergent" in atom
    assert "gallery.html#cicd-control-plane--the-build-recorded-the-buildspec-output" in atom
    ET.fromstring(atom)
    ET.fromstring(rss)
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["summary"]["fidelity_pct"] == board["summary"]["fidelity_pct"]
    assert latest["emulator"]["version"] == board["emulator"]["version"]


def test_registered_steps_have_unique_anchors_and_gallery_copy_on_known_gaps():
    anchors = []
    for scenario in ALL:
        for step in scenario.steps:
            anchors.append(anchor_id(scenario.slug, step.title))
    assert len(anchors) == len(set(anchors))
    expected = {
        ("cicd-control-plane", "BatchGetBuilds", "The build recorded the buildspec output"),
        ("platform-inventory", "CreatePermissionSet", "Create a permission set"),
        ("iam-guardrails", "SimulatePrincipalPolicy", "The built-in principal agrees with policy simulation"),
        ("platform-inventory", "ListAccounts", "List accounts in the organization"),
        ("finops-cost-report", "GetCostAndUsage", "Ask Cost Explorer for the month"),
    }
    found = {
        (scenario.slug, step.operation, step.title)
        for scenario in ALL
        for step in scenario.steps
        if step.aws_would
    }
    assert expected <= found


def _board():
    step = next(item for item in cicd.steps if "buildspec" in item.title)
    state = State("cf3164f1")
    state["marker"] = "arena-marker-cf3164f1"
    state["build"] = {
        "buildStatus": "SUCCEEDED",
        "logs": None,
        "phases": [{"phaseType": "BUILD", "phaseStatus": "SUCCEEDED", "durationInSeconds": 0}],
    }
    try:
        step.fn(None, state)
    except AssertionError:
        pass
    scenario = Scenario(slug="cicd-control-plane", title="CI control plane", summary="builds", services=["codebuild"])

    class _Result:
        def __init__(self):
            self.title = step.title
            self.service = "codebuild"
            self.operation = "BatchGetBuilds"
            self.outcome = "divergent"
            self.latency_ms = 0.03
            self.detail = (
                "build status is SUCCEEDED but nothing recorded arena-marker-cf3164f1; "
                "BUILD durationInSeconds=0, logs=None"
            )
            self.http_status = None
            self.error_code = None
            self.aws_would = step.aws_would
            self.observed = state.observed

    class _Gap:
        def __init__(self):
            self.title = "List accounts in the organization"
            self.service = "organizations"
            self.operation = "ListAccounts"
            self.outcome = "not_implemented"
            self.latency_ms = 4.0
            self.detail = "operation ListAccounts is scaffolded but not implemented in this emulator"
            self.http_status = 501
            self.error_code = "NotImplemented"
            self.aws_would = "On AWS, ListAccounts returns the accounts in the organisation, including the management account."
            self.observed = {
                "Error": {
                    "Code": "NotImplemented",
                    "Message": self.detail,
                },
                "httpStatus": 501,
            }

    gap_scenario = Scenario(
        slug="platform-inventory",
        title="Platform inventory",
        summary="accounts",
        services=["organizations"],
    )
    return build_scoreboard(
        meta={
            "generated_at": "2026-11-14T20:08:11Z",
            "emulator": {
                "version": "1.0.385",
                "commit": "813af480bf7f16d5418b64e4f5644a74a7da11c5",
                "startup_ms": 310,
                "rss_mb": 298.5,
            },
        },
        scenarios=[_ScenarioView(scenario, [_Result()]), _ScenarioView(gap_scenario, [_Gap()])],
        calls=[],
    )


class _ScenarioView:
    def __init__(self, scenario, steps):
        self.slug = scenario.slug
        self.title = scenario.title
        self.summary = scenario.summary
        self.services = scenario.services
        self.steps = steps
