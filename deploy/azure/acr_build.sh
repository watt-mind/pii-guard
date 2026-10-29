#!/usr/bin/env bash
# Build Dockerfile.hosted in Azure Container Registry with a registry layer cache (LAB-1446).
#
#   ACR_NAME=<registry> deploy/azure/acr_build.sh [--registry NAME] [--tag-prefix PREFIX] [REF]
#
# REF (default HEAD, or ACR_BUILD_REF) is exported with `git archive`, so only committed files
# reach the build. The image is tagged <PREFIX>-<short sha> (PREFIX default `develop`, or
# ACR_TAG_PREFIX) and pushed; stdout is exactly three lines:
#
#   TAG <prefix>-<sha>
#   DIGEST sha256:<64 hex>
#   IMAGE <registry>.azurecr.io/pii-guard@sha256:<64 hex>   (HOSTED_IMAGE for deploy.sh)
#
# Build logs go to stderr. Uses the caller's existing `az login`; holds no secret.
#
# Cache: the agent's docker build is BuildKit with the docker driver, which exports only inline
# cache, and inline cache covers only the stage it tags. Each stage is therefore built and pushed
# as its own cache image (pii-guard:buildcache-<stage>), and every build reads all of them, so a
# src-only change reuses the dependency, model and apt layers. python-deps and ner-model are
# ancestors of python-build, so its cache image covers them.
set -euo pipefail

usage() {
  echo 'Usage: ACR_NAME=<registry> deploy/azure/acr_build.sh [--registry NAME] [--tag-prefix PREFIX] [REF]' >&2
  exit 2
}

registry=${ACR_NAME:-}
prefix=${ACR_TAG_PREFIX:-develop}
ref=${ACR_BUILD_REF:-HEAD}
while (($#)); do
  case "$1" in
    -r|--registry) (($# >= 2)) || usage; registry=$2; shift 2;;
    -p|--tag-prefix) (($# >= 2)) || usage; prefix=$2; shift 2;;
    -h|--help) usage;;
    -*) usage;;
    *) ref=$1; shift;;
  esac
done
[[ -n "$registry" ]] || { echo 'Set ACR_NAME (or --registry) to the target registry name' >&2; exit 2; }
[[ "$registry" =~ ^[a-z0-9]{5,50}$ ]] || { echo 'Registry name must be 5-50 lowercase letters or digits' >&2; exit 2; }
[[ "$prefix" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]] || { echo 'Invalid tag prefix' >&2; exit 2; }

cd "$(dirname "$0")/../.."
sha=$(git rev-parse --verify --quiet "${ref}^{commit}") || { echo "Unknown git ref: $ref" >&2; exit 2; }
tag="${prefix}-$(git rev-parse --short=7 "$sha")"
repo=pii-guard
cache="\$Registry/${repo}:buildcache"

context=$(mktemp -d)
trap 'rm -rf "$context"' EXIT
git archive --format=tar "$sha" | tar -x -C "$context"
[[ -f "$context/Dockerfile.hosted" ]] || { echo "No Dockerfile.hosted at $ref" >&2; exit 2; }

# The task file must sit inside the uploaded context; .dockerignore does not exclude it.
# Steps run in order on one agent, so later stages reuse the earlier ones' local cache.
# RUN --mount needs BuildKit, hence DOCKER_BUILDKIT=1 on every build step.
from="--cache-from ${cache}-python-build --cache-from ${cache}-ui-build --cache-from ${cache}"
inline="--build-arg BUILDKIT_INLINE_CACHE=1 -f Dockerfile.hosted"
cat > "$context/acr-task.yaml" <<YAML
version: v1.1.0
stepTimeout: 2400
steps:
  - id: python-build
    build: -t ${cache}-python-build --target python-build ${from} ${inline} .
    env: ["DOCKER_BUILDKIT=1"]
  - id: ui-build
    build: -t ${cache}-ui-build --target ui-build ${from} ${inline} .
    env: ["DOCKER_BUILDKIT=1"]
  - id: image
    build: -t \$Registry/${repo}:${tag} -t ${cache} ${from} ${inline} .
    env: ["DOCKER_BUILDKIT=1"]
  - id: push
    push:
      - \$Registry/${repo}:${tag}
      - ${cache}
      - ${cache}-python-build
      - ${cache}-ui-build
YAML

echo "acr_build: building ${repo}:${tag} ($sha) in $registry" >&2
start=$SECONDS
az acr run --registry "$registry" --file acr-task.yaml --timeout 3600 "$context" >&2
echo "acr_build: finished in $((SECONDS - start))s" >&2

digest=$(az acr repository show --name "$registry" --image "${repo}:${tag}" --query digest --output tsv)
[[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo "Unexpected digest for ${repo}:${tag}: $digest" >&2; exit 1; }
echo "TAG $tag"
echo "DIGEST $digest"
echo "IMAGE ${registry}.azurecr.io/${repo}@${digest}"
