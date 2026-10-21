"""AWS Lambda entrypoint for the intake API (API Gateway + Mangum)."""

from __future__ import annotations

from typing import Any

from mangum import Mangum

from api.main import create_app

_handler = Mangum(create_app(), lifespan="off")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return _handler(event, context)
