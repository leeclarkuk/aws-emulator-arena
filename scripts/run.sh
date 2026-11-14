#!/usr/bin/env bash
# Start a fresh emulator, point the SDK only at it, run the arena, stop the emulator.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

PORT="${PORT:-9297}"

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE AWS_DEFAULT_PROFILE \
  AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_ARN AWS_CONTAINER_CREDENTIALS_RELATIVE_URI \
  AWS_CONTAINER_CREDENTIALS_FULL_URI || true

if ! command -v aws-emulator >/dev/null 2>&1; then
  bash "$root/scripts/install-emulator.sh"
fi

if [[ -n "${ARENA_PYTHON:-}" ]]; then
  py="$ARENA_PYTHON"
elif python3 -c "import boto3" >/dev/null 2>&1; then
  py="python3"
else
  python3 -m venv "$root/.venv"
  "$root/.venv/bin/pip" install -q -r "$root/requirements.txt"
  py="$root/.venv/bin/python"
fi

stop_listeners() {
  local pid=""
  if command -v ss >/dev/null 2>&1; then
    pid="$(ss -ltnp "sport = :${PORT}" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1 || true)"
  fi
  if [[ -z "$pid" ]]; then
    pid="$(pgrep -x aws-emulator | head -1 || true)"
  fi
  if [[ -n "$pid" ]]; then
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || return 0
      sleep 0.1
    done
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

stop_listeners

log="$(mktemp)"
start_ms="$(date +%s%3N)"
aws-emulator -p "$PORT" -t off >"$log" 2>&1 &
emu_pid=$!

cleanup() {
  if kill -0 "$emu_pid" 2>/dev/null; then
    kill -TERM "$emu_pid" 2>/dev/null || true
    wait "$emu_pid" 2>/dev/null || true
  fi
  rm -f "$log"
}
trap cleanup EXIT

ca="$HOME/.aws/emulator/${PORT}/ca.pem"
creds="$HOME/.aws/emulator/${PORT}/emulator_credentials"
health="https://127.0.0.1:${PORT}/__admin/health"
ready=0
for _ in $(seq 1 200); do
  if [[ -f "$ca" && -f "$creds" ]] && curl -sf --cacert "$ca" "$health" >/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$emu_pid" 2>/dev/null; then
    echo "aws-emulator exited before it was healthy:" >&2
    cat "$log" >&2
    exit 1
  fi
  sleep 0.05
done
if [[ "$ready" -ne 1 ]]; then
  echo "aws-emulator did not become healthy on port ${PORT}:" >&2
  cat "$log" >&2
  exit 1
fi
end_ms="$(date +%s%3N)"

version_text="$(aws-emulator -v)"
export ARENA_EMULATOR_VERSION="$(printf '%s\n' "$version_text" | awk -F': ' '/^Version:/{print $2; exit}')"
export ARENA_EMULATOR_RELEASE_DATE="$(printf '%s\n' "$version_text" | awk -F': ' '/^Release date:/{print $2; exit}')"
export ARENA_EMULATOR_COMMIT="$(printf '%s\n' "$version_text" | awk -F': ' '/^Commit:/{print $2; exit}')"
export ARENA_EMULATOR_STARTUP_MS="$((end_ms - start_ms))"
if [[ -r "/proc/${emu_pid}/status" ]]; then
  export ARENA_EMULATOR_RSS_KB="$(awk '/^VmRSS:/{print $2}' "/proc/${emu_pid}/status")"
fi

export AWS_ENDPOINT_URL="https://127.0.0.1:${PORT}"
export AWS_SHARED_CREDENTIALS_FILE="$creds"
export AWS_CONFIG_FILE="$HOME/.aws/emulator/${PORT}/config"
export AWS_CA_BUNDLE="$ca"
export AWS_EC2_METADATA_DISABLED=true
export AWS_DISABLE_HOST_PREFIX_INJECTION=true
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1

"$py" -m arena "$@"

if grep -E -q 'AKIA[0-9A-Z]{16}|aws_secret_access_key|BEGIN (RSA |OPENSSH )?PRIVATE KEY' scoreboard/latest.json; then
  echo "Refusing to keep a scoreboard that looks like it contains credential material." >&2
  exit 1
fi
