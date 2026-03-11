"""Tests for US-032: Advanced Stats (Open Shove, RBW, River Actions, Probe, XF OOP, Won Flop).

Covers:
PREFLOP:
- Open Shove %: hero goes all-in as first raiser
- RBW (Raise By Walk): hero raises when walked in BB

RIVER:
- Bet River %: hero bets on the river
- Call River %: hero calls a river bet

POSTFLOP ADVANCED:
- Probe Bet %: hero bets when villain didn't cbet
- Fold to Probe %: hero folds when probed after missing cbet
- Bet vs Missed CBet %: hero bets when villain missed cbet
- XF OOP %: hero check-folds out of position

WIN RATES:
- Won Saw Flop %: hero won among hands that saw the flop

INTEGRATION:
- Stats computed in CashAnalyzer and TournamentAnalyzer
- Health badges for each stat
- Web data layer integration
"""

import json
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


def _make_action(hand_id, street, player, action_type, seq, position='CO',
                 is_hero=0, amount=0.0, is_voluntary=0):
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


# ═══════════════════════════════════════════════════════════════════════
# PREFLOP: Open Shove
# ═══════════════════════════════════════════════════════════════════════

class TestOpenShove(unittest.TestCase):
    """Test Open Shove detection in _analyze_preflop_hand()."""

    def test_hero_open_shove(self):
        """Hero goes all-in with no prior raises → open_shove=True."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'Hero', 'action_type': 'all-in', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 25.0},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['open_shove'])
        self.assertTrue(result['vpip'])
        self.assertTrue(result['pfr'])

    def test_hero_normal_raise_not_shove(self):
        """Hero open-raises (not all-in) → open_shove=False."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 1.5},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertFalse(result['open_shove'])
        self.assertTrue(result['vpip'])
        self.assertTrue(result['pfr'])

    def test_hero_shove_over_raise_not_open_shove(self):
        """Hero goes all-in after opponent raised → NOT open shove (3-bet shove)."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'is_voluntary': 1, 'position': 'UTG', 'amount': 1.5},
            {'player': 'Hero', 'action_type': 'all-in', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 25.0},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertFalse(result['open_shove'])

    def test_hero_fold_no_shove(self):
        """Hero folds → open_shove=False."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'is_voluntary': 1, 'position': 'UTG', 'amount': 1.5},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'is_voluntary': 0, 'position': 'CO'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertFalse(result['open_shove'])


# ═══════════════════════════════════════════════════════════════════════
# PREFLOP: Raise By Walk (RBW)
# ═══════════════════════════════════════════════════════════════════════

class TestRaiseByWalk(unittest.TestCase):
    """Test RBW detection in _analyze_preflop_hand()."""

    def test_hero_bb_walk_raises(self):
        """Hero in BB, everyone folds, hero raises → RBW."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'CO'},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
            {'player': 'V4', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'SB'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'BB', 'amount': 1.5},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['rbw_opp'])
        self.assertTrue(result['rbw'])

    def test_hero_bb_walk_checks(self):
        """Hero in BB, everyone folds, hero checks → rbw_opp=True, rbw=False."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'CO'},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
            {'player': 'V4', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'SB'},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'is_voluntary': 0, 'position': 'BB'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['rbw_opp'])
        self.assertFalse(result['rbw'])

    def test_hero_not_bb_no_rbw(self):
        """Hero not in BB → no RBW opportunity."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'CO', 'amount': 1.5},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertFalse(result['rbw_opp'])
        self.assertFalse(result['rbw'])

    def test_hero_bb_limped_pot_no_walk(self):
        """Hero in BB, someone limps → NOT a walk."""
        actions = [
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'is_voluntary': 1, 'position': 'UTG', 'amount': 0.5},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'CO'},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
            {'player': 'V4', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'SB'},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'is_voluntary': 1, 'position': 'BB', 'amount': 2.0},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertFalse(result['rbw_opp'])

    def test_hero_bb_walk_shoves(self):
        """Hero in BB walk, goes all-in → RBW=True (shove counts as raise)."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'UTG'},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'CO'},
            {'player': 'V3', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'BTN'},
            {'player': 'V4', 'action_type': 'fold', 'is_hero': 0, 'is_voluntary': 0, 'position': 'SB'},
            {'player': 'Hero', 'action_type': 'all-in', 'is_hero': 1, 'is_voluntary': 1, 'position': 'BB', 'amount': 25.0},
        ]
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['rbw_opp'])
        self.assertTrue(result['rbw'])


