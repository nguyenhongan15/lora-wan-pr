"""Alembic environment.

KHÔNG import application models ở đây — DDL độc lập với SQLAlchemy ORM.
Chúng ta dùng raw SQL trong các revision để giữ kiểm soát tuyệt đối với
PostGIS / TimescaleDB / generated columns / extensions.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Load repo-root .env nếu có — alembic CLI từ shell thường (PowerShell/bash)
# không auto-inject env. api-service/docker-compose tự load qua Pydantic /
# compose `env_file:`, alembic standalone thì phải tự lo.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Cho phép override qua env (12-Factor F3).
db_url = os.environ.get("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
