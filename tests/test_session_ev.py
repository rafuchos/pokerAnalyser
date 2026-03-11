"""Tests for US-008: EV Analysis por Sessão (Cash e Torneio).

Covers:
- EVAnalyzer.get_session_ev_analysis: per-session EV for cash games
- CashAnalyzer.get_session_details: ev_data included when ev_analyzer passed
- CashAnalyzer.get_daily_reports_with_sessions: ev_data flows through to sessions
- TournamentAnalyzer._get_daily_ev_analysis: chart_data included per day
- Cash report: _render_session_ev_summary with Lucky/Unlucky badge
- Cash report: _render_mini_ev_chart (EV vs Real sparkline)
- Tournament report: _render_session_ev_summary with Lucky/Unlucky badge
- Tournament report: _render_mini_ev_chart (EV vs Real sparkline)
- Edge cases: no all-in hands, empty session, single hand
- Integration: full generate_cash_report and generate_tournament_report
"""

import sqlite3
import os
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.ev import EVAnalyzer
from src.analyzers.cash import CashAnalyzer
from src.analyzers.tournament import TournamentAnalyzer
from src.reports.cash_report import (
    generate_cash_report,
    _render_session_ev_summary,
    _render_mini_ev_chart,
    _render_session_card,
)
from src.reports.tournament_report import (
    generate_tournament_report,
    _render_session_ev_summary as _render_tournament_session_ev_summary,
    _render_mini_ev_chart as _render_tournament_mini_ev_chart,
    _render_daily_report as _render_tournament_daily_report,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_hand(hand_id, date='2026-01-15T20:00:00', hero_position='CO', **kwargs):
    """Create a HandData with sensible defaults for testing."""
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type=kwargs.get('game_type', 'cash'),
        date=datetime.fromisoformat(date) if isinstance(date, str) else date,
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
        tournament_id=kwargs.get('tournament_id', None),
    )


def _make_action(hand_id, player, action_type, seq, street='preflop',
                 position='CO', is_hero=0, amount=0.0, is_voluntary=0):
    """Create an ActionData for testing."""
    return ActionData(
        hand_id=hand_id,
        street=street,
        player=player,
        action_type=action_type,
        amount=amount,
        is_hero=is_hero,
        sequence_order=seq,
        position=position,
        is_voluntary=is_voluntary,
    )


