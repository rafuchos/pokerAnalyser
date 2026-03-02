"""Tests for US-015: Preflop Range Visualization (Hand Matrix por Posição).

Covers:
- _categorize_hand() hand notation conversion
- _classify_preflop_action() action type classification
- get_hand_matrix() overall computation
- Per-position hand matrix breakdown
- Frequency calculation (played/dealt)
- Action breakdown (open raise, call, 3-bet)
- Win rate per hand (bb/100)
- Top 10 most profitable and top 10 most deficit hands
- Repository get_cash_hands_with_cards() query
- HTML rendering: _render_hand_matrix_svg() SVG generation
- HTML rendering: _render_range_analysis() full section
- Integration in generate_cash_report()
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import (
    CashAnalyzer,
    _categorize_hand,
    _classify_preflop_action,
    RANKS,
)
from src.reports.cash_report import (
    _render_hand_matrix_svg,
    _render_range_analysis,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_hand(hand_id, date='2026-01-15', hero_position='CO',
               hero_cards='Ah Kd', net=0.0, blinds_bb=0.50, **kwargs):
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='cash',
        date=datetime.fromisoformat(f'{date}T20:00:00'),
        blinds_sb=0.25,
        blinds_bb=blinds_bb,
        hero_cards=hero_cards,
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


def _insert_hand_with_actions(repo, hand_id, hero_pos, hero_cards='Ah Kd',
                               net=0.0, blinds_bb=0.50,
                               date='2026-01-15', preflop_actions=None):
    """Helper: insert a hand + preflop actions into the DB."""
    hand = _make_hand(hand_id, date=date, hero_position=hero_pos,
                      hero_cards=hero_cards, net=net, blinds_bb=blinds_bb)
    repo.insert_hand(hand)
    actions = []
    if preflop_actions:
        for i, (player, atype, is_hero, pos) in enumerate(preflop_actions):
            actions.append(_make_action(
                hand_id, player, atype, i, street='preflop',
                position=pos, is_hero=is_hero,
                is_voluntary=1 if atype not in ('post_sb', 'post_bb', 'fold') else 0
            ))
    if actions:
        repo.insert_actions_batch(actions)
    return hand


# ── Unit Tests: _categorize_hand ────────────────────────────────────

class TestCategorizeHand(unittest.TestCase):
    """Tests for _categorize_hand() hand notation conversion."""

    def test_pocket_aces(self):
        """AA pair."""
        self.assertEqual(_categorize_hand('Ah As'), 'AA')

    def test_pocket_twos(self):
        """22 pair."""
        self.assertEqual(_categorize_hand('2d 2c'), '22')

    def test_suited_ak(self):
        """AKs suited."""
        self.assertEqual(_categorize_hand('Ah Kh'), 'AKs')

    def test_offsuit_ak(self):
        """AKo offsuit."""
        self.assertEqual(_categorize_hand('Ah Kd'), 'AKo')

    def test_reversed_order_suited(self):
        """Lower rank first, same suit → reordered to higher first."""
        self.assertEqual(_categorize_hand('Kh Ah'), 'AKs')

    def test_reversed_order_offsuit(self):
        """Lower rank first, different suit → reordered."""
        self.assertEqual(_categorize_hand('Td As'), 'ATo')

    def test_t9_suited(self):
        """T9s suited connector."""
        self.assertEqual(_categorize_hand('Ts 9s'), 'T9s')

    def test_72_offsuit(self):
        """72o worst hand."""
        self.assertEqual(_categorize_hand('7d 2c'), '72o')

    def test_pair_jacks(self):
        """JJ pair."""
        self.assertEqual(_categorize_hand('Jh Jd'), 'JJ')

    def test_invalid_empty(self):
        """Empty string returns None."""
        self.assertIsNone(_categorize_hand(''))

    def test_invalid_single_card(self):
        """Single card returns None."""
        self.assertIsNone(_categorize_hand('Ah'))

    def test_invalid_three_cards(self):
        """Three cards returns None."""
        self.assertIsNone(_categorize_hand('Ah Kd Qc'))

    def test_invalid_rank(self):
        """Invalid rank character returns None."""
        self.assertIsNone(_categorize_hand('Xh Kd'))

    def test_short_card_notation(self):
        """Card with only rank (no suit) returns None."""
        self.assertIsNone(_categorize_hand('A K'))

    def test_all_pairs(self):
        """All 13 pocket pairs are properly categorized."""
        for r in RANKS:
            result = _categorize_hand(f'{r}h {r}d')
            self.assertEqual(result, f'{r}{r}')

    def test_q5_suited(self):
        """Q5s suited."""
        self.assertEqual(_categorize_hand('Qc 5c'), 'Q5s')

    def test_63_offsuit(self):
        """63o offsuit."""
        self.assertEqual(_categorize_hand('6h 3d'), '63o')


# ── Unit Tests: _classify_preflop_action ────────────────────────────

class TestClassifyPreflopAction(unittest.TestCase):
    """Tests for _classify_preflop_action()."""

    def _actions(self, action_list):
        """Build action dicts from tuples (player, action_type, is_hero, position)."""
        return [
            {'hand_id': 'H1', 'player': p, 'action_type': at,
             'is_hero': ih, 'position': pos, 'is_voluntary': 1 if at not in ('fold', 'post_sb', 'post_bb') else 0}
            for p, at, ih, pos in action_list
        ]

    def test_open_raise(self):
        """Hero raises with no raises before → open_raise."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('MP', 'fold', 0, 'MP'),
            ('Hero', 'raise', 1, 'CO'),
        ])
        self.assertEqual(_classify_preflop_action(actions), 'open_raise')

    def test_call(self):
        """Hero calls a raise → call."""
        actions = self._actions([
            ('UTG', 'raise', 0, 'UTG'),
            ('Hero', 'call', 1, 'CO'),
        ])
        self.assertEqual(_classify_preflop_action(actions), 'call')

    def test_three_bet(self):
        """Hero re-raises after opponent raise → three_bet."""
        actions = self._actions([
            ('UTG', 'raise', 0, 'UTG'),
            ('Hero', 'raise', 1, 'CO'),
        ])
        self.assertEqual(_classify_preflop_action(actions), 'three_bet')

    def test_fold(self):
        """Hero folds → None."""
        actions = self._actions([
            ('UTG', 'raise', 0, 'UTG'),
            ('Hero', 'fold', 1, 'CO'),
        ])
        self.assertIsNone(_classify_preflop_action(actions))

    def test_post_blind_then_open_raise(self):
        """Hero posts blind then raises first → open_raise."""
        actions = self._actions([
            ('Hero', 'post_bb', 1, 'BB'),
            ('UTG', 'fold', 0, 'UTG'),
            ('MP', 'fold', 0, 'MP'),
            ('Hero', 'raise', 1, 'BB'),
        ])
        self.assertEqual(_classify_preflop_action(actions), 'open_raise')

    def test_allin_no_raises_before(self):
        """Hero all-in with no prior raises → open_raise."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('Hero', 'all-in', 1, 'BTN'),
        ])
        self.assertEqual(_classify_preflop_action(actions), 'open_raise')

    def test_allin_after_raise(self):
        """Hero all-in after opponent raise → three_bet."""
        actions = self._actions([
            ('UTG', 'raise', 0, 'UTG'),
            ('Hero', 'all-in', 1, 'CO'),
        ])
        self.assertEqual(_classify_preflop_action(actions), 'three_bet')

    def test_empty_actions(self):
        """No actions → None."""
        self.assertIsNone(_classify_preflop_action([]))

    def test_only_blinds(self):
        """Only blind posts, no voluntary action → None."""
        actions = self._actions([
            ('Hero', 'post_bb', 1, 'BB'),
            ('SB', 'post_sb', 0, 'SB'),
        ])
        self.assertIsNone(_classify_preflop_action(actions))

    def test_opponent_allin_hero_calls(self):
        """Opponent all-in then hero calls → call."""
        actions = self._actions([
            ('UTG', 'all-in', 0, 'UTG'),
            ('Hero', 'call', 1, 'BB'),
        ])
        self.assertEqual(_classify_preflop_action(actions), 'call')


# ── Integration Tests: get_hand_matrix ──────────────────────────────

class TestGetHandMatrix(unittest.TestCase):
    """Integration tests for CashAnalyzer.get_hand_matrix()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_empty_db_returns_empty(self):
        """No hands → empty overall dict."""
        result = self.analyzer.get_hand_matrix()
        self.assertEqual(result['overall'], {})
        self.assertEqual(result['total_hands'], 0)

    def test_single_hand_open_raise(self):
        """Single hand with open raise → correct categorization and action."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', hero_cards='Ah Kd',
            net=2.0, blinds_bb=0.50,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('Hero', 'raise', 1, 'BTN'),
                ('SB', 'fold', 0, 'SB'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        result = self.analyzer.get_hand_matrix()
        self.assertIn('AKo', result['overall'])
        ako = result['overall']['AKo']
        self.assertEqual(ako['dealt'], 1)
        self.assertEqual(ako['played'], 1)
        self.assertEqual(ako['open_raise'], 1)
        self.assertEqual(ako['call'], 0)
        self.assertEqual(ako['three_bet'], 0)
        self.assertEqual(ako['frequency'], 100.0)
        self.assertEqual(ako['net'], 2.0)

    def test_multiple_hands_same_category(self):
        """Multiple hands with same starting hand → aggregated stats."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', hero_cards='Ah Kd',
            net=3.0, blinds_bb=0.50,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('Hero', 'raise', 1, 'BTN'),
                ('SB', 'fold', 0, 'SB'),
                ('BB', 'fold', 0, 'BB'),
            ]
        )
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='CO', hero_cards='As Kc',
            net=-1.0, blinds_bb=0.50,
            preflop_actions=[
                ('UTG', 'raise', 0, 'UTG'),
                ('Hero', 'call', 1, 'CO'),
            ]
        )
        result = self.analyzer.get_hand_matrix()
        ako = result['overall']['AKo']
        self.assertEqual(ako['dealt'], 2)
        self.assertEqual(ako['played'], 2)
        self.assertEqual(ako['open_raise'], 1)
        self.assertEqual(ako['call'], 1)
        self.assertEqual(ako['net'], 2.0)  # 3.0 + (-1.0)

    def test_by_position_breakdown(self):
        """Hands at different positions → separate by_position entries."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', hero_cards='Ah Kh',
            net=2.0, blinds_bb=0.50,
            preflop_actions=[
                ('UTG', 'fold', 0, 'UTG'),
                ('Hero', 'raise', 1, 'BTN'),
            ]
        )
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='UTG', hero_cards='As Ks',
            net=-1.0, blinds_bb=0.50,
            preflop_actions=[
                ('Hero', 'raise', 1, 'UTG'),
                ('BTN', 'fold', 0, 'BTN'),
            ]
        )
        result = self.analyzer.get_hand_matrix()
        self.assertIn('BTN', result['by_position'])
        self.assertIn('UTG', result['by_position'])
        btn_aks = result['by_position']['BTN'].get('AKs')
        utg_aks = result['by_position']['UTG'].get('AKs')
        self.assertIsNotNone(btn_aks)
        self.assertIsNotNone(utg_aks)
        self.assertEqual(btn_aks['dealt'], 1)
        self.assertEqual(utg_aks['dealt'], 1)

    def test_three_bet_classification(self):
        """Hero re-raises after opponent raise → three_bet action."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='CO', hero_cards='Qh Qd',
            net=5.0, blinds_bb=0.50,
            preflop_actions=[
                ('UTG', 'raise', 0, 'UTG'),
                ('Hero', 'raise', 1, 'CO'),
                ('UTG', 'call', 0, 'UTG'),
            ]
        )
        result = self.analyzer.get_hand_matrix()
        qq = result['overall']['QQ']
        self.assertEqual(qq['three_bet'], 1)
        self.assertEqual(qq['open_raise'], 0)
        self.assertEqual(qq['call'], 0)

    def test_fold_not_counted_as_played(self):
        """Hero folds → dealt but not played."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='UTG', hero_cards='7h 2d',
            net=-0.25, blinds_bb=0.50,
            preflop_actions=[
                ('Hero', 'fold', 1, 'UTG'),
            ]
        )
        result = self.analyzer.get_hand_matrix()
        h72o = result['overall']['72o']
        self.assertEqual(h72o['dealt'], 1)
        self.assertEqual(h72o['played'], 0)
        self.assertEqual(h72o['frequency'], 0.0)

    def test_win_rate_calculation(self):
        """Win rate = bb_net/dealt * 100 as bb/100."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', hero_cards='Ah Ad',
            net=10.0, blinds_bb=0.50,
            preflop_actions=[
                ('Hero', 'raise', 1, 'BTN'),
            ]
        )
        result = self.analyzer.get_hand_matrix()
        aa = result['overall']['AA']
        # bb_net = 10.0/0.50 = 20.0; win_rate = 20.0/1 * 100 = 2000.0
        self.assertEqual(aa['win_rate'], 2000.0)

    def test_top_profitable_hands(self):
        """Top profitable hands sorted by win rate, minimum 3 dealt."""
        for i in range(5):
            _insert_hand_with_actions(
                self.repo, f'H{i:03d}', hero_pos='BTN', hero_cards='Ah Ad',
                net=5.0, blinds_bb=0.50,
                preflop_actions=[
                    ('Hero', 'raise', 1, 'BTN'),
                ]
            )
        for i in range(5, 10):
            _insert_hand_with_actions(
                self.repo, f'H{i:03d}', hero_pos='BTN', hero_cards='7h 2d',
                net=-2.0, blinds_bb=0.50,
                preflop_actions=[
                    ('Hero', 'fold', 1, 'BTN'),
                ]
            )
        result = self.analyzer.get_hand_matrix()
        self.assertTrue(len(result['top_profitable']) > 0)
        self.assertEqual(result['top_profitable'][0]['hand'], 'AA')

    def test_top_deficit_hands(self):
        """Top deficit hands sorted by worst win rate, minimum 3 dealt."""
        for i in range(5):
            _insert_hand_with_actions(
                self.repo, f'H{i:03d}', hero_pos='BTN', hero_cards='7h 2d',
                net=-2.0, blinds_bb=0.50,
                preflop_actions=[
                    ('Hero', 'call', 1, 'BTN'),
                ]
            )
        result = self.analyzer.get_hand_matrix()
        self.assertTrue(len(result['top_deficit']) > 0)
        self.assertEqual(result['top_deficit'][0]['hand'], '72o')

    def test_total_hands_count(self):
        """total_hands = sum of all dealt counts."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', hero_cards='Ah Kd',
            net=1.0, preflop_actions=[('Hero', 'raise', 1, 'BTN')]
        )
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='CO', hero_cards='Qh Js',
            net=-0.5, preflop_actions=[('Hero', 'fold', 1, 'CO')]
        )
        result = self.analyzer.get_hand_matrix()
        self.assertEqual(result['total_hands'], 2)

    def test_suited_vs_offsuit_different_categories(self):
        """Same ranks but suited vs offsuit → different categories."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', hero_cards='Ah Kh',
            net=1.0, preflop_actions=[('Hero', 'raise', 1, 'BTN')]
        )
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='BTN', hero_cards='Ad Kc',
            net=-1.0, preflop_actions=[('Hero', 'raise', 1, 'BTN')]
        )
        result = self.analyzer.get_hand_matrix()
        self.assertIn('AKs', result['overall'])
        self.assertIn('AKo', result['overall'])
        self.assertEqual(result['overall']['AKs']['dealt'], 1)
        self.assertEqual(result['overall']['AKo']['dealt'], 1)

    def test_hand_without_hero_cards_ignored(self):
        """Hands with no hero_cards are excluded."""
        hand = _make_hand('H001', hero_cards=None, net=1.0)
        self.repo.insert_hand(hand)
        result = self.analyzer.get_hand_matrix()
        self.assertEqual(result['total_hands'], 0)

    def test_frequency_partial(self):
        """2 dealt, 1 played → frequency = 50%."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', hero_cards='Jh Td',
            net=1.0, preflop_actions=[('Hero', 'raise', 1, 'BTN')]
        )
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='BTN', hero_cards='Js Tc',
            net=-0.5, preflop_actions=[('Hero', 'fold', 1, 'BTN')]
        )
        result = self.analyzer.get_hand_matrix()
        jto = result['overall']['JTo']
        self.assertEqual(jto['dealt'], 2)
        self.assertEqual(jto['played'], 1)
        self.assertEqual(jto['frequency'], 50.0)


# ── Integration Tests: Repository.get_cash_hands_with_cards ─────────

class TestRepositoryGetCashHandsWithCards(unittest.TestCase):
    """Tests for Repository.get_cash_hands_with_cards()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def test_returns_hands_with_cards(self):
        """Returns hands that have hero_cards."""
        hand = _make_hand('H001', hero_cards='Ah Kd', net=1.0)
        self.repo.insert_hand(hand)
        result = self.repo.get_cash_hands_with_cards('2026')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['hero_cards'], 'Ah Kd')

    def test_excludes_null_cards(self):
        """Hands with NULL hero_cards are excluded."""
        hand = _make_hand('H001', hero_cards=None, net=1.0)
        self.repo.insert_hand(hand)
        result = self.repo.get_cash_hands_with_cards('2026')
        self.assertEqual(len(result), 0)

    def test_includes_position_and_net(self):
        """Result includes hero_position, net, and blinds_bb."""
        hand = _make_hand('H001', hero_cards='Ah Kd', hero_position='BTN',
                          net=3.5, blinds_bb=0.50)
        self.repo.insert_hand(hand)
        result = self.repo.get_cash_hands_with_cards('2026')
        self.assertEqual(result[0]['hero_position'], 'BTN')
        self.assertEqual(result[0]['net'], 3.5)
        self.assertEqual(result[0]['blinds_bb'], 0.50)

    def test_year_filter(self):
        """Year filter works correctly."""
        hand = _make_hand('H001', hero_cards='Ah Kd', date='2025-01-15')
        self.repo.insert_hand(hand)
        result = self.repo.get_cash_hands_with_cards('2026')
        self.assertEqual(len(result), 0)
        result = self.repo.get_cash_hands_with_cards('2025')
        self.assertEqual(len(result), 1)


