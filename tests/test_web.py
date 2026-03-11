"""Tests for US-027/US-028/US-029: Flask Web App – structure, routes, templates, data layer."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from src.web.app import create_app
from src.web.data import (
    load_analytics_data,
    prepare_sessions_list,
    prepare_session_day,
)
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

        # Daily report (with rich session data for US-029)
        daily = {
            'date': '2026-01-15',
            'net': 50.25,
            'total_hands': 200,
            'hands_count': 200,
            'num_sessions': 2,
            'day_stats': {
                'total_hands': 200,
                'vpip': 24.5, 'pfr': 18.2, 'three_bet': 7.0,
                'fold_to_3bet': 45.0, 'ats': 32.0,
                'af': 2.8, 'cbet': 65.0, 'fold_to_cbet': 42.0,
                'wtsd': 28.0, 'wsd': 52.0,
            },
            'sessions': [
                {
                    'session_id': 's1', 'start_time': '2026-01-15T18:00:00',
                    'end_time': '2026-01-15T19:30:00', 'duration_minutes': 90,
                    'buy_in': 50.0, 'cash_out': 85.0, 'profit': 35.0,
                    'hands_count': 120,
                    'stats': {
                        'total_hands': 120,
                        'vpip': 23.0, 'vpip_health': 'good',
                        'pfr': 17.5, 'pfr_health': 'good',
                        'three_bet': 8.0, 'three_bet_health': 'good',
                        'af': 3.0, 'af_health': 'good',
                        'cbet': 70.0, 'cbet_health': 'good',
                        'wtsd': 30.0, 'wtsd_health': 'good',
                        'wsd': 55.0, 'wsd_health': 'good',
                    },
                    'sparkline': [
                        {'hand': 1, 'profit': 0},
                        {'hand': 30, 'profit': 10.0},
                        {'hand': 60, 'profit': 25.0},
                        {'hand': 90, 'profit': 20.0},
                        {'hand': 120, 'profit': 35.0},
                    ],
                    'biggest_win': {'net': 22.50, 'hero_position': 'BTN'},
                    'biggest_loss': {'net': -15.00, 'hero_position': 'BB'},
                    'ev_data': {
                        'total_hands': 120, 'allin_hands': 5,
                        'real_net': 35.0, 'ev_net': 28.0,
                        'luck_factor': 7.0, 'bb100_real': 5.8, 'bb100_ev': 4.7,
                        'chart_data': [
                            {'hand': 1, 'real': 0, 'ev': 0},
                            {'hand': 60, 'real': 20.0, 'ev': 15.0},
                            {'hand': 120, 'real': 35.0, 'ev': 28.0},
                        ],
                    },
                    'leak_summary': [
                        {
                            'stat_name': 'fold_to_3bet', 'label': 'Fold to 3-Bet',
                            'value': 60.0, 'health': 'warning',
                            'healthy_low': 40.0, 'healthy_high': 55.0,
                            'cost_bb100': 1.5, 'direction': 'too_high',
                            'suggestion': 'Defend more vs 3-bets',
                        },
                    ],
                },
                {
                    'session_id': 's2', 'start_time': '2026-01-15T20:00:00',
                    'end_time': '2026-01-15T20:45:00', 'duration_minutes': 45,
                    'buy_in': 50.0, 'cash_out': 65.25, 'profit': 15.25,
                    'hands_count': 80,
                    'stats': {
                        'total_hands': 80,
                        'vpip': 26.0, 'vpip_health': 'good',
                        'pfr': 19.0, 'pfr_health': 'good',
                        'three_bet': 6.0, 'three_bet_health': 'warning',
                        'af': 2.5, 'af_health': 'good',
                        'cbet': 60.0, 'cbet_health': 'good',
                        'wtsd': 25.0, 'wtsd_health': 'good',
                        'wsd': 48.0, 'wsd_health': 'warning',
                    },
                    'sparkline': [
                        {'hand': 1, 'profit': 0},
                        {'hand': 40, 'profit': 8.0},
                        {'hand': 80, 'profit': 15.25},
                    ],
                    'biggest_win': {'net': 12.00, 'hero_position': 'CO'},
                    'biggest_loss': {'net': -8.50, 'hero_position': 'SB'},
                    'ev_data': None,
                    'leak_summary': [],
                },
            ],
            'comparison': {
                'profit': {'best': 0, 'worst': 1},
                'vpip': {'best': 0, 'worst': 1},
            },
        }
        conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', '2026-01-15', 'daily_report', json.dumps(daily), now),
        )

        # Second daily report for pagination testing
        daily2 = {
            'date': '2026-01-20',
            'net': -25.50,
            'total_hands': 100,
            'hands_count': 100,
            'num_sessions': 1,
            'day_stats': {
                'total_hands': 100,
                'vpip': 30.0, 'pfr': 22.0, 'three_bet': 5.0,
                'af': 1.8, 'cbet': 55.0, 'fold_to_cbet': 50.0,
                'wtsd': 35.0, 'wsd': 45.0,
            },
            'sessions': [
                {
                    'session_id': 's3', 'start_time': '2026-01-20T21:00:00',
                    'end_time': '2026-01-20T22:00:00', 'duration_minutes': 60,
                    'buy_in': 50.0, 'cash_out': 24.50, 'profit': -25.50,
                    'hands_count': 100,
                    'stats': {
                        'total_hands': 100,
                        'vpip': 30.0, 'pfr': 22.0, 'three_bet': 5.0,
                        'af': 1.8, 'cbet': 55.0,
                        'wtsd': 35.0, 'wsd': 45.0,
                    },
                    'sparkline': [],
                    'biggest_win': None,
                    'biggest_loss': None,
                    'ev_data': None,
                    'leak_summary': [
                        {
                            'stat_name': 'vpip', 'label': 'VPIP',
                            'value': 30.0, 'health': 'warning',
                            'healthy_low': 22.0, 'healthy_high': 30.0,
                            'cost_bb100': 2.5, 'direction': 'too_high',
                            'suggestion': 'Tighten opening range',
                        },
                        {
                            'stat_name': 'af', 'label': 'AF',
                            'value': 1.8, 'health': 'warning',
                            'healthy_low': 2.0, 'healthy_high': 3.5,
                            'cost_bb100': 1.0, 'direction': 'too_low',
                            'suggestion': 'Be more aggressive postflop',
                        },
                    ],
                },
            ],
        }
        conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', '2026-01-20', 'daily_report', json.dumps(daily2), now),
        )

        # Positional stats (enriched for US-030)
        _pos_bb100 = {'UTG': -2.0, 'CO': 3.5, 'BTN': 5.5, 'BB': -4.0}
        for pos in ['UTG', 'CO', 'BTN', 'BB']:
            pos_data = {
                'total_hands': 200, 'hands': 200,
                'vpip': 22.0, 'vpip_health': 'good',
                'pfr': 16.0, 'pfr_health': 'warning',
                'three_bet': 6.0, 'three_bet_health': 'warning',
                'af': 2.5, 'af_health': 'good',
                'cbet': 65.0, 'cbet_health': 'good',
                'fold_to_cbet': 42.0, 'fold_to_cbet_health': 'good',
                'wtsd': 28.0, 'wtsd_health': 'good',
                'wsd': 52.0, 'wsd_health': 'good',
                'net': 50.0 if pos == 'BTN' else -20.0,
                'bb_per_100': _pos_bb100[pos],
                'bb100': _pos_bb100[pos],
                'ats': 35.0 if pos in ('CO', 'BTN') else None,
                'ats_opps': 40 if pos in ('CO', 'BTN') else 0,
                'ats_count': 14 if pos in ('CO', 'BTN') else 0,
            }
            conn.execute(
                "INSERT INTO positional_stats (game_type, position, stat_name, stat_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ('cash', pos, 'stats', json.dumps(pos_data), now),
            )

        # Postflop by street (US-030)
        by_street = {
            'flop': {'af': 3.0, 'afq': 55.0, 'cbet': 65.0, 'check_raise': 8.0},
            'turn': {'af': 2.5, 'afq': 48.0, 'cbet': 50.0, 'check_raise': 6.0},
            'river': {'af': 2.0, 'afq': 40.0, 'cbet': None, 'check_raise': 5.0},
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'postflop_by_street', json.dumps(by_street), now),
        )

        # Postflop by week (US-030)
        by_week = {
            '2026-W03': {'af': 2.8, 'cbet': 65.0, 'wtsd': 28.0, 'wsd': 52.0},
            '2026-W04': {'af': 2.5, 'cbet': 60.0, 'wtsd': 30.0, 'wsd': 50.0},
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'postflop_by_week', json.dumps(by_week), now),
        )

        # Positional radar (US-030) – needs ≥3 positions for polygon
        radar = {'UTG': 40, 'CO': 65, 'BTN': 80, 'BB': 30}
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'positional_radar', json.dumps(radar), now),
        )

        # Blinds defense (US-030)
        blinds_defense = {
            'BB': {'fold_to_steal': 55.0, 'three_bet_vs_steal': 12.0,
                   'call_vs_steal': 33.0, 'total_opps': 60},
            'SB': {'fold_to_steal': 65.0, 'three_bet_vs_steal': 10.0,
                   'call_vs_steal': 25.0, 'total_opps': 45},
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'positional_blinds_defense', json.dumps(blinds_defense), now),
        )

        # ATS by position (US-030)
        ats_by_pos = {
            'CO': {'ats': 32.0, 'ats_opps': 50, 'ats_count': 16},
            'BTN': {'ats': 40.0, 'ats_opps': 55, 'ats_count': 22},
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'positional_ats_by_pos', json.dumps(ats_by_pos), now),
        )

        # Stack depth stats (enriched for US-030)
        _tier_bb100 = {'deep': 5.0, 'medium': 3.0, 'shallow': -1.0, 'shove': -5.0}
        _tier_labels = {'deep': '50+ BB', 'medium': '25-50 BB',
                        'shallow': '15-25 BB', 'shove': '<15 BB'}
        for tier in ['deep', 'medium', 'shallow', 'shove']:
            tier_data = {
                'total_hands': 300, 'hands': 300,
                'label': _tier_labels[tier],
                'vpip': 24.0, 'vpip_health': 'good',
                'pfr': 18.0, 'pfr_health': 'good',
                'three_bet': 7.0, 'three_bet_health': 'good',
                'af': 2.5, 'af_health': 'good',
                'cbet': 65.0, 'cbet_health': 'good',
                'wtsd': 28.0, 'wtsd_health': 'good',
                'wsd': 52.0, 'wsd_health': 'good',
                'bb_per_100': _tier_bb100[tier],
                'bb100': _tier_bb100[tier],
            }
            conn.execute(
                "INSERT INTO stack_depth_stats (game_type, tier, stat_name, stat_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ('cash', tier, 'stats', json.dumps(tier_data), now),
            )

        # Stack depth cross table (US-030)
        cross_table = {
            'BTN': {
                'deep': {'total_hands': 50, 'bb_per_100': 8.0},
                'medium': {'total_hands': 30, 'bb_per_100': 3.0},
            },
            'CO': {
                'deep': {'total_hands': 40, 'bb_per_100': 4.0},
                'medium': {'total_hands': 25, 'bb_per_100': 1.0},
            },
        }
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'stack_depth_cross_table', json.dumps(cross_table), now),
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

        # Tournament preflop overall (US-030)
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('tournament', 'preflop_overall', json.dumps({
                'vpip': 26.0, 'vpip_badge': 'good',
                'pfr': 20.0, 'pfr_badge': 'good',
                'three_bet': 8.0, 'three_bet_badge': 'good',
                'fold_to_3bet': 50.0, 'fold_to_3bet_badge': 'good',
                'ats': 34.0, 'ats_badge': 'good',
            }), now),
        )

        # Tournament postflop overall (US-030)
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('tournament', 'postflop_overall', json.dumps({
                'af': 3.0, 'af_badge': 'good',
                'cbet': 68.0, 'cbet_badge': 'good',
                'fold_to_cbet': 40.0, 'fold_to_cbet_badge': 'good',
                'wtsd': 27.0, 'wtsd_badge': 'good',
                'wsd': 54.0, 'wsd_badge': 'good',
            }), now),
        )

        # Tournament positional stats (US-030)
        for pos in ['UTG', 'CO', 'BTN', 'BB']:
            conn.execute(
                "INSERT INTO positional_stats (game_type, position, stat_name, stat_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ('tournament', pos, 'stats', json.dumps({
                    'total_hands': 150, 'vpip': 25.0, 'pfr': 18.0,
                    'three_bet': 7.0, 'af': 2.8, 'cbet': 65.0,
                    'wtsd': 27.0, 'wsd': 53.0,
                    'bb_per_100': 4.0 if pos == 'BTN' else -1.0,
                }), now),
            )

        # Tournament stack depth stats (US-030)
        for tier in ['deep', 'medium', 'shallow']:
            conn.execute(
                "INSERT INTO stack_depth_stats (game_type, tier, stat_name, stat_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ('tournament', tier, 'stats', json.dumps({
                    'total_hands': 250, 'label': tier.title(),
                    'vpip': 25.0, 'pfr': 19.0, 'three_bet': 7.5,
                    'af': 2.7, 'cbet': 63.0, 'wtsd': 29.0, 'wsd': 51.0,
                    'bb_per_100': 2.0,
                }), now),
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
        self.assertEqual(len(data['daily_reports']), 2)
        dates = [r['date'] for r in data['daily_reports']]
        self.assertIn('2026-01-15', dates)
        self.assertIn('2026-01-20', dates)

    def test_load_positional_stats(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('BTN', data['positional'])
        self.assertEqual(data['positional']['BTN']['hands'], 200)

    def test_load_stack_depth(self):
        _create_analytics_db(self.db_path)
        data = load_analytics_data(self.db_path, 'cash')
        self.assertIn('deep', data['stack_depth'])
        self.assertEqual(data['stack_depth']['deep']['total_hands'], 300)

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

    def test_cash_sessions_shows_day_stats(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        # Sessions list shows VPIP/PFR/AF for each day
        self.assertIn('VPIP', html)
        self.assertIn('PFR', html)
        self.assertIn('AF', html)

    def test_cash_stats_shows_positions(self):
        r = self.client.get('/cash/stats?sub=preflop')
        html = r.data.decode()
        self.assertIn('BTN', html)
        self.assertIn('UTG', html)

    def test_cash_stats_shows_stack_depth(self):
        r = self.client.get('/cash/stats?sub=stackdepth')
        html = r.data.decode()
        self.assertIn('50+ BB', html)
        self.assertIn('25-50 BB', html)

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

    def test_cash_range_shows_matrix(self):
        r = self.client.get('/cash/range')
        html = r.data.decode()
        self.assertIn('Hand Matrix', html)
        self.assertIn('hand-matrix', html)

    def test_cash_sizing_shows_data(self):
        r = self.client.get('/cash/sizing')
        html = r.data.decode()
        self.assertIn('Preflop Sizing', html)
        self.assertIn('2-2.5x', html)
        self.assertIn('50-75%', html)

    def test_cash_tilt_shows_session_tilt(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('Sessions Analyzed', html)
        self.assertIn('Tilt Sessions', html)

    def test_cash_tilt_shows_hourly(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('Hourly Performance', html)
        self.assertIn('20:00', html)

    def test_cash_tilt_shows_recommendation(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('Ideal Session Recommendation', html)
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


# ── US-029 Sessions Data Helpers Tests ───────────────────────────


class TestPrepareSessionsList(unittest.TestCase):
    """Test prepare_sessions_list function."""

    def _make_data(self, num_days=3):
        reports = []
        for i in range(num_days):
            reports.append({
                'date': f'2026-01-{15 + i:02d}',
                'net': 10.0 * (i + 1),
                'hands_count': 100 * (i + 1),
                'num_sessions': i + 1,
                'day_stats': {
                    'vpip': 24.0, 'pfr': 18.0, 'three_bet': 7.0,
                    'fold_to_3bet': 45.0, 'ats': 32.0,
                    'af': 2.8, 'cbet': 65.0, 'fold_to_cbet': 42.0,
                    'wtsd': 28.0, 'wsd': 52.0,
                },
                'sessions': [{'leak_summary': []}] * (i + 1),
            })
        return {'daily_reports': reports}

    def test_basic_pagination(self):
        data = self._make_data(3)
        prepare_sessions_list(data, page=1, per_page=2)
        self.assertEqual(len(data['sessions_days']), 2)
        self.assertEqual(data['sessions_page'], 1)
        self.assertEqual(data['sessions_total_pages'], 2)

    def test_second_page(self):
        data = self._make_data(3)
        prepare_sessions_list(data, page=2, per_page=2)
        self.assertEqual(len(data['sessions_days']), 1)
        self.assertEqual(data['sessions_page'], 2)

    def test_page_out_of_range_clamps(self):
        data = self._make_data(3)
        prepare_sessions_list(data, page=99, per_page=2)
        self.assertEqual(data['sessions_page'], 2)

    def test_page_zero_clamps_to_one(self):
        data = self._make_data(3)
        prepare_sessions_list(data, page=0, per_page=2)
        self.assertEqual(data['sessions_page'], 1)

    def test_health_badges_added(self):
        data = self._make_data(1)
        prepare_sessions_list(data)
        day = data['sessions_days'][0]
        self.assertEqual(day['vpip_val'], 24.0)
        self.assertEqual(day['vpip_badge'], 'good')
        self.assertIn(day['health_badge'], ('good', 'warning', 'danger'))

    def test_health_badge_good_when_all_stats_good(self):
        data = self._make_data(1)
        prepare_sessions_list(data)
        day = data['sessions_days'][0]
        self.assertEqual(day['health_badge'], 'good')

    def test_health_badge_danger_when_many_danger(self):
        data = {
            'daily_reports': [{
                'date': '2026-01-15', 'net': 0, 'hands_count': 100,
                'day_stats': {
                    'vpip': 50.0, 'pfr': 50.0, 'three_bet': 50.0,
                    'af': 10.0, 'cbet': 10.0, 'wtsd': 10.0, 'wsd': 10.0,
                    'fold_to_3bet': 90.0, 'ats': 90.0, 'fold_to_cbet': 90.0,
                },
                'sessions': [],
            }],
        }
        prepare_sessions_list(data)
        self.assertEqual(data['sessions_days'][0]['health_badge'], 'danger')

    def test_leak_count_aggregated(self):
        data = {
            'daily_reports': [{
                'date': '2026-01-15', 'net': 0, 'hands_count': 100,
                'day_stats': {},
                'sessions': [
                    {'leak_summary': [{'stat_name': 'vpip'}]},
                    {'leak_summary': [{'stat_name': 'pfr'}, {'stat_name': 'af'}]},
                ],
            }],
        }
        prepare_sessions_list(data)
        self.assertEqual(data['sessions_days'][0]['leak_count'], 3)

    def test_empty_daily_reports(self):
        data = {'daily_reports': []}
        prepare_sessions_list(data)
        self.assertEqual(data['sessions_days'], [])
        self.assertEqual(data['sessions_total_pages'], 1)

    def test_total_days_count(self):
        data = self._make_data(5)
        prepare_sessions_list(data, page=1, per_page=3)
        self.assertEqual(data['sessions_total_days'], 5)


class TestPrepareSessionDay(unittest.TestCase):
    """Test prepare_session_day function."""

    def _make_data(self):
        return {
            'daily_reports': [{
                'date': '2026-01-15',
                'net': 50.25,
                'hands_count': 200,
                'num_sessions': 2,
                'day_stats': {
                    'vpip': 24.0, 'pfr': 18.0, 'three_bet': 7.0,
                    'af': 2.8, 'cbet': 65.0, 'fold_to_cbet': 42.0,
                    'wtsd': 28.0, 'wsd': 52.0,
                },
                'sessions': [
                    {
                        'session_id': 's1',
                        'start_time': '2026-01-15T18:00:00',
                        'end_time': '2026-01-15T19:30:00',
                        'duration_minutes': 90,
                        'profit': 35.0, 'hands_count': 120,
                        'stats': {
                            'vpip': 23.0, 'vpip_health': 'good',
                            'pfr': 17.0, 'af': 3.0,
                        },
                        'sparkline': [
                            {'hand': 1, 'profit': 0},
                            {'hand': 60, 'profit': 20.0},
                            {'hand': 120, 'profit': 35.0},
                        ],
                        'biggest_win': {'net': 22.50, 'hero_position': 'BTN'},
                        'biggest_loss': {'net': -15.00, 'hero_position': 'BB'},
                        'ev_data': {
                            'chart_data': [
                                {'hand': 1, 'real': 0, 'ev': 0},
                                {'hand': 120, 'real': 35.0, 'ev': 28.0},
                            ],
                        },
                        'leak_summary': [
                            {'stat_name': 'fold_to_3bet', 'label': 'Fold to 3-Bet',
                             'value': 60.0, 'cost_bb100': 1.5},
                        ],
                    },
                    {
                        'session_id': 's2',
                        'start_time': '2026-01-15T20:00:00',
                        'end_time': '2026-01-15T20:45:00',
                        'duration_minutes': 45,
                        'profit': 15.25, 'hands_count': 80,
                        'stats': {'vpip': 26.0, 'pfr': 19.0, 'af': 2.5},
                        'sparkline': [],
                        'biggest_win': None, 'biggest_loss': None,
                        'ev_data': None,
                        'leak_summary': [],
                    },
                ],
            }],
        }

    def test_finds_correct_day(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        self.assertIsNotNone(data['session_day'])
        self.assertEqual(data['session_day']['date'], '2026-01-15')

    def test_missing_day_returns_none(self):
        data = self._make_data()
        prepare_session_day(data, '2099-12-31')
        self.assertIsNone(data['session_day'])

    def test_day_health_badges(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        self.assertEqual(day['vpip_val'], 24.0)
        self.assertEqual(day['vpip_badge'], 'good')

    def test_sessions_enriched(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        sessions = data['session_day']['sessions']
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]['index'], 1)
        self.assertEqual(sessions[1]['index'], 2)

    def test_duration_formatting(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        sessions = data['session_day']['sessions']
        self.assertEqual(sessions[0]['duration_fmt'], '1h 30m')
        self.assertEqual(sessions[1]['duration_fmt'], '45m')

    def test_time_formatting(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        sessions = data['session_day']['sessions']
        self.assertEqual(sessions[0]['start_fmt'], '18:00')
        self.assertEqual(sessions[0]['end_fmt'], '19:30')

    def test_session_stats_badges(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        s = data['session_day']['sessions'][0]
        self.assertEqual(s['vpip_val'], 23.0)
        self.assertEqual(s['vpip_badge'], 'good')

    def test_sparkline_points(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertTrue(len(s1['sparkline_points']) > 0)
        self.assertAlmostEqual(s1['sparkline_final'], 35.0)

    def test_empty_sparkline(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        s2 = data['session_day']['sessions'][1]
        self.assertEqual(s2['sparkline_points'], '')

    def test_ev_chart_points(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertIsNotNone(s1['ev_chart'])
        self.assertIn('real_points', s1['ev_chart'])
        self.assertIn('ev_points', s1['ev_chart'])

    def test_no_ev_data(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        s2 = data['session_day']['sessions'][1]
        self.assertIsNone(s2['ev_chart'])

    def test_leak_count(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        s2 = data['session_day']['sessions'][1]
        self.assertEqual(s1['leak_count'], 1)
        self.assertEqual(s2['leak_count'], 0)

    def test_best_worst_session(self):
        data = self._make_data()
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        self.assertEqual(day['best_session'], 0)  # profit 35.0
        self.assertEqual(day['worst_session'], 1)  # profit 15.25

    def test_single_session_no_comparison(self):
        data = {
            'daily_reports': [{
                'date': '2026-01-20',
                'net': 10.0, 'hands_count': 50,
                'day_stats': {},
                'sessions': [{'profit': 10.0, 'hands_count': 50,
                              'stats': {}, 'sparkline': [],
                              'ev_data': None, 'leak_summary': []}],
            }],
        }
        prepare_session_day(data, '2026-01-20')
        day = data['session_day']
        self.assertIsNone(day['best_session'])
        self.assertIsNone(day['worst_session'])


# ── US-029 Route Tests ───────────────────────────────────────────


class TestSessionsRoutes(unittest.TestCase):
    """Test sessions routes with data (US-029)."""

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

    # ── Sessions List ──────────────────────────────────────────

    def test_cash_sessions_renders(self):
        r = self.client.get('/cash/sessions')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Cash Sessions', r.data)

    def test_cash_sessions_shows_day_rows(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('2026-01-15', html)
        self.assertIn('2026-01-20', html)

    def test_cash_sessions_shows_profit(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('+50.25', html)
        self.assertIn('-25.50', html)

    def test_cash_sessions_shows_health_badge(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('badge-', html)

    def test_cash_sessions_shows_stats(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('VPIP', html)
        self.assertIn('PFR', html)
        self.assertIn('AF', html)

    def test_cash_sessions_has_drill_down_link(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('/cash/sessions/2026-01-15', html)

    def test_cash_sessions_pagination_param(self):
        r = self.client.get('/cash/sessions?page=1')
        self.assertEqual(r.status_code, 200)

    def test_cash_sessions_leak_count(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('Leaks', html)

    def test_cash_sessions_hands_count(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('Hands', html)
        self.assertIn('200', html)

    # ── Session Day Drill-Down ─────────────────────────────────

    def test_cash_session_day_renders(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('2026-01-15', html)

    def test_cash_session_day_shows_summary(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Total Hands', html)
        self.assertIn('Net Profit', html)
        self.assertIn('+50.25', html)

    def test_cash_session_day_shows_day_stats(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Day Stats', html)
        self.assertIn('VPIP', html)
        self.assertIn('hud-table', html)

    def test_cash_session_day_shows_session_cards(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Session #1', html)
        self.assertIn('Session #2', html)

    def test_cash_session_day_shows_time(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('18:00', html)
        self.assertIn('19:30', html)

    def test_cash_session_day_shows_duration(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('1h 30m', html)
        self.assertIn('45m', html)

    def test_cash_session_day_shows_session_stats(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('badge-good', html)
        self.assertIn('sdc-stats-table', html)

    def test_cash_session_day_shows_sparkline(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('sparkline-chart', html)
        self.assertIn('Stack', html)

    def test_cash_session_day_shows_ev_chart(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('ev-mini-chart', html)
        self.assertIn('EV vs Real', html)

    def test_cash_session_day_shows_notable_hands(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Notable Hands', html)
        self.assertIn('Biggest Win', html)
        self.assertIn('Biggest Loss', html)
        self.assertIn('+22.50', html)
        self.assertIn('-15.00', html)

    def test_cash_session_day_shows_position_meta(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('BTN', html)

    def test_cash_session_day_shows_leaks_toggle(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Ver Leaks', html)
        self.assertIn('Fold to 3-Bet', html)

    def test_cash_session_day_shows_comparison(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Best Session', html)
        self.assertIn('Worst Session', html)

    def test_cash_session_day_best_worst_markers(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('best-session', html)
        self.assertIn('worst-session', html)

    def test_cash_session_day_back_link(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Back to Sessions', html)
        self.assertIn('/cash/sessions', html)

    def test_cash_session_day_not_found(self):
        r = self.client.get('/cash/sessions/2099-12-31')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('No data found', html)

    # ── Tournament Sessions ────────────────────────────────────

    def test_tournament_sessions_renders(self):
        r = self.client.get('/tournament/sessions')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Tournament Sessions', r.data)

    def test_tournament_session_day_not_found(self):
        r = self.client.get('/tournament/sessions/2099-12-31')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('No data found', html)


# ── US-029 Empty State Tests ────────────────────────────────────


class TestSessionsEmptyState(unittest.TestCase):
    """Test sessions pages with no data."""

    def setUp(self):
        self.app = create_app(analytics_db_path='/tmp/_nonexistent_test.db')
        self.client = self.app.test_client()

    def test_cash_sessions_empty(self):
        r = self.client.get('/cash/sessions')
        html = r.data.decode()
        self.assertIn('empty-state', html)
        self.assertIn('No session data', html)

    def test_tournament_sessions_empty(self):
        r = self.client.get('/tournament/sessions')
        html = r.data.decode()
        self.assertIn('empty-state', html)

    def test_cash_session_day_empty(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('No data found', html)


# ── US-029 CSS Tests ────────────────────────────────────────────


class TestSessionsCSS(unittest.TestCase):
    """Test CSS includes session-related styles."""

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_css_has_session_day_list(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.session-day-list', css)
        self.assertIn('.session-day-row', css)

    def test_css_has_session_detail_card(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.session-detail-card', css)
        self.assertIn('.sdc-header', css)

    def test_css_has_sparkline(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.sparkline-chart', css)

    def test_css_has_comparison_banner(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.comparison-banner', css)
        self.assertIn('.comparison-item', css)

    def test_css_has_notable_hands(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.notable-hand', css)
        self.assertIn('.notable-value', css)

    def test_css_has_pagination(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.pagination', css)

    def test_css_has_ev_chart(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.ev-mini-chart', css)
        self.assertIn('.ev-legend', css)

    def test_css_has_back_link(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.back-link', css)


# ── US-030: Stats Pages Tests ────────────────────────────────────


class TestPrepareStatsData(unittest.TestCase):
    """Test prepare_stats_data() enrichment function."""

    def _make_data(self):
        """Build sample analytics data dict."""
        return {
            'preflop_overall': {
                'vpip': 24.5, 'vpip_badge': 'good',
                'pfr': 18.2, 'pfr_badge': 'good',
                'three_bet': 7.1, 'three_bet_badge': 'good',
                'fold_to_3bet': 60.0, 'fold_to_3bet_badge': 'warning',
                'ats': 32.0, 'ats_badge': 'good',
            },
            'postflop_overall': {
                'af': 2.8, 'af_badge': 'good',
                'afq': 50.0,
                'cbet': 65.0, 'cbet_badge': 'good',
                'fold_to_cbet': 45.0,
                'wtsd': 28.0, 'wtsd_badge': 'good',
                'wsd': 52.0, 'wsd_badge': 'good',
                'check_raise': 8.0,
            },
            'positional': {
                'UTG': {
                    'total_hands': 200, 'vpip': 18.0, 'pfr': 14.0,
                    'three_bet': 5.0, 'af': 2.0, 'cbet': 60.0,
                    'wtsd': 25.0, 'wsd': 50.0,
                    'bb_per_100': -3.0, 'net': -30.0,
                },
                'BTN': {
                    'total_hands': 250, 'vpip': 30.0, 'pfr': 22.0,
                    'three_bet': 9.0, 'af': 3.5, 'cbet': 72.0,
                    'wtsd': 30.0, 'wsd': 55.0,
                    'bb_per_100': 8.0, 'net': 120.0,
                    'ats': 42.0, 'ats_opps': 60, 'ats_count': 25,
                },
            },
            'postflop_by_street': {
                'flop': {'af': 3.0, 'afq': 55.0, 'cbet': 65.0, 'check_raise': 8.0},
                'turn': {'af': 2.5, 'afq': 48.0, 'cbet': 50.0, 'check_raise': 6.0},
                'river': {'af': 2.0, 'afq': 40.0, 'cbet': None, 'check_raise': 5.0},
            },
            'postflop_by_week': {
                '2026-W03': {'af': 2.8, 'cbet': 65.0, 'wtsd': 28.0, 'wsd': 52.0},
                '2026-W04': {'af': 2.5, 'cbet': 60.0, 'wtsd': 30.0, 'wsd': 50.0},
            },
            'positional_radar': {'UTG': 40, 'BTN': 80},
            'positional_blinds_defense': {
                'BB': {'fold_to_steal': 55.0, 'three_bet_vs_steal': 12.0,
                       'call_vs_steal': 33.0, 'total_opps': 60},
            },
            'positional_ats_by_pos': {
                'BTN': {'ats': 42.0, 'ats_opps': 60, 'ats_count': 25},
            },
            'stack_depth': {
                'deep': {
                    'total_hands': 500, 'label': '50+ BB',
                    'vpip': 22.0, 'pfr': 17.0, 'three_bet': 7.0,
                    'af': 2.8, 'cbet': 68.0, 'wtsd': 27.0, 'wsd': 53.0,
                    'bb_per_100': 5.0,
                },
                'medium': {
                    'total_hands': 300, 'label': '25-50 BB',
                    'vpip': 25.0, 'pfr': 19.0, 'three_bet': 8.0,
                    'af': 2.5, 'cbet': 62.0, 'wtsd': 29.0, 'wsd': 50.0,
                    'bb_per_100': 2.0,
                },
            },
            'stack_depth_cross_table': {
                'BTN': {
                    'deep': {'total_hands': 80, 'bb_per_100': 10.0},
                    'medium': {'total_hands': 40, 'bb_per_100': 3.0},
                },
            },
            'daily_reports': [
                {
                    'date': '2026-01-15', 'net': 50.0,
                    'hands_count': 200, 'total_hands': 200,
                    'day_stats': {
                        'vpip': 24.0, 'pfr': 18.0, 'three_bet': 7.0,
                        'af': 2.8, 'cbet': 65.0, 'wtsd': 28.0, 'wsd': 52.0,
                    },
                },
                {
                    'date': '2026-01-20', 'net': -25.0,
                    'hands_count': 100, 'total_hands': 100,
                    'day_stats': {
                        'vpip': 30.0, 'pfr': 22.0, 'three_bet': 5.0,
                        'af': 1.8, 'cbet': 55.0, 'wtsd': 35.0, 'wsd': 45.0,
                    },
                },
            ],
        }

    def test_preflop_overall_stats(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        pf = data['stats_preflop_overall']
        self.assertEqual(len(pf), 7)  # 5 original + open_shove + rbw (US-032)
        self.assertEqual(pf[0]['name'], 'vpip')
        self.assertEqual(pf[0]['value'], 24.5)
        self.assertEqual(pf[0]['badge'], 'good')
        self.assertEqual(pf[0]['label'], 'VPIP')

    def test_preflop_by_position(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        by_pos = data['stats_preflop_by_pos']
        self.assertEqual(len(by_pos), 2)
        positions = [p['position'] for p in by_pos]
        self.assertIn('UTG', positions)
        self.assertIn('BTN', positions)
        btn = [p for p in by_pos if p['position'] == 'BTN'][0]
        self.assertEqual(btn['vpip'], 30.0)
        self.assertEqual(btn['bb100'], 8.0)

    def test_postflop_overall_stats(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        po = data['stats_postflop_overall']
        names = [s['name'] for s in po]
        self.assertIn('af', names)
        self.assertIn('cbet', names)
        self.assertIn('wtsd', names)
        self.assertIn('wsd', names)
        self.assertIn('check_raise', names)

    def test_postflop_by_street(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        by_street = data['stats_postflop_by_street']
        self.assertEqual(len(by_street), 3)
        self.assertEqual(by_street[0]['street'], 'Flop')
        self.assertEqual(by_street[0]['af'], 3.0)
        self.assertEqual(by_street[1]['street'], 'Turn')
        self.assertEqual(by_street[2]['street'], 'River')

    def test_postflop_weekly_trends(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        weekly = data['stats_postflop_weekly']
        self.assertEqual(len(weekly), 2)
        self.assertEqual(weekly[0]['week'], '2026-W03')
        self.assertEqual(weekly[0]['af'], 2.8)

    def test_positional_full_table(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        full = data['stats_positional_full']
        self.assertEqual(len(full), 2)
        btn = [p for p in full if p['position'] == 'BTN'][0]
        self.assertEqual(btn['af'], 3.5)
        self.assertEqual(btn['bb100'], 8.0)
        self.assertEqual(btn['net'], 120.0)

    def test_best_worst_position(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        self.assertEqual(data['stats_best_position']['position'], 'BTN')
        self.assertEqual(data['stats_worst_position']['position'], 'UTG')

    def test_blinds_defense(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        defense = data['stats_blinds_defense']
        self.assertEqual(len(defense), 1)
        self.assertEqual(defense[0]['position'], 'BB')
        self.assertEqual(defense[0]['fold_to_steal'], 55.0)

    def test_ats_by_position(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        ats = data['stats_ats_by_pos']
        self.assertEqual(len(ats), 1)
        self.assertEqual(ats[0]['position'], 'BTN')
        self.assertEqual(ats[0]['ats'], 42.0)

    def test_radar_data(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        # Radar needs at least 3 positions for SVG polygon
        data['positional_radar'] = {'UTG': 40, 'CO': 65, 'BTN': 80}
        prepare_stats_data(data)
        radar = data['stats_radar']
        self.assertIsNotNone(radar)
        self.assertIn('axes', radar)
        self.assertIn('polygon_points', radar)
        self.assertEqual(len(radar['axes']), 3)

    def test_radar_data_too_few_positions(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        data['positional_radar'] = {'UTG': 40, 'BTN': 80}
        prepare_stats_data(data)
        self.assertIsNone(data['stats_radar'])

    def test_tier_rows(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        tiers = data['stats_tier_rows']
        self.assertEqual(len(tiers), 2)
        self.assertEqual(tiers[0]['tier'], 'deep')
        self.assertEqual(tiers[0]['label'], '50+ BB')
        self.assertEqual(tiers[0]['hands'], 500)
        self.assertEqual(tiers[0]['bb100'], 5.0)

    def test_cross_table(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        ct = data['stats_cross_table']
        self.assertIn('BTN', ct)
        self.assertEqual(ct['BTN']['deep']['bb_per_100'], 10.0)

    def test_daily_trends(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        daily = data['stats_daily_trends']
        self.assertEqual(len(daily), 2)
        self.assertEqual(daily[0]['date'], '2026-01-15')
        self.assertEqual(daily[0]['vpip'], 24.0)

    def test_weekly_trends(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data)
        weekly = data['stats_weekly_trends']
        self.assertTrue(len(weekly) >= 1)

    def test_period_filter(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        prepare_stats_data(data, period='1m')
        self.assertEqual(data['active_period'], '1m')

    def test_empty_positional(self):
        from src.web.data import prepare_stats_data
        data = {'positional': {}, 'daily_reports': []}
        prepare_stats_data(data)
        self.assertEqual(data['stats_preflop_by_pos'], [])
        self.assertEqual(data['stats_positional_full'], [])
        self.assertIsNone(data['stats_best_position'])

    def test_empty_stack_depth(self):
        from src.web.data import prepare_stats_data
        data = {'positional': {}, 'daily_reports': [], 'stack_depth': {}}
        prepare_stats_data(data)
        self.assertEqual(data['stats_tier_rows'], [])
        self.assertEqual(data['stats_cross_table'], {})

    def test_health_badges_derived(self):
        from src.web.data import prepare_stats_data
        data = self._make_data()
        # Remove existing health from positional to test derivation
        data['positional']['UTG'] = {
            'total_hands': 200, 'vpip': 40.0, 'pfr': 14.0,
            'three_bet': 5.0, 'bb_per_100': -3.0,
        }
        prepare_stats_data(data)
        by_pos = data['stats_preflop_by_pos']
        utg = [p for p in by_pos if p['position'] == 'UTG'][0]
        self.assertEqual(utg['vpip_badge'], 'danger')


class TestStatsRoutes(unittest.TestCase):
    """Test stats page routes with data."""

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

    def test_cash_stats_default_preflop(self):
        r = self.client.get('/cash/stats')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('stats-subtabs', html)
        self.assertIn('Preflop', html)
        self.assertIn('Postflop', html)
        self.assertIn('Posicional', html)
        self.assertIn('Stack Depth', html)

    def test_cash_stats_preflop_tab(self):
        r = self.client.get('/cash/stats?sub=preflop')
        html = r.data.decode()
        self.assertIn('Overall Preflop Stats', html)
        self.assertIn('Preflop Stats by Position', html)
        self.assertIn('VPIP', html)
        self.assertIn('PFR', html)

    def test_cash_stats_postflop_tab(self):
        r = self.client.get('/cash/stats?sub=postflop')
        html = r.data.decode()
        self.assertIn('Overall Postflop Stats', html)
        self.assertIn('Stats by Street', html)
        self.assertIn('Flop', html)
        self.assertIn('Turn', html)
        self.assertIn('River', html)

    def test_cash_stats_positional_tab(self):
        r = self.client.get('/cash/stats?sub=positional')
        html = r.data.decode()
        self.assertIn('Complete Stats by Position', html)
        self.assertIn('Position Comparison', html)
        self.assertIn('Most Profitable', html)
        self.assertIn('Least Profitable', html)

    def test_cash_stats_positional_has_radar(self):
        r = self.client.get('/cash/stats?sub=positional')
        html = r.data.decode()
        self.assertIn('Positional Radar', html)
        self.assertIn('radar-svg', html)

    def test_cash_stats_positional_has_blinds_defense(self):
        r = self.client.get('/cash/stats?sub=positional')
        html = r.data.decode()
        self.assertIn('Blinds Defense', html)
        self.assertIn('Fold to Steal', html)

    def test_cash_stats_positional_has_ats(self):
        r = self.client.get('/cash/stats?sub=positional')
        html = r.data.decode()
        self.assertIn('Attempt to Steal', html)
        self.assertIn('ATS%', html)

    def test_cash_stats_stackdepth_tab(self):
        r = self.client.get('/cash/stats?sub=stackdepth')
        html = r.data.decode()
        self.assertIn('Stats by Stack Depth', html)
        self.assertIn('50+ BB', html)

    def test_cash_stats_stackdepth_has_cross_table(self):
        r = self.client.get('/cash/stats?sub=stackdepth')
        html = r.data.decode()
        self.assertIn('Position x Stack Depth', html)
        self.assertIn('cross-table', html)

    def test_cash_stats_has_period_filter(self):
        r = self.client.get('/cash/stats')
        html = r.data.decode()
        self.assertIn('period-filter', html)
        self.assertIn('Last Month', html)
        self.assertIn('Full Year', html)

    def test_cash_stats_period_param(self):
        r = self.client.get('/cash/stats?sub=preflop&period=1m')
        html = r.data.decode()
        self.assertEqual(r.status_code, 200)

    def test_cash_stats_has_health_badges(self):
        r = self.client.get('/cash/stats?sub=preflop')
        html = r.data.decode()
        self.assertIn('badge-good', html)

    def test_cash_stats_preflop_has_trends(self):
        r = self.client.get('/cash/stats?sub=preflop')
        html = r.data.decode()
        self.assertIn('Preflop Trends', html)
        self.assertIn('By Day', html)
        self.assertIn('By Week', html)

    def test_cash_stats_postflop_has_weekly(self):
        r = self.client.get('/cash/stats?sub=postflop')
        html = r.data.decode()
        self.assertIn('Postflop Weekly Trends', html)

    def test_tournament_stats_default(self):
        r = self.client.get('/tournament/stats')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('Tournament Stats', html)
        self.assertIn('stats-subtabs', html)

    def test_tournament_stats_preflop(self):
        r = self.client.get('/tournament/stats?sub=preflop')
        html = r.data.decode()
        self.assertIn('Overall Preflop Stats', html)
        self.assertIn('VPIP', html)

    def test_tournament_stats_postflop(self):
        r = self.client.get('/tournament/stats?sub=postflop')
        html = r.data.decode()
        self.assertIn('Overall Postflop Stats', html)

    def test_tournament_stats_positional(self):
        r = self.client.get('/tournament/stats?sub=positional')
        html = r.data.decode()
        self.assertIn('Complete Stats by Position', html)

    def test_tournament_stats_stackdepth(self):
        r = self.client.get('/tournament/stats?sub=stackdepth')
        html = r.data.decode()
        self.assertIn('Stats by Stack Depth', html)


class TestStatsEmptyState(unittest.TestCase):
    """Test stats page empty state."""

    def setUp(self):
        self.app = create_app(analytics_db_path='/tmp/_nonexistent_test_stats.db')
        self.client = self.app.test_client()

    def test_cash_stats_empty(self):
        r = self.client.get('/cash/stats')
        html = r.data.decode()
        self.assertIn('No stats data available', html)

    def test_tournament_stats_empty(self):
        r = self.client.get('/tournament/stats')
        html = r.data.decode()
        self.assertIn('No tournament stats available', html)

    def test_cash_stats_empty_subtab(self):
        r = self.client.get('/cash/stats?sub=postflop')
        html = r.data.decode()
        self.assertIn('No stats data available', html)


class TestStatsCSS(unittest.TestCase):
    """Test CSS includes stats-specific styles."""

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_css_has_stats_subtabs(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.stats-subtabs', css)
        self.assertIn('.stats-subtab', css)

    def test_css_has_stats_panel(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.stats-panel', css)

    def test_css_has_stats_hud_grid(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.stats-hud-grid', css)
        self.assertIn('.stat-hud-card', css)

    def test_css_has_radar(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.radar-chart-container', css)
        self.assertIn('.radar-svg', css)

    def test_css_has_cross_table(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.cross-table', css)
        self.assertIn('.cross-cell', css)

    def test_css_has_table_scroll(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.table-scroll', css)


# ── US-031: Leaks, EV, Range, Tilt, Sizing pages ────────────────


class TestPrepareLeaksData(unittest.TestCase):
    """Test prepare_leaks_data enrichment."""

    def setUp(self):
        from src.web.data import prepare_leaks_data
        self.prepare = prepare_leaks_data
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path)

    def _load(self):
        from src.web.data import load_analytics_data
        return load_analytics_data(self.db_path, 'cash')

    def test_health_score_from_db(self):
        data = self._load()
        self.prepare(data)
        self.assertEqual(data['health_score_val'], 78)
        self.assertEqual(data['health_score_class'], 'good')

    def test_health_score_computed_when_missing(self):
        data = {'leaks': [{'cost_bb100': 5.0}]}
        self.prepare(data)
        self.assertIn('health_score_val', data)
        self.assertLessEqual(data['health_score_val'], 100)
        self.assertGreaterEqual(data['health_score_val'], 0)

    def test_health_score_default_when_no_leaks(self):
        data = {}
        self.prepare(data)
        self.assertEqual(data['health_score_val'], 100)

    def test_top_leaks_sorted_by_cost(self):
        data = self._load()
        self.prepare(data)
        top = data['top_leaks']
        self.assertIsInstance(top, list)
        self.assertTrue(len(top) <= 5)
        if len(top) > 1:
            self.assertGreaterEqual(
                abs(top[0].get('cost_bb100', 0)),
                abs(top[1].get('cost_bb100', 0)),
            )

    def test_study_spots_have_suggestions(self):
        data = self._load()
        self.prepare(data)
        for spot in data.get('study_spots', []):
            self.assertTrue(spot.get('suggestion'))

    def test_period_comparison_has_stats(self):
        data = self._load()
        self.prepare(data)
        comp = data.get('period_comparison', [])
        self.assertIsInstance(comp, list)
        if comp:
            for row in comp:
                self.assertIn('stat', row)
                self.assertIn('label', row)

    def test_active_period_set(self):
        data = self._load()
        self.prepare(data, period='3m')
        self.assertEqual(data['active_period'], '3m')


class TestPrepareEvData(unittest.TestCase):
    """Test prepare_ev_data enrichment."""

    def setUp(self):
        from src.web.data import prepare_ev_data
        self.prepare = prepare_ev_data
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path)

    def _load(self):
        from src.web.data import load_analytics_data
        return load_analytics_data(self.db_path, 'cash')

    def test_ev_summary_populated(self):
        data = self._load()
        self.prepare(data)
        ev = data.get('ev_summary', {})
        self.assertAlmostEqual(ev.get('bb100_real'), 8.5, places=1)
        self.assertAlmostEqual(ev.get('bb100_ev'), 6.2, places=1)

    def test_ev_chart_built(self):
        data = self._load()
        self.prepare(data)
        ec = data.get('ev_chart', {})
        self.assertIn('real_points', ec)
        self.assertIn('ev_points', ec)

    def test_bb_comparison(self):
        data = self._load()
        self.prepare(data)
        bbc = data.get('ev_bb_comparison', {})
        self.assertIn('real', bbc)
        self.assertIn('ev', bbc)
        self.assertIn('diff', bbc)
        expected_diff = round(8.5 - 6.2, 2)
        self.assertAlmostEqual(bbc['diff'], expected_diff, places=2)

    def test_decision_ev_data(self):
        data = self._load()
        self.prepare(data)
        dev = data.get('decision_ev_data', {})
        self.assertIn('by_street', dev)

    def test_active_period_set(self):
        data = self._load()
        self.prepare(data, period='1m')
        self.assertEqual(data['active_period'], '1m')


class TestPrepareRangeData(unittest.TestCase):
    """Test prepare_range_data enrichment."""

    def setUp(self):
        from src.web.data import prepare_range_data
        self.prepare = prepare_range_data
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path)

    def _load(self):
        from src.web.data import load_analytics_data
        return load_analytics_data(self.db_path, 'cash')

    def test_positions_populated(self):
        data = self._load()
        self.prepare(data)
        positions = data.get('range_positions', [])
        self.assertIsInstance(positions, list)
        self.assertTrue(len(positions) > 0)

    def test_hand_ranks(self):
        data = self._load()
        self.prepare(data)
        ranks = data.get('hand_ranks', [])
        self.assertEqual(len(ranks), 13)
        self.assertEqual(ranks[0], 'A')
        self.assertEqual(ranks[-1], '2')

    def test_matrix_13x13(self):
        data = self._load()
        self.prepare(data)
        matrices = data.get('range_matrices', {})
        for pos, matrix in matrices.items():
            self.assertEqual(len(matrix), 13)
            for row in matrix:
                self.assertEqual(len(row), 13)

    def test_matrix_hand_types(self):
        data = self._load()
        self.prepare(data)
        matrices = data.get('range_matrices', {})
        for pos, matrix in matrices.items():
            # Diagonal = pairs
            self.assertEqual(matrix[0][0]['type'], 'pair')
            self.assertEqual(matrix[0][0]['hand'], 'AA')
            # Upper triangle = suited
            self.assertEqual(matrix[0][1]['type'], 'suited')
            self.assertEqual(matrix[0][1]['hand'], 'AKs')
            # Lower triangle = offsuit
            self.assertEqual(matrix[1][0]['type'], 'offsuit')
            self.assertEqual(matrix[1][0]['hand'], 'AKo')
            break

    def test_top_profitable_and_deficit(self):
        data = self._load()
        self.prepare(data)
        self.assertIsInstance(data.get('top_profitable'), list)
        self.assertIsInstance(data.get('top_deficit'), list)


class TestPrepareTiltData(unittest.TestCase):
    """Test prepare_tilt_data enrichment."""

    def setUp(self):
        from src.web.data import prepare_tilt_data
        self.prepare = prepare_tilt_data
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path)

    def _load(self):
        from src.web.data import load_analytics_data
        return load_analytics_data(self.db_path, 'cash')

    def test_session_summary(self):
        data = self._load()
        self.prepare(data)
        summary = data.get('tilt_session_summary', {})
        self.assertEqual(summary.get('total_sessions'), 10)
        self.assertEqual(summary.get('tilt_sessions'), 2)

    def test_heatmap_24_entries(self):
        data = self._load()
        self.prepare(data)
        heatmap = data.get('tilt_heatmap', [])
        self.assertEqual(len(heatmap), 24)

    def test_heatmap_intensity_classification(self):
        data = self._load()
        self.prepare(data)
        heatmap = data.get('tilt_heatmap', [])
        for cell in heatmap:
            self.assertIn(cell['intensity'],
                          ('none', 'neutral', 'warm', 'hot', 'cool', 'cold'))

    def test_heatmap_active_hours(self):
        data = self._load()
        self.prepare(data)
        heatmap = data.get('tilt_heatmap', [])
        # Hours 20 and 21 should have data
        h20 = heatmap[20]
        self.assertEqual(h20['hands'], 100)
        self.assertAlmostEqual(h20['bb100'], 5.0, places=1)
        h21 = heatmap[21]
        self.assertEqual(h21['hands'], 80)
        self.assertAlmostEqual(h21['bb100'], -3.0, places=1)

    def test_heatmap_no_data_hours(self):
        data = self._load()
        self.prepare(data)
        heatmap = data.get('tilt_heatmap', [])
        # Hour 0 should have no data
        self.assertEqual(heatmap[0]['hands'], 0)
        self.assertEqual(heatmap[0]['intensity'], 'none')

    def test_recommendation(self):
        data = self._load()
        self.prepare(data)
        rec = data.get('tilt_recommendation', {})
        self.assertEqual(rec.get('message'), 'Play shorter sessions')
        self.assertEqual(rec.get('ideal_duration'), '90 minutes')


class TestPrepareSizingData(unittest.TestCase):
    """Test prepare_sizing_data enrichment."""

    def setUp(self):
        from src.web.data import prepare_sizing_data
        self.prepare = prepare_sizing_data
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path)

    def _load(self):
        from src.web.data import load_analytics_data
        return load_analytics_data(self.db_path, 'cash')

    def test_preflop_sizing(self):
        data = self._load()
        self.prepare(data)
        pf = data.get('sizing_preflop', [])
        self.assertIsInstance(pf, list)
        self.assertTrue(len(pf) > 0)
        self.assertEqual(pf[0]['label'], '2-2.5x')

    def test_postflop_sizing(self):
        data = self._load()
        self.prepare(data)
        post = data.get('sizing_postflop', [])
        self.assertIsInstance(post, list)
        self.assertTrue(len(post) > 0)

    def test_active_period_set(self):
        data = self._load()
        self.prepare(data, period='1m')
        self.assertEqual(data['active_period'], '1m')


class TestLeaksRoutes(unittest.TestCase):
    """Test leaks page routes for cash and tournament."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path, cash=True, tournament=True)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def test_cash_leaks_200(self):
        r = self.client.get('/cash/leaks')
        self.assertEqual(r.status_code, 200)

    def test_cash_leaks_has_health_bar(self):
        r = self.client.get('/cash/leaks')
        html = r.data.decode()
        self.assertIn('health-bar', html)
        self.assertIn('Health Score', html)

    def test_cash_leaks_has_top_leaks(self):
        r = self.client.get('/cash/leaks')
        html = r.data.decode()
        self.assertIn('Top', html)
        self.assertIn('VPIP too high', html)

    def test_cash_leaks_has_period_filter(self):
        r = self.client.get('/cash/leaks')
        html = r.data.decode()
        self.assertIn('period-filter', html)
        self.assertIn('Last Month', html)

    def test_cash_leaks_period_param(self):
        r = self.client.get('/cash/leaks?period=3m')
        self.assertEqual(r.status_code, 200)

    def test_tournament_leaks_200(self):
        r = self.client.get('/tournament/leaks')
        self.assertEqual(r.status_code, 200)


