"""Tests for US-035: EV Tracking Completo – Luck Factor across all contexts."""

import json
import os
import sqlite3
import tempfile
import unittest

from src.web.app import create_app
from src.web.data import (
    prepare_session_day,
    prepare_sessions_list,
    prepare_overview_data,
    prepare_ev_data,
    _build_chart_points,
)
from src.db.analytics_schema import init_analytics_db


# ── Helpers ──────────────────────────────────────────────────────


def _make_ev_data(real_net=35.0, ev_net=28.0, total_hands=120, allin_hands=5):
    """Create EV data dict for a session."""
    luck = real_net - ev_net
    return {
        'total_hands': total_hands,
        'allin_hands': allin_hands,
        'real_net': real_net,
        'ev_net': ev_net,
        'luck_factor': luck,
        'bb100_real': round(real_net / 0.5 / total_hands * 100, 2) if total_hands else 0,
        'bb100_ev': round(ev_net / 0.5 / total_hands * 100, 2) if total_hands else 0,
        'chart_data': [
            {'hand': 1, 'real': 0, 'ev': 0},
            {'hand': total_hands // 2, 'real': real_net * 0.5, 'ev': ev_net * 0.5},
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
            'vpip': vpip, 'vpip_health': 'good',
            'pfr': pfr, 'pfr_health': 'good',
            'three_bet': 7.0, 'af': 2.8,
            'cbet': 65.0, 'wtsd': 28.0, 'wsd': 52.0,
        },
        'sparkline': [
            {'hand': 1, 'profit': 0},
            {'hand': hands // 2, 'profit': profit * 0.5},
            {'hand': hands, 'profit': profit},
        ],
        'biggest_win': {'net': 22.50, 'hero_position': 'BTN'},
        'biggest_loss': {'net': -15.00, 'hero_position': 'BB'},
        'ev_data': ev_data,
        'leak_summary': [],
    }


def _make_daily_report(date='2026-01-15', net=50.25, sessions=None):
    """Create a daily report dict."""
    if sessions is None:
        sessions = [
            _make_session('s1', profit=35.0, ev_data=_make_ev_data(35.0, 28.0)),
            _make_session('s2', profit=15.25, hands=80, duration=45, ev_data=None),
        ]
    total_hands = sum(s.get('hands_count', 0) for s in sessions)
    # Compute ev_net from sessions with EV data
    ev_net = None
    for s in sessions:
        sev = s.get('ev_data') or {}
        if sev.get('ev_net') is not None:
            if ev_net is None:
                ev_net = 0.0
            ev_net += sev['ev_net']
    report = {
        'date': date,
        'net': net,
        'hands_count': total_hands,
        'total_hands': total_hands,
        'num_sessions': len(sessions),
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
    data = {
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
            'total_hands': 200,
            'allin_hands': 8,
            'real_net': 50.25,
            'ev_net': 42.0,
            'luck_factor': 8.25,
            'bb100_real': 5.03,
            'bb100_ev': 4.20,
            'by_stakes': {},
            'chart_data': [],
        },
        'leaks': [],
    }
    return data


# ── Session Day: Luck Factor Card ────────────────────────────


class TestSessionDayLuckFactor(unittest.TestCase):
    """Tests for luck_factor card in session drill-down (prepare_session_day)."""

    def test_luck_factor_present_when_ev_data_exists(self):
        """Session with EV data should produce luck_factor dict."""
        data = _make_analytics_data()
        result = prepare_session_day(data, '2026-01-15')
        sessions = result['session_day']['sessions']
        s1 = sessions[0]
        self.assertIsNotNone(s1.get('luck_factor'))

    def test_luck_factor_absent_when_no_ev_data(self):
        """Session without EV data should have luck_factor=None."""
        data = _make_analytics_data()
        result = prepare_session_day(data, '2026-01-15')
        sessions = result['session_day']['sessions']
        s2 = sessions[1]
        self.assertIsNone(s2.get('luck_factor'))

    def test_luck_factor_real_net_value(self):
        """luck_factor.real_net should match EV data."""
        data = _make_analytics_data()
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['real_net'], 35.0)

    def test_luck_factor_ev_net_value(self):
        """luck_factor.ev_net should match EV data."""
        data = _make_analytics_data()
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['ev_net'], 28.0)

    def test_luck_factor_luck_calculation(self):
        """luck should be real_net - ev_net."""
        data = _make_analytics_data()
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['luck'], 7.0)

    def test_luck_factor_luck_bb100(self):
        """luck_bb100 should be bb100_real - bb100_ev."""
        ev = _make_ev_data(35.0, 28.0, 120, 5)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(ev_data=ev)])
        ])
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        expected = round(ev['bb100_real'] - ev['bb100_ev'], 2)
        self.assertEqual(lf['luck_bb100'], expected)

    def test_luck_factor_status_hot(self):
        """When luck > 0, status should be 'hot'."""
        ev = _make_ev_data(35.0, 28.0)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(ev_data=ev)])
        ])
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['status'], 'hot')

    def test_luck_factor_status_cold(self):
        """When luck < 0, status should be 'cold'."""
        ev = _make_ev_data(20.0, 30.0)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(profit=20.0, ev_data=ev)])
        ])
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['status'], 'cold')

    def test_luck_factor_status_neutral(self):
        """When luck == 0, status should be 'neutral'."""
        ev = _make_ev_data(25.0, 25.0)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(profit=25.0, ev_data=ev)])
        ])
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['status'], 'neutral')

    def test_luck_factor_allin_hands(self):
        """luck_factor should include allin_hands count."""
        data = _make_analytics_data()
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['allin_hands'], 5)

    def test_luck_factor_total_hands(self):
        """luck_factor should include total_hands count."""
        data = _make_analytics_data()
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['total_hands'], 120)

    def test_luck_factor_with_zero_ev(self):
        """Zero EV but positive real should show hot."""
        ev = _make_ev_data(10.0, 0.0)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(profit=10.0, ev_data=ev)])
        ])
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['luck'], 10.0)
        self.assertEqual(lf['status'], 'hot')

    def test_luck_factor_negative_values(self):
        """Luck factor with losing session shows correct negative values."""
        ev = _make_ev_data(-20.0, -10.0, 80, 3)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(profit=-20.0, ev_data=ev)])
        ])
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['luck'], -10.0)
        self.assertEqual(lf['status'], 'cold')