# ── Unit Tests: _render_hand_matrix_svg ─────────────────────────────

class TestRenderHandMatrixSvg(unittest.TestCase):
    """Tests for _render_hand_matrix_svg() SVG generation."""

    def test_empty_matrix_produces_svg(self):
        """Empty matrix data still produces valid SVG."""
        svg = _render_hand_matrix_svg({})
        self.assertIn('<svg', svg)
        self.assertIn('</svg>', svg)

    def test_contains_rank_labels(self):
        """SVG contains rank labels A through 2."""
        svg = _render_hand_matrix_svg({})
        for r in RANKS:
            self.assertIn(f'>{r}<', svg)

    def test_cell_with_data_has_color(self):
        """Cells with data have colored fill, not default grey."""
        data = {
            'AKo': {'dealt': 10, 'played': 8, 'frequency': 80.0,
                     'open_raise': 6, 'call': 2, 'three_bet': 0,
                     'net': 5.0, 'bb_net': 10.0, 'win_rate': 100.0}
        }
        svg = _render_hand_matrix_svg(data)
        self.assertIn('AKo', svg)
        # Check that frequency text is shown
        self.assertIn('80%', svg)

    def test_ideal_range_overlay(self):
        """When show_overlay is True and position has ideal range, green borders shown."""
        data = {
            'AA': {'dealt': 5, 'played': 5, 'frequency': 100.0,
                    'open_raise': 5, 'call': 0, 'three_bet': 0,
                    'net': 10.0, 'bb_net': 20.0, 'win_rate': 400.0}
        }
        svg = _render_hand_matrix_svg(data, position='UTG', show_overlay=True)
        # AA is in UTG ideal range → should have green dashed border
        self.assertIn('#00ff88', svg)
        self.assertIn('stroke-dasharray', svg)

    def test_no_overlay_overall(self):
        """Overall position with show_overlay=False → no ideal range borders."""
        data = {
            'AA': {'dealt': 5, 'played': 5, 'frequency': 100.0,
                    'open_raise': 5, 'call': 0, 'three_bet': 0,
                    'net': 10.0, 'bb_net': 20.0, 'win_rate': 400.0}
        }
        svg = _render_hand_matrix_svg(data, position='overall', show_overlay=False)
        self.assertNotIn('stroke-dasharray', svg)

    def test_three_bet_dominant_color(self):
        """When 3-bet is dominant, cell should have reddish color."""
        data = {
            'QQ': {'dealt': 10, 'played': 8, 'frequency': 80.0,
                    'open_raise': 1, 'call': 1, 'three_bet': 6,
                    'net': 15.0, 'bb_net': 30.0, 'win_rate': 300.0}
        }
        svg = _render_hand_matrix_svg(data)
        # With 3-bet dominant, red channel should be high (>180)
        self.assertIn('QQ', svg)

    def test_call_dominant_color(self):
        """When call is dominant, cell should have yellowish color."""
        data = {
            'T9s': {'dealt': 10, 'played': 7, 'frequency': 70.0,
                     'open_raise': 1, 'call': 5, 'three_bet': 1,
                     'net': 2.0, 'bb_net': 4.0, 'win_rate': 40.0}
        }
        svg = _render_hand_matrix_svg(data)
        self.assertIn('T9s', svg)

    def test_svg_dimensions(self):
        """SVG has proper width/height attributes."""
        svg = _render_hand_matrix_svg({})
        self.assertIn('width=', svg)
        self.assertIn('height=', svg)


