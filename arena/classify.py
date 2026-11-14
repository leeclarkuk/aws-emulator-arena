"""Turn a step's exception into pass / not_implemented / divergent / blocked."""

from __future__ import annotations

from dataclasses import dataclass

from botocore.exceptions import ClientError


class Blocked(Exception):
    """An earlier step did not produce something this step needs."""


@dataclass(frozen=True)
class Expectation:
    kind: str = "success"  # "success" or "error"
    code: str | None = None
    contains: str | None = None


def error(code: str, contains: str | None = None) -> Expectation:
    """Expect the step to fail with this AWS error code.

    Use this for behavior that is correct when AWS says no, such as an
    implicit deny. A 501 is still recorded as not implemented.
    """

    return Expectation("error", code, contains)


def unpack_client_error(exc: ClientError) -> tuple[int | None, str, str]:
    response = exc.response or {}
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    err = response.get("Error") or {}
    code = str(err.get("Code") or "")
    message = str(err.get("Message") or "")
    return status, code, message


def is_not_implemented(status: int | None, code: str) -> bool:
    return status == 501 or code == "NotImplemented"


def classify(exc: BaseException | None, expect: Expectation) -> tuple[str, str, int | None, str | None]:
    """Return outcome, detail, http status, and error code."""

    if isinstance(exc, Blocked):
        return "blocked", str(exc), None, None

    if isinstance(exc, AssertionError):
        return "divergent", str(exc) or "assertion failed", None, None

    if isinstance(exc, ClientError):
        status, code, message = unpack_client_error(exc)
        if is_not_implemented(status, code):
            return "not_implemented", message or "Not Implemented", status, code or "NotImplemented"
        if expect.kind == "error" and code == expect.code:
            if expect.contains and expect.contains not in message:
                return (
                    "divergent",
                    f"expected {expect.code} containing {expect.contains!r}, got: {message}",
                    status,
                    code,
                )
            return "pass", message, status, code
        if expect.kind == "error":
            return (
                "divergent",
                f"expected {expect.code}, got {code or status}: {message}",
                status,
                code or None,
            )
        return "divergent", f"{code}: {message}".strip(": "), status, code or None

    if exc is not None:
        return "divergent", f"{type(exc).__name__}: {exc}", None, None

    if expect.kind == "error":
        return "divergent", f"expected {expect.code}, but the call succeeded", 200, None
    return "pass", "", 200, None
