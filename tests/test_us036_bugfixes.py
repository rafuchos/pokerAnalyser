"""Tests for US-036: Bugfix – Data and Rendering fixes across all web pages."""

import unittest

from src.web.data import (
    prepare_ev_data,
    prepare_overview_data,
    prepare_session_day,
    prepare_sessions_list,
    prepare_sizing_data,
    prepare_tilt_data,
)


# ── Helpers ────────────────────────────────────────────────────────


def _make_ev_data(real_net=35.0, ev_net=28.0, total_hands=120, allin_hands=5):
    """Create EV data dict for a session."""
    return {
        'total_hands': total_hands,
        'allin_hands': allin_hands,
        'real_net': real_net,
        'ev_net': ev_net,
        'bb100_real': round(real_net / 0.5 / total_hands * 100, 2) if total_hands else 0,
        'bb100_ev': round(ev_net / 0.5 / total_hands * 100, 2) if total_hands else 0,
        'chart_data': [
            {'hand': 1, 'real': 0, 'ev': 0},
            {'hand': total_hands, 'real': real_net, 'ev': ev_net},
        ],
    }


def _make_session(session_id='s1', profit=35.0, hands=120, duration=90,
                  vpip=24.0, pfr=18.0, ev_data=None):
    """Create a test session dict."""
    return {
        'session_id': session_id,
        'start_time': '2026-01-15T18:00:00',
        'end_time': '2026-01-15T19:30:00',
        'duration_minutes': duration,
        'profit': profit,
        'hands_count': hands,
        'stats': {
            'vpip': vpip, 'pfr': pfr,
            'three_bet': 7.0, 'af': 2.8,
            'cbet': 65.0, 'fold_to_cbet': 42.0,
            'wtsd': 28.0, 'wsd': 52.0,
        },
        'sparkline': [{'hand': 1, 'profit': 0}, {'hand': hands, 'profit': profit}],
        'ev_data': ev_data,
        'leak_summary': [],
    }


def _make_daily_report(date='2026-01-15', net=50.25, sessions=None, ev_net=None):
    """Create a daily report dict."""
    if sessions is None:
        sessions = [
            _make_session('s1', profit=35.0, ev_data=_make_ev_data(35.0, 28.0)),
            _make_session('s2', profit=15.25, hands=80, ev_data=None),
        ]
    total_hands = sum(s.get('hands_count', 0) for s in sessions)
    report = {
        'date': date,
        'net': net,
        'hands_count': total_hands,
        'total_hands': total_hands,
        'day_stats': {
            'vpip': 24.5, 'pfr': 18.0, 'three_bet': 7.5,
            'af': 2.7, 'cbet': 64.0, 'fold_to_cbet': 42.0,
            'wtsd': 27.5, 'wsd': 51.0,
        },
        'sessions': sessions,
    }
    if ev_net is not None:
        report['ev_net'] = ev_net
    return report


def _make_analytics_data(daily_reports=None, allin_ev=None):
    """Create full analytics data dict."""
    if daily_reports is None:
        daily_reports = [_make_daily_report()]
    return {
        'daily_reports': daily_reports,
        'sessions': {},
        'preflop_overall': {
            'vpip': 25.0, 'pfr': 19.0, 'three_bet': 8.0,
            'fold_to_3bet': 45.0, 'ats': 35.0,
        },
        'postflop_overall': {
            'af': 2.8, 'cbet': 65.0, 'fold_to_cbet': 42.0,
            'wtsd': 28.0, 'wsd': 52.0,
        },
        'summary': {
            'total_hands': 200, 'total_net': 50.25, 'total_days': 1,
        },
        'allin_ev': allin_ev if allin_ev is not None else {
            'total_hands': 200, 'allin_hands': 8,
            'real_net': 50.25, 'ev_net': 42.0,
            'bb100_real': 5.03, 'bb100_ev': 4.20,
        },
        'leaks': [],
    }


# ── Bug #1: EV Line should not fallback to Real Line ──────────────


