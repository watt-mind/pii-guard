#!/usr/bin/env bash
# Secret scan of the commits a change adds (CI job "gitleaks"; locally: make gitleaks).
#
#   scripts/ci/gitleaks.sh BASE HEAD    # scan BASE..HEAD
#   scripts/ci/gitleaks.sh              # scan the whole history
#
# Uses a pinned gitleaks release (checksum-verified) and .gitleaks.toml; findings are redacted.
# The gitleaks GitHub Action needs a paid licence for organisation repositories; the binary is
# free (MIT). Downloads to $RUNNER_TEMP (or a temp dir) unless gitleaks is already on PATH.
set -euo pipefail

VERSION=8.30.1
SHA256_LINUX_X64=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb

if command -v gitleaks >/dev/null 2>&1; then
  bin=gitleaks
else
  if [ "$(uname -s)-$(uname -m)" != "Linux-x86_64" ]; then
    echo "gitleaks: not on PATH; install gitleaks $VERSION (brew install gitleaks)" >&2
    exit 2
  fi
  dir="${RUNNER_TEMP:-$(mktemp -d)}/gitleaks-$VERSION"
  mkdir -p "$dir"
  archive="$dir/gitleaks.tar.gz"
  curl -fsSL -o "$archive" \
    "https://github.com/gitleaks/gitleaks/releases/download/v$VERSION/gitleaks_${VERSION}_linux_x64.tar.gz"
  echo "$SHA256_LINUX_X64  $archive" | sha256sum -c --quiet -
  tar -xzf "$archive" -C "$dir" gitleaks
  bin="$dir/gitleaks"
fi

args=(git . --config .gitleaks.toml --redact --no-banner --exit-code 1)
if [ $# -ge 2 ] && [ -n "$1" ] && [ "$1" != "0000000000000000000000000000000000000000" ]; then
  echo "gitleaks: scanning $1..$2"
  args+=(--log-opts="$1..$2")
elif [ $# -ge 2 ]; then
  echo "gitleaks: no base (new branch); scanning $2 only"
  args+=(--log-opts="-1 $2")
else
  echo "gitleaks: scanning the whole history"
fi
"$bin" "${args[@]}"