# ═══════════════════════════════════════════════════════════════════════
# RIVER: Bet River & Call River
# ═══════════════════════════════════════════════════════════════════════

class TestRiverStats(unittest.TestCase):
    """Test Bet River and Call River detection in _analyze_postflop_hand()."""

    def _river_hand_hero_bets(self):
        """Hero bets the river."""
        return [
            # Preflop
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
            # Turn
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'turn',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'turn',
             'position': 'CO', 'amount': 0},
            # River
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'river',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'river',
             'position': 'CO', 'amount': 5.0},
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'street': 'river',
             'position': 'BB', 'amount': 0},
        ]

    def test_hero_bets_river(self):
        """Hero bets on the river → bet_river=True."""
        actions = self._river_hand_hero_bets()
        result = CashAnalyzer._analyze_postflop_hand(actions, 5.0)
        self.assertTrue(result['bet_river_opp'])
        self.assertTrue(result['bet_river'])

    def test_hero_checks_river(self):
        """Hero checks on the river → bet_river_opp=True, bet_river=False."""
        actions = [
            # Preflop
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
            # River
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'river',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'river',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 0.0)
        self.assertTrue(result['bet_river_opp'])
        self.assertFalse(result['bet_river'])

    def test_hero_calls_river_bet(self):
        """Hero calls opponent's river bet → call_river=True."""
        actions = [
            # Preflop
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
            # River
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'river',
             'position': 'BB', 'amount': 5.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'river',
             'position': 'CO', 'amount': 5.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -5.0)
        self.assertTrue(result['call_river_opp'])
        self.assertTrue(result['call_river'])

    def test_hero_folds_to_river_bet(self):
        """Hero folds to opponent's river bet → call_river_opp=True, call_river=False."""
        actions = [
            # Preflop
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
            # River
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'river',
             'position': 'BB', 'amount': 5.0},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'street': 'river',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -1.5)
        self.assertTrue(result['call_river_opp'])
        self.assertFalse(result['call_river'])

    def test_no_river_action(self):
        """Hand ends on flop → no river stats."""
        actions = [
            # Preflop
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.5)
        self.assertFalse(result['bet_river_opp'])
        self.assertFalse(result['bet_river'])
        self.assertFalse(result['call_river_opp'])
        self.assertFalse(result['call_river'])


# ═══════════════════════════════════════════════════════════════════════
# POSTFLOP: Probe Bet & Fold to Probe & Bet vs Missed CBet
# ═══════════════════════════════════════════════════════════════════════

class TestProbeStats(unittest.TestCase):
    """Test Probe, Fold to Probe, and Bet vs Missed CBet."""

    def test_probe_bet_hero_bets_when_villain_misses_cbet(self):
        """Villain raised preflop, misses cbet, hero bets flop → probe=True."""
        actions = [
            # Preflop: villain raises, hero calls
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: villain checks (misses cbet), hero bets (probe)
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 0.0)
        # Villain missed cbet but hero didn't bet either in this scenario
        self.assertTrue(result['probe_opp'])
        self.assertFalse(result['probe'])

    def test_probe_bet_hero_donks_when_villain_misses_cbet(self):
        """Villain raised preflop, misses cbet, hero bets flop → probe=True."""
        actions = [
            # Preflop: villain raises, hero calls
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: hero bets (donk/probe), villain had no chance to cbet
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'street': 'flop',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.5)
        self.assertTrue(result['probe_opp'])
        self.assertTrue(result['probe'])
        self.assertTrue(result['bet_vs_missed_cbet_opp'])
        self.assertTrue(result['bet_vs_missed_cbet'])

    def test_no_probe_when_villain_cbets(self):
        """Villain raised preflop and cbets → no probe opportunity."""
        actions = [
            # Preflop: villain raises, hero calls
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: hero checks, villain bets (cbet)
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -2.0)
        self.assertFalse(result['probe_opp'])
        self.assertFalse(result['probe'])
        self.assertFalse(result['bet_vs_missed_cbet_opp'])

    def test_no_probe_when_hero_is_pfa(self):
        """Hero is the preflop aggressor → probe logic doesn't apply to hero."""
        actions = [
            # Preflop: hero raises
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: villain checks, hero bets (this is a cbet, not probe)
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.5)
        self.assertFalse(result['probe_opp'])
        self.assertFalse(result['probe'])

    def test_fold_to_probe_hero_is_pfa_misses_cbet_folds(self):
        """Hero is PFA, misses cbet, opponent probes, hero folds → fold_to_probe=True."""
        actions = [
            # Preflop: hero raises
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: villain checks, hero checks (miss cbet), villain bets (probe), hero folds
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -1.5)
        self.assertTrue(result['fold_to_probe_opp'])
        self.assertTrue(result['fold_to_probe'])

    def test_fold_to_probe_hero_calls(self):
        """Hero is PFA, misses cbet, opponent probes, hero calls → fold_to_probe=False."""
        actions = [
            # Preflop: hero raises
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: villain checks, hero checks (miss cbet), villain bets (probe), hero calls
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -3.5)
        self.assertTrue(result['fold_to_probe_opp'])
        self.assertFalse(result['fold_to_probe'])

    def test_no_fold_to_probe_when_hero_cbets(self):
        """Hero is PFA and cbets → no fold_to_probe opportunity."""
        actions = [
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: hero bets (cbet)
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.5)
        self.assertFalse(result['fold_to_probe_opp'])


