"""Tests for US-034: Session Day Drill-Down – Enhanced Stats Page."""

import json
import os
import sqlite3
import tempfile
import unittest

from src.web.app import create_app
from src.web.data import (
    prepare_session_day,
    _get_global_averages,
    _compute_win_rate_per_hour,
    _build_session_comparison,
)
from src.db.analytics_schema import init_analytics_db


# ── Helpers ──────────────────────────────────────────────────────


def _make_session_data(
    vpip=24.0, pfr=18.0, three_bet=7.0, af=2.8,
    cbet=65.0, fold_to_cbet=42.0, wtsd=28.0, wsd=52.0,
    profit1=35.0, profit2=15.25, duration1=90, duration2=45,
    with_ev=True, with_positional=False, with_top_hands=False,
):
    """Create test data with rich session details for testing."""
    s1_stats = {
        'vpip': vpip, 'vpip_health': 'good',
        'pfr': pfr, 'pfr_health': 'good',
        'three_bet': three_bet, 'three_bet_health': 'good',
        'af': af, 'af_health': 'good',
        'cbet': cbet, 'cbet_health': 'good',
        'wtsd': wtsd, 'wtsd_health': 'good',
        'wsd': wsd, 'wsd_health': 'good',
    }
    if with_positional:
        s1_stats['by_position'] = {
            'BTN': {'vpip': 30.0, 'pfr': 22.0, 'hands': 20, 'bb100': 5.5},
            'CO': {'vpip': 25.0, 'pfr': 18.0, 'hands': 18, 'bb100': 2.0},
            'BB': {'vpip': 20.0, 'pfr': 14.0, 'hands': 22, 'bb100': -3.0},
        }

    s1 = {
        'session_id': 's1',
        'start_time': '2026-01-15T18:00:00',
        'end_time': '2026-01-15T19:30:00',
        'duration_minutes': duration1,
        'profit': profit1, 'hands_count': 120,
        'stats': s1_stats,
        'sparkline': [
            {'hand': 1, 'profit': 0},
            {'hand': 60, 'profit': 20.0},
            {'hand': 120, 'profit': profit1},
        ],
        'biggest_win': {'net': 22.50, 'hero_position': 'BTN', 'hero_cards': 'Ah Kh'},
        'biggest_loss': {'net': -15.00, 'hero_position': 'BB'},
        'ev_data': {
            'total_hands': 120, 'allin_hands': 5,
            'real_net': profit1, 'ev_net': 28.0,
            'luck_factor': 7.0, 'bb100_real': 5.8, 'bb100_ev': 4.7,
            'chart_data': [
                {'hand': 1, 'real': 0, 'ev': 0},
                {'hand': 60, 'real': 20.0, 'ev': 15.0},
                {'hand': 120, 'real': profit1, 'ev': 28.0},
            ],
        } if with_ev else None,
        'leak_summary': [
            {
                'stat_name': 'fold_to_3bet', 'label': 'Fold to 3-Bet',
                'value': 60.0, 'healthy_low': 40, 'healthy_high': 55,
                'cost_bb100': 1.5, 'direction': 'too_high',
                'suggestion': 'Defend more vs 3-bets',
            },
        ],
    }

    if with_top_hands:
        s1['top_hands'] = [
            {'net': 22.50, 'hero_position': 'BTN', 'hero_cards': 'Ah Kh'},
            {'net': 15.00, 'hero_position': 'CO', 'hero_cards': 'Qs Qh'},
            {'net': 8.00, 'hero_position': 'MP'},
            {'net': -15.00, 'hero_position': 'BB', 'hero_cards': '9s 8s'},
            {'net': -10.00, 'hero_position': 'UTG'},
            {'net': -5.00, 'hero_position': 'SB'},
        ]

    s2 = {
        'session_id': 's2',
        'start_time': '2026-01-15T20:00:00',
        'end_time': '2026-01-15T20:45:00',
        'duration_minutes': duration2,
        'profit': profit2, 'hands_count': 80,
        'stats': {'vpip': 26.0, 'pfr': 19.0, 'af': 2.5, 'three_bet': 6.0,
                  'cbet': 60.0, 'wtsd': 25.0, 'wsd': 48.0},
        'sparkline': [],
        'biggest_win': None, 'biggest_loss': None,
        'ev_data': None,
        'leak_summary': [],
    }

    return {
        'daily_reports': [{
            'date': '2026-01-15',
            'net': profit1 + profit2,
            'hands_count': 200,
            'num_sessions': 2,
            'day_stats': {
                'vpip': vpip, 'pfr': pfr, 'three_bet': three_bet,
                'af': af, 'cbet': cbet, 'fold_to_cbet': fold_to_cbet,
                'wtsd': wtsd, 'wsd': wsd,
            },
            'sessions': [s1, s2],
        }],
        # Global stats for comparison
        'preflop_overall': {
            'vpip': 25.0, 'pfr': 19.0, 'three_bet': 8.0,
            'fold_to_3bet': 48.0, 'ats': 35.0,
        },
        'postflop_overall': {
            'af': 2.5, 'cbet': 68.0, 'fold_to_cbet': 44.0,
            'wtsd': 27.0, 'wsd': 53.0,
        },
    }


