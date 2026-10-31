#!/usr/bin/env bash
# Docker image smoke test (CI job "docker"; locally: make docker-smoke).
#
#   scripts/ci/docker_smoke.sh [IMAGE]        # default pii-guard:dev, already built
#
# 1. The image is within its size budget (IMAGE_BUDGET_MB, committed here), measured as the
#    unpacked root filesystem (du inside the container). `docker image inspect .Size` depends
#    on the image store: Docker Desktop's containerd store reports ~429 MB for the same image
#    that the classic store on a CI runner reports as ~274 MB; du gives ~290 MB (amd64, CI)
#    to ~316 MB (arm64).
# 2. The image runs read-only as in compose.yaml: the mock upstream and the API from the same
#    image on a private network; /healthz answers and the container healthcheck (which also
#    checks OCR) turns healthy.
# 3. One chat request with fictional PII goes through the gateway: the answer is restored
#    exactly and the upstream (the mock records what it receives) never saw a raw value.
# Offline apart from the image itself; no key, no model download.
set -euo pipefail

IMAGE="${1:-pii-guard:dev}"
# 375 MB until LAB-1245; the local-vision extra (OpenCV headless + numpy, ~160 MB unpacked) and
# the YuNet model for the default hybrid segmenter take the arm64 image from ~317 to ~478 MB.
# LAB-1407 adds vetted authenticated encryption for persisted provider credentials.
# The first amd64 CI build with cryptography measured 541 MB; reserve 9 MB headroom.
# Keep OCR/vision in the image rather than dropping protection to meet the old footprint.
# LAB-1733 made the NER a core dependency; this image skips it and measured 544 MB. LAB-1734
# raises the budget to 650 MB for ordinary growth; torch leaking in (+1 GB) still fails here.
IMAGE_BUDGET_MB="${IMAGE_BUDGET_MB:-650}"
NET="pii-guard-smoke-$$"
API_PORT="${SMOKE_API_PORT:-18797}"
MOCK_PORT="${SMOKE_MOCK_PORT:-18798}"

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- api logs" >&2
    docker logs "$NET-api" 2>&1 | tail -40 >&2 || true
  fi
  docker rm -f "$NET-api" "$NET-mock" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

size_kb=$(docker run --rm --network none --entrypoint sh "$IMAGE" -c 'du -sxk / 2>/dev/null | cut -f1')
size_mb=$((size_kb * 1024 / 1000000))
echo "image $IMAGE: ${size_mb} MB (budget ${IMAGE_BUDGET_MB} MB)"
if [ "$size_mb" -gt "$IMAGE_BUDGET_MB" ]; then
  echo "docker smoke: FAILED: image is ${size_mb} MB, over the ${IMAGE_BUDGET_MB} MB budget" >&2
  exit 1
fi

docker network create "$NET" >/dev/null
docker run -d --name "$NET-mock" --network "$NET" --network-alias mock --read-only \
  -p "127.0.0.1:${MOCK_PORT}:8790" \
  "$IMAGE" pii-guard bench mock-upstream --host 0.0.0.0 --port 8790 >/dev/null
# Exercise the image's real OCR healthcheck promptly instead of its production 30 s cadence.
docker run -d --name "$NET-api" --network "$NET" --read-only --health-interval=2s \
  -p "127.0.0.1:${API_PORT}:8787" \
  -e PII_GUARD_UPSTREAM_BASE_URL=http://mock:8790/v1 \
  -e PII_GUARD_UPSTREAM_API_KEY= \
  -e PII_GUARD_GATEWAY_MODE=fast \
  -e PII_GUARD_TENANT_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  "$IMAGE" >/dev/null

wait_for() {  # url, name
  for _ in $(seq 1 60); do
    if curl -fsS "$1" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "docker smoke: FAILED: $2 did not answer at $1" >&2
  return 1
}
wait_for "http://127.0.0.1:${MOCK_PORT}/healthz" "mock upstream"
wait_for "http://127.0.0.1:${API_PORT}/healthz" "API"
echo "healthz: $(curl -fsS "http://127.0.0.1:${API_PORT}/healthz")"

for _ in $(seq 1 60); do
  health=$(docker inspect -f '{{.State.Health.Status}}' "$NET-api")
  [ "$health" = "healthy" ] && break
  [ "$health" = "unhealthy" ] && break
  sleep 1
done
echo "container health: $health"
if [ "$health" != "healthy" ]; then
  echo "docker smoke: FAILED: container healthcheck is $health (OCR missing?)" >&2
  exit 1
fi

python3 - "$API_PORT" "$MOCK_PORT" <<'PY'
import json, sys, urllib.error, urllib.request

api, mock = sys.argv[1], sys.argv[2]
# Fictional values only (ADR 0005): a reserved example domain and a checksum-valid test TAJ.
email, taj = "teszt.elek@example.com", "123 456 788"
text = f"Kérem, írjon a {email} címre, a TAJ számom {taj}."
body = {"model": "pii-guard-mock", "messages": [{"role": "user", "content": text}]}
req = urllib.request.Request(
    f"http://127.0.0.1:{api}/v1/chat/completions",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json", "X-PII-Guard-Language": "hu"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        answer = json.load(r)["choices"][0]["message"]["content"]
except urllib.error.HTTPError as exc:
    print(f"docker smoke: FAILED: gateway answered {exc.code}: {exc.read()[:300]!r}", file=sys.stderr)
    sys.exit(1)
with urllib.request.urlopen(f"http://127.0.0.1:{mock}/_mock/received", timeout=10) as r:
    received = json.dumps(json.load(r), ensure_ascii=False)
failures = []
if email in received or taj in received:
    failures.append("a raw value reached the upstream")
if "[[" not in received:
    failures.append("the upstream saw no placeholder")
if email not in answer or taj not in answer:
    failures.append("the answer was not restored")
if failures:
    print("docker smoke: FAILED: " + "; ".join(failures), file=sys.stderr)
    sys.exit(1)
print("masked request: upstream saw placeholders only, answer restored")
PY
echo "docker smoke: OK"
