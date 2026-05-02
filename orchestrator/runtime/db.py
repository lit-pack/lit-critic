"""Legacy compatibility wrapper for database persistence APIs.

This module preserves the historical ``server.db`` import surface while
delegating implementation to the Platform-owned persistence layer.
"""

from orchestrator.persistence import (
    ALL_CATEGORIES,
    CATEGORY_AMBIGUITY_ACCIDENTAL,
    CATEGORY_AMBIGUITY_INTENTIONAL,
    CATEGORY_BLIND_SPOT,
    CATEGORY_PREFERENCE,
    CATEGORY_RESOLUTION,
    LearningStore,
    SCHEMA_VERSION,
    get_connection,
    get_db_path,
    init_db,
)
from orchestrator.persistence.finding_store import FindingStore
from orchestrator.persistence.session_store import SessionStore

__all__ = [
    "SCHEMA_VERSION",
    "get_db_path",
    "get_connection",
    "init_db",
    "SessionStore",
    "FindingStore",
    "LearningStore",
    "CATEGORY_PREFERENCE",
    "CATEGORY_BLIND_SPOT",
    "CATEGORY_RESOLUTION",
    "CATEGORY_AMBIGUITY_INTENTIONAL",
    "CATEGORY_AMBIGUITY_ACCIDENTAL",
    "ALL_CATEGORIES",
]
