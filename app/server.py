"""Vercel FastAPI entrypoint for the online-only SSR deployment."""

from app.main import app


__all__ = ["app"]
