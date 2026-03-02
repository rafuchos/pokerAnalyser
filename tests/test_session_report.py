"""Tests for US-005: Daily Report with Session Breakdown and Game Stats.

Covers:
- Repository: get_hands_for_session, get_actions_for_session
- CashAnalyzer: get_session_stats (VPIP%, PFR%, 3-Bet%, AF, WTSD%, W$SD%, CBet%)
- CashAnalyzer: get_session_sparkline (stack evolution data)
- CashAnalyzer: get_session_details (full session detail)
- CashAnalyzer: get_daily_reports_with_sessions (daily reports with session breakdown)
- CashAnalyzer: _aggregate_session_stats (weighted average day stats)
- CashAnalyzer: _build_session_comparison (best/worst per stat)
- Report: _render_session_card, _render_sparkline, _render_session_stats
- Report: _render_day_summary_stats, _render_session_comparison
- Report: _render_daily_report, _render_hand_card
- Report: full generate_cash_report with session sections
- Edge cases: no sessions, empty session, single hand session
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer
from src.reports.cash_report import (
    generate_cash_report,
    _render_sparkline,
    _render_session_stats,
    _render_session_card,
    _render_hand_card,
    _render_day_summary_stats,
    _render_session_comparison,
    _render_daily_report,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_hand(hand_id, date='2026-01-15T20:00:00', hero_position='CO', **kwargs):
    """Create a HandData with sensible defaults for testing."""
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='cash',
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


def _insert_hand_with_preflop_raise(repo, hand_id, date_str, hero_pos='CO',
                                     net=-1.0, invested=1.0, won=0.0):
    """Insert a hand + a hero open-raise preflop action."""
    hand = _make_hand(hand_id, date=date_str, hero_position=hero_pos,
                      net=net, invested=invested, won=won)
    repo.insert_hand(hand)
    repo.insert_actions_batch([
        _make_action(hand_id, 'V1', 'fold', 1, position='UTG'),
        _make_action(hand_id, 'Hero', 'raise', 2, position=hero_pos,
                     is_hero=1, amount=1.5, is_voluntary=1),
        _make_action(hand_id, 'V2', 'fold', 3, position='BTN'),
    ])
    return hand


def _insert_hand_with_call(repo, hand_id, date_str, hero_pos='CO',
                            net=-1.0, invested=1.0, won=0.0):
    """Insert a hand + hero call (VPIP but no PFR)."""
    hand = _make_hand(hand_id, date=date_str, hero_position=hero_pos,
                      net=net, invested=invested, won=won)
    repo.insert_hand(hand)
    repo.insert_actions_batch([
        _make_action(hand_id, 'V1', 'raise', 1, position='UTG',
                     amount=1.5, is_voluntary=1),
        _make_action(hand_id, 'Hero', 'call', 2, position=hero_pos,
                     is_hero=1, amount=1.5, is_voluntary=1),
    ])
    return hand


def _insert_hand_with_flop_action(repo, hand_id, date_str, hero_pos='CO',
                                   net=5.0, invested=3.0, won=8.0,
                                   hero_bets_flop=True, went_to_showdown=True):
    """Insert a hand with preflop raise + flop action for postflop stat testing."""
    hand = _make_hand(hand_id, date=date_str, hero_position=hero_pos,
                      net=net, invested=invested, won=won)
    repo.insert_hand(hand)
    actions = [
        # Preflop: Hero raises
        _make_action(hand_id, 'V1', 'fold', 1, position='UTG'),
        _make_action(hand_id, 'Hero', 'raise', 2, position=hero_pos,
                     is_hero=1, amount=1.5, is_voluntary=1),
        _make_action(hand_id, 'V2', 'call', 3, position='BTN',
                     amount=1.5, is_voluntary=1),
    ]
    # Flop actions
    if hero_bets_flop:
        actions.append(_make_action(hand_id, 'Hero', 'bet', 4,
                                    street='flop', position=hero_pos,
                                    is_hero=1, amount=2.0))
        actions.append(_make_action(hand_id, 'V2', 'call', 5,
                                    street='flop', position='BTN',
                                    amount=2.0))
    else:
        actions.append(_make_action(hand_id, 'Hero', 'check', 4,
                                    street='flop', position=hero_pos,
                                    is_hero=1))
        actions.append(_make_action(hand_id, 'V2', 'check', 5,
                                    street='flop', position='BTN'))

    if went_to_showdown:
        # Turn + river checks to showdown
        actions.append(_make_action(hand_id, 'Hero', 'check', 6,
                                    street='turn', position=hero_pos,
                                    is_hero=1))
        actions.append(_make_action(hand_id, 'V2', 'check', 7,
                                    street='turn', position='BTN'))
        actions.append(_make_action(hand_id, 'Hero', 'check', 8,
                                    street='river', position=hero_pos,
                                    is_hero=1))
        actions.append(_make_action(hand_id, 'V2', 'check', 9,
                                    street='river', position='BTN'))

    repo.insert_actions_batch(actions)
    return hand


# ── Repository Tests ─────────────────────────────────────────────────

class TestRepositorySessionQueries(unittest.TestCase):
    """Test Repository.get_hands_for_session and get_actions_for_session."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_get_hands_for_session_returns_matching_hands(self):
        """Hands within session time range are returned."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        # Hand within session
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00')
        # Hand outside session
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T22:00:00')

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        hands = self.repo.get_hands_for_session(session)
        self.assertEqual(len(hands), 1)
        self.assertEqual(hands[0]['hand_id'], 'H1')

    def test_get_hands_for_session_empty_when_no_match(self):
        """Returns empty list when no hands in session time range."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T22:00:00')

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        hands = self.repo.get_hands_for_session(session)
        self.assertEqual(len(hands), 0)

    def test_get_actions_for_session_returns_actions(self):
        """Actions for hands within session are returned."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T22:00:00')

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        actions = self.repo.get_actions_for_session(session)
        # H1 has 3 preflop actions
        self.assertEqual(len(actions), 3)
        self.assertTrue(all(a['hand_id'] == 'H1' for a in actions))

    def test_get_actions_for_session_includes_postflop(self):
        """Actions from all streets are returned for session hands."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_flop_action(self.repo, 'H1', '2026-01-15T20:00:00')

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        actions = self.repo.get_actions_for_session(session)
        streets = set(a['street'] for a in actions)
        self.assertIn('preflop', streets)
        self.assertIn('flop', streets)

    def test_get_hands_for_session_boundary_times(self):
        """Hands at session start/end times are included."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H_START', '2026-01-15T19:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H_END', '2026-01-15T21:00:00')

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        hands = self.repo.get_hands_for_session(session)
        self.assertEqual(len(hands), 2)


# ── Session Stats Tests ──────────────────────────────────────────────

class TestGetSessionStats(unittest.TestCase):
    """Test CashAnalyzer.get_session_stats()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_session_stats_vpip_pfr(self):
        """VPIP and PFR are correctly calculated per session."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        # 2 raises, 1 call = VPIP 100%, PFR 66.7%
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T19:30:00')
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T20:00:00')
        _insert_hand_with_call(self.repo, 'H3', '2026-01-15T20:30:00')

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        stats = self.analyzer.get_session_stats(session)

        self.assertEqual(stats['total_hands'], 3)
        self.assertAlmostEqual(stats['vpip'], 100.0)
        self.assertAlmostEqual(stats['pfr'], 66.7, places=1)

    def test_session_stats_health_badges(self):
        """Health badges are present for all tracked stats."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00')

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        stats = self.analyzer.get_session_stats(session)

        self.assertIn('vpip_health', stats)
        self.assertIn('pfr_health', stats)
        self.assertIn('three_bet_health', stats)
        self.assertIn('af_health', stats)
        self.assertIn('wtsd_health', stats)
        self.assertIn('wsd_health', stats)
        self.assertIn('cbet_health', stats)

    def test_session_stats_empty_session(self):
        """Empty session (no matching hands) returns empty dict."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        # No hands in this time range
        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        stats = self.analyzer.get_session_stats(session)
        self.assertEqual(stats, {})

    def test_session_stats_postflop(self):
        """Postflop stats (AF, WTSD, CBet) calculated per session."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        # Hand with flop action: hero is PFA, bets flop (CBet), goes to showdown
        _insert_hand_with_flop_action(self.repo, 'H1', '2026-01-15T20:00:00',
                                       hero_bets_flop=True, went_to_showdown=True)

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        stats = self.analyzer.get_session_stats(session)

        self.assertAlmostEqual(stats['cbet'], 100.0)
        self.assertAlmostEqual(stats['wtsd'], 100.0)

    def test_session_stats_three_bet(self):
        """3-Bet% calculated when hero faces a raise and re-raises."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        hand = _make_hand('H1', date='2026-01-15T20:00:00', hero_position='CO')
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'V1', 'raise', 1, position='UTG',
                         amount=1.5, is_voluntary=1),
            _make_action('H1', 'Hero', 'raise', 2, position='CO',
                         is_hero=1, amount=4.5, is_voluntary=1),
        ])

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        stats = self.analyzer.get_session_stats(session)
        self.assertAlmostEqual(stats['three_bet'], 100.0)


# ── Session Sparkline Tests ──────────────────────────────────────────

class TestGetSessionSparkline(unittest.TestCase):
    """Test CashAnalyzer.get_session_sparkline()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_sparkline_cumulative_profit(self):
        """Sparkline returns cumulative profit points."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T19:30:00',
                                         net=5.0)
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T20:00:00',
                                         net=-2.0)
        _insert_hand_with_preflop_raise(self.repo, 'H3', '2026-01-15T20:30:00',
                                         net=3.0)

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        sparkline = self.analyzer.get_session_sparkline(session)

        self.assertEqual(len(sparkline), 3)
        self.assertEqual(sparkline[0], {'hand': 1, 'profit': 5.0})
        self.assertEqual(sparkline[1], {'hand': 2, 'profit': 3.0})
        self.assertEqual(sparkline[2], {'hand': 3, 'profit': 6.0})

    def test_sparkline_empty_session(self):
        """Empty session returns empty sparkline."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        sparkline = self.analyzer.get_session_sparkline(session)
        self.assertEqual(sparkline, [])

    def test_sparkline_single_hand(self):
        """Single hand session returns one-element sparkline."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00',
                                         net=10.0)

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        sparkline = self.analyzer.get_session_sparkline(session)
        self.assertEqual(len(sparkline), 1)
        self.assertEqual(sparkline[0], {'hand': 1, 'profit': 10.0})


# ── Session Details Tests ────────────────────────────────────────────

class TestGetSessionDetails(unittest.TestCase):
    """Test CashAnalyzer.get_session_details()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_session_details_contains_all_fields(self):
        """Session details has all expected fields."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00',
                        buy_in=50.0, cash_out=75.0, profit=25.0,
                        hands_count=100, min_stack=35.0)
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00',
                                         net=5.0)

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        detail = self.analyzer.get_session_details(session)

        self.assertIn('session_id', detail)
        self.assertIn('start_time', detail)
        self.assertIn('end_time', detail)
        self.assertIn('duration_minutes', detail)
        self.assertIn('buy_in', detail)
        self.assertIn('cash_out', detail)
        self.assertIn('profit', detail)
        self.assertIn('hands_count', detail)
        self.assertIn('min_stack', detail)
        self.assertIn('stats', detail)
        self.assertIn('sparkline', detail)
        self.assertIn('biggest_win', detail)
        self.assertIn('biggest_loss', detail)

    def test_session_details_duration(self):
        """Duration is correctly calculated in minutes."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:30:00')

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        detail = self.analyzer.get_session_details(session)
        self.assertEqual(detail['duration_minutes'], 150)

    def test_session_details_notable_hands(self):
        """Biggest win/loss are found within session."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T19:30:00',
                                         net=10.0, invested=5.0, won=15.0)
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T20:00:00',
                                         net=-8.0, invested=8.0, won=0.0)
        _insert_hand_with_preflop_raise(self.repo, 'H3', '2026-01-15T20:30:00',
                                         net=2.0, invested=3.0, won=5.0)

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        detail = self.analyzer.get_session_details(session)

        self.assertEqual(detail['biggest_win']['hand_id'], 'H1')
        self.assertEqual(detail['biggest_loss']['hand_id'], 'H2')


# ── Daily Reports with Sessions Tests ────────────────────────────────

class TestGetDailyReportsWithSessions(unittest.TestCase):
    """Test CashAnalyzer.get_daily_reports_with_sessions()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_daily_report_contains_session_details(self):
        """Daily report contains session details for each session."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00',
                        buy_in=50.0, cash_out=70.0, profit=20.0)
        _create_session(self.repo, start_time='2026-01-15T22:00:00',
                        end_time='2026-01-15T23:30:00',
                        buy_in=50.0, cash_out=45.0, profit=-5.0)
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T22:30:00')

        reports = self.analyzer.get_daily_reports_with_sessions()
        self.assertEqual(len(reports), 1)

        report = reports[0]
        self.assertEqual(report['num_sessions'], 2)
        self.assertEqual(len(report['sessions']), 2)
        self.assertIn('stats', report['sessions'][0])
        self.assertIn('sparkline', report['sessions'][0])

    def test_daily_report_day_stats_weighted_average(self):
        """Day stats are weighted average of session stats."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _create_session(self.repo, start_time='2026-01-15T22:00:00',
                        end_time='2026-01-15T23:30:00')
        # Session 1: 2 hands, both raise (VPIP=100, PFR=100)
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T19:30:00')
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T20:00:00')
        # Session 2: 1 hand, call (VPIP=100, PFR=0)
        _insert_hand_with_call(self.repo, 'H3', '2026-01-15T22:30:00')

        reports = self.analyzer.get_daily_reports_with_sessions()
        day_stats = reports[0].get('day_stats', {})

        # Weighted avg: (100*2 + 100*1)/3 = 100 for VPIP
        # (100*2 + 0*1)/3 = 66.67 for PFR
        self.assertAlmostEqual(day_stats['vpip'], 100.0)
        self.assertAlmostEqual(day_stats['pfr'], 66.7, places=1)

    def test_daily_report_comparison_multiple_sessions(self):
        """Comparison data is built when 2+ sessions exist."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00',
                        profit=20.0)
        _create_session(self.repo, start_time='2026-01-15T22:00:00',
                        end_time='2026-01-15T23:30:00',
                        profit=-5.0)
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T22:30:00')

        reports = self.analyzer.get_daily_reports_with_sessions()
        comparison = reports[0].get('comparison', {})
        self.assertIn('profit', comparison)
        self.assertEqual(comparison['profit']['best'], 0)  # Session 1 won more
        self.assertEqual(comparison['profit']['worst'], 1)  # Session 2 lost

    def test_daily_report_no_comparison_single_session(self):
        """No comparison data when only one session."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00')

        reports = self.analyzer.get_daily_reports_with_sessions()
        comparison = reports[0].get('comparison', {})
        self.assertEqual(comparison, {})

    def test_daily_report_no_sessions(self):
        """Daily report works with 0 sessions (hands exist but no session records)."""
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00')

        reports = self.analyzer.get_daily_reports_with_sessions()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['num_sessions'], 0)
        self.assertEqual(reports[0]['sessions'], [])


