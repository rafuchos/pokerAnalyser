"""Tests for US-007: Relatório de Torneios por Sessão.

Covers:
- TournamentAnalyzer._get_session_sparkline: aggregated sparkline across day's tournaments
- TournamentAnalyzer._get_daily_notable_hands: biggest win/loss across all day's tournaments
- TournamentAnalyzer._get_daily_ev_analysis: day-level EV analysis
- TournamentAnalyzer._aggregate_tournament_stats_with_health: weighted stats with health badges
- TournamentAnalyzer.get_session_comparison: cross-day session comparison
- TournamentAnalyzer.get_daily_reports: session-level fields (sparkline, notable, ROI, EV, hands)
- Report: _render_session_sparkline, _render_session_notable_hands, _render_session_ev_summary
- Report: _render_session_comparison, _render_day_summary_stats (with health badges)
- Report: _render_daily_report (session-focused layout with accordion)
- Report: generate_tournament_report (session comparison section)
- Edge cases: single tournament day, no hands, empty stats
"""

import sqlite3
import os
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.tournament import TournamentAnalyzer
from src.reports.tournament_report import (
    generate_tournament_report,
    _render_daily_report,
    _render_day_summary_stats,
    _render_session_sparkline,
    _render_session_notable_hands,
    _render_session_ev_summary,
    _render_session_comparison,
    _render_tournament_comparison,
    _render_chip_sparkline,
    _render_hand_card,
    _render_tournament_card,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tournament_hand(hand_id, tournament_id='T100', date='2026-01-15T20:00:00',
                          hero_position='CO', **kwargs):
    """Create a HandData with tournament defaults for testing."""
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='tournament',
        date=datetime.fromisoformat(date) if isinstance(date, str) else date,
        blinds_sb=kwargs.get('blinds_sb', 100),
        blinds_bb=kwargs.get('blinds_bb', 200),
        hero_cards=kwargs.get('hero_cards', 'Ah Kd'),
        hero_position=hero_position,
        invested=kwargs.get('invested', 200),
        won=kwargs.get('won', 0),
        net=kwargs.get('net', -200),
        rake=0.0,
        table_name='T',
        num_players=kwargs.get('num_players', 6),
        tournament_id=tournament_id,
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


def _insert_tournament(repo, tournament_id='T100', name='MTT $5.50',
                       date='2026-01-15', buy_in=5.0, rake=0.5,
                       prize=0.0, position=None, entries=1,
                       is_satellite=False):
    """Insert a tournament record."""
    repo.insert_tournament({
        'tournament_id': tournament_id,
        'platform': 'GGPoker',
        'name': name,
        'date': date,
        'buy_in': buy_in,
        'rake': rake,
        'bounty': 0,
        'total_buy_in': buy_in + rake,
        'position': position,
        'prize': prize,
        'bounty_won': 0,
        'total_players': 100,
        'entries': entries,
        'is_bounty': False,
        'is_satellite': is_satellite,
    })


def _setup_tournament_with_hands(repo, tournament_id='T100', day='2026-01-15',
                                  hands_count=5, prize=50.0, position=5):
    """Insert a tournament with N hands, each with preflop actions."""
    _insert_tournament(repo, tournament_id=tournament_id, prize=prize,
                      position=position, date=day)

    for i in range(hands_count):
        hid = f'{tournament_id}_h{i}'
        hand = _make_tournament_hand(
            hid, tournament_id=tournament_id,
            date=f'{day}T20:{i:02d}:00',
            invested=200, won=400 if i == 0 else 0,
            net=200 if i == 0 else -200,
        )
        repo.insert_hand(hand)

        actions = [
            _make_action(hid, 'Villain', 'post_sb', 0, position='SB'),
            _make_action(hid, 'Hero', 'post_bb', 1, position='BB', is_hero=1),
            _make_action(hid, 'Villain2', 'raise', 2, position='UTG', amount=400),
        ]
        if i % 2 == 0:
            actions.append(
                _make_action(hid, 'Hero', 'call', 3, position='BB',
                             is_hero=1, amount=400, is_voluntary=1))
        else:
            actions.append(
                _make_action(hid, 'Hero', 'fold', 3, position='BB', is_hero=1))
        repo.insert_actions_batch(actions)

    repo.conn.commit()


def _setup_two_tournaments_same_day(repo, day='2026-01-15'):
    """Setup two tournaments on the same day for session testing."""
    _setup_tournament_with_hands(repo, tournament_id='T100', day=day,
                                  hands_count=5, prize=50.0, position=5)
    _setup_tournament_with_hands(repo, tournament_id='T200', day=day,
                                  hands_count=3, prize=0.0, position=50)


def _setup_multi_day_tournaments(repo):
    """Setup tournaments across multiple days for session comparison testing."""
    # Day 1: 2 tournaments, good day
    _setup_tournament_with_hands(repo, tournament_id='T100', day='2026-01-15',
                                  hands_count=5, prize=100.0, position=3)
    _setup_tournament_with_hands(repo, tournament_id='T200', day='2026-01-15',
                                  hands_count=3, prize=50.0, position=10)

    # Day 2: 1 tournament, bad day
    _setup_tournament_with_hands(repo, tournament_id='T300', day='2026-01-16',
                                  hands_count=4, prize=0.0, position=80)

    # Day 3: 2 tournaments, medium day
    _setup_tournament_with_hands(repo, tournament_id='T400', day='2026-01-17',
                                  hands_count=6, prize=30.0, position=15)
    _setup_tournament_with_hands(repo, tournament_id='T500', day='2026-01-17',
                                  hands_count=4, prize=20.0, position=20)


# ── Session Sparkline Tests ──────────────────────────────────────────

class TestSessionSparkline(unittest.TestCase):
    """Test TournamentAnalyzer._get_session_sparkline."""

    def test_empty_tournament_details(self):
        result = TournamentAnalyzer._get_session_sparkline([])
        self.assertEqual(result, [])

    def test_single_tournament(self):
        details = [{
            'sparkline': [
                {'hand': 1, 'chips': 100},
                {'hand': 2, 'chips': 50},
                {'hand': 3, 'chips': 200},
            ]
        }]
        result = TournamentAnalyzer._get_session_sparkline(details)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['chips'], 100)
        self.assertEqual(result[1]['chips'], 50)
        self.assertEqual(result[2]['chips'], 200)

    def test_multiple_tournaments(self):
        """Session sparkline merges all tournaments' hands."""
        details = [
            {'sparkline': [
                {'hand': 1, 'chips': 100},
                {'hand': 2, 'chips': 50},
            ]},
            {'sparkline': [
                {'hand': 1, 'chips': -50},
                {'hand': 2, 'chips': -100},
            ]},
        ]
        result = TournamentAnalyzer._get_session_sparkline(details)
        self.assertEqual(len(result), 4)
        # Cumulative: 100, 50, -50, -100
        # Per-hand nets: 100, -50, -50, -50
        # Cumulative session: 100, 50, 0, -50
        self.assertEqual(result[0]['chips'], 100)
        self.assertEqual(result[1]['chips'], 50)
        self.assertEqual(result[2]['chips'], 0)
        self.assertEqual(result[3]['chips'], -50)

    def test_no_sparkline_data(self):
        details = [{'sparkline': []}, {'sparkline': []}]
        result = TournamentAnalyzer._get_session_sparkline(details)
        self.assertEqual(result, [])

    def test_hand_indices_are_sequential(self):
        details = [{
            'sparkline': [{'hand': 1, 'chips': 100}, {'hand': 2, 'chips': 200}]
        }]
        result = TournamentAnalyzer._get_session_sparkline(details)
        self.assertEqual(result[0]['hand'], 1)
        self.assertEqual(result[1]['hand'], 2)


