from fastapi import APIRouter

router = APIRouter(tags=["ingestion"])


@router.get("/ingestion/health")
async def ingestion_health() -> dict[str, str]:
    return {"status": "ok"}
