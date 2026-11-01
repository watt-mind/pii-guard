#!/usr/bin/env bash
# Smoke-test pii-guard the way a user runs it (LAB-1276, LAB-1741): `uv tool run --from <source>
# pii-guard up` in a throwaway environment, then /healthz until the NER is ready, the bundled UI
# at / (or the honest no-UI page), gateway calls on the built-in mock upstream (masked on the
# way up, restored on the way back), the traffic log, optionally one image request, and a clean
# exit on SIGINT.
#
#   scripts/ci/wheel_smoke.sh [--size-only] dist/<wheel>.whl
#   scripts/ci/wheel_smoke.sh [--python 3.12] [--from SPEC] [--no-ui] [--image] [dist/<wheel>.whl]
#
#   --size-only  only the wheel file checks (size budget, UI and benchmark index bundled)
#   --from SPEC  what uv installs (default: the wheel), e.g. a `git+https://...@<sha>` URL or
#                `wattmind-pii-guard==<version>`; without a wheel the file checks are skipped
#   --python V   the interpreter uv runs it on, as the README does (`uvx --python 3.12`)
#   --no-ui      expect the no-UI fallback page at / (a source install has no UI bundled)
#   --image      also send one image (needs the `tesseract` binary: /healthz must say ocr on)
#
# Env: PII_GUARD_SMOKE_PORT (default 18999), PII_GUARD_SMOKE_LOG (keep the server log there,
# e.g. to upload it from CI), PII_GUARD_SMOKE_READY_TIMEOUT (seconds to wait for the NER,
# default 600). Portable: bash 3.2 (macOS) and Linux. Fictional data only (ADR 0005).
set -euo pipefail

size_only=false
source_spec=""
python_version=""
expect_ui=true
image=false
while [ $# -gt 0 ]; do
  case "$1" in
    --size-only) size_only=true; shift ;;
    --from) source_spec="${2:?--from needs a value}"; shift 2 ;;
    --python) python_version="${2:?--python needs a value}"; shift 2 ;;
    --no-ui) expect_ui=false; shift ;;
    --image) image=true; shift ;;
    --) shift; break ;;
    -*) echo "wheel-smoke: unknown option $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
wheel="${1:-}"
if [ -z "$wheel" ] && [ -z "$source_spec" ]; then
  echo "usage: wheel_smoke.sh [--size-only] [--python V] [--from SPEC] [--no-ui] [--image] [<wheel>]" >&2
  exit 2
fi
max_bytes=$((5 * 1024 * 1024))

if [ -n "$wheel" ]; then
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
  # The benchmark index is generated at UI build time (pii-guard eval report --print-index,
  # LAB-1269) and ships as hashed JSON parts (ui/src/api/benchmarksSplit.ts, LAB-1454): the
  # summary, the run log and one file per fixture set. Each must be there, hold real data, and
  # be the one the app chunk points at (a stale or missing part would leave the Evaluation
  # screen empty).
  if ! python3 - "$wheel" <<'PY'
import json, re, sys, zipfile

z = zipfile.ZipFile(sys.argv[1])
assets = {n.split("pii_guard/_ui/", 1)[1]: n for n in z.namelist() if "pii_guard/_ui/assets/" in n}
part = lambda kind: sorted(k for k in assets if re.fullmatch(rf"assets/benchmarks-{kind}-[\w-]+\.json", k))
summary, runs, sets = part("summary"), part("runs"), part("set-[\w-]+")
if len(summary) != 1 or len(runs) != 1 or not sets:
    sys.exit(f"benchmark parts missing: summary={summary} runs={runs} sets={len(sets)}")
s = json.loads(z.read(assets[summary[0]]))
r = json.loads(z.read(assets[runs[0]]))
if s.get("schema_version") != 1 or not s.get("systems") or not s.get("fixture_sets") or not r.get("runs"):
    sys.exit("benchmark parts hold no benchmark data")
app = b"".join(z.read(n) for k, n in assets.items() if k.endswith(".js"))
missing = [k for k in (summary[0], runs[0], *sets) if k.encode() not in app]
if missing:
    sys.exit(f"the app does not reference {missing[:3]}")
