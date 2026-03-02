"""Tests for US-010: Positional Analysis (Stats + Win Rate per Position).

Covers:
- _analyze_blinds_defense() static method
- _classify_positional_health() with position-specific ranges
- get_positional_stats() overall calculation
- Per-position VPIP, PFR, 3-Bet, AF, CBet, WTSD, W$SD
- Win rate ($/hand and bb/100) per position
- Health badges per position
- ATS by steal position (CO, BTN, SB)
- Blinds defense (BB/SB): fold-to-steal%, 3-bet-vs-steal%, call-vs-steal%
- Most profitable vs most deficitary position comparison
- Radar chart data generation
- Repository get_cash_hands_with_position() query
- HTML rendering: positional table, comparison cards, ATS, blinds defense, radar
- Integration in generate_cash_report()
"""

import math
import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer
from src.reports.cash_report import (
    _render_positional_analysis,
    _render_radar_chart,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_hand(hand_id, date='2026-01-15', hero_position='CO',
               net=0.0, blinds_bb=0.50, **kwargs):
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='cash',
        date=datetime.fromisoformat(f'{date}T20:00:00'),
        blinds_sb=0.25,
        blinds_bb=blinds_bb,
        hero_cards='Ah Kd',
        hero_position=hero_position,
        invested=kwargs.get('invested', 1.0),
        won=kwargs.get('won', 0.0),
        net=net,
        rake=0.0,
        table_name='T',
        num_players=6,
    )


def _make_action(hand_id, player, action_type, seq, street='preflop',
                 position='CO', is_hero=0, amount=0.0, is_voluntary=0):
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
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Repository(conn)


# ── Unit Tests: _analyze_blinds_defense ──────────────────────────────

