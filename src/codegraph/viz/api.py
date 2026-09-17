"""FastAPI application for codegraph-viz (read-only web UI over Neo4j).

The app is built by ``create_app`` so tests can inject a fake adapter. In
production the CLI wires ``Settings`` + a real ``Neo4jAdapter`` under uvicorn.
The MCP stdio server is a separate process and is never touched here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from codegraph.config import Settings
from codegraph.repo.neo4j_adapter import Neo4jAdapter
from codegraph.viz.models import ImpactRequest, SubgraphRequest
from codegraph.viz.service import VizService

_DIST = Path(__file__).resolve().parents[3] / "vizui" / "dist"


def _err(status: int, detail: str, hint: str) -> JSONResponse:
    """Every error the UI sees: what went wrong + what to do about it."""
    return JSONResponse(status_code=status, content={"detail": detail, "hint": hint})


def create_app(settings: Settings, *, adapter: Neo4jAdapter | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo = adapter
        if repo is None:
            repo = Neo4jAdapter.from_settings(settings)
            await repo.connect()
        app.state.service = VizService(repo, settings.repos_dir)
        yield
        if adapter is None:
            await repo.close()

    app = FastAPI(title="codegraph-viz", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _svc() -> VizService:
        return app.state.service  # type: ignore[no-any-return]

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _req: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _err(422, "invalid request arguments", f"Fix the request body/params: {exc.errors()}")

    @app.exception_handler(ValueError)
    async def _value_error(_req: Request, exc: Exception) -> JSONResponse:
        return _err(404, str(exc), "Check the path exists in the selected repository.")

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, _exc: Exception) -> JSONResponse:
        return _err(
            500,
            "internal error",
            "The Neo4j database may be down — run `make up` to start it, then retry.",
        )

    # NOTE: graph_id is a repo slug like `github.com/owner/name` — it contains
    # slashes, and the ASGI server percent-decodes the path before routing, so
    # `%2F` does not help. Every endpoint takes graph_id as a QUERY parameter.
    @app.get("/api/repos")
    async def repos() -> list[dict[str, Any]]:
        return await _svc().repos()

    @app.get("/api/graph")
    async def graph(
        graph_id: str,
        view: str = Query("overview", pattern="^(overview|full)$"),
        depth: int = Query(1, ge=1, le=10),
    ) -> Any:
        if view == "full":
            return await _svc().full_graph(graph_id)
        return await _svc().overview_graph(graph_id, depth=depth)

    @app.post("/api/subgraph")
    async def subgraph(req: SubgraphRequest) -> Any:
        return await _svc().subgraph(req)

    @app.post("/api/impact")
    async def impact(req: ImpactRequest) -> Any:
        return await _svc().impact(req)

    @app.get("/api/expand")
    async def expand(graph_id: str, dir: str = Query("")) -> Any:
        return await _svc().expand_dir(graph_id, dir)

    @app.get("/api/search")
    async def search(
        graph_id: str,
        q: str,
        kind: str = Query("any", pattern="^(any|function|file)$"),
        limit: int = Query(20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return await _svc().search(graph_id, q, kind, limit)

    @app.get("/api/file")
    async def file_detail(graph_id: str, path: str) -> Any:
        return await _svc().file_detail(graph_id, path)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA when present (prod); otherwise just the API."""
    if not (_DIST / "index.html").is_file():
        @app.get("/", include_in_schema=False)
        async def _no_ui() -> JSONResponse:
            return JSONResponse(
                content={
                    "detail": "frontend not built",
                    "hint": "Run `make viz-build` (or `npm run dev` in vizui/ for dev mode).",
                }
            )
        return

    if (_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(_DIST / "index.html")