# ── Aggregate Session Stats Tests ────────────────────────────────────

class TestAggregateSessionStats(unittest.TestCase):
    """Test CashAnalyzer._aggregate_session_stats()."""

    def test_weighted_average(self):
        """Weighted average is correct."""
        sessions = [
            {'stats': {'total_hands': 100, 'vpip': 25.0, 'pfr': 20.0,
                        'three_bet': 8.0, 'af': 2.5, 'wtsd': 30.0,
                        'wsd': 50.0, 'cbet': 70.0}},
            {'stats': {'total_hands': 50, 'vpip': 30.0, 'pfr': 15.0,
                        'three_bet': 10.0, 'af': 3.0, 'wtsd': 25.0,
                        'wsd': 55.0, 'cbet': 65.0}},
        ]
        result = CashAnalyzer._aggregate_session_stats(sessions)

        # VPIP: (25*100 + 30*50) / 150 = 4000/150 = 26.67
        self.assertAlmostEqual(result['vpip'], 26.67, places=2)
        # PFR: (20*100 + 15*50) / 150 = 2750/150 = 18.33
        self.assertAlmostEqual(result['pfr'], 18.33, places=2)
        self.assertEqual(result['total_hands'], 150)

    def test_empty_sessions(self):
        """Empty sessions list returns empty dict."""
        result = CashAnalyzer._aggregate_session_stats([])
        self.assertEqual(result, {})

    def test_single_session(self):
        """Single session returns its own stats."""
        sessions = [
            {'stats': {'total_hands': 50, 'vpip': 30.0, 'pfr': 20.0,
                        'three_bet': 8.0, 'af': 2.0, 'wtsd': 28.0,
                        'wsd': 52.0, 'cbet': 68.0}},
        ]
        result = CashAnalyzer._aggregate_session_stats(sessions)
        self.assertAlmostEqual(result['vpip'], 30.0)
        self.assertAlmostEqual(result['pfr'], 20.0)

    def test_session_with_no_hands_skipped(self):
        """Sessions with 0 hands are skipped in weighted average."""
        sessions = [
            {'stats': {'total_hands': 50, 'vpip': 30.0, 'pfr': 20.0,
                        'three_bet': 8.0, 'af': 2.0, 'wtsd': 28.0,
                        'wsd': 52.0, 'cbet': 68.0}},
            {'stats': {'total_hands': 0}},
        ]
        result = CashAnalyzer._aggregate_session_stats(sessions)
        self.assertAlmostEqual(result['vpip'], 30.0)
        self.assertEqual(result['total_hands'], 50)


