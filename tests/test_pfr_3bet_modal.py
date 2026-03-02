"""Tests for US-019: PFR/3Bet Positional Matrix com Drill-Down (Posição vs Posição).

Covers:
- _analyze_preflop_hand() returns raiser_position and three_bettor_position
- _format_three_bet_matrix() formats raw counters into percentages
- get_positional_stats() returns three_bet_matrix in result
- _render_pfr_3bet_modal() renders modal structure, tabs, and panels
- PFR panel shows PFR% by position with health badges
- 3-Bet matrix panel shows hero_pos × raiser_pos cells
- Empty/partial data renders gracefully
- _render_player_stats() shows clickable 3-Bet card when matrix data available
- JS functions (openPfrModal, closePfrModal, switchPfrTab) present in report
- ESC key listener closes both modals
- Full generate_cash_report() includes PFR/3-Bet modal
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer
from src.reports.cash_report import (
    _render_pfr_3bet_modal,
    _render_player_stats,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_hand(hand_id, date='2026-01-15', hero_position='BTN',
               net=0.0, blinds_bb=0.50, hero_stack=50.0, **kwargs):
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
        hero_stack=hero_stack,
    )


def _make_action(hand_id, player, action_type, seq, street='preflop',
                 position='BTN', is_hero=0, amount=0.0, is_voluntary=0):
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


def _make_positional_stats(positions=None, three_bet_matrix=None):
    """Return a minimal positional_stats dict with optional matrix (US-019 shape)."""
    if positions is None:
        positions = {
            'BTN': {
                'total_hands': 80, 'vpip': 30.0, 'vpip_health': 'good',
                'pfr': 22.0, 'pfr_health': 'good',
                'three_bet': 7.0, 'three_bet_health': 'good',
                'af': 2.3, 'cbet': 60.0, 'wtsd': 28.0, 'wsd': 52.0,
                'bb_per_100': 9.5, 'net_per_hand': 0.12,
            },
            'CO': {
                'total_hands': 60, 'vpip': 25.0, 'vpip_health': 'good',
                'pfr': 18.0, 'pfr_health': 'good',
                'three_bet': 5.0, 'three_bet_health': 'good',
                'af': 2.1, 'cbet': 55.0, 'wtsd': 26.0, 'wsd': 50.0,
                'bb_per_100': 5.0, 'net_per_hand': 0.08,
            },
        }
    if three_bet_matrix is None:
        three_bet_matrix = {
            'BTN': {
                'UTG': {'three_bet_opps': 20, 'three_bet_count': 3, 'three_bet_pct': 15.0},
                'CO': {'three_bet_opps': 15, 'three_bet_count': 2, 'three_bet_pct': 13.3},
            },
            'CO': {
                'UTG': {'three_bet_opps': 12, 'three_bet_count': 1, 'three_bet_pct': 8.3},
            },
        }
    return {
        'by_position': positions,
        'blinds_defense': {},
        'ats_by_pos': {},
        'comparison': {},
        'radar': [],
        'three_bet_matrix': three_bet_matrix,
    }


def _make_preflop_overall():
    return {
        'total_hands': 200,
        'vpip': 26.0, 'vpip_health': 'good', 'vpip_hands': 52,
        'pfr': 18.0, 'pfr_health': 'good', 'pfr_hands': 36,
        'three_bet': 6.0, 'three_bet_health': 'good',
        'three_bet_hands': 8, 'three_bet_opps': 120,
        'fold_to_3bet': 55.0, 'fold_to_3bet_health': 'good',
        'fold_to_3bet_hands': 30, 'fold_to_3bet_opps': 55,
        'ats': 40.0, 'ats_health': 'good', 'ats_hands': 20, 'ats_opps': 50,
    }


# ── Unit: _analyze_preflop_hand() raiser_position tracking ───────────────────

class TestAnalyzePreflopHandRaiserPosition(unittest.TestCase):
    """Tests for raiser_position and three_bettor_position in _analyze_preflop_hand()."""

    def _actions(self, actions_list):
        return [
            {
                'player': p,
                'action_type': at,
                'is_hero': ih,
                'position': pos,
                'is_voluntary': 1 if at in ('raise', 'bet', 'call') else 0,
            }
            for p, at, ih, pos in actions_list
        ]

    def test_raiser_position_none_when_hero_opens(self):
        """When hero is the first to raise, raiser_position should be None."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('MP', 'fold', 0, 'MP'),
            ('Hero', 'raise', 1, 'CO'),
        ])
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertIsNone(result['raiser_position'])

    def test_raiser_position_set_when_utg_opens(self):
        """When UTG raises and hero faces it, raiser_position = 'UTG'."""
        actions = self._actions([
            ('UTG', 'raise', 0, 'UTG'),
            ('MP', 'fold', 0, 'MP'),
            ('CO', 'fold', 0, 'CO'),
            ('Hero', 'raise', 1, 'BTN'),  # hero 3-bets
        ])
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertEqual(result['raiser_position'], 'UTG')

    def test_raiser_position_reflects_last_raiser(self):
        """When MP re-raises after UTG, raiser_position should be MP (last raiser before hero)."""
        actions = self._actions([
            ('UTG', 'raise', 0, 'UTG'),
            ('MP', 'raise', 0, 'MP'),
            ('Hero', 'raise', 1, 'BTN'),
        ])
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertEqual(result['raiser_position'], 'MP')

    def test_raiser_position_co_steal(self):
        """CO raises, hero faces it from BTN."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('MP', 'fold', 0, 'MP'),
            ('CO', 'raise', 0, 'CO'),
            ('Hero', 'raise', 1, 'BTN'),
        ])
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertEqual(result['raiser_position'], 'CO')

    def test_three_bet_opp_flagged_when_raiser_present(self):
        """three_bet_opp should be True when raiser_position is set."""
        actions = self._actions([
            ('UTG', 'raise', 0, 'UTG'),
            ('Hero', 'call', 1, 'BTN'),
        ])
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['three_bet_opp'])
        self.assertFalse(result['three_bet'])  # hero called, not raised
        self.assertEqual(result['raiser_position'], 'UTG')

    def test_three_bettor_position_set_when_hero_open_raised_and_got_reraised(self):
        """three_bettor_position is set when opponent re-raises hero's open."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('Hero', 'raise', 1, 'CO'),
            ('BTN', 'raise', 0, 'BTN'),
            ('Hero', 'fold', 1, 'CO'),
        ])
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertTrue(result['fold_3bet_opp'])
        self.assertTrue(result['fold_3bet'])
        self.assertEqual(result['three_bettor_position'], 'BTN')

    def test_three_bettor_position_none_when_no_reraise(self):
        """three_bettor_position is None when hero opens and no one re-raises."""
        actions = self._actions([
            ('UTG', 'fold', 0, 'UTG'),
            ('Hero', 'raise', 1, 'CO'),
            ('BTN', 'fold', 0, 'BTN'),
        ])
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertIsNone(result['three_bettor_position'])

    def test_backwards_compat_old_keys_still_present(self):
        """Existing return keys are not broken by new additions."""
        actions = self._actions([
            ('UTG', 'raise', 0, 'UTG'),
            ('Hero', 'raise', 1, 'BTN'),
        ])
        result = CashAnalyzer._analyze_preflop_hand(actions)
        for key in ('vpip', 'pfr', 'three_bet_opp', 'three_bet',
                    'fold_3bet_opp', 'fold_3bet', 'ats_opp', 'ats'):
            self.assertIn(key, result)

    def test_new_keys_always_present(self):
        """raiser_position and three_bettor_position are always in result."""
        actions = self._actions([
            ('Hero', 'raise', 1, 'BTN'),
        ])
        result = CashAnalyzer._analyze_preflop_hand(actions)
        self.assertIn('raiser_position', result)
        self.assertIn('three_bettor_position', result)