def _setup_db():
    """Create an in-memory DB with schema initialized."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Repository(conn)


def _create_session(repo, date='2026-01-15',
                    start_time='2026-01-15T19:00:00',
                    end_time='2026-01-15T21:00:00',
                    buy_in=50.0, cash_out=75.0,
                    profit=25.0, hands_count=100,
                    min_stack=35.0):
    """Insert a session and return its ID."""
    return repo.insert_session({
        'platform': 'GGPoker',
        'start_time': datetime.fromisoformat(start_time),
        'end_time': datetime.fromisoformat(end_time),
        'buy_in': buy_in,
        'cash_out': cash_out,
        'profit': profit,
        'hands_count': hands_count,
        'min_stack': min_stack,
    })


def _create_allin_hand(repo, hand_id, date='2026-01-15T20:00:00',
                       hero_cards='Ah Kd', opponent_cards='Qs Qd',
                       pot_total=10.0, invested=5.0, net=5.0,
                       allin_street='preflop'):
    """Create a cash hand that went all-in with showdown."""
    hand = _make_hand(hand_id, date=date, hero_cards=hero_cards,
                      invested=invested, won=invested + net, net=net)
    repo.insert_hand(hand)
    repo.update_hand_showdown(hand_id, pot_total=pot_total,
                               opponent_cards=opponent_cards,
                               has_allin=True,
                               allin_street=allin_street)
    return hand


def _create_tournament_allin_hand(repo, hand_id, tournament_id='T100',
                                   date='2026-01-15T20:00:00',
                                   hero_cards='Ah Kd', opponent_cards='Qs Qd',
                                   pot_total=2000, invested=1000, net=1000,
                                   blinds_bb=200, allin_street='preflop'):
    """Create a tournament hand that went all-in with showdown."""
    # Ensure tournament row exists (needed for exclude_satellites JOIN)
    repo.insert_tournament({
        'tournament_id': tournament_id, 'platform': 'test', 'name': 'Test Tourney',
        'date': date[:10], 'buy_in': 10, 'rake': 1, 'bounty': 0, 'total_buy_in': 11,
        'position': None, 'prize': 0, 'bounty_won': 0, 'total_players': 100,
        'entries': 1, 'is_bounty': False, 'is_satellite': False,
    })
    hand = _make_hand(hand_id, date=date, hero_cards=hero_cards,
                      game_type='tournament', tournament_id=tournament_id,
                      blinds_sb=blinds_bb // 2, blinds_bb=blinds_bb,
                      invested=invested, won=invested + net, net=net)
    repo.insert_hand(hand)
    repo.update_hand_showdown(hand_id, pot_total=pot_total,
                               opponent_cards=opponent_cards,
                               has_allin=True,
                               allin_street=allin_street)
    return hand


# ── EVAnalyzer.get_session_ev_analysis Tests ──────────────────────

class TestSessionEvAnalysis(unittest.TestCase):
    """Test EVAnalyzer.get_session_ev_analysis for per-session EV."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.ev = EVAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_empty_session_returns_empty(self):
        """Session with no hands returns empty EV data."""
        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)
        self.assertEqual(result['total_hands'], 0)
        self.assertEqual(result['allin_hands'], 0)
        self.assertEqual(result['chart_data'], [])

    def test_session_no_allin_hands(self):
        """Session with hands but no all-ins returns real=ev."""
        hand = _make_hand('H1', date='2026-01-15T20:00:00', net=5.0, won=6.0)
        self.repo.insert_hand(hand)
        hand2 = _make_hand('H2', date='2026-01-15T20:30:00', net=-2.0, won=0.0)
        self.repo.insert_hand(hand2)

        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)

        self.assertEqual(result['total_hands'], 2)
        self.assertEqual(result['allin_hands'], 0)
        self.assertAlmostEqual(result['real_net'], 3.0, places=2)
        self.assertAlmostEqual(result['ev_net'], 3.0, places=2)
        self.assertAlmostEqual(result['luck_factor'], 0.0, places=2)
        self.assertEqual(len(result['chart_data']), 2)

    def test_session_with_allin(self):
        """Session with all-in hand computes equity-based EV."""
        # Regular hand
        hand1 = _make_hand('H1', date='2026-01-15T20:00:00', net=2.0, won=3.0)
        self.repo.insert_hand(hand1)

        # All-in hand: AK vs QQ preflop
        _create_allin_hand(self.repo, 'H2', date='2026-01-15T20:30:00',
                           hero_cards='Ah Kd', opponent_cards='Qs Qd',
                           pot_total=10.0, invested=5.0, net=5.0)

        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)

        self.assertEqual(result['total_hands'], 2)
        self.assertEqual(result['allin_hands'], 1)
        self.assertAlmostEqual(result['real_net'], 7.0, places=2)
        # EV should differ from real since equity != 100%
        self.assertNotEqual(result['ev_net'], result['real_net'])
        self.assertNotEqual(result['luck_factor'], 0.0)
        self.assertTrue(len(result['chart_data']) >= 2)

    def test_session_chart_data_structure(self):
        """Chart data has correct structure with 'hand', 'real', 'ev' keys."""
        hand = _make_hand('H1', date='2026-01-15T20:00:00', net=5.0, won=6.0)
        self.repo.insert_hand(hand)

        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)

        self.assertEqual(len(result['chart_data']), 1)
        point = result['chart_data'][0]
        self.assertIn('hand', point)
        self.assertIn('real', point)
        self.assertIn('ev', point)
        self.assertEqual(point['hand'], 1)
        self.assertAlmostEqual(point['real'], 5.0)
        self.assertAlmostEqual(point['ev'], 5.0)

    def test_session_only_includes_hands_in_range(self):
        """Only hands within session time range are included."""
        # Hand before session
        h1 = _make_hand('H1', date='2026-01-15T18:00:00', net=100.0, won=101.0)
        self.repo.insert_hand(h1)
        # Hand during session
        h2 = _make_hand('H2', date='2026-01-15T20:00:00', net=5.0, won=6.0)
        self.repo.insert_hand(h2)
        # Hand after session
        h3 = _make_hand('H3', date='2026-01-15T22:00:00', net=50.0, won=51.0)
        self.repo.insert_hand(h3)

        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)

        self.assertEqual(result['total_hands'], 1)
        self.assertAlmostEqual(result['real_net'], 5.0, places=2)

    def test_session_bb100_calculation(self):
        """bb/100 is correctly calculated for the session."""
        # 3 hands, each $0.50 BB
        for i in range(3):
            hand = _make_hand(f'H{i}', date=f'2026-01-15T20:{i:02d}:00',
                              net=1.0, won=2.0, blinds_bb=0.50)
            self.repo.insert_hand(hand)

        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)

        # net = $3.0, avg_bb = 0.50, 3 hands -> bb/100 = (3.0/0.50/3)*100 = 200
        self.assertAlmostEqual(result['bb100_real'], 200.0, places=1)

    def test_multiple_allin_hands_in_session(self):
        """Multiple all-in hands are all computed."""
        _create_allin_hand(self.repo, 'H1', date='2026-01-15T20:00:00',
                           hero_cards='Ah Kd', opponent_cards='Qs Qd',
                           pot_total=10.0, invested=5.0, net=5.0)
        _create_allin_hand(self.repo, 'H2', date='2026-01-15T20:30:00',
                           hero_cards='Kh Kd', opponent_cards='Ah Ad',
                           pot_total=20.0, invested=10.0, net=-10.0)

        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)

        self.assertEqual(result['allin_hands'], 2)
        self.assertEqual(result['total_hands'], 2)
        self.assertEqual(len(result['chart_data']), 2)