class TestEvRoutes(unittest.TestCase):
    """Test EV page routes for cash and tournament."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path, cash=True, tournament=True)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def test_cash_ev_200(self):
        r = self.client.get('/cash/ev')
        self.assertEqual(r.status_code, 200)

    def test_cash_ev_has_summary_cards(self):
        r = self.client.get('/cash/ev')
        html = r.data.decode()
        self.assertIn('Real bb/100', html)
        self.assertIn('EV bb/100', html)
        self.assertIn('Luck Factor', html)

    def test_cash_ev_has_decision_tree(self):
        r = self.client.get('/cash/ev')
        html = r.data.decode()
        self.assertIn('Decision EV by Street', html)

    def test_cash_ev_has_ev_leaks(self):
        r = self.client.get('/cash/ev')
        html = r.data.decode()
        self.assertIn('EV Leaks', html)

    def test_cash_ev_has_period_filter(self):
        r = self.client.get('/cash/ev')
        html = r.data.decode()
        self.assertIn('period-filter', html)

    def test_cash_ev_period_param(self):
        r = self.client.get('/cash/ev?period=1m')
        self.assertEqual(r.status_code, 200)

    def test_tournament_ev_200(self):
        r = self.client.get('/tournament/ev')
        self.assertEqual(r.status_code, 200)


class TestRangeRoutes(unittest.TestCase):
    """Test range page routes for cash and tournament."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path, cash=True, tournament=True)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def test_cash_range_200(self):
        r = self.client.get('/cash/range')
        self.assertEqual(r.status_code, 200)

    def test_cash_range_has_matrix(self):
        r = self.client.get('/cash/range')
        html = r.data.decode()
        self.assertIn('hand-matrix', html)
        self.assertIn('Hand Matrix', html)

    def test_cash_range_has_position_tabs(self):
        r = self.client.get('/cash/range')
        html = r.data.decode()
        self.assertIn('stats-subtab', html)

    def test_cash_range_has_period_filter(self):
        r = self.client.get('/cash/range')
        html = r.data.decode()
        self.assertIn('period-filter', html)

    def test_cash_range_pos_param(self):
        r = self.client.get('/cash/range?pos=BTN')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('BTN', html)

    def test_tournament_range_200(self):
        r = self.client.get('/tournament/range')
        self.assertEqual(r.status_code, 200)