# ── Unit Tests: Helper Functions ─────────────────────────────────


class TestGetGlobalAverages(unittest.TestCase):
    """Test _get_global_averages helper."""

    def test_merges_preflop_postflop(self):
        data = {
            'preflop_overall': {'vpip': 25.0, 'pfr': 19.0},
            'postflop_overall': {'af': 2.5, 'wtsd': 27.0},
        }
        avgs = _get_global_averages(data)
        self.assertEqual(avgs['vpip'], 25.0)
        self.assertEqual(avgs['af'], 2.5)

    def test_handles_empty_data(self):
        avgs = _get_global_averages({})
        self.assertEqual(avgs, {})

    def test_handles_none_values(self):
        data = {'preflop_overall': {'vpip': None}, 'postflop_overall': {}}
        avgs = _get_global_averages(data)
        self.assertNotIn('vpip', avgs)


class TestComputeWinRatePerHour(unittest.TestCase):
    """Test _compute_win_rate_per_hour helper."""

    def test_positive_rate(self):
        rate = _compute_win_rate_per_hour(30.0, 60)
        self.assertAlmostEqual(rate, 30.0)

    def test_fractional_hour(self):
        rate = _compute_win_rate_per_hour(15.0, 30)
        self.assertAlmostEqual(rate, 30.0)

    def test_zero_duration_returns_none(self):
        rate = _compute_win_rate_per_hour(50.0, 0)
        self.assertIsNone(rate)

    def test_negative_duration_returns_none(self):
        rate = _compute_win_rate_per_hour(50.0, -10)
        self.assertIsNone(rate)

    def test_negative_profit(self):
        rate = _compute_win_rate_per_hour(-20.0, 120)
        self.assertAlmostEqual(rate, -10.0)


