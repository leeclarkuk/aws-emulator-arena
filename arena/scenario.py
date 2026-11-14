"""Scenario authoring. A scenario file should read like the workflow it runs."""

from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from typing import Callable

from arena.classify import Blocked, Expectation, error

__all__ = ["Blocked", "Scenario", "State", "error", "poll", "python_zip"]


class State(dict):
    """Scratch space shared by the steps of one scenario."""

    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id
        self.observed = None

    def observe(self, payload) -> None:
        """Remember the key fields of what came back, for the gallery.

        The runner keeps this only when the step does not pass, then redacts
        secret-looking fields and trims long values. Do not put keys in it.
        """

        self.observed = payload

    def rid(self, prefix: str) -> str:
        """A name unique to this run. Safe for buckets, queues, and functions."""

        return f"arena-{prefix}-{self.run_id}"

    def need(self, *keys: str):
        missing = [key for key in keys if not self.get(key)]
        if missing:
            raise Blocked("needs " + ", ".join(missing) + " from an earlier step")


@dataclass
class Step:
    title: str
    service: str
    operation: str
    expect: Expectation
    fn: Callable
    aws_would: str = ""


class Scenario:
    def __init__(self, *, slug: str, title: str, summary: str, services: list[str]):
        self.slug = slug
        self.title = title
        self.summary = summary
        self.services = list(services)
        self.steps: list[Step] = []

    def step(
        self,
        title: str,
        *,
        service: str,
        operation: str,
        expect: Expectation | None = None,
        aws_would: str | None = None,
    ):
        """Register the next step. Steps run in definition order.

        aws_would is a plain sentence about what AWS would do. The gallery
        prints it next to the response the emulator actually returned.
        """

        expectation = expect if expect is not None else Expectation()
        note = (aws_would or "").strip()

        def decorate(fn: Callable) -> Callable:
            self.steps.append(
                Step(
                    title=title,
                    service=service,
                    operation=operation,
                    expect=expectation,
                    fn=fn,
                    aws_would=note,
                )
            )
            return fn

        return decorate


def poll(fn: Callable, predicate: Callable, *, timeout: float = 15, interval: float = 0.25, description: str = "condition"):
    """Call fn until predicate(result) is true, or raise AssertionError."""

    deadline = time.monotonic() + timeout
    last = None
    while True:
        last = fn()
        if predicate(last):
            return last
        if time.monotonic() >= deadline:
            shown = repr(last)
            if len(shown) > 240:
                shown = shown[:240] + "…"
            raise AssertionError(f"timed out waiting for {description}; last={shown}")
        time.sleep(interval)


def python_zip(source: str, filename: str = "index.py") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, source)
    return buffer.getvalue()
