"""Platform-team inventory.

Monday morning for a platform group: who has a user, what the identity
store contains, which OUs exist, and which accounts the organization
actually lists. The account APIs are part of that job, not an extra probe.
"""

import json

from arena.scenario import Scenario

scenario = Scenario(
    slug="platform-inventory",
    title="Platform inventory",
    summary="Audit IAM users, the identity store, organizational units, and the account list.",
    services=["iam", "identitystore", "sso-admin", "organizations"],
)


@scenario.step("List IAM users", service="iam", operation="ListUsers")
def list_users(aws, state):
    users = aws.client("iam").list_users().get("Users", [])
    names = {user["UserName"] for user in users}
    if "emulator" not in names:
        raise AssertionError(f"built-in user missing; saw {sorted(names)!r}")
    state["users_before"] = names


@scenario.step("Create an auditor user", service="iam", operation="CreateUser")
def create_auditor(aws, state):
    name = state.rid("auditor")
    aws.client("iam").create_user(UserName=name)
    state["auditor"] = name


@scenario.step("The auditor shows up in the directory", service="iam", operation="ListUsers")
def auditor_listed(aws, state):
    state.need("auditor")
    names = {user["UserName"] for user in aws.client("iam").list_users().get("Users", [])}
    if state["auditor"] not in names:
        raise AssertionError("auditor user was created but is not listed")


@scenario.step("List Identity Center instances", service="sso-admin", operation="ListInstances")
def list_instances(aws, state):
    instances = aws.client("sso-admin").list_instances().get("Instances", [])
    if not instances:
        raise AssertionError("no Identity Center instance")
    instance = instances[0]
    state["instance_arn"] = instance.get("InstanceArn")
    state["store_id"] = instance.get("IdentityStoreId")
    if not state["instance_arn"] or not state["store_id"]:
        raise AssertionError(f"instance is missing arn or store id: {instance!r}"[:240])


@scenario.step("Create a person in the identity store", service="identitystore", operation="CreateUser")
def create_person(aws, state):
    state.need("store_id")
    created = aws.client("identitystore").create_user(
        IdentityStoreId=state["store_id"],
        UserName=state.rid("ada"),
        Name={"GivenName": "Ada", "FamilyName": "Lovelace"},
        DisplayName="Ada Lovelace",
    )
    state["person_id"] = created.get("UserId")
    if not state["person_id"]:
        raise AssertionError("CreateUser returned no UserId")


@scenario.step("The person is in the identity store", service="identitystore", operation="ListUsers")
def list_people(aws, state):
    state.need("store_id", "person_id")
    users = aws.client("identitystore").list_users(IdentityStoreId=state["store_id"]).get("Users", [])
    if state["person_id"] not in {user.get("UserId") for user in users}:
        raise AssertionError("created user is not listed")


@scenario.step("Describe the organization", service="organizations", operation="DescribeOrganization")
def describe_org(aws, state):
    org = aws.client("organizations").describe_organization()["Organization"]
    if org.get("MasterAccountId") != "000000000000":
        raise AssertionError(f"master account is {org.get('MasterAccountId')!r}")
    state["org_id"] = org.get("Id")


@scenario.step("List roots", service="organizations", operation="ListRoots")
def list_roots(aws, state):
    roots = aws.client("organizations").list_roots().get("Roots", [])
    if not roots:
        raise AssertionError("organization has no root")
    state["root_id"] = roots[0]["Id"]


@scenario.step("Create a Workloads OU", service="organizations", operation="CreateOrganizationalUnit")
def create_ou(aws, state):
    state.need("root_id")
    ou = aws.client("organizations").create_organizational_unit(ParentId=state["root_id"], Name="Workloads")[
        "OrganizationalUnit"
    ]
    state["ou_id"] = ou["Id"]


@scenario.step("The Workloads OU is under the root", service="organizations", operation="ListOrganizationalUnitsForParent")
def list_ous(aws, state):
    state.need("root_id", "ou_id")
    ous = aws.client("organizations").list_organizational_units_for_parent(ParentId=state["root_id"])[
        "OrganizationalUnits"
    ]
    if state["ou_id"] not in {ou["Id"] for ou in ous}:
        raise AssertionError("OU was created but is not listed")


@scenario.step("List accounts in the organization", service="organizations", operation="ListAccounts")
def list_accounts(aws, state):
    aws.client("organizations").list_accounts()


@scenario.step("Describe the management account", service="organizations", operation="DescribeAccount")
def describe_account(aws, state):
    aws.client("organizations").describe_account(AccountId="000000000000")


@scenario.step("List children of the root", service="organizations", operation="ListChildren")
def list_children(aws, state):
    state.need("root_id")
    aws.client("organizations").list_children(ParentId=state["root_id"], ChildType="ORGANIZATIONAL_UNIT")


@scenario.step("Create a permission set", service="sso-admin", operation="CreatePermissionSet")
def create_permission_set(aws, state):
    state.need("instance_arn")
    created = aws.client("sso-admin").create_permission_set(
        InstanceArn=state["instance_arn"],
        Name="ArenaReadOnly",
        Description="Read-only access for the platform audit",
        SessionDuration="PT1H",
    )
    if not created.get("PermissionSet", {}).get("PermissionSetArn"):
        raise AssertionError(f"CreatePermissionSet returned {json.dumps(created)[:200]}")