# ── Daily Notable Hands Tests ──────────────────────────────────────

class TestDailyNotableHands(unittest.TestCase):
    """Test TournamentAnalyzer._get_daily_notable_hands."""

    def test_finds_biggest_across_tournaments(self):
        details = [
            {'biggest_win': {'net': 100, 'hero_cards': 'Ah Kh'},
             'biggest_loss': {'net': -50, 'hero_cards': 'Qs Jd'}},
            {'biggest_win': {'net': 200, 'hero_cards': 'Ac Ad'},
             'biggest_loss': {'net': -300, 'hero_cards': '7h 2d'}},
        ]
        result = TournamentAnalyzer._get_daily_notable_hands(details)
        self.assertEqual(result['biggest_win']['net'], 200)
        self.assertEqual(result['biggest_loss']['net'], -300)

    def test_no_notable_hands(self):
        details = [
            {'biggest_win': None, 'biggest_loss': None},
        ]
        result = TournamentAnalyzer._get_daily_notable_hands(details)
        self.assertIsNone(result['biggest_win'])
        self.assertIsNone(result['biggest_loss'])

    def test_only_wins(self):
        details = [
            {'biggest_win': {'net': 50}, 'biggest_loss': None},
            {'biggest_win': {'net': 150}, 'biggest_loss': None},
        ]
        result = TournamentAnalyzer._get_daily_notable_hands(details)
        self.assertEqual(result['biggest_win']['net'], 150)
        self.assertIsNone(result['biggest_loss'])

    def test_only_losses(self):
        details = [
            {'biggest_win': None, 'biggest_loss': {'net': -100}},
            {'biggest_win': None, 'biggest_loss': {'net': -200}},
        ]
        result = TournamentAnalyzer._get_daily_notable_hands(details)
        self.assertIsNone(result['biggest_win'])
        self.assertEqual(result['biggest_loss']['net'], -200)

    def test_single_tournament(self):
        details = [
            {'biggest_win': {'net': 500}, 'biggest_loss': {'net': -250}},
        ]
        result = TournamentAnalyzer._get_daily_notable_hands(details)
        self.assertEqual(result['biggest_win']['net'], 500)
        self.assertEqual(result['biggest_loss']['net'], -250)


