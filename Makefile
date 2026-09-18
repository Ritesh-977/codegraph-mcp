.PHONY: dev install up down test test-slow lint typecheck inspector run serve snapshot-update viz viz-dev viz-build viz-test

dev:            ## install dev deps
	uv sync --extra dev

install:        ## install runtime deps only
	uv sync

up:             ## start local Neo4j
	docker compose up -d neo4j

down:           ## stop Neo4j
	docker compose down

test:           ## unit + non-Docker tests
	uv run pytest -m "not slow and not integration"

test-slow:      ## all tests incl. Docker integration
	uv run pytest

lint:           ## ruff
	uv run ruff check src tests

typecheck:      ## mypy
	uv run mypy src

inspector:      ## MCP Inspector
	uv run mcp dev src/codegraph/server.py

run:            ## run server (stdio)
	uv run codegraph serve

serve:          ## alias for run
	uv run codegraph serve

snapshot-update:  ## regenerate contract snapshots
	uv run pytest tests/contract --snapshot-update

viz:            ## run the local web UI (browser graph viewer)
	uv run codegraph viz

# Dev mode is two processes: this runs the API only — run `npm run dev` in
# vizui/ from a second terminal for Vite on :5173 proxying /api.
viz-dev:        ## run the API for dev mode (pair with `npm run dev` in vizui/)
	uv run codegraph viz

viz-build:      ## build the frontend bundle into vizui/dist
	cd vizui && npm install && npm run build

viz-test:       ## frontend unit tests + typecheck
	cd vizui && npm test && npm run typecheck
