"""IAM guardrails.

What a security review actually checks on day one: a user with no policy
is denied, an explicit deny wins, an allow is required, a bucket policy
is enforced, and the emulator's own principal agrees with policy simulation.
"""

import json

from botocore.exceptions import ClientError

from arena.scenario import Scenario, error

scenario = Scenario(
    slug="iam-guardrails",
    title="IAM guardrails",
    summary="Implicit deny, explicit deny, allow, a bucket policy, and the built-in emulator principal.",
    services=["iam", "s3"],
)

_DENY_LIST = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Deny", "Action": "s3:ListAllMyBuckets", "Resource": "*"}],
    }
)
_ALLOW_LIST = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "s3:ListAllMyBuckets", "Resource": "*"}],
    }
)


def _user_s3(aws, state):
    return aws.client(
        "s3",
        aws_access_key_id=state["access_key"],
        aws_secret_access_key=state["secret_key"],
    )


@scenario.step("Create a user with no policies", service="iam", operation="CreateUser")
def create_user(aws, state):
    name = state.rid("nobody")
    aws.client("iam").create_user(UserName=name)
    state["user"] = name


@scenario.step("Create an access key for that user", service="iam", operation="CreateAccessKey")
def create_key(aws, state):
    state.need("user")
    key = aws.client("iam").create_access_key(UserName=state["user"])["AccessKey"]
    state["access_key"] = key["AccessKeyId"]
    state["secret_key"] = key["SecretAccessKey"]
    if not str(state["access_key"]).startswith("EMULATOR"):
        raise AssertionError("user access key was not issued by the emulator")


@scenario.step(
    "A user with no policy cannot list buckets",
    service="s3",
    operation="ListBuckets",
    expect=error("AccessDenied"),
)
def implicit_deny(aws, state):
    state.need("access_key", "secret_key")
    _user_s3(aws, state).list_buckets()


@scenario.step("Attach an explicit deny", service="iam", operation="PutUserPolicy")
def put_deny(aws, state):
    state.need("user")
    aws.client("iam").put_user_policy(UserName=state["user"], PolicyName="deny-list", PolicyDocument=_DENY_LIST)


@scenario.step(
    "The explicit deny blocks the user",
    service="s3",
    operation="ListBuckets",
    expect=error("AccessDenied", contains="explicit deny"),
)
def explicit_deny(aws, state):
    state.need("access_key", "secret_key")
    _user_s3(aws, state).list_buckets()


@scenario.step("An allow policy lets a second user list buckets", service="iam", operation="PutUserPolicy")
def allow_second_user(aws, state):
    iam = aws.client("iam")
    name = state.rid("reader")
    iam.create_user(UserName=name)
    key = iam.create_access_key(UserName=name)["AccessKey"]
    iam.put_user_policy(UserName=name, PolicyName="allow-list", PolicyDocument=_ALLOW_LIST)
    listed = aws.client(
        "s3",
        aws_access_key_id=key["AccessKeyId"],
        aws_secret_access_key=key["SecretAccessKey"],
    ).list_buckets()
    if "Buckets" not in listed:
        raise AssertionError("ListBuckets returned no Buckets list")


@scenario.step(
    "A bucket policy deny is enforced",
    service="s3",
    operation="GetObject",
    expect=error("AccessDenied", contains="resource-based"),
)
def bucket_policy(aws, state):
    s3 = aws.client("s3")
    bucket = state.rid("locked")
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="note.txt", Body=b"secret-to-the-scenario")
    s3.put_bucket_policy(
        Bucket=bucket,
        Policy=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "DenyRead",
                        "Effect": "Deny",
                        "Principal": "*",
                        "Action": "s3:GetObject",
                        "Resource": f"arn:aws:s3:::{bucket}/*",
                    }
                ],
            }
        ),
    )
    s3.get_object(Bucket=bucket, Key="note.txt")


@scenario.step("The built-in principal agrees with policy simulation", service="iam", operation="SimulatePrincipalPolicy")
def simulation_matches(aws, state):
    iam = aws.client("iam")
    caller = aws.identity["arn"]
    simulated = iam.simulate_principal_policy(PolicySourceArn=caller, ActionNames=["s3:ListAllMyBuckets"])
    results = simulated.get("EvaluationResults") or []
    if not results:
        raise AssertionError("SimulatePrincipalPolicy returned no evaluation")
    decision = results[0].get("EvalDecision")
    try:
        aws.client("s3").list_buckets()
        actual = "allowed"
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 501 or code == "NotImplemented":
            raise
        if code == "AccessDenied":
            actual = "denied"
        else:
            raise
    denied = {"implicitDeny", "explicitDeny"}
    allowed = {"allowed", "explicitAllow"}
    if decision in denied and actual == "allowed":
        raise AssertionError(
            f"SimulatePrincipalPolicy says {decision} for s3:ListAllMyBuckets, "
            "but the built-in emulator key listed buckets"
        )
    if decision in allowed and actual == "denied":
        raise AssertionError(
            f"SimulatePrincipalPolicy says {decision} for s3:ListAllMyBuckets, "
            "but the built-in emulator key was denied"
        )
    if decision not in denied | allowed:
        raise AssertionError(f"unexpected evaluation decision {decision!r} with actual {actual}")


@scenario.step(
    "An explicit deny applies to the built-in emulator key",
    service="s3",
    operation="ListBuckets",
    expect=error("AccessDenied", contains="explicit deny"),
)
def emulator_key_deny(aws, state):
    iam = aws.client("iam")
    # The caller is user/emulator. Pin the policy to that user, then always remove it.
    user_name = aws.identity["arn"].rsplit("/", 1)[-1]
    iam.put_user_policy(UserName=user_name, PolicyName="arena-deny-list", PolicyDocument=_DENY_LIST)
    try:
        aws.client("s3").list_buckets()
    finally:
        iam.delete_user_policy(UserName=user_name, PolicyName="arena-deny-list")
