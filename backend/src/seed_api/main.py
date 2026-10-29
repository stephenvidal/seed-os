"""Application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, auth, models, system
from .chat import api as chat_api
from .chat.store import ChatStore
from .config import Settings, get_settings
from .errors import install_error_handlers
from .flow import api as tasks_api
from .flow import overview
from .flow.db import make_pool, migrate
from .flow.store import TaskStore
from .projects import api as projects_api
from .projects.knowledge import KnowledgeStore
from .projects.memory import MemoryStore
from .projects.store import ProjectStore
from .studio import api as studio_api
from .studio.store import ArtifactStore

logging.basicConfig(
    level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}'
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.database_url is None:
            logging.getLogger("seed").warning(
                "SEED_DATABASE_URL unset: sign-in, tasks and chat are disabled"
            )
            yield
            return
        pool = make_pool(settings.database_url.get_secret_value())
        await pool.open(wait=True, timeout=30)
        try:
            await migrate(pool)
            app.state.task_store = TaskStore(pool)
            app.state.chat_store = ChatStore(pool)
            app.state.project_store = ProjectStore(pool)
            app.state.memory_store = MemoryStore(pool)
            app.state.knowledge_store = KnowledgeStore(pool)
            app.state.auth_store = auth.AuthStore(pool)
            root = settings.artifact_root
            app.state.artifact_store = ArtifactStore(pool, Path(root) if root else None)
            await auth.bootstrap_admin(app.state.auth_store, settings)
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
            allow_headers=["Content-Type", auth.CSRF_HEADER],
        )
    install_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(system.router)
    app.include_router(models.router)
    app.include_router(tasks_api.router)
    app.include_router(chat_api.router)
    app.include_router(projects_api.router)
    app.include_router(overview.router)
    app.include_router(studio_api.router)
    app.include_router(studio_api.previews)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
