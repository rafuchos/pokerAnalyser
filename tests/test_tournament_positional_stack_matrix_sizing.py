"""Tests for US-022: Tournament Backend - Positional Stats, Stack Depth, Hand Matrix, Bet Sizing.

Covers:
- TournamentAnalyzer.get_positional_stats() with per-position stats, radar, blinds defense,
  ATS, 3-bet matrix, comparison
- TournamentAnalyzer.__init__ new attributes: _pos_vpip_healthy, _pos_pfr_healthy,
  _stack_vpip_healthy, _stack_pfr_healthy, _stack_3bet_healthy
- TournamentAnalyzer.get_stack_depth_stats() with tiers (deep/medium/shallow/shove),
  position x tier cross-table
- TournamentAnalyzer.get_hand_matrix() with 13x13 matrix per position,
  top 10 profitable/deficit hands
- TournamentAnalyzer.get_bet_sizing_analysis() with pot-type stats, sizing distributions,
  HU vs multiway
- Imported helpers from cash.py: _categorize_hand, _classify_preflop_action,
  _classify_pot_type, etc.
- Health badges adjusted by position and stack depth
- Edge cases: no hands, single hand, multiple tournaments
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


def _insert_hand_with_actions(repo, hand_id, tournament_id='T100',
                               date='2026-01-15T20:00:00',
                               hero_position='CO', hero_cards='Ah Kd',
                               net=-200, hero_stack=5000.0,
                               blinds_bb=200, blinds_sb=100,
                               preflop_actions=None, postflop_actions=None):
    """Insert a tournament hand with optional preflop and postflop actions."""
    # Ensure tournament row exists (needed for exclude_satellites JOIN)
    repo.insert_tournament({
        'tournament_id': tournament_id, 'platform': 'test', 'name': 'Test Tourney',
        'date': date[:10], 'buy_in': 10, 'rake': 1, 'bounty': 0, 'total_buy_in': 11,
        'position': None, 'prize': 0, 'bounty_won': 0, 'total_players': 100,
        'entries': 1, 'is_bounty': False, 'is_satellite': False,
    })
    hand = _make_tournament_hand(
        hand_id, tournament_id=tournament_id, date=date,
        hero_position=hero_position, hero_cards=hero_cards,
        net=net, hero_stack=hero_stack, blinds_bb=blinds_bb,
        blinds_sb=blinds_sb,
    )
    repo.insert_hand(hand)

    actions = []
    if preflop_actions:
        actions.extend(preflop_actions)
    if postflop_actions:
        actions.extend(postflop_actions)
    if actions:
        repo.insert_actions_batch(actions)


# ── Tests: __init__ attributes ──────────────────────────────────────

class TestTournamentAnalyzerInitAttributes(unittest.TestCase):
    """Test that TournamentAnalyzer.__init__ exposes needed range dicts."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

    def test_pos_vpip_healthy_exists(self):
        self.assertIsNotNone(self.analyzer._pos_vpip_healthy)
        self.assertIsInstance(self.analyzer._pos_vpip_healthy, dict)

    def test_pos_pfr_healthy_exists(self):
        self.assertIsNotNone(self.analyzer._pos_pfr_healthy)
        self.assertIsInstance(self.analyzer._pos_pfr_healthy, dict)

    def test_stack_vpip_healthy_exists(self):
        self.assertIsNotNone(self.analyzer._stack_vpip_healthy)
        self.assertIsInstance(self.analyzer._stack_vpip_healthy, dict)

    def test_stack_pfr_healthy_exists(self):
        self.assertIsNotNone(self.analyzer._stack_pfr_healthy)
        self.assertIsInstance(self.analyzer._stack_pfr_healthy, dict)

    def test_stack_3bet_healthy_exists(self):
        self.assertIsNotNone(self.analyzer._stack_3bet_healthy)
        self.assertIsInstance(self.analyzer._stack_3bet_healthy, dict)

    def test_warning_ranges_exist(self):
        self.assertIsNotNone(self.analyzer._warning_ranges)
        self.assertIsNotNone(self.analyzer._postflop_warning_ranges)

    def test_ranges_match_cash_analyzer(self):
        self.assertEqual(self.analyzer._healthy_ranges, CashAnalyzer.HEALTHY_RANGES)
        self.assertEqual(self.analyzer._pos_vpip_healthy, CashAnalyzer.POSITION_VPIP_HEALTHY)
        self.assertEqual(self.analyzer._stack_vpip_healthy, CashAnalyzer.STACK_VPIP_HEALTHY)