# ═══════════════════════════════════════════════════════════════════════
# POSTFLOP: XF OOP (Check-Fold Out of Position)
# ═══════════════════════════════════════════════════════════════════════

class TestXfOop(unittest.TestCase):
    """Test XF OOP (check-fold out of position) detection."""

    def test_hero_check_folds_oop(self):
        """Hero acts first (OOP), checks, opponent bets, hero folds → xf_oop=True."""
        actions = [
            # Preflop
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: hero acts first (OOP), checks, villain bets, hero folds
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -1.5)
        self.assertTrue(result['xf_oop_opp'])
        self.assertTrue(result['xf_oop'])

    def test_hero_check_calls_oop(self):
        """Hero acts first (OOP), checks, opponent bets, hero calls → xf_oop=False."""
        actions = [
            # Preflop
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: hero checks, villain bets, hero calls
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -3.5)
        self.assertTrue(result['xf_oop_opp'])
        self.assertFalse(result['xf_oop'])

    def test_hero_in_position_no_xf_oop(self):
        """Hero acts second (IP) → no XF OOP opportunity."""
        actions = [
            # Preflop
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: villain acts first (OOP), not hero
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.5)
        self.assertFalse(result['xf_oop_opp'])
        self.assertFalse(result['xf_oop'])

    def test_hero_check_no_bet_no_xf_oop(self):
        """Hero checks OOP, opponent checks back → no XF OOP (no bet to fold to)."""
        actions = [
            # Preflop
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: both check
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 0.0)
        self.assertFalse(result['xf_oop_opp'])
        self.assertFalse(result['xf_oop'])


# ═══════════════════════════════════════════════════════════════════════
# WIN RATES: Won Saw Flop
# ═══════════════════════════════════════════════════════════════════════