# ── Sessions List: Daily Luck ────────────────────────────────


class TestSessionsListDailyLuck(unittest.TestCase):
    """Tests for daily_luck column in sessions list (prepare_sessions_list)."""

    def test_daily_luck_present(self):
        """Day with EV data should have daily_luck."""
        data = _make_analytics_data()
        result = prepare_sessions_list(data)
        day = result['sessions_days'][0]
        self.assertIsNotNone(day.get('daily_luck'))

    def test_daily_luck_value(self):
        """daily_luck should sum luck across sessions with EV data."""
        ev1 = _make_ev_data(35.0, 28.0)  # luck = 7.0
        sessions = [
            _make_session('s1', profit=35.0, ev_data=ev1),
            _make_session('s2', profit=15.25, ev_data=None),
        ]
        data = _make_analytics_data(daily_reports=[_make_daily_report(sessions=sessions)])
        result = prepare_sessions_list(data)
        self.assertEqual(result['sessions_days'][0]['daily_luck'], 7.0)

    def test_daily_luck_aggregation_multiple_sessions(self):
        """daily_luck sums EV from multiple sessions with EV data."""
        ev1 = _make_ev_data(35.0, 28.0, 120, 5)  # luck = 7.0
        ev2 = _make_ev_data(10.0, 15.0, 80, 3)   # luck = -5.0
        sessions = [
            _make_session('s1', profit=35.0, ev_data=ev1),
            _make_session('s2', profit=10.0, ev_data=ev2),
        ]
        data = _make_analytics_data(daily_reports=[_make_daily_report(sessions=sessions)])
        result = prepare_sessions_list(data)
        self.assertEqual(result['sessions_days'][0]['daily_luck'], 2.0)

    def test_daily_luck_none_when_no_ev(self):
        """Day without any EV data should have daily_luck=None."""
        sessions = [
            _make_session('s1', profit=35.0, ev_data=None),
            _make_session('s2', profit=15.25, ev_data=None),
        ]
        data = _make_analytics_data(daily_reports=[_make_daily_report(sessions=sessions)])
        result = prepare_sessions_list(data)
        self.assertIsNone(result['sessions_days'][0]['daily_luck'])

    def test_daily_luck_negative(self):
        """Negative luck displayed correctly."""
        ev = _make_ev_data(10.0, 25.0, 100, 4)  # luck = -15.0
        sessions = [_make_session('s1', profit=10.0, ev_data=ev)]
        data = _make_analytics_data(daily_reports=[_make_daily_report(sessions=sessions)])
        result = prepare_sessions_list(data)
        self.assertEqual(result['sessions_days'][0]['daily_luck'], -15.0)

    def test_daily_luck_zero(self):
        """Zero luck when real == ev."""
        ev = _make_ev_data(20.0, 20.0, 100, 3)
        sessions = [_make_session('s1', profit=20.0, ev_data=ev)]
        data = _make_analytics_data(daily_reports=[_make_daily_report(sessions=sessions)])
        result = prepare_sessions_list(data)
        self.assertEqual(result['sessions_days'][0]['daily_luck'], 0.0)

    def test_daily_luck_across_multiple_days(self):
        """Multiple days each have independent daily_luck."""
        ev1 = _make_ev_data(30.0, 25.0, 100, 4)  # luck = 5.0
        ev2 = _make_ev_data(10.0, 20.0, 80, 3)   # luck = -10.0
        reports = [
            _make_daily_report('2026-01-15', 30.0, [_make_session('s1', profit=30.0, ev_data=ev1)]),
            _make_daily_report('2026-01-16', 10.0, [_make_session('s2', profit=10.0, ev_data=ev2)]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        result = prepare_sessions_list(data)
        self.assertEqual(result['sessions_days'][0]['daily_luck'], 5.0)
        self.assertEqual(result['sessions_days'][1]['daily_luck'], -10.0)


# ── Overview: Running Luck + Mini EV Line ────────────────────


class TestOverviewRunningLuck(unittest.TestCase):
    """Tests for running_luck card and overview_ev_chart in overview."""

    def test_running_luck_present(self):
        """Overview with EV data should have running_luck dict."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        self.assertIsNotNone(result.get('running_luck'))

    def test_running_luck_total(self):
        """running_luck.total_luck should be real_net - ev_net from allin_ev."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        rl = result['running_luck']
        self.assertEqual(rl['total_luck'], 8.25)

    def test_running_luck_bb100(self):
        """running_luck.luck_bb100 should be bb100 difference."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        rl = result['running_luck']
        expected = round(5.03 - 4.20, 2)
        self.assertEqual(rl['luck_bb100'], expected)

    def test_running_luck_status_hot(self):
        """Positive luck bb100 shows 'hot' status."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        self.assertEqual(result['running_luck']['status'], 'hot')

    def test_running_luck_status_cold(self):
        """Negative luck bb100 shows 'cold' status."""
        data = _make_analytics_data(allin_ev={
            'total_hands': 200, 'allin_hands': 8,
            'real_net': 30.0, 'ev_net': 50.0,
            'luck_factor': -20.0,
            'bb100_real': 3.0, 'bb100_ev': 5.0,
        })
        result = prepare_overview_data(data)
        self.assertEqual(result['running_luck']['status'], 'cold')

    def test_running_luck_none_when_no_ev(self):
        """No EV data means running_luck is None."""
        data = _make_analytics_data(allin_ev={})
        result = prepare_overview_data(data)
        self.assertIsNone(result.get('running_luck'))

    def test_overview_ev_chart_present(self):
        """Overview should have an EV chart."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        self.assertIsNotNone(result.get('overview_ev_chart'))

    def test_overview_ev_chart_has_real_points(self):
        """EV chart should contain real_points."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        ec = result.get('overview_ev_chart')
        if ec:
            self.assertIn('real_points', ec)

    def test_overview_ev_chart_has_ev_points(self):
        """EV chart should contain ev_points."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        ec = result.get('overview_ev_chart')
        if ec:
            self.assertIn('ev_points', ec)

    def test_overview_ev_chart_has_dates(self):
        """EV chart should include date labels."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        ec = result.get('overview_ev_chart')
        if ec:
            self.assertIn('dates', ec)
            self.assertEqual(ec['dates'], ['2026-01-15'])

    def test_overview_ev_chart_y_bounds(self):
        """EV chart should have y_min and y_max."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        ec = result.get('overview_ev_chart')
        if ec:
            self.assertIn('y_min', ec)
            self.assertIn('y_max', ec)

    def test_overview_ev_chart_none_when_no_data(self):
        """No daily reports → no EV chart."""
        data = _make_analytics_data(daily_reports=[])
        data['allin_ev'] = {}
        result = prepare_overview_data(data)
        self.assertIsNone(result.get('overview_ev_chart'))

    def test_overview_ev_chart_final_values(self):
        """EV chart final values should match cumulative profit."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        ec = result.get('overview_ev_chart')
        if ec:
            self.assertEqual(ec['final_real'], 50.25)


# ── EV Page: Per-Session Table + Luck Trend ──────────────────


class TestEvPageSessionTable(unittest.TestCase):
    """Tests for EV per-session table and luck trend in prepare_ev_data."""

    def test_ev_sessions_table_present(self):
        """EV page should have ev_sessions_table."""
        data = _make_analytics_data()
        result = prepare_ev_data(data)
        self.assertIn('ev_sessions_table', result)

    def test_ev_sessions_table_length(self):
        """Only days with EV data appear in table."""
        data = _make_analytics_data()
        result = prepare_ev_data(data)
        # Only 1 day report, session s1 has EV
        self.assertEqual(len(result['ev_sessions_table']), 1)

    def test_ev_sessions_table_row_date(self):
        """Each row should have the date."""
        data = _make_analytics_data()
        result = prepare_ev_data(data)
        self.assertEqual(result['ev_sessions_table'][0]['date'], '2026-01-15')

    def test_ev_sessions_table_row_hands(self):
        """Row should show total hands for the day."""
        data = _make_analytics_data()
        result = prepare_ev_data(data)
        self.assertEqual(result['ev_sessions_table'][0]['hands'], 200)

    def test_ev_sessions_table_row_allins(self):
        """Row should show number of all-in hands."""
        data = _make_analytics_data()
        result = prepare_ev_data(data)
        self.assertEqual(result['ev_sessions_table'][0]['allins'], 5)

    def test_ev_sessions_table_row_real_net(self):
        """Row shows real net for the day."""
        data = _make_analytics_data()
        result = prepare_ev_data(data)
        self.assertEqual(result['ev_sessions_table'][0]['real_net'], 50.25)

    def test_ev_sessions_table_row_luck(self):
        """Row shows luck = sum(real_net - ev_net) across sessions."""
        data = _make_analytics_data()
        result = prepare_ev_data(data)
        self.assertEqual(result['ev_sessions_table'][0]['luck'], 7.0)

    def test_ev_sessions_table_no_ev_sessions_excluded(self):
        """Days without any EV data should not appear."""
        sessions = [
            _make_session('s1', profit=20.0, ev_data=None),
        ]
        data = _make_analytics_data(daily_reports=[_make_daily_report(sessions=sessions)])
        result = prepare_ev_data(data)
        self.assertEqual(len(result['ev_sessions_table']), 0)

    def test_ev_sessions_table_multiple_days(self):
        """Multiple days with EV data appear in order."""
        ev1 = _make_ev_data(30.0, 25.0, 100, 4)
        ev2 = _make_ev_data(15.0, 20.0, 80, 2)
        reports = [
            _make_daily_report('2026-01-15', 30.0, [_make_session('s1', profit=30.0, ev_data=ev1)]),
            _make_daily_report('2026-01-16', 15.0, [_make_session('s2', profit=15.0, ev_data=ev2)]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        result = prepare_ev_data(data)
        self.assertEqual(len(result['ev_sessions_table']), 2)
        self.assertEqual(result['ev_sessions_table'][0]['date'], '2026-01-15')
        self.assertEqual(result['ev_sessions_table'][1]['date'], '2026-01-16')

    def test_luck_trend_chart_present(self):
        """EV page should have luck_trend_chart when there's EV data."""
        ev = _make_ev_data(35.0, 28.0)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(ev_data=ev)])
        ])
        result = prepare_ev_data(data)
        self.assertIsNotNone(result.get('luck_trend_chart'))

    def test_luck_trend_chart_points(self):
        """Luck trend chart has points string."""
        ev = _make_ev_data(35.0, 28.0)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(ev_data=ev)])
        ])
        result = prepare_ev_data(data)
        ltc = result.get('luck_trend_chart')
        if ltc:
            self.assertIn('points', ltc)
            self.assertTrue(len(ltc['points']) > 0)

    def test_luck_trend_chart_dates(self):
        """Luck trend chart includes date labels."""
        ev = _make_ev_data(35.0, 28.0)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(ev_data=ev)])
        ])
        result = prepare_ev_data(data)
        ltc = result.get('luck_trend_chart')
        if ltc:
            self.assertEqual(ltc['dates'], ['2026-01-15'])

    def test_luck_trend_chart_final(self):
        """Luck trend final should be cumulative luck."""
        ev1 = _make_ev_data(30.0, 25.0, 100, 4)  # luck = 5.0
        ev2 = _make_ev_data(15.0, 20.0, 80, 2)   # luck = -5.0
        reports = [
            _make_daily_report('2026-01-15', 30.0, [_make_session('s1', profit=30.0, ev_data=ev1)]),
            _make_daily_report('2026-01-16', 15.0, [_make_session('s2', profit=15.0, ev_data=ev2)]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        result = prepare_ev_data(data)
        ltc = result['luck_trend_chart']
        # Cumulative: day1=5.0, day2=5.0+(-5.0)=0.0
        self.assertEqual(ltc['final'], 0.0)

    def test_luck_trend_chart_none_when_no_luck(self):
        """No EV data → luck_trend_chart is None."""
        sessions = [_make_session('s1', ev_data=None)]
        data = _make_analytics_data(daily_reports=[_make_daily_report(sessions=sessions)])
        result = prepare_ev_data(data)
        self.assertIsNone(result.get('luck_trend_chart'))

    def test_luck_trend_cumulative(self):
        """Luck trend values should be cumulative across days."""
        ev1 = _make_ev_data(30.0, 25.0, 100, 4)  # luck = 5.0
        ev2 = _make_ev_data(20.0, 15.0, 80, 2)   # luck = 5.0
        reports = [
            _make_daily_report('2026-01-15', 30.0, [_make_session('s1', profit=30.0, ev_data=ev1)]),
            _make_daily_report('2026-01-16', 20.0, [_make_session('s2', profit=20.0, ev_data=ev2)]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        result = prepare_ev_data(data)
        ltc = result['luck_trend_chart']
        # Cumulative: day1=5.0, day2=10.0
        self.assertEqual(ltc['final'], 10.0)


# ── EV Page: Period Filtering ────────────────────────────────


class TestEvPagePeriodFiltering(unittest.TestCase):
    """Tests for EV data recalculation when using period filters."""

    def test_ev_sessions_table_filtered_by_period(self):
        """EV sessions table respects period filter."""
        ev = _make_ev_data(30.0, 25.0, 100, 4)
        reports = [
            _make_daily_report('2026-01-01', 30.0, [_make_session('s1', profit=30.0, ev_data=ev)]),
            _make_daily_report('2026-03-01', 20.0, [_make_session('s2', profit=20.0, ev_data=ev)]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        result = prepare_ev_data(data, period='custom', from_date='2026-03-01', to_date='2026-03-31')
        self.assertEqual(len(result['ev_sessions_table']), 1)
        self.assertEqual(result['ev_sessions_table'][0]['date'], '2026-03-01')

    def test_luck_trend_filtered(self):
        """Luck trend chart recalculates for filtered period."""
        ev1 = _make_ev_data(30.0, 25.0, 100, 4)  # luck = 5
        ev2 = _make_ev_data(20.0, 15.0, 80, 2)   # luck = 5
        reports = [
            _make_daily_report('2026-01-01', 30.0, [_make_session('s1', profit=30.0, ev_data=ev1)]),
            _make_daily_report('2026-03-01', 20.0, [_make_session('s2', profit=20.0, ev_data=ev2)]),
        ]
        data = _make_analytics_data(daily_reports=reports)
        result = prepare_ev_data(data, period='custom', from_date='2026-03-01', to_date='2026-03-31')
        ltc = result['luck_trend_chart']
        # Only March data: luck = 5.0
        self.assertEqual(ltc['final'], 5.0)


# ── Web Template Rendering ───────────────────────────────────


class TestEVTrackingTemplateRendering(unittest.TestCase):
    """Integration tests: verify templates render without errors."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        conn = sqlite3.connect(self.tmp.name)
        init_analytics_db(conn)

        # Insert summary
        now = '2026-01-15T20:00:00'
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', 'summary', None, json.dumps({
                'total_hands': 200, 'total_net': 50.25, 'total_days': 1,
            }), now),
        )

        # Insert daily report
        report = _make_daily_report()
        conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', '2026-01-15', 'daily_report', json.dumps(report), now),
        )

        # Insert session
        for i, sess in enumerate(report['sessions']):
            conn.execute(
                "INSERT INTO session_stats (game_type, session_key, stat_name, stat_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ('cash', f'2026-01-15s{i+1}', 'session_detail', json.dumps(sess), now),
            )

        # Insert EV analysis
        conn.execute(
            "INSERT INTO ev_analysis (game_type, analysis_type, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'allin_ev', json.dumps({
                'total_hands': 200, 'allin_hands': 8,
                'real_net': 50.25, 'ev_net': 42.0,
                'luck_factor': 8.25,
                'bb100_real': 5.03, 'bb100_ev': 4.20,
                'by_stakes': {}, 'chart_data': [],
            }), now),
        )

        # Insert preflop/postflop overall
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', 'preflop_overall', None, json.dumps({
                'vpip': 25.0, 'pfr': 19.0, 'three_bet': 8.0,
            }), now),
        )
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', 'postflop_overall', None, json.dumps({
                'af': 2.8, 'cbet': 65.0, 'wtsd': 28.0, 'wsd': 52.0,
            }), now),
        )

        conn.commit()
        conn.close()

        self.app = create_app(analytics_db_path=self.tmp.name)
        self.client = self.app.test_client()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_session_day_renders_luck_factor(self):
        """Session day page renders luck factor card elements."""
        resp = self.client.get('/cash/sessions/2026-01-15')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('Session Luck Factor', html)
        self.assertIn('luck-factor-card', html)

    def test_session_day_renders_luck_badge(self):
        """Session day page renders running hot/cold badge."""
        resp = self.client.get('/cash/sessions/2026-01-15')
        html = resp.data.decode()
        self.assertIn('luck-factor-badge', html)

    def test_sessions_list_renders_luck_column(self):
        """Sessions list page shows luck indicator."""
        resp = self.client.get('/cash/sessions')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('Luck', html)

    def test_overview_renders_running_luck(self):
        """Overview page shows Running Luck card."""
        resp = self.client.get('/cash/overview')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('Running Luck', html)

    def test_overview_renders_ev_chart(self):
        """Overview page renders EV vs Real chart."""
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('EV Line vs Real Line', html)

    def test_overview_renders_luck_badge(self):
        """Overview Running Luck card has badge."""
        resp = self.client.get('/cash/overview')
        html = resp.data.decode()
        self.assertIn('luck-badge-', html)

    def test_ev_page_renders_luck_trend(self):
        """EV page renders luck trend chart."""
        resp = self.client.get('/cash/ev')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('Luck Over Time', html)

    def test_ev_page_renders_session_table(self):
        """EV page renders per-session EV table."""
        resp = self.client.get('/cash/ev')
        html = resp.data.decode()
        self.assertIn('EV por Sess', html)

    def test_ev_page_session_table_has_links(self):
        """EV session table rows link to session day page."""
        resp = self.client.get('/cash/ev')
        html = resp.data.decode()
        self.assertIn('/cash/sessions/2026-01-15', html)

    def test_ev_page_renders_luck_value(self):
        """EV page shows luck values in table."""
        resp = self.client.get('/cash/ev')
        html = resp.data.decode()
        # Should have luck value displayed with arrows
        self.assertIn('&#9650;', html)  # up arrow for positive luck


# ── Tournament Template Rendering ────────────────────────────


class TestTournamentTemplateRendering(unittest.TestCase):
    """Integration tests for tournament template EV tracking features."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        conn = sqlite3.connect(self.tmp.name)
        init_analytics_db(conn)

        # Insert tournament summary
        now = '2026-01-15T20:00:00'
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('tournament', 'summary', None, json.dumps({
                'total_hands': 150, 'total_net': 100.0,
                'total_days': 1, 'total_tournaments': 2,
                'roi': 25.0,
            }), now),
        )

        # Insert tournament daily report
        report = _make_daily_report()
        conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('tournament', '2026-01-15', 'daily_report', json.dumps(report), now),
        )

        # Insert tournament EV analysis
        conn.execute(
            "INSERT INTO ev_analysis (game_type, analysis_type, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('tournament', 'allin_ev', json.dumps({
                'total_hands': 150, 'allin_hands': 6,
                'real_net': 100.0, 'ev_net': 80.0,
                'luck_factor': 20.0,
                'bb100_real': 6.67, 'bb100_ev': 5.33,
                'by_stakes': {}, 'chart_data': [],
            }), now),
        )

        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('tournament', 'preflop_overall', None, json.dumps({
                'vpip': 22.0, 'pfr': 16.0, 'three_bet': 6.0,
            }), now),
        )

        conn.commit()
        conn.close()

        self.app = create_app(analytics_db_path=self.tmp.name)
        self.client = self.app.test_client()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_tournament_session_day_renders_luck_factor(self):
        """Tournament session day renders luck factor card."""
        resp = self.client.get('/tournament/sessions/2026-01-15')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('Session Luck Factor', html)

    def test_tournament_sessions_renders_luck(self):
        """Tournament sessions list renders luck column."""
        resp = self.client.get('/tournament/sessions')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('Luck', html)

    def test_tournament_overview_renders_running_luck(self):
        """Tournament overview shows Running Luck card."""
        resp = self.client.get('/tournament/overview')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('Running Luck', html)

    def test_tournament_ev_renders_luck_trend(self):
        """Tournament EV page renders luck trend chart."""
        resp = self.client.get('/tournament/ev')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('Luck Over Time', html)

    def test_tournament_ev_renders_session_table(self):
        """Tournament EV page renders per-session table."""
        resp = self.client.get('/tournament/ev')
        html = resp.data.decode()
        self.assertIn('EV por Sess', html)


