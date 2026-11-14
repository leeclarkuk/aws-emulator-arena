"""Infrastructure as code.

A small stack should create a real bucket and a real queue, then delete
both when the stack goes away. The check is the resources, not the stack id.
"""

import json

from botocore.exceptions import ClientError

from arena.scenario import Scenario, poll

scenario = Scenario(
    slug="cloudformation-stack",
    title="CloudFormation stack",
    summary="Deploy a bucket and a queue from a template, prove they exist, then delete the stack.",
    services=["cloudformation", "s3", "sqs"],
)


def _template(state) -> str:
    return json.dumps(
        {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Resources": {
                "Site": {
                    "Type": "AWS::S3::Bucket",
                    "Properties": {"BucketName": state.rid("cfn-site")},
                },
                "Jobs": {
                    "Type": "AWS::SQS::Queue",
                    "Properties": {"QueueName": state.rid("cfn-jobs")},
                },
            },
        }
    )


@scenario.step("Create a stack with a bucket and a queue", service="cloudformation", operation="CreateStack")
def create_stack(aws, state):
    state["stack"] = state.rid("stack")
    state["bucket"] = state.rid("cfn-site")
    state["queue"] = state.rid("cfn-jobs")
    response = aws.client("cloudformation").create_stack(StackName=state["stack"], TemplateBody=_template(state))
    if not response.get("StackId"):
        raise AssertionError("CreateStack returned no StackId")


@scenario.step("Wait until the stack is complete", service="cloudformation", operation="DescribeStacks")
def wait_complete(aws, state):
    state.need("stack")
    cfn = aws.client("cloudformation")

    def status():
        return cfn.describe_stacks(StackName=state["stack"])["Stacks"][0]["StackStatus"]

    final = poll(status, lambda value: value.endswith("COMPLETE") or value.endswith("FAILED"), description="stack settled")
    if final != "CREATE_COMPLETE":
        raise AssertionError(f"stack status is {final}")


@scenario.step("Both resources were created", service="cloudformation", operation="ListStackResources")
def list_resources(aws, state):
    state.need("stack")
    rows = aws.client("cloudformation").list_stack_resources(StackName=state["stack"])["StackResourceSummaries"]
    by_logical = {row["LogicalResourceId"]: row for row in rows}
    for logical in ("Site", "Jobs"):
        row = by_logical.get(logical)
        if not row or row.get("ResourceStatus") != "CREATE_COMPLETE":
            raise AssertionError(f"{logical} is {None if not row else row.get('ResourceStatus')}")
    state["queue_url"] = by_logical["Jobs"].get("PhysicalResourceId")


@scenario.step("The bucket from the template answers", service="s3", operation="HeadBucket")
def head_bucket(aws, state):
    state.need("bucket")
    aws.client("s3").head_bucket(Bucket=state["bucket"])


@scenario.step("The queue from the template answers", service="sqs", operation="GetQueueUrl")
def get_queue(aws, state):
    state.need("queue")
    url = aws.client("sqs").get_queue_url(QueueName=state["queue"])["QueueUrl"]
    if not url:
        raise AssertionError("GetQueueUrl returned an empty url")


@scenario.step("Delete the stack", service="cloudformation", operation="DeleteStack")
def delete_stack(aws, state):
    state.need("stack")
    aws.client("cloudformation").delete_stack(StackName=state["stack"])


@scenario.step("The stack is gone", service="cloudformation", operation="DescribeStacks")
def stack_gone(aws, state):
    state.need("stack")
    cfn = aws.client("cloudformation")
    deadline_status = {"done": False, "status": None}

    def look():
        try:
            deadline_status["status"] = cfn.describe_stacks(StackName=state["stack"])["Stacks"][0]["StackStatus"]
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            message = exc.response.get("Error", {}).get("Message", "")
            if code == "ValidationError" and "does not exist" in message:
                deadline_status["done"] = True
                return True
            raise
        return str(deadline_status["status"]).endswith("FAILED")

    poll(look, lambda done: bool(done), description="stack deleted")
    if not deadline_status["done"]:
        raise AssertionError(f"stack status is {deadline_status['status']}")


@scenario.step("The bucket was deleted with the stack", service="s3", operation="HeadBucket")
def bucket_gone(aws, state):
    state.need("bucket")
    s3 = aws.client("s3")

    def missing():
        try:
            s3.head_bucket(Bucket=state["bucket"])
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                return True
            raise
        return False

    if not poll(missing, lambda gone: gone, timeout=15, description="bucket deleted with the stack"):
        raise AssertionError("bucket still exists after the stack was deleted")
