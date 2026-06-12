"""Tests cho ChirpstackWebhookService — adapter + idempotent write.

Dùng FakeSurveyIngest để test idempotency thật sự (replay = 0 mới).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from lora_coverage_api.application.chirpstack_webhook_service import (
    ChirpstackWebhookService,
)
from lora_coverage_api.application.webhook_auth import WebhookContext

from ..fakes.survey_ingest import FakeSurveyIngest

_CONTEXT = WebhookContext(
    user_id=UUID("11111111-1111-1111-1111-111111111111"),
    linked_source_id=UUID("22222222-2222-2222-2222-222222222222"),
    source_type="chirpstack",
)


def _uplink(dedup: str = "dedup-A", rx_count: int = 1, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "deduplicationId": dedup,
        "deviceInfo": {"devEui": "a70174b2883514a3"},
        "txInfo": {
            "frequency": 921400000,
            "modulation": {"lora": {"spreadingFactor": 10}},
        },
        "object": {"gnss_latitude": 16.0741, "gnss_longitude": 108.1525},
        "rxInfo": [{"gatewayId": f"gw{i}", "rssi": -100 - i, "snr": -3} for i in range(rx_count)],
        "time": "2025-12-18T07:04:28.923090+00:00",
    }
    base.update(over)
    return base


def test_first_call_inserts_all() -> None:
    fake = FakeSurveyIngest()
    svc = ChirpstackWebhookService(fake)
    receipt = svc.ingest_uplink(_uplink(rx_count=2), _CONTEXT)
    assert receipt.accepted_count == 2
    assert receipt.inserted_count == 2
    assert receipt.rejected_count == 0


def test_replay_same_uplink_dedups() -> None:
    """ChirpStack retry cùng uplink → 0 record mới (đã in trước đó)."""
    fake = FakeSurveyIngest()
    svc = ChirpstackWebhookService(fake)
    up = _uplink(rx_count=2)
    svc.ingest_uplink(up, _CONTEXT)
    receipt2 = svc.ingest_uplink(up, _CONTEXT)
    assert receipt2.accepted_count == 2  # adapter vẫn produce records
    assert receipt2.inserted_count == 0  # nhưng DB skip hết do PK conflict


def test_different_uplinks_dont_collide() -> None:
    fake = FakeSurveyIngest()
    svc = ChirpstackWebhookService(fake)
    svc.ingest_uplink(_uplink(dedup="A", rx_count=1), _CONTEXT)
    receipt2 = svc.ingest_uplink(_uplink(dedup="B", rx_count=1), _CONTEXT)
    assert receipt2.inserted_count == 1


def test_invalid_uplink_returns_zero_with_reasons() -> None:
    fake = FakeSurveyIngest()
    svc = ChirpstackWebhookService(fake)
    bad = _uplink()
    del bad["txInfo"]
    receipt = svc.ingest_uplink(bad, _CONTEXT)
    assert receipt.accepted_count == 0
    assert receipt.inserted_count == 0
    assert receipt.rejected_count >= 1
    assert "txInfo" in receipt.rejected_reasons[0]
