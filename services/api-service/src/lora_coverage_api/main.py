"""Entrypoint cho `uvicorn lora_coverage_api.main:app`."""

from __future__ import annotations

from .edge.app import create_app

app = create_app()