# ── CashAnalyzer Session EV Integration Tests ────────────────────

class TestCashAnalyzerSessionEv(unittest.TestCase):
    """Test CashAnalyzer wiring of session EV data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')
        self.ev = EVAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_session_details_without_ev(self):
        """get_session_details without ev_analyzer returns ev_data=None."""
        _create_session(self.repo)
        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        detail = self.analyzer.get_session_details(session)
        self.assertIsNone(detail['ev_data'])

    def test_session_details_with_ev(self):
        """get_session_details with ev_analyzer returns ev_data dict."""
        _create_session(self.repo)
        # Add a hand in the session's range
        hand = _make_hand('H1', date='2026-01-15T20:00:00', net=5.0, won=6.0)
        self.repo.insert_hand(hand)

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        detail = self.analyzer.get_session_details(session, ev_analyzer=self.ev)

        self.assertIsNotNone(detail['ev_data'])
        self.assertEqual(detail['ev_data']['total_hands'], 1)
        self.assertAlmostEqual(detail['ev_data']['real_net'], 5.0, places=2)

    def test_daily_reports_include_session_ev(self):
        """get_daily_reports_with_sessions passes ev_analyzer to session details."""
        _create_session(self.repo)
        hand = _make_hand('H1', date='2026-01-15T20:00:00', net=5.0, won=6.0)
        self.repo.insert_hand(hand)

        reports = self.analyzer.get_daily_reports_with_sessions(ev_analyzer=self.ev)
        self.assertEqual(len(reports), 1)

        sessions = reports[0]['sessions']
        self.assertEqual(len(sessions), 1)
        self.assertIsNotNone(sessions[0]['ev_data'])
        self.assertEqual(sessions[0]['ev_data']['total_hands'], 1)

    def test_daily_reports_no_ev_analyzer(self):
        """get_daily_reports_with_sessions without ev_analyzer has ev_data=None."""
        _create_session(self.repo)
        hand = _make_hand('H1', date='2026-01-15T20:00:00', net=5.0, won=6.0)
        self.repo.insert_hand(hand)

        reports = self.analyzer.get_daily_reports_with_sessions()
        sessions = reports[0]['sessions']
        self.assertIsNone(sessions[0]['ev_data'])


# ── Tournament Daily EV with Chart Data Tests ────────────────────

class TestTournamentDailyEvChartData(unittest.TestCase):
    """Test TournamentAnalyzer._get_daily_ev_analysis includes chart_data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_daily_ev_empty_returns_empty_chart(self):
        """Day with no hands returns empty chart_data."""
        result = self.analyzer._get_daily_ev_analysis('2026-01-15')
        self.assertEqual(result['chart_data'], [])
        self.assertEqual(result['total_hands'], 0)

    def test_daily_ev_includes_chart_data(self):
        """Day with hands returns chart_data with correct structure."""
        # Insert a tournament
        self.repo.insert_tournament({
            'tournament_id': 'T100', 'platform': 'GGPoker',
            'name': 'Test', 'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 0,
            'total_buy_in': 11, 'position': 3, 'prize': 0,
            'bounty_won': 0, 'total_players': 100, 'entries': 1,
            'is_bounty': False, 'is_satellite': False,
        })

        # Insert tournament hands
        for i in range(3):
            hand = _make_hand(f'TH{i}', date=f'2026-01-15T20:{i:02d}:00',
                              game_type='tournament', tournament_id='T100',
                              blinds_sb=100, blinds_bb=200,
                              net=100 if i % 2 == 0 else -100,
                              won=300 if i % 2 == 0 else 0,
                              invested=200)
            self.repo.insert_hand(hand)

        result = self.analyzer._get_daily_ev_analysis('2026-01-15')

        self.assertEqual(result['total_hands'], 3)
        self.assertEqual(len(result['chart_data']), 3)
        # Each point should have hand, real, ev
        for point in result['chart_data']:
            self.assertIn('hand', point)
            self.assertIn('real', point)
            self.assertIn('ev', point)

    def test_daily_ev_chart_data_cumulative(self):
        """Chart data shows cumulative real and EV values."""
        self.repo.insert_tournament({
            'tournament_id': 'T100', 'platform': 'GGPoker',
            'name': 'Test', 'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 0,
            'total_buy_in': 11, 'position': 3, 'prize': 0,
            'bounty_won': 0, 'total_players': 100, 'entries': 1,
            'is_bounty': False, 'is_satellite': False,
        })

        h1 = _make_hand('TH1', date='2026-01-15T20:00:00',
                         game_type='tournament', tournament_id='T100',
                         blinds_sb=100, blinds_bb=200,
                         net=500, won=700, invested=200)
        h2 = _make_hand('TH2', date='2026-01-15T20:01:00',
                         game_type='tournament', tournament_id='T100',
                         blinds_sb=100, blinds_bb=200,
                         net=-200, won=0, invested=200)
        self.repo.insert_hand(h1)
        self.repo.insert_hand(h2)

        result = self.analyzer._get_daily_ev_analysis('2026-01-15')

        # No all-ins, so real == ev at each point
        self.assertEqual(result['chart_data'][0]['real'], 500.0)
        self.assertEqual(result['chart_data'][1]['real'], 300.0)
        self.assertEqual(result['chart_data'][0]['ev'], 500.0)
        self.assertEqual(result['chart_data'][1]['ev'], 300.0)

    def test_daily_ev_with_allin_hands(self):
        """Day with all-in hands has chart_data diverging from real."""
        self.repo.insert_tournament({
            'tournament_id': 'T100', 'platform': 'GGPoker',
            'name': 'Test', 'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 0,
            'total_buy_in': 11, 'position': 3, 'prize': 0,
            'bounty_won': 0, 'total_players': 100, 'entries': 1,
            'is_bounty': False, 'is_satellite': False,
        })

        # Regular hand
        h1 = _make_hand('TH1', date='2026-01-15T20:00:00',
                         game_type='tournament', tournament_id='T100',
                         blinds_sb=100, blinds_bb=200,
                         net=200, won=400, invested=200)
        self.repo.insert_hand(h1)

        # All-in hand
        _create_tournament_allin_hand(self.repo, 'TH2', 'T100',
                                       date='2026-01-15T20:30:00',
                                       hero_cards='Ah Kd', opponent_cards='Qs Qd',
                                       pot_total=2000, invested=1000, net=1000,
                                       blinds_bb=200)

        result = self.analyzer._get_daily_ev_analysis('2026-01-15')

        self.assertEqual(result['allin_hands'], 1)
        self.assertEqual(result['total_hands'], 2)
        self.assertTrue(len(result['chart_data']) >= 2)
        # At hand 2, ev should differ from real
        last = result['chart_data'][-1]
        self.assertNotAlmostEqual(last['real'], last['ev'], places=1)

    def test_daily_ev_in_daily_reports(self):
        """get_daily_reports includes chart_data in day_ev."""
        self.repo.insert_tournament({
            'tournament_id': 'T100', 'platform': 'GGPoker',
            'name': 'Test', 'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 0,
            'total_buy_in': 11, 'position': 3, 'prize': 0,
            'bounty_won': 0, 'total_players': 100, 'entries': 1,
            'is_bounty': False, 'is_satellite': False,
        })

        hand = _make_hand('TH1', date='2026-01-15T20:00:00',
                          game_type='tournament', tournament_id='T100',
                          blinds_sb=100, blinds_bb=200,
                          net=200, won=400, invested=200)
        self.repo.insert_hand(hand)

        # Need preflop actions for stats (at least one hero action)
        actions = [
            _make_action('TH1', 'Hero', 'raise', 1, position='CO',
                         is_hero=1, amount=200, is_voluntary=1),
            _make_action('TH1', 'Villain', 'fold', 2, position='BTN'),
        ]
        self.repo.insert_actions_batch(actions)

        reports = self.analyzer.get_daily_reports()
        self.assertEqual(len(reports), 1)

        day_ev = reports[0]['day_ev']
        self.assertIn('chart_data', day_ev)
        self.assertTrue(len(day_ev['chart_data']) >= 1)