class TestBuildSessionComparison(unittest.TestCase):
    """Test _build_session_comparison helper."""

    def test_returns_none_for_single_session(self):
        sessions = [{'vpip_val': 24.0, 'pfr_val': 18.0, 'vpip_badge': 'good',
                      'pfr_badge': 'good', 'profit': 10.0}]
        result = _build_session_comparison(sessions, {})
        self.assertIsNone(result)

    def test_builds_comparison_for_two_sessions(self):
        sessions = [
            {'vpip_val': 24.0, 'vpip_badge': 'good', 'pfr_val': 18.0, 'pfr_badge': 'good',
             'three_bet_val': 7.0, 'three_bet_badge': 'good', 'af_val': 2.8, 'af_badge': 'good',
             'cbet_val': 65.0, 'cbet_badge': 'good', 'wtsd_val': 28.0, 'wtsd_badge': 'good',
             'wsd_val': 52.0, 'wsd_badge': 'good', 'profit': 35.0},
            {'vpip_val': 26.0, 'vpip_badge': 'good', 'pfr_val': 19.0, 'pfr_badge': 'good',
             'three_bet_val': 6.0, 'three_bet_badge': 'warning', 'af_val': 2.5, 'af_badge': 'good',
             'cbet_val': 60.0, 'cbet_badge': 'good', 'wtsd_val': 25.0, 'wtsd_badge': 'good',
             'wsd_val': 48.0, 'wsd_badge': 'warning', 'profit': 15.0},
        ]
        result = _build_session_comparison(sessions, {'vpip': 25.0})
        self.assertIsNotNone(result)
        # 7 stats + 1 profit row = 8 rows
        self.assertEqual(len(result), 8)
        # Check structure
        vpip_row = result[0]
        self.assertEqual(vpip_row['stat'], 'vpip')
        self.assertEqual(len(vpip_row['values']), 2)
        self.assertEqual(vpip_row['values'][0]['value'], 24.0)
        self.assertEqual(vpip_row['values'][1]['value'], 26.0)
        self.assertEqual(vpip_row['global'], 25.0)
        # Last row is profit
        profit_row = result[-1]
        self.assertEqual(profit_row['stat'], 'profit')
        self.assertEqual(profit_row['values'][0]['value'], 35.0)

    def test_global_none_when_missing(self):
        sessions = [
            {'vpip_val': 24.0, 'vpip_badge': '', 'pfr_val': None, 'pfr_badge': '',
             'three_bet_val': None, 'three_bet_badge': '', 'af_val': None, 'af_badge': '',
             'cbet_val': None, 'cbet_badge': '', 'wtsd_val': None, 'wtsd_badge': '',
             'wsd_val': None, 'wsd_badge': '', 'profit': 10.0},
            {'vpip_val': 26.0, 'vpip_badge': '', 'pfr_val': None, 'pfr_badge': '',
             'three_bet_val': None, 'three_bet_badge': '', 'af_val': None, 'af_badge': '',
             'cbet_val': None, 'cbet_badge': '', 'wtsd_val': None, 'wtsd_badge': '',
             'wsd_val': None, 'wsd_badge': '', 'profit': -5.0},
        ]
        result = _build_session_comparison(sessions, {})
        self.assertIsNone(result[0]['global'])


# ── Unit Tests: prepare_session_day enhancements ─────────────────