# ── Tests: get_positional_stats ─────────────────────────────────────

class TestTournamentPositionalStatsEmpty(unittest.TestCase):
    """Test get_positional_stats() with no hands."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_empty_returns_structure(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        self.assertEqual(stats['by_position'], {})
        self.assertEqual(stats['blinds_defense'], {})
        self.assertEqual(stats['ats_by_pos'], {})
        self.assertEqual(stats['comparison'], {})
        self.assertEqual(stats['radar'], [])
        self.assertEqual(stats['three_bet_matrix'], {})


class TestTournamentPositionalStats(unittest.TestCase):
    """Test get_positional_stats() with tournament hands."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _setup_positional_hands(self):
        """Insert hands at different positions."""
        # Hand 1: BTN, hero raises (VPIP+PFR), wins
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='BTN', net=500,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'V3', 'fold', 2, position='UTG'),
                _make_action('h1', 'V4', 'fold', 3, position='CO'),
                _make_action('h1', 'Hero', 'raise', 4, position='BTN',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 5, position='SB'),
                _make_action('h1', 'V2', 'fold', 6, position='BB'),
            ],
        )
        # Hand 2: CO, hero calls (VPIP only)
        _insert_hand_with_actions(
            self.repo, 'h2', hero_position='CO', net=-200,
            preflop_actions=[
                _make_action('h2', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h2', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h2', 'V3', 'raise', 2, position='UTG', amount=500),
                _make_action('h2', 'Hero', 'call', 3, position='CO',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h2', 'V4', 'fold', 4, position='BTN'),
                _make_action('h2', 'V1', 'fold', 5, position='SB'),
                _make_action('h2', 'V2', 'fold', 6, position='BB'),
            ],
        )
        # Hand 3: BTN, hero folds (no VPIP)
        _insert_hand_with_actions(
            self.repo, 'h3', hero_position='BTN', net=0,
            preflop_actions=[
                _make_action('h3', 'V1', 'post_sb', 0, position='SB'),
                _make_action('h3', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h3', 'V3', 'raise', 2, position='UTG', amount=500),
                _make_action('h3', 'Hero', 'fold', 3, position='BTN',
                             is_hero=1, is_voluntary=0),
                _make_action('h3', 'V1', 'fold', 4, position='SB'),
                _make_action('h3', 'V2', 'fold', 5, position='BB'),
            ],
        )
        # Hand 4: BB, hero faces steal from BTN, calls
        _insert_hand_with_actions(
            self.repo, 'h4', hero_position='BB', net=300,
            preflop_actions=[
                _make_action('h4', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h4', 'Hero', 'post_bb', 1, position='BB',
                             is_hero=1, amount=200),
                _make_action('h4', 'V3', 'fold', 2, position='UTG'),
                _make_action('h4', 'V4', 'fold', 3, position='CO'),
                _make_action('h4', 'V5', 'raise', 4, position='BTN', amount=500),
                _make_action('h4', 'V1', 'fold', 5, position='SB'),
                _make_action('h4', 'Hero', 'call', 6, position='BB',
                             is_hero=1, amount=500, is_voluntary=1),
            ],
        )
        self.conn.commit()

    def test_by_position_structure(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        self.assertIn('BTN', stats['by_position'])
        self.assertIn('CO', stats['by_position'])
        self.assertIn('BB', stats['by_position'])

    def test_btn_stats(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        btn = stats['by_position']['BTN']
        self.assertEqual(btn['total_hands'], 2)
        # 1 VPIP out of 2 = 50%
        self.assertAlmostEqual(btn['vpip'], 50.0)
        # 1 PFR out of 2 = 50%
        self.assertAlmostEqual(btn['pfr'], 50.0)

    def test_co_stats(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        co = stats['by_position']['CO']
        self.assertEqual(co['total_hands'], 1)
        self.assertAlmostEqual(co['vpip'], 100.0)
        self.assertAlmostEqual(co['pfr'], 0.0)

    def test_health_badges_present(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        for pos, pd in stats['by_position'].items():
            for stat in ('vpip', 'pfr', 'three_bet', 'af', 'cbet', 'wtsd', 'wsd'):
                self.assertIn(f'{stat}_health', pd,
                              f'Missing {stat}_health for {pos}')
                self.assertIn(pd[f'{stat}_health'], ('good', 'warning', 'danger'))

    def test_blinds_defense(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        # h4: BB faces steal from BTN, hero calls
        self.assertIn('BB', stats['blinds_defense'])
        bb_def = stats['blinds_defense']['BB']
        self.assertEqual(bb_def['steal_opps'], 1)
        self.assertAlmostEqual(bb_def['fold_to_steal'], 0.0)
        self.assertAlmostEqual(bb_def['call_vs_steal'], 100.0)

    def test_ats_by_pos(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        # h1: BTN has ATS opp (all fold before hero), hero raises => ATS
        if 'BTN' in stats['ats_by_pos']:
            self.assertGreater(stats['ats_by_pos']['BTN']['ats_opps'], 0)

    def test_comparison(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        if stats['comparison']:
            self.assertIn('most_profitable', stats['comparison'])
            self.assertIn('most_deficitary', stats['comparison'])

    def test_radar_data(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        self.assertIsInstance(stats['radar'], list)
        if stats['radar']:
            r = stats['radar'][0]
            self.assertIn('position', r)
            self.assertIn('values', r)
            self.assertIn('hands', r)
            self.assertIn('bb_per_100', r)

    def test_three_bet_matrix(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        self.assertIn('three_bet_matrix', stats)
        self.assertIsInstance(stats['three_bet_matrix'], dict)

    def test_bb_per_100(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        btn = stats['by_position']['BTN']
        # BTN: net=500+0=500, bb=200, bb_net=500/200+0=2.5, bb/100 = (2.5/2)*100=125
        self.assertAlmostEqual(btn['bb_per_100'], 125.0)

    def test_winrate_health(self):
        self._setup_positional_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        btn = stats['by_position']['BTN']
        self.assertEqual(btn['winrate_health'], 'good')  # net=500 > 0
        co = stats['by_position']['CO']
        self.assertEqual(co['winrate_health'], 'danger')  # net=-200 < 0


# ── Tests: get_positional_stats with 3-bet scenario ─────────────────

class TestTournamentPositional3Bet(unittest.TestCase):
    """Test 3-bet tracking in positional stats."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_three_bet_opportunity_and_action(self):
        """Hero faces raise and 3-bets."""
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='CO', net=600,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'V3', 'raise', 2, position='UTG', amount=500),
                _make_action('h1', 'Hero', 'raise', 3, position='CO',
                             is_hero=1, amount=1200, is_voluntary=1),
                _make_action('h1', 'V3', 'fold', 4, position='UTG'),
            ],
        )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        co = stats['by_position']['CO']
        self.assertAlmostEqual(co['three_bet'], 100.0)

    def test_three_bet_matrix_entry(self):
        """3-bet matrix tracks hero_pos vs raiser_pos."""
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='CO', net=600,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'V3', 'raise', 2, position='UTG', amount=500),
                _make_action('h1', 'Hero', 'raise', 3, position='CO',
                             is_hero=1, amount=1200, is_voluntary=1),
                _make_action('h1', 'V3', 'fold', 4, position='UTG'),
            ],
        )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        matrix = stats['three_bet_matrix']
        self.assertIn('CO', matrix)
        self.assertIn('UTG', matrix['CO'])
        self.assertAlmostEqual(matrix['CO']['UTG']['three_bet_pct'], 100.0)


# ── Tests: get_stack_depth_stats ────────────────────────────────────

class TestTournamentStackDepthEmpty(unittest.TestCase):
    """Test get_stack_depth_stats() with no hands."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_empty_returns_structure(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        self.assertEqual(stats['by_tier'], {})
        self.assertEqual(stats['by_position_tier'], {})
        self.assertEqual(stats['tier_order'], ['deep', 'medium', 'shallow', 'shove'])
        self.assertEqual(stats['hands_with_stack'], 0)


class TestTournamentStackDepthStats(unittest.TestCase):
    """Test get_stack_depth_stats() with various stack sizes."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _setup_stack_hands(self):
        """Insert hands at different stack depths."""
        # Deep stack: 50+ BB (5000/200 = 25BB... need 10000 for 50BB)
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='BTN', net=400,
            hero_stack=12000.0, blinds_bb=200,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'fold', 4, position='BB'),
            ],
        )
        # Medium stack: 25-50 BB (6000/200 = 30BB)
        _insert_hand_with_actions(
            self.repo, 'h2', hero_position='CO', net=-200,
            hero_stack=6000.0, blinds_bb=200,
            preflop_actions=[
                _make_action('h2', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h2', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h2', 'Hero', 'call', 2, position='CO',
                             is_hero=1, amount=200, is_voluntary=1),
                _make_action('h2', 'V1', 'fold', 3, position='SB'),
            ],
        )
        # Shallow stack: 15-25 BB (4000/200 = 20BB)
        _insert_hand_with_actions(
            self.repo, 'h3', hero_position='BTN', net=300,
            hero_stack=4000.0, blinds_bb=200,
            preflop_actions=[
                _make_action('h3', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h3', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h3', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h3', 'V1', 'fold', 3, position='SB'),
                _make_action('h3', 'V2', 'fold', 4, position='BB'),
            ],
        )
        # Shove zone: <15 BB (2000/200 = 10BB)
        _insert_hand_with_actions(
            self.repo, 'h4', hero_position='SB', net=-2000,
            hero_stack=2000.0, blinds_bb=200,
            preflop_actions=[
                _make_action('h4', 'Hero', 'post_sb', 0, position='SB',
                             is_hero=1, amount=100),
                _make_action('h4', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h4', 'Hero', 'all-in', 2, position='SB',
                             is_hero=1, amount=2000, is_voluntary=1),
                _make_action('h4', 'V2', 'call', 3, position='BB', amount=2000),
            ],
        )
        self.conn.commit()

    def test_tiers_present(self):
        self._setup_stack_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        self.assertIn('deep', stats['by_tier'])
        self.assertIn('medium', stats['by_tier'])
        self.assertIn('shallow', stats['by_tier'])
        self.assertIn('shove', stats['by_tier'])

    def test_deep_tier_stats(self):
        self._setup_stack_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        deep = stats['by_tier']['deep']
        self.assertEqual(deep['total_hands'], 1)
        self.assertAlmostEqual(deep['vpip'], 100.0)
        self.assertAlmostEqual(deep['pfr'], 100.0)
        self.assertEqual(deep['label'], '50+ BB')

    def test_medium_tier_stats(self):
        self._setup_stack_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        medium = stats['by_tier']['medium']
        self.assertEqual(medium['total_hands'], 1)
        self.assertAlmostEqual(medium['vpip'], 100.0)
        self.assertAlmostEqual(medium['pfr'], 0.0)

    def test_shove_tier_stats(self):
        self._setup_stack_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        shove = stats['by_tier']['shove']
        self.assertEqual(shove['total_hands'], 1)

    def test_health_badges_per_tier(self):
        self._setup_stack_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        for tier, td in stats['by_tier'].items():
            for stat in ('vpip', 'pfr', 'three_bet', 'af', 'cbet', 'wtsd', 'wsd'):
                self.assertIn(f'{stat}_health', td,
                              f'Missing {stat}_health for tier {tier}')
                self.assertIn(td[f'{stat}_health'], ('good', 'warning', 'danger'))

    def test_tier_labels(self):
        self._setup_stack_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        self.assertEqual(stats['tier_labels']['deep'], '50+ BB')
        self.assertEqual(stats['tier_labels']['medium'], '25-50 BB')
        self.assertEqual(stats['tier_labels']['shallow'], '15-25 BB')
        self.assertEqual(stats['tier_labels']['shove'], '<15 BB')

    def test_hands_with_stack_count(self):
        self._setup_stack_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        self.assertEqual(stats['hands_with_stack'], 4)
        self.assertEqual(stats['hands_total'], 4)

    def test_winrate_health(self):
        self._setup_stack_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        self.assertEqual(stats['by_tier']['deep']['winrate_health'], 'good')
        self.assertEqual(stats['by_tier']['shove']['winrate_health'], 'danger')

    def test_bb_per_100(self):
        self._setup_stack_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        deep = stats['by_tier']['deep']
        # net=400, bb=200, bb_net=400/200=2, bb/100 = (2/1)*100 = 200
        self.assertAlmostEqual(deep['bb_per_100'], 200.0)

    def test_no_stack_hands_skipped(self):
        """Hands without hero_stack are skipped."""
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='BTN', net=400,
            hero_stack=0.0, blinds_bb=200,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'Hero', 'fold', 1, position='BTN', is_hero=1),
            ],
        )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        self.assertEqual(stats['hands_with_stack'], 0)

    def test_position_tier_cross_table(self):
        """Position x tier cross-table requires >= 5 hands per cell."""
        # Insert 5 deep hands at BTN
        for i in range(5):
            _insert_hand_with_actions(
                self.repo, f'hd{i}', hero_position='BTN', net=100,
                hero_stack=12000.0, blinds_bb=200,
                preflop_actions=[
                    _make_action(f'hd{i}', 'V1', 'post_sb', 0, position='SB', amount=100),
                    _make_action(f'hd{i}', 'V2', 'post_bb', 1, position='BB', amount=200),
                    _make_action(f'hd{i}', 'Hero', 'raise', 2, position='BTN',
                                 is_hero=1, amount=500, is_voluntary=1),
                    _make_action(f'hd{i}', 'V1', 'fold', 3, position='SB'),
                    _make_action(f'hd{i}', 'V2', 'fold', 4, position='BB'),
                ],
            )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        self.assertIn('BTN', stats['by_position_tier'])
        self.assertIn('deep', stats['by_position_tier']['BTN'])
        self.assertEqual(stats['by_position_tier']['BTN']['deep']['total_hands'], 5)


class TestTournamentStackDepthHealth(unittest.TestCase):
    """Test _classify_stack_depth_health on TournamentAnalyzer."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

    def test_vpip_deep_healthy(self):
        result = self.analyzer._classify_stack_depth_health('vpip', 'deep', 25.0)
        self.assertEqual(result, 'good')

    def test_vpip_shove_outside_range(self):
        result = self.analyzer._classify_stack_depth_health('vpip', 'shove', 80.0)
        self.assertEqual(result, 'danger')

    def test_three_bet_falls_back(self):
        result = self.analyzer._classify_stack_depth_health('three_bet', 'deep', 9.0)
        self.assertIn(result, ('good', 'warning', 'danger'))

    def test_unknown_stat_falls_back(self):
        result = self.analyzer._classify_stack_depth_health('af', 'deep', 2.5)
        self.assertIn(result, ('good', 'warning', 'danger'))


# ── Tests: get_hand_matrix ──────────────────────────────────────────

class TestTournamentHandMatrixEmpty(unittest.TestCase):
    """Test get_hand_matrix() with no hands."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_empty_returns_structure(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        self.assertEqual(stats['overall'], {})
        self.assertEqual(stats['by_position'], {})
        self.assertEqual(stats['top_profitable'], [])
        self.assertEqual(stats['top_deficit'], [])
        self.assertEqual(stats['total_hands'], 0)


class TestTournamentHandMatrix(unittest.TestCase):
    """Test get_hand_matrix() with various hands."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _setup_matrix_hands(self):
        """Insert hands with known cards."""
        # AKo - open raise, win
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='CO', net=500,
            hero_cards='Ah Kd',
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'Hero', 'raise', 2, position='CO',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'fold', 4, position='BB'),
            ],
        )
        # AKo - open raise again, win
        _insert_hand_with_actions(
            self.repo, 'h2', hero_position='BTN', net=300,
            hero_cards='Ad Kc',
            preflop_actions=[
                _make_action('h2', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h2', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h2', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h2', 'V1', 'fold', 3, position='SB'),
                _make_action('h2', 'V2', 'fold', 4, position='BB'),
            ],
        )
        # AKo - call, lose
        _insert_hand_with_actions(
            self.repo, 'h3', hero_position='BB', net=-500,
            hero_cards='As Kh',
            preflop_actions=[
                _make_action('h3', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h3', 'Hero', 'post_bb', 1, position='BB',
                             is_hero=1, amount=200),
                _make_action('h3', 'V3', 'raise', 2, position='UTG', amount=500),
                _make_action('h3', 'Hero', 'call', 3, position='BB',
                             is_hero=1, amount=500, is_voluntary=1),
            ],
        )
        # 72o - fold
        _insert_hand_with_actions(
            self.repo, 'h4', hero_position='UTG', net=0,
            hero_cards='7h 2d',
            preflop_actions=[
                _make_action('h4', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h4', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h4', 'Hero', 'fold', 2, position='UTG',
                             is_hero=1, is_voluntary=0),
            ],
        )
        self.conn.commit()

    def test_overall_matrix(self):
        self._setup_matrix_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        self.assertIn('AKo', stats['overall'])
        ak = stats['overall']['AKo']
        self.assertEqual(ak['dealt'], 3)
        self.assertEqual(ak['played'], 3)  # 2 raise + 1 call
        self.assertEqual(ak['open_raise'], 2)
        self.assertEqual(ak['call'], 1)

    def test_by_position_matrix(self):
        self._setup_matrix_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        self.assertIn('CO', stats['by_position'])
        self.assertIn('AKo', stats['by_position']['CO'])
        co_ak = stats['by_position']['CO']['AKo']
        self.assertEqual(co_ak['dealt'], 1)
        self.assertEqual(co_ak['open_raise'], 1)

    def test_win_rate_calculation(self):
        self._setup_matrix_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        ak = stats['overall']['AKo']
        # bb_net = 500/200 + 300/200 + (-500/200) = 2.5 + 1.5 - 2.5 = 1.5
        # win_rate = 1.5 / 3 * 100 = 50.0
        self.assertAlmostEqual(ak['win_rate'], 50.0, places=1)

    def test_frequency(self):
        self._setup_matrix_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        ak = stats['overall']['AKo']
        self.assertAlmostEqual(ak['frequency'], 100.0)  # 3/3 played
        # 72o dealt but folded (not played)
        if '72o' in stats['overall']:
            self.assertAlmostEqual(stats['overall']['72o']['frequency'], 0.0)

    def test_total_hands(self):
        self._setup_matrix_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        self.assertEqual(stats['total_hands'], 4)

    def test_top_profitable(self):
        self._setup_matrix_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        # AKo has 3 dealt (>= 3), win_rate > 0 => in top_profitable
        ak_in_top = [h for h in stats['top_profitable'] if h['hand'] == 'AKo']
        self.assertEqual(len(ak_in_top), 1)

    def test_top_deficit_requires_min_dealt(self):
        self._setup_matrix_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        # 72o only has 1 dealt (< 3), should NOT be in top_deficit
        deficit_72o = [h for h in stats['top_deficit'] if h['hand'] == '72o']
        self.assertEqual(len(deficit_72o), 0)


# ── Tests: get_bet_sizing_analysis ──────────────────────────────────

class TestTournamentBetSizingEmpty(unittest.TestCase):
    """Test get_bet_sizing_analysis() with no hands."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_empty_returns_structure(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertEqual(stats['total_hands'], 0)
        self.assertIn('pot_types', stats)
        self.assertIn('sizing', stats)
        self.assertIn('hu_vs_multiway', stats)
        self.assertIn('diagnostics', stats)


class TestTournamentBetSizing(unittest.TestCase):
    """Test get_bet_sizing_analysis() with various pot types."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _setup_sizing_hands(self):
        """Insert hands with different pot types."""
        # SRP: single raise
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='CO', net=300,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'Hero', 'raise', 2, position='CO',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'call', 4, position='BB', amount=500),
            ],
            postflop_actions=[
                _make_action('h1', 'V2', 'check', 5, street='flop', position='BB'),
                _make_action('h1', 'Hero', 'bet', 6, street='flop', position='CO',
                             is_hero=1, amount=500),
                _make_action('h1', 'V2', 'fold', 7, street='flop', position='BB'),
            ],
        )
        # 3-bet pot
        _insert_hand_with_actions(
            self.repo, 'h2', hero_position='BTN', net=-1200,
            preflop_actions=[
                _make_action('h2', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h2', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h2', 'V3', 'raise', 2, position='UTG', amount=500),
                _make_action('h2', 'Hero', 'raise', 3, position='BTN',
                             is_hero=1, amount=1200, is_voluntary=1),
                _make_action('h2', 'V1', 'fold', 4, position='SB'),
                _make_action('h2', 'V2', 'fold', 5, position='BB'),
                _make_action('h2', 'V3', 'call', 6, position='UTG', amount=1200),
            ],
        )
        # Limped pot
        _insert_hand_with_actions(
            self.repo, 'h3', hero_position='BB', net=100,
            preflop_actions=[
                _make_action('h3', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h3', 'Hero', 'post_bb', 1, position='BB',
                             is_hero=1, amount=200),
                _make_action('h3', 'V3', 'call', 2, position='UTG', amount=200),
                _make_action('h3', 'V4', 'call', 3, position='CO', amount=200),
                _make_action('h3', 'V1', 'call', 4, position='SB', amount=200),
                _make_action('h3', 'Hero', 'check', 5, position='BB',
                             is_hero=1, is_voluntary=1),
            ],
        )
        self.conn.commit()

    def test_pot_types_present(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertIn('srp', stats['pot_types'])
        self.assertIn('3bet', stats['pot_types'])
        self.assertIn('limped', stats['pot_types'])
        self.assertIn('4bet_plus', stats['pot_types'])

    def test_srp_hands_count(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertEqual(stats['pot_types']['srp']['hands'], 1)

    def test_3bet_hands_count(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertEqual(stats['pot_types']['3bet']['hands'], 1)

    def test_limped_hands_count(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertEqual(stats['pot_types']['limped']['hands'], 1)

    def test_total_hands(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertEqual(stats['total_hands'], 3)

    def test_sizing_structure(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        for street in ('preflop', 'flop', 'turn', 'river'):
            self.assertIn(street, stats['sizing'])
            self.assertIn('samples', stats['sizing'][street])
            self.assertIn('avg', stats['sizing'][street])
            self.assertIn('median', stats['sizing'][street])
            self.assertIn('distribution', stats['sizing'][street])

    def test_preflop_sizing_sample(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        # h1: raise 500 / bb 200 = 2.5x; h2: raise 1200 / bb 200 = 6x
        self.assertEqual(stats['sizing']['preflop']['samples'], 2)
        self.assertGreater(stats['sizing']['preflop']['avg'], 0)

    def test_hu_vs_multiway(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        hu = stats['hu_vs_multiway']['heads_up']
        mw = stats['hu_vs_multiway']['multiway']
        self.assertIsInstance(hu, dict)
        self.assertIsInstance(mw, dict)
        # h1: SRP 2 players see flop -> HU
        # h2: 3bet 2 players -> HU
        # h3: limped 4 players -> multiway
        self.assertEqual(hu['hands'], 2)
        self.assertEqual(mw['hands'], 1)

    def test_pot_type_stats_format(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        srp = stats['pot_types']['srp']
        for key in ('hands', 'vpip', 'pfr', 'af', 'cbet', 'wtsd', 'wsd',
                     'net', 'win_rate_bb100', 'health'):
            self.assertIn(key, srp, f'Missing {key} in SRP pot type')

    def test_diagnostics_list(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertIsInstance(stats['diagnostics'], list)

    def test_flop_sizing(self):
        self._setup_sizing_hands()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        # h1 has a flop bet of 500 with running pot > 0
        if stats['sizing']['flop']['samples'] > 0:
            self.assertGreater(stats['sizing']['flop']['avg'], 0)


# ── Tests: Integration / edge cases ─────────────────────────────────

class TestTournamentMultipleTournaments(unittest.TestCase):
    """Test that methods work across multiple tournament IDs."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_positional_stats_across_tournaments(self):
        # Tournament 1
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T1', hero_position='BTN', net=400,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'fold', 4, position='BB'),
            ],
        )
        # Tournament 2
        _insert_hand_with_actions(
            self.repo, 'h2', tournament_id='T2', hero_position='BTN', net=-300,
            preflop_actions=[
                _make_action('h2', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h2', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h2', 'Hero', 'call', 2, position='BTN',
                             is_hero=1, amount=200, is_voluntary=1),
                _make_action('h2', 'V1', 'fold', 3, position='SB'),
            ],
        )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        btn = stats['by_position']['BTN']
        self.assertEqual(btn['total_hands'], 2)
        self.assertAlmostEqual(btn['vpip'], 100.0)

    def test_hand_matrix_across_tournaments(self):
        _insert_hand_with_actions(
            self.repo, 'h1', tournament_id='T1', hero_position='CO', net=300,
            hero_cards='Ah Kd',
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'Hero', 'raise', 2, position='CO',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'fold', 4, position='BB'),
            ],
        )
        _insert_hand_with_actions(
            self.repo, 'h2', tournament_id='T2', hero_position='BTN', net=200,
            hero_cards='Ac Kc',
            preflop_actions=[
                _make_action('h2', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h2', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h2', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h2', 'V1', 'fold', 3, position='SB'),
                _make_action('h2', 'V2', 'fold', 4, position='BB'),
            ],
        )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        # AKo and AKs
        self.assertIn('AKo', stats['overall'])
        self.assertIn('AKs', stats['overall'])
        self.assertEqual(stats['total_hands'], 2)


class TestTournamentSingleHand(unittest.TestCase):
    """Test methods with a single hand."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='BTN', net=300,
            hero_cards='Ah Kd', hero_stack=10000.0, blinds_bb=200,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'fold', 4, position='BB'),
            ],
        )
        self.conn.commit()

    def test_positional_stats_single(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        self.assertIn('BTN', stats['by_position'])
        self.assertEqual(stats['by_position']['BTN']['total_hands'], 1)

    def test_stack_depth_single(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        # 10000/200 = 50 BB = deep
        self.assertIn('deep', stats['by_tier'])
        self.assertEqual(stats['by_tier']['deep']['total_hands'], 1)

    def test_hand_matrix_single(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_hand_matrix()
        self.assertIn('AKo', stats['overall'])
        self.assertEqual(stats['overall']['AKo']['dealt'], 1)

    def test_bet_sizing_single(self):
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertEqual(stats['total_hands'], 1)
        self.assertEqual(stats['pot_types']['srp']['hands'], 1)


class TestTournamentPostflopIntegration(unittest.TestCase):
    """Test postflop stats integration in positional and stack depth methods."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_postflop_stats_in_positional(self):
        """Hero sees flop and c-bets."""
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='BTN', net=800,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'call', 4, position='BB', amount=500),
            ],
            postflop_actions=[
                _make_action('h1', 'V2', 'check', 5, street='flop', position='BB'),
                _make_action('h1', 'Hero', 'bet', 6, street='flop', position='BTN',
                             is_hero=1, amount=600),
                _make_action('h1', 'V2', 'fold', 7, street='flop', position='BB'),
            ],
        )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_positional_stats()
        btn = stats['by_position']['BTN']
        self.assertAlmostEqual(btn['cbet'], 100.0)

    def test_postflop_stats_in_stack_depth(self):
        """Hero sees flop in medium stack."""
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='BTN', net=800,
            hero_stack=6000.0, blinds_bb=200,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'Hero', 'raise', 2, position='BTN',
                             is_hero=1, amount=500, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 3, position='SB'),
                _make_action('h1', 'V2', 'call', 4, position='BB', amount=500),
            ],
            postflop_actions=[
                _make_action('h1', 'V2', 'check', 5, street='flop', position='BB'),
                _make_action('h1', 'Hero', 'bet', 6, street='flop', position='BTN',
                             is_hero=1, amount=600),
                _make_action('h1', 'V2', 'fold', 7, street='flop', position='BB'),
            ],
        )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_stack_depth_stats()
        medium = stats['by_tier']['medium']
        self.assertAlmostEqual(medium['cbet'], 100.0)


class TestTournamentBetSizingBuckets(unittest.TestCase):
    """Test sizing distribution buckets."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_preflop_sizing_buckets(self):
        """Multiple preflop raises produce distribution."""
        for i, raise_amt in enumerate([400, 500, 600, 800, 1000]):
            _insert_hand_with_actions(
                self.repo, f'h{i}', hero_position='CO', net=100,
                blinds_bb=200,
                preflop_actions=[
                    _make_action(f'h{i}', 'V1', 'post_sb', 0, position='SB', amount=100),
                    _make_action(f'h{i}', 'V2', 'post_bb', 1, position='BB', amount=200),
                    _make_action(f'h{i}', 'Hero', 'raise', 2, position='CO',
                                 is_hero=1, amount=raise_amt, is_voluntary=1),
                    _make_action(f'h{i}', 'V1', 'fold', 3, position='SB'),
                    _make_action(f'h{i}', 'V2', 'fold', 4, position='BB'),
                ],
            )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertEqual(stats['sizing']['preflop']['samples'], 5)
        # Sizes: 2x, 2.5x, 3x, 4x, 5x
        dist = stats['sizing']['preflop']['distribution']
        self.assertEqual(len(dist), 5)  # 5 buckets
        total_pct = sum(d['pct'] for d in dist)
        self.assertAlmostEqual(total_pct, 100.0)


class TestTournament4BetPot(unittest.TestCase):
    """Test 4-bet+ pot classification."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_4bet_pot(self):
        _insert_hand_with_actions(
            self.repo, 'h1', hero_position='BTN', net=-3000,
            preflop_actions=[
                _make_action('h1', 'V1', 'post_sb', 0, position='SB', amount=100),
                _make_action('h1', 'V2', 'post_bb', 1, position='BB', amount=200),
                _make_action('h1', 'V3', 'raise', 2, position='UTG', amount=500),
                _make_action('h1', 'Hero', 'raise', 3, position='BTN',
                             is_hero=1, amount=1200, is_voluntary=1),
                _make_action('h1', 'V1', 'fold', 4, position='SB'),
                _make_action('h1', 'V2', 'fold', 5, position='BB'),
                _make_action('h1', 'V3', 'raise', 6, position='UTG', amount=3000),
                _make_action('h1', 'Hero', 'call', 7, position='BTN',
                             is_hero=1, amount=3000, is_voluntary=1),
            ],
        )
        self.conn.commit()
        analyzer = TournamentAnalyzer(self.repo, '2026')
        stats = analyzer.get_bet_sizing_analysis()
        self.assertEqual(stats['pot_types']['4bet_plus']['hands'], 1)


if __name__ == '__main__':
    unittest.main()