# ── Cash Report Rendering Tests ──────────────────────────────────

class TestCashSessionEvRendering(unittest.TestCase):
    """Test cash report session EV rendering functions."""

    def test_render_session_ev_summary_lucky(self):
        """Renders Lucky badge when luck_factor >= 0."""
        ev_data = {
            'total_hands': 50, 'allin_hands': 3,
            'real_net': 25.50, 'ev_net': 20.00,
            'luck_factor': 5.50,
            'bb100_real': 10.0, 'bb100_ev': 8.0,
            'chart_data': [
                {'hand': 1, 'real': 10.0, 'ev': 8.0},
                {'hand': 2, 'real': 25.50, 'ev': 20.0},
            ],
        }
        html = _render_session_ev_summary(ev_data)
        self.assertIn('Lucky', html)
        self.assertIn('badge-good', html)
        self.assertNotIn('Unlucky', html)
        self.assertIn('EV da Sess\u00e3o', html)
        self.assertIn('$25.50', html)
        self.assertIn('$20.00', html)
        self.assertIn('$+5.50', html)

    def test_render_session_ev_summary_unlucky(self):
        """Renders Unlucky badge when luck_factor < 0."""
        ev_data = {
            'total_hands': 50, 'allin_hands': 2,
            'real_net': -10.0, 'ev_net': -5.0,
            'luck_factor': -5.0,
            'bb100_real': -4.0, 'bb100_ev': -2.0,
            'chart_data': [
                {'hand': 1, 'real': -5.0, 'ev': -2.0},
                {'hand': 2, 'real': -10.0, 'ev': -5.0},
            ],
        }
        html = _render_session_ev_summary(ev_data)
        self.assertIn('Unlucky', html)
        self.assertIn('badge-danger', html)
        self.assertNotIn('badge-good', html)

    def test_render_session_ev_summary_empty(self):
        """Returns empty string for empty/no-allin EV data."""
        self.assertEqual(_render_session_ev_summary(None), '')
        self.assertEqual(_render_session_ev_summary({}), '')
        self.assertEqual(_render_session_ev_summary({'total_hands': 0}), '')
        self.assertEqual(_render_session_ev_summary(
            {'total_hands': 10, 'allin_hands': 0}), '')

    def test_render_session_ev_summary_contains_stats(self):
        """Rendered EV summary contains all-in count, real net, ev net, luck factor."""
        ev_data = {
            'total_hands': 100, 'allin_hands': 5,
            'real_net': 50.0, 'ev_net': 30.0,
            'luck_factor': 20.0,
            'bb100_real': 20.0, 'bb100_ev': 12.0,
            'chart_data': [],
        }
        html = _render_session_ev_summary(ev_data)
        self.assertIn('5', html)  # allin_hands
        self.assertIn('100 total', html)  # total_hands
        self.assertIn('$50.00', html)  # real_net
        self.assertIn('$30.00', html)  # ev_net
        self.assertIn('$+20.00', html)  # luck_factor (format is $+X.XX)

    def test_render_mini_ev_chart(self):
        """Renders inline SVG with Real and EV polylines."""
        chart_data = [
            {'hand': 1, 'real': 0.0, 'ev': 0.0},
            {'hand': 2, 'real': 5.0, 'ev': 3.0},
            {'hand': 3, 'real': 10.0, 'ev': 8.0},
        ]
        html = _render_mini_ev_chart(chart_data)
        self.assertIn('<svg', html)
        self.assertIn('polyline', html)
        self.assertIn('#00ff88', html)  # Real color (green)
        self.assertIn('#ffa500', html)  # EV color (orange)
        self.assertIn('Real', html)
        self.assertIn('EV', html)

    def test_render_mini_ev_chart_with_zero_line(self):
        """Mini EV chart shows zero line when values cross zero."""
        chart_data = [
            {'hand': 1, 'real': -5.0, 'ev': -3.0},
            {'hand': 2, 'real': 5.0, 'ev': 3.0},
        ]
        html = _render_mini_ev_chart(chart_data)
        self.assertIn('stroke-dasharray="2,2"', html)  # zero line