class TestPrepareSessionDayEnhanced(unittest.TestCase):
    """Test enhanced prepare_session_day (US-034)."""

    def test_global_avgs_added_to_day(self):
        data = _make_session_data()
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        self.assertIn('global_avgs', day)
        self.assertEqual(day['global_avgs']['vpip'], 25.0)
        self.assertEqual(day['global_avgs']['af'], 2.5)

    def test_total_duration_computed(self):
        data = _make_session_data(duration1=90, duration2=45)
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        self.assertEqual(day['total_duration'], 135)
        self.assertEqual(day['total_duration_fmt'], '2h 15m')

    def test_total_duration_short(self):
        data = _make_session_data(duration1=30, duration2=20)
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        self.assertEqual(day['total_duration'], 50)
        self.assertEqual(day['total_duration_fmt'], '50m')

    def test_win_rate_hourly(self):
        data = _make_session_data(profit1=60.0, profit2=0.0, duration1=60, duration2=60)
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        # Total: 60.0 profit / 2 hours = 30.0 $/hr
        self.assertAlmostEqual(day['win_rate_hourly'], 30.0)

    def test_session_win_rate_hourly(self):
        data = _make_session_data(profit1=30.0, duration1=60)
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertAlmostEqual(s1['win_rate_hourly'], 30.0)

    def test_session_bb100_from_ev_data(self):
        data = _make_session_data(with_ev=True)
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertEqual(s1['bb100'], 5.8)

    def test_session_bb100_none_without_ev(self):
        data = _make_session_data(with_ev=False)
        prepare_session_day(data, '2026-01-15')
        s2 = data['session_day']['sessions'][1]
        self.assertIsNone(s2['bb100'])

    def test_vs_global_arrows(self):
        data = _make_session_data(vpip=24.0)
        # Global vpip is 25.0, session vpip is 24.0 → diff is -1.0 → 'down'
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertEqual(s1['vpip_vs_global'], 'down')

    def test_vs_global_same_when_close(self):
        data = _make_session_data(vpip=25.2)
        data['daily_reports'][0]['sessions'][0]['stats']['vpip'] = 25.2
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        # 25.2 vs 25.0 → diff = 0.2 < 0.5 → 'same'
        self.assertEqual(s1['vpip_vs_global'], 'same')

    def test_vs_global_up(self):
        data = _make_session_data()
        data['daily_reports'][0]['sessions'][0]['stats']['vpip'] = 28.0
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        # 28.0 vs 25.0 → diff = 3.0 > 0 → 'up'
        self.assertEqual(s1['vpip_vs_global'], 'up')

    def test_vs_global_empty_without_global(self):
        data = _make_session_data()
        data['preflop_overall'] = {}
        data['postflop_overall'] = {}
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertEqual(s1['vpip_vs_global'], '')

    def test_positional_breakdown(self):
        data = _make_session_data(with_positional=True)
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertEqual(len(s1['positional_breakdown']), 3)
        # Positions follow canonical order: CO, BTN, BB
        positions = [p['position'] for p in s1['positional_breakdown']]
        self.assertEqual(positions, ['CO', 'BTN', 'BB'])
        btn = next(p for p in s1['positional_breakdown'] if p['position'] == 'BTN')
        self.assertEqual(btn['vpip'], 30.0)
        self.assertEqual(btn['bb100'], 5.5)

    def test_no_positional_breakdown_when_empty(self):
        data = _make_session_data()
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertEqual(s1['positional_breakdown'], [])

    def test_top_hands_sorted(self):
        data = _make_session_data(with_top_hands=True)
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertEqual(len(s1['top_wins']), 3)  # 3 positive hands
        self.assertEqual(len(s1['top_losses']), 3)  # 3 negative hands
        # Wins sorted descending
        self.assertEqual(s1['top_wins'][0]['net'], 22.50)
        self.assertEqual(s1['top_wins'][1]['net'], 15.00)
        # Losses sorted ascending (most negative first)
        self.assertEqual(s1['top_losses'][0]['net'], -15.00)

    def test_no_top_hands_when_missing(self):
        data = _make_session_data()
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertEqual(s1['top_wins'], [])
        self.assertEqual(s1['top_losses'], [])

    def test_session_comparison_present_for_multi_session(self):
        data = _make_session_data()
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        self.assertIsNotNone(day['session_comparison'])
        self.assertTrue(len(day['session_comparison']) > 0)

    def test_session_comparison_none_for_single_session(self):
        data = _make_session_data()
        data['daily_reports'][0]['sessions'] = [data['daily_reports'][0]['sessions'][0]]
        data['daily_reports'][0]['num_sessions'] = 1
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        self.assertIsNone(day['session_comparison'])

    def test_larger_sparkline_chart_dimensions(self):
        """Sparkline should use 400x80 viewport (larger than old 200x40)."""
        data = _make_session_data()
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        # Points should be in 400x80 space
        pts = s1['sparkline_points']
        self.assertTrue(len(pts) > 0)
        # First point x should be near padding=4
        parts = pts.split(' ')
        first_x = float(parts[0].split(',')[0])
        self.assertAlmostEqual(first_x, 4.0, places=0)

    def test_larger_ev_chart_dimensions(self):
        """EV chart should use 400x80 viewport (larger than old 200x60)."""
        data = _make_session_data(with_ev=True)
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertIsNotNone(s1['ev_chart'])
        pts = s1['ev_chart']['real_points']
        parts = pts.split(' ')
        # Last point x should be near 400 - padding=4 = 396
        last_x = float(parts[-1].split(',')[0])
        self.assertGreater(last_x, 350)

    def test_backward_compat_basic_fields(self):
        """Existing fields should still be present."""
        data = _make_session_data()
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        # Original fields
        self.assertIn('vpip_val', day)
        self.assertIn('vpip_badge', day)
        self.assertIn('best_session', day)
        self.assertIn('worst_session', day)
        s = day['sessions'][0]
        self.assertIn('index', s)
        self.assertIn('duration_fmt', s)
        self.assertIn('start_fmt', s)
        self.assertIn('leak_count', s)


# ── Route Tests ──────────────────────────────────────────────────


