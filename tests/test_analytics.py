"""Tests for US-026: Analytics DB + analyze command."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.db.analytics_schema import init_analytics_db, ANALYTICS_SCHEMA_SQL
from src.db.analytics_repository import AnalyticsRepository
from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import HandData, ActionData


# ── Helpers ────────────────────────────────────────────────────────


def _make_hand(hand_id, game_type='cash', date='2026-01-15',
               hero_position='CO', tournament_id=None, **kwargs):
    """Create a HandData with sensible defaults."""
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type=game_type,
        date=datetime.fromisoformat(
            f'{date}T20:00:00') if 'T' not in date else datetime.fromisoformat(date),
        blinds_sb=kwargs.get('blinds_sb', 0.25),
        blinds_bb=kwargs.get('blinds_bb', 0.50),
        hero_cards=kwargs.get('hero_cards', 'Ah Kd'),
        hero_position=hero_position,
        invested=kwargs.get('invested', 1.0),
        won=kwargs.get('won', 0.0),
        net=kwargs.get('net', -1.0),
        rake=0.0,
        table_name='T',
        num_players=kwargs.get('num_players', 6),
        tournament_id=tournament_id,
        hero_stack=kwargs.get('hero_stack', 100.0),
    )


def _make_action(hand_id, street, player, action_type, seq,
                 position='CO', is_hero=False, amount=0.0):
    """Create an ActionData for testing."""
    return ActionData(
        hand_id=hand_id,
        street=street,
        player=player,
        action_type=action_type,
        amount=amount,
        is_hero=1 if is_hero else 0,
        sequence_order=seq,
        position=position,
        is_voluntary=1 if action_type in ('call', 'raise', 'bet', 'all-in') else 0,
    )


def _setup_poker_db(conn):
    """Set up a poker.db schema and insert sample data."""
    init_db(conn)
    repo = Repository(conn)

    # Insert cash hands
    for i in range(5):
        hand = _make_hand(
            f'CASH{i:03d}', game_type='cash',
            date='2026-01-15', hero_position='CO',
            net=10.0 if i % 2 == 0 else -5.0,
        )
        repo.insert_hand(hand)
        actions = [
            _make_action(f'CASH{i:03d}', 'preflop', 'V1', 'raise', 0,
                         position='UTG', amount=1.5),
            _make_action(f'CASH{i:03d}', 'preflop', 'Hero', 'call', 1,
                         position='CO', is_hero=True, amount=1.5),
        ]
        repo.insert_actions_batch(actions)

    # Insert a session
    conn.execute(
        "INSERT INTO sessions (platform, date, buy_in, cash_out, profit, "
        "hands_count, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('GGPoker', '2026-01-15', 50.0, 65.0, 15.0, 5,
         '2026-01-15T19:00:00', '2026-01-15T21:00:00'),
    )
    conn.commit()
    return repo


def _setup_tournament_db(conn, repo):
    """Add tournament data to existing poker DB."""
    conn.execute(
        "INSERT INTO tournaments (tournament_id, platform, name, date, "
        "buy_in, rake, total_buy_in, position, prize, total_players) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ('T100', 'GGPoker', 'Test Tournament', '2026-01-15',
         10.0, 1.0, 11.0, 5, 25.0, 50),
    )
    for i in range(5):
        hand = _make_hand(
            f'TOURN{i:03d}', game_type='tournament',
            date='2026-01-15T20:00:00', hero_position='BTN',
            tournament_id='T100', blinds_bb=200.0, blinds_sb=100.0,
            net=500.0 if i % 2 == 0 else -200.0,
            hero_stack=5000.0,
        )
        repo.insert_hand(hand)
        actions = [
            _make_action(f'TOURN{i:03d}', 'preflop', 'V1', 'raise', 0,
                         position='UTG', amount=400.0),
            _make_action(f'TOURN{i:03d}', 'preflop', 'Hero', 'call', 1,
                         position='BTN', is_hero=True, amount=400.0),
        ]
        repo.insert_actions_batch(actions)
    conn.commit()


# ══════════════════════════════════════════════════════════════════
# Analytics Schema Tests
# ══════════════════════════════════════════════════════════════════


class TestAnalyticsSchema(unittest.TestCase):
    """Test analytics database schema initialization."""

    def test_init_analytics_db_creates_tables(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t['name'] for t in tables]

        expected = [
            'analytics_meta', 'global_stats', 'session_stats',
            'daily_stats', 'positional_stats', 'stack_depth_stats',
            'leak_analysis', 'tilt_analysis', 'ev_analysis',
            'bet_sizing_stats', 'hand_matrix', 'redline_blueline',
        ]
        for tbl in expected:
            self.assertIn(tbl, table_names, f"Missing table: {tbl}")
        conn.close()

    def test_init_analytics_db_idempotent(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)
        init_analytics_db(conn)  # Should not raise
        conn.close()

    def test_all_tables_have_game_type_column(self):
        """All data tables (except analytics_meta) have game_type."""
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)

        data_tables = [
            'global_stats', 'session_stats', 'daily_stats',
            'positional_stats', 'stack_depth_stats', 'leak_analysis',
            'tilt_analysis', 'ev_analysis', 'bet_sizing_stats',
            'hand_matrix', 'redline_blueline',
        ]
        for tbl in data_tables:
            cols = conn.execute(f"PRAGMA table_info({tbl})").fetchall()
            col_names = [c['name'] for c in cols]
            self.assertIn('game_type', col_names,
                          f"Table {tbl} missing game_type column")
        conn.close()

    def test_analytics_meta_has_key_value(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)

        cols = conn.execute("PRAGMA table_info(analytics_meta)").fetchall()
        col_names = [c['name'] for c in cols]
        self.assertIn('key', col_names)
        self.assertIn('value', col_names)
        self.assertIn('updated_at', col_names)
        conn.close()


# ══════════════════════════════════════════════════════════════════
# Analytics Repository Tests
# ══════════════════════════════════════════════════════════════════


class TestAnalyticsRepository(unittest.TestCase):
    """Test analytics repository CRUD operations."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_analytics_db(self.conn)
        self.repo = AnalyticsRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    # ── Meta ──────────────────────────────────────────────────────

    def test_set_and_get_meta(self):
        self.repo.set_meta('source_hash', 'abc123')
        self.assertEqual(self.repo.get_meta('source_hash'), 'abc123')

    def test_get_meta_returns_none_for_missing(self):
        self.assertIsNone(self.repo.get_meta('nonexistent'))

    def test_set_meta_upserts(self):
        self.repo.set_meta('key1', 'value1')
        self.repo.set_meta('key1', 'value2')
        self.assertEqual(self.repo.get_meta('key1'), 'value2')

    # ── Global Stats ──────────────────────────────────────────────

    def test_insert_and_get_global_stat_with_value(self):
        self.repo.insert_global_stat('cash', 'health_score', stat_value=85.5)
        self.repo.commit()

        stats = self.repo.get_global_stats('cash')
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['stat_name'], 'health_score')
        self.assertAlmostEqual(stats[0]['stat_value'], 85.5)
        self.assertIsNone(stats[0]['stat_json'])

    def test_insert_and_get_global_stat_with_json(self):
        data = {'total_hands': 100, 'total_net': 250.0}
        self.repo.insert_global_stat('cash', 'summary', stat_json=data)
        self.repo.commit()

        stats = self.repo.get_global_stats('cash')
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['stat_json']['total_hands'], 100)

    def test_global_stats_separated_by_game_type(self):
        self.repo.insert_global_stat('cash', 'summary', stat_value=1.0)
        self.repo.insert_global_stat('tournament', 'summary', stat_value=2.0)
        self.repo.commit()

        cash = self.repo.get_global_stats('cash')
        tourn = self.repo.get_global_stats('tournament')
        self.assertEqual(len(cash), 1)
        self.assertEqual(len(tourn), 1)
        self.assertAlmostEqual(cash[0]['stat_value'], 1.0)
        self.assertAlmostEqual(tourn[0]['stat_value'], 2.0)

    # ── Session Stats ─────────────────────────────────────────────

    def test_insert_and_get_session_stat(self):
        data = {'vpip': 25.0, 'pfr': 20.0}
        self.repo.insert_session_stat('cash', '2026-01-15s1', 'session_detail',
                                      stat_json=data)
        self.repo.commit()

        stats = self.repo.get_session_stats('cash')
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['session_key'], '2026-01-15s1')
        self.assertEqual(stats[0]['stat_json']['vpip'], 25.0)

    # ── Daily Stats ───────────────────────────────────────────────

    def test_insert_and_get_daily_stat(self):
        data = {'hands': 50, 'net': 100.0}
        self.repo.insert_daily_stat('cash', '2026-01-15', 'daily_report',
                                    stat_json=data)
        self.repo.commit()

        stats = self.repo.get_daily_stats('cash')
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['day'], '2026-01-15')

    # ── Positional Stats ──────────────────────────────────────────

    def test_insert_and_get_positional_stat(self):
        data = {'vpip': 30.0, 'pfr': 22.0}
        self.repo.insert_positional_stat('cash', 'CO', 'stats', stat_json=data)
        self.repo.commit()

        stats = self.repo.get_positional_stats('cash')
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['position'], 'CO')

    # ── Stack Depth Stats ─────────────────────────────────────────

    def test_insert_and_get_stack_depth_stat(self):
        data = {'vpip': 28.0, 'hands': 40}
        self.repo.insert_stack_depth_stat('cash', 'deep', 'stats',
                                          stat_json=data)
        self.repo.commit()

        stats = self.repo.get_stack_depth_stats('cash')
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['tier'], 'deep')

    # ── Leak Analysis ─────────────────────────────────────────────

    def test_insert_and_get_leak(self):
        self.repo.insert_leak(
            'cash', leak_name='VPIP muito alto', category='preflop',
            stat_name='vpip', current_value=38.0,
            healthy_low=22.0, healthy_high=30.0,
            cost_bb100=1.2, direction='too_high',
            suggestion='Tighten up preflop ranges',
        )
        self.repo.commit()

        leaks = self.repo.get_leak_analysis('cash')
        self.assertEqual(len(leaks), 1)
        self.assertEqual(leaks[0]['leak_name'], 'VPIP muito alto')
        self.assertAlmostEqual(leaks[0]['cost_bb100'], 1.2)

    def test_leak_with_position(self):
        self.repo.insert_leak(
            'cash', leak_name='VPIP UTG alto', category='positional',
            stat_name='vpip', current_value=25.0,
            healthy_low=12.0, healthy_high=18.0,
            cost_bb100=0.8, direction='too_high',
            suggestion='Play tighter from UTG', position='UTG',
        )
        self.repo.commit()

        leaks = self.repo.get_leak_analysis('cash')
        self.assertEqual(leaks[0]['position'], 'UTG')

    # ── Tilt Analysis ─────────────────────────────────────────────

    def test_insert_and_get_tilt_analysis(self):
        data = {'has_tilt': True, 'severity': 'warning', 'cost_bb': 2.5}
        self.repo.insert_tilt_analysis('cash', 'session_tilt', data)
        self.repo.commit()

        results = self.repo.get_tilt_analysis('cash')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['analysis_key'], 'session_tilt')
        self.assertTrue(results[0]['data']['has_tilt'])

    # ── EV Analysis ───────────────────────────────────────────────

    def test_insert_and_get_ev_analysis(self):
        data = {'total_hands': 100, 'ev_net': 50.0}
        self.repo.insert_ev_analysis('cash', 'allin_ev', data)
        self.repo.commit()

        results = self.repo.get_ev_analysis('cash')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['analysis_type'], 'allin_ev')

    # ── Bet Sizing ────────────────────────────────────────────────

    def test_insert_and_get_bet_sizing(self):
        data = {'preflop': {'avg_size': 2.5}}
        self.repo.insert_bet_sizing('cash', 'overall', data)
        self.repo.commit()

        results = self.repo.get_bet_sizing('cash')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['sizing_key'], 'overall')

    # ── Hand Matrix ───────────────────────────────────────────────

    def test_insert_and_get_hand_matrix_entry(self):
        breakdown = {'open_raise': 5, 'call': 2}
        self.repo.insert_hand_matrix_entry(
            'cash', 'CO', 'AKo', dealt=10, played=7,
            total_net=25.0, bb100=5.0, action_breakdown=breakdown,
        )
        self.repo.commit()

        results = self.repo.get_hand_matrix('cash')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['hand_combo'], 'AKo')
        self.assertEqual(results[0]['dealt'], 10)
        self.assertEqual(results[0]['action_breakdown']['open_raise'], 5)

    # ── Red Line / Blue Line ──────────────────────────────────────

    def test_insert_and_get_redline_blueline(self):
        data = {'showdown_net': 100.0, 'non_showdown_net': -30.0}
        self.repo.insert_redline_blueline('cash', 'overall', data)
        self.repo.commit()

        results = self.repo.get_redline_blueline('cash')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['data_key'], 'overall')
        self.assertAlmostEqual(results[0]['data']['showdown_net'], 100.0)

    # ── Clear Game Type ───────────────────────────────────────────

    def test_clear_game_type(self):
        self.repo.insert_global_stat('cash', 's1', stat_value=1.0)
        self.repo.insert_global_stat('tournament', 's2', stat_value=2.0)
        self.repo.insert_leak(
            'cash', 'L1', 'preflop', 'vpip', 30.0, 22.0, 30.0,
            1.0, 'too_high', 'fix',
        )
        self.repo.commit()

        self.repo.clear_game_type('cash')

        cash = self.repo.get_global_stats('cash')
        tourn = self.repo.get_global_stats('tournament')
        leaks = self.repo.get_leak_analysis('cash')

        self.assertEqual(len(cash), 0)
        self.assertEqual(len(tourn), 1)
        self.assertEqual(len(leaks), 0)


