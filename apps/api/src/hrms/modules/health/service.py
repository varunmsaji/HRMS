from typing import Literal

from pydantic import BaseModel

from hrms.core.db.session import get_engine
from hrms.core.errors.handlers import server_meta
from hrms.core.tenancy.context import current_request_id
from hrms.shared.pagination import DataEnvelope, ResponseMeta


class HealthData(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    database: Literal["ok", "error"] = "ok"
    redis: Literal["ok", "error", "skipped"] = "skipped"


class HealthService:
    async def check(self) -> HealthData:
        db_status: Literal["ok", "error"] = "ok"
        try:
            from sqlalchemy import text
            from sqlalchemy.exc import SQLAlchemyError

            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except SQLAlchemyError:
            db_status = "error"

        overall: Literal["ok", "degraded"] = "ok" if db_status == "ok" else "degraded"
        return HealthData(status=overall, database=db_status, redis="skipped")


def build_health_envelope(data: HealthData) -> DataEnvelope[HealthData]:
    request_id = current_request_id() or "unknown"
    meta = ResponseMeta(request_id=request_id, server_time=server_meta()["server_time"])
    return DataEnvelope(data=data, meta=meta)
