"""Tests for US-051: Lesson Tracker Web – Dashboard de Aulas + Performance por Aula."""

import json
import os
import sqlite3
import tempfile
import unittest

from src.web.app import create_app
from src.web.data import load_analytics_data, prepare_lessons_data
from src.db.analytics_schema import init_analytics_db
from src.db.analytics_repository import AnalyticsRepository


# ── Helpers ──────────────────────────────────────────────────────


def _create_analytics_db_with_lessons(path: str, game_type: str = 'cash'):
    """Create analytics.db with lesson_stats and lesson_summary data."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_analytics_db(conn)

    now = '2026-03-15T12:00:00'

    # Summary (needed for base page rendering)
    summary = {
        'total_hands': 500,
        'total_net': 100.0,
        'total_days': 5,
    }
    conn.execute(
        "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (game_type, 'summary', json.dumps(summary), now),
    )

    # Lesson summary
    lesson_summary = {
        'total_lessons_with_data': 8,
        'total_lessons': 25,
        'total_hands': 320,
        'total_correct': 240,
        'total_incorrect': 60,
        'global_accuracy': 80.0,
        'mastered': 3,
        'learning': 2,
        'needs_work': 3,
        'by_category': {
            'Preflop': {
                'total': 180, 'correct': 140, 'incorrect': 30,
                'accuracy': 82.4,
            },
            'Postflop': {
                'total': 120, 'correct': 85, 'incorrect': 25,
                'accuracy': 77.3,
            },
            'Torneios': {
                'total': 20, 'correct': 15, 'incorrect': 5,
                'accuracy': 75.0,
            },
        },
    }
    conn.execute(
        "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (game_type, 'lesson_summary', json.dumps(lesson_summary), now),
    )

    # Per-lesson stats
    lessons_data = [
        {
            'lesson_id': 1, 'title': 'Ranges de RFI em cEV',
            'category': 'Preflop', 'subcategory': 'Ranges',
            'description': 'Ranges de Raise First In.',
            'total_hands': 80, 'correct': 70, 'incorrect': 8, 'unknown': 2,
            'accuracy': 89.7, 'error_rate': 10.3,
            'mastery': 'mastered',
            'by_street': {'preflop': {'total': 80, 'correct': 70, 'incorrect': 8}},
        },
        {
            'lesson_id': 2, 'title': 'Ranges de Flat e 3-BET',
            'category': 'Preflop', 'subcategory': 'Ranges',
            'description': 'Flat call e 3-bet ranges.',
            'total_hands': 50, 'correct': 35, 'incorrect': 12, 'unknown': 3,
            'accuracy': 74.5, 'error_rate': 25.5,
            'mastery': 'learning',
            'by_street': {'preflop': {'total': 50, 'correct': 35, 'incorrect': 12}},
        },
        {
            'lesson_id': 6, 'title': 'Jogando no Big Blind - Pré-Flop',
            'category': 'Preflop', 'subcategory': 'Blinds',
            'description': 'Defesa do BB pré-flop.',
            'total_hands': 50, 'correct': 35, 'incorrect': 10, 'unknown': 5,
            'accuracy': 77.8, 'error_rate': 22.2,
            'mastery': 'learning',
            'by_street': {'preflop': {'total': 50, 'correct': 35, 'incorrect': 10}},
        },
        {
            'lesson_id': 13, 'title': 'C-Bet Flop em Posição',
            'category': 'Postflop', 'subcategory': 'C-Bet',
            'description': 'CBet IP.',
            'total_hands': 60, 'correct': 50, 'incorrect': 5, 'unknown': 5,
            'accuracy': 90.9, 'error_rate': 9.1,
            'mastery': 'mastered',
            'by_street': {'flop': {'total': 60, 'correct': 50, 'incorrect': 5}},
        },
        {
            'lesson_id': 14, 'title': 'C-Bet OOP',
            'category': 'Postflop', 'subcategory': 'C-Bet',
            'description': 'CBet OOP.',
            'total_hands': 30, 'correct': 18, 'incorrect': 10, 'unknown': 2,
            'accuracy': 64.3, 'error_rate': 35.7,
            'mastery': 'needs_work',
            'by_street': {'flop': {'total': 30, 'correct': 18, 'incorrect': 10}},
        },
        {
            'lesson_id': 15, 'title': 'C-Bet Turn',
            'category': 'Postflop', 'subcategory': 'C-Bet',
            'description': 'CBet turn.',
            'total_hands': 20, 'correct': 12, 'incorrect': 6, 'unknown': 2,
            'accuracy': 66.7, 'error_rate': 33.3,
            'mastery': 'needs_work',
            'by_street': {'turn': {'total': 20, 'correct': 12, 'incorrect': 6}},
        },
        {
            'lesson_id': 16, 'title': 'C-Bet River',
            'category': 'Postflop', 'subcategory': 'C-Bet',
            'description': 'CBet river.',
            'total_hands': 10, 'correct': 5, 'incorrect': 4, 'unknown': 1,
            'accuracy': 55.6, 'error_rate': 44.4,
            'mastery': 'needs_work',
            'by_street': {'river': {'total': 10, 'correct': 5, 'incorrect': 4}},
        },
        {
            'lesson_id': 24, 'title': 'Introdução aos Torneios Bounty',
            'category': 'Torneios', 'subcategory': 'Bounty',
            'description': 'Torneios bounty.',
            'total_hands': 20, 'correct': 15, 'incorrect': 5, 'unknown': 0,
            'accuracy': 75.0, 'error_rate': 25.0,
            'mastery': 'mastered',
            'by_street': {'preflop': {'total': 20, 'correct': 15, 'incorrect': 5}},
        },
    ]

    for ld in lessons_data:
        conn.execute(
            "INSERT INTO lesson_stats (game_type, lesson_id, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (game_type, ld['lesson_id'], json.dumps(ld), now),
        )

    conn.commit()
    conn.close()


# ── Schema Tests ─────────────────────────────────────────────────


class TestLessonStatsSchema(unittest.TestCase):
    """Test lesson_stats table creation."""

    def test_schema_creates_lesson_stats_table(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        self.assertIn('lesson_stats', tables)
        conn.close()

    def test_schema_creates_lesson_stats_index(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)
        indices = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()]
        self.assertIn('idx_lesson_stats_game', indices)
        conn.close()

    def test_lesson_stats_columns(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(lesson_stats)"
        ).fetchall()]
        self.assertIn('id', cols)
        self.assertIn('game_type', cols)
        self.assertIn('lesson_id', cols)
        self.assertIn('stat_json', cols)
        self.assertIn('updated_at', cols)
        conn.close()


# ── Analytics Repository Tests ───────────────────────────────────


class TestAnalyticsRepositoryLessons(unittest.TestCase):
    """Test lesson_stats CRUD in AnalyticsRepository."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_analytics_db(self.conn)
        self.repo = AnalyticsRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_insert_and_get_lesson_stat(self):
        data = {'lesson_id': 1, 'title': 'Test', 'accuracy': 85.0}
        self.repo.insert_lesson_stat('cash', 1, data)
        self.repo.commit()
        results = self.repo.get_lesson_stats('cash')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['lesson_id'], 1)
        self.assertEqual(results[0]['data']['accuracy'], 85.0)

    def test_get_empty_lesson_stats(self):
        results = self.repo.get_lesson_stats('cash')
        self.assertEqual(results, [])

    def test_lesson_stats_per_game_type(self):
        self.repo.insert_lesson_stat('cash', 1, {'accuracy': 80.0})
        self.repo.insert_lesson_stat('tournament', 1, {'accuracy': 70.0})
        self.repo.commit()
        cash = self.repo.get_lesson_stats('cash')
        tourn = self.repo.get_lesson_stats('tournament')
        self.assertEqual(len(cash), 1)
        self.assertEqual(len(tourn), 1)
        self.assertEqual(cash[0]['data']['accuracy'], 80.0)
        self.assertEqual(tourn[0]['data']['accuracy'], 70.0)

    def test_clear_game_type_includes_lesson_stats(self):
        self.repo.insert_lesson_stat('cash', 1, {'accuracy': 80.0})
        self.repo.insert_lesson_stat('cash', 2, {'accuracy': 70.0})
        self.repo.commit()
        self.repo.clear_game_type('cash')
        results = self.repo.get_lesson_stats('cash')
        self.assertEqual(len(results), 0)

    def test_multiple_lessons_same_game_type(self):
        for i in range(5):
            self.repo.insert_lesson_stat('cash', i + 1, {'lesson_id': i + 1})
        self.repo.commit()
        results = self.repo.get_lesson_stats('cash')
        self.assertEqual(len(results), 5)


