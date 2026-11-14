"""CI control plane.

A platform pipeline: CodeBuild project, a build, then a pipeline whose
source is an object in S3. A succeeded build only counts if something
records that the buildspec ran.
"""

import json

from arena.scenario import Scenario, poll

scenario = Scenario(
    slug="cicd-control-plane",
    title="CI control plane",
    summary="Create a CodeBuild project and a pipeline, start both, and look for evidence the build ran.",
    services=["iam", "codebuild", "codepipeline", "s3"],
)


def _buildspec(marker: str) -> str:
    return f"version: 0.2\nphases:\n  build:\n    commands:\n      - echo {marker}\n"


@scenario.step("Create a CodeBuild service role", service="iam", operation="CreateRole")
def create_role(aws, state):
    role_name = state.rid("build-role")
    trust = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "codebuild.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
    )
    role = aws.client("iam").create_role(RoleName=role_name, AssumeRolePolicyDocument=trust)["Role"]
    state["role_arn"] = role["Arn"]
    state["marker"] = f"arena-marker-{state.run_id}"


@scenario.step("Create a build project", service="codebuild", operation="CreateProject")
def create_project(aws, state):
    state.need("role_arn", "marker")
    name = state.rid("build")
    aws.client("codebuild").create_project(
        name=name,
        source={"type": "NO_SOURCE", "buildspec": _buildspec(state["marker"])},
        artifacts={"type": "NO_ARTIFACTS"},
        environment={
            "type": "LINUX_CONTAINER",
            "image": "aws/codebuild/standard:7.0",
            "computeType": "BUILD_GENERAL1_SMALL",
        },
        serviceRole=state["role_arn"],
    )
    state["project"] = name


@scenario.step("Start a build", service="codebuild", operation="StartBuild")
def start_build(aws, state):
    state.need("project")
    build = aws.client("codebuild").start_build(projectName=state["project"])["build"]
    if not build.get("id"):
        raise AssertionError("StartBuild returned no build id")
    state["build_id"] = build["id"]


@scenario.step("Wait for the build to finish", service="codebuild", operation="BatchGetBuilds")
def wait_build(aws, state):
    state.need("build_id")
    cb = aws.client("codebuild")

    def fetch():
        builds = cb.batch_get_builds(ids=[state["build_id"]]).get("builds", [])
        return builds[0] if builds else {}

    build = poll(
        fetch,
        lambda row: row.get("buildStatus") in {"SUCCEEDED", "FAILED", "FAULT", "STOPPED", "TIMED_OUT"},
        timeout=15,
        description="build reached a terminal status",
    )
    state["build"] = build
    if build.get("buildStatus") != "SUCCEEDED":
        raise AssertionError(f"build status is {build.get('buildStatus')}")


@scenario.step("The build recorded the buildspec output", service="codebuild", operation="BatchGetBuilds")
def build_logs(aws, state):
    state.need("build", "marker")
    build = state["build"]
    logs = build.get("logs")
    phases = build.get("phases") or []
    build_phase = next((phase for phase in phases if phase.get("phaseType") == "BUILD"), {})
    duration = build_phase.get("durationInSeconds")
    searchable = json.dumps({"logs": logs, "durationInSeconds": duration}, default=str)
    if state["marker"] in searchable:
        return
    raise AssertionError(
        f"build status is {build.get('buildStatus')} but nothing recorded {state['marker']}; "
        f"BUILD durationInSeconds={duration!r}, logs={logs!r}"[:400]
    )


@scenario.step("Put the source object the pipeline will read", service="s3", operation="PutObject")
def put_source(aws, state):
    bucket = state.rid("artifacts")
    body = b"pipeline-source"
    s3 = aws.client("s3")
    s3.create_bucket(Bucket=bucket)
    put = s3.put_object(Bucket=bucket, Key="source.txt", Body=body)
    state["artifact_bucket"] = bucket
    state["etag"] = str(put.get("ETag", "")).strip('"')


@scenario.step("Create a two-stage pipeline", service="codepipeline", operation="CreatePipeline")
def create_pipeline(aws, state):
    state.need("role_arn", "project", "artifact_bucket")
    name = state.rid("pipe")
    pipeline = {
        "name": name,
        "roleArn": state["role_arn"],
        "artifactStore": {"type": "S3", "location": state["artifact_bucket"]},
        "stages": [
            {
                "name": "Source",
                "actions": [
                    {
                        "name": "S3",
                        "actionTypeId": {"category": "Source", "owner": "AWS", "provider": "S3", "version": "1"},
                        "configuration": {"S3Bucket": state["artifact_bucket"], "S3ObjectKey": "source.txt"},
                        "outputArtifacts": [{"name": "src"}],
                        "runOrder": 1,
                    }
                ],
            },
            {
                "name": "Build",
                "actions": [
                    {
                        "name": "Build",
                        "actionTypeId": {"category": "Build", "owner": "AWS", "provider": "CodeBuild", "version": "1"},
                        "configuration": {"ProjectName": state["project"]},
                        "inputArtifacts": [{"name": "src"}],
                        "runOrder": 1,
                    }
                ],
            },
        ],
    }
    aws.client("codepipeline").create_pipeline(pipeline=pipeline)
    state["pipeline"] = name


@scenario.step("Start the pipeline", service="codepipeline", operation="StartPipelineExecution")
def start_pipeline(aws, state):
    state.need("pipeline")
    started = aws.client("codepipeline").start_pipeline_execution(name=state["pipeline"])
    state["execution_id"] = started.get("pipelineExecutionId")
    if not state["execution_id"]:
        raise AssertionError("StartPipelineExecution returned no id")


@scenario.step("The source action read the object", service="codepipeline", operation="GetPipelineExecution")
def source_revision(aws, state):
    state.need("pipeline", "execution_id", "etag")
    cp = aws.client("codepipeline")

    def fetch():
        return cp.get_pipeline_execution(pipelineName=state["pipeline"], pipelineExecutionId=state["execution_id"])[
            "pipelineExecution"
        ]

    execution = poll(
        fetch,
        lambda row: row.get("status") in {"Succeeded", "Failed", "Stopped", "Superseded"},
        timeout=15,
        description="pipeline execution settled",
    )
    revisions = execution.get("artifactRevisions") or execution.get("sourceRevisions") or []
    revision_ids = {str(row.get("revisionId", "")) for row in revisions}
    if state["etag"] not in revision_ids:
        raise AssertionError(
            f"execution {execution.get('status')} revisions {sorted(revision_ids)!r} do not include etag {state['etag']}"
        )
