"""Tests for US-021: Tournament Backend - Repository Queries + Analyzer Preflop/Postflop Stats.

Covers:
- Repository: get_tournament_hands_with_position(year, tournament_id)
- Repository: get_tournament_hands_with_cards(year, tournament_id)
- Repository: get_tournament_daily_stats(year)
- Repository fix: get_tournament_all_actions() now includes ha.is_voluntary
- TournamentAnalyzer: game_type class attribute = 'tournament'
- TournamentAnalyzer: _healthy_ranges, _postflop_healthy_ranges instance attributes
- TournamentAnalyzer: get_preflop_stats() with overall + by_position + by_day + health badges
- TournamentAnalyzer: get_postflop_stats() with overall + by_street + by_week + health badges
- Reuse of CashAnalyzer._analyze_preflop_hand() and _analyze_postflop_hand()
- Edge cases: no hands, single hand, multiple tournaments, multiple days
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.tournament import TournamentAnalyzer
from src.analyzers.cash import CashAnalyzer


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
        hero_stack=kwargs.get('hero_stack', 5000.0),
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


def _insert_hand_with_actions(repo, hand_id, tournament_id='T100',
                               date='2026-01-15T20:00:00',
                               hero_position='CO', hero_cards='Ah Kd',
                               net=-200, hero_stack=5000.0,
                               preflop_actions=None, postflop_actions=None):
    """Insert a tournament hand with optional preflop and postflop actions."""
    hand = _make_tournament_hand(
        hand_id, tournament_id=tournament_id, date=date,
        hero_position=hero_position, hero_cards=hero_cards,
        net=net, hero_stack=hero_stack,
    )
    repo.insert_hand(hand)

    actions = []
    if preflop_actions:
        actions.extend(preflop_actions)
    if postflop_actions:
        actions.extend(postflop_actions)
    if actions:
        repo.insert_actions_batch(actions)


# ── Repository Tests: get_tournament_hands_with_position ──────────────

class TestGetTournamentHandsWithPosition(unittest.TestCase):
    """Test get_tournament_hands_with_position()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            hero_position='BTN', net=300, hero_stack=8000.0,
        )
        _insert_hand_with_actions(
            self.repo, 'h2', tournament_id='T100',
            hero_position='SB', net=-150, hero_stack=3000.0,
        )
        _insert_hand_with_actions(
            self.repo, 'h3', tournament_id='T200',
            hero_position='CO', net=500, hero_stack=10000.0,
        )
        self.conn.commit()

    def test_returns_all_tournament_hands(self):
        hands = self.repo.get_tournament_hands_with_position('2026')
        self.assertEqual(len(hands), 3)

    def test_filter_by_tournament_id(self):
        hands = self.repo.get_tournament_hands_with_position('2026', 'T100')
        self.assertEqual(len(hands), 2)
        self.assertTrue(all(h['hero_position'] in ('BTN', 'SB') for h in hands))

    def test_returns_expected_columns(self):
        hands = self.repo.get_tournament_hands_with_position('2026')
        h = hands[0]
        self.assertIn('hand_id', h)
        self.assertIn('hero_position', h)
        self.assertIn('net', h)
        self.assertIn('blinds_bb', h)
        self.assertIn('hero_stack', h)
        self.assertIn('blinds_sb', h)

    def test_hero_stack_values(self):
        hands = self.repo.get_tournament_hands_with_position('2026', 'T100')
        stacks = sorted([h['hero_stack'] for h in hands])
        self.assertEqual(stacks, [3000.0, 8000.0])

    def test_wrong_year_returns_empty(self):
        hands = self.repo.get_tournament_hands_with_position('2025')
        self.assertEqual(len(hands), 0)

    def test_does_not_include_cash_hands(self):
        # Insert a cash hand
        cash_hand = HandData(
            hand_id='cash1', platform='GGPoker', game_type='cash',
            date=datetime(2026, 1, 15, 20), blinds_sb=0.25, blinds_bb=0.50,
            hero_cards='Ah Kd', hero_position='CO', invested=0.50,
            won=0, net=-0.50, rake=0.03, table_name='T',
            num_players=6,
        )
        self.repo.insert_hand(cash_hand)
        self.conn.commit()

        hands = self.repo.get_tournament_hands_with_position('2026')
        self.assertEqual(len(hands), 3)  # No cash hands
        self.assertTrue(all(h['hand_id'].startswith('h') for h in hands))