class TestTiltRoutes(unittest.TestCase):
    """Test tilt page routes for cash and tournament."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path, cash=True, tournament=True)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def test_cash_tilt_200(self):
        r = self.client.get('/cash/tilt')
        self.assertEqual(r.status_code, 200)

    def test_cash_tilt_has_session_summary(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('Sessions Analyzed', html)

    def test_cash_tilt_has_heatmap(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('heatmap-grid', html)
        self.assertIn('Hourly Performance Heatmap', html)

    def test_cash_tilt_has_recommendation(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('Ideal Session Recommendation', html)
        self.assertIn('Play shorter sessions', html)

    def test_cash_tilt_has_period_filter(self):
        r = self.client.get('/cash/tilt')
        html = r.data.decode()
        self.assertIn('period-filter', html)

    def test_cash_tilt_period_param(self):
        r = self.client.get('/cash/tilt?period=3m')
        self.assertEqual(r.status_code, 200)

    def test_tournament_tilt_200(self):
        r = self.client.get('/tournament/tilt')
        self.assertEqual(r.status_code, 200)


class TestSizingRoutes(unittest.TestCase):
    """Test sizing page routes for cash and tournament."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db(self.db_path, cash=True, tournament=True)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def test_cash_sizing_200(self):
        r = self.client.get('/cash/sizing')
        self.assertEqual(r.status_code, 200)

    def test_cash_sizing_has_preflop(self):
        r = self.client.get('/cash/sizing')
        html = r.data.decode()
        self.assertIn('Preflop Sizing', html)

    def test_cash_sizing_has_postflop(self):
        r = self.client.get('/cash/sizing')
        html = r.data.decode()
        self.assertIn('Postflop Sizing', html)

    def test_cash_sizing_has_sizing_bar(self):
        r = self.client.get('/cash/sizing')
        html = r.data.decode()
        self.assertIn('sizing-bar', html)

    def test_cash_sizing_has_period_filter(self):
        r = self.client.get('/cash/sizing')
        html = r.data.decode()
        self.assertIn('period-filter', html)

    def test_tournament_sizing_200(self):
        r = self.client.get('/tournament/sizing')
        self.assertEqual(r.status_code, 200)


