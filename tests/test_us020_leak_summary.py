"""Tests for US-020: Botão Resumo de Leaks por Sessão (Consolidação de Todas as Análises).

Tests cover:
1. LeakSummaryAnalyzer: grade_from_score, grade_color, build_leak_summary
2. Web data layer: prepare_overview_data builds leak_summary
3. Cash overview template: Grade card + modal rendering
4. Tournament overview template: Grade card + modal rendering
5. JavaScript functions: modal open/close/tab switch
"""

import json
import os
import sqlite3
import tempfile
import unittest

from src.analyzers.leak_summary import (
    grade_from_score,
    grade_color,
    build_leak_summary,
)
from src.web.app import create_app
from src.web.data import load_analytics_data, prepare_overview_data
from src.db.analytics_schema import init_analytics_db


# ── Helpers ──────────────────────────────────────────────────────


def _create_analytics_db_with_leaks(path, game_type='cash'):
    """Create an analytics.db with leak data for testing."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_analytics_db(conn)

    now = '2026-03-11T12:00:00'

    # Summary
    summary = {
        'total_hands': 1500,
        'total_net': 250.00,
        'total_days': 12,
    }
    if game_type == 'tournament':
        summary['total_tournaments'] = 25
        summary['roi'] = 15.5
    conn.execute(
        "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (game_type, 'summary', json.dumps(summary), now),
    )

    # Health score
    conn.execute(
        "INSERT INTO global_stats (game_type, stat_name, stat_value, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (game_type, 'health_score', 72, now),
    )

    # Preflop overall
    preflop = {
        'vpip': 26.0, 'vpip_badge': 'good',
        'pfr': 19.0, 'pfr_badge': 'good',
        'three_bet': 8.0, 'three_bet_badge': 'good',
        'fold_to_3bet': 58.0, 'fold_to_3bet_badge': 'warning',
        'ats': 33.0, 'ats_badge': 'good',
    }
    conn.execute(
        "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (game_type, 'preflop_overall', json.dumps(preflop), now),
    )

    # Postflop overall
    postflop = {
        'af': 2.5, 'af_badge': 'good',
        'wtsd': 30.0, 'wtsd_badge': 'good',
        'wsd': 50.0, 'wsd_badge': 'warning',
        'cbet': 62.0, 'cbet_badge': 'good',
        'fold_to_cbet': 48.0, 'fold_to_cbet_badge': 'warning',
    }
    conn.execute(
        "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (game_type, 'postflop_overall', json.dumps(postflop), now),
    )

    # Leaks
    leaks = [
        ('VPIP alto no UTG', 'positional', 'vpip', 28.0, 12.0, 18.0, 1.50, 'too_high',
         'Reduzir range UTG'),
        ('Fold to 3-Bet alto', 'preflop', 'fold_to_3bet', 58.0, 40.0, 55.0, 0.90, 'too_high',
         'Defender mais vs 3-bets'),
        ('W$SD baixo', 'postflop', 'wsd', 50.0, 50.0, 65.0, 0.60, 'too_low',
         'Melhorar seleção de mãos para showdown'),
        ('CBet fold alto', 'postflop', 'fold_to_cbet', 48.0, 35.0, 50.0, 0.40, 'too_high',
         'Defender mais vs CBet'),
        ('PFR baixo no CO', 'positional', 'pfr', 14.0, 18.0, 28.0, 0.56, 'too_low',
         'Abrir mais no CO'),
    ]
    for name, cat, stat, curr, low, high, cost, direction, suggestion in leaks:
        conn.execute(
            "INSERT INTO leak_analysis (game_type, leak_name, category, stat_name, "
            "current_value, healthy_low, healthy_high, cost_bb100, direction, suggestion, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (game_type, name, cat, stat, curr, low, high, cost, direction, suggestion, now),
        )

    # Daily report for overview chart
    daily = {
        'date': '2026-01-15',
        'net': 50.25,
        'total_hands': 200,
        'hands_count': 200,
        'day_stats': {
            'vpip': 26.0, 'pfr': 19.0, 'three_bet': 8.0,
            'af': 2.5, 'cbet': 62.0, 'wtsd': 30.0, 'wsd': 50.0,
        },
        'sessions': [],
    }
    conn.execute(
        "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (game_type, '2026-01-15', 'daily_report', json.dumps(daily), now),
    )

    conn.commit()
    conn.close()


# ── Unit Tests: leak_summary module ──────────────────────────────


class TestGradeFromScore(unittest.TestCase):
    """Test grade_from_score mapping."""

    def test_perfect_score(self):
        self.assertEqual(grade_from_score(100), 'A+')

    def test_a_plus_threshold(self):
        self.assertEqual(grade_from_score(95), 'A+')
        self.assertEqual(grade_from_score(94), 'A')

    def test_a_range(self):
        self.assertEqual(grade_from_score(90), 'A')
        self.assertEqual(grade_from_score(89), 'A-')

    def test_a_minus_range(self):
        self.assertEqual(grade_from_score(85), 'A-')
        self.assertEqual(grade_from_score(84), 'B+')

    def test_b_plus_range(self):
        self.assertEqual(grade_from_score(80), 'B+')
        self.assertEqual(grade_from_score(79), 'B')

    def test_b_range(self):
        self.assertEqual(grade_from_score(75), 'B')
        self.assertEqual(grade_from_score(74), 'B-')

    def test_b_minus_range(self):
        self.assertEqual(grade_from_score(70), 'B-')
        self.assertEqual(grade_from_score(69), 'C+')

    def test_c_plus_range(self):
        self.assertEqual(grade_from_score(65), 'C+')
        self.assertEqual(grade_from_score(64), 'C')

    def test_c_range(self):
        self.assertEqual(grade_from_score(60), 'C')
        self.assertEqual(grade_from_score(59), 'C-')

    def test_c_minus_range(self):
        self.assertEqual(grade_from_score(55), 'C-')
        self.assertEqual(grade_from_score(54), 'D+')

    def test_d_plus_range(self):
        self.assertEqual(grade_from_score(50), 'D+')
        self.assertEqual(grade_from_score(49), 'D')

    def test_d_range(self):
        self.assertEqual(grade_from_score(45), 'D')
        self.assertEqual(grade_from_score(44), 'D-')

    def test_d_minus_range(self):
        self.assertEqual(grade_from_score(40), 'D-')
        self.assertEqual(grade_from_score(39), 'F')

    def test_f_range(self):
        self.assertEqual(grade_from_score(0), 'F')
        self.assertEqual(grade_from_score(20), 'F')
        self.assertEqual(grade_from_score(10), 'F')

    def test_boundary_values(self):
        """Test all boundary values."""
        boundaries = {
            100: 'A+', 95: 'A+', 94: 'A', 90: 'A', 89: 'A-',
            85: 'A-', 84: 'B+', 80: 'B+', 79: 'B', 75: 'B',
            74: 'B-', 70: 'B-', 69: 'C+', 65: 'C+', 64: 'C',
            60: 'C', 59: 'C-', 55: 'C-', 54: 'D+', 50: 'D+',
            49: 'D', 45: 'D', 44: 'D-', 40: 'D-', 39: 'F', 0: 'F',
        }
        for score, expected in boundaries.items():
            with self.subTest(score=score):
                self.assertEqual(grade_from_score(score), expected)


class TestGradeColor(unittest.TestCase):
    """Test grade_color mapping."""

    def test_a_grades_are_good(self):
        self.assertEqual(grade_color('A+'), 'good')
        self.assertEqual(grade_color('A'), 'good')
        self.assertEqual(grade_color('A-'), 'good')

    def test_b_grades_are_good(self):
        self.assertEqual(grade_color('B+'), 'good')
        self.assertEqual(grade_color('B'), 'good')
        self.assertEqual(grade_color('B-'), 'good')

    def test_c_grades_are_warning(self):
        self.assertEqual(grade_color('C+'), 'warning')
        self.assertEqual(grade_color('C'), 'warning')
        self.assertEqual(grade_color('C-'), 'warning')

    def test_d_grades_are_warning(self):
        self.assertEqual(grade_color('D+'), 'warning')
        self.assertEqual(grade_color('D'), 'warning')
        self.assertEqual(grade_color('D-'), 'warning')

    def test_f_is_danger(self):
        self.assertEqual(grade_color('F'), 'danger')


class TestBuildLeakSummary(unittest.TestCase):
    """Test build_leak_summary consolidation function."""

    def test_empty_leaks(self):
        result = build_leak_summary(100, [])
        self.assertEqual(result['grade'], 'A+')
        self.assertEqual(result['grade_color'], 'good')
        self.assertEqual(result['health_score'], 100)
        self.assertEqual(result['total_leaks'], 0)
        self.assertEqual(result['total_cost'], 0)
        self.assertEqual(result['top_leaks'], [])
        self.assertEqual(result['by_category'], {})
        self.assertEqual(result['categories'], [])

    def test_none_leaks(self):
        result = build_leak_summary(80, None)
        self.assertEqual(result['total_leaks'], 0)
        self.assertEqual(result['grade'], 'B+')

    def test_single_leak(self):
        leaks = [{'leak_name': 'Test', 'category': 'preflop',
                  'stat_name': 'vpip', 'cost_bb100': 1.5}]
        result = build_leak_summary(65, leaks)
        self.assertEqual(result['grade'], 'C+')
        self.assertEqual(result['grade_color'], 'warning')
        self.assertEqual(result['total_leaks'], 1)
        self.assertEqual(result['total_cost'], 1.5)
        self.assertEqual(len(result['top_leaks']), 1)
        self.assertEqual(len(result['categories']), 1)
        self.assertEqual(result['categories'][0]['name'], 'preflop')

    def test_top_3_sorted_by_cost(self):
        leaks = [
            {'leak_name': 'Leak1', 'category': 'preflop', 'cost_bb100': 0.5},
            {'leak_name': 'Leak2', 'category': 'postflop', 'cost_bb100': 2.0},
            {'leak_name': 'Leak3', 'category': 'positional', 'cost_bb100': 1.0},
            {'leak_name': 'Leak4', 'category': 'preflop', 'cost_bb100': 3.0},
            {'leak_name': 'Leak5', 'category': 'postflop', 'cost_bb100': 0.3},
        ]
        result = build_leak_summary(50, leaks)
        self.assertEqual(len(result['top_leaks']), 3)
        self.assertEqual(result['top_leaks'][0]['leak_name'], 'Leak4')
        self.assertEqual(result['top_leaks'][1]['leak_name'], 'Leak2')
        self.assertEqual(result['top_leaks'][2]['leak_name'], 'Leak3')

    def test_grouping_by_category(self):
        leaks = [
            {'leak_name': 'L1', 'category': 'preflop', 'cost_bb100': 1.0},
            {'leak_name': 'L2', 'category': 'postflop', 'cost_bb100': 0.5},
            {'leak_name': 'L3', 'category': 'preflop', 'cost_bb100': 0.8},
            {'leak_name': 'L4', 'category': 'positional', 'cost_bb100': 0.3},
        ]
        result = build_leak_summary(60, leaks)
        self.assertIn('positional', result['by_category'])
        self.assertIn('postflop', result['by_category'])
        self.assertIn('preflop', result['by_category'])
        self.assertEqual(len(result['by_category']['preflop']), 2)
        self.assertEqual(len(result['by_category']['postflop']), 1)

    def test_categories_sorted_alphabetically(self):
        leaks = [
            {'category': 'postflop', 'cost_bb100': 0.5},
            {'category': 'preflop', 'cost_bb100': 1.0},
            {'category': 'abc', 'cost_bb100': 0.2},
        ]
        result = build_leak_summary(70, leaks)
        names = [c['name'] for c in result['categories']]
        self.assertEqual(names, ['abc', 'postflop', 'preflop'])

    def test_category_total_cost(self):
        leaks = [
            {'category': 'preflop', 'cost_bb100': 1.0},
            {'category': 'preflop', 'cost_bb100': 0.5},
            {'category': 'postflop', 'cost_bb100': 2.0},
        ]
        result = build_leak_summary(55, leaks)
        pf_cat = next(c for c in result['categories'] if c['name'] == 'preflop')
        po_cat = next(c for c in result['categories'] if c['name'] == 'postflop')
        self.assertAlmostEqual(pf_cat['total_cost'], 1.5)
        self.assertAlmostEqual(po_cat['total_cost'], 2.0)

    def test_total_cost_rounded(self):
        leaks = [
            {'category': 'preflop', 'cost_bb100': 1.111},
            {'category': 'postflop', 'cost_bb100': 2.222},
        ]
        result = build_leak_summary(60, leaks)
        self.assertEqual(result['total_cost'], 3.33)

    def test_score_clamped(self):
        result_low = build_leak_summary(-10, [])
        self.assertEqual(result_low['health_score'], 0)
        result_high = build_leak_summary(150, [])
        self.assertEqual(result_high['health_score'], 100)

    def test_none_health_score(self):
        result = build_leak_summary(None, [])
        self.assertEqual(result['health_score'], 0)
        self.assertEqual(result['grade'], 'F')

    def test_less_than_3_leaks(self):
        leaks = [{'category': 'preflop', 'cost_bb100': 1.0}]
        result = build_leak_summary(80, leaks)
        self.assertEqual(len(result['top_leaks']), 1)

    def test_missing_cost_defaults_to_zero(self):
        leaks = [{'category': 'preflop'}]
        result = build_leak_summary(90, leaks)
        self.assertEqual(result['total_cost'], 0)

    def test_missing_category_defaults_to_other(self):
        leaks = [{'cost_bb100': 1.0}]
        result = build_leak_summary(70, leaks)
        self.assertIn('other', result['by_category'])


# ── Integration Tests: Web Data Layer ────────────────────────────


class TestPrepareOverviewLeakSummary(unittest.TestCase):
    """Test that prepare_overview_data builds leak_summary."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmpdir)

    def test_leak_summary_present_when_leaks_exist(self):
        _create_analytics_db_with_leaks(self.db_path, 'cash')
        data = load_analytics_data(self.db_path, 'cash')
        prepare_overview_data(data)
        self.assertIn('leak_summary', data)
        ls = data['leak_summary']
        self.assertIsNotNone(ls)
        self.assertEqual(ls['health_score'], 72)
        self.assertEqual(ls['grade'], 'B-')
        self.assertEqual(ls['grade_color'], 'good')
        self.assertEqual(ls['total_leaks'], 5)
        self.assertEqual(len(ls['top_leaks']), 3)

    def test_leak_summary_none_when_no_data(self):
        # Create empty DB
        conn = sqlite3.connect(self.db_path)
        init_analytics_db(conn)
        conn.commit()
        conn.close()
        data = load_analytics_data(self.db_path, 'cash')
        prepare_overview_data(data)
        self.assertIsNone(data.get('leak_summary'))

    def test_leak_summary_categories(self):
        _create_analytics_db_with_leaks(self.db_path, 'cash')
        data = load_analytics_data(self.db_path, 'cash')
        prepare_overview_data(data)
        ls = data['leak_summary']
        cat_names = [c['name'] for c in ls['categories']]
        self.assertIn('preflop', cat_names)
        self.assertIn('postflop', cat_names)
        self.assertIn('positional', cat_names)

    def test_tournament_leak_summary(self):
        _create_analytics_db_with_leaks(self.db_path, 'tournament')
        data = load_analytics_data(self.db_path, 'tournament')
        prepare_overview_data(data)
        ls = data['leak_summary']
        self.assertIsNotNone(ls)
        self.assertEqual(ls['health_score'], 72)
        self.assertEqual(ls['total_leaks'], 5)

    def test_top_leaks_sorted_descending_by_cost(self):
        _create_analytics_db_with_leaks(self.db_path, 'cash')
        data = load_analytics_data(self.db_path, 'cash')
        prepare_overview_data(data)
        ls = data['leak_summary']
        costs = [l.get('cost_bb100', 0) for l in ls['top_leaks']]
        self.assertEqual(costs, sorted(costs, reverse=True))