# ── Aggregate Stats with Health Tests ────────────────────────────

class TestAggregateStatsWithHealth(unittest.TestCase):
    """Test TournamentAnalyzer._aggregate_tournament_stats_with_health."""

    def test_single_tournament_with_health_badges(self):
        details = [{
            'stats': {
                'total_hands': 10,
                'vpip': 25.0, 'pfr': 20.0, 'three_bet': 8.0,
                'fold_to_3bet': 50.0, 'ats': 35.0,
                'af': 2.5, 'wtsd': 30.0, 'wsd': 50.0,
                'cbet': 65.0, 'fold_to_cbet': 40.0, 'check_raise': 8.0,
            }
        }]
        result = TournamentAnalyzer._aggregate_tournament_stats_with_health(details)
        self.assertEqual(result['total_hands'], 10)
        self.assertEqual(result['vpip'], 25.0)
        self.assertIn('vpip_health', result)
        self.assertEqual(result['vpip_health'], 'good')
        self.assertIn('pfr_health', result)
        self.assertIn('af_health', result)
        self.assertIn('wtsd_health', result)

    def test_weighted_average_with_health(self):
        details = [
            {'stats': {'total_hands': 10, 'vpip': 20.0, 'pfr': 15.0,
                       'three_bet': 5.0, 'fold_to_3bet': 40.0, 'ats': 30.0,
                       'af': 2.0, 'wtsd': 25.0, 'wsd': 48.0,
                       'cbet': 60.0, 'fold_to_cbet': 35.0, 'check_raise': 6.0}},
            {'stats': {'total_hands': 10, 'vpip': 30.0, 'pfr': 25.0,
                       'three_bet': 10.0, 'fold_to_3bet': 50.0, 'ats': 40.0,
                       'af': 3.0, 'wtsd': 30.0, 'wsd': 55.0,
                       'cbet': 70.0, 'fold_to_cbet': 45.0, 'check_raise': 10.0}},
        ]
        result = TournamentAnalyzer._aggregate_tournament_stats_with_health(details)
        self.assertEqual(result['total_hands'], 20)
        self.assertAlmostEqual(result['vpip'], 25.0)
        self.assertAlmostEqual(result['pfr'], 20.0)
        # All should have health keys
        for key in ('vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats',
                    'af', 'wtsd', 'wsd', 'cbet', 'fold_to_cbet', 'check_raise'):
            self.assertIn(f'{key}_health', result)

    def test_empty_stats(self):
        details = [{'stats': {}}]
        result = TournamentAnalyzer._aggregate_tournament_stats_with_health(details)
        self.assertEqual(result, {})

    def test_danger_health_classification(self):
        """Stats way outside normal ranges should be 'danger'."""
        details = [{
            'stats': {
                'total_hands': 10,
                'vpip': 80.0, 'pfr': 5.0, 'three_bet': 1.0,
                'fold_to_3bet': 90.0, 'ats': 5.0,
                'af': 0.5, 'wtsd': 10.0, 'wsd': 20.0,
                'cbet': 10.0, 'fold_to_cbet': 90.0, 'check_raise': 1.0,
            }
        }]
        result = TournamentAnalyzer._aggregate_tournament_stats_with_health(details)
        self.assertEqual(result['vpip_health'], 'danger')
        self.assertEqual(result['pfr_health'], 'danger')


