"""Tests for the import pipeline."""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from src.db.schema import init_db
from src.db.repository import Repository
from src.importer import _file_hash, Importer


class TestFileHash(unittest.TestCase):
    """Test file hashing."""

    def test_hash_consistency(self):
        """Test that same content produces same hash."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("test content")
            path = f.name

        try:
            h1 = _file_hash(path)
            h2 = _file_hash(path)
            self.assertEqual(h1, h2)
            self.assertEqual(len(h1), 64)  # SHA-256 hex length
        finally:
            os.unlink(path)

    def test_different_content_different_hash(self):
        """Test that different content produces different hashes."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("content A")
            path_a = f.name

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("content B")
            path_b = f.name

        try:
            self.assertNotEqual(_file_hash(path_a), _file_hash(path_b))
        finally:
            os.unlink(path_a)
            os.unlink(path_b)


class TestImporterDeduplication(unittest.TestCase):
    """Test the import pipeline deduplication logic."""

    def test_skip_already_imported(self):
        """Test that already imported files are skipped."""
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        # Mark a file as imported
        repo.mark_file_imported('/path/to/file.txt', 'abc123', 10)
        self.assertTrue(repo.is_file_imported('/path/to/file.txt', 'abc123'))

        # Changed file (different hash) should not be considered imported
        self.assertFalse(repo.is_file_imported('/path/to/file.txt', 'xyz789'))

        conn.close()


if __name__ == '__main__':
    unittest.main()
