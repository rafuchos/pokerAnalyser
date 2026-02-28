"""Tests for database layer."""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import HandData, TournamentSummaryData


class TestSchema(unittest.TestCase):
    """Test database schema initialization."""

    def test_init_db_creates_tables(self):
        """Test that init_db creates all required tables."""
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t['name'] for t in tables]

        self.assertIn('hands', table_names)
        self.assertIn('hand_actions', table_names)
        self.assertIn('sessions', table_names)
        self.assertIn('tournaments', table_names)
        self.assertIn('tournament_summaries', table_names)
        self.assertIn('imported_files', table_names)
        conn.close()

    def test_init_db_idempotent(self):
        """Test that init_db can be called multiple times."""
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        init_db(conn)  # Should not raise
        conn.close()


class TestRepository(unittest.TestCase):
    """Test repository CRUD operations."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_insert_hand(self):
        """Test inserting a hand."""
        hand = HandData(
            hand_id='TEST001',
            platform='GGPoker',
            game_type='cash',
            date=datetime(2026, 1, 15, 20, 30, 0),
            blinds_sb=0.25,
            blinds_bb=0.50,
            hero_cards='Ah Kd',
            hero_position=None,
            invested=1.00,
            won=1.90,
            net=0.90,
            rake=0.0,
            table_name='TestTable',
            num_players=6,
        )
        result = self.repo.insert_hand(hand)
        self.assertTrue(result)

        # Duplicate should return False
        result = self.repo.insert_hand(hand)
        self.assertFalse(result)

    def test_insert_hands_batch(self):
        """Test batch insert."""
        hands = [
            HandData(hand_id=f'BATCH{i}', platform='GGPoker', game_type='cash',
                     date=datetime(2026, 1, 15, 20, i, 0), blinds_sb=0.25,
                     blinds_bb=0.50, hero_cards=None, hero_position=None,
                     invested=1.0, won=0.0, net=-1.0, rake=0.0,
                     table_name='T', num_players=6)
            for i in range(5)
        ]
        count = self.repo.insert_hands_batch(hands)
        self.assertEqual(count, 5)
        self.assertEqual(self.repo.get_hands_count(), 5)

    def test_file_import_tracking(self):
        """Test imported file tracking."""
        self.assertFalse(self.repo.is_file_imported('test.txt', 'hash123'))

        self.repo.mark_file_imported('test.txt', 'hash123', 10)
        self.assertTrue(self.repo.is_file_imported('test.txt', 'hash123'))
        self.assertFalse(self.repo.is_file_imported('test.txt', 'differenthash'))

    def test_insert_tournament(self):
        """Test tournament insertion."""
        t = {
            'tournament_id': 'T001',
            'platform': 'GGPoker',
            'name': 'Test Tournament',
            'date': datetime(2026, 1, 15),
            'buy_in': 10.0,
            'rake': 1.0,
            'bounty': 0.0,
            'total_buy_in': 11.0,
            'position': 5,
            'prize': 25.0,
            'bounty_won': 0.0,
            'total_players': 100,
            'entries': 1,
            'is_bounty': False,
            'is_satellite': False,
        }
        result = self.repo.insert_tournament(t)
        self.assertTrue(result)
        self.assertEqual(self.repo.get_tournaments_count(), 1)

    def test_get_cash_daily_stats(self):
        """Test aggregated daily cash stats query."""
        hands = [
            HandData(hand_id=f'DAY{i}', platform='GGPoker', game_type='cash',
                     date=datetime(2026, 1, 15, 20, i, 0), blinds_sb=0.25,
                     blinds_bb=0.50, hero_cards=None, hero_position=None,
                     invested=1.0, won=2.0 if i % 2 == 0 else 0.0,
                     net=1.0 if i % 2 == 0 else -1.0,
                     rake=0.0, table_name='T', num_players=6)
            for i in range(10)
        ]
        self.repo.insert_hands_batch(hands)

        daily = self.repo.get_cash_daily_stats('2026')
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]['hands'], 10)

    def test_insert_session(self):
        """Test session insertion."""
        session = {
            'platform': 'GGPoker',
            'start_time': datetime(2026, 1, 15, 20, 0, 0),
            'end_time': datetime(2026, 1, 15, 22, 0, 0),
            'buy_in': 50.0,
            'cash_out': 75.0,
            'profit': 25.0,
            'hands_count': 100,
            'min_stack': 30.0,
        }
        sid = self.repo.insert_session(session)
        self.assertIsNotNone(sid)
        self.assertGreater(sid, 0)


if __name__ == '__main__':
    unittest.main()