# ── Unit: _format_three_bet_matrix() ─────────────────────────────────────────

class TestFormatThreeBetMatrix(unittest.TestCase):
    """Tests for CashAnalyzer._format_three_bet_matrix()."""

    def test_basic_formatting(self):
        raw = {
            'BTN': {
                'UTG': {'three_bet_opps': 20, 'three_bet': 4},
            }
        }
        result = CashAnalyzer._format_three_bet_matrix(raw)
        self.assertIn('BTN', result)
        self.assertIn('UTG', result['BTN'])
        cell = result['BTN']['UTG']
        self.assertAlmostEqual(cell['three_bet_pct'], 20.0, places=1)
        self.assertEqual(cell['three_bet_opps'], 20)
        self.assertEqual(cell['three_bet_count'], 4)

    def test_zero_opps_cell_excluded(self):
        raw = {
            'BTN': {
                'UTG': {'three_bet_opps': 0, 'three_bet': 0},
            }
        }
        result = CashAnalyzer._format_three_bet_matrix(raw)
        self.assertNotIn('BTN', result)

    def test_empty_raw_returns_empty(self):
        result = CashAnalyzer._format_three_bet_matrix({})
        self.assertEqual(result, {})

    def test_position_order_preserved(self):
        raw = {
            'SB': {'UTG': {'three_bet_opps': 5, 'three_bet': 1}},
            'UTG': {'BTN': {'three_bet_opps': 10, 'three_bet': 2}},
        }
        result = CashAnalyzer._format_three_bet_matrix(raw)
        keys = list(result.keys())
        # UTG should come before SB (position order)
        self.assertLess(keys.index('UTG'), keys.index('SB'))

    def test_unknown_position_skipped(self):
        raw = {
            'UNKNOWN_POS': {'UTG': {'three_bet_opps': 5, 'three_bet': 1}},
            'BTN': {'UTG': {'three_bet_opps': 10, 'three_bet': 2}},
        }
        result = CashAnalyzer._format_three_bet_matrix(raw)
        self.assertNotIn('UNKNOWN_POS', result)
        self.assertIn('BTN', result)

    def test_pct_zero_when_no_three_bets(self):
        raw = {
            'BTN': {
                'UTG': {'three_bet_opps': 10, 'three_bet': 0},
            }
        }
        result = CashAnalyzer._format_three_bet_matrix(raw)
        self.assertAlmostEqual(result['BTN']['UTG']['three_bet_pct'], 0.0)

    def test_pct_hundred_when_always_three_bet(self):
        raw = {
            'BTN': {
                'UTG': {'three_bet_opps': 5, 'three_bet': 5},
            }
        }
        result = CashAnalyzer._format_three_bet_matrix(raw)
        self.assertAlmostEqual(result['BTN']['UTG']['three_bet_pct'], 100.0)


