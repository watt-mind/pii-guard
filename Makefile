.PHONY: help setup lint format test serve check docker

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
