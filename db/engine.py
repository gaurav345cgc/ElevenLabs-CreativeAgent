"""Database engine factory."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from db.secrets import resolve_database_url

DEFAULT_DATABASE_URL = "postgresql://creative_agent:creative_agent@localhost:5432/creative_agent"


def get_database_url() -> str:
    return resolve_database_url() or DEFAULT_DATABASE_URL


def create_db_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    url = database_url or get_database_url()
    # Fail fast in Lambda/VPC networking misconfigurations (default can hang for minutes).
    connect_args: dict[str, object] = {}
    if url.startswith("postgresql://"):
        connect_args["connect_timeout"] = int(os.environ.get("CREATIVE_AGENT_DB_CONNECT_TIMEOUT", "8"))
    return create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        echo=echo,
        connect_args=connect_args,
    )
