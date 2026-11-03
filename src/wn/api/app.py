"""The local API. It also serves the built web UI when one exists."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import data_dir as default_data_dir
from ..db import open_catalog, open_profile
from .routes import health, learner, novels

STATIC_DIR = Path(__file__).parent / "static"


def create_app(data_dir: Path | None = None) -> FastAPI:
    root = data_dir or default_data_dir()
    # Create and migrate both databases on startup, then let requests open their own.
    open_catalog(root).close()
    open_profile(root).close()

    app = FastAPI(title="wn-spinner", version=__version__)
    app.state.data_dir = root
    app.state.cache = {}
    app.include_router(health.router, prefix="/api")
    app.include_router(novels.router, prefix="/api")
    app.include_router(learner.router, prefix="/api")

    if (STATIC_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    return app
