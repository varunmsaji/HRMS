"""
Application entry alias.

The FastAPI factory lives in ``hrms.app.create_app``. Production and local dev
use ``entrypoints/api.py`` (Document 06 §2). Import ``create_app`` from here
when tooling expects ``hrms.main``.
"""

from hrms.app import create_app

__all__ = ["create_app"]