class TestEVLineFallback(unittest.TestCase):
    """EV line should carry forward when ev_net is None, not copy real net."""

    def test_ev_chart_not_identical_to_real(self):
        """When some days have no ev_net, EV line should differ from real line."""
        reports = [
            _make_daily_report('2026-01-10', net=20.0, ev_net=15.0,
                               sessions=[_make_session(profit=20.0, ev_data=_make_ev_data(20.0, 15.0))]),
            _make_daily_report('2026-01-11', net=30.0, ev_net=None,
                               sessions=[_make_session(profit=30.0, ev_data=None)]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        prepare_ev_data(data)

        ec = data.get('ev_chart', {})
        self.assertTrue(ec, "ev_chart should exist when there is EV data")
        # EV points should differ from real points
        self.assertNotEqual(ec.get('ev_points'), ec.get('real_points'),
                            "EV and Real lines should not be identical")

    def test_ev_chart_carries_forward_cumulative(self):
        """Cumulative EV should stay flat when a day has no ev_net."""
        reports = [
            _make_daily_report('2026-01-10', net=20.0, ev_net=15.0,
                               sessions=[_make_session(profit=20.0, ev_data=_make_ev_data(20.0, 15.0))]),
            _make_daily_report('2026-01-11', net=30.0, ev_net=None,
                               sessions=[_make_session(profit=30.0, ev_data=None)]),
            _make_daily_report('2026-01-12', net=10.0, ev_net=8.0,
                               sessions=[_make_session(profit=10.0, ev_data=_make_ev_data(10.0, 8.0))]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        prepare_ev_data(data)

        ec = data['ev_chart']
        # final_ev should be 15+0+8 = 23 (not 15+30+8 = 53)
        self.assertAlmostEqual(ec['final_ev'], 23.0, places=1)
        # final_real should be 20+30+10 = 60
        self.assertAlmostEqual(ec['final_real'], 60.0, places=1)

    def test_ev_chart_not_generated_without_any_ev(self):
        """No ev_chart if no day has ev_net data."""
        reports = [
            _make_daily_report('2026-01-10', net=20.0, ev_net=None,
                               sessions=[_make_session(profit=20.0, ev_data=None)]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        prepare_ev_data(data)
        self.assertEqual(data.get('ev_chart'), {},
                         "ev_chart should be empty when no EV data exists")

    def test_overview_ev_chart_not_identical(self):
        """Overview mini EV chart should also not fallback."""
        reports = [
            _make_daily_report('2026-01-10', net=20.0, ev_net=15.0,
                               sessions=[_make_session(profit=20.0, ev_data=_make_ev_data(20.0, 15.0))]),
            _make_daily_report('2026-01-11', net=30.0, ev_net=None,
                               sessions=[_make_session(profit=30.0, ev_data=None)]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        prepare_overview_data(data)

        ec = data.get('overview_ev_chart')
        self.assertIsNotNone(ec, "overview_ev_chart should exist")
        self.assertNotEqual(ec['ev_points'], ec['real_points'])


# ── Bug #2 & #9: bb/100 in overview ──────────────────────────────


class TestOverviewBb100(unittest.TestCase):
    """bb/100 should be properly passed to the overview."""

    def test_overall_row_has_ev_bb100(self):
        """Overall row should have ev_bb100 from allin_ev."""
        data = _make_analytics_data()
        prepare_overview_data(data)
        overall = data['overall_row']
        self.assertEqual(overall['ev_bb100'], 4.20)

    def test_overall_row_has_bb100_real(self):
        """Overall row should also include bb100_real."""
        data = _make_analytics_data()
        prepare_overview_data(data)
        overall = data['overall_row']
        self.assertEqual(overall['bb100_real'], 5.03)


# ── Bug #3 & #6: Sizing pct and avg_pot ──────────────────────────


class TestSizingData(unittest.TestCase):
    """Sizing data should compute pct and avg_pot correctly."""

    def test_pot_types_dict_gets_pct_computed(self):
        """When pot_types is a dict, pct should be computed from totals."""
        data = {
            'bet_sizing': {
                'pot_types': {
                    'Single Raised': {'hands': 60, 'avg_pot_size': 12.5, 'net': 50},
                    'Limped': {'hands': 40, 'avg_pot_size': 5.0, 'net': -20},
                },
            },
        }
        prepare_sizing_data(data)
        pt = data['pot_types']
        self.assertEqual(len(pt), 2)
        # Check that percentages sum to 100
        total_pct = sum(p['pct'] for p in pt)
        self.assertAlmostEqual(total_pct, 100.0, places=1)
        # Check individual pct
        sr = next(p for p in pt if p['label'] == 'Single Raised')
        self.assertAlmostEqual(sr['pct'], 60.0, places=1)

    def test_pot_types_dict_gets_avg_pot(self):
        """avg_pot should be mapped from avg_pot_size."""
        data = {
            'bet_sizing': {
                'pot_types': {
                    'Single Raised': {'hands': 60, 'avg_pot_size': 12.5},
                },
            },
        }
        prepare_sizing_data(data)
        pt = data['pot_types'][0]
        self.assertEqual(pt['avg_pot'], 12.5)

    def test_preflop_sizing_pct_computed(self):
        """Preflop sizing should compute pct when missing."""
        data = {
            'bet_sizing': {
                'preflop_sizing': [
                    {'label': '2x', 'count': 30},
                    {'label': '2.5x', 'count': 70},
                ],
            },
        }
        prepare_sizing_data(data)
        pre = data['sizing_preflop']
        self.assertAlmostEqual(pre[0]['pct'], 30.0, places=1)
        self.assertAlmostEqual(pre[1]['pct'], 70.0, places=1)

    def test_by_street_pct_computed(self):
        """By-street sizing should also compute pct."""
        data = {
            'bet_sizing': {
                'by_street': {
                    'flop': [
                        {'label': '1/3 pot', 'count': 20},
                        {'label': '2/3 pot', 'count': 80},
                    ],
                },
            },
        }
        prepare_sizing_data(data)
        flop = data['sizing_by_street']['flop']
        self.assertAlmostEqual(flop[0]['pct'], 20.0, places=1)
        self.assertAlmostEqual(flop[1]['pct'], 80.0, places=1)


# ── Bug #4, #5, #11: Tilt data normalization ─────────────────────


class TestTiltDataNormalization(unittest.TestCase):
    """Tilt data keys should be normalized for templates."""

    def test_tilt_sessions_key_mapping(self):
        """session_date -> date, tilt_cost_bb -> cost_bb, tilt_signals -> trigger."""
        data = {
            'tilt': {
                'session_tilt': [
                    {
                        'session_id': 'sess1',
                        'session_date': '2026-01-15',
                        'tilt_cost_bb': 12.5,
                        'tilt_signals': ['vpip_spike', 'pfr_spike'],
                        'severity': 'warning',
                    },
                ],
            },
        }
        prepare_tilt_data(data)
        sessions = data['tilt_sessions']
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s['date'], '2026-01-15')
        self.assertEqual(s['cost_bb'], 12.5)
        self.assertIn('vpip_spike', s['trigger'])

    def test_tilt_session_summary_computed(self):
        """Summary stats should be computed from session list."""
        data = {
            'tilt': {
                'session_tilt': [
                    {'session_date': '2026-01-15', 'severity': 'warning',
                     'tilt_cost_bb': 10.0, 'tilt_signals': []},
                    {'session_date': '2026-01-16', 'severity': 'good',
                     'tilt_cost_bb': 0, 'tilt_signals': []},
                    {'session_date': '2026-01-17', 'severity': 'danger',
                     'tilt_cost_bb': 20.0, 'tilt_signals': ['vpip_spike']},
                ],
            },
        }
        prepare_tilt_data(data)
        summary = data['tilt_session_summary']
        self.assertEqual(summary['total_sessions'], 3)
        self.assertEqual(summary['tilt_sessions'], 2)
        self.assertAlmostEqual(summary['tilt_pct'], 66.7, places=1)
        self.assertAlmostEqual(summary['tilt_cost'], 30.0, places=1)

    def test_hourly_heatmap_win_rate_bb100_key(self):
        """Hourly data with win_rate_bb100 key should be picked up."""
        data = {
            'tilt': {
                'hourly': {
                    'hourly': [
                        {'hour': 10, 'hands': 50, 'win_rate_bb100': 3.5},
                        {'hour': 22, 'hands': 30, 'win_rate_bb100': -2.0},
                    ],
                },
            },
        }
        prepare_tilt_data(data)
        heatmap = data['tilt_heatmap']
        self.assertEqual(len(heatmap), 24)
        h10 = next(c for c in heatmap if c['hour'] == 10)
        self.assertAlmostEqual(h10['bb100'], 3.5, places=1)
        self.assertEqual(h10['hands'], 50)

    def test_duration_buckets_normalized(self):
        """Duration buckets should be available under 'by_duration' key."""
        data = {
            'tilt': {
                'duration': {
                    'buckets': [
                        {'label': '0-60min', 'sessions': 5, 'win_rate_bb100': 2.0},
                        {'label': '60-120min', 'sessions': 3, 'win_rate_bb100': -1.0},
                    ],
                },
            },
        }
        prepare_tilt_data(data)
        dur = data['tilt_duration']
        buckets = dur.get('by_duration', [])
        self.assertEqual(len(buckets), 2)
        self.assertEqual(buckets[0]['bb100'], 2.0)
        self.assertEqual(buckets[0]['count'], 5)

    def test_recommendation_text_to_message(self):
        """Recommendation 'text' key should be mapped to 'message'."""
        data = {
            'tilt': {
                'recommendation': {
                    'text': 'Keep sessions under 2 hours',
                    'best_bucket': '60-120min',
                },
            },
        }
        prepare_tilt_data(data)
        rec = data['tilt_recommendation']
        self.assertEqual(rec['message'], 'Keep sessions under 2 hours')
        self.assertEqual(rec['ideal_duration'], '60-120min')


# ── Bug #7: Tournament Session Drill-Down ────────────────────────


class TestTournamentSessionDrillDown(unittest.TestCase):
    """Tournament session drill-down should work with 'tournaments' key."""

    def test_tournaments_key_mapped_to_sessions(self):
        """Daily report with 'tournaments' key should be normalized to 'sessions'."""
        data = {
            'daily_reports': [{
                'date': '2026-01-15',
                'net': -50.0,
                'total_hands': 300,
                'day_stats': {'vpip': 22.0, 'pfr': 16.0},
                'tournaments': [
                    {
                        'tournament_id': 't1',
                        'name': 'Daily $10',
                        'net': -10.0,
                        'hands_count': 150,
                        'stats': {'vpip': 20.0, 'pfr': 15.0},
                        'sparkline': [],
                    },
                    {
                        'tournament_id': 't2',
                        'name': 'Daily $5',
                        'net': -40.0,
                        'hands_count': 150,
                        'stats': {'vpip': 24.0, 'pfr': 17.0},
                        'sparkline': [],
                    },
                ],
            }],
            'sessions': {},
            'preflop_overall': {'vpip': 22.0, 'pfr': 16.0},
            'postflop_overall': {'af': 2.5, 'wtsd': 27.0, 'wsd': 50.0},
        }
        prepare_session_day(data, '2026-01-15')
        day = data['session_day']
        self.assertIsNotNone(day, "session_day should not be None")
        sessions = day.get('sessions', [])
        self.assertEqual(len(sessions), 2)

    def test_tournament_profit_mapped_from_net(self):
        """Tournament 'net' should be accessible as 'profit'."""
        data = {
            'daily_reports': [{
                'date': '2026-01-15',
                'net': -10.0,
                'total_hands': 100,
                'day_stats': {},
                'tournaments': [{
                    'tournament_id': 't1',
                    'net': -10.0,
                    'hands_count': 100,
                    'stats': {},
                    'sparkline': [],
                }],
            }],
            'sessions': {},
            'preflop_overall': {},
            'postflop_overall': {},
        }
        prepare_session_day(data, '2026-01-15')
        sess = data['session_day']['sessions'][0]
        self.assertEqual(sess['profit'], -10.0)


# ── Bug #8: Tournament ROI and Health Score ──────────────────────


class TestTournamentROI(unittest.TestCase):
    """Tournament ROI should be computed from invested and net."""

    def test_roi_computed_from_summary(self):
        """ROI should be total_net / total_invested * 100."""
        data = _make_analytics_data()
        data['summary'] = {
            'total_hands': 500,
            'total_net': 100.0,
            'total_invested': 200.0,
            'total_days': 5,
        }
        prepare_overview_data(data)
        self.assertEqual(data['summary']['roi'], 50.0)

    def test_roi_zero_when_no_investment(self):
        """ROI should be 0 when total_invested is 0."""
        data = _make_analytics_data()
        data['summary'] = {
            'total_hands': 0,
            'total_net': 0,
            'total_invested': 0,
            'total_days': 0,
        }
        prepare_overview_data(data)
        self.assertEqual(data['summary']['roi'], 0)

    def test_health_score_computed_from_leaks(self):
        """Health score should be derived from leaks when 0 or None."""
        data = _make_analytics_data()
        data['health_score'] = 0
        data['leaks'] = [
            {'cost_bb100': 2.0, 'stat_name': 'vpip'},
            {'cost_bb100': 1.0, 'stat_name': 'pfr'},
        ]
        prepare_overview_data(data)
        # 100 - (2+1)*5 = 85
        self.assertEqual(data['health_score'], 85)


if __name__ == '__main__':
    unittest.main()