# ── Session Comparison Tests ──────────────────────────────────────

class TestSessionComparison(unittest.TestCase):
    """Test TournamentAnalyzer.get_session_comparison."""

    def test_comparison_with_multiple_days(self):
        conn, repo = _setup_db()
        _setup_multi_day_tournaments(repo)
        analyzer = TournamentAnalyzer(repo, '2026')
        daily_reports = analyzer.get_daily_reports()
        comparison = analyzer.get_session_comparison(daily_reports)

        self.assertIn('net', comparison)
        self.assertIn('roi', comparison)
        self.assertIn('itm', comparison)
        self.assertIn('hands', comparison)

        # Net comparison should have best and worst
        self.assertIn('best', comparison['net'])
        self.assertIn('worst', comparison['net'])
        self.assertIn('best_value', comparison['net'])
        self.assertIn('worst_value', comparison['net'])

    def test_comparison_single_day_returns_empty(self):
        conn, repo = _setup_db()
        _setup_tournament_with_hands(repo, tournament_id='T100', day='2026-01-15')
        analyzer = TournamentAnalyzer(repo, '2026')
        daily_reports = analyzer.get_daily_reports()
        comparison = analyzer.get_session_comparison(daily_reports)
        self.assertEqual(comparison, {})

    def test_comparison_identifies_best_worst_net(self):
        conn, repo = _setup_db()
        _setup_multi_day_tournaments(repo)
        analyzer = TournamentAnalyzer(repo, '2026')
        daily_reports = analyzer.get_daily_reports()
        comparison = analyzer.get_session_comparison(daily_reports)

        # Best net day should have highest net
        best_idx = comparison['net']['best']
        worst_idx = comparison['net']['worst']
        self.assertGreater(daily_reports[best_idx]['net'],
                           daily_reports[worst_idx]['net'])


# ── Daily Reports Session Fields Tests ──────────────────────────

