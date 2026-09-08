"""Vercel FastAPI entrypoint for the online-only SSR deployment."""

import os

os.environ.setdefault("REVIEWER_DEMO_MODE", "true")

from app.main import app


__all__ = ["app"]
