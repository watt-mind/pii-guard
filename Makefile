.PHONY: help setup lint format test serve check docker baselines

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

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

check: lint test ## everything CI runs

docker: ## build the container image
	docker build -t pii-guard:dev .

baselines: ## compare with Presidio, LLM Guard and PrivAiTe (first run downloads a few GB)
	uv sync --extra baselines
	PII_GUARD_BASELINE_WORKERS=1 uv run pytest tests/eval/test_baselines_live.py --no-cov
	uv run pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --fixtures eval/fixtures/en-smoke.jsonl \
		--detectors rules --baselines presidio,llm-guard,privaite
