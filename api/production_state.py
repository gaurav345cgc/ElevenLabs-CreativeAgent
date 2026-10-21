"""Persist First-10 production checklist state (local file or S3 on Lambda)."""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any

logger = logging.getLogger("creative_agent.api")

_API_DIR = pathlib.Path(__file__).parent
_DEFAULT_STATE_PATH = _API_DIR / "data" / "first10_production_state.json"
_S3_OBJECT_KEY = "ops/first10_production_state.json"
_TMP_STATE_PATH = pathlib.Path("/tmp/first10_production_state.json")


def _tts_bucket() -> str | None:
    value = os.environ.get("CREATIVE_AGENT_TTS_AUDIO_BUCKET", "").strip()
    return value or None


def _use_s3() -> bool:
    return bool(_tts_bucket()) and bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def load_production_state() -> dict[str, Any]:
    if _use_s3():
        try:
            import boto3
            from botocore.exceptions import ClientError

            client = boto3.client("s3")
            response = client.get_object(Bucket=_tts_bucket(), Key=_S3_OBJECT_KEY)
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"NoSuchKey", "404", "NotFound"}:
                logger.warning("production state S3 read failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("production state S3 read failed: %s", exc)

    if _TMP_STATE_PATH.is_file():
        return json.loads(_TMP_STATE_PATH.read_text(encoding="utf-8"))
    return json.loads(_DEFAULT_STATE_PATH.read_text(encoding="utf-8"))


def save_production_state(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if _use_s3():
        import boto3

        client = boto3.client("s3")
        client.put_object(
            Bucket=_tts_bucket(),
            Key=_S3_OBJECT_KEY,
            Body=text.encode("utf-8"),
            ContentType="application/json",
        )
        return payload

    # Local uvicorn / non-Lambda: write next to the package (or /tmp fallback).
    try:
        _DEFAULT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DEFAULT_STATE_PATH.write_text(text, encoding="utf-8")
        return payload
    except OSError:
        _TMP_STATE_PATH.write_text(text, encoding="utf-8")
        return payload
