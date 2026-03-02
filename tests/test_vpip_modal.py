"""Tests for US-018: VPIP Drill-Down Modal com Breakdown por Posição e Stack Depth.

Covers:
- _render_vpip_modal() renders modal overlay and modal container
- Modal contains both tab buttons (Por Posição, Por Stack Depth)
- Modal contains both tab panels
- Position panel shows VPIP by position
- Stack depth panel shows VPIP by tier
- Health badges present in modal panels
- _render_player_stats() produces clickable VPIP card when data supplied
- _render_player_stats() produces normal VPIP card when no data supplied
- openVpipModal / closeVpipModal / switchVpipTab JS present in report
- ESC key listener present in report
- Full generate_cash_report() includes modal in output
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer
from src.reports.cash_report import _render_vpip_modal, _render_player_stats


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


def _make_positional_stats(positions=None):
    """Return a minimal positional_stats dict (US-010 shape)."""
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
    return {
        'by_position': positions,
        'blinds_defense': {},
        'ats_by_pos': {},
        'comparison': {},
        'radar': [],
    }


def _make_stack_depth_data(tiers=None):
    """Return a minimal stack_depth_data dict (US-017 shape)."""
    if tiers is None:
        tiers = {
            'deep': {
                'label': '50+ BB', 'total_hands': 100,
                'vpip': 24.0, 'vpip_health': 'good',
                'pfr': 20.0, 'pfr_health': 'good',
                'three_bet': 8.0, 'af': 2.5, 'cbet': 65.0,
                'wtsd': 28.0, 'wsd': 50.0,
                'net': 50.0, 'net_per_hand': 0.5, 'bb_per_100': 5.0,
            },
            'shove': {
                'label': '<15 BB', 'total_hands': 30,
                'vpip': 40.0, 'vpip_health': 'warning',
                'pfr': 38.0, 'pfr_health': 'good',
                'three_bet': 2.0, 'af': 0.5, 'cbet': 50.0,
                'wtsd': 60.0, 'wsd': 45.0,
                'net': -10.0, 'net_per_hand': -0.33, 'bb_per_100': -5.0,
            },
        }
    return {
        'by_tier': tiers,
        'by_position_tier': {'BTN': {'deep': {'vpip': 30.0, 'pfr': 25.0, 'bb_per_100': 8.0}}},
        'tier_order': ['deep', 'medium', 'shallow', 'shove'],
        'tier_labels': {'deep': '50+ BB', 'medium': '25-50 BB', 'shallow': '15-25 BB', 'shove': '<15 BB'},
        'hands_with_stack': 130,
        'hands_total': 150,
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


# ── _render_vpip_modal() tests ────────────────────────────────────────────────

class TestRenderVpipModal(unittest.TestCase):

    def setUp(self):
        self.pos_stats = _make_positional_stats()
        self.stack_data = _make_stack_depth_data()

    def _render(self, pos_stats=None, stack_data=None):
        p = pos_stats if pos_stats is not None else self.pos_stats
        s = stack_data if stack_data is not None else self.stack_data
        return _render_vpip_modal(p, s)

    # ── basic structure ──────────────────────────────────────────────────────

    def test_renders_non_empty(self):
        html = self._render()
        self.assertGreater(len(html), 100)

    def test_contains_modal_overlay(self):
        html = self._render()
        self.assertIn('vpip-modal-overlay', html)

    def test_contains_modal_container(self):
        html = self._render()
        self.assertIn('vpip-modal', html)

    def test_contains_close_button(self):
        html = self._render()
        self.assertIn('vpip-modal-close', html)

    def test_contains_title(self):
        html = self._render()
        self.assertIn('VPIP Drill-Down', html)

    # ── tab buttons ──────────────────────────────────────────────────────────

    def test_contains_position_tab_button(self):
        html = self._render()
        self.assertIn('vpip-tab-btn-position', html)

    def test_contains_stack_tab_button(self):
        html = self._render()
        self.assertIn('vpip-tab-btn-stack', html)

    def test_position_tab_label(self):
        html = self._render()
        self.assertIn('Por Posi', html)   # "Por Posição"

    def test_stack_tab_label(self):
        html = self._render()
        self.assertIn('Por Stack Depth', html)

    # ── tab panels ───────────────────────────────────────────────────────────

    def test_contains_position_panel(self):
        html = self._render()
        self.assertIn('vpip-panel-position', html)

    def test_contains_stack_panel(self):
        html = self._render()
        self.assertIn('vpip-panel-stack', html)

    def test_position_panel_is_active_by_default(self):
        html = self._render()
        # Position panel should have 'active' class
        self.assertIn('id="vpip-panel-position" class="vpip-panel active"', html)

    def test_stack_panel_is_inactive_by_default(self):
        html = self._render()
        # Stack panel should NOT have 'active' class initially
        self.assertIn('id="vpip-panel-stack" class="vpip-panel"', html)

    # ── position panel data ──────────────────────────────────────────────────

    def test_position_panel_shows_btn(self):
        html = self._render()
        self.assertIn('BTN', html)

    def test_position_panel_shows_co(self):
        html = self._render()
        self.assertIn('CO', html)

    def test_position_panel_shows_vpip_value_btn(self):
        html = self._render()
        self.assertIn('30.0%', html)

    def test_position_panel_shows_vpip_value_co(self):
        html = self._render()
        self.assertIn('25.0%', html)

    def test_position_panel_shows_health_badge(self):
        html = self._render()
        self.assertIn('badge-good', html)

    def test_position_panel_shows_pfr(self):
        html = self._render()
        self.assertIn('22.0%', html)  # BTN PFR

    # ── stack depth panel data ───────────────────────────────────────────────

    def test_stack_panel_shows_deep_label(self):
        html = self._render()
        self.assertIn('50+ BB', html)

    def test_stack_panel_shows_shove_label(self):
        html = self._render()
        self.assertIn('<15 BB', html)

    def test_stack_panel_shows_deep_vpip(self):
        html = self._render()
        self.assertIn('24.0%', html)

    def test_stack_panel_shows_shove_vpip(self):
        html = self._render()
        self.assertIn('40.0%', html)

    def test_stack_panel_shows_warning_badge(self):
        html = self._render()
        self.assertIn('badge-warning', html)

    # ── empty / partial data ─────────────────────────────────────────────────

    def test_empty_positional_stats_shows_no_data_message(self):
        html = _render_vpip_modal({}, self.stack_data)
        self.assertIn('Sem dados por posi', html)

    def test_empty_stack_data_shows_no_data_message(self):
        html = _render_vpip_modal(self.pos_stats, {})
        self.assertIn('Sem dados por stack depth', html)

    def test_both_empty_still_renders(self):
        html = _render_vpip_modal({}, {})
        self.assertIn('vpip-modal-overlay', html)

    # ── JS functions embedded ────────────────────────────────────────────────

    def test_close_vpip_modal_js_not_in_modal_html(self):
        """JS is in the main report, not inside the modal HTML itself."""
        html = self._render()
        # The modal function itself contains onclick="closeVpipModal()"
        self.assertIn('closeVpipModal()', html)

    def test_switch_tab_js_reference(self):
        html = self._render()
        self.assertIn('switchVpipTab', html)

    def test_open_vpip_modal_not_in_modal_html(self):
        """openVpipModal is called from the VPIP card, not inside the modal HTML."""
        html = self._render()
        # Modal overlay itself should not call openVpipModal
        self.assertNotIn('openVpipModal', html)


# ── _render_player_stats() tests ──────────────────────────────────────────────

class TestRenderPlayerStatsVpipClickable(unittest.TestCase):

    def setUp(self):
        self.overall = _make_preflop_overall()
        self.by_position = {}
        self.pos_stats = _make_positional_stats()
        self.stack_data = _make_stack_depth_data()

    def test_vpip_card_clickable_when_data_supplied(self):
        html = _render_player_stats(
            self.overall, self.by_position,
            self.pos_stats, self.stack_data,
        )
        self.assertIn('vpip-clickable', html)
        self.assertIn('openVpipModal()', html)

    def test_vpip_card_shows_hint_when_clickable(self):
        html = _render_player_stats(
            self.overall, self.by_position,
            self.pos_stats, self.stack_data,
        )
        self.assertIn('vpip-hint', html)
        self.assertIn('clique para detalhes', html)

    def test_vpip_card_not_clickable_without_data(self):
        html = _render_player_stats(self.overall, self.by_position)
        self.assertNotIn('vpip-clickable', html)
        self.assertNotIn('openVpipModal()', html)

    def test_vpip_card_not_clickable_with_empty_data(self):
        html = _render_player_stats(
            self.overall, self.by_position,
            {}, {},
        )
        self.assertNotIn('vpip-clickable', html)

    def test_vpip_value_shown(self):
        html = _render_player_stats(
            self.overall, self.by_position,
            self.pos_stats, self.stack_data,
        )
        self.assertIn('26.0%', html)

    def test_other_stat_cards_unchanged(self):
        html = _render_player_stats(
            self.overall, self.by_position,
            self.pos_stats, self.stack_data,
        )
        self.assertIn('PFR', html)
        self.assertIn('3-Bet', html)
        self.assertIn('ATS', html)

    def test_backwards_compat_two_args(self):
        """Calling with only overall+by_position still works (no crash)."""
        html = _render_player_stats(self.overall, self.by_position)
        self.assertIn('VPIP', html)
        self.assertIn('26.0%', html)


# ── Full report JS / modal integration ────────────────────────────────────────

class TestFullReportModalIntegration(unittest.TestCase):
    """Smoke tests for the full report: modal JS and HTML are present."""

    def _generate_report(self):
        conn, repo = _setup_db()
        # Insert a minimal hand so analysis functions have data
        hand = _make_hand('H001', hero_position='BTN', net=5.0, hero_stack=100.0)
        repo.insert_hand(hand)
        action = _make_action('H001', 'Hero', 'raise', 1, position='BTN',
                              is_hero=1, amount=1.0, is_voluntary=1)
        repo.insert_actions_batch([action])
        conn.commit()

        analyzer = CashAnalyzer(repo)
        from src.reports.cash_report import generate_cash_report
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            tmp = f.name
        try:
            generate_cash_report(analyzer, output_file=tmp)
            with open(tmp, encoding='utf-8') as f:
                return f.read()
        finally:
            os.unlink(tmp)

    def test_report_contains_vpip_modal_overlay(self):
        html = self._generate_report()
        self.assertIn('vpip-modal-overlay', html)

    def test_report_contains_open_vpip_modal_js(self):
        html = self._generate_report()
        self.assertIn('function openVpipModal()', html)

    def test_report_contains_close_vpip_modal_js(self):
        html = self._generate_report()
        self.assertIn('function closeVpipModal()', html)

    def test_report_contains_switch_tab_js(self):
        html = self._generate_report()
        self.assertIn('function switchVpipTab(tab)', html)

    def test_report_contains_esc_key_listener(self):
        html = self._generate_report()
        self.assertIn('Escape', html)

    def test_report_contains_vpip_tab_buttons(self):
        html = self._generate_report()
        self.assertIn('vpip-tab-btn-position', html)
        self.assertIn('vpip-tab-btn-stack', html)

    def test_report_vpip_card_is_clickable(self):
        html = self._generate_report()
        self.assertIn('vpip-clickable', html)

    def test_report_vpip_card_has_hint(self):
        html = self._generate_report()
        self.assertIn('vpip-hint', html)

    def test_report_modal_css_present(self):
        html = self._generate_report()
        self.assertIn('.vpip-modal-overlay', html)
        self.assertIn('.vpip-modal {', html)

    def test_report_modal_close_overlay_js(self):
        html = self._generate_report()
        self.assertIn('function closeVpipModalOverlay(event)', html)


if __name__ == '__main__':
    unittest.main()