class TestWonSawFlop(unittest.TestCase):
    """Test Won Saw Flop detection."""

    def test_won_saw_flop_positive_net(self):
        """Hero sees flop and wins → won_saw_flop=True."""
        actions = [
            # Preflop
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.5)
        self.assertTrue(result['saw_flop'])
        self.assertTrue(result['won_saw_flop'])

    def test_lost_saw_flop_negative_net(self):
        """Hero sees flop and loses → won_saw_flop=False."""
        actions = [
            # Preflop
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -1.5)
        self.assertTrue(result['saw_flop'])
        self.assertFalse(result['won_saw_flop'])

    def test_no_flop_no_won_saw_flop(self):
        """Hero folds preflop → saw_flop=False, won_saw_flop not applicable."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 0, 'is_voluntary': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -0.5)
        self.assertFalse(result['saw_flop'])
        # won_saw_flop should not be in result when no flop seen
        self.assertNotIn('won_saw_flop', result)


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION: CashAnalyzer get_preflop_stats / get_postflop_stats
# ═══════════════════════════════════════════════════════════════════════

class TestPreflopStatsIntegrationUS032(unittest.TestCase):
    """Integration test for Open Shove and RBW in get_preflop_stats()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def _insert_hand(self, hand, actions):
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch(actions)

    def test_open_shove_stats(self):
        """Open shove counted in preflop stats."""
        # Hand 1: hero open shoves
        h1 = _make_hand('H1', hero_position='BTN')
        a1 = [
            _make_action('H1', 'preflop', 'V1', 'fold', 1, 'UTG'),
            _make_action('H1', 'preflop', 'Hero', 'all-in', 2, 'BTN', is_hero=1, amount=25.0, is_voluntary=1),
            _make_action('H1', 'preflop', 'V2', 'fold', 3, 'SB'),
            _make_action('H1', 'preflop', 'V3', 'fold', 4, 'BB'),
        ]
        self._insert_hand(h1, a1)

        # Hand 2: hero open raises (not shove)
        h2 = _make_hand('H2', hero_position='CO')
        a2 = [
            _make_action('H2', 'preflop', 'V1', 'fold', 1, 'UTG'),
            _make_action('H2', 'preflop', 'Hero', 'raise', 2, 'CO', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H2', 'preflop', 'V2', 'fold', 3, 'BTN'),
        ]
        self._insert_hand(h2, a2)

        analyzer = CashAnalyzer(self.repo, year='2026')
        overall = analyzer.get_preflop_stats()['overall']
        # 1 out of 2 hands is open shove → 50%
        self.assertEqual(overall['open_shove'], 50.0)
        self.assertEqual(overall['open_shove_hands'], 1)
        self.assertIn('open_shove_health', overall)

    def test_rbw_stats(self):
        """RBW counted in preflop stats."""
        # Hand 1: walk, hero raises
        h1 = _make_hand('H1', hero_position='BB')
        a1 = [
            _make_action('H1', 'preflop', 'V1', 'fold', 1, 'UTG'),
            _make_action('H1', 'preflop', 'V2', 'fold', 2, 'CO'),
            _make_action('H1', 'preflop', 'V3', 'fold', 3, 'BTN'),
            _make_action('H1', 'preflop', 'V4', 'fold', 4, 'SB'),
            _make_action('H1', 'preflop', 'Hero', 'raise', 5, 'BB', is_hero=1, amount=1.5, is_voluntary=1),
        ]
        self._insert_hand(h1, a1)

        # Hand 2: walk, hero checks
        h2 = _make_hand('H2', hero_position='BB')
        a2 = [
            _make_action('H2', 'preflop', 'V1', 'fold', 1, 'UTG'),
            _make_action('H2', 'preflop', 'V2', 'fold', 2, 'CO'),
            _make_action('H2', 'preflop', 'V3', 'fold', 3, 'BTN'),
            _make_action('H2', 'preflop', 'V4', 'fold', 4, 'SB'),
            _make_action('H2', 'preflop', 'Hero', 'check', 5, 'BB', is_hero=1),
        ]
        self._insert_hand(h2, a2)

        analyzer = CashAnalyzer(self.repo, year='2026')
        overall = analyzer.get_preflop_stats()['overall']
        # 1 out of 2 walks = 50% RBW
        self.assertEqual(overall['rbw'], 50.0)
        self.assertEqual(overall['rbw_hands'], 1)
        self.assertEqual(overall['rbw_opps'], 2)
        self.assertIn('rbw_health', overall)


class TestPostflopStatsIntegrationUS032(unittest.TestCase):
    """Integration test for new postflop stats in get_postflop_stats()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def _insert_hand(self, hand, actions):
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch(actions)

    def test_won_saw_flop_stats(self):
        """Won Saw Flop computed in postflop stats."""
        # Hand 1: sees flop and wins
        h1 = _make_hand('H1', hero_position='CO', won=3.5, net=2.0)
        a1 = [
            _make_action('H1', 'preflop', 'Hero', 'raise', 1, 'CO', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H1', 'preflop', 'V1', 'call', 2, 'BB', amount=1.5, is_voluntary=1),
            _make_action('H1', 'flop', 'V1', 'check', 3, 'BB'),
            _make_action('H1', 'flop', 'Hero', 'bet', 4, 'CO', is_hero=1, amount=2.0),
            _make_action('H1', 'flop', 'V1', 'fold', 5, 'BB'),
        ]
        self._insert_hand(h1, a1)

        # Hand 2: sees flop and loses
        h2 = _make_hand('H2', hero_position='CO', won=0.0, net=-3.5)
        a2 = [
            _make_action('H2', 'preflop', 'Hero', 'raise', 1, 'CO', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H2', 'preflop', 'V1', 'call', 2, 'BB', amount=1.5, is_voluntary=1),
            _make_action('H2', 'flop', 'V1', 'bet', 3, 'BB', amount=2.0),
            _make_action('H2', 'flop', 'Hero', 'call', 4, 'CO', is_hero=1, amount=2.0),
            _make_action('H2', 'turn', 'V1', 'bet', 5, 'BB', amount=4.0),
            _make_action('H2', 'turn', 'Hero', 'fold', 6, 'CO', is_hero=1),
        ]
        self._insert_hand(h2, a2)

        analyzer = CashAnalyzer(self.repo, year='2026')
        overall = analyzer.get_postflop_stats()['overall']
        # 1 out of 2 saw-flop hands won → 50%
        self.assertEqual(overall['won_saw_flop'], 50.0)
        self.assertEqual(overall['won_saw_flop_hands'], 1)
        self.assertIn('won_saw_flop_health', overall)

    def test_bet_river_stats(self):
        """Bet River computed in postflop stats."""
        # Hand 1: hero bets river
        h1 = _make_hand('H1', hero_position='CO', won=8.0, net=4.0)
        a1 = [
            _make_action('H1', 'preflop', 'Hero', 'raise', 1, 'CO', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H1', 'preflop', 'V1', 'call', 2, 'BB', amount=1.5, is_voluntary=1),
            _make_action('H1', 'flop', 'V1', 'check', 3, 'BB'),
            _make_action('H1', 'flop', 'Hero', 'check', 4, 'CO', is_hero=1),
            _make_action('H1', 'river', 'V1', 'check', 5, 'BB'),
            _make_action('H1', 'river', 'Hero', 'bet', 6, 'CO', is_hero=1, amount=4.0),
            _make_action('H1', 'river', 'V1', 'fold', 7, 'BB'),
        ]
        self._insert_hand(h1, a1)

        # Hand 2: hero checks river
        h2 = _make_hand('H2', hero_position='CO', won=3.0, net=1.5)
        a2 = [
            _make_action('H2', 'preflop', 'Hero', 'raise', 1, 'CO', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H2', 'preflop', 'V1', 'call', 2, 'BB', amount=1.5, is_voluntary=1),
            _make_action('H2', 'flop', 'V1', 'check', 3, 'BB'),
            _make_action('H2', 'flop', 'Hero', 'check', 4, 'CO', is_hero=1),
            _make_action('H2', 'river', 'V1', 'check', 5, 'BB'),
            _make_action('H2', 'river', 'Hero', 'check', 6, 'CO', is_hero=1),
        ]
        self._insert_hand(h2, a2)

        analyzer = CashAnalyzer(self.repo, year='2026')
        overall = analyzer.get_postflop_stats()['overall']
        # 1 out of 2 = 50% bet river
        self.assertEqual(overall['bet_river'], 50.0)
        self.assertIn('bet_river_health', overall)

    def test_probe_stats(self):
        """Probe Bet computed in postflop stats."""
        # Hand 1: villain raises preflop, misses cbet, hero probes
        h1 = _make_hand('H1', hero_position='BB', won=3.5, net=2.0)
        a1 = [
            _make_action('H1', 'preflop', 'V1', 'raise', 1, 'CO', amount=1.5, is_voluntary=1),
            _make_action('H1', 'preflop', 'Hero', 'call', 2, 'BB', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H1', 'flop', 'Hero', 'bet', 3, 'BB', is_hero=1, amount=2.0),
            _make_action('H1', 'flop', 'V1', 'fold', 4, 'CO'),
        ]
        self._insert_hand(h1, a1)

        # Hand 2: villain raises preflop, misses cbet, hero checks too
        h2 = _make_hand('H2', hero_position='BB', won=0.0, net=-1.5)
        a2 = [
            _make_action('H2', 'preflop', 'V1', 'raise', 1, 'CO', amount=1.5, is_voluntary=1),
            _make_action('H2', 'preflop', 'Hero', 'call', 2, 'BB', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H2', 'flop', 'Hero', 'check', 3, 'BB', is_hero=1),
            _make_action('H2', 'flop', 'V1', 'check', 4, 'CO'),
        ]
        self._insert_hand(h2, a2)

        analyzer = CashAnalyzer(self.repo, year='2026')
        overall = analyzer.get_postflop_stats()['overall']
        # 1 out of 2 = 50% probe
        self.assertEqual(overall['probe'], 50.0)
        self.assertIn('probe_health', overall)

    def test_xf_oop_stats(self):
        """XF OOP computed in postflop stats."""
        # Hand 1: hero OOP check-folds
        h1 = _make_hand('H1', hero_position='BB', won=0.0, net=-1.5)
        a1 = [
            _make_action('H1', 'preflop', 'V1', 'raise', 1, 'CO', amount=1.5, is_voluntary=1),
            _make_action('H1', 'preflop', 'Hero', 'call', 2, 'BB', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H1', 'flop', 'Hero', 'check', 3, 'BB', is_hero=1),
            _make_action('H1', 'flop', 'V1', 'bet', 4, 'CO', amount=2.0),
            _make_action('H1', 'flop', 'Hero', 'fold', 5, 'BB', is_hero=1),
        ]
        self._insert_hand(h1, a1)

        # Hand 2: hero OOP check-calls
        h2 = _make_hand('H2', hero_position='BB', won=0.0, net=-3.5)
        a2 = [
            _make_action('H2', 'preflop', 'V1', 'raise', 1, 'CO', amount=1.5, is_voluntary=1),
            _make_action('H2', 'preflop', 'Hero', 'call', 2, 'BB', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H2', 'flop', 'Hero', 'check', 3, 'BB', is_hero=1),
            _make_action('H2', 'flop', 'V1', 'bet', 4, 'CO', amount=2.0),
            _make_action('H2', 'flop', 'Hero', 'call', 5, 'BB', is_hero=1, amount=2.0),
        ]
        self._insert_hand(h2, a2)

        analyzer = CashAnalyzer(self.repo, year='2026')
        overall = analyzer.get_postflop_stats()['overall']
        # 1 out of 2 = 50% xf_oop
        self.assertEqual(overall['xf_oop'], 50.0)
        self.assertIn('xf_oop_health', overall)

    def test_all_new_postflop_stats_have_health_badges(self):
        """All US-032 postflop stats have health badge classifications."""
        # Insert minimal hand
        h = _make_hand('H1', hero_position='CO', won=3.5, net=2.0)
        a = [
            _make_action('H1', 'preflop', 'Hero', 'raise', 1, 'CO', is_hero=1, amount=1.5, is_voluntary=1),
            _make_action('H1', 'preflop', 'V1', 'call', 2, 'BB', amount=1.5, is_voluntary=1),
            _make_action('H1', 'flop', 'V1', 'check', 3, 'BB'),
            _make_action('H1', 'flop', 'Hero', 'bet', 4, 'CO', is_hero=1, amount=2.0),
            _make_action('H1', 'flop', 'V1', 'fold', 5, 'BB'),
        ]
        self._insert_hand(h, a)

        analyzer = CashAnalyzer(self.repo, year='2026')
        overall = analyzer.get_postflop_stats()['overall']
        for s in ('won_saw_flop', 'bet_river', 'call_river', 'probe',
                  'fold_to_probe', 'bet_vs_missed_cbet', 'xf_oop'):
            self.assertIn(f'{s}_health', overall, f'Missing health badge for {s}')


# ═══════════════════════════════════════════════════════════════════════
# HEALTH BADGES: Verify classification
# ═══════════════════════════════════════════════════════════════════════

class TestHealthBadgesUS032(unittest.TestCase):
    """Test health badge classification for US-032 stats."""

    def test_preflop_open_shove_health(self):
        self.assertEqual(CashAnalyzer._classify_health('open_shove', 3.0), 'good')
        self.assertEqual(CashAnalyzer._classify_health('open_shove', 8.0), 'warning')
        self.assertEqual(CashAnalyzer._classify_health('open_shove', 15.0), 'danger')

    def test_preflop_rbw_health(self):
        self.assertEqual(CashAnalyzer._classify_health('rbw', 65.0), 'good')
        self.assertEqual(CashAnalyzer._classify_health('rbw', 40.0), 'warning')
        self.assertEqual(CashAnalyzer._classify_health('rbw', 20.0), 'danger')

    def test_postflop_won_saw_flop_health(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('won_saw_flop', 50.0), 'good')
        self.assertEqual(CashAnalyzer._classify_postflop_health('won_saw_flop', 40.0), 'warning')
        self.assertEqual(CashAnalyzer._classify_postflop_health('won_saw_flop', 30.0), 'danger')

    def test_postflop_bet_river_health(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('bet_river', 40.0), 'good')
        self.assertEqual(CashAnalyzer._classify_postflop_health('bet_river', 55.0), 'warning')
        self.assertEqual(CashAnalyzer._classify_postflop_health('bet_river', 65.0), 'danger')

    def test_postflop_call_river_health(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('call_river', 30.0), 'good')
        self.assertEqual(CashAnalyzer._classify_postflop_health('call_river', 50.0), 'warning')

    def test_postflop_probe_health(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('probe', 40.0), 'good')
        self.assertEqual(CashAnalyzer._classify_postflop_health('probe', 15.0), 'danger')

    def test_postflop_fold_to_probe_health(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('fold_to_probe', 45.0), 'good')
        self.assertEqual(CashAnalyzer._classify_postflop_health('fold_to_probe', 70.0), 'danger')

    def test_postflop_bet_vs_missed_cbet_health(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('bet_vs_missed_cbet', 40.0), 'good')

    def test_postflop_xf_oop_health(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('xf_oop', 25.0), 'good')
        self.assertEqual(CashAnalyzer._classify_postflop_health('xf_oop', 50.0), 'danger')


# ═══════════════════════════════════════════════════════════════════════
# WEB DATA LAYER: overview and stats integration
# ═══════════════════════════════════════════════════════════════════════

class TestWebDataIntegrationUS032(unittest.TestCase):
    """Test web data layer includes US-032 stats."""

    def test_stat_labels_include_new_stats(self):
        from src.web.data import _STAT_LABELS
        for s in ('open_shove', 'rbw', 'won_saw_flop', 'bet_river',
                  'call_river', 'probe', 'fold_to_probe', 'bet_vs_missed_cbet', 'xf_oop'):
            self.assertIn(s, _STAT_LABELS, f'Missing label for {s}')

    def test_healthy_ranges_include_new_stats(self):
        from src.web.data import _HEALTHY_RANGES
        for s in ('open_shove', 'rbw', 'won_saw_flop', 'bet_river',
                  'call_river', 'probe', 'fold_to_probe', 'bet_vs_missed_cbet', 'xf_oop'):
            self.assertIn(s, _HEALTHY_RANGES, f'Missing healthy range for {s}')

    def test_warning_ranges_include_new_stats(self):
        from src.web.data import _WARNING_RANGES
        for s in ('open_shove', 'rbw', 'won_saw_flop', 'bet_river',
                  'call_river', 'probe', 'fold_to_probe', 'bet_vs_missed_cbet', 'xf_oop'):
            self.assertIn(s, _WARNING_RANGES, f'Missing warning range for {s}')

    def test_classify_health_new_stats(self):
        from src.web.data import _classify_health
        # Verify new stats are classifiable
        self.assertEqual(_classify_health('open_shove', 3.0), 'good')
        self.assertEqual(_classify_health('rbw', 65.0), 'good')
        self.assertEqual(_classify_health('won_saw_flop', 50.0), 'good')
        self.assertEqual(_classify_health('bet_river', 40.0), 'good')
        self.assertEqual(_classify_health('probe', 40.0), 'good')
        self.assertEqual(_classify_health('xf_oop', 25.0), 'good')


# ═══════════════════════════════════════════════════════════════════════
# CONFIG: targets.yaml includes new stats
# ═══════════════════════════════════════════════════════════════════════

class TestConfigUS032(unittest.TestCase):
    """Test config/targets.yaml includes health ranges for US-032 stats."""

    def test_targets_yaml_has_new_preflop_stats(self):
        from src.config import TargetsConfig
        cfg = TargetsConfig.load()
        # open_shove and rbw should be in the preflop healthy/warning ranges
        self.assertIn('open_shove', cfg.healthy_ranges)
        self.assertIn('rbw', cfg.healthy_ranges)

    def test_targets_yaml_has_new_postflop_stats(self):
        from src.config import TargetsConfig
        cfg = TargetsConfig.load()
        for s in ('won_saw_flop', 'bet_river', 'call_river', 'probe',
                  'fold_to_probe', 'bet_vs_missed_cbet', 'xf_oop'):
            self.assertIn(s, cfg.postflop_healthy_ranges, f'Missing target for {s}')
            self.assertIn(s, cfg.postflop_warning_ranges, f'Missing warning target for {s}')


# ═══════════════════════════════════════════════════════════════════════
# TOURNAMENT: Verify TournamentAnalyzer also computes US-032 stats
# ═══════════════════════════════════════════════════════════════════════

class TestTournamentAnalyzerUS032(unittest.TestCase):
    """Verify TournamentAnalyzer includes US-032 stats."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def _insert_tournament_hand(self, hand_id, hero_position='CO',
                                date='2026-01-15', actions_data=None,
                                won=0.0, net=-1.0):
        """Insert a tournament hand with actions."""
        from src.parsers.base import HandData
        hand = HandData(
            hand_id=hand_id,
            platform='GGPoker',
            game_type='tournament',
            date=datetime.fromisoformat(f'{date}T20:00:00'),
            blinds_sb=25,
            blinds_bb=50,
            hero_cards='Ah Kd',
            hero_position=hero_position,
            invested=1.0,
            won=won,
            net=net,
            rake=0.0,
            table_name='T1',
            num_players=6,
            tournament_id='TOURN1',
        )
        self.repo.insert_hand(hand)
        # Insert tournament record
        self.conn.execute("""
            INSERT OR IGNORE INTO tournaments
            (tournament_id, platform, name, date, buy_in, rake, bounty, total_buy_in,
             position, prize, bounty_won, total_players, entries, is_bounty, is_satellite)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('TOURN1', 'GGPoker', 'Test MTT', '2026-01-15', 10.0, 1.0, 0, 11.0,
              1, 50.0, 0, 100, 100, 0, 0))
        if actions_data:
            self.repo.insert_actions_batch(actions_data)

    def test_tournament_preflop_has_open_shove_rbw(self):
        """TournamentAnalyzer preflop stats include open_shove and rbw."""
        from src.analyzers.tournament import TournamentAnalyzer

        # Hand with open shove
        self._insert_tournament_hand('TH1', hero_position='BTN', actions_data=[
            _make_action('TH1', 'preflop', 'V1', 'fold', 1, 'UTG'),
            _make_action('TH1', 'preflop', 'Hero', 'all-in', 2, 'BTN', is_hero=1, amount=500, is_voluntary=1),
            _make_action('TH1', 'preflop', 'V2', 'fold', 3, 'SB'),
            _make_action('TH1', 'preflop', 'V3', 'fold', 4, 'BB'),
        ])

        analyzer = TournamentAnalyzer(self.repo, '2026')
        overall = analyzer.get_preflop_stats()['overall']
        self.assertIn('open_shove', overall)
        self.assertIn('rbw', overall)
        self.assertIn('open_shove_health', overall)
        self.assertIn('rbw_health', overall)
        self.assertEqual(overall['open_shove'], 100.0)

    def test_tournament_postflop_has_new_stats(self):
        """TournamentAnalyzer postflop stats include all US-032 stats."""
        from src.analyzers.tournament import TournamentAnalyzer

        # Hand that sees flop and hero bets river
        self._insert_tournament_hand('TH1', hero_position='CO', won=100, net=50, actions_data=[
            _make_action('TH1', 'preflop', 'Hero', 'raise', 1, 'CO', is_hero=1, amount=150, is_voluntary=1),
            _make_action('TH1', 'preflop', 'V1', 'call', 2, 'BB', amount=150, is_voluntary=1),
            _make_action('TH1', 'flop', 'V1', 'check', 3, 'BB'),
            _make_action('TH1', 'flop', 'Hero', 'check', 4, 'CO', is_hero=1),
            _make_action('TH1', 'river', 'V1', 'check', 5, 'BB'),
            _make_action('TH1', 'river', 'Hero', 'bet', 6, 'CO', is_hero=1, amount=200),
            _make_action('TH1', 'river', 'V1', 'fold', 7, 'BB'),
        ])

        analyzer = TournamentAnalyzer(self.repo, '2026')
        overall = analyzer.get_postflop_stats()['overall']
        for s in ('won_saw_flop', 'bet_river', 'call_river', 'probe',
                  'fold_to_probe', 'bet_vs_missed_cbet', 'xf_oop'):
            self.assertIn(s, overall, f'Missing {s} in tournament postflop stats')
            self.assertIn(f'{s}_health', overall, f'Missing {s}_health in tournament postflop stats')


if __name__ == '__main__':
    unittest.main()
