"""Static site on S3.

The shape of a marketing page: a bucket, an index document, website
hosting, and a round trip that proves the bytes survived.
"""

from arena.scenario import Scenario, error

scenario = Scenario(
    slug="static-site",
    title="Static site on S3",
    summary="Create a bucket, publish an index page, turn on website hosting, then take it down.",
    services=["s3"],
)

_INDEX = b"<!doctype html><title>Arena</title><h1>served by the emulator</h1>"


@scenario.step("Create the site bucket", service="s3", operation="CreateBucket")
def create_bucket(aws, state):
    name = state.rid("site")
    aws.client("s3").create_bucket(Bucket=name)
    state["bucket"] = name


@scenario.step("Upload index.html", service="s3", operation="PutObject")
def put_index(aws, state):
    state.need("bucket")
    aws.client("s3").put_object(
        Bucket=state["bucket"],
        Key="index.html",
        Body=_INDEX,
        ContentType="text/html",
    )


@scenario.step("Enable website hosting", service="s3", operation="PutBucketWebsite")
def put_website(aws, state):
    state.need("bucket")
    aws.client("s3").put_bucket_website(
        Bucket=state["bucket"],
        WebsiteConfiguration={"IndexDocument": {"Suffix": "index.html"}},
    )


@scenario.step("Read the index page back", service="s3", operation="GetObject")
def get_index(aws, state):
    state.need("bucket")
    body = aws.client("s3").get_object(Bucket=state["bucket"], Key="index.html")["Body"].read()
    if body != _INDEX:
        raise AssertionError(f"object body is {body[:80]!r}")


@scenario.step("List the site and find index.html", service="s3", operation="ListObjectsV2")
def list_objects(aws, state):
    state.need("bucket")
    keys = [obj["Key"] for obj in aws.client("s3").list_objects_v2(Bucket=state["bucket"]).get("Contents", [])]
    if keys != ["index.html"]:
        raise AssertionError(f"keys are {keys!r}")


@scenario.step("Read the website configuration", service="s3", operation="GetBucketWebsite")
def get_website(aws, state):
    state.need("bucket")
    suffix = aws.client("s3").get_bucket_website(Bucket=state["bucket"])["IndexDocument"]["Suffix"]
    if suffix != "index.html":
        raise AssertionError(f"index suffix is {suffix!r}")


@scenario.step("Delete the index page", service="s3", operation="DeleteObject")
def delete_object(aws, state):
    state.need("bucket")
    aws.client("s3").delete_object(Bucket=state["bucket"], Key="index.html")


@scenario.step("Delete the bucket", service="s3", operation="DeleteBucket")
def delete_bucket(aws, state):
    state.need("bucket")
    aws.client("s3").delete_bucket(Bucket=state["bucket"])


@scenario.step(
    "The deleted bucket is gone",
    service="s3",
    operation="HeadBucket",
    expect=error("404"),
)
def head_gone(aws, state):
    state.need("bucket")
    aws.client("s3").head_bucket(Bucket=state["bucket"])
