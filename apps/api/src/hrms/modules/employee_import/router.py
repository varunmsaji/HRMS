"""HTTP routes for employee_import — thin layer only, per Module Standard §2."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from hrms.core.rbac.dependencies import require_permission
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.core.uploads import read_upload_bounded
from hrms.modules.employee_import.dependencies import get_employee_import_service
from hrms.modules.employee_import.permissions import EMPLOYEE_BULK_IMPORT
from hrms.modules.employee_import.schemas import (
    MAX_IMPORT_FILE_SIZE_BYTES,
    EmployeeImportBatchRead,
    EmployeeImportRowErrorRead,
)
from hrms.modules.employee_import.service import EmployeeImportService
from hrms.modules.identity.schemas import build_meta
from hrms.shared.pagination import DataEnvelope, ListEnvelope

router = APIRouter(tags=["employee_import"])


@router.post("/employee-imports", status_code=status.HTTP_201_CREATED)
async def create_employee_import(
    file: Annotated[UploadFile, File()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_BULK_IMPORT))],
    service: Annotated[EmployeeImportService, Depends(get_employee_import_service)],
) -> DataEnvelope[EmployeeImportBatchRead]:
    # SEC-03 — bounded read, mirroring the onboarding public upload fix; see
    # hrms.core.uploads for why the actual early-rejection enforcement is the ASGI-level
    # `MaxUploadSizeMiddleware` (app.py) rather than anything that can run inside this handler.
    body = await read_upload_bounded(file, max_bytes=MAX_IMPORT_FILE_SIZE_BYTES)
    data = await service.create_batch(
        tenant.company_id,
        filename=file.filename or "upload.csv",
        file_bytes=body,
        actor_user_id=tenant.user_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/employee-imports/template", status_code=status.HTTP_200_OK)
async def get_employee_import_template(
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_BULK_IMPORT))],
    service: Annotated[EmployeeImportService, Depends(get_employee_import_service)],
) -> Response:
    csv_text = service.get_template()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="employee_import_template.csv"'},
    )


@router.get("/employee-imports/reference-data", status_code=status.HTTP_200_OK)
async def get_employee_import_reference_data(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_BULK_IMPORT))],
    service: Annotated[EmployeeImportService, Depends(get_employee_import_service)],
) -> DataEnvelope[dict[str, list[dict[str, str]]]]:
    data = await service.get_reference_data(tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/employee-imports/{batch_id}", status_code=status.HTTP_200_OK)
async def get_employee_import(
    batch_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_BULK_IMPORT))],
    service: Annotated[EmployeeImportService, Depends(get_employee_import_service)],
) -> DataEnvelope[EmployeeImportBatchRead]:
    data = await service.get_batch(tenant.company_id, batch_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/employee-imports/{batch_id}/errors", status_code=status.HTTP_200_OK)
async def list_employee_import_errors(
    batch_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_BULK_IMPORT))],
    service: Annotated[EmployeeImportService, Depends(get_employee_import_service)],
) -> ListEnvelope[EmployeeImportRowErrorRead]:
    data = await service.list_row_errors(tenant.company_id, batch_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
