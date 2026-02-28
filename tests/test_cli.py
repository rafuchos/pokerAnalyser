"""Tests for CLI entry point."""

import subprocess
import sys
import unittest


class TestCLI(unittest.TestCase):
    """Test CLI commands."""

    def test_help(self):
        """Test that --help works."""
        result = subprocess.run(
            [sys.executable, 'main.py', '--help'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('import', result.stdout)
        self.assertIn('report', result.stdout)
        self.assertIn('stats', result.stdout)

    def test_import_help(self):
        """Test that import --help works."""
        result = subprocess.run(
            [sys.executable, 'main.py', 'import', '--help'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('--force', result.stdout)
        self.assertIn('--source', result.stdout)

    def test_report_help(self):
        """Test that report --help works."""
        result = subprocess.run(
            [sys.executable, 'main.py', 'report', '--help'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('--type', result.stdout)

    def test_stats_help(self):
        """Test that stats --help works."""
        result = subprocess.run(
            [sys.executable, 'main.py', 'stats', '--help'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('--type', result.stdout)
        self.assertIn('--days', result.stdout)

    def test_no_command_shows_help(self):
        """Test that running without command shows help."""
        result = subprocess.run(
            [sys.executable, 'main.py'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('import', result.stdout)

    def test_stats_with_empty_db(self):
        """Test stats command with a fresh database."""
        result = subprocess.run(
            [sys.executable, 'main.py', '--db', '/tmp/test_empty_poker.db', 'stats'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('POKER ANALYZER', result.stdout)


if __name__ == '__main__':
    unittest.main()
