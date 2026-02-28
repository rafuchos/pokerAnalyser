"""Tests for US-003: Postflop statistics (AF, AFq, WTSD%, W$SD%, CBet%, Fold-to-CBet%, Check-Raise%).

Covers:
- AF (Aggression Factor): (bets + raises) / calls per street and overall
- AFq (Aggression Frequency): (bets + raises) / (bets + raises + calls + folds) per street
- WTSD% (Went To Showdown): % of hands that went to showdown when saw flop
- W$SD% (Won $ at Showdown): % of hands won at showdown
- CBet% (Continuation Bet): % of times hero bet on flop after being preflop aggressor
- Fold to CBet%: % of times hero folded to opponent's CBet
- Check-Raise%: % of times hero check-raised per street
- Stats aggregation: overall, by street, by week
- Health badge classification for postflop stats
- HTML report integration with Postflop Analysis section
- Edge cases (0 hands, no flop seen, all folds, etc.)
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


# ── Postflop Hand Analysis Unit Tests ────────────────────────────────

class TestAnalyzePostflopHand(unittest.TestCase):
    """Test CashAnalyzer._analyze_postflop_hand() logic."""

    def test_hero_folds_preflop_no_flop_seen(self):
        """Hero folds preflop → saw_flop=False, all postflop stats empty."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 0, 'is_voluntary': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -0.5)
        self.assertFalse(result['saw_flop'])
        self.assertFalse(result['went_to_showdown'])
        self.assertFalse(result['cbet_opp'])
        self.assertEqual(result['hero_aggression'], {})
        self.assertEqual(result['check_raise'], {})

    def test_hero_cbet_on_flop(self):
        """Hero raises preflop, bets flop → CBet detected."""
        actions = [
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 0, 'is_voluntary': 0},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V2', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V2', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.5)
        self.assertTrue(result['saw_flop'])
        self.assertTrue(result['cbet_opp'])
        self.assertTrue(result['cbet'])
        self.assertFalse(result['went_to_showdown'])  # V2 folded

    def test_hero_misses_cbet(self):
        """Hero raises preflop, checks flop → missed CBet."""
        actions = [
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 0.0)
        self.assertTrue(result['cbet_opp'])
        self.assertFalse(result['cbet'])

    def test_no_cbet_when_no_preflop_raise(self):
        """Limped pot (no preflop raise) → no CBet opportunity."""
        actions = [
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 0.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'preflop',
             'position': 'BB', 'amount': 0, 'is_voluntary': 0},
            # Flop
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 1.0},
            {'player': 'V1', 'action_type': 'fold', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.0)
        self.assertFalse(result['cbet_opp'])
        self.assertFalse(result['cbet'])

    def test_no_cbet_when_donk_bet(self):
        """Opponent donk-bets before hero (PFA) → hero can't CBet."""
        actions = [
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: opponent donk-bets
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -2.0)
        self.assertTrue(result['cbet_opp'])
        # Hero can't CBet because opponent bet first - hero has 'call', not 'bet'
        self.assertFalse(result['cbet'])

    def test_fold_to_cbet(self):
        """Opponent was PFA, bets flop, hero folds → fold to CBet."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: opponent CBets
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -1.5)
        self.assertTrue(result['fold_to_cbet_opp'])
        self.assertTrue(result['fold_to_cbet'])
        self.assertFalse(result['cbet_opp'])  # Hero wasn't PFA

    def test_call_cbet_no_fold(self):
        """Opponent CBets, hero calls → fold_to_cbet_opp=True, fold_to_cbet=False."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -3.5)
        self.assertTrue(result['fold_to_cbet_opp'])
        self.assertFalse(result['fold_to_cbet'])

    def test_no_fold_to_cbet_when_hero_is_pfa(self):
        """Hero is PFA → no fold_to_cbet opportunity."""
        actions = [
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.5)
        self.assertFalse(result['fold_to_cbet_opp'])
        self.assertFalse(result['fold_to_cbet'])

    def test_went_to_showdown(self):
        """Two players see flop, neither folds → showdown."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            # Turn
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'turn',
             'position': 'UTG', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'turn',
             'position': 'CO', 'amount': 0},
            # River
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'river',
             'position': 'UTG', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'river',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 5.0)
        self.assertTrue(result['went_to_showdown'])
        self.assertTrue(result['won_at_showdown'])

    def test_not_showdown_when_opponent_folds(self):
        """Opponent folds on flop → no showdown."""
        actions = [
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
        self.assertFalse(result['went_to_showdown'])
        self.assertFalse(result['won_at_showdown'])

    def test_not_showdown_when_hero_folds_on_turn(self):
        """Hero folds on turn → no showdown."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            # Turn
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'turn',
             'position': 'UTG', 'amount': 5.0},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'street': 'turn',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -3.5)
        self.assertFalse(result['went_to_showdown'])

    def test_lost_at_showdown(self):
        """Hero goes to showdown but loses (net < 0) → won_at_showdown=False."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
            # River
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'river',
             'position': 'UTG', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'river',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -1.5)
        self.assertTrue(result['went_to_showdown'])
        self.assertFalse(result['won_at_showdown'])

    def test_aggression_factor(self):
        """Hero bets and raises → aggression counted correctly."""
        actions = [
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: hero bets (aggressive)
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'bet', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 2.0},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
            # Turn: hero checks, V1 bets, hero calls (passive)
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'turn',
             'position': 'BB', 'amount': 4.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'turn',
             'position': 'CO', 'amount': 4.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 3.0)
        # Flop: 1 bet, 0 raises, 0 calls
        self.assertEqual(result['hero_aggression']['flop']['bets'], 1)
        self.assertEqual(result['hero_aggression']['flop']['calls'], 0)
        # Turn: 0 bets, 0 raises, 1 call
        self.assertEqual(result['hero_aggression']['turn']['bets'], 0)
        self.assertEqual(result['hero_aggression']['turn']['calls'], 1)

    def test_check_raise_on_flop(self):
        """Hero checks, opponent bets, hero raises → check-raise detected."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: hero check-raises
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 6.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 5.0)
        self.assertIn('flop', result['check_raise'])
        self.assertTrue(result['check_raise']['flop']['opp'])
        self.assertTrue(result['check_raise']['flop']['did'])

    def test_check_call_not_check_raise(self):
        """Hero checks, opponent bets, hero calls → check-raise opp but not done."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: hero checks, calls (not check-raise)
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 2.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'BB', 'amount': 2.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -3.5)
        self.assertIn('flop', result['check_raise'])
        self.assertTrue(result['check_raise']['flop']['opp'])
        self.assertFalse(result['check_raise']['flop']['did'])

    def test_no_check_raise_opp_when_no_bet_after_check(self):
        """Hero checks, opponent checks → no check-raise opportunity."""
        actions = [
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: both check
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 0)
        self.assertNotIn('flop', result['check_raise'])

    def test_multiway_showdown(self):
        """3 players see flop, one folds, two remain → showdown."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V2', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'MP', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            # Flop
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 3.0},
            {'player': 'V2', 'action_type': 'fold', 'is_hero': 0, 'street': 'flop',
             'position': 'MP', 'amount': 0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 3.0},
            # Turn + River check-check
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'turn',
             'position': 'UTG', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'turn',
             'position': 'CO', 'amount': 0},
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'river',
             'position': 'UTG', 'amount': 0},
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'river',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 2.0)
        self.assertTrue(result['went_to_showdown'])
        self.assertTrue(result['won_at_showdown'])

    def test_allin_on_flop_showdown(self):
        """Hero calls all-in on flop → showdown (no turn/river actions needed)."""
        actions = [
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'UTG', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: all-in
            {'player': 'V1', 'action_type': 'all-in', 'is_hero': 0, 'street': 'flop',
             'position': 'UTG', 'amount': 50.0},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 50.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 48.5)
        self.assertTrue(result['went_to_showdown'])
        self.assertTrue(result['won_at_showdown'])

    def test_empty_actions(self):
        """No actions at all → empty result."""
        result = CashAnalyzer._analyze_postflop_hand([], 0)
        self.assertFalse(result['saw_flop'])

    def test_allin_counts_as_aggressive(self):
        """All-in on flop counts as aggressive for AF."""
        actions = [
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'call', 'is_hero': 0, 'street': 'preflop',
             'position': 'BB', 'amount': 1.5, 'is_voluntary': 1},
            # Flop: hero goes all-in
            {'player': 'V1', 'action_type': 'check', 'is_hero': 0, 'street': 'flop',
             'position': 'BB', 'amount': 0},
            {'player': 'Hero', 'action_type': 'all-in', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 50.0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, 1.5)
        self.assertEqual(result['hero_aggression']['flop']['raises'], 1)

    def test_last_raiser_with_3bet(self):
        """When villain 3-bets, villain is PFA (last raiser)."""
        actions = [
            {'player': 'Hero', 'action_type': 'raise', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 1.5, 'is_voluntary': 1},
            {'player': 'V1', 'action_type': 'raise', 'is_hero': 0, 'street': 'preflop',
             'position': 'BTN', 'amount': 4.5, 'is_voluntary': 1},
            {'player': 'Hero', 'action_type': 'call', 'is_hero': 1, 'street': 'preflop',
             'position': 'CO', 'amount': 4.5, 'is_voluntary': 0},
            # Flop
            {'player': 'Hero', 'action_type': 'check', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
            {'player': 'V1', 'action_type': 'bet', 'is_hero': 0, 'street': 'flop',
             'position': 'BTN', 'amount': 5.0},
            {'player': 'Hero', 'action_type': 'fold', 'is_hero': 1, 'street': 'flop',
             'position': 'CO', 'amount': 0},
        ]
        result = CashAnalyzer._analyze_postflop_hand(actions, -4.5)
        # Villain is PFA (last raiser), so hero doesn't have cbet_opp
        self.assertFalse(result['cbet_opp'])
        # But hero has fold_to_cbet opportunity
        self.assertTrue(result['fold_to_cbet_opp'])
        self.assertTrue(result['fold_to_cbet'])


# ── Health Badge Classification Tests ────────────────────────────────

class TestPostflopHealthClassification(unittest.TestCase):
    """Test postflop health badge classification."""

    def test_af_healthy(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('af', 2.5), 'good')

    def test_af_warning_low(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('af', 1.7), 'warning')

    def test_af_danger_low(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('af', 0.5), 'danger')

    def test_af_danger_high(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('af', 6.0), 'danger')

    def test_wtsd_healthy(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('wtsd', 28.0), 'good')

    def test_wsd_healthy(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('wsd', 52.0), 'good')

    def test_cbet_healthy(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('cbet', 68.0), 'good')

    def test_fold_to_cbet_healthy(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('fold_to_cbet', 42.0), 'good')

    def test_check_raise_healthy(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('check_raise', 8.0), 'good')

    def test_unknown_stat_returns_good(self):
        self.assertEqual(CashAnalyzer._classify_postflop_health('unknown', 50.0), 'good')


# ── Week Helper Test ─────────────────────────────────────────────────

class TestGetWeek(unittest.TestCase):
    """Test _get_week helper."""

    def test_normal_date(self):
        result = CashAnalyzer._get_week('2026-01-15')
        self.assertEqual(result, '2026-W03')

    def test_first_week(self):
        result = CashAnalyzer._get_week('2026-01-01')
        self.assertEqual(result, '2026-W01')

    def test_empty_day(self):
        result = CashAnalyzer._get_week('')
        self.assertEqual(result, 'unknown')

    def test_none_day(self):
        result = CashAnalyzer._get_week(None)
        self.assertEqual(result, 'unknown')


# ── Database Integration Tests ───────────────────────────────────────

class TestPostflopStatsIntegration(unittest.TestCase):
    """Integration tests: insert hands/actions → compute postflop stats."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def _insert_hand_with_actions(self, hand_id, hero_position, actions_data,
                                  date='2026-01-15', net=-1.0):
        """Helper: insert a hand and its actions across all streets.

        actions_data: list of (street, player, action_type, is_hero, amount, position)
        """
        hand = _make_hand(hand_id, date=date, hero_position=hero_position, net=net)
        self.repo.insert_hand(hand)

        actions = []
        for seq, (street, player, atype, is_h, amt, pos) in enumerate(actions_data):
            actions.append(_make_action(
                hand_id, street, player, atype, seq, position=pos,
                is_hero=is_h, amount=amt,
            ))
        self.repo.insert_actions_batch(actions)
        self.conn.commit()

    def test_basic_wtsd_and_wsd(self):
        """2 hands that saw flop: one showdown (won), one fold → WTSD=50%, W$SD=100%."""
        # Hand 1: Hero sees flop, goes to showdown, wins
        self._insert_hand_with_actions('H1', 'CO', [
            ('preflop', 'V1', 'raise', 0, 1.5, 'UTG'),
            ('preflop', 'Hero', 'call', 1, 1.5, 'CO'),
            ('flop', 'V1', 'check', 0, 0, 'UTG'),
            ('flop', 'Hero', 'check', 1, 0, 'CO'),
            ('river', 'V1', 'check', 0, 0, 'UTG'),
            ('river', 'Hero', 'check', 1, 0, 'CO'),
        ], net=3.0)

        # Hand 2: Hero sees flop, folds on flop
        self._insert_hand_with_actions('H2', 'CO', [
            ('preflop', 'V1', 'raise', 0, 1.5, 'UTG'),
            ('preflop', 'Hero', 'call', 1, 1.5, 'CO'),
            ('flop', 'V1', 'bet', 0, 3.0, 'UTG'),
            ('flop', 'Hero', 'fold', 1, 0, 'CO'),
        ], net=-1.5)

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['saw_flop_hands'], 2)
        self.assertEqual(overall['wtsd_hands'], 1)
        self.assertAlmostEqual(overall['wtsd'], 50.0, places=1)
        self.assertEqual(overall['wsd_hands'], 1)
        self.assertAlmostEqual(overall['wsd'], 100.0, places=1)

    def test_cbet_stats(self):
        """Hero is PFA in 2 hands: CBets in one, misses in other → CBet=50%."""
        # Hand 1: Hero raises, CBets flop
        self._insert_hand_with_actions('H1', 'CO', [
            ('preflop', 'Hero', 'raise', 1, 1.5, 'CO'),
            ('preflop', 'V1', 'call', 0, 1.5, 'BB'),
            ('flop', 'V1', 'check', 0, 0, 'BB'),
            ('flop', 'Hero', 'bet', 1, 2.0, 'CO'),
            ('flop', 'V1', 'fold', 0, 0, 'BB'),
        ], net=1.5)

        # Hand 2: Hero raises, checks flop (missed CBet)
        self._insert_hand_with_actions('H2', 'CO', [
            ('preflop', 'Hero', 'raise', 1, 1.5, 'CO'),
            ('preflop', 'V1', 'call', 0, 1.5, 'BB'),
            ('flop', 'V1', 'check', 0, 0, 'BB'),
            ('flop', 'Hero', 'check', 1, 0, 'CO'),
        ], net=0.0)

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['cbet_opps'], 2)
        self.assertEqual(overall['cbet_hands'], 1)
        self.assertAlmostEqual(overall['cbet'], 50.0, places=1)

    def test_fold_to_cbet_stats(self):
        """Opponent CBets, hero folds in 1/2 → Fold-to-CBet=50%."""
        # Hand 1: V raises, CBets, Hero folds
        self._insert_hand_with_actions('H1', 'CO', [
            ('preflop', 'V1', 'raise', 0, 1.5, 'UTG'),
            ('preflop', 'Hero', 'call', 1, 1.5, 'CO'),
            ('flop', 'V1', 'bet', 0, 2.0, 'UTG'),
            ('flop', 'Hero', 'fold', 1, 0, 'CO'),
        ], net=-1.5)

        # Hand 2: V raises, CBets, Hero calls
        self._insert_hand_with_actions('H2', 'CO', [
            ('preflop', 'V1', 'raise', 0, 1.5, 'UTG'),
            ('preflop', 'Hero', 'call', 1, 1.5, 'CO'),
            ('flop', 'V1', 'bet', 0, 2.0, 'UTG'),
            ('flop', 'Hero', 'call', 1, 2.0, 'CO'),
        ], net=-3.5)

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['fold_to_cbet_opps'], 2)
        self.assertEqual(overall['fold_to_cbet_hands'], 1)
        self.assertAlmostEqual(overall['fold_to_cbet'], 50.0, places=1)

    def test_af_calculation(self):
        """AF = (bets + raises) / calls → 2 aggressive / 1 call = 2.0."""
        # Hand with 1 bet + 1 raise + 1 call by hero
        self._insert_hand_with_actions('H1', 'CO', [
            ('preflop', 'Hero', 'raise', 1, 1.5, 'CO'),
            ('preflop', 'V1', 'call', 0, 1.5, 'BB'),
            ('flop', 'V1', 'check', 0, 0, 'BB'),
            ('flop', 'Hero', 'bet', 1, 2.0, 'CO'),
            ('flop', 'V1', 'call', 0, 2.0, 'BB'),
            ('turn', 'V1', 'bet', 0, 4.0, 'BB'),
            ('turn', 'Hero', 'raise', 1, 10.0, 'CO'),
            ('turn', 'V1', 'call', 0, 10.0, 'BB'),
            ('river', 'V1', 'bet', 0, 8.0, 'BB'),
            ('river', 'Hero', 'call', 1, 8.0, 'CO'),
        ], net=5.0)

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        # Flop: 1 bet, 0 raises = 1 aggressive. Turn: 1 raise = 1 aggressive. River: 1 call.
        # Total aggressive = 2, total calls = 1
        self.assertAlmostEqual(overall['af'], 2.0, places=1)

    def test_by_street_breakdown(self):
        """Street-level AF and AFq are computed correctly."""
        self._insert_hand_with_actions('H1', 'CO', [
            ('preflop', 'Hero', 'raise', 1, 1.5, 'CO'),
            ('preflop', 'V1', 'call', 0, 1.5, 'BB'),
            # Flop: hero bets (1 aggressive action, 0 calls, 0 folds → AFq = 100%)
            ('flop', 'V1', 'check', 0, 0, 'BB'),
            ('flop', 'Hero', 'bet', 1, 2.0, 'CO'),
            ('flop', 'V1', 'call', 0, 2.0, 'BB'),
            # Turn: hero calls (0 aggressive, 1 call → AFq = 0%)
            ('turn', 'V1', 'bet', 0, 4.0, 'BB'),
            ('turn', 'Hero', 'call', 1, 4.0, 'CO'),
        ], net=0)

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_postflop_stats()
        by_street = stats['by_street']

        self.assertAlmostEqual(by_street['flop']['afq'], 100.0, places=1)
        self.assertAlmostEqual(by_street['turn']['afq'], 0.0, places=1)

    def test_check_raise_integration(self):
        """Check-raise on flop detected in integration test."""
        self._insert_hand_with_actions('H1', 'BB', [
            ('preflop', 'V1', 'raise', 0, 1.5, 'UTG'),
            ('preflop', 'Hero', 'call', 1, 1.5, 'BB'),
            # Flop: hero check-raises
            ('flop', 'Hero', 'check', 1, 0, 'BB'),
            ('flop', 'V1', 'bet', 0, 2.0, 'UTG'),
            ('flop', 'Hero', 'raise', 1, 6.0, 'BB'),
            ('flop', 'V1', 'fold', 0, 0, 'UTG'),
        ], net=3.5)

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']
        by_street = stats['by_street']

        self.assertEqual(overall['check_raise_opps'], 1)
        self.assertEqual(overall['check_raise_hands'], 1)
        self.assertAlmostEqual(overall['check_raise'], 100.0, places=1)
        self.assertAlmostEqual(by_street['flop']['check_raise'], 100.0, places=1)

    def test_weekly_trends(self):
        """Stats grouped by ISO week."""
        # Week 3 (2026-01-15 is Thursday of week 3)
        self._insert_hand_with_actions('H1', 'CO', [
            ('preflop', 'Hero', 'raise', 1, 1.5, 'CO'),
            ('preflop', 'V1', 'call', 0, 1.5, 'BB'),
            ('flop', 'V1', 'check', 0, 0, 'BB'),
            ('flop', 'Hero', 'bet', 1, 2.0, 'CO'),
            ('flop', 'V1', 'fold', 0, 0, 'BB'),
        ], date='2026-01-15', net=1.5)

        # Week 4 (2026-01-22 is Thursday of week 4)
        self._insert_hand_with_actions('H2', 'CO', [
            ('preflop', 'V1', 'raise', 0, 1.5, 'UTG'),
            ('preflop', 'Hero', 'call', 1, 1.5, 'CO'),
            ('flop', 'V1', 'check', 0, 0, 'UTG'),
            ('flop', 'Hero', 'check', 1, 0, 'CO'),
            ('river', 'V1', 'check', 0, 0, 'UTG'),
            ('river', 'Hero', 'check', 1, 0, 'CO'),
        ], date='2026-01-22', net=-1.5)

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_postflop_stats()
        by_week = stats['by_week']

        self.assertIn('2026-W03', by_week)
        self.assertIn('2026-W04', by_week)
        self.assertEqual(by_week['2026-W03']['total_hands'], 1)
        self.assertEqual(by_week['2026-W04']['total_hands'], 1)
        self.assertEqual(by_week['2026-W03']['saw_flop'], 1)

    def test_empty_database(self):
        """No hands → all stats zero."""
        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['total_hands'], 0)
        self.assertEqual(overall['saw_flop_hands'], 0)
        self.assertAlmostEqual(overall['af'], 0.0)
        self.assertAlmostEqual(overall['wtsd'], 0.0)
        self.assertAlmostEqual(overall['cbet'], 0.0)

    def test_hands_without_flop_excluded_from_postflop_stats(self):
        """Hands where hero folds preflop don't affect postflop stats."""
        # Hero folds preflop
        self._insert_hand_with_actions('H1', 'CO', [
            ('preflop', 'V1', 'raise', 0, 1.5, 'UTG'),
            ('preflop', 'Hero', 'fold', 1, 0, 'CO'),
        ], net=0.0)

        # Hero sees flop
        self._insert_hand_with_actions('H2', 'CO', [
            ('preflop', 'Hero', 'raise', 1, 1.5, 'CO'),
            ('preflop', 'V1', 'call', 0, 1.5, 'BB'),
            ('flop', 'V1', 'check', 0, 0, 'BB'),
            ('flop', 'Hero', 'bet', 1, 2.0, 'CO'),
            ('flop', 'V1', 'fold', 0, 0, 'BB'),
        ], net=1.5)

        analyzer = CashAnalyzer(self.repo, year='2026')
        stats = analyzer.get_postflop_stats()
        overall = stats['overall']

        self.assertEqual(overall['total_hands'], 2)
        self.assertEqual(overall['saw_flop_hands'], 1)

    def test_year_filter(self):
        """Year filtering works for postflop stats."""
        self._insert_hand_with_actions('H1', 'CO', [
            ('preflop', 'Hero', 'raise', 1, 1.5, 'CO'),
            ('preflop', 'V1', 'call', 0, 1.5, 'BB'),
            ('flop', 'V1', 'check', 0, 0, 'BB'),
            ('flop', 'Hero', 'bet', 1, 2.0, 'CO'),
            ('flop', 'V1', 'fold', 0, 0, 'BB'),
        ], date='2026-01-15', net=1.5)

        self._insert_hand_with_actions('H2', 'CO', [
            ('preflop', 'Hero', 'raise', 1, 1.5, 'CO'),
            ('preflop', 'V1', 'call', 0, 1.5, 'BB'),
            ('flop', 'V1', 'check', 0, 0, 'BB'),
            ('flop', 'Hero', 'bet', 1, 2.0, 'CO'),
            ('flop', 'V1', 'fold', 0, 0, 'BB'),
        ], date='2025-12-31', net=1.5)

        analyzer_2026 = CashAnalyzer(self.repo, year='2026')
        stats_2026 = analyzer_2026.get_postflop_stats()
        self.assertEqual(stats_2026['overall']['saw_flop_hands'], 1)

        analyzer_2025 = CashAnalyzer(self.repo, year='2025')
        stats_2025 = analyzer_2025.get_postflop_stats()
        self.assertEqual(stats_2025['overall']['saw_flop_hands'], 1)


# ── Repository Query Tests ───────────────────────────────────────────

class TestAllActionSequencesQuery(unittest.TestCase):
    """Test Repository.get_all_action_sequences()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def test_returns_all_streets(self):
        """Returns actions from all streets (preflop, flop, turn, river)."""
        hand = _make_hand('H1')
        self.repo.insert_hand(hand)

        actions = [
            _make_action('H1', 'preflop', 'Hero', 'raise', 0, 'CO', is_hero=1, amount=1.5),
            _make_action('H1', 'flop', 'Hero', 'bet', 1, 'CO', is_hero=1, amount=2.0),
            _make_action('H1', 'turn', 'Hero', 'check', 2, 'CO', is_hero=1),
            _make_action('H1', 'river', 'Hero', 'bet', 3, 'CO', is_hero=1, amount=5.0),
        ]
        self.repo.insert_actions_batch(actions)
        self.conn.commit()

        result = self.repo.get_all_action_sequences('2026')
        streets = {r['street'] for r in result}
        self.assertEqual(streets, {'preflop', 'flop', 'turn', 'river'})

    def test_excludes_tournament_hands(self):
        """Only cash game hands returned."""
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
                _make_action(hid, 'flop', 'Hero', 'bet', 0, 'CO', is_hero=1, amount=2.0),
            ])
        self.conn.commit()

        result = self.repo.get_all_action_sequences('2026')
        hand_ids = {r['hand_id'] for r in result}
        self.assertIn('CASH1', hand_ids)
        self.assertNotIn('TOURNEY1', hand_ids)

    def test_includes_hero_net(self):
        """Returned rows include hero_net from hands table."""
        hand = _make_hand('H1', net=5.5)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'flop', 'Hero', 'bet', 0, 'CO', is_hero=1, amount=2.0),
        ])
        self.conn.commit()

        result = self.repo.get_all_action_sequences('2026')
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]['hero_net'], 5.5)

    def test_ordered_by_street_and_sequence(self):
        """Results ordered by hand_id, street order, sequence_order."""
        hand = _make_hand('H1')
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'flop', 'Hero', 'bet', 0, 'CO', is_hero=1, amount=2.0),
            _make_action('H1', 'preflop', 'Hero', 'raise', 0, 'CO', is_hero=1, amount=1.5),
            _make_action('H1', 'turn', 'Hero', 'check', 0, 'CO', is_hero=1),
        ])
        self.conn.commit()

        result = self.repo.get_all_action_sequences('2026')
        streets = [r['street'] for r in result]
        self.assertEqual(streets, ['preflop', 'flop', 'turn'])


# ── HTML Report Integration Tests ────────────────────────────────────

class TestPostflopReportIntegration(unittest.TestCase):
    """Test that Postflop Analysis section appears in HTML report."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def _insert_full_hand(self, hand_id, date='2026-01-15', net=1.5):
        """Insert a hand with full preflop+flop actions."""
        hand = _make_hand(hand_id, date=date, hero_position='CO', net=net)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action(hand_id, 'preflop', 'V1', 'post_sb', 0, 'SB', amount=0.25),
            _make_action(hand_id, 'preflop', 'V2', 'post_bb', 1, 'BB', amount=0.50),
            _make_action(hand_id, 'preflop', 'Hero', 'raise', 2, 'CO', is_hero=1, amount=1.50, is_voluntary=1),
            _make_action(hand_id, 'preflop', 'V2', 'call', 3, 'BB', amount=1.50),
            _make_action(hand_id, 'flop', 'V2', 'check', 0, 'BB'),
            _make_action(hand_id, 'flop', 'Hero', 'bet', 1, 'CO', is_hero=1, amount=2.0),
            _make_action(hand_id, 'flop', 'V2', 'fold', 2, 'BB'),
        ])
        self.conn.commit()

    def test_postflop_section_rendered(self):
        """Verify Postflop Analysis section appears when stats are available."""
        self._insert_full_hand('H1')

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

            self.assertIn('Postflop Analysis', html)
            self.assertIn('AF', html)
            self.assertIn('WTSD%', html)
            self.assertIn('W$SD%', html)
            self.assertIn('CBet%', html)
            self.assertIn('Fold to CBet', html)
            self.assertIn('Check-Raise%', html)
            self.assertIn('badge-', html)
        finally:
            os.unlink(output_path)

    def test_street_table_rendered(self):
        """Verify per-street breakdown table appears."""
        self._insert_full_hand('H1')

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

            self.assertIn('Stats por Street', html)
            self.assertIn('Flop', html)
        finally:
            os.unlink(output_path)

    def test_weekly_trends_rendered(self):
        """Verify weekly trends table appears."""
        self._insert_full_hand('H1', date='2026-01-15')
        self._insert_full_hand('H2', date='2026-01-22')

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

            self.assertIn('Tend\u00eancias Semanais', html)
            self.assertIn('2026-W03', html)
            self.assertIn('2026-W04', html)
        finally:
            os.unlink(output_path)

    def test_no_postflop_section_when_no_flop_seen(self):
        """No Postflop Analysis section when hero never sees flop."""
        hand = _make_hand('H1')
        self.repo.insert_hand(hand)
        # Only preflop actions
        self.repo.insert_actions_batch([
            _make_action('H1', 'preflop', 'V1', 'post_sb', 0, 'SB', amount=0.25),
            _make_action('H1', 'preflop', 'V2', 'post_bb', 1, 'BB', amount=0.50),
            _make_action('H1', 'preflop', 'V3', 'raise', 2, 'UTG', amount=1.50),
            _make_action('H1', 'preflop', 'Hero', 'fold', 3, 'CO', is_hero=1),
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

            self.assertNotIn('Postflop Analysis', html)
        finally:
            os.unlink(output_path)


if __name__ == '__main__':
    unittest.main()