# ── Template Tests: Cash Overview ────────────────────────────────


class TestCashOverviewLeakSummaryTemplate(unittest.TestCase):
    """Test cash overview page renders leak summary card and modal."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db_with_leaks(self.db_path, 'cash')

        self.app = create_app(self.db_path)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmpdir)

    def test_grade_card_rendered(self):
        resp = self.client.get('/cash/overview')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('leak-summary-card', html)
        self.assertIn('B-', html)
        self.assertIn('click for details', html)

    def test_modal_rendered(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('leak-summary-modal', html)
        self.assertIn('leak-modal-overlay', html)
        self.assertIn('Resumo de Leaks', html)

    def test_modal_tabs_rendered(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('leak-modal-tab', html)
        self.assertIn('Overview', html)
        self.assertIn('Todos os Leaks', html)

    def test_grade_card_in_modal(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('grade-card', html)
        self.assertIn('grade-letter', html)
        self.assertIn('Health Score: 72/100', html)

    def test_top_leaks_in_modal(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('Top Priority Leaks', html)
        self.assertIn('VPIP alto no UTG', html)

    def test_categories_table_in_modal(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('By Category', html)
        self.assertIn('preflop', html)
        self.assertIn('postflop', html)
        self.assertIn('positional', html)

    def test_all_leaks_tab_content(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('leak-tab-all-leaks', html)
        # All 5 leaks should appear in all-leaks tab
        self.assertIn('Fold to 3-Bet alto', html)
        self.assertIn('W$SD baixo', html)
        self.assertIn('CBet fold alto', html)
        self.assertIn('PFR baixo no CO', html)

    def test_javascript_functions(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('openLeakSummaryModal', html)
        self.assertIn('closeLeakSummaryModal', html)
        self.assertIn('closeLeakSummaryOverlay', html)
        self.assertIn('switchLeakSummaryTab', html)

    def test_esc_key_handler(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('Escape', html)

    def test_health_score_card_still_present(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('Health Score', html)
        self.assertIn('72', html)

    def test_modal_close_button(self):
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('leak-modal-close', html)


# ── Template Tests: Tournament Overview ──────────────────────────


class TestTournamentOverviewLeakSummaryTemplate(unittest.TestCase):
    """Test tournament overview page renders leak summary card and modal."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db_with_leaks(self.db_path, 'tournament')

        self.app = create_app(self.db_path)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmpdir)

    def test_grade_card_rendered(self):
        resp = self.client.get('/tournament/overview')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('leak-summary-card', html)
        self.assertIn('B-', html)

    def test_modal_rendered(self):
        resp = self.client.get('/tournament/overview')
        html = resp.data.decode()
        self.assertIn('leak-summary-modal', html)
        self.assertIn('Resumo de Leaks', html)

    def test_top_leaks_in_modal(self):
        resp = self.client.get('/tournament/overview')
        html = resp.data.decode()
        self.assertIn('Top Priority Leaks', html)

    def test_categories_in_modal(self):
        resp = self.client.get('/tournament/overview')
        html = resp.data.decode()
        self.assertIn('By Category', html)

    def test_javascript_functions(self):
        resp = self.client.get('/tournament/overview')
        html = resp.data.decode()
        self.assertIn('openLeakSummaryModal', html)
        self.assertIn('closeLeakSummaryModal', html)
        self.assertIn('switchLeakSummaryTab', html)


