"""
services/mqtt_listener.py — Background worker subscribe ChirpStack MQTT.

Đường ingest realtime song song với HTTP webhook. Khi broker đẩy uplink,
listener decode JSON và gọi persist_chirpstack_uplink (cùng logic webhook).

Pattern: asyncio task spawn từ FastAPI lifespan, reconnect-on-error với
backoff. Tương tự services/webhook_retry.py.
"""

from __future__ import annotations

import asyncio
import json
import logging

import aiomqtt

from config import get_settings
from database import AsyncSessionLocal
from services.uplink_ingest import InvalidUplinkError, persist_chirpstack_uplink

logger = logging.getLogger(__name__)

RECONNECT_BACKOFF_SEC = 5


async def _handle_message(payload: bytes, topic: str) -> None:
    """Decode 1 MQTT message và persist. Không raise — chỉ log."""
    try:
        body = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("mqtt_invalid_json",
                       extra={"topic": topic, "reason": str(e)})
        return

    try:
        async with AsyncSessionLocal() as db:
            result = await persist_chirpstack_uplink(db, body, data_source="mqtt")
            await db.commit()
        logger.info("mqtt_uplink_ingested", extra={
            "topic":  topic,
            "devEui": result["devEui"],
            "saved":  result["saved"],
            "dedup":  result["deduplicated"],
        })
    except InvalidUplinkError as e:
        logger.warning("mqtt_incomplete_payload",
                       extra={"topic": topic, "reason": str(e)})
    except Exception as e:
        # Không để 1 message lỗi làm chết cả listener
        logger.exception("mqtt_persist_failed",
                         extra={"topic": topic, "reason": str(e)})


async def _listener_loop() -> None:
    """Loop chính — reconnect khi mất kết nối."""
    settings = get_settings()

    client_kwargs: dict = {
        "hostname":  settings.mqtt_broker_host,
        "port":      settings.mqtt_broker_port,
        "identifier": settings.mqtt_client_id,
    }
    if settings.mqtt_username:
        client_kwargs["username"] = settings.mqtt_username
        client_kwargs["password"] = settings.mqtt_password
    if settings.mqtt_tls:
        client_kwargs["tls_params"] = aiomqtt.TLSParameters()

    while True:
        try:
            async with aiomqtt.Client(**client_kwargs) as client:
                logger.info("mqtt_connected", extra={
                    "host":  settings.mqtt_broker_host,
                    "port":  settings.mqtt_broker_port,
                    "topic": settings.mqtt_topic,
                })
                await client.subscribe(settings.mqtt_topic)
                async for message in client.messages:
                    await _handle_message(message.payload, str(message.topic))
        except asyncio.CancelledError:
            logger.info("mqtt_listener_cancelled")
            raise
        except aiomqtt.MqttError as e:
            logger.warning("mqtt_connection_lost", extra={
                "reason":      str(e),
                "retry_in_s":  RECONNECT_BACKOFF_SEC,
            })
            await asyncio.sleep(RECONNECT_BACKOFF_SEC)
        except Exception as e:
            logger.exception("mqtt_listener_error", extra={"reason": str(e)})
            await asyncio.sleep(RECONNECT_BACKOFF_SEC)


def start_mqtt_listener() -> asyncio.Task:
    """Spawn task. Caller giữ reference để cancel khi shutdown."""
    return asyncio.create_task(_listener_loop(), name="mqtt-listener")
