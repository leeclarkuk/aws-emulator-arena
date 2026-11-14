"""A boto3 session that can only talk to a local AWS Emulator.

The arena refuses to start unless the endpoint is loopback HTTPS and the
credentials file is the one the emulator just generated. Requests never
carry ambient AWS keys, web-identity tokens, or a profile.
"""

from __future__ import annotations

import os
from configparser import ConfigParser
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
)

# Network and credential failures mean we are not measuring the emulator.
FATAL = (EndpointConnectionError, NoCredentialsError, PartialCredentialsError)

CLIENT_CONFIG = Config(
    retries={"max_attempts": 1, "mode": "standard"},
    connect_timeout=3,
    read_timeout=30,
    user_agent_extra="aws-emulator-arena",
)

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_FORBIDDEN_ENV = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
)


class Aws:
    def __init__(self, session, endpoint: str, identity: dict):
        self.session = session
        self.endpoint = endpoint
        self.identity = identity

    def client(self, service: str, **kwargs):
        endpoint = kwargs.pop("endpoint_url", self.endpoint)
        host = urlparse(endpoint).hostname
        if host not in _LOOPBACK:
            raise SystemExit(f"Refusing to create a {service} client for non-loopback endpoint {endpoint}")
        return self.session.client(
            service,
            endpoint_url=endpoint,
            region_name="us-east-1",
            config=CLIENT_CONFIG,
            **kwargs,
        )


def check_environment() -> str:
    """Fail closed before any AWS call. Returns the emulator endpoint URL."""

    for name in _FORBIDDEN_ENV:
        if os.environ.get(name):
            raise SystemExit(
                f"Refusing to run: {name} is set. Unset it so the arena can only "
                "use credentials the emulator generated."
            )

    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or parsed.hostname not in _LOOPBACK or not parsed.port:
        raise SystemExit(
            "Refusing to run: AWS_ENDPOINT_URL must be https on 127.0.0.1, localhost, or ::1 "
            f"(got {endpoint!r})."
        )
    if "amazonaws.com" in endpoint or "aws.amazon.com" in endpoint:
        raise SystemExit("Refusing to run: endpoint looks like real AWS.")

    if os.environ.get("AWS_EC2_METADATA_DISABLED", "").lower() != "true":
        raise SystemExit("Refusing to run: set AWS_EC2_METADATA_DISABLED=true so IMDS cannot supply keys.")

    cred_path = os.path.abspath(os.path.expanduser(os.environ.get("AWS_SHARED_CREDENTIALS_FILE", "")))
    ca_path = os.path.abspath(os.path.expanduser(os.environ.get("AWS_CA_BUNDLE", "")))
    home = os.path.abspath(os.path.expanduser("~/.aws/emulator"))
    port_dir = os.path.join(home, str(parsed.port))
    if os.path.commonpath([cred_path, port_dir]) != port_dir:
        raise SystemExit(
            "Refusing to run: AWS_SHARED_CREDENTIALS_FILE is not the emulator file for this port."
        )
    if os.path.basename(ca_path) != "ca.pem" or os.path.commonpath([ca_path, port_dir]) != port_dir:
        raise SystemExit("Refusing to run: AWS_CA_BUNDLE is not the emulator ca.pem for this port.")

    key_id = _read_access_key_id(cred_path)
    if not key_id.startswith("EMULATOR"):
        raise SystemExit(
            "Refusing to run: the credentials file does not hold an emulator access key "
            "(keys the emulator generates start with EMULATOR)."
        )
    return endpoint


def check_identity(session, endpoint: str) -> dict:
    sts = session.client("sts", endpoint_url=endpoint, region_name="us-east-1", config=CLIENT_CONFIG)
    try:
        ident = sts.get_caller_identity()
    except FATAL:
        raise
    except ClientError as exc:
        raise SystemExit(f"Refusing to run: GetCallerIdentity failed ({exc})") from exc
    account = ident.get("Account", "")
    arn = ident.get("Arn", "")
    if account != "000000000000":
        raise SystemExit(
            f"Refusing to run: caller account is {account}, not the emulator account 000000000000."
        )
    if not arn.startswith("arn:aws:iam::000000000000:"):
        raise SystemExit(f"Refusing to run: caller {arn} is not in the emulator account.")
    return {"account": account, "arn": arn, "user_id": ident.get("UserId", "")}


def open_session() -> Aws:
    endpoint = check_environment()
    session = boto3.Session()
    identity = check_identity(session, endpoint)
    return Aws(session, endpoint, identity)


def _read_access_key_id(path: str) -> str:
    parser = ConfigParser(interpolation=None)
    try:
        read = parser.read(path)
    except Exception as exc:
        raise SystemExit(f"Refusing to run: could not read the emulator credentials file ({exc})") from exc
    if not read or not parser.has_option("default", "aws_access_key_id"):
        raise SystemExit("Refusing to run: emulator credentials file has no default access key.")
    return parser.get("default", "aws_access_key_id").strip()