# ── Session Comparison Tests ─────────────────────────────────────────

class TestBuildSessionComparison(unittest.TestCase):
    """Test CashAnalyzer._build_session_comparison()."""

    def test_comparison_identifies_best_worst(self):
        """Best/worst session indices are correctly identified."""
        sessions = [
            {'stats': {'total_hands': 50, 'vpip': 25.0, 'pfr': 20.0,
                        'af': 2.5, 'wtsd': 30.0, 'wsd': 50.0, 'cbet': 70.0},
             'profit': 20.0},
            {'stats': {'total_hands': 50, 'vpip': 35.0, 'pfr': 15.0,
                        'af': 1.5, 'wtsd': 25.0, 'wsd': 55.0, 'cbet': 60.0},
             'profit': -10.0},
        ]
        comp = CashAnalyzer._build_session_comparison(sessions)

        self.assertEqual(comp['profit']['best'], 0)
        self.assertEqual(comp['profit']['worst'], 1)
        self.assertEqual(comp['vpip']['best'], 1)  # Higher VPIP
        self.assertEqual(comp['vpip']['worst'], 0)

    def test_comparison_single_session(self):
        """Single session returns empty comparison."""
        sessions = [
            {'stats': {'total_hands': 50, 'vpip': 25.0}, 'profit': 10.0},
        ]
        comp = CashAnalyzer._build_session_comparison(sessions)
        self.assertEqual(comp, {})

    def test_comparison_empty(self):
        """Empty sessions returns empty comparison."""
        comp = CashAnalyzer._build_session_comparison([])
        self.assertEqual(comp, {})


