"""Unit tests cho Result[T, E]."""

from __future__ import annotations

from lora_coverage_api.domain.result import Err, Ok


def test_ok_is_ok() -> None:
    r: Ok[int] = Ok(42)
    assert r.is_ok and not r.is_err
    assert r.value == 42


def test_err_is_err() -> None:
    r: Err[str] = Err("nope")
    assert r.is_err and not r.is_ok
    assert r.error == "nope"


def test_isinstance_discriminates() -> None:
    def f(x: int) -> Ok[int] | Err[str]:
        return Ok(x) if x > 0 else Err("non-positive")

    a = f(1)
    b = f(-1)
    assert isinstance(a, Ok)
    assert isinstance(b, Err)
