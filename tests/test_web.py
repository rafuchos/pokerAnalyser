"""Tests for US-027: Flask Web App – structure, routes, templates, data layer."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from src.web.app import create_app
from src.web.data import load_analytics_data
from src.db.analytics_schema import init_analytics_db


# ── Helpers ──────────────────────────────────────────────────────


def _create_analytics_db(path: str, cash: bool = True, tournament: bool = False):
    """Create an analytics.db with sample data for testing."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_analytics_db(conn)

    now = '2026-03-10T12:00:00'

    if cash:
        # Summary
        summary = {
            'total_hands': 1200,
            'total_net': 350.75,
            'total_days': 10,
            'biggest_win': 120.50,
            'biggest_loss': -85.00,
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'summary', json.dumps(summary), now),
        )

        # Health score
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_value, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'health_score', 78, now),
        )

        # Preflop overall
        preflop = {
            'vpip': 24.5, 'vpip_badge': 'good',
            'pfr': 18.2, 'pfr_badge': 'good',
            'three_bet': 7.1, 'three_bet_badge': 'good',
            'fold_to_3bet': 60.0, 'fold_to_3bet_badge': 'warning',
            'ats': 32.0, 'ats_badge': 'good',
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'preflop_overall', json.dumps(preflop), now),
        )

        # Postflop overall
        postflop = {
            'af': 2.8, 'af_badge': 'good',
            'wtsd': 28.0, 'wtsd_badge': 'good',
            'wsd': 52.0, 'wsd_badge': 'good',
            'cbet': 65.0, 'cbet_badge': 'good',
            'fold_to_cbet': 45.0, 'fold_to_cbet_badge': 'warning',
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'postflop_overall', json.dumps(postflop), now),
        )

        # Daily report
        daily = {
            'date': '2026-01-15',
            'net': 50.25,
            'total_hands': 200,
            'sessions': [
                {'total_hands': 120, 'net': 35.0, 'duration': '1h 30m'},
                {'total_hands': 80, 'net': 15.25, 'duration': '45m'},
            ],
        }
        conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', '2026-01-15', 'daily_report', json.dumps(daily), now),
        )

        # Positional stats
        for pos in ['UTG', 'CO', 'BTN', 'BB']:
            pos_data = {
                'hands': 200, 'vpip': 22.0, 'pfr': 16.0,
                'three_bet': 6.0, 'bb100': 5.5 if pos == 'BTN' else -2.0,
            }
            conn.execute(
                "INSERT INTO positional_stats (game_type, position, stat_name, stat_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ('cash', pos, 'stats', json.dumps(pos_data), now),
            )

        # Stack depth stats
        for tier in ['deep', 'medium', 'shallow']:
            tier_data = {
                'hands': 400, 'vpip': 24.0, 'pfr': 18.0, 'bb100': 3.0,
            }
            conn.execute(
                "INSERT INTO stack_depth_stats (game_type, tier, stat_name, stat_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ('cash', tier, 'stats', json.dumps(tier_data), now),
            )

        # Leaks
        conn.execute(
            "INSERT INTO leak_analysis "
            "(game_type, leak_name, category, stat_name, current_value, "
            "healthy_low, healthy_high, cost_bb100, direction, suggestion, position, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ('cash', 'VPIP too high', 'preflop', 'vpip', 30.0,
             20.0, 27.0, 3.5, 'too_high',
             'Tighten preflop opening range', '', now),
        )

        # Tilt analysis
        conn.execute(
            "INSERT INTO tilt_analysis (game_type, analysis_key, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'session_tilt', json.dumps({
                'total_sessions': 10, 'tilt_sessions': 2,
            }), now),
        )
        conn.execute(
            "INSERT INTO tilt_analysis (game_type, analysis_key, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'hourly', json.dumps({
                'by_hour': {'20': {'hands': 100, 'bb100': 5.0}, '21': {'hands': 80, 'bb100': -3.0}},
            }), now),
        )
        conn.execute(
            "INSERT INTO tilt_analysis (game_type, analysis_key, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'recommendation', json.dumps({
                'message': 'Play shorter sessions', 'ideal_duration': '90 minutes',
            }), now),
        )
        conn.execute(
            "INSERT INTO tilt_analysis (game_type, analysis_key, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'diagnostics', json.dumps({
                'messages': ['Tilt detected in 2 sessions', 'Night sessions underperform'],
            }), now),
        )

        # EV analysis
        ev_data = {
            'bb100_real': 8.5, 'bb100_ev': 6.2,
            'luck_factor': 45.00, 'allin_count': 35,
            'by_stakes': {
                '$0.25/$0.50': {
                    'count': 20, 'real_net': 80.0, 'ev_net': 60.0, 'luck': 20.0,
                },
            },
        }
        conn.execute(
            "INSERT INTO ev_analysis (game_type, analysis_type, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'allin_ev', json.dumps(ev_data), now),
        )

        decision_ev = {
            'by_street': [
                {'street': 'preflop', 'decision': 'raise', 'count': 100, 'total_net': 50.0, 'avg_net': 0.5},
            ],
            'leaks': [
                {'description': 'Folding too much on river vs bet', 'count': 15, 'total_net': -30.0, 'avg_net': -2.0},
            ],
        }
        conn.execute(
            "INSERT INTO ev_analysis (game_type, analysis_type, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'decision_ev', json.dumps(decision_ev), now),
        )

        # Bet sizing
        sizing = {
            'preflop_sizing': [
                {'label': '2-2.5x', 'count': 80, 'pct': 40.0},
                {'label': '2.5-3x', 'count': 120, 'pct': 60.0},
            ],
            'postflop_sizing': [
                {'label': '50-75%', 'count': 90, 'pct': 45.0},
                {'label': '75-100%', 'count': 110, 'pct': 55.0},
            ],
        }
        conn.execute(
            "INSERT INTO bet_sizing_stats (game_type, sizing_key, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'overall', json.dumps(sizing), now),
        )

    if tournament:
        summary = {
            'total_tournaments': 25,
            'total_net': -50.0,
            'total_invested': 500.0,
            'roi': -10.0,
            'total_hands': 800,
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('tournament', 'summary', json.dumps(summary), now),
        )

    conn.commit()
    conn.close()