# ── Data Layer Tests ─────────────────────────────────────────────


class TestLoadAnalyticsLessonData(unittest.TestCase):
    """Test load_analytics_data includes lesson_stats."""

    def test_loads_lesson_stats(self):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            _create_analytics_db_with_lessons(db_path)
            data = load_analytics_data(db_path, 'cash')
            self.assertIn('lesson_stats', data)
            self.assertEqual(len(data['lesson_stats']), 8)
            self.assertIn(1, data['lesson_stats'])
            self.assertEqual(data['lesson_stats'][1]['title'], 'Ranges de RFI em cEV')
        finally:
            os.unlink(db_path)

    def test_loads_lesson_summary(self):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            _create_analytics_db_with_lessons(db_path)
            data = load_analytics_data(db_path, 'cash')
            self.assertIn('lesson_summary', data)
            self.assertEqual(data['lesson_summary']['total_hands'], 320)
            self.assertEqual(data['lesson_summary']['global_accuracy'], 80.0)
        finally:
            os.unlink(db_path)

    def test_empty_db_returns_empty_lesson_stats(self):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            init_analytics_db(conn)
            conn.close()
            data = load_analytics_data(db_path, 'cash')
            self.assertEqual(data.get('lesson_stats', {}), {})
        finally:
            os.unlink(db_path)