# ── Integration: get_positional_stats() returns three_bet_matrix ─────────────

class TestGetPositionalStatsMatrix(unittest.TestCase):
    """Tests for three_bet_matrix in get_positional_stats()."""

    def _insert_hand_with_actions(self, repo, hand, actions):
        repo.insert_hand(hand)
        repo.insert_actions_batch(actions)

    def _setup_three_bet_scenario(self):
        """Create a DB with hero 3-betting from BTN vs UTG opener."""
        conn, repo = _setup_db()
        # Hand 1: UTG raises, hero (BTN) 3-bets
        h1 = _make_hand('H001', hero_position='BTN', net=5.0)
        a1 = [
            _make_action('H001', 'UTG', 'raise', 1, position='UTG', is_hero=0,
                         amount=1.5, is_voluntary=1),
            _make_action('H001', 'MP', 'fold', 2, position='MP', is_hero=0),
            _make_action('H001', 'CO', 'fold', 3, position='CO', is_hero=0),
            _make_action('H001', 'Hero', 'raise', 4, position='BTN', is_hero=1,
                         amount=4.5, is_voluntary=1),
        ]
        self._insert_hand_with_actions(repo, h1, a1)
        # Hand 2: UTG raises, hero (BTN) calls (no 3-bet)
        h2 = _make_hand('H002', hero_position='BTN', net=-1.0)
        a2 = [
            _make_action('H002', 'UTG', 'raise', 1, position='UTG', is_hero=0,
                         amount=1.5, is_voluntary=1),
            _make_action('H002', 'Hero', 'call', 2, position='BTN', is_hero=1,
                         amount=1.5, is_voluntary=1),
        ]
        self._insert_hand_with_actions(repo, h2, a2)
        conn.commit()
        return repo

    def test_three_bet_matrix_key_present(self):
        repo = self._setup_three_bet_scenario()
        analyzer = CashAnalyzer(repo)
        result = analyzer.get_positional_stats()
        self.assertIn('three_bet_matrix', result)

    def test_three_bet_matrix_btn_vs_utg_entry(self):
        repo = self._setup_three_bet_scenario()
        analyzer = CashAnalyzer(repo)
        result = analyzer.get_positional_stats()
        matrix = result['three_bet_matrix']
        self.assertIn('BTN', matrix)
        self.assertIn('UTG', matrix['BTN'])

    def test_three_bet_matrix_pct_correct(self):
        """1 out of 2 opportunities = 50%."""
        repo = self._setup_three_bet_scenario()
        analyzer = CashAnalyzer(repo)
        result = analyzer.get_positional_stats()
        cell = result['three_bet_matrix']['BTN']['UTG']
        self.assertEqual(cell['three_bet_opps'], 2)
        self.assertEqual(cell['three_bet_count'], 1)
        self.assertAlmostEqual(cell['three_bet_pct'], 50.0, places=1)

    def test_empty_db_returns_empty_matrix(self):
        conn, repo = _setup_db()
        analyzer = CashAnalyzer(repo)
        result = analyzer.get_positional_stats()
        self.assertEqual(result.get('three_bet_matrix', {}), {})

    def test_no_three_bet_opps_matrix_empty(self):
        """When hero only opens (no one raised before), matrix is empty."""
        conn, repo = _setup_db()
        h = _make_hand('H001', hero_position='BTN', net=1.0)
        a = [
            _make_action('H001', 'UTG', 'fold', 1, position='UTG', is_hero=0),
            _make_action('H001', 'Hero', 'raise', 2, position='BTN', is_hero=1,
                         amount=1.5, is_voluntary=1),
        ]
        repo.insert_hand(h)
        repo.insert_actions_batch(a)
        conn.commit()
        analyzer = CashAnalyzer(repo)
        result = analyzer.get_positional_stats()
        self.assertEqual(result.get('three_bet_matrix', {}), {})