def _create_test_db(path, cash=True):
    """Create analytics DB with session data for US-034 testing."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_analytics_db(conn)
    now = '2026-03-11T12:00:00'

    if cash:
        # Global stats for comparison
        preflop = {'vpip': 25.0, 'pfr': 19.0, 'three_bet': 8.0,
                   'fold_to_3bet': 48.0, 'ats': 35.0}
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'preflop_overall', json.dumps(preflop), now),
        )
        postflop = {'af': 2.5, 'cbet': 68.0, 'fold_to_cbet': 44.0,
                    'wtsd': 27.0, 'wsd': 53.0}
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'postflop_overall', json.dumps(postflop), now),
        )

        # Daily report with 2 sessions
        daily = {
            'date': '2026-01-15',
            'net': 50.25,
            'total_hands': 200, 'hands_count': 200,
            'num_sessions': 2,
            'day_stats': {
                'vpip': 24.5, 'pfr': 18.2, 'three_bet': 7.0,
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
                        'pfr': 17.5, 'pfr_health': 'good',
                        'three_bet': 8.0, 'three_bet_health': 'good',
                        'af': 3.0, 'af_health': 'good',
                        'cbet': 70.0, 'cbet_health': 'good',
                        'wtsd': 30.0, 'wtsd_health': 'good',
                        'wsd': 55.0, 'wsd_health': 'good',
                    },
                    'sparkline': [
                        {'hand': 1, 'profit': 0},
                        {'hand': 60, 'profit': 25.0},
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
                            'value': 60.0, 'healthy_low': 40, 'healthy_high': 55,
                            'cost_bb100': 1.5, 'direction': 'too_high',
                            'suggestion': 'Defend more vs 3-bets',
                        },
                    ],
                },
                {
                    'session_id': 's2',
                    'start_time': '2026-01-15T20:00:00',
                    'end_time': '2026-01-15T20:45:00',
                    'duration_minutes': 45,
                    'profit': 15.25, 'hands_count': 80,
                    'stats': {
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
        }
        conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', '2026-01-15', 'daily_report', json.dumps(daily), now),
        )

    conn.commit()
    conn.close()


class TestSessionDayRouteEnhanced(unittest.TestCase):
    """Test enhanced session day routes (US-034)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_test_db(self.db_path, cash=True)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmpdir)

    def test_renders_ok(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        self.assertEqual(r.status_code, 200)

    def test_shows_duration_card(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Duration', html)
        self.assertIn('2h 15m', html)

    def test_shows_win_rate_hourly(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('$/hr', html)

    def test_shows_global_avg_row(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('global-avg-row', html)
        self.assertIn('global-avg-val', html)

    def test_shows_global_avg_hint(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Global averages', html)

    def test_shows_vs_global_arrows(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('vs-global-arrow', html)

    def test_shows_stack_evolution_label(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Stack Evolution', html)

    def test_shows_larger_sparkline(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('sparkline-large', html)
        self.assertIn('400 80', html)  # viewBox="0 0 400 80"

    def test_shows_larger_ev_chart(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('ev-chart-large', html)

    def test_shows_session_comparison_table(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Session Comparison', html)
        self.assertIn('session-comparison-table', html)

    def test_comparison_has_global_column(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('global-col', html)
        self.assertIn('Global', html)

    def test_comparison_has_session_columns(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('S#1', html)
        self.assertIn('S#2', html)

    def test_comparison_has_stat_rows(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('VPIP', html)
        self.assertIn('Profit', html)

    def test_shows_session_bb100(self):
        """Session with EV data should show bb/100."""
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('bb/100', html)

    def test_back_link_preserved(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Back to Sessions', html)

    def test_not_found_still_works(self):
        r = self.client.get('/cash/sessions/2099-12-31')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('No data found', html)

    def test_original_features_preserved(self):
        """All original features should still render."""
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Session #1', html)
        self.assertIn('Session #2', html)
        self.assertIn('Day Stats', html)
        self.assertIn('Best Session', html)
        self.assertIn('Worst Session', html)
        self.assertIn('Notable Hands', html)
        self.assertIn('Ver Leaks', html)
        self.assertIn('EV vs Real', html)


# ── CSS Tests ────────────────────────────────────────────────────


class TestSessionDayCSS(unittest.TestCase):
    """Test CSS includes US-034 session day styles."""

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_css_has_global_avg_row(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.global-avg-row', css)
        self.assertIn('.global-avg-val', css)

    def test_css_has_global_avg_hint(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.global-avg-hint', css)

    def test_css_has_vs_global_arrow(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.vs-global-arrow', css)
        self.assertIn('.vs-global-arrow.up', css)
        self.assertIn('.vs-global-arrow.down', css)

    def test_css_has_sdc_chart_large(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.sdc-chart-large', css)

    def test_css_has_positional_table(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.sdc-positional', css)
        self.assertIn('.pos-mini-table', css)
        self.assertIn('.pos-label', css)

    def test_css_has_top_hands(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.top-hands-section', css)
        self.assertIn('.top-hands-col', css)
        self.assertIn('.top-hand-row', css)
        self.assertIn('.top-hand-net', css)

    def test_css_has_session_comparison_table(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.session-comparison-table', css)

    def test_css_has_notable_cards(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.notable-cards', css)

    def test_css_has_winrate_bb100(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.sdc-winrate', css)
        self.assertIn('.sdc-bb100', css)


# ── Edge Cases ───────────────────────────────────────────────────


class TestSessionDayEdgeCases(unittest.TestCase):
    """Test edge cases for US-034 enhancements."""

    def test_missing_global_stats(self):
        """Should work without global stats data."""
        data = {
            'daily_reports': [{
                'date': '2026-02-01',
                'net': 10.0, 'hands_count': 50,
                'day_stats': {'vpip': 24.0},
                'sessions': [{
                    'profit': 10.0, 'hands_count': 50,
                    'duration_minutes': 30,
                    'stats': {'vpip': 24.0},
                    'sparkline': [], 'ev_data': None, 'leak_summary': [],
                }],
            }],
        }
        prepare_session_day(data, '2026-02-01')
        day = data['session_day']
        self.assertIsNotNone(day)
        self.assertEqual(day['global_avgs'], {})
        self.assertEqual(day['total_duration'], 30)

    def test_zero_duration_sessions(self):
        data = {
            'daily_reports': [{
                'date': '2026-02-01',
                'net': 10.0, 'hands_count': 50,
                'day_stats': {},
                'sessions': [{
                    'profit': 10.0, 'hands_count': 50,
                    'duration_minutes': 0,
                    'stats': {},
                    'sparkline': [], 'ev_data': None, 'leak_summary': [],
                }],
            }],
        }
        prepare_session_day(data, '2026-02-01')
        day = data['session_day']
        self.assertIsNone(day['win_rate_hourly'])
        s = day['sessions'][0]
        self.assertIsNone(s['win_rate_hourly'])

    def test_no_sessions_at_all(self):
        data = {
            'daily_reports': [{
                'date': '2026-02-01',
                'net': 0, 'hands_count': 0,
                'day_stats': {},
                'sessions': [],
            }],
        }
        prepare_session_day(data, '2026-02-01')
        day = data['session_day']
        self.assertEqual(day['total_duration'], 0)
        self.assertEqual(day['sessions'], [])
        self.assertIsNone(day['session_comparison'])

    def test_single_session_no_comparison(self):
        data = _make_session_data()
        data['daily_reports'][0]['sessions'] = [data['daily_reports'][0]['sessions'][0]]
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        self.assertIsNone(day['session_comparison'])
        self.assertIsNone(day['best_session'])

    def test_none_profit_handled(self):
        """Sessions with None profit should not crash."""
        data = {
            'daily_reports': [{
                'date': '2026-02-01',
                'net': None, 'hands_count': 50,
                'day_stats': {},
                'sessions': [{
                    'profit': None, 'hands_count': 50,
                    'duration_minutes': 60,
                    'stats': {},
                    'sparkline': [], 'ev_data': None, 'leak_summary': [],
                }],
            }],
        }
        prepare_session_day(data, '2026-02-01')
        day = data['session_day']
        self.assertIsNotNone(day)

    def test_top_hands_caps_at_five(self):
        """top_wins and top_losses should have max 5 entries."""
        data = _make_session_data()
        many_hands = [
            {'net': i * 5.0, 'hero_position': 'BTN'}
            for i in range(1, 12)
        ] + [
            {'net': -i * 5.0, 'hero_position': 'BB'}
            for i in range(1, 12)
        ]
        data['daily_reports'][0]['sessions'][0]['top_hands'] = many_hands
        prepare_session_day(data, '2026-01-15')
        s1 = data['session_day']['sessions'][0]
        self.assertLessEqual(len(s1['top_wins']), 5)
        self.assertLessEqual(len(s1['top_losses']), 5)


if __name__ == '__main__':
    unittest.main()