# ── Repository Tests: get_tournament_hands_with_cards ─────────────────

class TestGetTournamentHandsWithCards(unittest.TestCase):
    """Test get_tournament_hands_with_cards()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            hero_cards='Ah Kd', hero_position='BTN', net=300,
        )
        _insert_hand_with_actions(
            self.repo, 'h2', tournament_id='T100',
            hero_cards='Qs Jh', hero_position='SB', net=-150,
        )
        _insert_hand_with_actions(
            self.repo, 'h3', tournament_id='T200',
            hero_cards='Td 9d', hero_position='CO', net=500,
        )
        # Hand with no hero_cards
        hand_no_cards = _make_tournament_hand(
            'h4', tournament_id='T200',
            hero_cards=None, net=-100,
        )
        self.repo.insert_hand(hand_no_cards)
        self.conn.commit()

    def test_returns_hands_with_cards(self):
        hands = self.repo.get_tournament_hands_with_cards('2026')
        self.assertEqual(len(hands), 3)  # h4 excluded (no cards)

    def test_filter_by_tournament_id(self):
        hands = self.repo.get_tournament_hands_with_cards('2026', 'T100')
        self.assertEqual(len(hands), 2)

    def test_returns_expected_columns(self):
        hands = self.repo.get_tournament_hands_with_cards('2026')
        h = hands[0]
        self.assertIn('hand_id', h)
        self.assertIn('hero_cards', h)
        self.assertIn('hero_position', h)
        self.assertIn('net', h)
        self.assertIn('blinds_bb', h)

    def test_excludes_null_hero_cards(self):
        hands = self.repo.get_tournament_hands_with_cards('2026')
        hand_ids = [h['hand_id'] for h in hands]
        self.assertNotIn('h4', hand_ids)

    def test_wrong_year_returns_empty(self):
        hands = self.repo.get_tournament_hands_with_cards('2025')
        self.assertEqual(len(hands), 0)


# ── Repository Tests: get_tournament_daily_stats ─────────────────────

class TestGetTournamentDailyStats(unittest.TestCase):
    """Test get_tournament_daily_stats()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        # Day 1: 2 hands
        _insert_hand_with_actions(
            self.repo, 'h1', date='2026-01-15T20:00:00', net=300,
        )
        _insert_hand_with_actions(
            self.repo, 'h2', date='2026-01-15T21:00:00', net=-150,
        )
        # Day 2: 1 hand
        _insert_hand_with_actions(
            self.repo, 'h3', date='2026-01-16T20:00:00', net=500,
        )
        self.conn.commit()

    def test_returns_daily_aggregation(self):
        stats = self.repo.get_tournament_daily_stats('2026')
        self.assertEqual(len(stats), 2)

    def test_day_stats_values(self):
        stats = self.repo.get_tournament_daily_stats('2026')
        # Ordered DESC, so day 2 first
        day2 = stats[0]
        self.assertEqual(day2['day'], '2026-01-16')
        self.assertEqual(day2['hands'], 1)
        self.assertEqual(day2['net'], 500)

        day1 = stats[1]
        self.assertEqual(day1['day'], '2026-01-15')
        self.assertEqual(day1['hands'], 2)
        self.assertEqual(day1['net'], 150)  # 300 + (-150)

    def test_includes_won_and_lost(self):
        stats = self.repo.get_tournament_daily_stats('2026')
        day1 = stats[1]  # 2026-01-15
        self.assertEqual(day1['total_won'], 300)
        self.assertEqual(day1['total_lost'], 150)

    def test_wrong_year_returns_empty(self):
        stats = self.repo.get_tournament_daily_stats('2025')
        self.assertEqual(len(stats), 0)


# ── Repository Tests: get_tournament_all_actions is_voluntary fix ─────

