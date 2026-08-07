from fastapi import FastAPI

from hrms.app import create_app
from hrms.ingestion.routes import router as ingestion_router


def create_ingestion_app() -> FastAPI:
    app = create_app()
    app.include_router(ingestion_router, prefix="/v1")
    return app


app = create_ingestion_app()