# ── Tournament Report Rendering Tests ────────────────────────────

class TestTournamentSessionEvRendering(unittest.TestCase):
    """Test tournament report session EV rendering functions."""

    def test_render_session_ev_summary_lucky(self):
        """Renders Lucky badge for positive luck factor."""
        day_ev = {
            'total_hands': 80, 'allin_hands': 4,
            'real_net': 1500, 'ev_net': 1000,
            'luck_factor': 500,
            'bb100_real': 5.0, 'bb100_ev': 3.5,
            'chart_data': [
                {'hand': 1, 'real': 500, 'ev': 300},
                {'hand': 2, 'real': 1500, 'ev': 1000},
            ],
        }
        html = _render_tournament_session_ev_summary(day_ev)
        self.assertIn('Lucky', html)
        self.assertIn('badge-good', html)
        self.assertIn('EV da Sess\u00e3o', html)

    def test_render_session_ev_summary_unlucky(self):
        """Renders Unlucky badge for negative luck factor."""
        day_ev = {
            'total_hands': 80, 'allin_hands': 4,
            'real_net': -1000, 'ev_net': -500,
            'luck_factor': -500,
            'bb100_real': -3.5, 'bb100_ev': -1.5,
            'chart_data': [],
        }
        html = _render_tournament_session_ev_summary(day_ev)
        self.assertIn('Unlucky', html)
        self.assertIn('badge-danger', html)

    def test_render_session_ev_summary_contains_stats(self):
        """Tournament EV summary contains all required stats."""
        day_ev = {
            'total_hands': 50, 'allin_hands': 3,
            'real_net': 2000, 'ev_net': 1500,
            'luck_factor': 500,
            'bb100_real': 10.0, 'bb100_ev': 7.0,
            'chart_data': [],
        }
        html = _render_tournament_session_ev_summary(day_ev)
        self.assertIn('3', html)  # allin_hands
        self.assertIn('50 total', html)
        self.assertIn('+2000', html)  # real_net
        self.assertIn('+1500', html)  # ev_net
        self.assertIn('+500', html)  # luck_factor
        self.assertIn('acima do EV', html)

    def test_render_mini_ev_chart_tournament(self):
        """Tournament mini EV chart uses orange (#ff8800) for Real."""
        chart_data = [
            {'hand': 1, 'real': 0, 'ev': 0},
            {'hand': 2, 'real': 500, 'ev': 300},
        ]
        html = _render_tournament_mini_ev_chart(chart_data)
        self.assertIn('<svg', html)
        self.assertIn('#ff8800', html)  # Tournament Real color (orange)
        self.assertIn('#00aaff', html)  # Tournament EV color (blue)

    def test_render_session_ev_empty(self):
        """Returns empty string for empty tournament EV data."""
        self.assertEqual(_render_tournament_session_ev_summary(None), '')
        self.assertEqual(_render_tournament_session_ev_summary({}), '')
        self.assertEqual(_render_tournament_session_ev_summary(
            {'total_hands': 0}), '')