# ── Unit: _render_pfr_3bet_modal() ───────────────────────────────────────────

class TestRenderPfr3BetModal(unittest.TestCase):

    def setUp(self):
        self.pos_stats = _make_positional_stats()

    def _render(self, pos_stats=None):
        p = pos_stats if pos_stats is not None else self.pos_stats
        return _render_pfr_3bet_modal(p)

    # ── basic structure ──────────────────────────────────────────────────────

    def test_renders_non_empty(self):
        html = self._render()
        self.assertGreater(len(html), 100)

    def test_contains_modal_overlay(self):
        html = self._render()
        self.assertIn('pfr-modal-overlay', html)

    def test_contains_modal_container(self):
        html = self._render()
        self.assertIn('pfr-modal', html)

    def test_contains_close_button(self):
        html = self._render()
        self.assertIn('vpip-modal-close', html)  # reuses same CSS class
        self.assertIn('closePfrModal()', html)

    def test_contains_title(self):
        html = self._render()
        self.assertIn('PFR', html)
        self.assertIn('3-Bet', html)

    # ── tab buttons ──────────────────────────────────────────────────────────

    def test_contains_pfr_tab_button(self):
        html = self._render()
        self.assertIn('pfr-tab-btn-pfr', html)

    def test_contains_matrix_tab_button(self):
        html = self._render()
        self.assertIn('pfr-tab-btn-matrix', html)

    def test_pfr_tab_label(self):
        html = self._render()
        self.assertIn('PFR por Posi', html)

    def test_matrix_tab_label(self):
        html = self._render()
        self.assertIn('3-Bet vs Posi', html)

    # ── tab panels ───────────────────────────────────────────────────────────

    def test_contains_pfr_panel(self):
        html = self._render()
        self.assertIn('pfr-panel-pfr', html)

    def test_contains_matrix_panel(self):
        html = self._render()
        self.assertIn('pfr-panel-matrix', html)

    def test_pfr_panel_is_active_by_default(self):
        html = self._render()
        self.assertIn('id="pfr-panel-pfr" class="vpip-panel active"', html)

    def test_matrix_panel_is_inactive_by_default(self):
        html = self._render()
        self.assertIn('id="pfr-panel-matrix" class="vpip-panel"', html)

    # ── PFR panel data ───────────────────────────────────────────────────────

    def test_pfr_panel_shows_btn(self):
        html = self._render()
        self.assertIn('BTN', html)

    def test_pfr_panel_shows_co(self):
        html = self._render()
        self.assertIn('CO', html)

    def test_pfr_panel_shows_pfr_value_btn(self):
        html = self._render()
        self.assertIn('22.0%', html)  # BTN PFR

    def test_pfr_panel_shows_pfr_value_co(self):
        html = self._render()
        self.assertIn('18.0%', html)  # CO PFR

    def test_pfr_panel_shows_health_badge(self):
        html = self._render()
        self.assertIn('badge-good', html)

    def test_pfr_panel_shows_vpip_column(self):
        html = self._render()
        self.assertIn('VPIP', html)

    # ── 3-Bet matrix panel data ──────────────────────────────────────────────

    def test_matrix_panel_shows_hero_positions(self):
        html = self._render()
        self.assertIn('BTN', html)

    def test_matrix_panel_shows_opp_positions_in_header(self):
        html = self._render()
        self.assertIn('UTG', html)

    def test_matrix_panel_shows_pct_values(self):
        html = self._render()
        self.assertIn('15.0%', html)  # BTN vs UTG: 15.0%

    def test_matrix_panel_shows_opportunity_count(self):
        html = self._render()
        self.assertIn('20m', html)  # 20 opportunities

    def test_matrix_cell_has_hot_class_for_high_pct(self):
        html = self._render()
        self.assertIn('matrix-cell-hot', html)  # 15% → hot

    def test_matrix_cell_has_warm_class_for_lower_pct(self):
        """8.3% < 10% threshold → warm class."""
        html = self._render()
        self.assertIn('matrix-cell-warm', html)

    def test_matrix_empty_cells_shown_as_dash(self):
        html = self._render()
        self.assertIn('matrix-cell-empty', html)

    def test_matrix_uses_pfr_matrix_table_class(self):
        html = self._render()
        self.assertIn('pfr-matrix-table', html)

    # ── empty / partial data ─────────────────────────────────────────────────

    def test_empty_positional_stats_renders_no_data(self):
        html = _render_pfr_3bet_modal({})
        self.assertIn('pfr-modal-overlay', html)
        self.assertIn('Sem dados por posi', html)

    def test_empty_matrix_renders_no_matrix_data(self):
        ps = _make_positional_stats(three_bet_matrix={})
        html = _render_pfr_3bet_modal(ps)
        self.assertIn('pfr-modal-overlay', html)
        self.assertIn('Sem dados de matriz', html)

    def test_both_empty_still_renders(self):
        html = _render_pfr_3bet_modal({})
        self.assertIn('pfr-modal-overlay', html)

    # ── JS references ────────────────────────────────────────────────────────

    def test_modal_references_close_pfr_modal(self):
        html = self._render()
        self.assertIn('closePfrModal()', html)

    def test_modal_references_switch_pfr_tab(self):
        html = self._render()
        self.assertIn('switchPfrTab', html)

    def test_open_pfr_modal_not_in_modal_html(self):
        """openPfrModal is on the 3-Bet card, not inside the modal HTML itself."""
        html = self._render()
        self.assertNotIn('openPfrModal', html)