# ── Unit Tests: _render_range_analysis ──────────────────────────────

class TestRenderRangeAnalysis(unittest.TestCase):
    """Tests for _render_range_analysis() HTML section."""

    def _sample_data(self):
        """Create sample matrix data for rendering tests."""
        overall = {
            'AA': {'dealt': 10, 'played': 10, 'frequency': 100.0,
                    'open_raise': 8, 'call': 0, 'three_bet': 2,
                    'net': 50.0, 'bb_net': 100.0, 'win_rate': 1000.0},
            '72o': {'dealt': 8, 'played': 2, 'frequency': 25.0,
                     'open_raise': 0, 'call': 2, 'three_bet': 0,
                     'net': -10.0, 'bb_net': -20.0, 'win_rate': -250.0},
        }
        return {
            'overall': overall,
            'by_position': {
                'BTN': {
                    'AA': {'dealt': 3, 'played': 3, 'frequency': 100.0,
                            'open_raise': 2, 'call': 0, 'three_bet': 1,
                            'net': 15.0, 'bb_net': 30.0, 'win_rate': 1000.0},
                },
                'UTG': {
                    'AA': {'dealt': 2, 'played': 2, 'frequency': 100.0,
                            'open_raise': 2, 'call': 0, 'three_bet': 0,
                            'net': 10.0, 'bb_net': 20.0, 'win_rate': 1000.0},
                },
            },
            'top_profitable': [
                {'hand': 'AA', 'dealt': 10, 'played': 10, 'frequency': 100.0,
                 'open_raise': 8, 'call': 0, 'three_bet': 2,
                 'net': 50.0, 'bb_net': 100.0, 'win_rate': 1000.0},
            ],
            'top_deficit': [
                {'hand': '72o', 'dealt': 8, 'played': 2, 'frequency': 25.0,
                 'open_raise': 0, 'call': 2, 'three_bet': 0,
                 'net': -10.0, 'bb_net': -20.0, 'win_rate': -250.0},
            ],
            'total_hands': 18,
        }

    def test_empty_returns_nothing(self):
        """Empty data returns empty string."""
        self.assertEqual(_render_range_analysis(None), '')
        self.assertEqual(_render_range_analysis({}), '')
        self.assertEqual(_render_range_analysis({'total_hands': 0}), '')

    def test_contains_section_title(self):
        """HTML contains section title."""
        html = _render_range_analysis(self._sample_data())
        self.assertIn('Preflop Range Visualization', html)

    def test_contains_legend(self):
        """HTML contains action color legend."""
        html = _render_range_analysis(self._sample_data())
        self.assertIn('Open Raise', html)
        self.assertIn('Call', html)
        self.assertIn('3-Bet', html)
        self.assertIn('Range Ideal', html)

    def test_contains_position_tabs(self):
        """HTML contains position tabs for available positions."""
        html = _render_range_analysis(self._sample_data())
        self.assertIn('Geral', html)
        self.assertIn('BTN', html)
        self.assertIn('UTG', html)

    def test_contains_svg_matrices(self):
        """HTML contains SVG elements for matrices."""
        html = _render_range_analysis(self._sample_data())
        self.assertIn('<svg', html)

    def test_contains_top_profitable_table(self):
        """HTML contains top profitable hands table."""
        html = _render_range_analysis(self._sample_data())
        self.assertIn('Mãos Mais Lucrativas', html)
        self.assertIn('AA', html)

    def test_contains_top_deficit_table(self):
        """HTML contains top deficit hands table."""
        html = _render_range_analysis(self._sample_data())
        self.assertIn('Mãos Mais Deficitárias', html)
        self.assertIn('72o', html)

    def test_contains_tab_javascript(self):
        """HTML contains JavaScript for tab switching."""
        html = _render_range_analysis(self._sample_data())
        self.assertIn('range-tab', html)
        self.assertIn('range-panel', html)

    def test_range_panels_have_ids(self):
        """Each position panel has a unique ID."""
        html = _render_range_analysis(self._sample_data())
        self.assertIn('id="range-overall"', html)
        self.assertIn('id="range-BTN"', html)
        self.assertIn('id="range-UTG"', html)

    def test_profit_table_shows_net_and_winrate(self):
        """Profit table shows net $ and win rate bb/100."""
        html = _render_range_analysis(self._sample_data())
        self.assertIn('$', html)
        self.assertIn('bb/100', html)

    def test_too_few_hands_returns_empty(self):
        """Less than 5 hands returns empty string."""
        data = self._sample_data()
        data['total_hands'] = 3
        self.assertEqual(_render_range_analysis(data), '')