print(f"benchmark index: {len(s['systems'])} systems, {len(r['runs'])} runs, {len(sets)} fixture-set parts")
PY
  then
    echo "wheel-smoke: the UI was built without the benchmark index" >&2
    exit 1
  fi
  if [ -z "$source_spec" ]; then
    source_spec="$(cd "$(dirname "$wheel")" && pwd)/$(basename "$wheel")"
  fi
fi
$size_only && exit 0

port="${PII_GUARD_SMOKE_PORT:-18999}"
ready_timeout="${PII_GUARD_SMOKE_READY_TIMEOUT:-600}"
base="http://127.0.0.1:$port"
log="${PII_GUARD_SMOKE_LOG:-$(mktemp)}"
: >"$log"
uv_args="--isolated"
[ -n "$python_version" ] && uv_args="$uv_args --python $python_version"
echo "source: $source_spec"
# A clean environment: no developer upstream, key or .env leaks into the run. TMPDIR is kept
# (pytesseract writes the image there); UV_CACHE_DIR only if the caller set one.
workdir="$(mktemp -d)"
started=$SECONDS
env -i HOME="$HOME" PATH="$PATH" ${TMPDIR:+TMPDIR="$TMPDIR"} ${UV_CACHE_DIR:+UV_CACHE_DIR="$UV_CACHE_DIR"} \
  bash -c "cd '$workdir' && exec uv tool run $uv_args --from '$source_spec' pii-guard up --no-browser --port $port" \
  >"$log" 2>&1 &
pid=$!
fail() {
  echo "--- server log (tail) ---" >&2
  tail -n 80 "$log" >&2 || true
  echo "wheel-smoke: $*" >&2
  exit 1
}
cleanup() {
  kill -INT "$pid" 2>/dev/null || true
  rm -rf "$workdir"
}
trap cleanup EXIT
# POST JSON; prints the body, fails with it on a non-2xx answer.
post() {
  local out code
  out="$workdir/reply.json"
  code="$(curl -sS -o "$out" -w '%{http_code}' "$base$1" -H 'content-type: application/json' -d "$2")" ||
    fail "POST $1: no answer"
  case "$code" in 2??) cat "$out" ;; *) fail "POST $1 answered $code: $(cat "$out")" ;; esac
}

# Up (install + start), then the NER: chat calls would wait for it anyway, but the judge-facing
# number is the time until /healthz says "ner":"ready".
health=""
up_at=""
while [ $((SECONDS - started)) -lt "$ready_timeout" ]; do
  if ! kill -0 "$pid" 2>/dev/null; then fail "pii-guard up exited during startup"; fi
  if health="$(curl -fsS "$base/healthz" 2>/dev/null)"; then
    [ -n "$up_at" ] || { up_at=$((SECONDS - started)); echo "healthz answered after ${up_at}s"; }
    case "$health" in
      *'"ner":"ready"'* | *'"ner":"off"'*) break ;;
      *'"ner":"failed"'*) fail "the NER failed to load: $health" ;;
    esac
  fi
  sleep 1
done
case "$health" in
  *'"ner":"ready"'* | *'"ner":"off"'*) ;;
  *) fail "the NER was not ready within ${ready_timeout}s: ${health:-no /healthz answer}" ;;
esac
echo "time-to-ready: $((SECONDS - started))s (healthz: $health)"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  echo "- \`$source_spec\` on $(uname -sm): /healthz after ${up_at}s, NER ready after $((SECONDS - started))s" >>"$GITHUB_STEP_SUMMARY"
fi

page="$(curl -fsS "$base/")"
if $expect_ui; then
  grep -q 'id="root"' <<<"$page" || fail "/ is not the bundled UI"
  curl -fsS -o /dev/null "$base/traffic" || fail "/traffic (SPA fallback) did not serve index.html"
  asset="$(grep -m1 -oE '/assets/[^"]+\.js' <<<"$page")"
  asset="${asset%%$'\n'*}"
  curl -fsS -o /dev/null "$base$asset" || fail "the UI asset $asset did not load"