# ── _render_player_stats() 3-Bet clickable card ──────────────────────────────

class TestRenderPlayerStatsThreeBetClickable(unittest.TestCase):

    def setUp(self):
        self.overall = _make_preflop_overall()
        self.by_position = {}
        self.pos_stats = _make_positional_stats()

    def test_three_bet_card_clickable_when_data_supplied(self):
        html = _render_player_stats(
            self.overall, self.by_position, self.pos_stats,
        )
        self.assertIn('three-bet-clickable', html)
        self.assertIn('openPfrModal()', html)

    def test_three_bet_card_shows_hint_when_clickable(self):
        html = _render_player_stats(
            self.overall, self.by_position, self.pos_stats,
        )
        self.assertIn('three-bet-hint', html)
        self.assertIn('clique para matriz', html)

    def test_three_bet_card_not_clickable_without_data(self):
        html = _render_player_stats(self.overall, self.by_position)
        self.assertNotIn('three-bet-clickable', html)
        self.assertNotIn('openPfrModal()', html)

    def test_three_bet_card_not_clickable_with_empty_positional(self):
        html = _render_player_stats(self.overall, self.by_position, {})
        self.assertNotIn('three-bet-clickable', html)

    def test_three_bet_value_shown(self):
        html = _render_player_stats(
            self.overall, self.by_position, self.pos_stats,
        )
        self.assertIn('6.0%', html)  # overall three_bet

    def test_vpip_card_still_clickable_independently(self):
        """VPIP and 3-Bet can be independently clickable."""
        from src.db.schema import init_db
        stack_data = {
            'by_tier': {'deep': {'label': '50+ BB', 'total_hands': 10,
                                  'vpip': 24.0, 'vpip_health': 'good',
                                  'pfr': 20.0, 'pfr_health': 'good',
                                  'three_bet': 8.0, 'bb_per_100': 5.0}},
            'tier_order': ['deep'],
        }
        html = _render_player_stats(
            self.overall, self.by_position, self.pos_stats, stack_data,
        )
        self.assertIn('vpip-clickable', html)
        self.assertIn('three-bet-clickable', html)

    def test_backwards_compat_two_args(self):
        """Calling with only overall+by_position still works."""
        html = _render_player_stats(self.overall, self.by_position)
        self.assertIn('VPIP', html)
        self.assertIn('3-Bet', html)
        self.assertIn('6.0%', html)


