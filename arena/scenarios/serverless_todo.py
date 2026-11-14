"""Serverless todo API.

A direct invoke stands in for POST /todos: the function writes the item,
then the scenario reads it back. This is the synchronous half of a small
service. The queue half lives in event_pipeline.
"""

from arena.scenario import Scenario, poll, python_zip

scenario = Scenario(
    slug="serverless-todo",
    title="Serverless todo API",
    summary="A Python 3.12 function writes a todo to DynamoDB, and the read path returns it.",
    services=["dynamodb", "iam", "lambda"],
)

_HANDLER = """\
def handler(event, context):
    import boto3
    todo_id = str(event["id"])
    title = str(event["title"])
    boto3.client("dynamodb").put_item(
        TableName={table!r},
        Item={{"id": {{"S": todo_id}}, "title": {{"S": title}}}},
    )
    print("saved", todo_id)
    return {{"id": todo_id, "title": title}}
"""


@scenario.step("Create the todos table", service="dynamodb", operation="CreateTable")
def create_table(aws, state):
    name = state.rid("todos")
    aws.client("dynamodb").create_table(
        TableName=name,
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    state["table"] = name


@scenario.step("Wait until the table is active", service="dynamodb", operation="DescribeTable")
def describe_table(aws, state):
    state.need("table")
    ddb = aws.client("dynamodb")
    described = poll(
        lambda: ddb.describe_table(TableName=state["table"])["Table"],
        lambda table: table.get("TableStatus") == "ACTIVE",
        description="table ACTIVE",
    )
    if described["TableName"] != state["table"]:
        raise AssertionError(f"described {described['TableName']}")


@scenario.step("Create a role the function can assume", service="iam", operation="CreateRole")
def create_role(aws, state):
    import json

    role_name = state.rid("todo-role")
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


@scenario.step("Allow the role to write todos", service="iam", operation="PutRolePolicy")
def allow_put(aws, state):
    import json

    state.need("role_name", "table")
    aws.client("iam").put_role_policy(
        RoleName=state["role_name"],
        PolicyName="todos",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["dynamodb:PutItem", "dynamodb:GetItem"],
                        "Resource": "*",
                    }
                ],
            }
        ),
    )


@scenario.step("Create the Python 3.12 function", service="lambda", operation="CreateFunction")
def create_function(aws, state):
    state.need("role_arn", "table")
    name = state.rid("todos")
    aws.client("lambda").create_function(
        FunctionName=name,
        Runtime="python3.12",
        Role=state["role_arn"],
        Handler="index.handler",
        Code={"ZipFile": python_zip(_HANDLER.format(table=state["table"]))},
        Timeout=10,
        MemorySize=128,
    )
    state["function"] = name


@scenario.step("Wait until the function is active", service="lambda", operation="GetFunction")
def wait_active(aws, state):
    state.need("function")
    lam = aws.client("lambda")
    poll(
        lambda: lam.get_function(FunctionName=state["function"])["Configuration"],
        lambda cfg: cfg.get("State") == "Active",
        description="function Active",
    )


@scenario.step("Invoke the function with a todo", service="lambda", operation="Invoke")
def invoke(aws, state):
    import json

    state.need("function")
    response = aws.client("lambda").invoke(
        FunctionName=state["function"],
        Payload=json.dumps({"id": "1", "title": "ship the arena"}).encode(),
    )
    if response.get("FunctionError"):
        payload = response["Payload"].read().decode()
        raise AssertionError(f"function error {response['FunctionError']}: {payload[:240]}")
    body = json.loads(response["Payload"].read())
    if body.get("title") != "ship the arena":
        raise AssertionError(f"handler returned {body!r}")


@scenario.step("Read the todo back from DynamoDB", service="dynamodb", operation="GetItem")
def get_item(aws, state):
    state.need("table")
    item = aws.client("dynamodb").get_item(TableName=state["table"], Key={"id": {"S": "1"}}).get("Item")
    title = ((item or {}).get("title") or {}).get("S")
    if title != "ship the arena":
        raise AssertionError(f"item title is {title!r}")
