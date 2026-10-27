#!/usr/bin/env bash
# Link check of README.md and docs/** with lychee.toml (CI job "links" and links.yml).
#
#   scripts/ci/lychee.sh --offline   # relative links only (every PR)
#   scripts/ci/lychee.sh             # external links too (weekly)
#
# Uses lychee from PATH, else a pinned, checksum-verified release (Linux x86_64).
set -euo pipefail

VERSION=0.24.2
SHA256_LINUX_X64=1f4e0ef7f6554a6ed33dd7ac144fb2e1bbed98598e7af973042fc5cd43951c9a

if command -v lychee >/dev/null 2>&1; then
  bin=lychee
else
  if [ "$(uname -s)-$(uname -m)" != "Linux-x86_64" ]; then
    echo "lychee: not on PATH; install lychee $VERSION (brew install lychee)" >&2
    exit 2
  fi
  dir="${RUNNER_TEMP:-$(mktemp -d)}/lychee-$VERSION"
  mkdir -p "$dir"
  archive="$dir/lychee.tar.gz"
  curl -fsSL -o "$archive" \
    "https://github.com/lycheeverse/lychee/releases/download/lychee-v$VERSION/lychee-x86_64-unknown-linux-gnu.tar.gz"
  echo "$SHA256_LINUX_X64  $archive" | sha256sum -c --quiet -
  tar -xzf "$archive" -C "$dir" --strip-components=1
  bin="$dir/lychee"
fi

"$bin" --config lychee.toml "$@" README.md 'docs/**/*.md'
