"""Application factory."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, auth, system
from .config import get_settings
from .errors import install_error_handlers

logging.basicConfig(
    level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}'
)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SEED API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json"
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

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if settings.admin_password is None:
        logging.getLogger("seed").warning("SEED_ADMIN_PASSWORD unset: sign-in disabled")
    return app


app = create_app()