# ── Report Rendering Tests ───────────────────────────────────────────

class TestRenderSparkline(unittest.TestCase):
    """Test _render_sparkline()."""

    def test_sparkline_renders_svg(self):
        """Sparkline renders valid SVG markup."""
        data = [{'hand': 1, 'profit': 0}, {'hand': 2, 'profit': 5},
                {'hand': 3, 'profit': 3}]
        html = _render_sparkline(data)
        self.assertIn('<svg', html)
        self.assertIn('polyline', html)
        self.assertIn('viewBox', html)

    def test_sparkline_positive_green(self):
        """Positive final profit uses green stroke."""
        data = [{'hand': 1, 'profit': 0}, {'hand': 2, 'profit': 10}]
        html = _render_sparkline(data)
        self.assertIn('#00ff88', html)

    def test_sparkline_negative_red(self):
        """Negative final profit uses red stroke."""
        data = [{'hand': 1, 'profit': 0}, {'hand': 2, 'profit': -5}]
        html = _render_sparkline(data)
        self.assertIn('#ff4444', html)

    def test_sparkline_zero_line(self):
        """Zero line shown when values span positive and negative."""
        data = [{'hand': 1, 'profit': -5}, {'hand': 2, 'profit': 5}]
        html = _render_sparkline(data)
        self.assertIn('stroke-dasharray', html)