class TestPrepareLessonsData(unittest.TestCase):
    """Test prepare_lessons_data() function."""

    def _make_data(self):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        _create_analytics_db_with_lessons(db_path)
        data = load_analytics_data(db_path, 'cash')
        os.unlink(db_path)
        return data

    def test_overview_cards(self):
        data = self._make_data()
        prepare_lessons_data(data)
        self.assertEqual(data['lesson_total'], 25)
        self.assertEqual(data['lesson_classified_hands'], 320)
        self.assertEqual(data['lesson_global_accuracy'], 80.0)
        self.assertEqual(data['lesson_mastered'], 3)
        self.assertEqual(data['lesson_learning'], 2)
        self.assertEqual(data['lesson_needs_work'], 3)

    def test_lessons_list_sorted_by_accuracy(self):
        data = self._make_data()
        prepare_lessons_data(data)
        lessons = data['lessons_list']
        self.assertGreater(len(lessons), 0)
        # Worst accuracy should be first
        accuracies = [l.get('accuracy') for l in lessons if l.get('accuracy') is not None]
        self.assertEqual(accuracies, sorted(accuracies))

    def test_lessons_by_category(self):
        data = self._make_data()
        prepare_lessons_data(data)
        cats = data['lessons_by_category']
        self.assertGreater(len(cats), 0)
        cat_names = [c['name'] for c in cats]
        self.assertIn('Preflop', cat_names)
        self.assertIn('Postflop', cat_names)

    def test_category_accuracy(self):
        data = self._make_data()
        prepare_lessons_data(data)
        cats = data['lessons_by_category']
        preflop = next(c for c in cats if c['name'] == 'Preflop')
        self.assertAlmostEqual(preflop['accuracy'], 82.4, places=1)

    def test_cat_chart_data(self):
        data = self._make_data()
        prepare_lessons_data(data)
        chart = data['lessons_cat_chart']
        self.assertGreater(len(chart), 0)
        self.assertIn('name', chart[0])
        self.assertIn('accuracy', chart[0])

    def test_errors_only_filter(self):
        data = self._make_data()
        prepare_lessons_data(data)
        errors = data['lessons_errors_only']
        for l in errors:
            self.assertGreater(l['incorrect'], 0)

    def test_study_suggestions(self):
        data = self._make_data()
        prepare_lessons_data(data)
        suggestions = data['lessons_study_suggestions']
        self.assertLessEqual(len(suggestions), 5)
        for s in suggestions:
            self.assertIn(s['mastery'], ('needs_work', 'learning'))

    def test_mastery_pct(self):
        data = self._make_data()
        prepare_lessons_data(data)
        # 3 mastered out of 8 with data = 37.5%
        self.assertAlmostEqual(data['mastery_pct'], 37.5, places=1)

    def test_empty_data(self):
        data = {}
        prepare_lessons_data(data)
        self.assertEqual(data['lesson_total'], 25)
        self.assertEqual(data['lesson_classified_hands'], 0)
        self.assertIsNone(data['lesson_global_accuracy'])
        self.assertEqual(data['lessons_list'], [])
        self.assertEqual(data['lessons_by_category'], [])

    def test_with_data_count(self):
        data = self._make_data()
        prepare_lessons_data(data)
        self.assertEqual(data['lesson_with_data'], 8)

    def test_period_params_set(self):
        data = self._make_data()
        prepare_lessons_data(data, period='3m', from_date='2026-01-01', to_date='2026-03-31')
        self.assertEqual(data['active_period'], '3m')
        self.assertEqual(data['custom_from'], '2026-01-01')
        self.assertEqual(data['custom_to'], '2026-03-31')


