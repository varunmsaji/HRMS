"""A broker outage while queueing a range calculation is a retryable 503 with nothing recorded,
never a bare 500 and never a "queued" success."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from hrms.modules.attendance.exceptions import AttendanceQueueUnavailableError
from hrms.modules.attendance.schemas import AttendanceRangeCalculateInput
from hrms.modules.attendance.service import AttendanceDayService

pytestmark = pytest.mark.asyncio


async def test_broker_failure_is_503_and_writes_no_audit() -> None:
    service = AttendanceDayService(MagicMock())
    service._audit = MagicMock(record=AsyncMock())
    yesterday = date.today() - timedelta(days=2)
    body = AttendanceRangeCalculateInput(date_from=yesterday, date_to=yesterday)

    with (
        patch(
            "hrms.modules.organisation.service.OrganisationService.get_company_profile",
            AsyncMock(return_value=SimpleNamespace(timezone="UTC")),
        ),
        patch(
            "hrms.modules.attendance.tasks.calculate_range.delay",
            side_effect=ConnectionError("redis://user:secret@broker:6379 refused"),
        ),
        pytest.raises(AttendanceQueueUnavailableError) as caught,
    ):
        await service.queue_range_calculation(uuid4(), body, actor_user_id=uuid4())

    assert caught.value.status_code == 503
    assert caught.value.headers == {"Retry-After": "5"}
    assert "secret" not in caught.value.message
    service._audit.record.assert_not_called()