class TestRenderSessionStats(unittest.TestCase):
    """Test _render_session_stats()."""

    def test_renders_all_stats(self):
        """All 7 stats are rendered with badges."""
        stats = {
            'total_hands': 50,
            'vpip': 25.0, 'vpip_health': 'good',
            'pfr': 20.0, 'pfr_health': 'good',
            'three_bet': 8.0, 'three_bet_health': 'good',
            'af': 2.5, 'af_health': 'good',
            'wtsd': 30.0, 'wtsd_health': 'good',
            'wsd': 50.0, 'wsd_health': 'warning',
            'cbet': 70.0, 'cbet_health': 'danger',
        }
        html = _render_session_stats(stats)
        self.assertIn('VPIP', html)
        self.assertIn('PFR', html)
        self.assertIn('3-Bet', html)
        self.assertIn('AF', html)
        self.assertIn('WTSD%', html)
        self.assertIn('W$SD%', html)
        self.assertIn('CBet%', html)
        self.assertIn('badge-good', html)
        self.assertIn('badge-warning', html)
        self.assertIn('badge-danger', html)


class TestRenderSessionCard(unittest.TestCase):
    """Test _render_session_card()."""

    def test_renders_session_card_with_all_info(self):
        """Session card contains all required elements."""
        sd = {
            'session_id': 1,
            'start_time': '2026-01-15T19:00:00',
            'end_time': '2026-01-15T21:00:00',
            'duration_minutes': 120,
            'buy_in': 50.0,
            'cash_out': 75.0,
            'profit': 25.0,
            'hands_count': 100,
            'min_stack': 35.0,
            'stats': {
                'total_hands': 100,
                'vpip': 25.0, 'vpip_health': 'good',
                'pfr': 20.0, 'pfr_health': 'good',
                'three_bet': 8.0, 'three_bet_health': 'good',
                'af': 2.5, 'af_health': 'good',
                'wtsd': 30.0, 'wtsd_health': 'good',
                'wsd': 50.0, 'wsd_health': 'good',
                'cbet': 70.0, 'cbet_health': 'good',
            },
            'sparkline': [{'hand': 1, 'profit': 0}, {'hand': 2, 'profit': 25}],
            'biggest_win': {'hero_cards': 'Ah Kd', 'invested': 5, 'won': 15,
                            'net': 10, 'blinds_sb': 0.25, 'blinds_bb': 0.5},
            'biggest_loss': None,
        }
        html = _render_session_card(sd, 1)

        self.assertIn('session-card', html)
        self.assertIn('session-header', html)
        self.assertIn('19:00 - 21:00', html)
        self.assertIn('$50.00', html)
        self.assertIn('$75.00', html)
        self.assertIn('$25.00', html)
        self.assertIn('100', html)
        self.assertIn('svg', html)
        self.assertIn('Ah Kd', html)

    def test_renders_session_card_without_stats(self):
        """Session card works when stats are empty."""
        sd = {
            'session_id': 1,
            'start_time': '2026-01-15T19:00:00',
            'end_time': '2026-01-15T21:00:00',
            'duration_minutes': 120,
            'buy_in': 50.0,
            'cash_out': 45.0,
            'profit': -5.0,
            'hands_count': 0,
            'min_stack': 0,
            'stats': {},
            'sparkline': [],
            'biggest_win': None,
            'biggest_loss': None,
        }
        html = _render_session_card(sd, 1)
        self.assertIn('session-card', html)
        self.assertNotIn('session-stats-grid', html)


