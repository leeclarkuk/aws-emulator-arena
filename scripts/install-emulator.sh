#!/usr/bin/env bash
# Install the latest AWS Emulator Linux package and check its signature.
set -euo pipefail

arch="$(uname -m)"
case "$arch" in
  x86_64) deb="aws-emulator_amd64.deb" ;;
  aarch64 | arm64) deb="aws-emulator_arm64.deb" ;;
  *)
    echo "AWS Emulator packages are published for x86_64 and arm64 (this machine is ${arch})." >&2
    exit 1
    ;;
esac

base="https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest"
tmp="$(mktemp -d)"
gnupg="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp" "$gnupg"
}
trap cleanup EXIT

curl -fsSLo "$tmp/$deb" "$base/$deb"
curl -fsSLo "$tmp/$deb.sig" "$base/$deb.sig"
curl -fsSLo "$tmp/aws-publishing.asc" "https://downloads.aws.com/keys/gpg/current.asc"

export GNUPGHOME="$gnupg"
gpg --batch --quiet --import "$tmp/aws-publishing.asc"
fingerprint="$(gpg --batch --with-colons --fingerprint ssm-publishing@amazon.com | awk -F: '/^fpr:/{print $10; exit}')"
expected="98BCF336A3BE53B734E967C52E5BF49BD940F624"
if [[ "$fingerprint" != "$expected" ]]; then
  echo "Refusing to install: signing key fingerprint is ${fingerprint:-missing}." >&2
  exit 1
fi
gpg --batch --verify "$tmp/$deb.sig" "$tmp/$deb"

if [[ "$(id -u)" -eq 0 ]]; then
  apt-get update
  apt-get install -y "$tmp/$deb"
else
  sudo apt-get update
  sudo apt-get install -y "$tmp/$deb"
fi

aws-emulator -v