# ── Session Card EV Integration (Cash) ───────────────────────────

class TestSessionCardEvIntegration(unittest.TestCase):
    """Test that session card renders EV data when present."""

    def test_session_card_with_ev_data(self):
        """Session card includes EV summary when ev_data is present."""
        sd = {
            'session_id': 1,
            'start_time': '2026-01-15T19:00:00',
            'end_time': '2026-01-15T21:00:00',
            'duration_minutes': 120,
            'buy_in': 50.0, 'cash_out': 75.0,
            'profit': 25.0, 'hands_count': 100,
            'min_stack': 35.0,
            'stats': {},
            'sparkline': [],
            'biggest_win': None, 'biggest_loss': None,
            'ev_data': {
                'total_hands': 100, 'allin_hands': 3,
                'real_net': 25.0, 'ev_net': 15.0,
                'luck_factor': 10.0,
                'bb100_real': 10.0, 'bb100_ev': 6.0,
                'chart_data': [
                    {'hand': 1, 'real': 10.0, 'ev': 8.0},
                    {'hand': 2, 'real': 25.0, 'ev': 15.0},
                ],
            },
        }
        html = _render_session_card(sd, 1)
        self.assertIn('EV da Sess\u00e3o', html)
        self.assertIn('Lucky', html)

    def test_session_card_without_ev_data(self):
        """Session card doesn't include EV section when ev_data is None."""
        sd = {
            'session_id': 1,
            'start_time': '2026-01-15T19:00:00',
            'end_time': '2026-01-15T21:00:00',
            'duration_minutes': 120,
            'buy_in': 50.0, 'cash_out': 75.0,
            'profit': 25.0, 'hands_count': 100,
            'min_stack': 35.0,
            'stats': {},
            'sparkline': [],
            'biggest_win': None, 'biggest_loss': None,
            'ev_data': None,
        }
        html = _render_session_card(sd, 1)
        self.assertNotIn('EV da Sess\u00e3o', html)


# ── Tournament Daily Report EV Integration ───────────────────────

