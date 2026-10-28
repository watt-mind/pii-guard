#!/usr/bin/env bash
# Smoke-test a built wheel the way a user runs it (LAB-1276): `uv tool run --from <wheel>
# pii-guard up` in a throwaway environment, then /healthz, the bundled UI at /, one gateway
# chat call on the built-in mock upstream (masked on the way up, restored on the way back) and
# the traffic log. Stops the server with SIGINT and checks it exits cleanly.
#
#   scripts/ci/wheel_smoke.sh [--size-only] dist/<wheel>.whl
#
# PII_GUARD_SMOKE_PORT picks the port (default 18999). Fictional data only.
set -euo pipefail

size_only=false
if [ "${1:-}" = "--size-only" ]; then size_only=true; shift; fi
wheel="${1:?usage: wheel_smoke.sh [--size-only] <wheel>}"
max_bytes=$((5 * 1024 * 1024))

bytes=$(wc -c <"$wheel" | tr -d ' ')
echo "wheel: $(basename "$wheel") ($((bytes / 1024)) KiB, budget $((max_bytes / 1024)) KiB)"
if [ "$bytes" -gt "$max_bytes" ]; then
  echo "wheel-smoke: wheel is larger than 5 MiB" >&2
  exit 1
fi
if ! unzip -Z1 "$wheel" | grep -c 'pii_guard/_ui/index.html' >/dev/null; then
  echo "wheel-smoke: the web UI is not bundled (pii_guard/_ui/index.html missing)" >&2
  exit 1
fi
# The benchmark index is generated at UI build time (pii-guard eval report --print-index, LAB-1269).
if ! unzip -Z1 "$wheel" | grep -cE 'pii_guard/_ui/assets/benchmarks-index-[^/]+\.js$' >/dev/null; then
  echo "wheel-smoke: the UI was built without the benchmark index" >&2
  exit 1
fi
$size_only && exit 0

port="${PII_GUARD_SMOKE_PORT:-18999}"
base="http://127.0.0.1:$port"
log="$(mktemp)"
# A clean environment: no developer upstream, key or .env leaks into the run.
workdir="$(mktemp -d)"
env -i HOME="$HOME" PATH="$PATH" ${UV_CACHE_DIR:+UV_CACHE_DIR="$UV_CACHE_DIR"} \
  bash -c "cd '$workdir' && exec uv tool run --isolated --from '$(cd "$(dirname "$wheel")" && pwd)/$(basename "$wheel")' pii-guard up --no-browser --port $port" \
  >"$log" 2>&1 &
pid=$!
cleanup() {
  kill -INT "$pid" 2>/dev/null || true
  rm -rf "$workdir"
}
trap cleanup EXIT

for _ in $(seq 1 240); do
  curl -fsS "$base/healthz" >/dev/null 2>&1 && break
  if ! kill -0 "$pid" 2>/dev/null; then
    cat "$log" >&2
    echo "wheel-smoke: pii-guard up exited during startup" >&2
    exit 1
  fi
  sleep 0.5
done
curl -fsS "$base/healthz"
echo

page="$(curl -fsS "$base/")"
grep -q 'id="root"' <<<"$page" || { echo "wheel-smoke: / is not the bundled UI" >&2; exit 1; }
# The console reads the upstream from /v1/status (the page carries no status strip).
status="$(curl -fsS "$base/v1/status")"
grep -Eq '"upstream": *\{[^}]*"mock": *true' <<<"$status" || { echo "wheel-smoke: /v1/status does not say the upstream is the mock" >&2; exit 1; }
curl -fsS -o /dev/null "$base/traffic" # client-side route -> index.html (SPA fallback)
asset="$(grep -m1 -oE '/assets/[^"]+\.js' <<<"$page")"
asset="${asset%%$'\n'*}"
curl -fsS -o /dev/null "$base$asset"
code="$(curl -s -o /dev/null -w '%{http_code}' "$base/v1/no-such-route")"
[ "$code" = 404 ] || { echo "wheel-smoke: unknown API path answered $code, not 404" >&2; exit 1; }

# Fictional email; the mock echoes what it received, so a restored answer proves the round trip.
reply="$(curl -fsS "$base/v1/chat/completions" -H 'content-type: application/json' \
  -d '{"model":"pii-guard-mock","messages":[{"role":"user","content":"Write to anna.example@example.com"}]}')"
grep -q 'Echo: Write to anna.example@example.com' <<<"$reply" ||
  { echo "wheel-smoke: chat reply was not restored: $reply" >&2; exit 1; }
traffic="$(curl -fsS "$base/v1/traffic")"
grep -q 'EMAIL' <<<"$traffic" || { echo "wheel-smoke: the traffic log has no masked EMAIL" >&2; exit 1; }
if grep -q 'anna.example@example.com' <<<"$traffic"; then
  echo "wheel-smoke: the masked traffic log contains the original email" >&2
  exit 1
fi
echo "chat: restored; traffic log: masked"

kill -INT "$pid"
for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
if kill -0 "$pid" 2>/dev/null; then
  echo "wheel-smoke: pii-guard up did not stop on SIGINT" >&2
  kill -9 "$pid"
  exit 1
fi
wait "$pid" || { cat "$log" >&2; echo "wheel-smoke: non-zero exit after SIGINT" >&2; exit 1; }
grep -q 'pii-guard is up' "$log" || { cat "$log" >&2; echo "wheel-smoke: no banner" >&2; exit 1; }
trap - EXIT
rm -rf "$workdir" "$log"
echo "wheel-smoke: ok"