# ── Flask Route Tests ────────────────────────────────────────────


class TestLessonsRoutes(unittest.TestCase):
    """Test /cash/lessons and /tournament/lessons routes."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        _create_analytics_db_with_lessons(self.db_path, game_type='cash')
        # Also add tournament lesson data
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        now = '2026-03-15T12:00:00'
        # Tournament summary
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('tournament', 'summary', json.dumps({'total_hands': 200}), now),
        )
        # Tournament lesson summary
        tourn_summary = {
            'total_lessons_with_data': 2,
            'total_lessons': 25,
            'total_hands': 40,
            'total_correct': 30,
            'total_incorrect': 10,
            'global_accuracy': 75.0,
            'mastered': 1,
            'learning': 1,
            'needs_work': 0,
            'by_category': {
                'Torneios': {'total': 40, 'correct': 30, 'incorrect': 10, 'accuracy': 75.0},
            },
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('tournament', 'lesson_summary', json.dumps(tourn_summary), now),
        )
        # Tournament lesson stat
        conn.execute(
            "INSERT INTO lesson_stats (game_type, lesson_id, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('tournament', 24, json.dumps({
                'lesson_id': 24, 'title': 'Torneios Bounty',
                'category': 'Torneios', 'total_hands': 40,
                'correct': 30, 'incorrect': 10, 'unknown': 0,
                'accuracy': 75.0, 'mastery': 'mastered',
            }), now),
        )
        conn.commit()
        conn.close()

        self.app = create_app(analytics_db_path=self.db_path)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_cash_lessons_route_200(self):
        resp = self.client.get('/cash/lessons')
        self.assertEqual(resp.status_code, 200)

    def test_tournament_lessons_route_200(self):
        resp = self.client.get('/tournament/lessons')
        self.assertEqual(resp.status_code, 200)

    def test_cash_lessons_contains_title(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Dashboard de Aulas', html)

    def test_cash_lessons_contains_overview_cards(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Aulas com Dados', html)
        self.assertIn('Maos Classificadas', html)
        self.assertIn('Acerto Global', html)
        self.assertIn('Dominadas', html)

    def test_cash_lessons_contains_category_table(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Acerto por Categoria', html)
        self.assertIn('Preflop', html)
        self.assertIn('Postflop', html)

    def test_cash_lessons_contains_lessons_table(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Performance por Aula', html)
        self.assertIn('Ranges de RFI em cEV', html)
        self.assertIn('C-Bet OOP', html)

    def test_cash_lessons_contains_mastery_badges(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Dominada', html)
        self.assertIn('Aprendendo', html)
        self.assertIn('Precisa Trabalho', html)

    def test_cash_lessons_contains_study_suggestions(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Sugestoes de Estudo', html)

    def test_cash_lessons_contains_errors_filter_button(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('toggleErrorsOnly', html)
        self.assertIn('Apenas com Erros', html)

    def test_cash_lessons_contains_mastery_progress(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Progresso de Mastery', html)

    def test_cash_lessons_accuracy_badges(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('badge-good', html)
        self.assertIn('badge-danger', html)

    def test_tournament_lessons_contains_title(self):
        resp = self.client.get('/tournament/lessons')
        html = resp.data.decode()
        self.assertIn('Dashboard de Aulas (Torneios)', html)

    def test_tournament_lessons_contains_data(self):
        resp = self.client.get('/tournament/lessons')
        html = resp.data.decode()
        self.assertIn('Torneios Bounty', html)

    def test_cash_lessons_category_chart(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('<svg', html)
        self.assertIn('<rect', html)

    def test_lessons_tab_in_navigation(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Aulas', html)

    def test_invalid_tab_redirects_to_overview(self):
        resp = self.client.get('/cash/invalid_tab_xyz')
        self.assertEqual(resp.status_code, 200)


# ── Empty State Tests ────────────────────────────────────────────


class TestLessonsEmptyState(unittest.TestCase):
    """Test lessons page with no lesson data."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'summary', json.dumps({'total_hands': 100}), '2026-03-15'),
        )
        conn.commit()
        conn.close()
        self.app = create_app(analytics_db_path=self.db_path)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_empty_lessons_shows_empty_state(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Nenhum dado de aulas disponivel', html)

    def test_empty_lessons_shows_analyze_hint(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('python main.py analyze', html)


# ── Pipeline Integration Tests ───────────────────────────────────


class TestPipelineLessonStats(unittest.TestCase):
    """Test _persist_lesson_stats in analytics pipeline."""

    def test_persist_lesson_stats_import(self):
        """Verify _persist_lesson_stats is importable."""
        from src.analytics_pipeline import _persist_lesson_stats
        self.assertTrue(callable(_persist_lesson_stats))

    def test_persist_lesson_stats_no_lessons(self):
        """Test with empty lesson catalog."""
        from src.analytics_pipeline import _persist_lesson_stats
        from src.db.schema import init_db

        source_conn = sqlite3.connect(':memory:')
        source_conn.row_factory = sqlite3.Row
        init_db(source_conn)

        analytics_conn = sqlite3.connect(':memory:')
        analytics_conn.row_factory = sqlite3.Row
        init_analytics_db(analytics_conn)
        analytics = AnalyticsRepository(analytics_conn)

        from src.db.repository import Repository
        repo = Repository(source_conn)
        _persist_lesson_stats(analytics, repo)

        results = analytics.get_lesson_stats('cash')
        self.assertEqual(len(results), 0)

        source_conn.close()
        analytics_conn.close()

    def test_persist_lesson_stats_with_data(self):
        """Test with seeded lessons and hand_lessons data."""
        from src.analytics_pipeline import _persist_lesson_stats
        from src.db.schema import init_db
        from src.db.seed_lessons import seed_lessons

        source_conn = sqlite3.connect(':memory:')
        source_conn.row_factory = sqlite3.Row
        init_db(source_conn)
        seed_lessons(source_conn)

        # Insert a hand
        source_conn.execute("""
            INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb,
                               blinds_bb, hero_cards, hero_position,
                               invested, won, net, rake, table_name, num_players)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('h1', 'GGPoker', 'cash', '2026-01-15T10:00:00',
              0.25, 0.50, 'Ah Kd', 'BTN', 5.0, 10.0, 5.0, 0.5, 'T1', 6))
        source_conn.commit()

        # Link hand to lesson
        source_conn.execute("""
            INSERT INTO hand_lessons (hand_id, lesson_id, street,
                                      executed_correctly, confidence, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ('h1', 1, 'preflop', 1, 1.0, '', '2026-01-15'))
        source_conn.commit()

        analytics_conn = sqlite3.connect(':memory:')
        analytics_conn.row_factory = sqlite3.Row
        init_analytics_db(analytics_conn)
        analytics = AnalyticsRepository(analytics_conn)

        from src.db.repository import Repository
        repo = Repository(source_conn)
        _persist_lesson_stats(analytics, repo)

        # Should have lesson stat for lesson 1
        results = analytics.get_lesson_stats('cash')
        self.assertGreater(len(results), 0)
        lesson_1 = next(r for r in results if r['lesson_id'] == 1)
        self.assertEqual(lesson_1['data']['correct'], 1)
        self.assertEqual(lesson_1['data']['total_hands'], 1)

        # Should have lesson summary global stat
        global_stats = analytics.get_global_stats('cash')
        summary_rows = [s for s in global_stats if s['stat_name'] == 'lesson_summary']
        self.assertEqual(len(summary_rows), 1)
        summary = summary_rows[0]['stat_json']
        self.assertEqual(summary['total_hands'], 1)
        self.assertEqual(summary['mastered'], 0)  # only 1 hand, not enough for mastered

        source_conn.close()
        analytics_conn.close()

    def test_persist_lesson_stats_mastery_classification(self):
        """Test mastery levels: mastered (>=20 hands, >=80%), learning, needs_work."""
        from src.analytics_pipeline import _persist_lesson_stats
        from src.db.schema import init_db
        from src.db.seed_lessons import seed_lessons

        source_conn = sqlite3.connect(':memory:')
        source_conn.row_factory = sqlite3.Row
        init_db(source_conn)
        seed_lessons(source_conn)

        # Insert 25 hands for lesson 1 with 21 correct, 4 incorrect
        for i in range(25):
            hand_id = f'h{i}'
            source_conn.execute("""
                INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb,
                                   blinds_bb, hero_cards, hero_position,
                                   invested, won, net, rake, table_name, num_players)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (hand_id, 'GGPoker', 'cash', '2026-01-15T10:00:00',
                  0.25, 0.50, 'Ah Kd', 'BTN', 5.0, 10.0, 5.0, 0.5, 'T1', 6))
            ec = 1 if i < 21 else 0
            source_conn.execute("""
                INSERT INTO hand_lessons (hand_id, lesson_id, street,
                                          executed_correctly, confidence, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (hand_id, 1, 'preflop', ec, 1.0, '', '2026-01-15'))
        source_conn.commit()

        analytics_conn = sqlite3.connect(':memory:')
        analytics_conn.row_factory = sqlite3.Row
        init_analytics_db(analytics_conn)
        analytics = AnalyticsRepository(analytics_conn)

        from src.db.repository import Repository
        repo = Repository(source_conn)
        _persist_lesson_stats(analytics, repo)

        results = analytics.get_lesson_stats('cash')
        lesson_1 = next(r for r in results if r['lesson_id'] == 1)
        self.assertEqual(lesson_1['data']['mastery'], 'mastered')
        self.assertEqual(lesson_1['data']['correct'], 21)
        self.assertEqual(lesson_1['data']['incorrect'], 4)
        self.assertAlmostEqual(lesson_1['data']['accuracy'], 84.0, places=1)

        source_conn.close()
        analytics_conn.close()

    def test_persist_multi_game_type(self):
        """Test lesson stats are separated by game_type."""
        from src.analytics_pipeline import _persist_lesson_stats
        from src.db.schema import init_db
        from src.db.seed_lessons import seed_lessons

        source_conn = sqlite3.connect(':memory:')
        source_conn.row_factory = sqlite3.Row
        init_db(source_conn)
        seed_lessons(source_conn)

        # Cash hand
        source_conn.execute("""
            INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb,
                               blinds_bb, hero_cards, hero_position,
                               invested, won, net, rake, table_name, num_players)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('h_cash', 'GGPoker', 'cash', '2026-01-15', 0.25, 0.50,
              'Ah Kd', 'BTN', 5, 10, 5, 0.5, 'T1', 6))
        # Tournament hand
        source_conn.execute("""
            INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb,
                               blinds_bb, hero_cards, hero_position,
                               invested, won, net, rake, table_name, num_players)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('h_tourn', 'GGPoker', 'tournament', '2026-01-15', 25, 50,
              'Ks Qd', 'CO', 100, 200, 100, 0, 'T2', 6))
        source_conn.execute("""
            INSERT INTO hand_lessons (hand_id, lesson_id, street,
                                      executed_correctly, confidence, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ('h_cash', 1, 'preflop', 1, 1.0, '', '2026-01-15'))
        source_conn.execute("""
            INSERT INTO hand_lessons (hand_id, lesson_id, street,
                                      executed_correctly, confidence, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ('h_tourn', 24, 'preflop', 0, 1.0, '', '2026-01-15'))
        source_conn.commit()

        analytics_conn = sqlite3.connect(':memory:')
        analytics_conn.row_factory = sqlite3.Row
        init_analytics_db(analytics_conn)
        analytics = AnalyticsRepository(analytics_conn)

        from src.db.repository import Repository
        repo = Repository(source_conn)
        _persist_lesson_stats(analytics, repo)

        cash_stats = analytics.get_lesson_stats('cash')
        tourn_stats = analytics.get_lesson_stats('tournament')
        self.assertEqual(len(cash_stats), 1)
        self.assertEqual(len(tourn_stats), 1)
        self.assertEqual(cash_stats[0]['lesson_id'], 1)
        self.assertEqual(tourn_stats[0]['lesson_id'], 24)

        source_conn.close()
        analytics_conn.close()


# ── Template Rendering Tests ─────────────────────────────────────


class TestLessonsTemplateRendering(unittest.TestCase):
    """Test specific template rendering details."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        _create_analytics_db_with_lessons(self.db_path)
        self.app = create_app(analytics_db_path=self.db_path)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_accuracy_values_displayed(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('89.7', html)  # RFI accuracy
        self.assertIn('55.6', html)  # C-Bet River accuracy

    def test_hand_counts_displayed(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('320', html)  # total classified hands

    def test_mastery_count_displayed(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        # 3 mastered
        self.assertIn('3', html)

    def test_category_accuracy_in_chart(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('82', html)  # Preflop accuracy ~82.4%

    def test_lesson_row_has_data_attribute(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('data-has-errors', html)

    def test_lesson_row_with_errors_marked(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('has-errors', html)

    def test_js_toggle_function(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('function toggleErrorsOnly', html)

    def test_page_title_correct(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        self.assertIn('Cash — Aulas', html)

    def test_tournament_page_title_correct(self):
        # Need tournament lesson data too
        conn = sqlite3.connect(self.db_path)
        now = '2026-03-15T12:00:00'
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('tournament', 'summary', json.dumps({'total_hands': 100}), now),
        )
        conn.commit()
        conn.close()
        resp = self.client.get('/tournament/lessons')
        html = resp.data.decode()
        self.assertIn('Torneios — Aulas', html)


# ── Tab Navigation Tests ─────────────────────────────────────────


class TestLessonsTabNavigation(unittest.TestCase):
    """Test lessons tab appears in navigation."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'summary', json.dumps({'total_hands': 100}), '2026-03-15'),
        )
        conn.commit()
        conn.close()
        self.app = create_app(analytics_db_path=self.db_path)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_lessons_tab_in_cash_nav(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('Aulas', html)
        self.assertIn('/cash/lessons', html)

    def test_lessons_tab_active_on_lessons_page(self):
        resp = self.client.get('/cash/lessons')
        html = resp.data.decode()
        # The lessons tab should have the active class
        # Look for the active class near the Aulas link
        self.assertIn('lessons', html)

    def test_valid_tabs_includes_lessons(self):
        from src.web.routes.cash import VALID_TABS as CASH_TABS
        from src.web.routes.tournament import VALID_TABS as TOURN_TABS
        self.assertIn('lessons', CASH_TABS)
        self.assertIn('lessons', TOURN_TABS)


if __name__ == '__main__':
    unittest.main()