class TestTournamentDailyReportEvIntegration(unittest.TestCase):
    """Test that daily report renders EV with badge and chart."""

    def test_daily_report_renders_ev_with_badge(self):
        """Daily report includes Lucky/Unlucky badge and mini chart."""
        report = {
            'date': '2026-01-15',
            'tournament_count': 2,
            'total_buy_in': 100.0,
            'total_won': 150.0,
            'net': 50.0,
            'total_rake': 10.0,
            'rebuys': 0,
            'total_entries': 2,
            'itm_count': 1,
            'itm_rate': 50.0,
            'tournaments': [],
            'day_stats': {},
            'comparison': {},
            'session_sparkline': [],
            'session_notable': {},
            'session_roi': 50.0,
            'day_ev': {
                'total_hands': 40, 'allin_hands': 2,
                'real_net': 500, 'ev_net': 200,
                'luck_factor': 300,
                'bb100_real': 5.0, 'bb100_ev': 2.0,
                'chart_data': [
                    {'hand': 1, 'real': 200, 'ev': 100},
                    {'hand': 2, 'real': 500, 'ev': 200},
                ],
            },
            'total_hands': 40,
        }
        html = _render_tournament_daily_report(report)
        self.assertIn('Lucky', html)
        self.assertIn('badge-good', html)
        self.assertIn('<svg', html)  # Mini EV chart

    def test_daily_report_unlucky_badge(self):
        """Daily report shows Unlucky badge for negative luck."""
        report = {
            'date': '2026-01-15',
            'tournament_count': 1,
            'total_buy_in': 50.0,
            'total_won': 0.0,
            'net': -50.0,
            'total_rake': 5.0,
            'rebuys': 0,
            'total_entries': 1,
            'itm_count': 0,
            'itm_rate': 0.0,
            'tournaments': [],
            'day_stats': {},
            'comparison': {},
            'session_sparkline': [],
            'session_notable': {},
            'session_roi': -100.0,
            'day_ev': {
                'total_hands': 30, 'allin_hands': 1,
                'real_net': -800, 'ev_net': -200,
                'luck_factor': -600,
                'bb100_real': -10.0, 'bb100_ev': -3.0,
                'chart_data': [
                    {'hand': 1, 'real': -400, 'ev': -100},
                    {'hand': 2, 'real': -800, 'ev': -200},
                ],
            },
            'total_hands': 30,
        }
        html = _render_tournament_daily_report(report)
        self.assertIn('Unlucky', html)
        self.assertIn('badge-danger', html)


# ── Full Report Integration Tests ────────────────────────────────

class TestCashReportFullIntegration(unittest.TestCase):
    """Test full cash report generation with session EV data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()
        output = 'output/test_session_ev_report.html'
        if os.path.exists(output):
            os.remove(output)

    def test_full_report_with_session_ev(self):
        """Full cash report includes session EV when ev_analyzer provided."""
        # Create session
        _create_session(self.repo)

        # Create hands including an all-in
        hand = _make_hand('H1', date='2026-01-15T20:00:00', net=5.0, won=6.0)
        self.repo.insert_hand(hand)
        _create_allin_hand(self.repo, 'H2', date='2026-01-15T20:30:00',
                           hero_cards='Ah Kd', opponent_cards='Qs Qd',
                           pot_total=10.0, invested=5.0, net=5.0)

        # Insert actions for stats
        for hid in ['H1', 'H2']:
            actions = [
                _make_action(hid, 'Hero', 'raise', 1, position='CO',
                             is_hero=1, amount=1.0, is_voluntary=1),
                _make_action(hid, 'Villain', 'fold', 2, position='BTN'),
            ]
            self.repo.insert_actions_batch(actions)

        analyzer = CashAnalyzer(self.repo, year='2026')
        ev_analyzer = EVAnalyzer(self.repo, year='2026')

        output = 'output/test_session_ev_report.html'
        generate_cash_report(analyzer, output, ev_analyzer=ev_analyzer)

        with open(output, 'r', encoding='utf-8') as f:
            html = f.read()

        # Global EV section should still exist
        self.assertIn('EV Analysis', html)
        # Session EV should be present
        self.assertIn('EV da Sess\u00e3o', html)

    def test_full_report_without_ev(self):
        """Full cash report works without ev_analyzer (no EV sections)."""
        _create_session(self.repo)
        hand = _make_hand('H1', date='2026-01-15T20:00:00', net=5.0, won=6.0)
        self.repo.insert_hand(hand)

        actions = [
            _make_action('H1', 'Hero', 'raise', 1, position='CO',
                         is_hero=1, amount=1.0, is_voluntary=1),
            _make_action('H1', 'Villain', 'fold', 2, position='BTN'),
        ]
        self.repo.insert_actions_batch(actions)

        analyzer = CashAnalyzer(self.repo, year='2026')
        output = 'output/test_session_ev_report.html'
        generate_cash_report(analyzer, output, ev_analyzer=None)

        with open(output, 'r', encoding='utf-8') as f:
            html = f.read()

        # Should not have session EV
        self.assertNotIn('EV da Sess\u00e3o', html)


class TestTournamentReportFullIntegration(unittest.TestCase):
    """Test full tournament report generation with session EV data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()
        output = 'output/test_tournament_session_ev_report.html'
        if os.path.exists(output):
            os.remove(output)

    def test_full_tournament_report_with_ev_chart(self):
        """Full tournament report includes mini EV chart in daily reports."""
        # Insert tournament
        self.repo.insert_tournament({
            'tournament_id': 'T100', 'platform': 'GGPoker',
            'name': 'Test Tourney', 'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 0,
            'total_buy_in': 11, 'position': 3, 'prize': 25,
            'bounty_won': 0, 'total_players': 100, 'entries': 1,
            'is_bounty': False, 'is_satellite': False,
        })

        # Insert tournament hands including an all-in
        hand = _make_hand('TH1', date='2026-01-15T20:00:00',
                          game_type='tournament', tournament_id='T100',
                          blinds_sb=100, blinds_bb=200,
                          net=200, won=400, invested=200)
        self.repo.insert_hand(hand)
        _create_tournament_allin_hand(self.repo, 'TH2', 'T100',
                                       date='2026-01-15T20:30:00',
                                       hero_cards='Ah Kd', opponent_cards='Qs Qd',
                                       pot_total=2000, invested=1000, net=1000)

        # Insert actions for stats
        for hid in ['TH1', 'TH2']:
            actions = [
                _make_action(hid, 'Hero', 'raise', 1, position='CO',
                             is_hero=1, amount=200, is_voluntary=1),
                _make_action(hid, 'Villain', 'fold', 2, position='BTN'),
            ]
            self.repo.insert_actions_batch(actions)

        analyzer = TournamentAnalyzer(self.repo, year='2026')
        output = 'output/test_tournament_session_ev_report.html'
        generate_tournament_report(analyzer, output)

        with open(output, 'r', encoding='utf-8') as f:
            html = f.read()

        # Global EV chart should still be there
        self.assertIn('EV Analysis', html)
        # Session EV should be present with badge
        self.assertIn('EV da Sess\u00e3o', html)
        # Lucky or Unlucky badge should appear
        self.assertTrue('Lucky' in html or 'Unlucky' in html)