# ── Full report integration ───────────────────────────────────────────────────

class TestFullReportPfrModalIntegration(unittest.TestCase):
    """Smoke tests: PFR/3-Bet modal JS and HTML present in full report."""

    def _generate_report(self):
        conn, repo = _setup_db()
        # Hand 1: hero opens from BTN
        h1 = _make_hand('H001', hero_position='BTN', net=5.0, hero_stack=100.0)
        repo.insert_hand(h1)
        repo.insert_actions_batch([
            _make_action('H001', 'UTG', 'fold', 1, position='UTG'),
            _make_action('H001', 'Hero', 'raise', 2, position='BTN',
                         is_hero=1, amount=1.5, is_voluntary=1),
        ])
        # Hand 2: hero 3-bets from BTN vs UTG
        h2 = _make_hand('H002', hero_position='BTN', net=8.0, hero_stack=100.0)
        repo.insert_hand(h2)
        repo.insert_actions_batch([
            _make_action('H002', 'UTG', 'raise', 1, position='UTG',
                         amount=1.5, is_voluntary=1),
            _make_action('H002', 'Hero', 'raise', 2, position='BTN',
                         is_hero=1, amount=4.5, is_voluntary=1),
        ])
        conn.commit()

        analyzer = CashAnalyzer(repo)
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            tmp = f.name
        try:
            generate_cash_report(analyzer, output_file=tmp)
            with open(tmp, encoding='utf-8') as f:
                return f.read()
        finally:
            os.unlink(tmp)

    def test_report_contains_pfr_modal_overlay(self):
        html = self._generate_report()
        self.assertIn('pfr-modal-overlay', html)

    def test_report_contains_open_pfr_modal_js(self):
        html = self._generate_report()
        self.assertIn('function openPfrModal()', html)

    def test_report_contains_close_pfr_modal_js(self):
        html = self._generate_report()
        self.assertIn('function closePfrModal()', html)

    def test_report_contains_switch_pfr_tab_js(self):
        html = self._generate_report()
        self.assertIn('function switchPfrTab(tab)', html)

    def test_report_contains_close_pfr_overlay_js(self):
        html = self._generate_report()
        self.assertIn('function closePfrModalOverlay(event)', html)

    def test_report_contains_pfr_tab_buttons(self):
        html = self._generate_report()
        self.assertIn('pfr-tab-btn-pfr', html)
        self.assertIn('pfr-tab-btn-matrix', html)

    def test_report_three_bet_card_is_clickable(self):
        html = self._generate_report()
        self.assertIn('three-bet-clickable', html)

    def test_report_three_bet_card_has_hint(self):
        html = self._generate_report()
        self.assertIn('three-bet-hint', html)

    def test_report_pfr_modal_css_present(self):
        html = self._generate_report()
        self.assertIn('.three-bet-clickable', html)
        self.assertIn('.pfr-matrix-table', html)

    def test_report_esc_closes_both_modals(self):
        """ESC listener should call both closeVpipModal and closePfrModal."""
        html = self._generate_report()
        self.assertIn('closeVpipModal()', html)
        self.assertIn('closePfrModal()', html)
        self.assertIn('Escape', html)

    def test_report_contains_matrix_data(self):
        """The report should contain the 3-bet matrix with BTN and UTG data."""
        html = self._generate_report()
        self.assertIn('pfr-panel-matrix', html)
        # There's a 3-bet opportunity: BTN vs UTG
        self.assertIn('BTN', html)

    def test_report_vpip_modal_still_present(self):
        """US-018 VPIP modal should still be present alongside US-019."""
        html = self._generate_report()
        self.assertIn('vpip-modal-overlay', html)
        self.assertIn('function openVpipModal()', html)


if __name__ == '__main__':
    unittest.main()
