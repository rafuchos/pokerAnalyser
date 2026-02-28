"""Tests for US-002: Preflop statistics (VPIP, PFR, 3-Bet%, Fold-to-3Bet%, ATS).

Covers:
- VPIP calculation (voluntary pot entry, excluding forced blinds)
- PFR calculation (preflop raise percentage)
- 3-Bet% calculation (re-raise after a raise)
- Fold to 3-Bet% (folding after receiving a 3-bet)
- ATS (attempt to steal from CO/BTN/SB)
- Stats aggregation: overall, by position, by day
- Health badge classification
- HTML report integration with Player Stats section
- Edge cases (0 hands, all folds, etc.)
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer


# ── Helpers ──────────────────────────────────────────────────────────

def _make_hand(hand_id, date='2026-01-15', hero_position='CO', **kwargs):
    """Create a HandData with sensible defaults for testing."""
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='cash',
        date=datetime.fromisoformat(f'{date}T20:00:00') if isinstance(date, str) else date,
        blinds_sb=0.25,
        blinds_bb=0.50,
        hero_cards='Ah Kd',
        hero_position=hero_position,
        invested=kwargs.get('invested', 1.0),
        won=kwargs.get('won', 0.0),
        net=kwargs.get('net', -1.0),
        rake=0.0,
        table_name='T',
        num_players=kwargs.get('num_players', 6),
    )


def _make_action(hand_id, player, action_type, seq, position='CO',
                 is_hero=0, amount=0.0, is_voluntary=0):
    """Create an ActionData for preflop testing."""
    return ActionData(
        hand_id=hand_id,
        street='preflop',
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


# ── Preflop Hand Analysis Unit Tests ─────────────────────────────────

class TestAnalyzePreflopHand(unittest.TestCase):
    """Test CashAnalyzer._analyze_preflop_hand() logic."""

    def test_hero_open_raise_vpip_and_pfr(self):
        """Hero open-raises → VPIP=True, PFR=True."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 1.5},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['vpip'])
        self.assertTrue(result['pfr'])
        self.assertFalse(result['three_bet_opp'])
        self.assertFalse(result['three_bet'])

    def test_hero_call_vpip_no_pfr(self):
        """Hero calls → VPIP=True, PFR=False."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'is_voluntary': 1, 'position': 'UTG', 'amount': 1.5},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 1.5},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['vpip'])
        self.assertFalse(result['pfr'])
        self.assertTrue(result['three_bet_opp'])
        self.assertFalse(result['three_bet'])

    def test_hero_fold_no_vpip(self):
        """Hero folds → VPIP=False, PFR=False."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'is_voluntary': 1, 'position': 'UTG', 'amount': 1.5},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'is_voluntary': 0, 'position': 'CO'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertFalse(result['vpip'])
        self.assertFalse(result['pfr'])
        self.assertTrue(result['three_bet_opp'])

    def test_hero_3bet(self):
        """Hero re-raises after opponent raise → 3-bet."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'is_voluntary': 1, 'position': 'UTG', 'amount': 1.5},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'MP'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 4.5},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['vpip'])
        self.assertTrue(result['pfr'])
        self.assertTrue(result['three_bet_opp'])
        self.assertTrue(result['three_bet'])

    def test_fold_to_3bet(self):
        """Hero raises, gets re-raised, folds → fold to 3-bet."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 1.5},
            {'player': 'V2', 'action_type': 'raise', 'is_hero': 0, 'is_voluntary': 1, 'position': 'BTN', 'amount': 4.5},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'SB'},
            {'player': 'V4', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BB'},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'is_voluntary': 0, 'position': 'CO'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['vpip'])
        self.assertTrue(result['pfr'])
        self.assertTrue(result['fold_3bet_opp'])
        self.assertTrue(result['fold_3bet'])

    def test_call_3bet(self):
        """Hero raises, gets re-raised, calls → NOT fold to 3-bet."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 1.5},
            {'player': 'V2', 'action_type': 'raise', 'is_hero': 0, 'is_voluntary': 1, 'position': 'BTN', 'amount': 4.5},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'SB'},
            {'player': 'V4', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BB'},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'is_voluntary': 0, 'position': 'CO', 'amount': 4.5},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['fold_3bet_opp'])
        self.assertFalse(result['fold_3bet'])

    def test_ats_from_btn(self):
        """All fold to Hero on BTN, hero raises → ATS."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'MP'},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'CO'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'BTN', 'amount': 1.5},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['ats_opp'])
        self.assertTrue(result['ats'])

    def test_ats_from_co(self):
        """All fold to Hero on CO, hero raises → ATS."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'MP'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 1.5},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['ats_opp'])
        self.assertTrue(result['ats'])

    def test_ats_from_sb(self):
        """All fold to Hero on SB, hero raises → ATS."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'MP'},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'CO'},
            {'player': 'V4', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'SB', 'amount': 1.5},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['ats_opp'])
        self.assertTrue(result['ats'])

    def test_no_ats_from_bb(self):
        """Hero on BB → no ATS opportunity."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'MP'},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'CO'},
            {'player': 'V4', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
            {'player': 'V5', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'SB'},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'is_voluntary': 0, 'position': 'BB'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertFalse(result['ats_opp'])

    def test_no_ats_when_limper_before_hero(self):
        """Someone calls before hero → not all folded → no ATS opportunity."""
        actions = [
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'is_voluntary': 1, 'position': 'UTG', 'amount': 0.5},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'MP'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 2.0},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertFalse(result['ats_opp'])

    def test_no_ats_when_raise_before_hero(self):
        """Someone raises before hero → not all folded → no ATS opportunity."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'is_voluntary': 1, 'position': 'UTG', 'amount': 1.5},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 4.5},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertFalse(result['ats_opp'])
        # But this IS a 3-bet
        self.assertTrue(result['three_bet'])

    def test_ats_missed_hero_folds(self):
        """All fold to hero on BTN but hero folds → ATS opportunity, no ATS."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'MP'},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'CO'},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'is_voluntary': 0, 'position': 'BTN'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['ats_opp'])
        self.assertFalse(result['ats'])

    def test_empty_actions(self):
        """No actions → all False."""
        result = CashAnalyzer._analyze_preflop_hand([])
        self.assertFalse(result['vpip'])
        self.assertFalse(result['pfr'])
        self.assertFalse(result['three_bet_opp'])
        self.assertFalse(result['ats_opp'])

    def test_allin_counted_for_raises_before_hero(self):
        """All-in by opponent counts as a raise for 3-bet opportunity detection."""
        actions = [
            {'player': 'V1', 'action_type': 'all-in', 'is_hero': 0, 'is_voluntary': 1, 'position': 'UTG', 'amount': 20.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 20.0},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['three_bet_opp'])
        self.assertFalse(result['three_bet'])


# ── Health Badge Classification Tests ────────────────────────────────

class TestHealthClassification(unittest.TestCase):
    """Test health badge classification logic."""

    def test_vpip_healthy(self):
        self.assertEqual(CashAnalyzer._classify_health('vpip', 25.0), 'good')

    def test_vpip_warning_low(self):
        self.assertEqual(CashAnalyzer._classify_health('vpip', 19.0), 'warning')

    def test_vpip_warning_high(self):
        self.assertEqual(CashAnalyzer._classify_health('vpip', 33.0), 'warning')

    def test_vpip_danger_low(self):
        self.assertEqual(CashAnalyzer._classify_health('vpip', 10.0), 'danger')

    def test_vpip_danger_high(self):
        self.assertEqual(CashAnalyzer._classify_health('vpip', 50.0), 'danger')

    def test_pfr_healthy(self):
        self.assertEqual(CashAnalyzer._classify_health('pfr', 20.0), 'good')

    def test_pfr_danger(self):
        self.assertEqual(CashAnalyzer._classify_health('pfr', 5.0), 'danger')

    def test_three_bet_healthy(self):
        self.assertEqual(CashAnalyzer._classify_health('three_bet', 9.0), 'good')

    def test_fold_to_3bet_healthy(self):
        self.assertEqual(CashAnalyzer._classify_health('fold_to_3bet', 50.0), 'good')

    def test_ats_healthy(self):
        self.assertEqual(CashAnalyzer._classify_health('ats', 35.0), 'good')

    def test_unknown_stat_returns_good(self):
        self.assertEqual(CashAnalyzer._classify_health('unknown_stat', 50.0), 'good')


# ── Database Integration Tests ───────────────────────────────────────

class TestPreflopStatsIntegration(unittest.TestCase):
    """Integration tests: insert hands/actions → compute preflop stats."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def _insert_hand_with_actions(self, hand_id, hero_position, actions_data,
                                  date='2026-01-15'):
        """Helper: insert a hand and its preflop actions.

        actions_data: list of (player, action_type, is_hero, amount, is_voluntary, position)
        """
        hand = _make_hand(hand_id, date=date, hero_position=hero_position)
        self.repo.insert_hand(hand)

        actions = []
        for seq, (player, atype, is_h, amt, is_v, pos) in enumerate(actions_data):
            actions.append(_make_action(
                hand_id, player, atype, seq, position=pos,
                is_hero=is_h, amount=amt, is_voluntary=is_v,
            ))
        self.repo.insert_actions_batch(actions)
        self.conn.commit()

    def test_basic_vpip_pfr(self):
        """Test VPIP and PFR with 3 hands: raise, call, fold."""
        # Hand 1: Hero raises (VPIP=yes, PFR=yes)
        self._insert_hand_with_actions('H1', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'fold', 0, 0, 0, 'UTG'),
            ('Hero', 'raise', 1, 1.50, 1, 'CO'),
            ('V4', 'fold', 0, 0, 0, 'BTN'),
        ])

        # Hand 2: Hero calls (VPIP=yes, PFR=no)
        self._insert_hand_with_actions('H2', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'raise', 0, 1.50, 1, 'UTG'),
            ('Hero', 'call', 1, 1.50, 1, 'CO'),
        ])

        # Hand 3: Hero folds (VPIP=no, PFR=no)
        self._insert_hand_with_actions('H3', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'raise', 0, 1.50, 1, 'UTG'),
            ('Hero', 'fold', 1, 0, 0, 'CO'),
        ])

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['total_hands'], 3)
        self.assertAlmostEqual(overall['vpip'], 2 / 3 * 100, places=1)
        self.assertAlmostEqual(overall['pfr'], 1 / 3 * 100, places=1)
        self.assertEqual(overall['vpip_hands'], 2)
        self.assertEqual(overall['pfr_hands'], 1)

    def test_three_bet_stats(self):
        """Test 3-bet calculation: 2 opportunities, 1 three-bet."""
        # Hand 1: V raises, Hero 3-bets
        self._insert_hand_with_actions('H1', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'raise', 0, 1.50, 1, 'UTG'),
            ('Hero', 'raise', 1, 4.50, 1, 'CO'),
        ])

        # Hand 2: V raises, Hero calls
        self._insert_hand_with_actions('H2', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'raise', 0, 1.50, 1, 'UTG'),
            ('Hero', 'call', 1, 1.50, 1, 'CO'),
        ])

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['three_bet_opps'], 2)
        self.assertEqual(overall['three_bet_hands'], 1)
        self.assertAlmostEqual(overall['three_bet'], 50.0, places=1)

    def test_fold_to_3bet_stats(self):
        """Test fold-to-3-bet: hero open-raises, gets 3-bet, folds."""
        # Hand 1: Hero raises, V 3-bets, Hero folds
        self._insert_hand_with_actions('H1', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'fold', 0, 0, 0, 'UTG'),
            ('Hero', 'raise', 1, 1.50, 1, 'CO'),
            ('V4', 'raise', 0, 4.50, 1, 'BTN'),
            ('V1', 'fold', 0, 0, 0, 'SB'),
            ('V2', 'fold', 0, 0, 0, 'BB'),
            ('Hero', 'fold', 1, 0, 0, 'CO'),
        ])

        # Hand 2: Hero raises, V 3-bets, Hero calls
        self._insert_hand_with_actions('H2', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'fold', 0, 0, 0, 'UTG'),
            ('Hero', 'raise', 1, 1.50, 1, 'CO'),
            ('V4', 'raise', 0, 4.50, 1, 'BTN'),
            ('V1', 'fold', 0, 0, 0, 'SB'),
            ('V2', 'fold', 0, 0, 0, 'BB'),
            ('Hero', 'call', 1, 4.50, 0, 'CO'),
        ])

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['fold_to_3bet_opps'], 2)
        self.assertEqual(overall['fold_to_3bet_hands'], 1)
        self.assertAlmostEqual(overall['fold_to_3bet'], 50.0, places=1)

    def test_ats_stats(self):
        """Test ATS: steal from BTN when folded to."""
        # Hand 1: All fold to Hero BTN, Hero raises → ATS
        self._insert_hand_with_actions('H1', 'BTN', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'fold', 0, 0, 0, 'UTG'),
            ('V4', 'fold', 0, 0, 0, 'MP'),
            ('V5', 'fold', 0, 0, 0, 'CO'),
            ('Hero', 'raise', 1, 1.50, 1, 'BTN'),
        ])

        # Hand 2: All fold to Hero BTN, Hero folds → ATS opp, not ATS
        self._insert_hand_with_actions('H2', 'BTN', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'fold', 0, 0, 0, 'UTG'),
            ('V4', 'fold', 0, 0, 0, 'MP'),
            ('V5', 'fold', 0, 0, 0, 'CO'),
            ('Hero', 'fold', 1, 0, 0, 'BTN'),
        ])

        # Hand 3: UTG raises, Hero BTN calls → no ATS opp
        self._insert_hand_with_actions('H3', 'BTN', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'raise', 0, 1.50, 1, 'UTG'),
            ('V4', 'fold', 0, 0, 0, 'MP'),
            ('V5', 'fold', 0, 0, 0, 'CO'),
            ('Hero', 'call', 1, 1.50, 1, 'BTN'),
        ])

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['ats_opps'], 2)
        self.assertEqual(overall['ats_hands'], 1)
        self.assertAlmostEqual(overall['ats'], 50.0, places=1)

    def test_stats_by_position(self):
        """Test position-based stat breakdown."""
        # Hand from CO
        self._insert_hand_with_actions('H1', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('Hero', 'raise', 1, 1.50, 1, 'CO'),
        ])

        # Hand from BTN
        self._insert_hand_with_actions('H2', 'BTN', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('V3', 'fold', 0, 0, 0, 'UTG'),
            ('Hero', 'fold', 1, 0, 0, 'BTN'),
        ])

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_preflop_stats()
        by_pos = stats['by_position']

        self.assertIn('CO', by_pos)
        self.assertIn('BTN', by_pos)
        self.assertEqual(by_pos['CO']['total_hands'], 1)
        self.assertAlmostEqual(by_pos['CO']['vpip'], 100.0)
        self.assertEqual(by_pos['BTN']['total_hands'], 1)
        self.assertAlmostEqual(by_pos['BTN']['vpip'], 0.0)

    def test_stats_by_day(self):
        """Test day-based stat breakdown."""
        self._insert_hand_with_actions('H1', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('Hero', 'raise', 1, 1.50, 1, 'CO'),
        ], date='2026-01-15')

        self._insert_hand_with_actions('H2', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('Hero', 'fold', 1, 0, 0, 'CO'),
        ], date='2026-01-16')

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_preflop_stats()
        by_day = stats['by_day']

        self.assertIn('2026-01-15', by_day)
        self.assertIn('2026-01-16', by_day)
        self.assertAlmostEqual(by_day['2026-01-15']['vpip'], 100.0)
        self.assertAlmostEqual(by_day['2026-01-16']['vpip'], 0.0)

    def test_empty_database(self):
        """Test stats with no hands in database."""
        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['total_hands'], 0)
        self.assertAlmostEqual(overall['vpip'], 0.0)
        self.assertAlmostEqual(overall['pfr'], 0.0)

    def test_year_filter(self):
        """Test year filtering excludes other years."""
        self._insert_hand_with_actions('H1', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('Hero', 'raise', 1, 1.50, 1, 'CO'),
        ], date='2026-01-15')

        self._insert_hand_with_actions('H2', 'CO', [
            ('V1', 'post_sb', 0, 0.25, 0, 'SB'),
            ('V2', 'post_bb', 0, 0.50, 0, 'BB'),
            ('Hero', 'raise', 1, 1.50, 1, 'CO'),
        ], date='2025-12-31')

        analyzer_2026 = CashAnalyzer(self.repo, year='2026')
        stats_2026 = analyzer_2026.get_preflop_stats()
        self.assertEqual(stats_2026['overall']['total_hands'], 1)

        analyzer_2025 = CashAnalyzer(self.repo, year='2025')
        stats_2025 = analyzer_2025.get_preflop_stats()
        self.assertEqual(stats_2025['overall']['total_hands'], 1)

    def test_hands_without_hero_actions_excluded(self):
        """Hands where hero has no actions should not be counted."""
        hand = _make_hand('NO_HERO', hero_position='CO')
        self.repo.insert_hand(hand)
        # Insert only opponent actions
        self.repo.insert_actions_batch([
            _make_action('NO_HERO', 'V1', 'post_sb', 0, 'SB'),
            _make_action('NO_HERO', 'V2', 'post_bb', 1, 'BB'),
            _make_action('NO_HERO', 'V1', 'fold', 2, 'SB'),
        ])
        self.conn.commit()

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_preflop_stats()
        self.assertEqual(stats['overall']['total_hands'], 0)


