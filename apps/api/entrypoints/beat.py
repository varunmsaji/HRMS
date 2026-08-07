"""Celery beat uses the same application object as the worker (Document 06 §2)."""

from entrypoints.worker import app

__all__ = ["app"]