class TestRenderHandCard(unittest.TestCase):
    """Test _render_hand_card()."""

    def test_win_card(self):
        """Win card has positive class and 'Lucro' label."""
        hand = {'hero_cards': 'Ah Kd', 'invested': 5, 'won': 15,
                'net': 10, 'blinds_sb': 0.25, 'blinds_bb': 0.5}
        html = _render_hand_card(hand, is_win=True)
        self.assertIn('hand-card win', html)
        self.assertIn('Lucro', html)
        self.assertIn('positive', html)

    def test_loss_card(self):
        """Loss card has negative class and 'Perda' label."""
        hand = {'hero_cards': 'Qh Qd', 'invested': 10, 'won': 0,
                'net': -10, 'blinds_sb': 0.25, 'blinds_bb': 0.5}
        html = _render_hand_card(hand, is_win=False)
        self.assertIn('hand-card loss', html)
        self.assertIn('Perda', html)
        self.assertIn('negative', html)


class TestRenderDaySummaryStats(unittest.TestCase):
    """Test _render_day_summary_stats()."""

    def test_renders_all_stats(self):
        """All 7 day stats are rendered."""
        day_stats = {
            'total_hands': 150,
            'vpip': 26.7, 'pfr': 18.3, 'three_bet': 9.0,
            'af': 2.7, 'wtsd': 28.0, 'wsd': 52.0, 'cbet': 68.0,
        }
        html = _render_day_summary_stats(day_stats)
        self.assertIn('VPIP', html)
        self.assertIn('PFR', html)
        self.assertIn('AF', html)
        self.assertIn('CBet%', html)
        self.assertIn('26.7%', html)


class TestRenderSessionComparison(unittest.TestCase):
    """Test _render_session_comparison()."""

    def test_renders_comparison_table(self):
        """Comparison table shows all stats for all sessions."""
        comparison = {
            'vpip': {'best': 1, 'worst': 0},
            'profit': {'best': 0, 'worst': 1},
        }
        sessions = [
            {'stats': {'vpip': 25.0, 'pfr': 20.0, 'af': 2.5,
                        'wtsd': 30.0, 'wsd': 50.0, 'cbet': 70.0},
             'profit': 20.0},
            {'stats': {'vpip': 35.0, 'pfr': 15.0, 'af': 1.5,
                        'wtsd': 25.0, 'wsd': 55.0, 'cbet': 60.0},
             'profit': -10.0},
        ]
        html = _render_session_comparison(comparison, sessions)
        self.assertIn('Comparativo', html)
        self.assertIn('S1', html)
        self.assertIn('S2', html)
        self.assertIn('VPIP', html)
        self.assertIn('Profit', html)


