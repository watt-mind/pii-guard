.PHONY: help setup lint format test types gate serve check docker docker-smoke audit licences \
	pii-diff gitleaks links baselines demo demo-traffic smoke bench

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

test: ## run the test suite with coverage
	uv run pytest

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

baselines: ## compare with Presidio, LLM Guard and PrivAiTe (first run downloads a few GB)
	uv sync --extra baselines
	PII_GUARD_BASELINE_WORKERS=1 uv run pytest tests/eval/test_baselines_live.py --no-cov
	uv run pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --fixtures eval/fixtures/en-smoke.jsonl \
		--detectors rules --baselines presidio,llm-guard,privaite

demo: ## start API + gateway + UI on a mock upstream (offline); real upstream if configured
	uv run --extra local-vision python -m pii_guard.visual.segment fetch
	uv run --extra local-vision python scripts/demo.py

demo-traffic: ## send scripted fictional hu/en/de requests through the running demo gateway
	uv run python scripts/demo_traffic.py

smoke: ## start the stack on the mock upstream, send the demo traffic, assert nothing leaked
	uv run python scripts/smoke.py

bench: ## gateway latency benchmark on the mock upstream (fast mode, concurrency 1 and 8)
	uv run pii-guard bench latency
