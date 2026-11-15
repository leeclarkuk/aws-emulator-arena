# Contributing

Arena is a scoreboard. A useful change is a new workflow, a sharper assertion, or a clearer reading of a result. It is not a place to hard-code which calls you hope will pass.

## Ground rules

- Run only against a local AWS Emulator. `scripts/run.sh` unsets ambient credentials and the runner exits if the endpoint is not loopback HTTPS or the key was not produced by the emulator.
- Do not commit credentials, account ids from a real account, customer data, or screenshots that contain them. The emulator account is `000000000000`. That one is fine.
- A step that receives HTTP 501 is `not_implemented`. Do not catch that error and turn it into a pass. The wall of 501s is the point.
- A step that should be denied on AWS uses `expect=error("AccessDenied")`. Success in that case is a divergence.
- Keep scenario files short enough to read in one sitting. One workflow per file.

## Add a scenario

1. Copy the shape below into `arena/scenarios/<slug>.py`.
2. Register it in `arena/scenarios/__init__.py`. Order in that list is the order the arena runs.
3. `make test`
4. `make arena ARGS="--only <slug>"`

```python
from arena.scenario import Scenario

scenario = Scenario(
    slug="hello-bucket",
    title="Hello bucket",
    summary="Create a bucket and read back the object you put in it.",
    services=["s3"],
)

@scenario.step("Create a bucket", service="s3", operation="CreateBucket")
def create_bucket(aws, state):
    name = state.rid("hello")
    aws.client("s3").create_bucket(Bucket=name)
    state["bucket"] = name

@scenario.step("Round-trip an object", service="s3", operation="GetObject")
def round_trip(aws, state):
    state.need("bucket")
    s3 = aws.client("s3")
    s3.put_object(Bucket=state["bucket"], Key="hello.txt", Body=b"hello")
    body = s3.get_object(Bucket=state["bucket"], Key="hello.txt")["Body"].read()
    if body != b"hello":
        raise AssertionError(f"body is {body!r}")
```

`state.rid("hello")` keeps names unique for the run. `state.need("bucket")` marks the step blocked, instead of fake-failing, when an earlier step did not produce it.

Raise `AssertionError` when the call succeeded and the result is not what AWS would have produced. That is recorded as divergent.

`aws_would` on the step decorator is one sentence about what AWS would do. The gallery prints it. When the interesting part of the response is not the error the SDK raises, call `state.observe({...})` with the key fields before you assert. The runner keeps that only for a divergent step or a 501, redacts secret-looking fields, and trims long values. Do not put keys in it. A pass does not store the body.

## What the outcomes mean

| Outcome | When |
| --- | --- |
| pass | The call did what the step asserted, including an expected error. |
| not_implemented | HTTP 501, or error code `NotImplemented`. |
| divergent | Any other error, or a successful call that failed an assertion. |
| blocked | An earlier step did not leave the state this step needs. Blocked steps are shown and left out of the fidelity percentage. |

Fidelity is `pass / (pass + not_implemented + divergent)`.

## Run it

```bash
make test
make arena
make serve   # http://127.0.0.1:8765
```

`make test` creates `.venv` if it is missing, installs `requirements-dev.txt` into it, and runs pytest with that interpreter. A fresh clone does not need a separate `pip install`. The same `.venv` is what `make arena` creates when the system Python cannot import boto3.

`make arena` restarts the emulator on port 9297 so each run starts empty. It does not upgrade an emulator that is already installed. `make install-emulator` installs the latest signed package. Linux x86_64 or arm64 is required for the package. Elsewhere, use the Dockerfile in this repo.

## Reporting a gap

Open an [emulator gap](https://github.com/leeclarkuk/aws-emulator-arena/issues/new?template=emulator-gap.yml) with the version from the scoreboard and the step detail. If you also file it on [aws/aws-emulator](https://github.com/aws/aws-emulator/issues), link the two issues. Do not paste keys. The credentials file under `~/.aws/emulator/` is produced per run and is not a secret to commit, and it is still not something to paste into a ticket.