class TestRenderDailyReport(unittest.TestCase):
    """Test _render_daily_report()."""

    def test_renders_daily_report_with_sessions(self):
        """Daily report renders sessions and day summary."""
        report = {
            'date': '2026-01-15',
            'hands_count': 150,
            'total_won': 100.0,
            'total_lost': 50.0,
            'net': 50.0,
            'num_sessions': 2,
            'total_invested': 100.0,
            'sessions': [
                {
                    'session_id': 1,
                    'start_time': '2026-01-15T19:00:00',
                    'end_time': '2026-01-15T21:00:00',
                    'duration_minutes': 120,
                    'buy_in': 50.0, 'cash_out': 70.0, 'profit': 20.0,
                    'hands_count': 100, 'min_stack': 35.0,
                    'stats': {'total_hands': 100,
                              'vpip': 25.0, 'vpip_health': 'good',
                              'pfr': 20.0, 'pfr_health': 'good',
                              'three_bet': 8.0, 'three_bet_health': 'good',
                              'af': 2.5, 'af_health': 'good',
                              'wtsd': 30.0, 'wtsd_health': 'good',
                              'wsd': 50.0, 'wsd_health': 'good',
                              'cbet': 70.0, 'cbet_health': 'good'},
                    'sparkline': [{'hand': 1, 'profit': 0},
                                  {'hand': 2, 'profit': 20}],
                    'biggest_win': None, 'biggest_loss': None,
                },
                {
                    'session_id': 2,
                    'start_time': '2026-01-15T22:00:00',
                    'end_time': '2026-01-15T23:30:00',
                    'duration_minutes': 90,
                    'buy_in': 50.0, 'cash_out': 80.0, 'profit': 30.0,
                    'hands_count': 50, 'min_stack': 40.0,
                    'stats': {'total_hands': 50,
                              'vpip': 30.0, 'vpip_health': 'good',
                              'pfr': 22.0, 'pfr_health': 'good',
                              'three_bet': 10.0, 'three_bet_health': 'good',
                              'af': 3.0, 'af_health': 'good',
                              'wtsd': 28.0, 'wtsd_health': 'good',
                              'wsd': 55.0, 'wsd_health': 'warning',
                              'cbet': 65.0, 'cbet_health': 'good'},
                    'sparkline': [{'hand': 1, 'profit': 0},
                                  {'hand': 2, 'profit': 30}],
                    'biggest_win': None, 'biggest_loss': None,
                },
            ],
            'day_stats': {
                'total_hands': 150,
                'vpip': 26.7, 'pfr': 20.7, 'three_bet': 8.7,
                'af': 2.67, 'wtsd': 29.3, 'wsd': 51.7, 'cbet': 68.3,
            },
            'comparison': {
                'vpip': {'best': 1, 'worst': 0},
                'profit': {'best': 1, 'worst': 0},
            },
        }
        html = _render_daily_report(report)

        self.assertIn('daily-report', html)
        self.assertIn('<div class="session-accordion">', html)
        self.assertIn('<div class="session-card">', html)
        self.assertIn('day-summary-stats', html)
        self.assertIn('Comparativo', html)
        # Two sessions rendered
        self.assertEqual(html.count('<div class="session-header">'), 2)


# ── Full Report Integration Test ─────────────────────────────────────

