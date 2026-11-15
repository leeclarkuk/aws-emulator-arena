"""FinOps cost report.

A monthly review reads a budget, a cost export that already landed in S3,
and Cost Explorer. The export is the path teams use when the API is the
thing that is missing.
"""

from arena.scenario import Scenario

scenario = Scenario(
    slug="finops-cost-report",
    title="FinOps cost report",
    summary="Read a budget and a cost export from S3, then ask Cost Explorer for the same month.",
    services=["budgets", "s3", "ce"],
)

_PERIOD = {"Start": "2026-11-01", "End": "2026-11-14"}
_EXPORT = (
    "service,unblended_cost\n"
    "Amazon Simple Storage Service,1.25\n"
    "AWS Lambda,0.40\n"
)


@scenario.step("Create a monthly cost budget", service="budgets", operation="CreateBudget")
def create_budget(aws, state):
    aws.client("budgets").create_budget(
        AccountId="000000000000",
        Budget={
            "BudgetName": state.rid("monthly"),
            "BudgetType": "COST",
            "TimeUnit": "MONTHLY",
            "BudgetLimit": {"Amount": "100", "Unit": "USD"},
        },
    )
    state["budget"] = state.rid("monthly")


@scenario.step("The budget is listed", service="budgets", operation="DescribeBudgets")
def describe_budgets(aws, state):
    state.need("budget")
    budgets = aws.client("budgets").describe_budgets(AccountId="000000000000").get("Budgets", [])
    found = next((row for row in budgets if row.get("BudgetName") == state["budget"]), None)
    if not found:
        raise AssertionError("budget was created but is not listed")
    amount = (found.get("BudgetLimit") or {}).get("Amount")
    if str(amount) != "100":
        raise AssertionError(f"budget limit is {amount!r}")


@scenario.step("Land a cost export in S3", service="s3", operation="PutObject")
def put_export(aws, state):
    bucket = state.rid("cur")
    s3 = aws.client("s3")
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="cur/2026-11.csv", Body=_EXPORT.encode(), ContentType="text/csv")
    state["bucket"] = bucket


@scenario.step("Sum the cost export", service="s3", operation="GetObject")
def read_export(aws, state):
    state.need("bucket")
    body = aws.client("s3").get_object(Bucket=state["bucket"], Key="cur/2026-11.csv")["Body"].read().decode()
    rows = [line.split(",") for line in body.splitlines()[1:] if line.strip()]
    total = sum(float(row[1]) for row in rows)
    if abs(total - 1.65) > 0.001:
        raise AssertionError(f"export total is {total}")


@scenario.step(
    "Ask Cost Explorer for the month",
    service="ce",
    operation="GetCostAndUsage",
    aws_would="On AWS, GetCostAndUsage returns the cost for the period you ask for, grouped the way you asked.",
)
def get_cost_and_usage(aws, state):
    aws.client("ce").get_cost_and_usage(TimePeriod=_PERIOD, Granularity="MONTHLY", Metrics=["UnblendedCost"])


@scenario.step(
    "List services that had spend",
    service="ce",
    operation="GetDimensionValues",
    aws_would="On AWS, GetDimensionValues lists the values of a dimension, such as the service names that had spend.",
)
def get_dimension_values(aws, state):
    aws.client("ce").get_dimension_values(TimePeriod=_PERIOD, Dimension="SERVICE")


@scenario.step(
    "Forecast the rest of the month",
    service="ce",
    operation="GetCostForecast",
    aws_would="On AWS, GetCostForecast returns a forecast of cost for the rest of the period.",
)
def get_cost_forecast(aws, state):
    aws.client("ce").get_cost_forecast(
        TimePeriod={"Start": "2026-11-14", "End": "2026-12-01"},
        Metric="UNBLENDED_COST",
        Granularity="MONTHLY",
    )


@scenario.step(
    "List cost allocation tags",
    service="ce",
    operation="GetTags",
    aws_would="On AWS, GetTags lists the cost allocation tag keys that match the filter.",
)
def get_tags(aws, state):
    aws.client("ce").get_tags(TimePeriod=_PERIOD)