# ── Edge Case Tests ──────────────────────────────────────────────


class TestLeakSummaryEdgeCases(unittest.TestCase):
    """Test edge cases for leak summary."""

    def test_no_leaks_no_grade_card(self):
        """When no leaks and no health_score, template should not render modal."""
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, 'analytics.db')

        # Create DB with summary but no leaks
        conn = sqlite3.connect(db_path)
        init_analytics_db(conn)
        now = '2026-03-11T12:00:00'
        summary = {'total_hands': 100, 'total_net': 10.0, 'total_days': 1}
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'summary', json.dumps(summary), now),
        )
        daily = {
            'date': '2026-01-15', 'net': 10.0, 'total_hands': 100,
            'hands_count': 100, 'day_stats': {'vpip': 25.0}, 'sessions': [],
        }
        conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', '2026-01-15', 'daily_report', json.dumps(daily), now),
        )
        conn.commit()
        conn.close()

        app = create_app(db_path)
        app.config['TESTING'] = True
        client = app.test_client()

        resp = client.get('/cash/overview')
        html = resp.data.decode()
        self.assertNotIn('leak-summary-card', html)
        self.assertNotIn('id="leak-summary-modal"', html)

        os.unlink(db_path)
        os.rmdir(tmpdir)

    def test_health_score_without_leaks_still_shows_grade(self):
        """Health score exists but no leaks → still shows grade card."""
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, 'analytics.db')

        conn = sqlite3.connect(db_path)
        init_analytics_db(conn)
        now = '2026-03-11T12:00:00'
        summary = {'total_hands': 500, 'total_net': 100.0, 'total_days': 5}
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'summary', json.dumps(summary), now),
        )
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_value, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'health_score', 95, now),
        )
        daily = {
            'date': '2026-01-15', 'net': 100.0, 'total_hands': 500,
            'hands_count': 500, 'day_stats': {'vpip': 25.0}, 'sessions': [],
        }
        conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', '2026-01-15', 'daily_report', json.dumps(daily), now),
        )
        conn.commit()
        conn.close()

        app = create_app(db_path)
        app.config['TESTING'] = True
        client = app.test_client()

        resp = client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('leak-summary-card', html)
        self.assertIn('A+', html)
        self.assertIn('0 leaks', html)

        os.unlink(db_path)
        os.rmdir(tmpdir)

    def test_leak_suggestions_displayed(self):
        """Verify leak suggestions appear in the modal."""
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, 'analytics.db')
        _create_analytics_db_with_leaks(db_path, 'cash')

        app = create_app(db_path)
        app.config['TESTING'] = True
        client = app.test_client()

        resp = client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('Reduzir range UTG', html)
        self.assertIn('Defender mais vs 3-bets', html)

        os.unlink(db_path)
        os.rmdir(tmpdir)