class TestGenerateCashReportWithSessions(unittest.TestCase):
    """Test full generate_cash_report with session breakdown."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_report_generates_with_sessions(self):
        """Full report generates HTML with session accordion sections."""
        import tempfile
        import os

        # Create session and hands
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00',
                        buy_in=50.0, cash_out=75.0, profit=25.0,
                        hands_count=3, min_stack=35.0)
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T19:30:00',
                                         net=10.0, invested=5.0, won=15.0)
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T20:00:00',
                                         net=-3.0, invested=3.0, won=0.0)
        _insert_hand_with_call(self.repo, 'H3', '2026-01-15T20:30:00',
                                net=5.0, invested=2.0, won=7.0)

        analyzer = CashAnalyzer(self.repo, year='2026')

        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, 'cash_report.html')
            result = generate_cash_report(analyzer, outfile)
            self.assertEqual(result, outfile)

            with open(outfile, 'r', encoding='utf-8') as f:
                html = f.read()

            # Basic structure
            self.assertIn('<!DOCTYPE html>', html)
            self.assertIn('Resumo Geral', html)

            # Session accordion
            self.assertIn('session-accordion', html)
            self.assertIn('session-card', html)
            self.assertIn('session-header', html)

            # JavaScript for toggle
            self.assertIn('addEventListener', html)
            self.assertIn('toggle', html)

    def test_report_generates_without_sessions(self):
        """Report works when hands exist but no session records."""
        import tempfile
        import os

        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00',
                                         net=5.0)

        analyzer = CashAnalyzer(self.repo, year='2026')

        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, 'cash_report.html')
            result = generate_cash_report(analyzer, outfile)

            with open(outfile, 'r', encoding='utf-8') as f:
                html = f.read()

            self.assertIn('<!DOCTYPE html>', html)
            self.assertIn('Resumo Geral', html)
            # No session-accordion div when no sessions
            self.assertNotIn('<div class="session-accordion">', html)

    def test_report_responsive_css(self):
        """Report includes responsive CSS media queries."""
        import tempfile
        import os

        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T20:00:00')

        analyzer = CashAnalyzer(self.repo, year='2026')

        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, 'cash_report.html')
            generate_cash_report(analyzer, outfile)

            with open(outfile, 'r', encoding='utf-8') as f:
                html = f.read()

            self.assertIn('@media', html)
            self.assertIn('768px', html)
            self.assertIn('480px', html)

    def test_report_with_multiple_sessions_same_day(self):
        """Report handles multiple sessions on the same day."""
        import tempfile
        import os

        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00',
                        buy_in=50.0, cash_out=70.0, profit=20.0)
        _create_session(self.repo, start_time='2026-01-15T22:00:00',
                        end_time='2026-01-15T23:30:00',
                        buy_in=50.0, cash_out=45.0, profit=-5.0)

        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T19:30:00',
                                         net=10.0, invested=5.0, won=15.0)
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T22:30:00',
                                         net=-5.0, invested=5.0, won=0.0)

        analyzer = CashAnalyzer(self.repo, year='2026')

        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, 'cash_report.html')
            generate_cash_report(analyzer, outfile)

            with open(outfile, 'r', encoding='utf-8') as f:
                html = f.read()

            # Two session header divs
            self.assertEqual(html.count('<div class="session-header">'), 2)
            # Comparison table
            self.assertIn('Comparativo', html)
            # Day summary stats
            self.assertIn('<div class="day-summary-stats">', html)


# ── Edge Cases ───────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    """Test edge cases for session handling."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_session_with_all_losing_hands(self):
        """Session where all hands are losses."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00',
                        profit=-30.0)
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T19:30:00',
                                         net=-10.0)
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T20:00:00',
                                         net=-20.0)

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        detail = self.analyzer.get_session_details(session)

        self.assertIsNone(detail['biggest_win'])
        self.assertEqual(detail['biggest_loss']['hand_id'], 'H2')

    def test_session_with_all_winning_hands(self):
        """Session where all hands are wins."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00',
                        profit=30.0)
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T19:30:00',
                                         net=10.0, won=11.0)
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T20:00:00',
                                         net=20.0, won=21.0)

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        detail = self.analyzer.get_session_details(session)

        self.assertEqual(detail['biggest_win']['hand_id'], 'H2')
        self.assertIsNone(detail['biggest_loss'])

    def test_multiple_days_each_with_sessions(self):
        """Multiple days each with their own sessions."""
        # Day 1
        _create_session(self.repo, date='2026-01-15',
                        start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'D1H1', '2026-01-15T20:00:00')

        # Day 2
        _create_session(self.repo, date='2026-01-16',
                        start_time='2026-01-16T19:00:00',
                        end_time='2026-01-16T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'D2H1', '2026-01-16T20:00:00')

        reports = self.analyzer.get_daily_reports_with_sessions()
        self.assertEqual(len(reports), 2)
        for r in reports:
            self.assertEqual(r['num_sessions'], 1)

    def test_sparkline_all_zero_profit(self):
        """Sparkline handles all zero net values."""
        _create_session(self.repo, start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _insert_hand_with_preflop_raise(self.repo, 'H1', '2026-01-15T19:30:00',
                                         net=0.0)
        _insert_hand_with_preflop_raise(self.repo, 'H2', '2026-01-15T20:00:00',
                                         net=0.0)

        session = self.repo.get_sessions_for_day('2026-01-15')[0]
        sparkline = self.analyzer.get_session_sparkline(session)
        self.assertEqual(len(sparkline), 2)
        self.assertEqual(sparkline[0]['profit'], 0.0)
        self.assertEqual(sparkline[1]['profit'], 0.0)

        # Rendering shouldn't crash
        html = _render_sparkline(sparkline)
        self.assertIn('svg', html)


if __name__ == '__main__':
    unittest.main()