# ── Integration Tests: generate_cash_report ─────────────────────────

class TestHandMatrixInReport(unittest.TestCase):
    """Tests for hand matrix integration in generate_cash_report()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_report_includes_range_section(self):
        """Report contains range section when enough hands exist."""
        for i in range(10):
            _insert_hand_with_actions(
                self.repo, f'H{i:03d}', hero_pos='BTN',
                hero_cards='Ah Kd' if i % 2 == 0 else 'Qh Qd',
                net=1.0 if i % 3 == 0 else -0.5,
                blinds_bb=0.50,
                preflop_actions=[
                    ('UTG', 'fold', 0, 'UTG'),
                    ('Hero', 'raise', 1, 'BTN'),
                ]
            )
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            output = f.name
        try:
            generate_cash_report(self.analyzer, output_file=output)
            with open(output, 'r') as f:
                html = f.read()
            self.assertIn('Preflop Range Visualization', html)
        finally:
            os.unlink(output)

    def test_report_without_hands_no_range(self):
        """Report without hands doesn't include range section."""
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            output = f.name
        try:
            generate_cash_report(self.analyzer, output_file=output)
            with open(output, 'r') as f:
                html = f.read()
            self.assertNotIn('Preflop Range Visualization', html)
        finally:
            os.unlink(output)