# ── CSS Tests ────────────────────────────────────────────────────


class TestLeakSummaryCSS(unittest.TestCase):
    """Test CSS styles for leak summary modal."""

    def test_css_contains_modal_styles(self):
        css_path = os.path.join(
            os.path.dirname(__file__), '..', 'src', 'web', 'static', 'css', 'style.css'
        )
        with open(css_path) as f:
            css = f.read()

        # Key classes present
        self.assertIn('.leak-summary-card', css)
        self.assertIn('.leak-modal-overlay', css)
        self.assertIn('.leak-modal', css)
        self.assertIn('.leak-modal-header', css)
        self.assertIn('.leak-modal-tabs', css)
        self.assertIn('.leak-modal-tab', css)
        self.assertIn('.leak-modal-panel', css)
        self.assertIn('.grade-card', css)
        self.assertIn('.grade-letter', css)
        self.assertIn('.grade-good', css)
        self.assertIn('.grade-warning', css)
        self.assertIn('.grade-danger', css)
        self.assertIn('.badge-text-good', css)
        self.assertIn('.badge-text-warning', css)
        self.assertIn('.badge-text-danger', css)
        self.assertIn('.stat-hint', css)
        self.assertIn('.leak-modal-close', css)
        self.assertIn('.leak-modal-section', css)
        self.assertIn('.leak-modal-section-title', css)

    def test_css_slideup_animation(self):
        css_path = os.path.join(
            os.path.dirname(__file__), '..', 'src', 'web', 'static', 'css', 'style.css'
        )
        with open(css_path) as f:
            css = f.read()
        self.assertIn('@keyframes slideUp', css)

    def test_css_responsive_modal(self):
        css_path = os.path.join(
            os.path.dirname(__file__), '..', 'src', 'web', 'static', 'css', 'style.css'
        )
        with open(css_path) as f:
            css = f.read()
        self.assertIn('.leak-modal', css)
        # Max-height rule in responsive block
        self.assertIn('max-height: 90vh', css)


if __name__ == '__main__':
    unittest.main()
