#!/usr/bin/env bash
# Lint GitHub Actions workflows (CI job "workflows"; locally: scripts/ci/actionlint.sh).
#
# Uses a pinned actionlint release (checksum-verified). Downloads to $RUNNER_TEMP (or a temp
# dir) unless actionlint is already on PATH. On runners, actionlint also runs shellcheck over
# `run:` blocks when shellcheck is on PATH.
set -euo pipefail

VERSION=1.7.12
SHA256_LINUX_X64=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8

if command -v actionlint >/dev/null 2>&1; then
  bin=actionlint
else
  if [ "$(uname -s)-$(uname -m)" != "Linux-x86_64" ]; then
    echo "actionlint: not on PATH; install actionlint $VERSION (brew install actionlint)" >&2
    exit 2
  fi
  dir="${RUNNER_TEMP:-$(mktemp -d)}/actionlint-$VERSION"
  mkdir -p "$dir"
  archive="$dir/actionlint.tar.gz"
  curl -fsSL -o "$archive" \
    "https://github.com/rhysd/actionlint/releases/download/v$VERSION/actionlint_${VERSION}_linux_amd64.tar.gz"
  echo "$SHA256_LINUX_X64  $archive" | sha256sum -c --quiet -
  tar -xzf "$archive" -C "$dir" actionlint
  bin="$dir/actionlint"
fi

"$bin" "$@"
