"""Routers for ``/v1/*``.

Each module in this package that defines a module-level ``router`` (a
``fastapi.APIRouter``) is mounted by :func:`include_routers`, in module-name order. Routers
declare full paths (``@router.post("/v1/analyze")``), so adding an endpoint means adding a
module here and nothing else. Import errors propagate: a broken router stops the app from
starting instead of silently disappearing.
"""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import APIRouter, FastAPI

__all__ = ["discover_routers", "include_routers"]


def discover_routers() -> list[APIRouter]:
    routers: list[APIRouter] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            routers.append(router)
    return routers


def include_routers(app: FastAPI) -> None:
    for router in discover_routers():
        app.include_router(router)