# ── App Factory Tests ────────────────────────────────────────────


class TestCreateApp(unittest.TestCase):
    """Test Flask app factory."""

    def test_create_app_returns_flask(self):
        app = create_app()
        from flask import Flask
        self.assertIsInstance(app, Flask)

    def test_create_app_sets_config(self):
        app = create_app(analytics_db_path='/tmp/test.db', debug=True)
        self.assertEqual(app.config['ANALYTICS_DB_PATH'], '/tmp/test.db')
        self.assertTrue(app.config['DEBUG'])

    def test_create_app_registers_blueprints(self):
        app = create_app()
        bp_names = [bp.name for bp in app.blueprints.values()]
        self.assertIn('main', bp_names)
        self.assertIn('cash', bp_names)
        self.assertIn('tournament', bp_names)

    def test_context_processor_injects_globals(self):
        app = create_app()
        with app.test_request_context():
            ctx = app.jinja_env.globals
            # context_processor injects into template context, test via client
        client = app.test_client()
        r = client.get('/cash/overview')
        self.assertIn(b'Poker Analyzer', r.data)


# ── Route Tests ──────────────────────────────────────────────────


class TestRoutes(unittest.TestCase):
    """Test Flask route responses."""

    def setUp(self):
        self.app = create_app(analytics_db_path='/tmp/_nonexistent_test.db')
        self.client = self.app.test_client()

    def test_index_redirects_to_cash_overview(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/cash/overview', r.headers['Location'])

    def test_cash_index_redirects(self):
        r = self.client.get('/cash/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/cash/overview', r.headers['Location'])

    def test_tournament_index_redirects(self):
        r = self.client.get('/tournament/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/tournament/overview', r.headers['Location'])

    def test_cash_overview_renders(self):
        r = self.client.get('/cash/overview')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Cash Game Overview', r.data)

    def test_cash_sessions_renders(self):
        r = self.client.get('/cash/sessions')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Cash Sessions', r.data)

    def test_cash_stats_renders(self):
        r = self.client.get('/cash/stats')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Cash Game Stats', r.data)

    def test_cash_leaks_renders(self):
        r = self.client.get('/cash/leaks')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Leak Analysis', r.data)

    def test_cash_ev_renders(self):
        r = self.client.get('/cash/ev')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'EV Analysis', r.data)

    def test_cash_range_renders(self):
        r = self.client.get('/cash/range')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Range Analysis', r.data)

    def test_cash_tilt_renders(self):
        r = self.client.get('/cash/tilt')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tilt Analysis', r.data)

    def test_tournament_overview_renders(self):
        r = self.client.get('/tournament/overview')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tournament Overview', r.data)

    def test_tournament_sessions_renders(self):
        r = self.client.get('/tournament/sessions')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tournament Sessions', r.data)

    def test_tournament_stats_renders(self):
        r = self.client.get('/tournament/stats')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tournament Stats', r.data)

    def test_tournament_leaks_renders(self):
        r = self.client.get('/tournament/leaks')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tournament Leak Analysis', r.data)

    def test_tournament_ev_renders(self):
        r = self.client.get('/tournament/ev')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tournament EV Analysis', r.data)

    def test_tournament_range_renders(self):
        r = self.client.get('/tournament/range')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tournament Range Analysis', r.data)

    def test_tournament_tilt_renders(self):
        r = self.client.get('/tournament/tilt')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tournament Tilt Analysis', r.data)

    def test_invalid_cash_tab_shows_overview(self):
        r = self.client.get('/cash/nonexistent')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Cash Game Overview', r.data)

    def test_invalid_tournament_tab_shows_overview(self):
        r = self.client.get('/tournament/nonexistent')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tournament Overview', r.data)