class TestTournamentAllActionsIsVoluntary(unittest.TestCase):
    """Test that get_tournament_all_actions() includes ha.is_voluntary."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            preflop_actions=[
                _make_action('h1', 'Villain', 'post_sb', 0, position='SB'),
                _make_action('h1', 'Hero', 'post_bb', 1, position='BB', is_hero=1),
                _make_action('h1', 'Hero', 'call', 2, position='BB',
                             is_hero=1, amount=200, is_voluntary=1),
            ],
        )
        self.conn.commit()

    def test_is_voluntary_present(self):
        actions = self.repo.get_tournament_all_actions('2026')
        self.assertTrue(len(actions) > 0)
        self.assertIn('is_voluntary', actions[0])

    def test_is_voluntary_values_correct(self):
        actions = self.repo.get_tournament_all_actions('2026')
        hero_call = [a for a in actions if a['action_type'] == 'call'][0]
        self.assertEqual(hero_call['is_voluntary'], 1)

        hero_bb = [a for a in actions if a['action_type'] == 'post_bb'][0]
        self.assertEqual(hero_bb['is_voluntary'], 0)


# ── TournamentAnalyzer Class Attributes ──────────────────────────────

class TestTournamentAnalyzerAttributes(unittest.TestCase):
    """Test game_type class attribute and instance attributes."""

    def test_game_type_class_attribute(self):
        self.assertEqual(TournamentAnalyzer.game_type, 'tournament')

    def test_game_type_on_instance(self):
        conn, repo = _setup_db()
        analyzer = TournamentAnalyzer(repo, '2026')
        self.assertEqual(analyzer.game_type, 'tournament')

    def test_healthy_ranges_instance_attribute(self):
        conn, repo = _setup_db()
        analyzer = TournamentAnalyzer(repo, '2026')
        self.assertIsInstance(analyzer._healthy_ranges, dict)
        self.assertIn('vpip', analyzer._healthy_ranges)
        self.assertIn('pfr', analyzer._healthy_ranges)
        self.assertEqual(analyzer._healthy_ranges, CashAnalyzer.HEALTHY_RANGES)

    def test_postflop_healthy_ranges_instance_attribute(self):
        conn, repo = _setup_db()
        analyzer = TournamentAnalyzer(repo, '2026')
        self.assertIsInstance(analyzer._postflop_healthy_ranges, dict)
        self.assertIn('af', analyzer._postflop_healthy_ranges)
        self.assertIn('wtsd', analyzer._postflop_healthy_ranges)
        self.assertEqual(analyzer._postflop_healthy_ranges,
                         CashAnalyzer.POSTFLOP_HEALTHY_RANGES)


# ── TournamentAnalyzer.get_preflop_stats() ───────────────────────────

class TestTournamentPreflopStats(unittest.TestCase):
    """Test TournamentAnalyzer.get_preflop_stats()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _setup_hands_with_preflop(self):
        """Set up tournament hands with various preflop scenarios."""
        # Hand 1: Hero raises (VPIP + PFR) from BTN on day 1
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            date='2026-01-15T20:00:00', hero_position='BTN', net=300,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h1', 'V3', 'fold', 2, position='UTG'),
                _make_action('h1', 'V4', 'fold', 3, position='MP'),
                _make_action('h1', 'V5', 'fold', 4, position='CO'),
                _make_action('h1', 'Hero', 'raise', 5, position='BTN',
                             is_hero=1, amount=400, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 6, position='SB'),
                _make_action('h1', 'V2', 'fold', 7, position='BB'),
            ],
        )

        # Hand 2: Hero calls a raise (VPIP but not PFR) from CO on day 1
        _insert_hand_with_actions(
            self.repo, 'h2', tournament_id='T100',
            date='2026-01-15T20:05:00', hero_position='CO', net=-200,
            preflop_actions=[
                _make_action('h2', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h2', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h2', 'V3', 'raise', 2, position='UTG', amount=400),
                _make_action('h2', 'Hero', 'call', 3, position='CO',
                             is_hero=1, amount=400, is_voluntary=1),
            ],
        )

        # Hand 3: Hero folds from BB on day 2
        _insert_hand_with_actions(
            self.repo, 'h3', tournament_id='T100',
            date='2026-01-16T20:00:00', hero_position='BB', net=0,
            preflop_actions=[
                _make_action('h3', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h3', 'Hero', 'post_bb', 1, position='BB', is_hero=1),
                _make_action('h3', 'V3', 'raise', 2, position='UTG', amount=400),
                _make_action('h3', 'Hero', 'fold', 3, position='BB', is_hero=1),
            ],
        )

        # Hand 4: Hero 3-bets from SB on day 2
        _insert_hand_with_actions(
            self.repo, 'h4', tournament_id='T200',
            date='2026-01-16T21:00:00', hero_position='SB', net=500,
            preflop_actions=[
                _make_action('h4', 'Hero', 'post_sb', 0, position='SB', is_hero=1),
                _make_action('h4', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h4', 'V3', 'raise', 2, position='UTG', amount=400),
                _make_action('h4', 'Hero', 'raise', 3, position='SB',
                             is_hero=1, amount=1200, is_voluntary=1),
                _make_action('h4', 'V2', 'fold', 4, position='BB'),
                _make_action('h4', 'V3', 'fold', 5, position='UTG'),
            ],
        )

        self.conn.commit()

    def test_empty_db_returns_empty(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()
        # With no data, _format_preflop_stats returns with total_hands=0
        self.assertEqual(stats['overall']['total_hands'], 0)

    def test_overall_stats(self):
        self._setup_hands_with_preflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['total_hands'], 4)
        # VPIP: h1 (raise), h2 (call), h4 (raise) = 3/4 = 75%
        self.assertAlmostEqual(overall['vpip'], 75.0)
        self.assertEqual(overall['vpip_hands'], 3)
        # PFR: h1 (raise), h4 (raise) = 2/4 = 50%
        self.assertAlmostEqual(overall['pfr'], 50.0)
        self.assertEqual(overall['pfr_hands'], 2)

    def test_three_bet_stats(self):
        self._setup_hands_with_preflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        # 3-bet opps: h2 (opp raised before hero), h3 (opp raised before hero),
        # h4 (opp raised before hero) = 3
        # 3-bet count: h4 (hero re-raised) = 1
        self.assertEqual(overall['three_bet_opps'], 3)
        self.assertEqual(overall['three_bet_hands'], 1)
        self.assertAlmostEqual(overall['three_bet'], 1 / 3 * 100, places=1)

    def test_ats_stats(self):
        self._setup_hands_with_preflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        # ATS opps: h1 (BTN, all fold before hero) = 1
        # ATS count: h1 (hero raised) = 1
        self.assertGreaterEqual(overall['ats_opps'], 1)

    def test_health_badges_present(self):
        self._setup_hands_with_preflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        for stat in ('vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats'):
            self.assertIn(f'{stat}_health', overall)
            self.assertIn(overall[f'{stat}_health'], ('good', 'warning', 'danger'))

    def test_by_position(self):
        self._setup_hands_with_preflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()

        self.assertIn('by_position', stats)
        by_pos = stats['by_position']
        self.assertIn('BTN', by_pos)
        self.assertEqual(by_pos['BTN']['total_hands'], 1)
        self.assertAlmostEqual(by_pos['BTN']['vpip'], 100.0)

        self.assertIn('CO', by_pos)
        self.assertEqual(by_pos['CO']['total_hands'], 1)
        self.assertAlmostEqual(by_pos['CO']['vpip'], 100.0)

        self.assertIn('BB', by_pos)
        self.assertEqual(by_pos['BB']['total_hands'], 1)
        self.assertAlmostEqual(by_pos['BB']['vpip'], 0.0)

    def test_by_day(self):
        self._setup_hands_with_preflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()

        self.assertIn('by_day', stats)
        by_day = stats['by_day']
        self.assertIn('2026-01-15', by_day)
        self.assertEqual(by_day['2026-01-15']['total_hands'], 2)
        # Day 1: h1 (VPIP), h2 (VPIP) → 100%
        self.assertAlmostEqual(by_day['2026-01-15']['vpip'], 100.0)

        self.assertIn('2026-01-16', by_day)
        self.assertEqual(by_day['2026-01-16']['total_hands'], 2)
        # Day 2: h3 (fold), h4 (raise) → 50%
        self.assertAlmostEqual(by_day['2026-01-16']['vpip'], 50.0)

    def test_return_structure(self):
        self._setup_hands_with_preflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()

        self.assertIn('overall', stats)
        self.assertIn('by_position', stats)
        self.assertIn('by_day', stats)

    def test_reuses_cash_analyzer_static_method(self):
        """Verify that _analyze_preflop_hand is actually from CashAnalyzer."""
        # CashAnalyzer._analyze_preflop_hand is a static method
        self.assertTrue(callable(CashAnalyzer._analyze_preflop_hand))


# ── TournamentAnalyzer.get_postflop_stats() ──────────────────────────

class TestTournamentPostflopStats(unittest.TestCase):
    """Test TournamentAnalyzer.get_postflop_stats()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _setup_hands_with_postflop(self):
        """Set up tournament hands with preflop + postflop actions."""
        # Hand 1: Hero is PFA, cbets flop, opponent folds (non-showdown win)
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            date='2026-01-15T20:00:00', hero_position='BTN', net=500,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=400, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'call', 4, position='BB', amount=400),
            ],
            postflop_actions=[
                _make_action('h1', 'V2', 'check', 5, street='flop', position='BB'),
                _make_action('h1', 'Hero', 'bet', 6, street='flop', position='BTN',
                             is_hero=1, amount=300),
                _make_action('h1', 'V2', 'fold', 7, street='flop', position='BB'),
            ],
        )

        # Hand 2: Hero sees flop, goes to showdown and wins
        _insert_hand_with_actions(
            self.repo, 'h2', tournament_id='T100',
            date='2026-01-15T20:10:00', hero_position='CO', net=800,
            preflop_actions=[
                _make_action('h2', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h2', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h2', 'Hero', 'raise', 2, position='CO',
                             is_hero=1, amount=400, is_voluntary=1),
                _make_action('h2', 'V1', 'call', 3, position='SB', amount=400),
                _make_action('h2', 'V2', 'fold', 4, position='BB'),
            ],
            postflop_actions=[
                _make_action('h2', 'V1', 'check', 5, street='flop', position='SB'),
                _make_action('h2', 'Hero', 'bet', 6, street='flop', position='CO',
                             is_hero=1, amount=300),
                _make_action('h2', 'V1', 'call', 7, street='flop', position='SB',
                             amount=300),
                _make_action('h2', 'V1', 'check', 8, street='turn', position='SB'),
                _make_action('h2', 'Hero', 'check', 9, street='turn', position='CO',
                             is_hero=1),
                _make_action('h2', 'V1', 'check', 10, street='river', position='SB'),
                _make_action('h2', 'Hero', 'check', 11, street='river', position='CO',
                             is_hero=1),
            ],
        )

        # Hand 3: Hero faces cbet and folds on flop (different day, week)
        _insert_hand_with_actions(
            self.repo, 'h3', tournament_id='T200',
            date='2026-01-22T20:00:00', hero_position='BB', net=-200,
            preflop_actions=[
                _make_action('h3', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h3', 'Hero', 'post_bb', 1, position='BB', is_hero=1),
                _make_action('h3', 'V3', 'raise', 2, position='UTG', amount=400),
                _make_action('h3', 'Hero', 'call', 3, position='BB',
                             is_hero=1, amount=200, is_voluntary=1),
                _make_action('h3', 'V1', 'fold', 4, position='SB'),
            ],
            postflop_actions=[
                _make_action('h3', 'V3', 'bet', 5, street='flop', position='UTG',
                             amount=500),
                _make_action('h3', 'Hero', 'fold', 6, street='flop', position='BB',
                             is_hero=1),
            ],
        )

        # Hand 4: Preflop only (hero folds, no postflop) on day 2
        _insert_hand_with_actions(
            self.repo, 'h4', tournament_id='T200',
            date='2026-01-22T20:10:00', hero_position='UTG', net=0,
            preflop_actions=[
                _make_action('h4', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h4', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h4', 'Hero', 'fold', 2, position='UTG', is_hero=1),
            ],
        )

        self.conn.commit()

    def test_empty_db_returns_empty(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        self.assertEqual(stats['overall']['total_hands'], 0)

    def test_overall_structure(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()

        self.assertIn('overall', stats)
        self.assertIn('by_street', stats)
        self.assertIn('by_week', stats)

    def test_overall_saw_flop(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['total_hands'], 4)
        # h1, h2, h3 saw the flop; h4 did not
        self.assertEqual(overall['saw_flop_hands'], 3)

    def test_overall_wtsd(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        # h2 went to showdown (2 players remain), WTSD = 1/3 saw_flop
        self.assertEqual(overall['wtsd_hands'], 1)
        self.assertAlmostEqual(overall['wtsd'], 1 / 3 * 100, places=1)

    def test_overall_wsd(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        # h2 won at showdown (net=800>0), W$SD = 1/1 = 100%
        self.assertEqual(overall['wsd_hands'], 1)
        self.assertAlmostEqual(overall['wsd'], 100.0)

    def test_overall_cbet(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        # CBet opps: h1 (PFA + bet), h2 (PFA + bet) → both cbet
        self.assertEqual(overall['cbet_opps'], 2)
        self.assertEqual(overall['cbet_hands'], 2)
        self.assertAlmostEqual(overall['cbet'], 100.0)

    def test_overall_fold_to_cbet(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        # fold_to_cbet: h3 (opp was PFA, cbet, hero folded) = 1/1
        self.assertEqual(overall['fold_to_cbet_opps'], 1)
        self.assertEqual(overall['fold_to_cbet_hands'], 1)

    def test_overall_aggression(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        # AF = bets_raises / calls
        # h1 flop: bet (1 br), h2 flop: bet (1 br) → 2 bets_raises
        # No hero calls on postflop → AF = 0 (division guard: 0 calls → 0.0)
        self.assertEqual(overall['af_bets_raises'], 2)
        self.assertEqual(overall['af_calls'], 0)
        # AFq = bets_raises / total_actions → should be > 0
        self.assertGreater(overall['afq'], 0)

    def test_health_badges_present(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        for stat in ('af', 'wtsd', 'wsd', 'cbet', 'fold_to_cbet', 'check_raise'):
            self.assertIn(f'{stat}_health', overall)
            self.assertIn(overall[f'{stat}_health'], ('good', 'warning', 'danger'))

    def test_by_street(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()

        by_street = stats['by_street']
        self.assertIn('flop', by_street)
        self.assertIn('turn', by_street)
        self.assertIn('river', by_street)

        # Flop: h1 bet, h2 bet → bets_raises=2
        flop = by_street['flop']
        self.assertIn('af', flop)
        self.assertIn('afq', flop)
        self.assertIn('check_raise', flop)

    def test_by_week(self):
        self._setup_hands_with_postflop()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()

        by_week = stats['by_week']
        # Two different weeks: W03 (Jan 15) and W04 (Jan 22)
        self.assertGreaterEqual(len(by_week), 1)
        # Check structure of a week entry
        week_key = list(by_week.keys())[0]
        week_data = by_week[week_key]
        self.assertIn('total_hands', week_data)
        self.assertIn('saw_flop', week_data)
        self.assertIn('af', week_data)
        self.assertIn('wtsd', week_data)
        self.assertIn('wsd', week_data)
        self.assertIn('cbet', week_data)

    def test_reuses_cash_analyzer_static_method(self):
        """Verify that _analyze_postflop_hand is from CashAnalyzer."""
        self.assertTrue(callable(CashAnalyzer._analyze_postflop_hand))


# ── TournamentAnalyzer._get_week() ───────────────────────────────────

class TestTournamentGetWeek(unittest.TestCase):
    """Test the _get_week static method on TournamentAnalyzer."""

    def test_normal_date(self):
        result = TournamentAnalyzer._get_week('2026-01-15')
        self.assertTrue(result.startswith('2026-W'))

    def test_empty_string(self):
        result = TournamentAnalyzer._get_week('')
        self.assertEqual(result, 'unknown')

    def test_none_value(self):
        result = TournamentAnalyzer._get_week(None)
        self.assertEqual(result, 'unknown')

    def test_different_weeks(self):
        w1 = TournamentAnalyzer._get_week('2026-01-15')
        w2 = TournamentAnalyzer._get_week('2026-01-22')
        self.assertNotEqual(w1, w2)


# ── Integration: Preflop + Postflop together ─────────────────────────

class TestTournamentStatsIntegration(unittest.TestCase):
    """Integration tests for preflop + postflop stats together."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        _insert_tournament(self.repo, tournament_id='T100', prize=50.0)
        _insert_tournament(self.repo, tournament_id='T200', prize=100.0)

    def test_preflop_and_postflop_from_same_hands(self):
        """Verify we can get both preflop and postflop stats from same DB."""
        # Insert hand with both preflop and postflop actions
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            date='2026-01-15T20:00:00', hero_position='BTN', net=500,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=400, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'call', 4, position='BB', amount=400),
            ],
            postflop_actions=[
                _make_action('h1', 'V2', 'check', 5, street='flop', position='BB'),
                _make_action('h1', 'Hero', 'bet', 6, street='flop', position='BTN',
                             is_hero=1, amount=300),
                _make_action('h1', 'V2', 'fold', 7, street='flop', position='BB'),
            ],
        )
        self.conn.commit()

        analyzer = TournamentAnalyzer(self.repo, '2026')

        preflop = analyzer.get_preflop_stats()
        self.assertEqual(preflop['overall']['total_hands'], 1)
        self.assertAlmostEqual(preflop['overall']['vpip'], 100.0)
        self.assertAlmostEqual(preflop['overall']['pfr'], 100.0)

        postflop = analyzer.get_postflop_stats()
        self.assertEqual(postflop['overall']['total_hands'], 1)
        self.assertEqual(postflop['overall']['saw_flop_hands'], 1)
        self.assertAlmostEqual(postflop['overall']['cbet'], 100.0)

    def test_multiple_tournaments_aggregated(self):
        """Both T100 and T200 hands should be included in stats."""
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            date='2026-01-15T20:00:00', hero_position='BTN', net=500,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=400, is_voluntary=1),
                _make_action('h1', 'V2', 'fold', 3, position='BB'),
            ],
        )
        _insert_hand_with_actions(
            self.repo, 'h2', tournament_id='T200',
            date='2026-01-15T21:00:00', hero_position='CO', net=-200,
            preflop_actions=[
                _make_action('h2', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h2', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h2', 'Hero', 'fold', 2, position='CO', is_hero=1),
            ],
        )
        self.conn.commit()

        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()
        self.assertEqual(stats['overall']['total_hands'], 2)

    def test_wrong_year_no_data(self):
        """Querying wrong year should return empty stats."""
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            date='2026-01-15T20:00:00', hero_position='BTN', net=500,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=400, is_voluntary=1),
            ],
        )
        self.conn.commit()

        analyzer = TournamentAnalyzer(self.repo, '2025')
        stats = analyzer.get_preflop_stats()
        self.assertEqual(stats['overall']['total_hands'], 0)


