.PHONY: help setup lint format test test-all types gate serve check docker docker-smoke audit licences \
	pii-diff gitleaks links baselines demo demo-traffic smoke smoke-fast bench wheel wheel-smoke

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-13s %s\n", $$1, $$2}'

setup: ## install dependencies and the pre-commit hook
	uv sync
	uv run --with pre-commit pre-commit install

lint: ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## apply ruff fixes and formatting
	uv run ruff check --fix .
	uv run ruff format .

# The fast suite (pull requests) skips the tests marked slow and measures line coverage with the
# sys.monitoring core (about twice as fast as branch coverage on Python 3.12), so it has its own
# floor on its own measure. The full run keeps branch coverage and fail_under from pyproject.toml
# (LAB-1267).
FAST_COV_FLOOR := 90

test: ## fast suite as pull-request CI runs it: parallel, no slow tests, line coverage, its floor
	COVERAGE_CORE=sysmon COVERAGE_BRANCH=false \
		uv run pytest -n auto --dist worksteal -m "not slow" --cov-fail-under=$(FAST_COV_FLOOR)

# test-all keeps the default (C) tracer: its floor is branch coverage, and on Python 3.12
# sys.monitoring measures lines only, so COVERAGE_CORE=sysmon would fall back to it anyway, with
# a warning (coverage.py no-sysmon). Revisit on Python 3.14, where sysmon measures branches.
test-all: ## every test, as main, nightly and manual CI run it: parallel, full coverage floor
	uv run pytest -n auto --dist worksteal

serve: ## run the API on http://127.0.0.1:8787
	uv run pii-guard serve --reload

types: ## mypy on src/, failing only on errors not in scripts/ci/mypy-baseline.txt
	uv run python scripts/ci/mypy_baseline.py

gate: ## quality regression gate: leak / round trip / over-masking vs committed runs (offline)
	uv run python -m pii_guard.eval.gate

check: lint types test gate ## the Python checks CI runs (CONTRIBUTING.md lists every CI job)

docker: ## build the container image
	docker build -t pii-guard:dev .

docker-smoke: docker ## build, then check image size, healthcheck and one masked request
	scripts/ci/docker_smoke.sh pii-guard:dev

audit: ## known vulnerabilities in uv.lock (OSV) and the UI's production dependencies
	uv audit --frozen --preview-features audit
	cd ui && pnpm audit --prod --audit-level high

licences: ## no GPL/AGPL runtime dependency (Python environment as installed, UI production)
	uv run python scripts/ci/licenses.py
	cd ui && pnpm licenses list --prod --json > "$${TMPDIR:-/tmp}/pii-guard-ui-licenses.json"
	uv run python scripts/ci/licenses.py --pnpm-json "$${TMPDIR:-/tmp}/pii-guard-ui-licenses.json"

pii-diff: ## real-looking PII on lines added since origin/develop (pii-guard rules, dogfood)
	uv run python scripts/ci/pii_in_diff.py --base origin/develop

gitleaks: ## secrets in commits since origin/develop (needs gitleaks on PATH off Linux)
	scripts/ci/gitleaks.sh "$$(git merge-base origin/develop HEAD)" HEAD

links: ## relative links in README.md and docs/** (lychee, offline)
	scripts/ci/lychee.sh --offline

baselines: ## compare with Presidio, LLM Guard and PrivAiTe (first run downloads a few GB, once)
	uv sync --extra baselines
	uv run --no-sync pii-guard baselines download
	PII_GUARD_BASELINE_WORKERS=1 uv run --no-sync pytest tests/eval/test_baselines_live.py --no-cov
	uv run --no-sync pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --fixtures eval/fixtures/en-smoke.jsonl \
		--detectors rules --baselines presidio,llm-guard,privaite

# `make demo` runs fast mode: rules + NER. Without PII_GUARD_NER_MODEL the NER is the public
# fallback model (docs/models.md), downloaded once (about 1.1 GB) into ~/.cache/pii-guard/models.
# MODE=rules: rules only, offline, no NER extra and no model download.
MODE ?= fast
DEMO_EXTRAS := --extra local-vision $(if $(filter rules,$(MODE)),,--extra ner)

demo: ## start API + gateway + UI on a mock upstream, fast mode (rules + NER); MODE=rules: offline
	uv run $(DEMO_EXTRAS) python -m pii_guard.visual.segment fetch
	uv run $(DEMO_EXTRAS) python scripts/demo.py --mode $(MODE)

demo-traffic: ## send scripted fictional hu/en/de requests through the running demo gateway
	uv run python scripts/demo_traffic.py

smoke: ## rules only (CI): start the stack on the mock upstream, send the demo traffic, no leak
	uv run python scripts/smoke.py --mode rules

smoke-fast: ## fast mode (local): as smoke with rules + NER, the NER-only scenario must be masked
	uv run --extra ner python scripts/smoke.py --mode fast

bench: ## gateway latency benchmark on the mock upstream (fast mode, concurrency 1 and 8)
	uv run pii-guard bench latency

wheel: ## release wheel with the web UI bundled (needs pnpm): dist/*.whl for `uvx --from`
	cd ui && pnpm install --frozen-lockfile && VITE_PII_GUARD_MODE=api pnpm build
	rm -rf src/pii_guard/_ui dist
	cp -R ui/dist src/pii_guard/_ui
	uv build --wheel
	scripts/ci/wheel_smoke.sh --size-only dist/*.whl

wheel-smoke: ## install dist/*.whl in a throwaway tool env, run `pii-guard up`, check UI + gateway
	scripts/ci/wheel_smoke.sh dist/*.whl