# ── Edge Cases ───────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    """Test edge cases for session EV analysis."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.ev = EVAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_single_hand_session(self):
        """Session with a single hand returns valid EV data."""
        hand = _make_hand('H1', date='2026-01-15T20:00:00', net=3.0, won=4.0)
        self.repo.insert_hand(hand)

        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)

        self.assertEqual(result['total_hands'], 1)
        self.assertEqual(len(result['chart_data']), 1)

    def test_allin_without_opponent_cards(self):
        """All-in hand without opponent cards doesn't count as EV-adjustable."""
        hand = _make_hand('H1', date='2026-01-15T20:00:00', net=5.0, won=10.0,
                          invested=5.0, hero_cards='Ah Kd')
        self.repo.insert_hand(hand)
        self.repo.update_hand_showdown('H1', pot_total=10.0,
                                        opponent_cards=None,
                                        has_allin=True,
                                        allin_street='preflop')

        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)

        self.assertEqual(result['allin_hands'], 0)
        # Real should equal EV since no valid all-in for adjustment
        self.assertAlmostEqual(result['real_net'], result['ev_net'], places=2)

    def test_mini_ev_chart_flat_values(self):
        """Mini chart handles all-same values without division by zero."""
        chart_data = [
            {'hand': 1, 'real': 5.0, 'ev': 5.0},
            {'hand': 2, 'real': 5.0, 'ev': 5.0},
        ]
        html = _render_mini_ev_chart(chart_data)
        self.assertIn('<svg', html)

    def test_mini_ev_chart_single_point(self):
        """Mini chart with a single data point is still renderable."""
        # This shouldn't normally be called with < 2 points
        # but test defensive behavior
        chart_data = [{'hand': 1, 'real': 5.0, 'ev': 3.0}]
        html = _render_mini_ev_chart(chart_data)
        self.assertIn('<svg', html)

    def test_session_ev_chart_downsampled(self):
        """Large number of hands gets downsampled to max 100 points."""
        # Insert 150 hands
        for i in range(150):
            hand = _make_hand(f'H{i}', date=f'2026-01-15T20:{i // 60:02d}:{i % 60:02d}',
                              net=0.5, won=1.5)
            self.repo.insert_hand(hand)

        session = {'start_time': '2026-01-15T19:00:00',
                   'end_time': '2026-01-15T21:00:00'}
        result = self.ev.get_session_ev_analysis(session)

        self.assertEqual(result['total_hands'], 150)
        self.assertLessEqual(len(result['chart_data']), 100)

    def test_luck_factor_zero_badge_is_lucky(self):
        """Luck factor of exactly 0 shows Lucky badge (>= 0)."""
        ev_data = {
            'total_hands': 10, 'allin_hands': 1,
            'real_net': 5.0, 'ev_net': 5.0,
            'luck_factor': 0.0,
            'bb100_real': 2.0, 'bb100_ev': 2.0,
            'chart_data': [],
        }
        html = _render_session_ev_summary(ev_data)
        self.assertIn('Lucky', html)
        self.assertIn('badge-good', html)


if __name__ == '__main__':
    unittest.main()
