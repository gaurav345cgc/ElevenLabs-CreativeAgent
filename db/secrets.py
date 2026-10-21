"""Load database credentials from AWS Secrets Manager for Lambda deployments."""

from __future__ import annotations

import json
import os
from functools import lru_cache


class DatabaseConfigError(RuntimeError):
    """Raised when database credentials cannot be resolved."""


@lru_cache(maxsize=1)
def resolve_database_url() -> str | None:
    """Return SQLAlchemy URL from env or Secrets Manager."""
    direct = os.environ.get("CREATIVE_AGENT_DATABASE_URL", "").strip()
    if direct:
        return direct

    secret_arn = os.environ.get("CREATIVE_AGENT_DB_SECRET_ARN", "").strip()
    if not secret_arn:
        return None
    return _load_database_url_from_secrets_manager(secret_arn)


def _load_database_url_from_secrets_manager(secret_arn: str) -> str:
    import boto3

    region = os.environ.get("CREATIVE_AGENT_AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_arn)
    payload = json.loads(response["SecretString"])

    database_url = payload.get("database_url")
    if database_url:
        return str(database_url).strip()

    username = payload.get("username")
    password = payload.get("password")
    host = payload.get("host")
    port = payload.get("port", 5432)
    dbname = payload.get("dbname") or payload.get("database")
    if not all([username, password, host, dbname]):
        raise DatabaseConfigError(
            f"Secret {secret_arn!r} is missing database_url or connection fields"
        )
    return f"postgresql://{username}:{password}@{host}:{port}/{dbname}?sslmode=require"
