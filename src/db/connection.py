"""SQLite connection management."""

import sqlite3
from pathlib import Path

from src.db.schema import init_db

_connection = None
_db_path = None


def get_connection(db_path: str = 'poker.db') -> sqlite3.Connection:
    """Get or create a SQLite connection (singleton per path)."""
    global _connection, _db_path

    if _connection is not None and _db_path == db_path:
        return _connection

    # Close existing connection if path changed
    if _connection is not None:
        _connection.close()

    _db_path = db_path
    _connection = sqlite3.connect(db_path)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")

    # Initialize schema
    init_db(_connection)

    return _connection


def close_connection():
    """Close the current connection."""
    global _connection, _db_path
    if _connection is not None:
        _connection.close()
        _connection = None
        _db_path = None
