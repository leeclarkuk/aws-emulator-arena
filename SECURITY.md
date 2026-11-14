# Security

## Reporting a vulnerability

Report a vulnerability in private, through GitHub. Open the Security tab of this repository and choose Report a vulnerability. That uses GitHub private vulnerability reporting, so the report is not posted as a public issue.

If the matter is not sensitive (a score that looks wrong, a scenario that should fail, a mistake in the docs), open a normal issue.

Do not paste credentials, account ids from a real account, or the contents of `~/.aws/emulator/`.

## What the runner will talk to

The runner only talks to a local loopback emulator. It will not start unless `AWS_ENDPOINT_URL` is HTTPS on `127.0.0.1`, `localhost`, or `::1`, and it refuses real AWS endpoints. There is no setting in this repository that sends a request to AWS.