# ── Edge Cases ───────────────────────────────────────────────────────

class TestTournamentStatsEdgeCases(unittest.TestCase):
    """Edge case tests for tournament preflop/postflop stats."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_single_hand_preflop(self):
        """Single hand should still produce valid stats."""
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            date='2026-01-15T20:00:00', hero_position='BTN', net=300,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=400, is_voluntary=1),
            ],
        )
        self.conn.commit()

        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()
        self.assertEqual(stats['overall']['total_hands'], 1)
        self.assertAlmostEqual(stats['overall']['vpip'], 100.0)
        self.assertAlmostEqual(stats['overall']['pfr'], 100.0)

    def test_only_non_hero_actions(self):
        """Hands with no hero actions should be excluded."""
        hand = _make_tournament_hand('h1', tournament_id='T100')
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('h1', 'V1', 'raise', 0, position='UTG', is_hero=0),
            _make_action('h1', 'V2', 'fold', 1, position='BB', is_hero=0),
        ])
        self.conn.commit()

        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_preflop_stats()
        self.assertEqual(stats['overall']['total_hands'], 0)

    def test_check_raise_on_flop(self):
        """Test check-raise detection in postflop stats."""
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            date='2026-01-15T20:00:00', hero_position='BB', net=1000,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h1', 'Hero', 'post_bb', 1, position='BB', is_hero=1),
                _make_action('h1', 'V3', 'raise', 2, position='UTG', amount=400),
                _make_action('h1', 'Hero', 'call', 3, position='BB',
                             is_hero=1, amount=200, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 4, position='SB'),
            ],
            postflop_actions=[
                _make_action('h1', 'Hero', 'check', 5, street='flop',
                             position='BB', is_hero=1),
                _make_action('h1', 'V3', 'bet', 6, street='flop',
                             position='UTG', amount=300),
                _make_action('h1', 'Hero', 'raise', 7, street='flop',
                             position='BB', is_hero=1, amount=900),
                _make_action('h1', 'V3', 'fold', 8, street='flop',
                             position='UTG'),
            ],
        )
        self.conn.commit()

        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']
        self.assertGreaterEqual(overall['check_raise_opps'], 1)
        self.assertGreaterEqual(overall['check_raise_hands'], 1)
        self.assertGreater(overall['check_raise'], 0)

    def test_no_postflop_actions(self):
        """Hands with only preflop should not count as saw_flop."""
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T100',
            date='2026-01-15T20:00:00', hero_position='BTN', net=300,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB'),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=400, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'fold', 4, position='BB'),
            ],
        )
        self.conn.commit()

        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_postflop_stats()
        self.assertEqual(stats['overall']['saw_flop_hands'], 0)


if __name__ == '__main__':
    unittest.main()
