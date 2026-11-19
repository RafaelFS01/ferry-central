"""Ponto de entrada da aplicação FastAPI para a API REST interna da Central."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import ApiSettings
from src.api.routes.boats import router as boats_router
from src.api.routes.compat import router as compat_router
from src.api.routes.health import router as health_router
from src.api.routes.metrics import router as metrics_router
from src.database.session import dispose_engine, get_session_factory
from src.logging_config import configure_json_logging

logger = logging.getLogger(__name__)


def configure_logging(level: str = "INFO") -> None:
    """Configura logging estruturado em JSON para a API REST da Central."""
    configure_json_logging(service="api", level=level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gerencia ciclo de vida dos recursos assíncronos da API (Engine e Conexões)."""
    logger.info("Inicializando recursos da API REST da Central...")
    # Garante que o pool de conexões do SQLAlchemy 2.0 está acessível
    get_session_factory()
    try:
        yield
    finally:
        logger.info("Finalizando recursos e liberando pool de banco de dados...")
        await dispose_engine()


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Fábrica de aplicação FastAPI com middlewares e roteadores registrados."""
    cfg = settings or ApiSettings.from_env()

    app = FastAPI(
        title="Ferry Telemetry Central REST API",
        description="API REST interna para desacoplamento de consultas, traçado de rotas e telemetria náutica.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Configuração de CORS para viabilizar integração com painéis Next.js locais ou remotos
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Registro das rotas da API
    app.include_router(boats_router)
    app.include_router(metrics_router)
    app.include_router(compat_router)
    app.include_router(health_router)

    return app


app = create_app()


def run_api_server(settings: ApiSettings | None = None) -> None:
    """Inicia o servidor HTTP da API REST via Uvicorn."""
    cfg = settings or ApiSettings.from_env()
    configure_logging(cfg.log_level)
    uvicorn.run(
        "src.api.main:app",
        host=cfg.api_host,
        port=cfg.api_port,
        log_level=cfg.log_level.lower(),
        log_config=None,
        access_log=True,
    )


if __name__ == "__main__":
    run_api_server()
