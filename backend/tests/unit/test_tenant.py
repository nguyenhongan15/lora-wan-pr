"""
tests/unit/test_tenant.py — Unit test cho core.tenant middleware.

Test bằng cách dispatch trực tiếp middleware với mock Request/call_next.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.tenant import TenantMiddleware


def _make_request(headers: dict) -> SimpleNamespace:
    """Mock fastapi.Request với .headers và .state."""
    return SimpleNamespace(
        headers=headers,
        state=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_dispatch_valid_uuid_header_sets_project_id_on_request_state():
    # Arrange
    valid_uuid = "d0000000-0000-0000-0000-000000000001"
    request    = _make_request({"x-project-id": valid_uuid})
    call_next  = AsyncMock(return_value="response_ok")

    middleware = TenantMiddleware(app=AsyncMock())

    # Act
    response = await middleware.dispatch(request, call_next)

    # Assert
    assert request.state.project_id == uuid.UUID(valid_uuid)
    assert response == "response_ok"


@pytest.mark.asyncio
async def test_dispatch_invalid_uuid_header_returns_422_without_calling_next():
    # Arrange
    request   = _make_request({"x-project-id": "not-a-uuid"})
    call_next = AsyncMock()

    middleware = TenantMiddleware(app=AsyncMock())

    # Act
    response = await middleware.dispatch(request, call_next)

    # Assert — 422 + call_next KHÔNG được gọi
    assert response.status_code == 422
    call_next.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_missing_header_sets_project_id_none_and_passes_through():
    # Arrange
    request   = _make_request({})
    call_next = AsyncMock(return_value="response_ok")

    middleware = TenantMiddleware(app=AsyncMock())

    # Act
    response = await middleware.dispatch(request, call_next)

    # Assert
    assert request.state.project_id is None
    assert response == "response_ok"