# ── Edge Cases ───────────────────────────────────────────────


class TestEVTrackingEdgeCases(unittest.TestCase):
    """Edge case tests for EV tracking features."""

    def test_empty_daily_reports(self):
        """Empty daily reports should not crash."""
        data = _make_analytics_data(daily_reports=[])
        result = prepare_sessions_list(data)
        self.assertEqual(len(result['sessions_days']), 0)

    def test_session_with_zero_total_hands_no_luck_factor(self):
        """Session with 0 total hands should have no luck factor."""
        ev = _make_ev_data(0.0, 0.0, 0, 0)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(ev_data=ev)])
        ])
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertIsNone(lf)

    def test_prepare_overview_with_no_allin_ev(self):
        """Overview with no allin_ev should have running_luck=None."""
        data = _make_analytics_data(allin_ev={'total_hands': 0})
        result = prepare_overview_data(data)
        self.assertIsNone(result.get('running_luck'))

    def test_luck_factor_precision(self):
        """Luck factor values should be rounded to 2 decimal places."""
        ev = _make_ev_data(35.123, 28.456, 120, 5)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(ev_data=ev)])
        ])
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        # luck = 35.123 - 28.456 = 6.667
        self.assertEqual(lf['luck'], round(35.123 - 28.456, 2))

    def test_large_negative_luck(self):
        """Large negative luck values display correctly."""
        ev = _make_ev_data(-500.0, 200.0, 500, 20)
        data = _make_analytics_data(daily_reports=[
            _make_daily_report(sessions=[_make_session(profit=-500.0, ev_data=ev)])
        ])
        result = prepare_session_day(data, '2026-01-15')
        lf = result['session_day']['sessions'][0]['luck_factor']
        self.assertEqual(lf['luck'], -700.0)
        self.assertEqual(lf['status'], 'cold')

    def test_overview_ev_chart_with_single_day(self):
        """Single day should still produce valid EV chart."""
        data = _make_analytics_data()
        result = prepare_overview_data(data)
        ec = result.get('overview_ev_chart')
        if ec:
            self.assertIn('final_real', ec)
            self.assertIn('final_ev', ec)

    def test_ev_sessions_table_ev_net_calculation(self):
        """EV net in sessions table aggregates from sessions."""
        ev1 = _make_ev_data(30.0, 25.0, 100, 4)
        ev2 = _make_ev_data(10.0, 8.0, 50, 2)
        sessions = [
            _make_session('s1', profit=30.0, ev_data=ev1),
            _make_session('s2', profit=10.0, ev_data=ev2),
        ]
        data = _make_analytics_data(daily_reports=[
            _make_daily_report('2026-01-15', 40.0, sessions)
        ])
        result = prepare_ev_data(data)
        row = result['ev_sessions_table'][0]
        # ev_net = 25.0 + 8.0 = 33.0
        self.assertEqual(row['ev_net'], 33.0)

    def test_daily_luck_rounding(self):
        """daily_luck should be properly rounded."""
        ev = _make_ev_data(10.333, 7.666, 50, 2)
        sessions = [_make_session('s1', profit=10.333, ev_data=ev)]
        data = _make_analytics_data(daily_reports=[_make_daily_report(sessions=sessions)])
        result = prepare_sessions_list(data)
        luck = result['sessions_days'][0]['daily_luck']
        self.assertEqual(luck, round(10.333 - 7.666, 2))

    def test_multiple_sessions_mixed_ev(self):
        """Mix of sessions with and without EV data."""
        ev1 = _make_ev_data(30.0, 20.0, 100, 5)  # luck = 10
        sessions = [
            _make_session('s1', profit=30.0, ev_data=ev1),
            _make_session('s2', profit=15.0, ev_data=None),
            _make_session('s3', profit=-5.0, ev_data=None),
        ]
        data = _make_analytics_data(daily_reports=[
            _make_daily_report('2026-01-15', 40.0, sessions)
        ])
        result = prepare_session_day(data, '2026-01-15')
        sessions_out = result['session_day']['sessions']
        self.assertIsNotNone(sessions_out[0]['luck_factor'])
        self.assertIsNone(sessions_out[1]['luck_factor'])
        self.assertIsNone(sessions_out[2]['luck_factor'])


# ── CSS Classes ──────────────────────────────────────────────


class TestCSSClassesExist(unittest.TestCase):
    """Verify CSS classes for luck factor are defined."""

    def test_luck_factor_css_exists(self):
        """luck-factor-card CSS should be in style.css."""
        css_path = os.path.join(
            os.path.dirname(__file__), '..', 'src', 'web', 'static', 'css', 'style.css'
        )
        with open(css_path) as f:
            css = f.read()
        self.assertIn('.luck-factor-card', css)
        self.assertIn('.luck-factor-badge', css)
        self.assertIn('.luck-factor-grid', css)

    def test_luck_badge_css_exists(self):
        """luck-badge CSS for overview should be in style.css."""
        css_path = os.path.join(
            os.path.dirname(__file__), '..', 'src', 'web', 'static', 'css', 'style.css'
        )
        with open(css_path) as f:
            css = f.read()
        self.assertIn('.luck-badge-hot', css)
        self.assertIn('.luck-badge-cold', css)
        self.assertIn('.luck-badge-neutral', css)


if __name__ == '__main__':
    unittest.main()