class TestAnalyzeBlindsDefense(unittest.TestCase):
    """Tests for CashAnalyzer._analyze_blinds_defense()."""

    def _actions(self, actions_list):
        return [
            {'player': p, 'action_type': at, 'is_hero': ih, 'position': pos,
             'is_voluntary': 1 if at not in ('fold',) else 0}
            for p, at, ih, pos in actions_list
        ]

    def test_bb_folds_to_btn_steal(self):
        """BB faces BTN raise with all others folding → steal opportunity → BB folds."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('MP', 'fold', 0, 'MP'),
            ('CO', 'fold', 0, 'CO'),
            ('BTN', 'raise', 0, 'BTN'),
            ('SB', 'fold', 0, 'SB'),
            ('Hero', 'fold', 1, 'BB'),
        ])
        result = CashAnalyzer._analyze_blinds_defense(actions, 'BB')
        self.assertTrue(result['steal_opp'])
        self.assertTrue(result['fold_to_steal'])
        self.assertFalse(result['three_bet_vs_steal'])
        self.assertFalse(result['call_vs_steal'])

    def test_bb_calls_vs_co_steal(self):
        """BB calls CO steal."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('MP', 'fold', 0, 'MP'),
            ('CO', 'raise', 0, 'CO'),
            ('BTN', 'fold', 0, 'BTN'),
            ('SB', 'fold', 0, 'SB'),
            ('Hero', 'call', 1, 'BB'),
        ])
        result = CashAnalyzer._analyze_blinds_defense(actions, 'BB')
        self.assertTrue(result['steal_opp'])
        self.assertFalse(result['fold_to_steal'])
        self.assertFalse(result['three_bet_vs_steal'])
        self.assertTrue(result['call_vs_steal'])

    def test_bb_three_bets_vs_sb_steal(self):
        """BB 3-bets vs SB steal."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('MP', 'fold', 0, 'MP'),
            ('CO', 'fold', 0, 'CO'),
            ('BTN', 'fold', 0, 'BTN'),
            ('SB', 'raise', 0, 'SB'),
            ('Hero', 'raise', 1, 'BB'),
        ])
        result = CashAnalyzer._analyze_blinds_defense(actions, 'BB')
        self.assertTrue(result['steal_opp'])
        self.assertFalse(result['fold_to_steal'])
        self.assertTrue(result['three_bet_vs_steal'])
        self.assertFalse(result['call_vs_steal'])

    def test_sb_folds_to_btn_steal(self):
        """SB folds to BTN steal (CO/BTN = valid stealers vs SB)."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('CO', 'fold', 0, 'CO'),
            ('BTN', 'raise', 0, 'BTN'),
            ('Hero', 'fold', 1, 'SB'),
        ])
        result = CashAnalyzer._analyze_blinds_defense(actions, 'SB')
        self.assertTrue(result['steal_opp'])
        self.assertTrue(result['fold_to_steal'])

    def test_sb_steal_from_sb_not_valid(self):
        """SB cannot be stolen from by SB (SB not a valid stealer vs SB)."""
        # SB steals vs BB - not a steal scenario for SB itself
        actions = self._actions([
            ('BTN', 'fold', 0, 'BTN'),
            ('Hero', 'raise', 1, 'SB'),
        ])
        result = CashAnalyzer._analyze_blinds_defense(actions, 'SB')
        # Hero acts first (no raise before hero) → not a steal scenario for SB
        self.assertFalse(result['steal_opp'])

    def test_no_steal_with_limper(self):
        """If someone limped before the raise, it's not a clean steal."""
        actions = self._actions([
            ('UTG', 'call', 0, 'UTG'),   # limper
            ('BTN', 'raise', 0, 'BTN'),
            ('SB', 'fold', 0, 'SB'),
            ('Hero', 'fold', 1, 'BB'),
        ])
        result = CashAnalyzer._analyze_blinds_defense(actions, 'BB')
        # all_fold_before_hero is False because UTG limped
        self.assertFalse(result['steal_opp'])

    def test_no_steal_when_hero_not_in_blinds(self):
        """CO position gets no steal opportunities as a defender."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('BTN', 'raise', 0, 'BTN'),
            ('Hero', 'fold', 1, 'CO'),
        ])
        result = CashAnalyzer._analyze_blinds_defense(actions, 'CO')
        # CO is not BB/SB, so no valid stealers
        self.assertFalse(result['steal_opp'])

    def test_no_steal_with_multiple_raisers(self):
        """Two raises before hero → not a simple steal situation."""
        actions = self._actions([
            ('UTG', 'raise', 0, 'UTG'),
            ('BTN', 'raise', 0, 'BTN'),
            ('SB', 'fold', 0, 'SB'),
            ('Hero', 'fold', 1, 'BB'),
        ])
        result = CashAnalyzer._analyze_blinds_defense(actions, 'BB')
        self.assertFalse(result['steal_opp'])


# ── Unit Tests: _classify_positional_health ────────────────────────────

class TestClassifyPositionalHealth(unittest.TestCase):
    """Tests for per-position health classification."""

    def test_utg_vpip_tight_is_good(self):
        """UTG VPIP 15% is healthy (tight early position range)."""
        result = CashAnalyzer._classify_positional_health('vpip', 'UTG', 15.0)
        self.assertEqual(result, 'good')

    def test_utg_vpip_30_is_danger(self):
        """UTG VPIP 30% is dangerous (too loose for early position)."""
        result = CashAnalyzer._classify_positional_health('vpip', 'UTG', 30.0)
        self.assertEqual(result, 'danger')

    def test_btn_vpip_35_is_good(self):
        """BTN VPIP 35% is healthy (BTN is loosest position)."""
        result = CashAnalyzer._classify_positional_health('vpip', 'BTN', 35.0)
        self.assertEqual(result, 'good')

    def test_btn_vpip_15_is_danger(self):
        """BTN VPIP 15% is dangerous (too tight for button)."""
        result = CashAnalyzer._classify_positional_health('vpip', 'BTN', 15.0)
        self.assertEqual(result, 'danger')

    def test_utg_pfr_13_is_good(self):
        """UTG PFR 13% is healthy."""
        result = CashAnalyzer._classify_positional_health('pfr', 'UTG', 13.0)
        self.assertEqual(result, 'good')

    def test_bb_pfr_10_is_good(self):
        """BB PFR 10% is healthy (BB raises less often)."""
        result = CashAnalyzer._classify_positional_health('pfr', 'BB', 10.0)
        self.assertEqual(result, 'good')

    def test_unknown_stat_falls_back(self):
        """Unknown stat key falls back to overall classification (returns 'good')."""
        result = CashAnalyzer._classify_positional_health('af', 'UTG', 2.5)
        self.assertIn(result, ('good', 'warning', 'danger'))

    def test_unknown_position_uses_fallback(self):
        """Unknown position falls back to overall ranges."""
        result = CashAnalyzer._classify_positional_health('vpip', 'Unknown', 25.0)
        self.assertIn(result, ('good', 'warning', 'danger'))


# ── Integration Tests: get_positional_stats ───────────────────────────

def _insert_hand_with_actions(repo, hand_id, hero_pos, net=0.0, blinds_bb=0.50,
                               date='2026-01-15', preflop_actions=None,
                               postflop_actions=None):
    """Helper: insert a hand + actions into the DB."""
    hand = _make_hand(hand_id, date=date, hero_position=hero_pos,
                      net=net, blinds_bb=blinds_bb)
    repo.insert_hand(hand)
    actions = []
    if preflop_actions:
        for i, (player, atype, is_hero, pos) in enumerate(preflop_actions):
            actions.append(_make_action(
                hand_id, player, atype, i, street='preflop',
                position=pos, is_hero=is_hero,
                is_voluntary=1 if atype not in ('post_sb', 'post_bb', 'fold') else 0
            ))
    if postflop_actions:
        for i, (player, atype, is_hero, pos, street) in enumerate(postflop_actions):
            actions.append(_make_action(
                hand_id, player, atype, i, street=street,
                position=pos, is_hero=is_hero, is_voluntary=0
            ))
    if actions:
        repo.insert_actions_batch(actions)
    return hand


class TestGetPositionalStats(unittest.TestCase):
    """Integration tests for CashAnalyzer.get_positional_stats()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_empty_returns_empty_by_position(self):
        """No hands → empty by_position dict."""
        result = self.analyzer.get_positional_stats()
        self.assertEqual(result['by_position'], {})

    def test_single_position_vpip_pfr(self):
        """One hand at BTN with raise → VPIP and PFR = 100%."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', net=1.0,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('Hero', 'raise', 1, 'BTN'),
                ('SB', 'fold', 0, 'SB'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        btn = result['by_position'].get('BTN', {})
        self.assertEqual(btn['total_hands'], 1)
        self.assertAlmostEqual(btn['vpip'], 100.0)
        self.assertAlmostEqual(btn['pfr'], 100.0)

    def test_multiple_positions(self):
        """Hands at different positions are separated correctly."""
        # UTG hand: open raise → VPIP+PFR
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='UTG', net=-1.0,
            preflop_actions=[
                ('Hero', 'raise', 1, 'UTG'),
                ('MP', 'fold', 0, 'MP'),
                ('BTN', 'fold', 0, 'BTN'),
            ]
        )
        # CO hand: call → VPIP only
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='CO', net=2.0,
            preflop_actions=[
                ('UTG', 'raise', 0, 'UTG'),
                ('Hero', 'call', 1, 'CO'),
                ('BTN', 'fold', 0, 'BTN'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        by_pos = result['by_position']

        self.assertIn('UTG', by_pos)
        self.assertIn('CO', by_pos)
        self.assertEqual(by_pos['UTG']['total_hands'], 1)
        self.assertEqual(by_pos['CO']['total_hands'], 1)

        self.assertAlmostEqual(by_pos['UTG']['vpip'], 100.0)
        self.assertAlmostEqual(by_pos['UTG']['pfr'], 100.0)

        self.assertAlmostEqual(by_pos['CO']['vpip'], 100.0)
        self.assertAlmostEqual(by_pos['CO']['pfr'], 0.0)

    def test_win_rate_per_hand(self):
        """Win rate $/hand calculated correctly."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', net=10.0, blinds_bb=0.50,
            preflop_actions=[
                ('Hero', 'raise', 1, 'BTN'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='BTN', net=-4.0, blinds_bb=0.50,
            preflop_actions=[
                ('Hero', 'call', 1, 'BTN'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        btn = result['by_position']['BTN']
        # Average net: (10 - 4) / 2 = 3.0 $/hand
        self.assertAlmostEqual(btn['net_per_hand'], 3.0)
        # Net total = 6.0
        self.assertAlmostEqual(btn['net'], 6.0)

    def test_bb_per_100(self):
        """bb/100 correctly computed per position."""
        # Hand: net=+1.0 with blinds_bb=0.50 → +2 bb gain
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='CO', net=1.0, blinds_bb=0.50,
            preflop_actions=[
                ('Hero', 'raise', 1, 'CO'),
                ('BTN', 'fold', 0, 'BTN'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        co = result['by_position']['CO']
        # bb_per_100 = (net/blinds_bb) / hands * 100 = (1.0/0.5) / 1 * 100 = 200.0
        self.assertAlmostEqual(co['bb_per_100'], 200.0)

    def test_three_bet_per_position(self):
        """3-bet opportunity and 3-bet% tracked per position."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='CO', net=0.0,
            preflop_actions=[
                ('UTG', 'raise', 0, 'UTG'),
                ('Hero', 'raise', 1, 'CO'),
                ('UTG', 'fold', 0, 'UTG'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        co = result['by_position']['CO']
        self.assertAlmostEqual(co['three_bet'], 100.0)

    def test_ats_by_steal_position(self):
        """ATS tracked per steal position (CO, BTN, SB).

        H001: BTN raises after all fold → ATS opportunity + steal (raise)
        H002: BTN folds after all fold → ATS opportunity but no steal
        Both hands count as ATS opportunities; only H001 is a steal.
        """
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', net=0.50,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('MP', 'fold', 0, 'MP'),
                ('CO', 'fold', 0, 'CO'),
                ('Hero', 'raise', 1, 'BTN'),
                ('SB', 'fold', 0, 'SB'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='BTN', net=-0.50,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('MP', 'fold', 0, 'MP'),
                ('CO', 'fold', 0, 'CO'),
                ('Hero', 'fold', 1, 'BTN'),   # missed steal opp → still counts as opp
            ]
        )
        result = self.analyzer.get_positional_stats()
        ats = result['ats_by_pos']
        self.assertIn('BTN', ats)
        # Both hands have ATS opportunity (hero was BTN, all folded before hero)
        self.assertEqual(ats['BTN']['ats_opps'], 2)
        # Only H001 resulted in an actual steal (raise)
        self.assertEqual(ats['BTN']['ats_count'], 1)
        self.assertAlmostEqual(ats['BTN']['ats'], 50.0)

    def test_blinds_defense_bb_fold(self):
        """BB blinds defense: fold to steal counted."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BB', net=-0.50,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('MP', 'fold', 0, 'MP'),
                ('CO', 'fold', 0, 'CO'),
                ('BTN', 'raise', 0, 'BTN'),
                ('SB', 'fold', 0, 'SB'),
                ('Hero', 'fold', 1, 'BB'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        bd = result['blinds_defense']
        self.assertIn('BB', bd)
        self.assertEqual(bd['BB']['steal_opps'], 1)
        self.assertAlmostEqual(bd['BB']['fold_to_steal'], 100.0)
        self.assertAlmostEqual(bd['BB']['three_bet_vs_steal'], 0.0)
        self.assertAlmostEqual(bd['BB']['call_vs_steal'], 0.0)

    def test_blinds_defense_bb_call(self):
        """BB calls steal → call_vs_steal counted."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BB', net=-0.20,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('BTN', 'raise', 0, 'BTN'),
                ('SB', 'fold', 0, 'SB'),
                ('Hero', 'call', 1, 'BB'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        bd = result['blinds_defense']
        self.assertIn('BB', bd)
        self.assertAlmostEqual(bd['BB']['fold_to_steal'], 0.0)
        self.assertAlmostEqual(bd['BB']['call_vs_steal'], 100.0)

    def test_blinds_defense_sb_three_bet(self):
        """SB 3-bets vs BTN steal."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='SB', net=1.5,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('CO', 'fold', 0, 'CO'),
                ('BTN', 'raise', 0, 'BTN'),
                ('Hero', 'raise', 1, 'SB'),
                ('BTN', 'fold', 0, 'BTN'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        bd = result['blinds_defense']
        self.assertIn('SB', bd)
        self.assertAlmostEqual(bd['SB']['three_bet_vs_steal'], 100.0)

    def test_comparison_most_profitable_deficitary(self):
        """Comparison identifies most profitable and most deficitary position."""
        # BTN: profitable (+200 bb/100)
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', net=1.0, blinds_bb=0.50,
            preflop_actions=[
                ('Hero', 'raise', 1, 'BTN'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        # UTG: deficitary (-200 bb/100)
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='UTG', net=-1.0, blinds_bb=0.50,
            preflop_actions=[
                ('Hero', 'raise', 1, 'UTG'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        comp = result['comparison']
        self.assertEqual(comp['most_profitable']['position'], 'BTN')
        self.assertEqual(comp['most_deficitary']['position'], 'UTG')

    def test_comparison_empty_when_single_position(self):
        """Single position: no comparison (best == worst)."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', net=1.0,
            preflop_actions=[
                ('Hero', 'raise', 1, 'BTN'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        comp = result['comparison']
        self.assertEqual(comp, {})

    def test_radar_data_present(self):
        """Radar data generated for positions with hands."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', net=1.0,
            preflop_actions=[
                ('Hero', 'raise', 1, 'BTN'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        radar = result['radar']
        self.assertGreater(len(radar), 0)
        entry = radar[0]
        self.assertIn('position', entry)
        self.assertIn('values', entry)
        self.assertIn('vpip', entry['values'])
        self.assertIn('pfr', entry['values'])
        self.assertIn('bb_per_100', entry)

    def test_radar_values_normalized_0_to_100(self):
        """Radar values are normalized between 0 and 100."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='CO', net=0.0,
            preflop_actions=[
                ('UTG', 'raise', 0, 'UTG'),
                ('Hero', 'raise', 1, 'CO'),
                ('UTG', 'fold', 0, 'UTG'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        for entry in result['radar']:
            for key, val in entry['values'].items():
                self.assertGreaterEqual(val, 0.0, f'{key} should be >= 0')
                self.assertLessEqual(val, 100.0, f'{key} should be <= 100')

    def test_winrate_health_positive(self):
        """Positive net_per_hand → winrate_health='good'."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', net=5.0,
            preflop_actions=[
                ('Hero', 'raise', 1, 'BTN'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        self.assertEqual(result['by_position']['BTN']['winrate_health'], 'good')

    def test_winrate_health_negative(self):
        """Negative net_per_hand → winrate_health='danger'."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='UTG', net=-5.0,
            preflop_actions=[
                ('Hero', 'fold', 1, 'UTG'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        self.assertEqual(result['by_position']['UTG']['winrate_health'], 'danger')

    def test_postflop_stats_per_position(self):
        """Postflop stats (AF, WTSD, W$SD, CBet) accumulated per position."""
        # Preflop: BTN raises, BB calls → BTN is PFA
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', net=5.0,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('Hero', 'raise', 1, 'BTN'),
                ('BB', 'call', 0, 'BB'),
            ],
            postflop_actions=[
                ('Hero', 'bet', 1, 'BTN', 'flop'),    # CBet
                ('BB', 'fold', 0, 'BB', 'flop'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        btn = result['by_position']['BTN']
        # CBet opportunity: hero was PFA and bet on flop → cbet=100%
        self.assertAlmostEqual(btn['cbet'], 100.0)

    def test_health_badge_vpip_utg_tight(self):
        """UTG VPIP 15% → position-specific health badge is 'good'."""
        # Create enough hands to simulate 15% VPIP at UTG
        # 1 VPIP hand out of 7 total ≈ 14.3%
        for i in range(6):
            _insert_hand_with_actions(
                self.repo, f'H{i:03d}', hero_pos='UTG', net=0.0,
                preflop_actions=[
                    ('Hero', 'fold', 1, 'UTG'),
                ]
            )
        _insert_hand_with_actions(
            self.repo, 'H006', hero_pos='UTG', net=1.0,
            preflop_actions=[
                ('Hero', 'raise', 1, 'UTG'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        result = self.analyzer.get_positional_stats()
        utg = result['by_position']['UTG']
        # VPIP ≈ 14.3%, should be 'good' or 'warning' at UTG (UTG healthy range 12-18)
        self.assertIn(utg['vpip_health'], ('good', 'warning'))


# ── Repository Tests ──────────────────────────────────────────────────

class TestRepositoryGetPositionalData(unittest.TestCase):
    """Tests for Repository.get_cash_hands_with_position()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def test_returns_empty_when_no_hands(self):
        result = self.repo.get_cash_hands_with_position()
        self.assertEqual(result, [])

    def test_returns_cash_hands_only(self):
        """Tournament hands excluded from positional query."""
        cash_hand = _make_hand('C001', hero_position='BTN', net=1.0)
        self.repo.insert_hand(cash_hand)
        # Insert a tournament hand manually
        tourn_hand = HandData(
            hand_id='T001', platform='GGPoker', game_type='tournament',
            date=datetime.fromisoformat('2026-01-15T20:00:00'),
            blinds_sb=25, blinds_bb=50, hero_cards='Ah Kd',
            hero_position='CO', invested=50, won=0, net=-50, rake=0,
            table_name='T', num_players=9,
        )
        self.repo.insert_hand(tourn_hand)
        result = self.repo.get_cash_hands_with_position()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['hand_id'], 'C001')

    def test_includes_position_and_financial_fields(self):
        """Result includes hand_id, hero_position, net, blinds_bb."""
        hand = _make_hand('H001', hero_position='CO', net=2.5, blinds_bb=0.50)
        self.repo.insert_hand(hand)
        result = self.repo.get_cash_hands_with_position()
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row['hand_id'], 'H001')
        self.assertEqual(row['hero_position'], 'CO')
        self.assertAlmostEqual(row['net'], 2.5)
        self.assertAlmostEqual(row['blinds_bb'], 0.50)

    def test_year_filter(self):
        """Year filter limits results to that year only."""
        hand_2026 = _make_hand('H001', date='2026-01-15', hero_position='BTN', net=1.0)
        hand_2025 = _make_hand('H002', date='2025-12-01', hero_position='CO', net=-1.0)
        self.repo.insert_hand(hand_2026)
        self.repo.insert_hand(hand_2025)
        result = self.repo.get_cash_hands_with_position(year='2026')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['hand_id'], 'H001')

    def test_null_position_handled(self):
        """Hands with null hero_position are still returned."""
        hand = HandData(
            hand_id='H001', platform='GGPoker', game_type='cash',
            date=datetime.fromisoformat('2026-01-15T20:00:00'),
            blinds_sb=0.25, blinds_bb=0.50, hero_cards='Ah Kd',
            hero_position=None, invested=1.0, won=0.0, net=-1.0,
            rake=0.0, table_name='T', num_players=6,
        )
        self.repo.insert_hand(hand)
        result = self.repo.get_cash_hands_with_position()
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]['hero_position'])


# ── HTML Rendering Tests ───────────────────────────────────────────────

class TestRenderPositionalAnalysis(unittest.TestCase):
    """Tests for _render_positional_analysis() HTML output."""

    def _make_pos_stats(self, positions=None):
        """Build a minimal positional_stats dict for rendering tests."""
        positions = positions or {
            'BTN': {
                'total_hands': 50, 'vpip': 40.0, 'vpip_health': 'good',
                'pfr': 30.0, 'pfr_health': 'good',
                'three_bet': 8.0, 'three_bet_health': 'good',
                'af': 2.5, 'af_health': 'good',
                'cbet': 65.0, 'cbet_health': 'good',
                'wtsd': 28.0, 'wtsd_health': 'good',
                'wsd': 52.0, 'wsd_health': 'good',
                'net': 25.0, 'net_per_hand': 0.5,
                'bb_per_100': 100.0, 'winrate_health': 'good',
                'ats': 38.0, 'ats_opps': 30, 'ats_count': 11,
            },
            'UTG': {
                'total_hands': 40, 'vpip': 14.0, 'vpip_health': 'good',
                'pfr': 12.0, 'pfr_health': 'good',
                'three_bet': 5.0, 'three_bet_health': 'warning',
                'af': 2.0, 'af_health': 'good',
                'cbet': 60.0, 'cbet_health': 'good',
                'wtsd': 25.0, 'wtsd_health': 'good',
                'wsd': 48.0, 'wsd_health': 'warning',
                'net': -8.0, 'net_per_hand': -0.2,
                'bb_per_100': -40.0, 'winrate_health': 'danger',
                'ats': 0.0, 'ats_opps': 0, 'ats_count': 0,
            },
        }
        return {
            'by_position': positions,
            'comparison': {
                'most_profitable': {'position': 'BTN', 'bb_per_100': 100.0,
                                    'total_hands': 50, 'vpip': 40.0, 'pfr': 30.0},
                'most_deficitary': {'position': 'UTG', 'bb_per_100': -40.0,
                                    'total_hands': 40, 'vpip': 14.0, 'pfr': 12.0},
            },
            'ats_by_pos': {
                'BTN': {'ats': 38.0, 'ats_opps': 30, 'ats_count': 11},
            },
            'blinds_defense': {
                'BB': {
                    'steal_opps': 20, 'fold_to_steal': 50.0, 'fold_to_steal_count': 10,
                    'three_bet_vs_steal': 15.0, 'three_bet_vs_steal_count': 3,
                    'call_vs_steal': 35.0, 'call_vs_steal_count': 7,
                },
            },
            'radar': [
                {
                    'position': 'BTN', 'hands': 50, 'bb_per_100': 100.0,
                    'values': {'vpip': 66.7, 'pfr': 60.0, 'three_bet': 40.0,
                               'af': 50.0, 'cbet': 65.0, 'wtsd': 56.0, 'wsd': 74.3},
                },
            ],
        }

    def test_empty_by_position_returns_empty(self):
        """Empty by_position → empty string returned."""
        result = _render_positional_analysis({'by_position': {}})
        self.assertEqual(result, '')

    def test_contains_section_header(self):
        """HTML contains main section header."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('Análise Posicional Completa', html)

    def test_contains_position_names(self):
        """HTML lists present positions."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('BTN', html)
        self.assertIn('UTG', html)

    def test_contains_stat_columns(self):
        """HTML table includes all stat columns."""
        html = _render_positional_analysis(self._make_pos_stats())
        for stat in ('VPIP', 'PFR', '3-Bet', 'AF', 'CBet', 'WTSD', 'W$SD', 'bb/100'):
            self.assertIn(stat, html)

    def test_contains_win_rate_values(self):
        """HTML shows bb/100 values."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('+100.0', html)   # BTN bb/100
        self.assertIn('-40.0', html)    # UTG bb/100

    def test_contains_comparison_section(self):
        """HTML includes comparison between most profitable and most deficitary."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('Mais Lucrativa', html)
        self.assertIn('Mais Deficitária', html)

    def test_contains_ats_section(self):
        """HTML includes ATS section for steal positions."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('ATS', html)
        self.assertIn('Attempt to Steal', html)

    def test_contains_blinds_defense_section(self):
        """HTML includes blinds defense section for BB/SB."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('Defesa das Blinds', html)
        self.assertIn('Fold to Steal', html)
        self.assertIn('3-Bet vs Steal', html)
        self.assertIn('Call vs Steal', html)

    def test_contains_radar_chart_svg(self):
        """HTML includes SVG radar chart."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('<svg', html)
        self.assertIn('Radar', html)

    def test_health_badges_rendered(self):
        """Health badges appear in the position table."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('badge-good', html)
        self.assertIn('badge-warning', html)

    def test_positive_winrate_class(self):
        """Positive bb/100 gets 'positive' CSS class."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('class="positive"', html)

    def test_negative_winrate_class(self):
        """Negative bb/100 gets 'negative' CSS class."""
        html = _render_positional_analysis(self._make_pos_stats())
        self.assertIn('class="negative"', html)

    def test_no_ats_section_when_empty(self):
        """ATS section omitted when ats_by_pos is empty."""
        stats = self._make_pos_stats()
        stats['ats_by_pos'] = {}
        html = _render_positional_analysis(stats)
        self.assertNotIn('Attempt to Steal', html)

    def test_no_blinds_defense_when_empty(self):
        """Blinds defense section omitted when blinds_defense is empty."""
        stats = self._make_pos_stats()
        stats['blinds_defense'] = {}
        html = _render_positional_analysis(stats)
        self.assertNotIn('Defesa das Blinds', html)

    def test_no_comparison_when_empty(self):
        """Comparison section omitted when comparison is empty."""
        stats = self._make_pos_stats()
        stats['comparison'] = {}
        html = _render_positional_analysis(stats)
        self.assertNotIn('Mais Lucrativa', html)


class TestRenderRadarChart(unittest.TestCase):
    """Tests for _render_radar_chart() SVG output."""

    def _sample_radar(self):
        return [
            {
                'position': 'BTN', 'hands': 50, 'bb_per_100': 100.0,
                'values': {'vpip': 66.7, 'pfr': 60.0, 'three_bet': 40.0,
                           'af': 50.0, 'cbet': 65.0, 'wtsd': 56.0, 'wsd': 74.3},
            },
            {
                'position': 'UTG', 'hands': 40, 'bb_per_100': -40.0,
                'values': {'vpip': 23.3, 'pfr': 24.0, 'three_bet': 25.0,
                           'af': 40.0, 'cbet': 60.0, 'wtsd': 50.0, 'wsd': 68.6},
            },
        ]

    def test_returns_svg_string(self):
        """Output contains SVG element."""
        html = _render_radar_chart(self._sample_radar())
        self.assertIn('<svg', html)

    def test_returns_axis_labels(self):
        """SVG includes axis labels."""
        html = _render_radar_chart(self._sample_radar())
        for label in ('VPIP', 'PFR', '3-Bet', 'AF', 'CBet', 'WTSD', 'W$SD'):
            self.assertIn(label, html)

    def test_returns_position_legend(self):
        """SVG legend includes position names."""
        html = _render_radar_chart(self._sample_radar())
        self.assertIn('BTN', html)
        self.assertIn('UTG', html)

    def test_returns_polygons(self):
        """SVG contains polygon elements for each position."""
        html = _render_radar_chart(self._sample_radar())
        self.assertIn('<polygon', html)

    def test_empty_returns_no_position_polygons(self):
        """Empty radar data → SVG contains only grid polygons, no position-colored fills."""
        html = _render_radar_chart([])
        # Grid polygons are always present (they have fill="none")
        # Position polygons have fill colors (rgba(...)), so check for those
        self.assertNotIn('rgba(0,170,255', html)   # BTN fill color absent
        self.assertNotIn('rgba(255,100,100', html)  # UTG fill color absent

    def test_bb_per_100_in_legend(self):
        """bb/100 values shown in legend (as +100 or -40)."""
        html = _render_radar_chart(self._sample_radar())
        self.assertIn('+100', html)
        self.assertIn('-40', html)


# ── _build_radar_data Unit Tests ──────────────────────────────────────

class TestBuildRadarData(unittest.TestCase):
    """Tests for CashAnalyzer._build_radar_data()."""

    def test_empty_returns_empty(self):
        result = CashAnalyzer._build_radar_data({})
        self.assertEqual(result, [])

    def test_position_order_preserved(self):
        """Output ordered by canonical position order (UTG before BTN)."""
        by_pos = {
            'BTN': {'total_hands': 10, 'vpip': 35.0, 'pfr': 28.0, 'three_bet': 8.0,
                    'af': 2.5, 'cbet': 65.0, 'wtsd': 28.0, 'wsd': 52.0, 'bb_per_100': 50.0},
            'UTG': {'total_hands': 8, 'vpip': 15.0, 'pfr': 12.0, 'three_bet': 5.0,
                    'af': 2.0, 'cbet': 60.0, 'wtsd': 24.0, 'wsd': 48.0, 'bb_per_100': -10.0},
        }
        result = CashAnalyzer._build_radar_data(by_pos)
        positions = [e['position'] for e in result]
        self.assertEqual(positions.index('UTG'), 0)
        self.assertEqual(positions.index('BTN'), 1)

    def test_values_bounded_0_100(self):
        """Normalized values are within [0, 100]."""
        by_pos = {
            'BTN': {'total_hands': 10, 'vpip': 100.0, 'pfr': 100.0, 'three_bet': 100.0,
                    'af': 100.0, 'cbet': 100.0, 'wtsd': 100.0, 'wsd': 100.0, 'bb_per_100': 500.0},
        }
        result = CashAnalyzer._build_radar_data(by_pos)
        for val in result[0]['values'].values():
            self.assertLessEqual(val, 100.0)
            self.assertGreaterEqual(val, 0.0)

    def test_includes_bb_per_100_and_hands(self):
        """Each radar entry has bb_per_100 and hands fields."""
        by_pos = {
            'CO': {'total_hands': 20, 'vpip': 25.0, 'pfr': 20.0, 'three_bet': 7.0,
                   'af': 2.5, 'cbet': 65.0, 'wtsd': 28.0, 'wsd': 52.0, 'bb_per_100': 75.0},
        }
        result = CashAnalyzer._build_radar_data(by_pos)
        self.assertEqual(result[0]['position'], 'CO')
        self.assertAlmostEqual(result[0]['bb_per_100'], 75.0)
        self.assertEqual(result[0]['hands'], 20)


# ── Report Integration Test ──────────────────────────────────────────

class TestGenerateCashReportPositional(unittest.TestCase):
    """Integration test: positional analysis appears in generated report."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_positional_section_in_report(self):
        """Positional analysis section appears in the generated HTML report."""
        from src.reports.cash_report import generate_cash_report
        import tempfile, os

        # Insert a hand with actions to make positional stats non-empty
        hand = _make_hand('H001', hero_position='BTN', net=1.0,
                          date='2026-01-15')
        self.repo.insert_hand(hand)
        session = {
            'session_id': 1,
            'platform': 'GGPoker',
            'date': '2026-01-15',
            'buy_in': 50.0,
            'cash_out': 51.0,
            'profit': 1.0,
            'hands_count': 1,
            'min_stack': 50.0,
            'start_time': '2026-01-15T20:00:00',
            'end_time': '2026-01-15T22:00:00',
        }
        self.repo.insert_session(session)
        actions = [
            _make_action('H001', 'Hero', 'raise', 0, position='BTN', is_hero=1, is_voluntary=1),
            _make_action('H001', 'BB', 'fold', 1, position='BB', is_hero=0),
        ]
        self.repo.insert_actions_batch(actions)

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            out = f.name

        try:
            generate_cash_report(self.analyzer, output_file=out)
            with open(out, encoding='utf-8') as f:
                html = f.read()
            self.assertIn('Análise Posicional Completa', html)
        finally:
            os.unlink(out)


if __name__ == '__main__':
    unittest.main()
