from __future__ import annotations

from fastapi import APIRouter, Request

from ... import __version__
from ...db import open_catalog, open_profile
from ...db.migrate import current_version

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict:
    root = request.app.state.data_dir
    catalog, profile = open_catalog(root), open_profile(root)
    try:
        return {
            "status": "ok",
            "version": __version__,
            "catalog_version": current_version(catalog),
            "profile_version": current_version(profile),
        }
    finally:
        catalog.close()
        profile.close()


@router.get("/stats")
def stats(request: Request) -> dict:
    catalog = open_catalog(request.app.state.data_dir)
    try:
        novels = catalog.execute("SELECT COUNT(*) FROM novel").fetchone()[0]
        cache = catalog.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM cache_entry"
        ).fetchone()
        sources = catalog.execute(
            "SELECT s.name, s.language, COUNT(n.id) AS novels FROM source s"
            " LEFT JOIN novel n ON n.source_id = s.id GROUP BY s.id ORDER BY s.name"
        ).fetchall()
        return {
            "novels": novels,
            "cache_pages": cache[0],
            "cache_bytes": cache[1],
            "sources": [dict(r) for r in sources],
        }
    finally:
        catalog.close()