# ── Repository Query Tests ───────────────────────────────────────────

class TestPreflopActionSequencesQuery(unittest.TestCase):
    """Test Repository.get_preflop_action_sequences()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def test_returns_preflop_only(self):
        """Only preflop actions are returned."""
        hand = _make_hand('H1')
        self.repo.insert_hand(hand)

        actions = [
            ActionData(hand_id='H1', street='preflop', player='Hero',
                       action_type='raise', amount=1.5, is_hero=1,
                       sequence_order=0, position='CO', is_voluntary=1),
            ActionData(hand_id='H1', street='flop', player='Hero',
                       action_type='bet', amount=2.0, is_hero=1,
                       sequence_order=0, position='CO', is_voluntary=0),
        ]
        self.repo.insert_actions_batch(actions)
        self.conn.commit()

        result = self.repo.get_preflop_action_sequences('2026')
        # Only 1 row returned (flop action filtered out by WHERE street='preflop')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['action_type'], 'raise')

    def test_excludes_tournament_hands(self):
        """Only cash game hands are returned."""
        cash_hand = _make_hand('CASH1')
        self.repo.insert_hand(cash_hand)

        tourney_hand = HandData(
            hand_id='TOURNEY1', platform='GGPoker', game_type='tournament',
            date=datetime(2026, 1, 15), blinds_sb=25, blinds_bb=50,
            hero_cards='Ah Kd', hero_position='CO',
            invested=50, won=0, net=-50, rake=0,
            table_name='T', num_players=6,
        )
        self.repo.insert_hand(tourney_hand)

        for hid in ('CASH1', 'TOURNEY1'):
            self.repo.insert_actions_batch([
                ActionData(hand_id=hid, street='preflop', player='Hero',
                           action_type='raise', amount=1.5, is_hero=1,
                           sequence_order=0, position='CO', is_voluntary=1),
            ])
        self.conn.commit()

        result = self.repo.get_preflop_action_sequences('2026')
        hand_ids = {r['hand_id'] for r in result}
        self.assertIn('CASH1', hand_ids)
        self.assertNotIn('TOURNEY1', hand_ids)

    def test_includes_hero_position_and_day(self):
        """Returned rows include hero_position and day from hands table."""
        hand = _make_hand('H1', date='2026-02-20', hero_position='BTN')
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            ActionData(hand_id='H1', street='preflop', player='Hero',
                       action_type='fold', amount=0, is_hero=1,
                       sequence_order=0, position='BTN', is_voluntary=0),
        ])
        self.conn.commit()

        result = self.repo.get_preflop_action_sequences('2026')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['hero_position'], 'BTN')
        self.assertEqual(result[0]['day'], '2026-02-20')

    def test_ordered_by_hand_and_sequence(self):
        """Results are ordered by hand_id then sequence_order."""
        for hid in ('H1', 'H2'):
            self.repo.insert_hand(_make_hand(hid))
            self.repo.insert_actions_batch([
                ActionData(hand_id=hid, street='preflop', player='V1',
                           action_type='post_sb', amount=0.25, is_hero=0,
                           sequence_order=0, position='SB', is_voluntary=0),
                ActionData(hand_id=hid, street='preflop', player='Hero',
                           action_type='fold', amount=0, is_hero=1,
                           sequence_order=1, position='CO', is_voluntary=0),
            ])
        self.conn.commit()

        result = self.repo.get_preflop_action_sequences('2026')
        self.assertEqual(len(result), 4)
        # H1 actions should come before H2
        self.assertEqual(result[0]['hand_id'], 'H1')
        self.assertEqual(result[0]['sequence_order'], 0)
        self.assertEqual(result[1]['hand_id'], 'H1')
        self.assertEqual(result[1]['sequence_order'], 1)


# ── HTML Report Integration Tests ────────────────────────────────────

class TestReportIntegration(unittest.TestCase):
    """Test that Player Stats section appears in HTML report."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def test_player_stats_section_rendered(self):
        """Verify Player Stats section appears when stats are available."""
        hand = _make_hand('H1')
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            ActionData(hand_id='H1', street='preflop', player='V1',
                       action_type='post_sb', amount=0.25, is_hero=0,
                       sequence_order=0, position='SB', is_voluntary=0),
            ActionData(hand_id='H1', street='preflop', player='V2',
                       action_type='post_bb', amount=0.50, is_hero=0,
                       sequence_order=1, position='BB', is_voluntary=0),
            ActionData(hand_id='H1', street='preflop', player='Hero',
                       action_type='raise', amount=1.50, is_hero=1,
                       sequence_order=2, position='CO', is_voluntary=1),
        ])
        self.conn.commit()

        analyzer = CashAnalyzer(self.repo, year='2026')
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            output_path = f.name

        try:
            generate_cash_report(analyzer, output_path)
            with open(output_path, 'r', encoding='utf-8') as f:
                html = f.read()

            self.assertIn('Player Stats (Preflop)', html)
            self.assertIn('VPIP', html)
            self.assertIn('PFR', html)
            self.assertIn('3-Bet', html)
            self.assertIn('Fold to 3-Bet', html)
            self.assertIn('ATS (Steal)', html)
            # Badge should be present
            self.assertIn('badge-', html)
        finally:
            os.unlink(output_path)

    def test_position_table_rendered(self):
        """Verify position breakdown table appears."""
        hand = _make_hand('H1', hero_position='BTN')
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            ActionData(hand_id='H1', street='preflop', player='V1',
                       action_type='post_sb', amount=0.25, is_hero=0,
                       sequence_order=0, position='SB', is_voluntary=0),
            ActionData(hand_id='H1', street='preflop', player='V2',
                       action_type='post_bb', amount=0.50, is_hero=0,
                       sequence_order=1, position='BB', is_voluntary=0),
            ActionData(hand_id='H1', street='preflop', player='Hero',
                       action_type='raise', amount=1.50, is_hero=1,
                       sequence_order=2, position='BTN', is_voluntary=1),
        ])
        self.conn.commit()

        analyzer = CashAnalyzer(self.repo, year='2026')
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            output_path = f.name

        try:
            generate_cash_report(analyzer, output_path)
            with open(output_path, 'r', encoding='utf-8') as f:
                html = f.read()

            self.assertIn('Stats por Posi\u00e7\u00e3o', html)
            self.assertIn('BTN', html)
        finally:
            os.unlink(output_path)

    def test_no_stats_section_when_no_actions(self):
        """No Player Stats section when there are no action records."""
        # Insert a hand but no actions
        hand = _make_hand('H1')
        self.repo.insert_hand(hand)
        self.conn.commit()

        analyzer = CashAnalyzer(self.repo, year='2026')
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            output_path = f.name

        try:
            generate_cash_report(analyzer, output_path)
            with open(output_path, 'r', encoding='utf-8') as f:
                html = f.read()

            self.assertNotIn('Player Stats (Preflop)', html)
        finally:
            os.unlink(output_path)