class TestSizingTab(unittest.TestCase):
    """Test sizing tab is properly registered."""

    def test_sizing_in_sub_tabs(self):
        app = create_app()
        with app.test_request_context():
            from flask import g
            ctx = app.jinja_env.globals
        # Check via context processor
        with app.test_client() as client:
            r = client.get('/cash/overview')
            html = r.data.decode()
            self.assertIn('Sizing', html)

    def test_sizing_in_valid_tabs(self):
        from src.web.routes.cash import VALID_TABS
        self.assertIn('sizing', VALID_TABS)

    def test_tournament_sizing_in_valid_tabs(self):
        from src.web.routes.tournament import VALID_TABS
        self.assertIn('sizing', VALID_TABS)


class TestUS031EmptyState(unittest.TestCase):
    """Test empty state rendering for US-031 pages."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'empty.db')
        from src.db.analytics_schema import init_analytics_db
        conn = sqlite3.connect(self.db_path)
        init_analytics_db(conn)
        conn.close()
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def test_leaks_empty_state(self):
        r = self.client.get('/cash/leaks')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('empty-state', html)

    def test_ev_empty_state(self):
        r = self.client.get('/cash/ev')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('empty-state', html)

    def test_range_empty_state(self):
        r = self.client.get('/cash/range')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('empty-state', html)

    def test_tilt_empty_state(self):
        r = self.client.get('/cash/tilt')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('empty-state', html)

    def test_sizing_empty_state(self):
        r = self.client.get('/cash/sizing')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('empty-state', html)


class TestUS031CSS(unittest.TestCase):
    """Test CSS includes US-031 specific styles."""

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_css_has_health_bar(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.health-bar', css)
        self.assertIn('.health-bar-fill', css)
        self.assertIn('.health-good', css)

    def test_css_has_hand_matrix(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.hand-matrix', css)
        self.assertIn('.hm-cell', css)
        self.assertIn('.hm-pair', css)
        self.assertIn('.hm-suited', css)
        self.assertIn('.hm-offsuit', css)

    def test_css_has_heatmap(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.heatmap-grid', css)
        self.assertIn('.heatmap-cell', css)
        self.assertIn('.heatmap-hot', css)
        self.assertIn('.heatmap-cold', css)

    def test_css_has_sizing_bar(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.sizing-bar', css)
        self.assertIn('.sizing-bar-fill', css)


if __name__ == '__main__':
    unittest.main()