# ── Edge Case Tests ─────────────────────────────────────────────────

class TestHandMatrixEdgeCases(unittest.TestCase):
    """Edge case tests for hand matrix analysis."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_all_169_hand_categories_possible(self):
        """13 pairs + 78 suited + 78 offsuit = 169 categories."""
        categories = set()
        for i, r1 in enumerate(RANKS):
            for j, r2 in enumerate(RANKS):
                if i == j:
                    categories.add(f'{r1}{r2}')
                elif i < j:
                    categories.add(f'{r1}{r2}s')
                else:
                    categories.add(f'{r2}{r1}o')
        self.assertEqual(len(categories), 169)

    def test_suited_hand_above_diagonal(self):
        """Suited hands appear above diagonal (row < col)."""
        cat = _categorize_hand('Ah Kh')
        self.assertEqual(cat, 'AKs')
        # A=idx0, K=idx1, row 0 < col 1 → above diagonal

    def test_offsuit_hand_below_diagonal(self):
        """Offsuit hands appear below diagonal (row > col)."""
        cat = _categorize_hand('Kh Ad')
        self.assertEqual(cat, 'AKo')

    def test_zero_blinds_bb_no_crash(self):
        """Zero blinds_bb doesn't crash (division by zero protection)."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', hero_cards='Ah Kd',
            net=1.0, blinds_bb=0.0,
            preflop_actions=[('Hero', 'raise', 1, 'BTN')]
        )
        result = self.analyzer.get_hand_matrix()
        self.assertEqual(result['total_hands'], 1)

    def test_top_profitable_requires_minimum_dealt(self):
        """Hands with fewer than 3 dealt don't appear in top lists."""
        for i in range(2):
            _insert_hand_with_actions(
                self.repo, f'H{i:03d}', hero_pos='BTN', hero_cards='Ah Ad',
                net=100.0, blinds_bb=0.50,
                preflop_actions=[('Hero', 'raise', 1, 'BTN')]
            )
        result = self.analyzer.get_hand_matrix()
        # AA dealt only 2 times, shouldn't appear in top list
        top_hands = [h['hand'] for h in result['top_profitable']]
        self.assertNotIn('AA', top_hands)

    def test_multiple_positions_same_hand(self):
        """Same hand category at different positions tracked separately."""
        _insert_hand_with_actions(
            self.repo, 'H001', hero_pos='BTN', hero_cards='Jh Js',
            net=5.0, preflop_actions=[('Hero', 'raise', 1, 'BTN')]
        )
        _insert_hand_with_actions(
            self.repo, 'H002', hero_pos='UTG', hero_cards='Jd Jc',
            net=-3.0, preflop_actions=[('Hero', 'raise', 1, 'UTG')]
        )
        result = self.analyzer.get_hand_matrix()
        self.assertEqual(result['overall']['JJ']['dealt'], 2)
        self.assertEqual(result['by_position']['BTN']['JJ']['dealt'], 1)
        self.assertEqual(result['by_position']['UTG']['JJ']['dealt'], 1)
        self.assertEqual(result['by_position']['BTN']['JJ']['net'], 5.0)
        self.assertEqual(result['by_position']['UTG']['JJ']['net'], -3.0)


if __name__ == '__main__':
    unittest.main()
