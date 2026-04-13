"""Point d'entrée FastAPI — 3D Print Factory v4.

Responsabilités (Phase 1) :
- Créer l'app FastAPI
- Initialiser la BDD au démarrage (tables + settings par défaut)
- Brancher le middleware Basic Auth
- Exposer `GET /api/health` (public, utilisé pour monitoring)
- Servir le frontend Vite (`frontend/dist`) en static si build présent

Les routers métier (pipeline, models3d, exports, services, stats) seront
ajoutés en Phase 2+.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
from auth import basic_auth_middleware
from database import init_db
from routers import models3d as models3d_router
from routers import pipeline as pipeline_router
from routers import services as services_router


class SPAStaticFiles(StaticFiles):
    """StaticFiles avec fallback vers `index.html` pour le routing client.

    Sans ça, recharger `/models` ou `/settings` dans le navigateur renvoie
    un 404 parce que ces routes n'existent que côté React Router.

    Le fallback se déclenche **uniquement** si le path ressemble à une route
    SPA (pas d'extension de fichier). Un asset manquant comme
    `/assets/foo.js` continue de renvoyer 404 — sinon le navigateur
    tenterait d'exécuter du HTML comme du JS, ce qui masque les bugs.
    """

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                return await super().get_response("index.html", scope)
            raise


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cycle de vie de l'app : initialise la BDD au démarrage."""
    init_db()
    logger.info("3D Factory backend ready (data dir: %s)", config.DATA_DIR)
    yield


app = FastAPI(title="3D Print Factory", version="4.0.0", lifespan=lifespan)

# Middleware d'authentification — s'applique à toutes les routes sauf celles
# déclarées publiques dans auth.py.
app.middleware("http")(basic_auth_middleware)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    """Healthcheck public (pas d'auth) pour monitoring / uptime."""
    return {"status": "ok"}


# Routers métier
app.include_router(pipeline_router.router)
app.include_router(models3d_router.router)
app.include_router(services_router.router)


# --------------------------------------------------------------------------- #
# Frontend static — monté en dernier pour ne pas masquer les routes /api/*
# --------------------------------------------------------------------------- #
if config.FRONTEND_DIST.is_dir():
    app.mount(
        "/",
        SPAStaticFiles(directory=config.FRONTEND_DIST, html=True),
        name="frontend",
    )
    logger.info("Serving frontend static from %s", config.FRONTEND_DIST)
else:
    logger.warning(
        "Frontend build absent (%s) — run `cd frontend && npm run build`",
        config.FRONTEND_DIST,
    )
