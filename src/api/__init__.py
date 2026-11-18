"""Módulo de API REST interna do Nó Central (FastAPI / Pydantic v2)."""

from src.api.main import app, create_app

__all__ = ["app", "create_app"]
