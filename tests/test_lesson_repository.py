"""Tests for lesson tracker: schema, seed data, repository methods, and CLI."""

import sqlite3
import subprocess
import sys
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.db.seed_lessons import REGLIFE_LESSONS, seed_lessons
from src.parsers.base import HandData


def _make_hand(hand_id, date='2026-01-15T20:00:00'):
    """Helper to create a HandData for testing."""
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='cash',
        date=date,
        blinds_sb=0.25,
        blinds_bb=0.50,
        hero_cards='Ah Kd',
        hero_position='BTN',
        invested=1.0,
        won=2.0,
        net=1.0,
        rake=0.0,
        table_name='TestTable',
        num_players=6,
    )


class TestLessonSchema(unittest.TestCase):
    """Test that lessons and hand_lessons tables are created."""

    def test_init_db_creates_lesson_tables(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        tables = {r['name'] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        self.assertIn('lessons', tables)
        self.assertIn('hand_lessons', tables)
        conn.close()

    def test_lessons_table_columns(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(lessons)").fetchall()}
        expected = {'lesson_id', 'title', 'category', 'subcategory',
                    'pdf_filename', 'description', 'sort_order'}
        self.assertEqual(expected, cols)
        conn.close()

    def test_hand_lessons_table_columns(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(hand_lessons)").fetchall()}
        expected = {'id', 'hand_id', 'lesson_id', 'street',
                    'executed_correctly', 'confidence', 'notes', 'created_at'}
        self.assertEqual(expected, cols)
        conn.close()

    def test_init_db_idempotent_with_lessons(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        init_db(conn)  # Should not raise
        count = conn.execute("SELECT COUNT(*) as cnt FROM lessons").fetchone()['cnt']
        self.assertEqual(count, 23)
        conn.close()


class TestSeedLessons(unittest.TestCase):
    """Test lesson seed data."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_seed_data_has_23_lessons(self):
        self.assertEqual(len(REGLIFE_LESSONS), 23)

    def test_seed_inserts_23_lessons(self):
        # init_db already seeds, so clear and re-seed manually
        self.conn.execute("DELETE FROM lessons")
        self.conn.commit()
        count = seed_lessons(self.conn)
        self.assertEqual(count, 23)
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM lessons").fetchone()
        self.assertEqual(row['cnt'], 23)

    def test_seed_is_idempotent(self):
        # Already seeded by init_db
        count = seed_lessons(self.conn)
        self.assertEqual(count, 0)

    def test_seed_categories(self):
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM lessons ORDER BY category"
        ).fetchall()
        categories = [r['category'] for r in rows]
        self.assertIn('Preflop', categories)
        self.assertIn('Postflop', categories)
        self.assertIn('Torneios', categories)

    def test_seed_subcategories(self):
        rows = self.conn.execute(
            "SELECT DISTINCT subcategory FROM lessons ORDER BY subcategory"
        ).fetchall()
        subcategories = [r['subcategory'] for r in rows]
        self.assertIn('Ranges', subcategories)
        self.assertIn('Blinds', subcategories)
        self.assertIn('C-Bet', subcategories)
        self.assertIn('Fundamentos', subcategories)
        self.assertIn('Defesa', subcategories)
        self.assertIn('Avançado', subcategories)
        self.assertIn('Bounty', subcategories)

    def test_seed_sort_order_unique(self):
        rows = self.conn.execute("SELECT sort_order FROM lessons").fetchall()
        orders = [r['sort_order'] for r in rows]
        self.assertEqual(len(orders), len(set(orders)), "sort_order must be unique")

    def test_seed_all_have_pdf_filename(self):
        rows = self.conn.execute(
            "SELECT title, pdf_filename FROM lessons WHERE pdf_filename IS NULL"
        ).fetchall()
        self.assertEqual(len(rows), 0, "All lessons must have a pdf_filename")

    def test_seed_all_have_description(self):
        rows = self.conn.execute(
            "SELECT title FROM lessons WHERE description IS NULL OR description = ''"
        ).fetchall()
        self.assertEqual(len(rows), 0, "All lessons must have a description")

    def test_preflop_lesson_count(self):
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM lessons WHERE category = 'Preflop'"
        ).fetchone()
        self.assertEqual(row['cnt'], 9)

    def test_postflop_lesson_count(self):
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM lessons WHERE category = 'Postflop'"
        ).fetchone()
        self.assertEqual(row['cnt'], 12)

    def test_torneios_lesson_count(self):
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM lessons WHERE category = 'Torneios'"
        ).fetchone()
        self.assertEqual(row['cnt'], 2)


class TestLessonRepository(unittest.TestCase):
    """Test Repository lesson methods."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_get_lessons(self):
        lessons = self.repo.get_lessons()
        self.assertEqual(len(lessons), 23)
        self.assertEqual(lessons[0]['sort_order'], 1)
        self.assertEqual(lessons[-1]['sort_order'], 23)

    def test_get_lesson_by_id(self):
        lesson = self.repo.get_lesson_by_id(1)
        self.assertIsNotNone(lesson)
        self.assertEqual(lesson['title'], 'Ranges de RFI em cEV')

    def test_get_lesson_by_id_not_found(self):
        lesson = self.repo.get_lesson_by_id(999)
        self.assertIsNone(lesson)

    def test_get_lessons_with_hand_count_no_links(self):
        lessons = self.repo.get_lessons_with_hand_count()
        self.assertEqual(len(lessons), 23)
        for lesson in lessons:
            self.assertEqual(lesson['hand_count'], 0)

    def test_link_hand_to_lesson(self):
        hand = _make_hand('LINK001')
        self.repo.insert_hand(hand)
        row_id = self.repo.link_hand_to_lesson('LINK001', 1, notes='Bom exemplo')
        self.assertIsNotNone(row_id)
        self.assertGreater(row_id, 0)

    def test_link_hand_to_lesson_without_notes(self):
        hand = _make_hand('LINK002')
        self.repo.insert_hand(hand)
        row_id = self.repo.link_hand_to_lesson('LINK002', 1)
        self.assertGreater(row_id, 0)

    def test_get_lesson_hand_count(self):
        hand1 = _make_hand('COUNT001')
        hand2 = _make_hand('COUNT002')
        self.repo.insert_hand(hand1)
        self.repo.insert_hand(hand2)
        self.assertEqual(self.repo.get_lesson_hand_count(1), 0)

        self.repo.link_hand_to_lesson('COUNT001', 1)
        self.assertEqual(self.repo.get_lesson_hand_count(1), 1)

        self.repo.link_hand_to_lesson('COUNT002', 1)
        self.assertEqual(self.repo.get_lesson_hand_count(1), 2)

    def test_get_lessons_with_hand_count_with_links(self):
        hand = _make_hand('WC001')
        self.repo.insert_hand(hand)
        self.repo.link_hand_to_lesson('WC001', 1)
        self.repo.link_hand_to_lesson('WC001', 2)

        lessons = self.repo.get_lessons_with_hand_count()
        lesson1 = next(l for l in lessons if l['lesson_id'] == 1)
        lesson2 = next(l for l in lessons if l['lesson_id'] == 2)
        lesson3 = next(l for l in lessons if l['lesson_id'] == 3)
        self.assertEqual(lesson1['hand_count'], 1)
        self.assertEqual(lesson2['hand_count'], 1)
        self.assertEqual(lesson3['hand_count'], 0)

    def test_unlink_hand_from_lesson(self):
        hand = _make_hand('UNLINK001')
        self.repo.insert_hand(hand)
        self.repo.link_hand_to_lesson('UNLINK001', 1)
        self.assertEqual(self.repo.get_lesson_hand_count(1), 1)

        result = self.repo.unlink_hand_from_lesson('UNLINK001', 1)
        self.assertTrue(result)
        self.assertEqual(self.repo.get_lesson_hand_count(1), 0)

    def test_unlink_nonexistent(self):
        result = self.repo.unlink_hand_from_lesson('NOHAND', 1)
        self.assertFalse(result)

    def test_get_hands_for_lesson(self):
        hand1 = _make_hand('HL001')
        hand2 = _make_hand('HL002')
        self.repo.insert_hand(hand1)
        self.repo.insert_hand(hand2)
        self.repo.link_hand_to_lesson('HL001', 1, notes='nota 1')
        self.repo.link_hand_to_lesson('HL002', 1, notes='nota 2')

        hands = self.repo.get_hands_for_lesson(1)
        self.assertEqual(len(hands), 2)
        self.assertEqual(hands[0]['hand_id'], 'HL001')
        self.assertEqual(hands[0]['lesson_notes'], 'nota 1')
        self.assertIn('linked_at', hands[0])

    def test_get_hands_for_lesson_empty(self):
        hands = self.repo.get_hands_for_lesson(1)
        self.assertEqual(len(hands), 0)

    def test_get_lessons_for_hand(self):
        hand = _make_hand('LH001')
        self.repo.insert_hand(hand)
        self.repo.link_hand_to_lesson('LH001', 1, notes='A')
        self.repo.link_hand_to_lesson('LH001', 5, notes='B')

        lessons = self.repo.get_lessons_for_hand('LH001')
        self.assertEqual(len(lessons), 2)
        self.assertEqual(lessons[0]['lesson_id'], 1)
        self.assertEqual(lessons[1]['lesson_id'], 5)
        self.assertEqual(lessons[0]['lesson_notes'], 'A')

    def test_get_lessons_for_hand_empty(self):
        lessons = self.repo.get_lessons_for_hand('NOHAND')
        self.assertEqual(len(lessons), 0)

    def test_seed_lessons_if_empty(self):
        # Already seeded by init_db
        count = self.repo.seed_lessons_if_empty()
        self.assertEqual(count, 0)

    def test_seed_lessons_if_empty_after_clear(self):
        self.conn.execute("DELETE FROM lessons")
        self.conn.commit()
        count = self.repo.seed_lessons_if_empty()
        self.assertEqual(count, 23)

    def test_multiple_hands_same_lesson(self):
        for i in range(5):
            hand = _make_hand(f'MULTI{i:03d}')
            self.repo.insert_hand(hand)
            self.repo.link_hand_to_lesson(f'MULTI{i:03d}', 3)

        self.assertEqual(self.repo.get_lesson_hand_count(3), 5)
        hands = self.repo.get_hands_for_lesson(3)
        self.assertEqual(len(hands), 5)

    def test_one_hand_multiple_lessons(self):
        hand = _make_hand('ONEHAND')
        self.repo.insert_hand(hand)
        self.repo.link_hand_to_lesson('ONEHAND', 1)
        self.repo.link_hand_to_lesson('ONEHAND', 10)
        self.repo.link_hand_to_lesson('ONEHAND', 23)

        lessons = self.repo.get_lessons_for_hand('ONEHAND')
        self.assertEqual(len(lessons), 3)
        ids = [l['lesson_id'] for l in lessons]
        self.assertIn(1, ids)
        self.assertIn(10, ids)
        self.assertIn(23, ids)


class TestLessonsMigration(unittest.TestCase):
    """Test that migration creates lesson tables for existing DBs."""

    def test_migration_creates_tables(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        # Simulate old DB without lesson tables
        conn.executescript("""
            CREATE TABLE hands (
                hand_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                game_type TEXT NOT NULL,
                date TEXT NOT NULL,
                blinds_sb REAL,
                blinds_bb REAL,
                hero_cards TEXT,
                hero_position TEXT,
                invested REAL DEFAULT 0,
                won REAL DEFAULT 0,
                net REAL DEFAULT 0,
                rake REAL DEFAULT 0,
                table_name TEXT,
                num_players INTEGER,
                board_flop TEXT,
                board_turn TEXT,
                board_river TEXT,
                pot_total REAL,
                opponent_cards TEXT,
                has_allin INTEGER DEFAULT 0,
                allin_street TEXT,
                tournament_id TEXT,
                hero_stack REAL
            );
            CREATE TABLE hand_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hand_id TEXT NOT NULL,
                street TEXT NOT NULL,
                player TEXT NOT NULL,
                action_type TEXT NOT NULL,
                amount REAL DEFAULT 0,
                is_hero INTEGER DEFAULT 0,
                sequence_order INTEGER DEFAULT 0,
                position TEXT,
                is_voluntary INTEGER DEFAULT 0
            );
            CREATE TABLE sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT,
                date TEXT NOT NULL,
                buy_in REAL DEFAULT 0,
                cash_out REAL DEFAULT 0,
                profit REAL DEFAULT 0,
                hands_count INTEGER DEFAULT 0,
                min_stack REAL DEFAULT 0,
                start_time TEXT,
                end_time TEXT
            );
            CREATE TABLE tournaments (
                tournament_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                name TEXT,
                date TEXT,
                buy_in REAL DEFAULT 0,
                rake REAL DEFAULT 0,
                bounty REAL DEFAULT 0,
                total_buy_in REAL DEFAULT 0,
                position INTEGER,
                prize REAL DEFAULT 0,
                bounty_won REAL DEFAULT 0,
                total_players INTEGER DEFAULT 0,
                entries INTEGER DEFAULT 1,
                is_bounty INTEGER DEFAULT 0,
                is_satellite INTEGER DEFAULT 0
            );
            CREATE TABLE tournament_summaries (
                tournament_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                name TEXT,
                date TEXT,
                buy_in REAL DEFAULT 0,
                rake REAL DEFAULT 0,
                bounty REAL DEFAULT 0,
                total_buy_in REAL DEFAULT 0,
                position INTEGER,
                prize REAL DEFAULT 0,
                bounty_won REAL DEFAULT 0,
                total_players INTEGER DEFAULT 0,
                entries INTEGER DEFAULT 1,
                is_bounty INTEGER DEFAULT 0,
                is_satellite INTEGER DEFAULT 0
            );
            CREATE TABLE imported_files (
                file_path TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                records_count INTEGER DEFAULT 0
            );
        """)
        conn.commit()

        # Now run init_db which should create lessons tables via migration
        init_db(conn)

        tables = {r['name'] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        self.assertIn('lessons', tables)
        self.assertIn('hand_lessons', tables)

        # Should also seed
        count = conn.execute("SELECT COUNT(*) as cnt FROM lessons").fetchone()['cnt']
        self.assertEqual(count, 23)
        conn.close()


class TestLessonsCLI(unittest.TestCase):
    """Test CLI lessons command."""

    def test_lessons_help(self):
        result = subprocess.run(
            [sys.executable, 'main.py', 'lessons', '--help'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)

    def test_lessons_command_runs(self):
        result = subprocess.run(
            [sys.executable, 'main.py', '--db', '/tmp/test_lessons_cli.db', 'lessons'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Lesson Tracker', result.stdout)
        self.assertIn('Preflop', result.stdout)
        self.assertIn('Postflop', result.stdout)
        self.assertIn('Torneios', result.stdout)
        self.assertIn('23 aulas', result.stdout)

    def test_lessons_shows_all_lessons(self):
        result = subprocess.run(
            [sys.executable, 'main.py', '--db', '/tmp/test_lessons_cli2.db', 'lessons'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Ranges de RFI', result.stdout)
        self.assertIn('C-Bet', result.stdout)
        self.assertIn('Bounty', result.stdout)

    def test_lessons_appears_in_help(self):
        result = subprocess.run(
            [sys.executable, 'main.py', '--help'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('lessons', result.stdout)


if __name__ == '__main__':
    unittest.main()
