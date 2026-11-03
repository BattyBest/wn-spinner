.PHONY: setup dev run build test lint fmt

setup:
	uv sync
	pnpm --dir frontend install

# API with reload on :8000 and the Vite dev server on :5173 (proxies /api to :8000).
dev:
	@trap 'kill 0' INT TERM EXIT; \
	uv run wn serve --reload --port 8000 & \
	pnpm --dir frontend dev & \
	wait

# Build the UI and serve everything from one process on :8000.
run: build
	uv run wn serve --port 8000

build:
	pnpm --dir frontend build

test:
	uv run pytest
	pnpm --dir frontend check

lint:
	uv run ruff check .
	uv run ruff format --check .
	pnpm --dir frontend lint

fmt:
	uv run ruff check --fix .
	uv run ruff format .
	pnpm --dir frontend format
