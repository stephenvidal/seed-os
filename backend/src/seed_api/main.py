"""Application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, auth, runs, system
from .config import Settings, get_settings
from .errors import install_error_handlers
from .flow import api as tasks_api
from .flow.db import make_pool, migrate
from .flow.store import TaskStore

logging.basicConfig(
    level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}'
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.database_url is None:
            logging.getLogger("seed").warning("SEED_DATABASE_URL unset: tasks are disabled")
            yield
            return
        pool = make_pool(settings.database_url.get_secret_value())
        await pool.open(wait=True, timeout=30)
        try:
            await migrate(pool)
            app.state.task_store = TaskStore(pool)
            yield
        finally:
            await pool.close()

    app = FastAPI(
        title="SEED API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )
    install_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(system.router)
    app.include_router(runs.router)
    app.include_router(tasks_api.router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if settings.admin_password is None:
        logging.getLogger("seed").warning("SEED_ADMIN_PASSWORD unset: sign-in disabled")
    return app


app = create_app()
