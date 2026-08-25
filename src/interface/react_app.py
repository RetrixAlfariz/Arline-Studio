from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from src.interface.web.app import create_app as create_backend_app
from src.runtime_config import DEFAULT_CONFIG_PATH, RuntimeConfig


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_ROOT / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


def _frontend_built() -> bool:
    return FRONTEND_INDEX.is_file() and (FRONTEND_DIST / "assets").is_dir()


def _remove_legacy_root(app: FastAPI) -> None:
    """Remove only the old GET / HTML route when a Vite build is available.

    The backend API, /static compatibility mount, media routes, downloads, and
    every Python service remain untouched. The legacy UI therefore stays a
    fallback for source checkouts that have not run the frontend build yet.
    """
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/"
            and "GET" in (getattr(route, "methods", None) or set())
        )
    ]


def create_app(config_path: Path | str = DEFAULT_CONFIG_PATH) -> FastAPI:
    app = create_backend_app(config_path)
    react_ready = _frontend_built()

    @app.get("/api/frontend", include_in_schema=False)
    def frontend_status() -> dict[str, object]:
        return {
            "mode": "react" if react_ready else "legacy-fallback",
            "built": react_ready,
            "frontend_root": "frontend/dist" if react_ready else "src/interface/web/static",
        }

    if not react_ready:
        return app

    _remove_legacy_root(app)
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="react-assets",
    )

    @app.get("/", include_in_schema=False)
    def react_index() -> FileResponse:
        return FileResponse(FRONTEND_INDEX)

    return app


def launch_ui(config_path: Path | str = DEFAULT_CONFIG_PATH) -> None:
    cfg = RuntimeConfig.load(config_path)
    host = str(cfg.ui.host or "127.0.0.1").strip().lower()
    if host not in {"127.0.0.1", "localhost", "::1"} and os.getenv(
        "ARLINE_ALLOW_UNAUTHENTICATED_REMOTE_UI"
    ) != "1":
        raise RuntimeError(
            "Refusing unauthenticated remote UI bind. Keep ui.host on loopback "
            "or explicitly set ARLINE_ALLOW_UNAUTHENTICATED_REMOTE_UI=1."
        )
    uvicorn.run(create_app(config_path), host=cfg.ui.host, port=cfg.ui.port)