# ── End-to-End with Real Parser Tests ────────────────────────────────

class TestEndToEndWithParser(unittest.TestCase):
    """End-to-end: parse hand → persist → calculate stats."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        from src.parsers.ggpoker import GGPokerParser
        self.parser = GGPokerParser()

    def tearDown(self):
        self.conn.close()

    HAND_RAISE = (
        "Poker Hand #RC1001: Hold'em No Limit ($0.25/$0.50) - "
        "2026/01/15 20:30:00\n"
        "Table 'RushAndCash999' 6-max Seat #4 is the button\n"
        "Seat 1: Player1 ($50.00 in chips)\n"
        "Seat 2: Player2 ($48.00 in chips)\n"
        "Seat 3: Hero ($52.00 in chips)\n"
        "Seat 4: Player4 ($55.00 in chips)\n"
        "Seat 5: Player5 ($45.00 in chips)\n"
        "Seat 6: Player6 ($60.00 in chips)\n"
        "Player5: posts small blind $0.25\n"
        "Player6: posts big blind $0.50\n"
        "*** HOLE CARDS ***\n"
        "Dealt to Hero [Ah Kd]\n"
        "Player1: folds\n"
        "Player2: folds\n"
        "Hero: raises $1.00 to $1.50\n"
        "Player4: folds\n"
        "Player5: folds\n"
        "Player6: folds\n"
        "*** SUMMARY ***\n"
        "Total pot $1.25 | Rake $0.00\n"
    )

    HAND_FOLD = (
        "Poker Hand #RC1002: Hold'em No Limit ($0.25/$0.50) - "
        "2026/01/15 20:35:00\n"
        "Table 'RushAndCash999' 6-max Seat #4 is the button\n"
        "Seat 1: Player1 ($50.00 in chips)\n"
        "Seat 2: Player2 ($48.00 in chips)\n"
        "Seat 3: Hero ($52.00 in chips)\n"
        "Seat 4: Player4 ($55.00 in chips)\n"
        "Seat 5: Player5 ($45.00 in chips)\n"
        "Seat 6: Player6 ($60.00 in chips)\n"
        "Player5: posts small blind $0.25\n"
        "Player6: posts big blind $0.50\n"
        "*** HOLE CARDS ***\n"
        "Dealt to Hero [2h 7c]\n"
        "Player1: raises $1.00 to $1.50\n"
        "Player2: folds\n"
        "Hero: folds\n"
        "Player4: folds\n"
        "Player5: folds\n"
        "Player6: folds\n"
        "*** SUMMARY ***\n"
        "Total pot $1.25 | Rake $0.00\n"
    )

    def test_end_to_end_vpip_pfr(self):
        """Full pipeline: parse two hands, one raise + one fold → VPIP=50%, PFR=50%."""
        for hand_text in (self.HAND_RAISE, self.HAND_FOLD):
            hand = self.parser.parse_single_hand(hand_text)
            actions, board, positions = self.parser.parse_actions(hand_text, hand.hand_id)
            self.repo.insert_hand(hand)
            self.repo.insert_actions_batch(actions)
            hero_pos = positions.get('Hero')
            if hero_pos:
                self.repo.update_hand_position(hand.hand_id, hero_pos)
        self.conn.commit()

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_preflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['total_hands'], 2)
        self.assertAlmostEqual(overall['vpip'], 50.0, places=1)
        self.assertAlmostEqual(overall['pfr'], 50.0, places=1)


if __name__ == '__main__':
    unittest.main()
