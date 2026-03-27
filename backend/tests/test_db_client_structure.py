from __future__ import annotations

from db.admin_repository import AdminRepositoryMixin
from db.base import BaseDatabaseClient
from db.client import DatabaseClient
from db.thread_repository import ThreadRepositoryMixin
from db.user_repository import UserRepositoryMixin


def test_database_client_uses_domain_mixins() -> None:
    assert issubclass(DatabaseClient, BaseDatabaseClient)
    assert issubclass(DatabaseClient, UserRepositoryMixin)
    assert issubclass(DatabaseClient, ThreadRepositoryMixin)
    assert issubclass(DatabaseClient, AdminRepositoryMixin)


def test_database_client_keeps_expected_public_methods() -> None:
    expected = [
        "fetch_user",
        "ensure_user_from_request",
        "create_thread",
        "fetch_posts",
        "create_report",
        "fetch_thread_votes",
        "admin_list_threads",
        "admin_update_agent",
        "load_debate_state",
        "save_debate_state",
    ]
    missing = [name for name in expected if not hasattr(DatabaseClient, name)]
    assert missing == []
