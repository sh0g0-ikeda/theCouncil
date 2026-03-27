from __future__ import annotations

import os

from db.admin_repository import AdminRepositoryMixin
from db.base import BaseDatabaseClient
from db.thread_repository import ThreadRepositoryMixin
from db.user_repository import UserRepositoryMixin


class DatabaseClient(
    BaseDatabaseClient,
    UserRepositoryMixin,
    ThreadRepositoryMixin,
    AdminRepositoryMixin,
):
    """Facade kept for backwards compatibility while repositories are split by domain."""


_db: DatabaseClient | None = None


def get_db() -> DatabaseClient:
    global _db
    if _db is None:
        dsn = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/the_council")
        _db = DatabaseClient(dsn=dsn)
    return _db
