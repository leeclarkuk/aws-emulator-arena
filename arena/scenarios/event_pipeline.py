"""Event pipeline: SQS to Lambda to DynamoDB.

An order event lands on a queue. An event source mapping should invoke a
worker, and the worker should persist the order. The proof is the item,
not the mapping object existing.
"""

from arena.scenario import Scenario, poll, python_zip

scenario = Scenario(
    slug="event-pipeline",
    title="Event pipeline",
    summary="An SQS message wakes a Lambda worker, which writes the order to DynamoDB.",
    services=["sqs", "lambda", "dynamodb", "iam"],
)

_WORKER = """\
import json

def handler(event, context):
    import boto3
    table = boto3.client("dynamodb")
    saved = 0
    for record in event.get("Records") or []:
        body = json.loads(record["body"])
        table.put_item(
            TableName={table!r},
            Item={{
                "id": {{"S": str(body["id"])}},
                "title": {{"S": str(body["title"])}},
            }},
        )
        saved += 1
    print("pipeline-saved", saved)
    return {{"saved": saved}}
"""


@scenario.step("Create the orders table", service="dynamodb", operation="CreateTable")
def create_table(aws, state):
    name = state.rid("orders")
    aws.client("dynamodb").create_table(
        TableName=name,
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    state["table"] = name


@scenario.step("Wait until the orders table is active", service="dynamodb", operation="DescribeTable")
def describe_table(aws, state):
    state.need("table")
    ddb = aws.client("dynamodb")
    poll(
        lambda: ddb.describe_table(TableName=state["table"])["Table"],
        lambda table: table.get("TableStatus") == "ACTIVE",
        description="orders table ACTIVE",
    )


@scenario.step("Create the orders queue", service="sqs", operation="CreateQueue")
def create_queue(aws, state):
    name = state.rid("orders")
    sqs = aws.client("sqs")
    url = sqs.create_queue(QueueName=name)["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    state["queue_url"] = url
    state["queue_arn"] = arn


@scenario.step("Create a role for the worker", service="iam", operation="CreateRole")
def create_role(aws, state):
    import json

    role_name = state.rid("worker-role")
    trust = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
    )
    role = aws.client("iam").create_role(RoleName=role_name, AssumeRolePolicyDocument=trust)["Role"]
    state["role_name"] = role_name
    state["role_arn"] = role["Arn"]


@scenario.step("Allow the worker to read the queue and write orders", service="iam", operation="PutRolePolicy")
def allow_worker(aws, state):
    import json

    state.need("role_name")
    aws.client("iam").put_role_policy(
        RoleName=state["role_name"],
        PolicyName="worker",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "sqs:ReceiveMessage",
                            "sqs:DeleteMessage",
                            "sqs:GetQueueAttributes",
                            "dynamodb:PutItem",
                        ],
                        "Resource": "*",
                    }
                ],
            }
        ),
    )


@scenario.step("Create the worker function", service="lambda", operation="CreateFunction")
def create_function(aws, state):
    state.need("role_arn", "table")
    name = state.rid("worker")
    aws.client("lambda").create_function(
        FunctionName=name,
        Runtime="python3.12",
        Role=state["role_arn"],
        Handler="index.handler",
        Code={"ZipFile": python_zip(_WORKER.format(table=state["table"]))},
        Timeout=15,
        MemorySize=128,
    )
    state["function"] = name


@scenario.step("Wait until the worker is active", service="lambda", operation="GetFunction")
def wait_active(aws, state):
    state.need("function")
    lam = aws.client("lambda")
    poll(
        lambda: lam.get_function(FunctionName=state["function"])["Configuration"],
        lambda cfg: cfg.get("State") == "Active",
        description="worker Active",
    )


@scenario.step("Attach the queue to the worker", service="lambda", operation="CreateEventSourceMapping")
def create_mapping(aws, state):
    state.need("queue_arn", "function")
    mapping = aws.client("lambda").create_event_source_mapping(
        EventSourceArn=state["queue_arn"],
        FunctionName=state["function"],
        Enabled=True,
        BatchSize=1,
    )
    state["mapping"] = mapping["UUID"]


@scenario.step("Wait until the mapping is enabled", service="lambda", operation="GetEventSourceMapping")
def wait_mapping(aws, state):
    state.need("mapping")
    lam = aws.client("lambda")
    poll(
        lambda: lam.get_event_source_mapping(UUID=state["mapping"]),
        lambda mapping: mapping.get("State") == "Enabled",
        description="mapping Enabled",
    )


@scenario.step("Publish an order", service="sqs", operation="SendMessage")
def send(aws, state):
    import json

    state.need("queue_url")
    aws.client("sqs").send_message(
        QueueUrl=state["queue_url"],
        MessageBody=json.dumps({"id": "ord-1", "title": "one espresso"}),
    )


@scenario.step("The worker stored the order", service="dynamodb", operation="GetItem")
def order_landed(aws, state):
    state.need("table", "queue_url")
    ddb = aws.client("dynamodb")
    sqs = aws.client("sqs")

    def look():
        item = ddb.get_item(TableName=state["table"], Key={"id": {"S": "ord-1"}}).get("Item")
        attrs = sqs.get_queue_attributes(
            QueueUrl=state["queue_url"],
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )["Attributes"]
        return item, attrs

    item, _attrs = poll(
        look,
        lambda found: bool(found[0]) and found[1]["ApproximateNumberOfMessages"] == "0",
        timeout=12,
        description="order item written and queue drained",
    )
    title = item.get("title", {}).get("S")
    if title != "one espresso":
        raise AssertionError(f"stored title is {title!r}")