else
  # A source install has no UI bundled: the page must say so, not pretend (LAB-1740).
  grep -q 'pii-guard is running' <<<"$page" || fail "/ is not the no-UI page"
  grep -q 'no web UI bundled' <<<"$page" || fail "the no-UI page does not say the UI is missing"
  echo "no-UI page: served and says the UI is not bundled"
fi
# The console reads the upstream from /v1/status (the page carries no status strip).
status="$(curl -fsS "$base/v1/status")"
grep -Eq '"upstream": *\{[^}]*"mock": *true' <<<"$status" || fail "/v1/status does not say the upstream is the mock"
code="$(curl -s -o /dev/null -w '%{http_code}' "$base/v1/no-such-route")"
[ "$code" = 404 ] || fail "unknown API path answered $code, not 404"

# A fictional name and an example.com email; the mock echoes what it received, so a restored
# answer proves the round trip.
text='Hi, I am Zorblat Quimbleworth, write to zorblat.quimbleworth@example.com'
reply="$(post /v1/chat/completions "{\"model\":\"pii-guard-mock\",\"messages\":[{\"role\":\"user\",\"content\":\"$text\"}]}")"
grep -q "Echo: $text" <<<"$reply" || fail "chat reply was not restored: $reply"
last="$(curl -fsS "$base/v1/traffic?limit=1")"
python3 - "$last" <<'PY' || fail "the traffic log does not show the chat call masked: $last"
import json, sys

events = json.loads(sys.argv[1])["events"]
assert len(events) == 1, "no traffic event"
e = events[0]
masked = (e.get("entities") or {}).get("masked") or {}
assert masked.get("EMAIL"), f"no masked EMAIL: {masked}"
assert (e.get("outbound_check") or {}).get("result") == "passed", e.get("outbound_check")
assert e.get("outcome") == "ok", e.get("outcome")
assert "zorblat" not in json.dumps(e).lower(), "the masked event contains the original"
print(f"traffic: masked {masked}, outbound check passed")
PY
resp_reply="$(post /v1/responses "{\"model\":\"pii-guard-mock\",\"input\":\"$text\"}")"
grep -q "Echo: $text" <<<"$resp_reply" || fail "responses reply was not restored: $resp_reply"
msg_reply="$(post /v1/messages "{\"model\":\"claude-sonnet-4-5\",\"max_tokens\":64,\"messages\":[{\"role\":\"user\",\"content\":\"$text\"}]}")"
grep -q "Echo: $text" <<<"$msg_reply" || fail "messages reply was not restored: $msg_reply"
echo "chat + responses + messages: restored"

if $image; then
  case "$health" in *'"ocr":"on"'*) ;; *) fail "--image needs OCR, but /healthz says: $health" ;; esac
  # A tiny white PNG as an inline image_url part: the request must be masked and forwarded,
  # not refused.
  png="$(python3 -c '
import base64, struct, zlib
w = h = 48
raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
print(base64.b64encode(png).decode())')"
  img_body="{\"model\":\"pii-guard-mock\",\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"What is in this picture?\"},{\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/png;base64,$png\"}}]}]}"
  post /v1/chat/completions "$img_body" >/dev/null
  outcome="$(curl -fsS "$base/v1/traffic?limit=1" | python3 -c 'import json, sys; print(json.load(sys.stdin)["events"][0]["outcome"])')"
  [ "$outcome" = ok ] || fail "the image request's traffic event says $outcome"
  echo "image: masked and forwarded (200)"
fi

kill -INT "$pid"
for _ in $(seq 1 80); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
if kill -0 "$pid" 2>/dev/null; then
  kill -9 "$pid"
  fail "pii-guard up did not stop within 20 s of SIGINT"
fi
wait "$pid" || fail "non-zero exit after SIGINT"
grep -q 'pii-guard is up' "$log" || fail "no banner"
trap - EXIT
rm -rf "$workdir"
[ -n "${PII_GUARD_SMOKE_LOG:-}" ] || rm -f "$log"
echo "wheel-smoke: ok"
