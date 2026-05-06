"""Test parsing CHIRPSTACK_WEBHOOK_TOKENS env → token_map."""

from __future__ import annotations

from uuid import UUID

import pytest

from lora_coverage_api.config import Settings


def test_empty_returns_empty_map() -> None:
    s = Settings(chirpstack_webhook_tokens="")
    assert s.chirpstack_webhook_token_map == {}


def test_single_pair() -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    s = Settings(chirpstack_webhook_tokens=f"abc:{uid}")
    assert s.chirpstack_webhook_token_map == {"abc": UUID(uid)}


def test_multiple_pairs_with_whitespace() -> None:
    uid1 = "11111111-1111-1111-1111-111111111111"
    uid2 = "22222222-2222-2222-2222-222222222222"
    s = Settings(chirpstack_webhook_tokens=f" tok1:{uid1} , tok2:{uid2} ")
    m = s.chirpstack_webhook_token_map
    assert m == {"tok1": UUID(uid1), "tok2": UUID(uid2)}


@pytest.mark.parametrize(
    "raw",
    [
        "no-colon-here",  # missing :
        ":11111111-1111-1111-1111-111111111111",  # empty token
        "tok:not-a-uuid",  # bad uuid
    ],
)
def test_silently_skips_malformed(raw: str) -> None:
    s = Settings(chirpstack_webhook_tokens=raw)
    assert s.chirpstack_webhook_token_map == {}