class TestDailyReportsSessionFields(unittest.TestCase):
    """Test that get_daily_reports includes session-level fields."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_daily_report_has_session_sparkline(self):
        _setup_two_tournaments_same_day(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        reports = analyzer.get_daily_reports()
        self.assertEqual(len(reports), 1)
        self.assertIn('session_sparkline', reports[0])
        self.assertIsInstance(reports[0]['session_sparkline'], list)

    def test_daily_report_has_session_notable(self):
        _setup_two_tournaments_same_day(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        reports = analyzer.get_daily_reports()
        self.assertIn('session_notable', reports[0])
        notable = reports[0]['session_notable']
        self.assertIn('biggest_win', notable)
        self.assertIn('biggest_loss', notable)

    def test_daily_report_has_session_roi(self):
        _setup_two_tournaments_same_day(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        reports = analyzer.get_daily_reports()
        self.assertIn('session_roi', reports[0])
        self.assertIsInstance(reports[0]['session_roi'], float)

    def test_daily_report_has_day_ev(self):
        _setup_two_tournaments_same_day(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        reports = analyzer.get_daily_reports()
        self.assertIn('day_ev', reports[0])
        day_ev = reports[0]['day_ev']
        self.assertIn('total_hands', day_ev)
        self.assertIn('real_net', day_ev)
        self.assertIn('ev_net', day_ev)
        self.assertIn('luck_factor', day_ev)

    def test_daily_report_has_total_hands(self):
        _setup_two_tournaments_same_day(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        reports = analyzer.get_daily_reports()
        self.assertIn('total_hands', reports[0])
        self.assertEqual(reports[0]['total_hands'], 8)  # 5 + 3 hands

    def test_daily_report_day_stats_has_health_badges(self):
        _setup_two_tournaments_same_day(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        reports = analyzer.get_daily_reports()
        day_stats = reports[0]['day_stats']
        if day_stats and day_stats.get('total_hands', 0) > 0:
            self.assertIn('vpip_health', day_stats)
            self.assertIn('pfr_health', day_stats)
            self.assertIn('af_health', day_stats)

    def test_session_roi_calculation(self):
        """ROI = (net / total_buy_in) * 100."""
        _insert_tournament(self.repo, tournament_id='T100', buy_in=10.0, rake=1.0,
                          prize=25.0, position=3, date='2026-01-15')
        hand = _make_tournament_hand('h1', tournament_id='T100',
                                     date='2026-01-15T20:00:00')
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('h1', 'Hero', 'call', 0, is_hero=1, is_voluntary=1),
        ])
        self.repo.conn.commit()

        analyzer = TournamentAnalyzer(self.repo, '2026')
        reports = analyzer.get_daily_reports()
        # total_buy_in = 11.0, won=25, net=14.0, ROI = 14/11 * 100 = 127.3%
        self.assertAlmostEqual(reports[0]['session_roi'], 127.3, places=1)


# ── Daily EV Analysis Tests ──────────────────────────────────────

class TestDailyEvAnalysis(unittest.TestCase):
    """Test TournamentAnalyzer._get_daily_ev_analysis."""

    def test_no_hands_returns_zeros(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100', date='2026-01-15')
        repo.conn.commit()
        analyzer = TournamentAnalyzer(repo, '2026')
        result = analyzer._get_daily_ev_analysis('2026-01-15')
        self.assertEqual(result['total_hands'], 0)
        self.assertEqual(result['real_net'], 0)

    def test_day_ev_filters_by_day(self):
        conn, repo = _setup_db()
        _setup_multi_day_tournaments(repo)
        analyzer = TournamentAnalyzer(repo, '2026')

        day1_ev = analyzer._get_daily_ev_analysis('2026-01-15')
        day2_ev = analyzer._get_daily_ev_analysis('2026-01-16')

        # Day 1 has 8 hands (5 + 3), Day 2 has 4 hands
        self.assertEqual(day1_ev['total_hands'], 8)
        self.assertEqual(day2_ev['total_hands'], 4)

    def test_day_ev_has_all_fields(self):
        conn, repo = _setup_db()
        _setup_tournament_with_hands(repo)
        analyzer = TournamentAnalyzer(repo, '2026')
        result = analyzer._get_daily_ev_analysis('2026-01-15')

        for field in ('total_hands', 'allin_hands', 'real_net', 'ev_net',
                      'luck_factor', 'bb100_real', 'bb100_ev'):
            self.assertIn(field, result)

    def test_no_allin_hands_ev_equals_real(self):
        conn, repo = _setup_db()
        _setup_tournament_with_hands(repo)
        analyzer = TournamentAnalyzer(repo, '2026')
        result = analyzer._get_daily_ev_analysis('2026-01-15')
        # Without all-in data, EV should equal real
        self.assertEqual(result['real_net'], result['ev_net'])
        self.assertEqual(result['luck_factor'], 0)


# ── Report Rendering Tests ──────────────────────────────────────

class TestRenderSessionSparkline(unittest.TestCase):
    """Test _render_session_sparkline."""

    def test_empty_data_returns_empty(self):
        self.assertEqual(_render_session_sparkline([]), '')

    def test_single_point_returns_empty(self):
        self.assertEqual(_render_session_sparkline([{'hand': 1, 'chips': 100}]), '')

    def test_renders_svg_with_polyline(self):
        data = [{'hand': 1, 'chips': 100}, {'hand': 2, 'chips': 200}]
        html = _render_session_sparkline(data)
        self.assertIn('<svg', html)
        self.assertIn('polyline', html)
        self.assertIn('session-sparkline', html)

    def test_positive_uses_green_color(self):
        data = [{'hand': 1, 'chips': -50}, {'hand': 2, 'chips': 100}]
        html = _render_session_sparkline(data)
        self.assertIn('#00ff88', html)

    def test_negative_uses_red_color(self):
        data = [{'hand': 1, 'chips': 50}, {'hand': 2, 'chips': -100}]
        html = _render_session_sparkline(data)
        self.assertIn('#ff4444', html)

    def test_has_title(self):
        data = [{'hand': 1, 'chips': 100}, {'hand': 2, 'chips': 200}]
        html = _render_session_sparkline(data)
        self.assertIn('Chips da Sess', html)


class TestRenderSessionNotableHands(unittest.TestCase):
    """Test _render_session_notable_hands."""

    def test_empty_notable_returns_empty(self):
        self.assertEqual(_render_session_notable_hands(
            {'biggest_win': None, 'biggest_loss': None}), '')

    def test_renders_win_and_loss(self):
        notable = {
            'biggest_win': {'hero_cards': 'Ah Kh', 'invested': 200,
                           'won': 800, 'net': 600, 'blinds_sb': 50, 'blinds_bb': 100},
            'biggest_loss': {'hero_cards': '7d 2c', 'invested': 200,
                            'won': 0, 'net': -200, 'blinds_sb': 50, 'blinds_bb': 100},
        }
        html = _render_session_notable_hands(notable)
        self.assertIn('Not\u00e1veis da Sess', html)
        self.assertIn('hand-card win', html)
        self.assertIn('hand-card loss', html)

    def test_only_win(self):
        notable = {
            'biggest_win': {'hero_cards': 'Ah Kh', 'invested': 200,
                           'won': 800, 'net': 600, 'blinds_sb': 50, 'blinds_bb': 100},
            'biggest_loss': None,
        }
        html = _render_session_notable_hands(notable)
        self.assertIn('hand-card win', html)
        self.assertNotIn('hand-card loss', html)


class TestRenderSessionEvSummary(unittest.TestCase):
    """Test _render_session_ev_summary."""

    def test_empty_ev_returns_empty(self):
        self.assertEqual(_render_session_ev_summary({}), '')
        self.assertEqual(_render_session_ev_summary({'total_hands': 0}), '')

    def test_renders_ev_stats(self):
        day_ev = {
            'total_hands': 50,
            'allin_hands': 5,
            'real_net': 1000.0,
            'ev_net': 800.0,
            'luck_factor': 200.0,
            'bb100_real': 5.0,
            'bb100_ev': 4.0,
        }
        html = _render_session_ev_summary(day_ev)
        self.assertIn('EV da Sess', html)
        self.assertIn('All-in Hands', html)
        self.assertIn('bb/100 Real', html)
        self.assertIn('bb/100 EV', html)
        self.assertIn('Luck Factor', html)
        self.assertIn('acima do EV', html)

    def test_negative_luck_factor(self):
        day_ev = {
            'total_hands': 50, 'allin_hands': 5,
            'real_net': -500.0, 'ev_net': 100.0,
            'luck_factor': -600.0, 'bb100_real': -2.0, 'bb100_ev': 1.0,
        }
        html = _render_session_ev_summary(day_ev)
        self.assertIn('abaixo do EV', html)
        self.assertIn('negative', html)


class TestRenderSessionComparison(unittest.TestCase):
    """Test _render_session_comparison."""

    def test_empty_comparison_returns_empty(self):
        self.assertEqual(_render_session_comparison({}, []), '')

    def test_single_report_returns_empty(self):
        self.assertEqual(_render_session_comparison(
            {'net': {'best': 0, 'worst': 0, 'best_value': 10, 'worst_value': 10}},
            [{'date': '2026-01-15'}]), '')

    def test_renders_comparison_table(self):
        comparison = {
            'net': {'best': 0, 'worst': 1, 'best_value': 100.0, 'worst_value': -50.0},
            'roi': {'best': 0, 'worst': 1, 'best_value': 50.0, 'worst_value': -25.0},
        }
        reports = [
            {'date': '2026-01-15', 'net': 100, 'session_roi': 50},
            {'date': '2026-01-16', 'net': -50, 'session_roi': -25},
        ]
        html = _render_session_comparison(comparison, reports)
        self.assertIn('Comparativo entre Sess', html)
        self.assertIn('position-table', html)
        self.assertIn('2026-01-15', html)
        self.assertIn('2026-01-16', html)
        self.assertIn('Resultado', html)
        self.assertIn('ROI', html)


class TestRenderDaySummaryStatsWithHealth(unittest.TestCase):
    """Test _render_day_summary_stats with health badges."""

    def test_empty_returns_empty(self):
        self.assertEqual(_render_day_summary_stats({}), '')
        self.assertEqual(_render_day_summary_stats({'total_hands': 0}), '')

    def test_renders_health_badges(self):
        day_stats = {
            'total_hands': 50,
            'vpip': 25.0, 'vpip_health': 'good',
            'pfr': 20.0, 'pfr_health': 'good',
            'three_bet': 8.0, 'three_bet_health': 'good',
            'af': 2.5, 'af_health': 'good',
            'wtsd': 30.0, 'wtsd_health': 'good',
            'wsd': 50.0, 'wsd_health': 'good',
            'cbet': 65.0, 'cbet_health': 'good',
        }
        html = _render_day_summary_stats(day_stats)
        self.assertIn('badge-good', html)
        self.assertIn('Stats da Sess', html)
        self.assertIn('50 m\u00e3os', html)
        self.assertIn('VPIP', html)
        self.assertIn('PFR', html)

    def test_warning_badge(self):
        day_stats = {
            'total_hands': 50,
            'vpip': 35.0, 'vpip_health': 'warning',
            'pfr': 20.0, 'pfr_health': 'good',
            'three_bet': 8.0, 'three_bet_health': 'good',
            'af': 2.5, 'af_health': 'good',
            'wtsd': 30.0, 'wtsd_health': 'good',
            'wsd': 50.0, 'wsd_health': 'good',
            'cbet': 65.0, 'cbet_health': 'good',
        }
        html = _render_day_summary_stats(day_stats)
        self.assertIn('badge-warning', html)


class TestRenderDailyReport(unittest.TestCase):
    """Test _render_daily_report with session-focused layout."""

    def _make_report(self, **overrides):
        defaults = {
            'date': '2026-01-15',
            'tournament_count': 2,
            'total_buy_in': 22.0,
            'total_won': 50.0,
            'net': 28.0,
            'total_rake': 2.0,
            'rebuys': 0,
            'total_entries': 2,
            'itm_count': 1,
            'itm_rate': 50.0,
            'tournaments': [],
            'day_stats': {},
            'comparison': {},
            'session_sparkline': [],
            'session_notable': {'biggest_win': None, 'biggest_loss': None},
            'session_roi': 127.3,
            'day_ev': {},
            'total_hands': 20,
        }
        defaults.update(overrides)
        return defaults

    def test_renders_session_header(self):
        report = self._make_report()
        html = _render_daily_report(report)
        self.assertIn('15/01/2026', html)
        self.assertIn('$+28.00', html)

    def test_renders_roi(self):
        report = self._make_report()
        html = _render_daily_report(report)
        self.assertIn('ROI', html)
        self.assertIn('+127.3%', html)

    def test_renders_total_hands(self):
        report = self._make_report()
        html = _render_daily_report(report)
        self.assertIn('20', html)

    def test_renders_financial_summary(self):
        report = self._make_report()
        html = _render_daily_report(report)
        self.assertIn('Total Investido', html)
        self.assertIn('Total Ganho', html)
        self.assertIn('Resultado', html)
        self.assertIn('ITM', html)

    def test_renders_accordion_for_tournaments(self):
        report = self._make_report()
        html = _render_daily_report(report)
        self.assertIn('accordion-toggle', html)
        self.assertIn('accordion-content', html)
        self.assertIn('Ver detalhes dos torneios', html)

    def test_renders_session_sparkline_when_present(self):
        report = self._make_report(session_sparkline=[
            {'hand': 1, 'chips': 100}, {'hand': 2, 'chips': 200}
        ])
        html = _render_daily_report(report)
        self.assertIn('session-sparkline', html)

    def test_renders_session_ev_when_present(self):
        report = self._make_report(day_ev={
            'total_hands': 20, 'allin_hands': 2,
            'real_net': 500, 'ev_net': 400,
            'luck_factor': 100, 'bb100_real': 3.0, 'bb100_ev': 2.5,
        })
        html = _render_daily_report(report)
        self.assertIn('EV da Sess', html)

    def test_renders_session_notable_when_present(self):
        report = self._make_report(session_notable={
            'biggest_win': {'hero_cards': 'Ah Kh', 'invested': 200,
                           'won': 800, 'net': 600, 'blinds_sb': 50, 'blinds_bb': 100},
            'biggest_loss': None,
        })
        html = _render_daily_report(report)
        self.assertIn('Not\u00e1veis da Sess', html)

    def test_renders_day_stats_with_badges(self):
        report = self._make_report(day_stats={
            'total_hands': 20,
            'vpip': 25.0, 'vpip_health': 'good',
            'pfr': 20.0, 'pfr_health': 'good',
            'three_bet': 8.0, 'three_bet_health': 'good',
            'af': 2.5, 'af_health': 'good',
            'wtsd': 30.0, 'wtsd_health': 'good',
            'wsd': 50.0, 'wsd_health': 'good',
            'cbet': 65.0, 'cbet_health': 'good',
        })
        html = _render_daily_report(report)
        self.assertIn('badge-good', html)

    def test_negative_day_shows_red(self):
        report = self._make_report(net=-15.0, session_roi=-50.0)
        html = _render_daily_report(report)
        self.assertIn('negative', html)


# ── Full Report Integration Tests ──────────────────────────────

class TestGenerateReportIntegration(unittest.TestCase):
    """Integration tests for generate_tournament_report with session features."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.output_file = '/tmp/test_tournament_session_report.html'

    def tearDown(self):
        if os.path.exists(self.output_file):
            os.remove(self.output_file)

    def test_full_report_with_multi_day(self):
        _setup_multi_day_tournaments(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        result = generate_tournament_report(analyzer, self.output_file)

        self.assertEqual(result, self.output_file)
        self.assertTrue(os.path.exists(self.output_file))

        with open(self.output_file, 'r') as f:
            html = f.read()

        # Session comparison section
        self.assertIn('Comparativo entre Sess', html)
        # Session-focused daily reports
        self.assertIn('ROI', html)
        self.assertIn('Stats da Sess', html)
        # Accordion for tournament details
        self.assertIn('accordion-toggle', html)
        self.assertIn('Ver detalhes dos torneios', html)

    def test_report_has_session_sparklines(self):
        _setup_two_tournaments_same_day(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        generate_tournament_report(analyzer, self.output_file)

        with open(self.output_file, 'r') as f:
            html = f.read()

        self.assertIn('Chips da Sess', html)
        self.assertIn('session-sparkline', html)

    def test_report_single_day_no_session_comparison(self):
        """Single day should not render session comparison section."""
        _setup_tournament_with_hands(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        generate_tournament_report(analyzer, self.output_file)

        with open(self.output_file, 'r') as f:
            html = f.read()

        # Session comparison should not appear with single day
        self.assertNotIn('Comparativo entre Sess', html)

    def test_report_empty_database(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        result = generate_tournament_report(analyzer, self.output_file)
        self.assertTrue(os.path.exists(self.output_file))

    def test_report_preserves_tournament_accordion(self):
        """Individual tournament details should still be accessible via accordion."""
        _setup_two_tournaments_same_day(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        generate_tournament_report(analyzer, self.output_file)

        with open(self.output_file, 'r') as f:
            html = f.read()

        # Tournament cards should be inside accordion
        self.assertIn('tournament-card', html)
        self.assertIn('tournament-header', html)
        self.assertIn('toggleAccordion', html)

    def test_report_has_ev_per_session(self):
        _setup_multi_day_tournaments(self.repo)
        analyzer = TournamentAnalyzer(self.repo, '2026')
        generate_tournament_report(analyzer, self.output_file)

        with open(self.output_file, 'r') as f:
            html = f.read()

        # Each daily report should have EV section
        self.assertIn('EV da Sess', html)


# ── Edge Cases ───────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    """Edge cases for session-level features."""

    def test_tournament_with_zero_buy_in_roi(self):
        """ROI with zero buy-in should be 0."""
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100', buy_in=0.0, rake=0.0,
                          prize=10.0, position=1, date='2026-01-15')
        hand = _make_tournament_hand('h1', tournament_id='T100',
                                     date='2026-01-15T20:00:00')
        repo.insert_hand(hand)
        repo.insert_actions_batch([
            _make_action('h1', 'Hero', 'call', 0, is_hero=1, is_voluntary=1),
        ])
        repo.conn.commit()

        analyzer = TournamentAnalyzer(repo, '2026')
        reports = analyzer.get_daily_reports()
        # total_buy_in = 0, ROI should be 0 (avoid division by zero)
        self.assertEqual(reports[0]['session_roi'], 0.0)

    def test_sparkline_single_hand(self):
        """Session sparkline with single hand should have one point."""
        details = [{'sparkline': [{'hand': 1, 'chips': 500}]}]
        result = TournamentAnalyzer._get_session_sparkline(details)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['chips'], 500)

    def test_daily_notable_hands_empty_details(self):
        result = TournamentAnalyzer._get_daily_notable_hands([])
        self.assertIsNone(result['biggest_win'])
        self.assertIsNone(result['biggest_loss'])

    def test_aggregate_stats_zero_hands(self):
        details = [{'stats': {'total_hands': 0, 'vpip': 0}}]
        result = TournamentAnalyzer._aggregate_tournament_stats_with_health(details)
        self.assertEqual(result, {})

    def test_session_comparison_with_empty_reports(self):
        comparison = TournamentAnalyzer(
            Repository(sqlite3.connect(':memory:')), '2026'
        ).get_session_comparison([])
        self.assertEqual(comparison, {})


if __name__ == '__main__':
    unittest.main()