# ══════════════════════════════════════════════════════════════════
# Analytics Pipeline Tests
# ══════════════════════════════════════════════════════════════════


class TestAnalyticsPipeline(unittest.TestCase):
    """Test the analytics pipeline orchestration."""

    def setUp(self):
        self.poker_db_fd, self.poker_db_path = tempfile.mkstemp(suffix='.db')
        self.analytics_db_fd, self.analytics_db_path = tempfile.mkstemp(suffix='.db')

        # Set up poker DB with data
        conn = sqlite3.connect(self.poker_db_path)
        conn.row_factory = sqlite3.Row
        _setup_poker_db(conn)
        conn.close()

    def tearDown(self):
        os.close(self.poker_db_fd)
        os.close(self.analytics_db_fd)
        os.unlink(self.poker_db_path)
        os.unlink(self.analytics_db_path)

    def test_run_analysis_creates_analytics_db(self):
        from src.analytics_pipeline import run_analysis

        result = run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='cash',
        )
        self.assertTrue(result['cash_processed'])
        self.assertFalse(result['skipped'])

        # Verify analytics DB has data
        conn = sqlite3.connect(self.analytics_db_path)
        conn.row_factory = sqlite3.Row
        repo = AnalyticsRepository(conn)

        stats = repo.get_global_stats('cash')
        self.assertGreater(len(stats), 0)

        meta_hash = repo.get_meta('source_hash')
        self.assertIsNotNone(meta_hash)

        meta_run = repo.get_meta('last_run')
        self.assertIsNotNone(meta_run)

        conn.close()

    def test_skip_when_no_changes(self):
        from src.analytics_pipeline import run_analysis

        # First run
        run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='cash',
        )

        # Second run without changes → should skip
        result = run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=False,
            analysis_type='cash',
        )
        self.assertTrue(result['skipped'])
        self.assertIn('No new imports', result['reason'])

    def test_force_recalculates(self):
        from src.analytics_pipeline import run_analysis

        # First run
        run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='cash',
        )

        # Force run → should NOT skip
        result = run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='cash',
        )
        self.assertFalse(result['skipped'])
        self.assertTrue(result['cash_processed'])

    def test_cash_only_analysis(self):
        from src.analytics_pipeline import run_analysis

        result = run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='cash',
        )
        self.assertTrue(result['cash_processed'])
        self.assertFalse(result['tournament_processed'])

    def test_tournament_only_analysis(self):
        from src.analytics_pipeline import run_analysis

        # Add tournament data
        conn = sqlite3.connect(self.poker_db_path)
        conn.row_factory = sqlite3.Row
        repo = Repository(conn)
        _setup_tournament_db(conn, repo)
        conn.close()

        result = run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='tournament',
        )
        self.assertFalse(result['cash_processed'])
        self.assertTrue(result['tournament_processed'])

    def test_all_analysis(self):
        from src.analytics_pipeline import run_analysis

        # Add tournament data
        conn = sqlite3.connect(self.poker_db_path)
        conn.row_factory = sqlite3.Row
        repo = Repository(conn)
        _setup_tournament_db(conn, repo)
        conn.close()

        result = run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='all',
        )
        self.assertTrue(result['cash_processed'])
        self.assertTrue(result['tournament_processed'])

    def test_meta_updated_after_run(self):
        from src.analytics_pipeline import run_analysis

        run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='cash',
        )

        conn = sqlite3.connect(self.analytics_db_path)
        conn.row_factory = sqlite3.Row
        repo = AnalyticsRepository(conn)

        self.assertIsNotNone(repo.get_meta('source_hash'))
        self.assertIsNotNone(repo.get_meta('last_run'))
        self.assertEqual(repo.get_meta('analysis_type'), 'cash')
        conn.close()

    def test_clear_before_rerun(self):
        """Re-running clears old data for that game_type before inserting."""
        from src.analytics_pipeline import run_analysis

        # Run twice
        run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='cash',
        )
        run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='cash',
        )

        conn = sqlite3.connect(self.analytics_db_path)
        conn.row_factory = sqlite3.Row
        repo = AnalyticsRepository(conn)

        # Should have same count as one run (not doubled)
        stats = repo.get_global_stats('cash')
        stat_names = [s['stat_name'] for s in stats]
        # summary should appear exactly once
        self.assertEqual(stat_names.count('summary'), 1)
        conn.close()

    def test_empty_db_no_error(self):
        """Running on an empty poker DB should not error."""
        from src.analytics_pipeline import run_analysis

        empty_fd, empty_path = tempfile.mkstemp(suffix='.db')
        try:
            # Initialize an empty poker DB
            conn = sqlite3.connect(empty_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            conn.close()

            result = run_analysis(
                poker_db_path=empty_path,
                analytics_db_path=self.analytics_db_path,
                force=True,
                analysis_type='all',
            )
            # No data to process but shouldn't crash
            self.assertFalse(result['cash_processed'])
            self.assertFalse(result['tournament_processed'])
        finally:
            os.close(empty_fd)
            os.unlink(empty_path)


# ══════════════════════════════════════════════════════════════════
# Source Hash Tests
# ══════════════════════════════════════════════════════════════════


class TestSourceHash(unittest.TestCase):
    """Test source hash computation for incremental updates."""

    def test_hash_changes_with_more_data(self):
        from src.analytics_pipeline import _compute_source_hash

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        hash1 = _compute_source_hash(repo, '2026')

        # Add a hand
        hand = _make_hand('H001')
        repo.insert_hand(hand)
        conn.commit()

        hash2 = _compute_source_hash(repo, '2026')
        self.assertNotEqual(hash1, hash2)
        conn.close()

    def test_hash_deterministic(self):
        from src.analytics_pipeline import _compute_source_hash

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        hash1 = _compute_source_hash(repo, '2026')
        hash2 = _compute_source_hash(repo, '2026')
        self.assertEqual(hash1, hash2)
        conn.close()


# ══════════════════════════════════════════════════════════════════
# CLI Integration Tests
# ══════════════════════════════════════════════════════════════════


class TestAnalyzeCLI(unittest.TestCase):
    """Test the analyze CLI command."""

    def test_analyze_help(self):
        result = subprocess.run(
            [sys.executable, 'main.py', 'analyze', '--help'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('--force', result.stdout)
        self.assertIn('--type', result.stdout)
        self.assertIn('--analytics-db', result.stdout)

    def test_analyze_appears_in_main_help(self):
        result = subprocess.run(
            [sys.executable, 'main.py', '--help'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('analyze', result.stdout)

    def test_analyze_with_empty_db(self):
        """Analyze with an empty poker DB should not crash."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as pdb:
            poker_path = pdb.name
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as adb:
            analytics_path = adb.name

        try:
            result = subprocess.run(
                [sys.executable, 'main.py', '--db', poker_path,
                 'analyze', '--force', '--analytics-db', analytics_path],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn('POKER ANALYZER', result.stdout)
        finally:
            os.unlink(poker_path)
            os.unlink(analytics_path)

    def test_analyze_with_data(self):
        """Full end-to-end: import → analyze."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as pdb:
            poker_path = pdb.name
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as adb:
            analytics_path = adb.name

        try:
            # Set up poker DB
            conn = sqlite3.connect(poker_path)
            conn.row_factory = sqlite3.Row
            _setup_poker_db(conn)
            conn.close()

            result = subprocess.run(
                [sys.executable, 'main.py', '--db', poker_path,
                 'analyze', '--force', '--type', 'cash',
                 '--analytics-db', analytics_path],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn('Cash analysis', result.stdout)
            self.assertIn('completed', result.stdout)

            # Verify analytics DB
            conn = sqlite3.connect(analytics_path)
            conn.row_factory = sqlite3.Row
            repo = AnalyticsRepository(conn)
            stats = repo.get_global_stats('cash')
            self.assertGreater(len(stats), 0)
            conn.close()
        finally:
            os.unlink(poker_path)
            os.unlink(analytics_path)

    def test_analyze_skip_message(self):
        """Second run without changes shows skip message."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as pdb:
            poker_path = pdb.name
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as adb:
            analytics_path = adb.name

        try:
            conn = sqlite3.connect(poker_path)
            conn.row_factory = sqlite3.Row
            _setup_poker_db(conn)
            conn.close()

            # First run
            subprocess.run(
                [sys.executable, 'main.py', '--db', poker_path,
                 'analyze', '--force', '--analytics-db', analytics_path],
                capture_output=True, text=True,
            )

            # Second run
            result = subprocess.run(
                [sys.executable, 'main.py', '--db', poker_path,
                 'analyze', '--analytics-db', analytics_path],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn('No new imports', result.stdout)
        finally:
            os.unlink(poker_path)
            os.unlink(analytics_path)


# ══════════════════════════════════════════════════════════════════
# Safe JSON Tests
# ══════════════════════════════════════════════════════════════════


class TestSafeJson(unittest.TestCase):
    """Test the _safe_json helper."""

    def test_safe_json_dict(self):
        from src.analytics_pipeline import _safe_json
        data = {'a': 1, 'b': [1, 2]}
        self.assertEqual(_safe_json(data), data)

    def test_safe_json_none(self):
        from src.analytics_pipeline import _safe_json
        self.assertIsNone(_safe_json(None))

    def test_safe_json_non_serializable(self):
        from src.analytics_pipeline import _safe_json
        obj = datetime.now()
        result = _safe_json(obj)
        self.assertIsInstance(result, str)


# ══════════════════════════════════════════════════════════════════
# Analytics DB Content Verification Tests
# ══════════════════════════════════════════════════════════════════


class TestAnalyticsDBContent(unittest.TestCase):
    """Verify analytics DB contains expected analysis results after pipeline."""

    def setUp(self):
        self.poker_db_fd, self.poker_db_path = tempfile.mkstemp(suffix='.db')
        self.analytics_db_fd, self.analytics_db_path = tempfile.mkstemp(suffix='.db')

        conn = sqlite3.connect(self.poker_db_path)
        conn.row_factory = sqlite3.Row
        _setup_poker_db(conn)
        conn.close()

        from src.analytics_pipeline import run_analysis
        run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='cash',
        )

        self.conn = sqlite3.connect(self.analytics_db_path)
        self.conn.row_factory = sqlite3.Row
        self.repo = AnalyticsRepository(self.conn)

    def tearDown(self):
        self.conn.close()
        os.close(self.poker_db_fd)
        os.close(self.analytics_db_fd)
        os.unlink(self.poker_db_path)
        os.unlink(self.analytics_db_path)

    def test_has_summary_stat(self):
        stats = self.repo.get_global_stats('cash')
        names = [s['stat_name'] for s in stats]
        self.assertIn('summary', names)

    def test_has_preflop_overall(self):
        stats = self.repo.get_global_stats('cash')
        names = [s['stat_name'] for s in stats]
        self.assertIn('preflop_overall', names)

    def test_has_postflop_overall(self):
        stats = self.repo.get_global_stats('cash')
        names = [s['stat_name'] for s in stats]
        self.assertIn('postflop_overall', names)

    def test_has_health_score(self):
        stats = self.repo.get_global_stats('cash')
        health = [s for s in stats if s['stat_name'] == 'health_score']
        self.assertEqual(len(health), 1)
        self.assertIsNotNone(health[0]['stat_value'])

    def test_summary_has_total_hands(self):
        stats = self.repo.get_global_stats('cash')
        summary = [s for s in stats if s['stat_name'] == 'summary'][0]
        self.assertIn('total_hands', summary['stat_json'])
        self.assertEqual(summary['stat_json']['total_hands'], 5)

    def test_no_tournament_data(self):
        """Cash-only run should not have tournament data."""
        tourn = self.repo.get_global_stats('tournament')
        self.assertEqual(len(tourn), 0)

    def test_ev_analysis_stored(self):
        ev = self.repo.get_ev_analysis('cash')
        types = [e['analysis_type'] for e in ev]
        self.assertIn('allin_ev', types)
        self.assertIn('decision_ev', types)

    def test_bet_sizing_stored(self):
        sizing = self.repo.get_bet_sizing('cash')
        self.assertGreater(len(sizing), 0)

    def test_redline_stored(self):
        redline = self.repo.get_redline_blueline('cash')
        self.assertGreater(len(redline), 0)


# ══════════════════════════════════════════════════════════════════
# Tournament Analytics Tests
# ══════════════════════════════════════════════════════════════════


class TestTournamentAnalytics(unittest.TestCase):
    """Test tournament analysis pipeline."""

    def setUp(self):
        self.poker_db_fd, self.poker_db_path = tempfile.mkstemp(suffix='.db')
        self.analytics_db_fd, self.analytics_db_path = tempfile.mkstemp(suffix='.db')

        conn = sqlite3.connect(self.poker_db_path)
        conn.row_factory = sqlite3.Row
        repo = _setup_poker_db(conn)
        _setup_tournament_db(conn, repo)
        conn.close()

    def tearDown(self):
        os.close(self.poker_db_fd)
        os.close(self.analytics_db_fd)
        os.unlink(self.poker_db_path)
        os.unlink(self.analytics_db_path)

    def test_tournament_analysis_runs(self):
        from src.analytics_pipeline import run_analysis

        result = run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='tournament',
        )
        self.assertTrue(result['tournament_processed'])

    def test_tournament_summary_stored(self):
        from src.analytics_pipeline import run_analysis

        run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='tournament',
        )

        conn = sqlite3.connect(self.analytics_db_path)
        conn.row_factory = sqlite3.Row
        repo = AnalyticsRepository(conn)

        stats = repo.get_global_stats('tournament')
        names = [s['stat_name'] for s in stats]
        self.assertIn('summary', names)
        conn.close()

    def test_both_game_types_stored(self):
        from src.analytics_pipeline import run_analysis

        run_analysis(
            poker_db_path=self.poker_db_path,
            analytics_db_path=self.analytics_db_path,
            force=True,
            analysis_type='all',
        )

        conn = sqlite3.connect(self.analytics_db_path)
        conn.row_factory = sqlite3.Row
        repo = AnalyticsRepository(conn)

        cash = repo.get_global_stats('cash')
        tourn = repo.get_global_stats('tournament')
        self.assertGreater(len(cash), 0)
        self.assertGreater(len(tourn), 0)
        conn.close()


if __name__ == '__main__':
    unittest.main()
