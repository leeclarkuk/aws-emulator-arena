import json
from pathlib import Path

import pytest

from arena.aws import check_environment


def _write_emulator(home: Path, key: str = "EMULATOR0123456789AB") -> None:
    port = home / ".aws" / "emulator" / "9297"
    port.mkdir(parents=True)
    (port / "emulator_credentials").write_text(
        "[default]\naws_access_key_id=" + key + "\naws_secret_access_key=ABCDEF\n",
        encoding="utf-8",
    )
    (port / "ca.pem").write_text("cert\n", encoding="utf-8")


def _env(monkeypatch, home: Path, **extra):
    monkeypatch.setenv("HOME", str(home))
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_ROLE_ARN",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://127.0.0.1:9297")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(home / ".aws/emulator/9297/emulator_credentials"))
    monkeypatch.setenv("AWS_CA_BUNDLE", str(home / ".aws/emulator/9297/ca.pem"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    for key, value in extra.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def test_guard_accepts_emulator_files(tmp_path, monkeypatch):
    _write_emulator(tmp_path)
    _env(monkeypatch, tmp_path)
    assert check_environment() == "https://127.0.0.1:9297"


def test_guard_rejects_real_looking_key(tmp_path, monkeypatch):
    _write_emulator(tmp_path, key="NOTANEMULATORKEY123")
    _env(monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="EMULATOR"):
        check_environment()


def test_guard_rejects_ambient_credentials(tmp_path, monkeypatch):
    _write_emulator(tmp_path)
    _env(monkeypatch, tmp_path, AWS_ACCESS_KEY_ID="EMULATOR0123456789AB")
    with pytest.raises(SystemExit, match="AWS_ACCESS_KEY_ID"):
        check_environment()


def test_guard_rejects_non_loopback(tmp_path, monkeypatch):
    _write_emulator(tmp_path)
    _env(monkeypatch, tmp_path, AWS_ENDPOINT_URL="https://s3.us-east-1.amazonaws.com")
    with pytest.raises(SystemExit, match="127.0.0.1"):
        check_environment()


def test_guard_rejects_credentials_outside_emulator_dir(tmp_path, monkeypatch):
    _write_emulator(tmp_path)
    outside = tmp_path / "stolen"
    outside.write_text("[default]\naws_access_key_id=EMULATOR0123456789AB\n", encoding="utf-8")
    _env(monkeypatch, tmp_path, AWS_SHARED_CREDENTIALS_FILE=str(outside))
    with pytest.raises(SystemExit, match="AWS_SHARED_CREDENTIALS_FILE"):
        check_environment()


def test_render_escapes_markup(tmp_path):
    from arena.render import render_site

    scoreboard = {
        "schema": 1,
        "generated_at": "2026-11-14T00:00:00Z",
        "emulator": {"version": "1.0.364", "account": "000000000000", "startup_ms": 1, "rss_mb": 1},
        "summary": {
            "scenarios": 1,
            "steps": 1,
            "pass": 0,
            "not_implemented": 1,
            "divergent": 0,
            "blocked": 0,
            "fidelity": 0,
            "fidelity_pct": 0,
            "latency_ms": {"n": 0, "min": None, "mean": None, "p50": None, "p95": None, "max": None},
        },
        "scenarios": [],
        "services": [],
        "wall_of_501": [{"detail": "</script><script>alert(1)</script>"}],
        "divergences": [],
        "calls": [{"service": "s3", "operation": "ListBuckets", "http_status": 200, "error_code": None, "latency_ms": 1}],
    }
    page = render_site(scoreboard, {"runs": []}, tmp_path)
    html = page.read_text(encoding="utf-8")
    report = html.split('id="arena-report"', 1)[1].split("</script>", 1)[0]
    assert "<script>alert" not in html
    assert "\\u003c/script>" in report
    assert '"calls"' not in report
    assert 'href="latest.json"' in html
    assert "../scoreboard/latest.json" not in html
    assert 'rel="canonical" href="https://leeclarkuk.github.io/aws-emulator-arena/"' in html
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'property="og:url" content="https://leeclarkuk.github.io/aws-emulator-arena/"' in html
    assert 'property="og:image" content="https://leeclarkuk.github.io/aws-emulator-arena/og.png"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert 'type="application/atom+xml"' in html
    assert 'href="feed.xml"' in html
    assert 'type="application/rss+xml"' in html
    assert (tmp_path / "gallery.html").is_file()
    assert (tmp_path / "feed.xml").is_file()
    assert (tmp_path / "rss.xml").is_file()
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["summary"]["fidelity_pct"] == 0
    assert latest["wall_of_501"][0]["detail"].startswith("</script>")
    from PIL import Image

    with Image.open(tmp_path / "og.png") as image:
        assert image.size == (1200, 630)