# ── Template Content Tests ───────────────────────────────────────


class TestTemplateContent(unittest.TestCase):
    """Test templates render correct layout elements."""

    def setUp(self):
        self.app = create_app(analytics_db_path='/tmp/_nonexistent_test.db')
        self.client = self.app.test_client()

    def test_base_template_has_header(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('app-header', html)
        self.assertIn('Poker Analyzer', html)

    def test_base_template_has_main_tabs(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('Cash', html)
        self.assertIn('Torneios', html)

    def test_base_template_has_sub_nav(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('sub-nav', html)
        self.assertIn('Overview', html)
        self.assertIn('Sessions', html)
        self.assertIn('Stats', html)
        self.assertIn('Leaks', html)
        self.assertIn('EV Analysis', html)
        self.assertIn('Range', html)
        self.assertIn('Tilt', html)

    def test_cash_tab_active_class(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        # The Cash main tab should be active
        self.assertIn('main-tab active', html)

    def test_sub_tab_active_class(self):
        r = self.client.get('/cash/stats')
        html = r.data.decode()
        # The Stats sub-tab should be active
        self.assertIn('sub-tab active', html)

    def test_base_template_has_footer(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('app-footer', html)

    def test_static_css_link(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('/static/css/style.css', html)

    def test_static_js_link(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('/static/js/app.js', html)

    def test_empty_state_when_no_data(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('empty-state', html)
        self.assertIn('python main.py analyze', html)


# ── Data Layer Tests ─────────────────────────────────────────────


class TestDataLayer(unittest.TestCase):
    """Test analytics data loading from analytics.db."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmpdir)

    def test_load_nonexistent_db_returns_empty(self):
        data = load_analytics_data('/tmp/_no_such_file.db', 'cash')
        self.assertEqual(data, {})

    def test_load_empty_db_returns_empty_keys(self):
        conn = sqlite3.connect(self.db_path)
        init_analytics_db(conn)
        conn.close()
        data = load_analytics_data(self.db_path, 'cash')
        self.assertEqual(data.get('daily_reports'), [])
        self.assertEqual(data.get('sessions'), {})
        self.assertEqual(data.get('positional'), {})
        self.assertEqual(data.get('leaks'), [])

    def test_load_cash_summary(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('summary', data)
        self.assertEqual(data['summary']['total_hands'], 1200)
        self.assertAlmostEqual(data['summary']['total_net'], 350.75)

    def test_load_health_score(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertEqual(data['health_score'], 78)

    def test_load_preflop_overall(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('preflop_overall', data)
        self.assertAlmostEqual(data['preflop_overall']['vpip'], 24.5)

    def test_load_postflop_overall(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('postflop_overall', data)
        self.assertAlmostEqual(data['postflop_overall']['af'], 2.8)

    def test_load_daily_reports(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertEqual(len(data['daily_reports']), 1)
        self.assertEqual(data['daily_reports'][0]['date'], '2026-01-15')

    def test_load_positional_stats(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('BTN', data['positional'])
        self.assertEqual(data['positional']['BTN']['hands'], 200)

    def test_load_stack_depth(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('deep', data['stack_depth'])
        self.assertEqual(data['stack_depth']['deep']['hands'], 400)

    def test_load_leaks(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertEqual(len(data['leaks']), 1)
        self.assertEqual(data['leaks'][0]['leak_name'], 'VPIP too high')

    def test_load_tilt(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('session_tilt', data['tilt'])
        self.assertEqual(data['tilt']['session_tilt']['tilt_sessions'], 2)

    def test_load_ev_analysis(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('allin_ev', data)
        self.assertAlmostEqual(data['allin_ev']['bb100_real'], 8.5)

    def test_load_decision_ev(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('decision_ev', data)
        self.assertEqual(len(data['decision_ev']['by_street']), 1)

    def test_load_bet_sizing(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('bet_sizing', data)
        self.assertEqual(len(data['bet_sizing']['preflop_sizing']), 2)

    def test_load_tournament_data(self):
        _create_analytics_db(self.db_path, cash=False, tournament=True)
        data = load_analytics_data(self.db_path, 'tournament')
        self.assertIn('summary', data)
        self.assertEqual(data['summary']['total_tournaments'], 25)

    def test_cash_data_isolated_from_tournament(self):
        _create_analytics_db(self.db_path, cash=True, tournament=True)
        cash = load_analytics_data(self.db_path, 'cash')
        tourn = load_analytics_data(self.db_path, 'tournament')
        self.assertIn('total_hands', cash['summary'])
        self.assertIn('total_tournaments', tourn['summary'])


# ── Rendering with Data Tests ────────────────────────────────────


class TestRenderWithData(unittest.TestCase):
    """Test templates render correctly when data is available."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path, cash=True, tournament=True)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmpdir)

    def test_cash_overview_shows_summary(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('1,200', html)
        self.assertIn('350.75', html)

    def test_cash_overview_shows_preflop(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('24.5', html)
        self.assertIn('Stats Compactas', html)

    def test_cash_overview_shows_postflop(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('2.80', html)
        self.assertIn('WTSD', html)

    def test_cash_sessions_shows_daily(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('2026-01-15', html)
        self.assertIn('50.25', html)

    def test_cash_sessions_shows_session_table(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('1h 30m', html)
        self.assertIn('35.00', html)

    def test_cash_stats_shows_positions(self):
        r = self.client.get('/cash/stats')
        html = r.data.decode()
        self.assertIn('BTN', html)
        self.assertIn('UTG', html)

    def test_cash_stats_shows_stack_depth(self):
        r = self.client.get('/cash/stats')
        html = r.data.decode()
        self.assertIn('Deep', html)
        self.assertIn('Medium', html)

    def test_cash_leaks_shows_leak(self):
        r = self.client.get('/cash/leaks')
        html = r.data.decode()
        self.assertIn('VPIP too high', html)
        self.assertIn('3.50', html)
        self.assertIn('Tighten preflop', html)

    def test_cash_leaks_shows_health_score(self):
        r = self.client.get('/cash/leaks')
        html = r.data.decode()
        self.assertIn('78', html)
        self.assertIn('Health Score', html)

    def test_cash_ev_shows_stats(self):
        r = self.client.get('/cash/ev')
        html = r.data.decode()
        self.assertIn('8.50', html)
        self.assertIn('6.20', html)
        self.assertIn('45.00', html)

    def test_cash_ev_shows_by_stakes(self):
        r = self.client.get('/cash/ev')
        html = r.data.decode()
        self.assertIn('$0.25/$0.50', html)

    def test_cash_ev_shows_decision_ev(self):
        r = self.client.get('/cash/ev')
        html = r.data.decode()
        self.assertIn('Decision EV by Street', html)
        self.assertIn('preflop', html)

    def test_cash_ev_shows_ev_leaks(self):
        r = self.client.get('/cash/ev')
        html = r.data.decode()
        self.assertIn('EV Leaks', html)
        self.assertIn('Folding too much on river', html)

    def test_cash_range_shows_sizing(self):
        r = self.client.get('/cash/range')
        html = r.data.decode()
        self.assertIn('Preflop Sizing', html)
        self.assertIn('2-2.5x', html)
        self.assertIn('50-75%', html)

    def test_cash_tilt_shows_session_tilt(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('Session Tilt Detection', html)
        self.assertIn('Tilt Sessions', html)

    def test_cash_tilt_shows_hourly(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('Hourly Performance', html)
        self.assertIn('20:00', html)

    def test_cash_tilt_shows_recommendation(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('Recommendations', html)
        self.assertIn('90 minutes', html)

    def test_cash_tilt_shows_diagnostics(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('Diagnostics', html)
        self.assertIn('Night sessions underperform', html)

    def test_tournament_overview_shows_summary(self):
        r = self.client.get('/tournament/overview')
        html = r.data.decode()
        self.assertIn('25', html)
        self.assertIn('Tournament Overview', html)

    def test_no_empty_state_when_data_present(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertNotIn('empty-state', html)


# ── Static Files Tests ───────────────────────────────────────────


class TestStaticFiles(unittest.TestCase):
    """Test that static files are served correctly."""

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_css_file_served(self):
        r = self.client.get('/static/css/style.css')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'--bg-primary', r.data)

    def test_js_file_served(self):
        r = self.client.get('/static/js/app.js')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'DOMContentLoaded', r.data)

    def test_css_has_dark_theme(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('#0d1117', css)
        self.assertIn('--bg-primary', css)
        self.assertIn('--text-primary', css)

    def test_css_has_responsive(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('@media', css)
        self.assertIn('768px', css)
        self.assertIn('480px', css)


# ── CLI Tests ────────────────────────────────────────────────────


class TestServeCLI(unittest.TestCase):
    """Test the serve CLI subcommand."""

    def test_serve_help(self):
        result = subprocess.run(
            [sys.executable, 'main.py', 'serve', '--help'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('--port', result.stdout)
        self.assertIn('--debug', result.stdout)
        self.assertIn('--no-browser', result.stdout)
        self.assertIn('--analytics-db', result.stdout)

    def test_main_help_includes_serve(self):
        result = subprocess.run(
            [sys.executable, 'main.py', '--help'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('serve', result.stdout)


# ── Responsive Template Tests ────────────────────────────────────


class TestResponsiveLayout(unittest.TestCase):
    """Test that templates use responsive patterns."""

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_viewport_meta_tag(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('viewport', html)
        self.assertIn('width=device-width', html)

    def test_html_lang_attribute(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('lang="pt-BR"', html)


# ── US-028 Overview Dashboard Tests ─────────────────────────────


class TestOverviewDataHelpers(unittest.TestCase):
    """Test data layer helper functions for overview dashboard."""

    def test_classify_health_good(self):
        from src.web.data import _classify_health
        self.assertEqual(_classify_health('vpip', 25.0), 'good')
        self.assertEqual(_classify_health('af', 2.5), 'good')
        self.assertEqual(_classify_health('wtsd', 30.0), 'good')

    def test_classify_health_warning(self):
        from src.web.data import _classify_health
        self.assertEqual(_classify_health('vpip', 19.0), 'warning')
        self.assertEqual(_classify_health('vpip', 33.0), 'warning')

    def test_classify_health_danger(self):
        from src.web.data import _classify_health
        self.assertEqual(_classify_health('vpip', 10.0), 'danger')
        self.assertEqual(_classify_health('vpip', 50.0), 'danger')

    def test_classify_health_none(self):
        from src.web.data import _classify_health
        self.assertEqual(_classify_health('vpip', None), '')

    def test_classify_health_unknown_stat(self):
        from src.web.data import _classify_health
        self.assertEqual(_classify_health('unknown', 50.0), '')

    def test_aggregate_period_basic(self):
        from src.web.data import _aggregate_period
        reports = [
            {'total_hands': 100, 'net': 50.0, 'day_stats': {'vpip': 24.0, 'pfr': 18.0}},
            {'total_hands': 200, 'net': -30.0, 'day_stats': {'vpip': 26.0, 'pfr': 20.0}},
        ]
        result = _aggregate_period(reports)
        self.assertEqual(result['hands'], 300)
        self.assertAlmostEqual(result['net'], 20.0)
        self.assertEqual(result['days'], 2)
        # Weighted average: (24*100 + 26*200) / 300 = 25.33
        self.assertAlmostEqual(result['vpip'], 25.3, places=1)
        # Weighted average: (18*100 + 20*200) / 300 = 19.33
        self.assertAlmostEqual(result['pfr'], 19.3, places=1)

    def test_aggregate_period_missing_stats(self):
        from src.web.data import _aggregate_period
        reports = [{'total_hands': 100, 'net': 10.0}]
        result = _aggregate_period(reports)
        self.assertEqual(result['hands'], 100)
        self.assertIsNone(result['vpip'])
        self.assertEqual(result['vpip_badge'], '')

    def test_aggregate_period_uses_hands_count_key(self):
        from src.web.data import _aggregate_period
        reports = [{'hands_count': 50, 'net': 5.0}]
        result = _aggregate_period(reports)
        self.assertEqual(result['hands'], 50)

    def test_aggregate_period_health_badges(self):
        from src.web.data import _aggregate_period
        reports = [{'total_hands': 100, 'net': 10.0, 'day_stats': {'vpip': 25.0}}]
        result = _aggregate_period(reports)
        self.assertEqual(result['vpip_badge'], 'good')

    def test_filter_reports_year(self):
        from src.web.data import _filter_reports_by_period
        reports = [{'date': '2026-01-01'}, {'date': '2026-06-01'}]
        result = _filter_reports_by_period(reports, 'year')
        self.assertEqual(len(result), 2)

    def test_filter_reports_custom(self):
        from src.web.data import _filter_reports_by_period
        reports = [
            {'date': '2026-01-01'}, {'date': '2026-02-15'}, {'date': '2026-03-01'},
        ]
        result = _filter_reports_by_period(reports, 'custom', '2026-01-01', '2026-02-28')
        self.assertEqual(len(result), 2)

    def test_filter_reports_custom_no_dates(self):
        from src.web.data import _filter_reports_by_period
        reports = [{'date': '2026-01-01'}]
        result = _filter_reports_by_period(reports, 'custom')
        self.assertEqual(len(result), 1)

    def test_build_chart_points_empty(self):
        from src.web.data import _build_chart_points
        self.assertEqual(_build_chart_points([]), '')

    def test_build_chart_points_single(self):
        from src.web.data import _build_chart_points
        result = _build_chart_points([100.0])
        self.assertIn(',', result)

    def test_build_chart_points_multiple(self):
        from src.web.data import _build_chart_points
        result = _build_chart_points([0, 50, 100])
        parts = result.split(' ')
        self.assertEqual(len(parts), 3)

    def test_build_chart_points_constant_values(self):
        from src.web.data import _build_chart_points
        result = _build_chart_points([50, 50, 50])
        self.assertIn(' ', result)


class TestPrepareOverviewData(unittest.TestCase):
    """Test prepare_overview_data function."""

    def test_empty_data(self):
        from src.web.data import prepare_overview_data
        data = {}
        prepare_overview_data(data)
        self.assertEqual(data.get('monthly_stats'), [])
        self.assertEqual(data.get('weekly_stats'), [])
        self.assertEqual(data.get('profit_chart'), {})

    def test_with_daily_reports(self):
        from src.web.data import prepare_overview_data
        data = {
            'summary': {'total_hands': 500, 'total_net': 100.0, 'total_days': 3},
            'preflop_overall': {'vpip': 24.0, 'vpip_badge': 'good', 'pfr': 18.0, 'pfr_badge': 'good'},
            'postflop_overall': {'af': 2.5, 'af_badge': 'good'},
            'daily_reports': [
                {'date': '2026-01-15', 'net': 50.0, 'total_hands': 200,
                 'day_stats': {'vpip': 24.0, 'pfr': 18.0, 'af': 2.5}},
                {'date': '2026-01-20', 'net': 30.0, 'total_hands': 150,
                 'day_stats': {'vpip': 26.0, 'pfr': 20.0, 'af': 3.0}},
                {'date': '2026-02-05', 'net': 20.0, 'total_hands': 150,
                 'day_stats': {'vpip': 22.0, 'pfr': 16.0, 'af': 2.0}},
            ],
        }
        prepare_overview_data(data)

        # Monthly stats
        self.assertEqual(len(data['monthly_stats']), 2)
        self.assertEqual(data['monthly_stats'][0]['period'], '2026-01')
        self.assertEqual(data['monthly_stats'][0]['hands'], 350)
        self.assertEqual(data['monthly_stats'][1]['period'], '2026-02')
        self.assertEqual(data['monthly_stats'][1]['hands'], 150)

        # Weekly stats
        self.assertGreater(len(data['weekly_stats']), 0)

        # Overall row
        self.assertEqual(data['overall_row']['hands'], 500)
        self.assertEqual(data['overall_row']['vpip'], 24.0)
        self.assertEqual(data['overall_row']['vpip_badge'], 'good')

        # Profit chart
        self.assertTrue(data['profit_chart']['points'])
        self.assertEqual(len(data['profit_chart']['values']), 3)
        self.assertAlmostEqual(data['profit_chart']['final'], 100.0)

    def test_active_period_set(self):
        from src.web.data import prepare_overview_data
        data = {'daily_reports': []}
        prepare_overview_data(data, period='3m')
        self.assertEqual(data['active_period'], '3m')

    def test_overall_row_ev_bb100(self):
        from src.web.data import prepare_overview_data
        data = {
            'summary': {'total_hands': 100},
            'preflop_overall': {},
            'postflop_overall': {},
            'allin_ev': {'bb100_ev': 5.5},
            'daily_reports': [{'date': '2026-01-01', 'net': 10.0, 'total_hands': 100}],
        }
        prepare_overview_data(data)
        self.assertAlmostEqual(data['overall_row']['ev_bb100'], 5.5)

    def test_redline_chart(self):
        from src.web.data import prepare_overview_data
        data = {
            'summary': {'total_hands': 100},
            'preflop_overall': {},
            'postflop_overall': {},
            'daily_reports': [{'date': '2026-01-01', 'net': 10.0, 'total_hands': 100}],
            'redline': {
                'cumulative': [
                    {'total': 0, 'showdown': 0, 'non_showdown': 0},
                    {'total': 10, 'showdown': 15, 'non_showdown': -5},
                    {'total': 20, 'showdown': 25, 'non_showdown': -5},
                ],
            },
        }
        prepare_overview_data(data)
        self.assertIn('total_points', data['redline_chart'])
        self.assertIn('showdown_points', data['redline_chart'])
        self.assertIn('non_showdown_points', data['redline_chart'])

    def test_redline_chart_empty(self):
        from src.web.data import prepare_overview_data
        data = {
            'summary': {'total_hands': 100},
            'preflop_overall': {},
            'postflop_overall': {},
            'daily_reports': [{'date': '2026-01-01', 'net': 10.0, 'total_hands': 100}],
        }
        prepare_overview_data(data)
        self.assertEqual(data['redline_chart'], {})

    def test_monthly_stats_with_badges(self):
        from src.web.data import prepare_overview_data
        data = {
            'summary': {'total_hands': 100},
            'preflop_overall': {},
            'postflop_overall': {},
            'daily_reports': [
                {'date': '2026-01-15', 'net': 50.0, 'total_hands': 100,
                 'day_stats': {'vpip': 25.0, 'pfr': 18.0}},
            ],
        }
        prepare_overview_data(data)
        m = data['monthly_stats'][0]
        self.assertAlmostEqual(m['vpip'], 25.0)
        self.assertEqual(m['vpip_badge'], 'good')

    def test_custom_period_filter(self):
        from src.web.data import prepare_overview_data
        data = {
            'summary': {'total_hands': 300},
            'preflop_overall': {},
            'postflop_overall': {},
            'daily_reports': [
                {'date': '2026-01-10', 'net': 10.0, 'total_hands': 100},
                {'date': '2026-02-15', 'net': 20.0, 'total_hands': 100},
                {'date': '2026-03-05', 'net': 30.0, 'total_hands': 100},
            ],
        }
        prepare_overview_data(data, period='custom', from_date='2026-01-01', to_date='2026-02-28')
        self.assertEqual(len(data['monthly_stats']), 2)
        self.assertEqual(data['active_period'], 'custom')
        self.assertEqual(data['custom_from'], '2026-01-01')
        self.assertEqual(data['custom_to'], '2026-02-28')


class TestOverviewRoutes(unittest.TestCase):
    """Test overview routes with data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path, cash=True, tournament=True)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmpdir)

    def test_cash_overview_has_period_filter(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('period-filter', html)
        self.assertIn('Last Month', html)
        self.assertIn('Last 3 Months', html)
        self.assertIn('Full Year', html)
        self.assertIn('Custom', html)

    def test_cash_overview_has_hud_table(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('hud-table', html)
        self.assertIn('VPIP', html)
        self.assertIn('PFR', html)
        self.assertIn('3Bet', html)
        self.assertIn('ATS', html)
        self.assertIn('AF', html)
        self.assertIn('CBet', html)
        self.assertIn('WTSD', html)
        self.assertIn('W$SD', html)
        self.assertIn('EV bb/100', html)

    def test_cash_overview_has_overall_row(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('overall-row', html)
        self.assertIn('Overall', html)

    def test_cash_overview_has_monthly_rows(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('monthly-rows', html)

    def test_cash_overview_has_weekly_rows(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('weekly-rows', html)

    def test_cash_overview_has_view_toggle(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('btn-monthly', html)
        self.assertIn('btn-weekly', html)
        self.assertIn('By Month', html)
        self.assertIn('By Week', html)

    def test_cash_overview_ver_detalhes_link(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('Ver detalhes', html)
        self.assertIn('detail-link', html)

    def test_cash_overview_has_profit_chart(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('Profit Over Time', html)

    def test_cash_overview_has_bb100_card(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('bb/100', html)

    def test_cash_overview_has_health_score_card(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('Health Score', html)
        self.assertIn('78', html)

    def test_cash_overview_shows_summary_values(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('1,200', html)
        self.assertIn('350.75', html)

    def test_cash_overview_hud_shows_stat_values(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('24.5', html)  # VPIP
        self.assertIn('18.2', html)  # PFR
        self.assertIn('2.80', html)  # AF

    def test_cash_overview_hud_shows_health_badges(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('badge-good', html)

    def test_cash_overview_period_filter_param(self):
        r = self.client.get('/cash/overview?period=3m')
        html = r.data.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn('Cash Game Overview', html)

    def test_cash_overview_custom_period(self):
        r = self.client.get('/cash/overview?period=custom&from=2026-01-01&to=2026-12-31')
        self.assertEqual(r.status_code, 200)

    def test_tournament_overview_has_period_filter(self):
        r = self.client.get('/tournament/overview')
        html = r.data.decode()
        self.assertIn('period-filter', html)
        self.assertIn('Full Year', html)

    def test_tournament_overview_has_roi_card(self):
        r = self.client.get('/tournament/overview')
        html = r.data.decode()
        self.assertIn('ROI', html)

    def test_tournament_overview_has_tournaments_card(self):
        r = self.client.get('/tournament/overview')
        html = r.data.decode()
        self.assertIn('Tournaments', html)
        self.assertIn('25', html)

    def test_cash_overview_toggle_script(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('toggleView', html)
        self.assertIn('toggleCustomFilter', html)

    def test_cash_overview_net_profit_label(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('Net Profit', html)

    def test_cash_overview_days_played(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('Days Played', html)


class TestOverviewEmptyState(unittest.TestCase):
    """Test overview empty state."""

    def setUp(self):
        self.app = create_app(analytics_db_path='/tmp/_nonexistent_test.db')
        self.client = self.app.test_client()

    def test_cash_overview_empty_state(self):
        r = self.client.get('/cash/overview')
        html = r.data.decode()
        self.assertIn('empty-state', html)
        self.assertIn('python main.py analyze', html)

    def test_tournament_overview_empty_state(self):
        r = self.client.get('/tournament/overview')
        html = r.data.decode()
        self.assertIn('empty-state', html)


if __name__ == '__main__':
    unittest.main()
