"""Tests for US-020: Botão Resumo de Leaks por Sessão.

Covers:
- CashAnalyzer.get_session_leak_summary(): empty/good/warning/danger stats
- Leak detection for all 7 stat types (VPIP, PFR, 3-Bet, AF, WTSD, W$SD, CBet)
- Cost estimation (deviation * weight)
- Sorting by cost descending
- Integration with get_session_details() (leak_summary key present)
- _render_session_leak_modal(): structure, tabs, panels, content
- Modal contains stats table and leak analysis panel
- Health badges in modal
- _render_session_card(): leak button presence/absence, button CSS classes
- _render_session_card(): modal appended when stats present
- _render_daily_report(): unique session keys per day
- JS functions: openLeakModal, closeLeakModal, closeLeakModalOverlay, switchLeakTab
- CSS: leak-summary-btn class present in report output
- ESC key listener updated to close leak modals
- Full generate_cash_report() output includes leak modal elements
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer
from src.reports.cash_report import (
    _render_session_leak_modal,
    _render_session_card,
    _render_daily_report,
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


def _good_stats():
    """Session stats where all stats are in healthy range."""
    return {
        'total_hands': 100,
        'vpip': 25.0, 'vpip_health': 'good',
        'pfr': 20.0, 'pfr_health': 'good',
        'three_bet': 9.0, 'three_bet_health': 'good',
        'af': 2.8, 'af_health': 'good',
        'wtsd': 28.0, 'wtsd_health': 'good',
        'wsd': 50.0, 'wsd_health': 'good',
        'cbet': 67.0, 'cbet_health': 'good',
    }


def _warning_stats():
    """Session stats with one warning (VPIP slightly too high)."""
    return {
        'total_hands': 80,
        'vpip': 33.0, 'vpip_health': 'warning',  # >30 warning
        'pfr': 20.0, 'pfr_health': 'good',
        'three_bet': 9.0, 'three_bet_health': 'good',
        'af': 2.8, 'af_health': 'good',
        'wtsd': 28.0, 'wtsd_health': 'good',
        'wsd': 50.0, 'wsd_health': 'good',
        'cbet': 67.0, 'cbet_health': 'good',
    }


def _danger_stats():
    """Session stats with a danger (VPIP very high) and a warning (PFR too low)."""
    return {
        'total_hands': 60,
        'vpip': 45.0, 'vpip_health': 'danger',   # >35 = danger
        'pfr': 12.0, 'pfr_health': 'warning',    # <17 = warning
        'three_bet': 9.0, 'three_bet_health': 'good',
        'af': 2.8, 'af_health': 'good',
        'wtsd': 28.0, 'wtsd_health': 'good',
        'wsd': 50.0, 'wsd_health': 'good',
        'cbet': 67.0, 'cbet_health': 'good',
    }


def _multi_leak_stats():
    """Stats with multiple leaks across preflop + postflop."""
    return {
        'total_hands': 120,
        'vpip': 10.0, 'vpip_health': 'danger',    # too_low
        'pfr': 5.0, 'pfr_health': 'danger',        # too_low
        'three_bet': 20.0, 'three_bet_health': 'danger',  # too_high
        'af': 5.0, 'af_health': 'danger',          # too_high
        'wtsd': 45.0, 'wtsd_health': 'danger',     # too_high
        'wsd': 70.0, 'wsd_health': 'danger',       # too_high
        'cbet': 10.0, 'cbet_health': 'danger',     # too_low
    }


# ── Tests: CashAnalyzer.get_session_leak_summary() ───────────────────────────

class TestGetSessionLeakSummary(unittest.TestCase):

    def setUp(self):
        conn, repo = _setup_db()
        self.analyzer = CashAnalyzer(repo, year='2026')

    # ── empty / trivial cases ─────────────────────────────────────────────────

    def test_empty_stats_returns_empty_list(self):
        result = self.analyzer.get_session_leak_summary({})
        self.assertEqual(result, [])

    def test_none_stats_returns_empty_list(self):
        result = self.analyzer.get_session_leak_summary(None)
        self.assertEqual(result, [])

    def test_zero_hands_returns_empty_list(self):
        stats = {'total_hands': 0, 'vpip': 50.0, 'vpip_health': 'danger'}
        result = self.analyzer.get_session_leak_summary(stats)
        self.assertEqual(result, [])

    # ── healthy stats produce no leaks ────────────────────────────────────────

    def test_all_good_stats_returns_empty_list(self):
        result = self.analyzer.get_session_leak_summary(_good_stats())
        self.assertEqual(result, [])

    # ── warning detection ─────────────────────────────────────────────────────

    def test_warning_vpip_produces_one_leak(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertEqual(len(result), 1)

    def test_warning_leak_has_correct_stat_name(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertEqual(result[0]['stat_name'], 'vpip')

    def test_warning_leak_has_correct_health(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertEqual(result[0]['health'], 'warning')

    def test_warning_leak_has_correct_direction(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertEqual(result[0]['direction'], 'too_high')

    def test_warning_leak_has_value(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertAlmostEqual(result[0]['value'], 33.0)

    # ── danger detection ──────────────────────────────────────────────────────

    def test_danger_stats_produces_two_leaks(self):
        result = self.analyzer.get_session_leak_summary(_danger_stats())
        self.assertEqual(len(result), 2)

    def test_danger_stat_present_in_leaks(self):
        result = self.analyzer.get_session_leak_summary(_danger_stats())
        stat_names = [l['stat_name'] for l in result]
        self.assertIn('vpip', stat_names)

    def test_warning_stat_also_in_leaks(self):
        result = self.analyzer.get_session_leak_summary(_danger_stats())
        stat_names = [l['stat_name'] for l in result]
        self.assertIn('pfr', stat_names)

    # ── sorting by cost ───────────────────────────────────────────────────────

    def test_sorted_by_cost_descending(self):
        result = self.analyzer.get_session_leak_summary(_danger_stats())
        if len(result) >= 2:
            self.assertGreaterEqual(result[0]['cost_bb100'], result[1]['cost_bb100'])

    def test_multi_leaks_sorted_by_cost(self):
        result = self.analyzer.get_session_leak_summary(_multi_leak_stats())
        costs = [l['cost_bb100'] for l in result]
        self.assertEqual(costs, sorted(costs, reverse=True))

    # ── cost calculation ──────────────────────────────────────────────────────

    def test_vpip_too_low_cost_uses_weight_015(self):
        # VPIP = 10, healthy_low = 22, deviation = 12, weight = 0.15 → cost = 1.80
        result = self.analyzer.get_session_leak_summary(_multi_leak_stats())
        vpip_leak = next(l for l in result if l['stat_name'] == 'vpip')
        self.assertAlmostEqual(vpip_leak['cost_bb100'], 1.80, places=1)

    def test_pfr_too_low_cost_uses_weight_018(self):
        # PFR = 5, healthy_low = 17, deviation = 12, weight = 0.18 → cost = 2.16
        result = self.analyzer.get_session_leak_summary(_multi_leak_stats())
        pfr_leak = next(l for l in result if l['stat_name'] == 'pfr')
        self.assertAlmostEqual(pfr_leak['cost_bb100'], 2.16, places=1)

    def test_af_too_high_cost_uses_weight_040(self):
        # AF = 5.0, healthy_high = 3.5, deviation = 1.5, weight = 0.40 → cost = 0.60
        result = self.analyzer.get_session_leak_summary(_multi_leak_stats())
        af_leak = next(l for l in result if l['stat_name'] == 'af')
        self.assertAlmostEqual(af_leak['cost_bb100'], 0.60, places=1)

    # ── healthy range values present ──────────────────────────────────────────

    def test_leak_includes_healthy_low(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertIn('healthy_low', result[0])
        self.assertEqual(result[0]['healthy_low'], 22)  # VPIP healthy_low

    def test_leak_includes_healthy_high(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertIn('healthy_high', result[0])
        self.assertEqual(result[0]['healthy_high'], 30)  # VPIP healthy_high

    # ── suggestion present ────────────────────────────────────────────────────

    def test_leak_has_suggestion_field(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertIn('suggestion', result[0])

    def test_suggestion_is_non_empty_string(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertIsInstance(result[0]['suggestion'], str)
        self.assertGreater(len(result[0]['suggestion']), 5)

    def test_too_high_suggestion_for_vpip(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertIn('Reduza', result[0]['suggestion'])

    def test_too_low_suggestion_for_vpip(self):
        stats = {**_good_stats(), 'vpip': 5.0, 'vpip_health': 'danger'}
        result = self.analyzer.get_session_leak_summary(stats)
        vpip_leak = next(l for l in result if l['stat_name'] == 'vpip')
        self.assertIn('Amplie', vpip_leak['suggestion'])

    # ── all stat types detected ───────────────────────────────────────────────

    def test_af_leak_detected_when_warning(self):
        stats = {**_good_stats(), 'af': 5.0, 'af_health': 'danger'}
        result = self.analyzer.get_session_leak_summary(stats)
        stat_names = [l['stat_name'] for l in result]
        self.assertIn('af', stat_names)

    def test_wtsd_leak_detected_when_warning(self):
        stats = {**_good_stats(), 'wtsd': 50.0, 'wtsd_health': 'danger'}
        result = self.analyzer.get_session_leak_summary(stats)
        stat_names = [l['stat_name'] for l in result]
        self.assertIn('wtsd', stat_names)

    def test_wsd_leak_detected_when_warning(self):
        stats = {**_good_stats(), 'wsd': 80.0, 'wsd_health': 'danger'}
        result = self.analyzer.get_session_leak_summary(stats)
        stat_names = [l['stat_name'] for l in result]
        self.assertIn('wsd', stat_names)

    def test_cbet_leak_detected_when_warning(self):
        stats = {**_good_stats(), 'cbet': 20.0, 'cbet_health': 'danger'}
        result = self.analyzer.get_session_leak_summary(stats)
        stat_names = [l['stat_name'] for l in result]
        self.assertIn('cbet', stat_names)

    def test_three_bet_leak_detected(self):
        stats = {**_good_stats(), 'three_bet': 25.0, 'three_bet_health': 'danger'}
        result = self.analyzer.get_session_leak_summary(stats)
        stat_names = [l['stat_name'] for l in result]
        self.assertIn('three_bet', stat_names)

    # ── label field ───────────────────────────────────────────────────────────

    def test_vpip_leak_has_label_VPIP(self):
        result = self.analyzer.get_session_leak_summary(_warning_stats())
        self.assertEqual(result[0]['label'], 'VPIP')

    def test_three_bet_label(self):
        stats = {**_good_stats(), 'three_bet': 25.0, 'three_bet_health': 'danger'}
        result = self.analyzer.get_session_leak_summary(stats)
        tb = next(l for l in result if l['stat_name'] == 'three_bet')
        self.assertEqual(tb['label'], '3-Bet')


# ── Tests: get_session_details() integration ─────────────────────────────────

class TestGetSessionDetailsLeakSummaryIntegration(unittest.TestCase):

    def setUp(self):
        conn, repo = _setup_db()
        self.repo = repo
        self.analyzer = CashAnalyzer(repo, year='2026')

    def test_session_details_includes_leak_summary_key(self):
        session = {
            'session_id': 1, 'start_time': '2026-01-15T20:00:00',
            'end_time': '2026-01-15T22:00:00',
            'buy_in': 50.0, 'cash_out': 60.0, 'profit': 10.0,
            'hands_count': 0, 'min_stack': 45.0,
        }
        details = self.analyzer.get_session_details(session)
        self.assertIn('leak_summary', details)

    def test_session_details_leak_summary_is_list(self):
        session = {
            'session_id': 1, 'start_time': '2026-01-15T20:00:00',
            'end_time': '2026-01-15T22:00:00',
            'buy_in': 50.0, 'cash_out': 60.0, 'profit': 10.0,
            'hands_count': 0, 'min_stack': 45.0,
        }
        details = self.analyzer.get_session_details(session)
        self.assertIsInstance(details['leak_summary'], list)


# ── Tests: _render_session_leak_modal() ──────────────────────────────────────

class TestRenderSessionLeakModal(unittest.TestCase):

    def setUp(self):
        self.stats = _good_stats()
        self.leak_summary = []

    def _render(self, key='testkey', stats=None, leaks=None):
        s = stats if stats is not None else self.stats
        ls = leaks if leaks is not None else self.leak_summary
        return _render_session_leak_modal(key, s, ls)

    # ── empty / trivial cases ─────────────────────────────────────────────────

    def test_empty_stats_returns_empty_string(self):
        html = _render_session_leak_modal('k', {}, [])
        self.assertEqual(html, '')

    def test_renders_non_empty_for_valid_stats(self):
        html = self._render()
        self.assertGreater(len(html), 100)

    # ── structure ─────────────────────────────────────────────────────────────

    def test_contains_modal_overlay(self):
        html = self._render()
        self.assertIn('vpip-modal-overlay', html)

    def test_contains_modal_container(self):
        html = self._render()
        self.assertIn('vpip-modal', html)

    def test_contains_close_button(self):
        html = self._render()
        self.assertIn('vpip-modal-close', html)

    def test_modal_id_contains_session_key(self):
        html = self._render(key='abc123')
        self.assertIn('leak-modal-abc123', html)

    def test_different_keys_produce_different_ids(self):
        html1 = self._render(key='key1')
        html2 = self._render(key='key2')
        self.assertIn('leak-modal-key1', html1)
        self.assertIn('leak-modal-key2', html2)
        self.assertNotIn('leak-modal-key2', html1)

    def test_contains_resumo_title(self):
        html = self._render()
        self.assertIn('Resumo de Leaks', html)

    def test_contains_session_key_in_close_button_onclick(self):
        html = self._render(key='sess42')
        self.assertIn("closeLeakModal('sess42')", html)

    def test_contains_overlay_onclick(self):
        html = self._render(key='sess42')
        self.assertIn("closeLeakModalOverlay(event,'sess42')", html)

    # ── tab structure ──────────────────────────────────────────────────────────

    def test_contains_stats_tab_button(self):
        html = self._render(key='k1')
        self.assertIn('leak-tab-btn-stats-k1', html)

    def test_contains_leaks_tab_button(self):
        html = self._render(key='k1')
        self.assertIn('leak-tab-btn-leaks-k1', html)

    def test_stats_panel_present(self):
        html = self._render(key='k1')
        self.assertIn('leak-panel-stats-k1', html)

    def test_leaks_panel_present(self):
        html = self._render(key='k1')
        self.assertIn('leak-panel-leaks-k1', html)

    def test_stats_panel_active_by_default(self):
        html = self._render(key='k1')
        self.assertIn('id="leak-panel-stats-k1" class="vpip-panel active"', html)

    def test_leaks_panel_inactive_by_default(self):
        html = self._render(key='k1')
        self.assertIn('id="leak-panel-leaks-k1" class="vpip-panel"', html)

    def test_switch_leak_tab_calls_with_correct_key(self):
        html = self._render(key='kk')
        self.assertIn("switchLeakTab('kk','stats')", html)
        self.assertIn("switchLeakTab('kk','leaks')", html)

    # ── stats table content ────────────────────────────────────────────────────

    def test_stats_table_shows_vpip(self):
        html = self._render()
        self.assertIn('VPIP', html)

    def test_stats_table_shows_pfr(self):
        html = self._render()
        self.assertIn('PFR', html)

    def test_stats_table_shows_three_bet(self):
        html = self._render()
        self.assertIn('3-Bet', html)

    def test_stats_table_shows_af(self):
        html = self._render()
        self.assertIn('AF', html)

    def test_stats_table_shows_vpip_value(self):
        html = self._render()
        self.assertIn('25.0%', html)

    def test_stats_table_shows_health_badge(self):
        html = self._render()
        self.assertIn('badge-good', html)

    def test_stats_table_shows_warning_badge_when_warning(self):
        html = self._render(stats=_warning_stats())
        self.assertIn('badge-warning', html)

    def test_stats_table_shows_danger_badge_when_danger(self):
        html = self._render(stats=_danger_stats())
        self.assertIn('badge-danger', html)

    # ── no-leak message ────────────────────────────────────────────────────────

    def test_no_leak_shows_ok_message_when_no_leaks(self):
        html = self._render(leaks=[])
        self.assertIn('Nenhum problema detectado', html)

    # ── leak content ──────────────────────────────────────────────────────────

    def _make_leak_dict(self, stat='vpip', label='VPIP', value=40.0,
                        health='danger', direction='too_high',
                        low=22, high=30, cost=1.50,
                        suggestion='Reduza range'):
        return {
            'stat_name': stat, 'label': label, 'value': value,
            'health': health, 'healthy_low': low, 'healthy_high': high,
            'cost_bb100': cost, 'direction': direction, 'suggestion': suggestion,
        }

    def test_leak_section_shows_label(self):
        leaks = [self._make_leak_dict()]
        html = self._render(leaks=leaks)
        self.assertIn('VPIP', html)

    def test_leak_section_shows_suggestion(self):
        leaks = [self._make_leak_dict(suggestion='Reduza range de abertura')]
        html = self._render(leaks=leaks)
        self.assertIn('Reduza range de abertura', html)

    def test_leak_section_shows_cost(self):
        leaks = [self._make_leak_dict(cost=1.50)]
        html = self._render(leaks=leaks)
        self.assertIn('1.50', html)

    def test_leak_section_shows_up_arrow_for_too_high(self):
        leaks = [self._make_leak_dict(direction='too_high')]
        html = self._render(leaks=leaks)
        self.assertIn('↑', html)

    def test_leak_section_shows_down_arrow_for_too_low(self):
        leaks = [self._make_leak_dict(direction='too_low', value=5.0)]
        html = self._render(leaks=leaks)
        self.assertIn('↓', html)

    def test_multiple_leaks_all_shown(self):
        leaks = [
            self._make_leak_dict(stat='vpip', label='VPIP', cost=2.0),
            self._make_leak_dict(stat='pfr', label='PFR', cost=1.5),
        ]
        html = self._render(leaks=leaks)
        self.assertIn('VPIP', html)
        self.assertIn('PFR', html)

    def test_leak_count_shown_in_summary(self):
        leaks = [
            self._make_leak_dict(health='danger'),
            self._make_leak_dict(stat='pfr', label='PFR', health='warning', cost=0.5),
        ]
        html = self._render(leaks=leaks)
        # Should show "1 crítico(s)" and "1 atenção"
        self.assertIn('crítico', html)
        self.assertIn('atenção', html)

    def test_total_cost_shown_in_summary(self):
        leaks = [
            self._make_leak_dict(cost=2.0),
            self._make_leak_dict(stat='pfr', label='PFR', cost=1.5),
        ]
        html = self._render(leaks=leaks)
        self.assertIn('3.50', html)  # 2.0 + 1.5

    def test_total_hands_shown(self):
        html = self._render()
        self.assertIn('100', html)  # total_hands from _good_stats


# ── Tests: _render_session_card() with leak button ──────────────────────────

class TestRenderSessionCardLeakButton(unittest.TestCase):

    def _make_sd(self, stats=None, leak_summary=None, session_id=1):
        return {
            'session_id': session_id,
            'start_time': '2026-01-15T20:00:00',
            'end_time': '2026-01-15T22:00:00',
            'duration_minutes': 120,
            'buy_in': 50.0, 'cash_out': 60.0, 'profit': 10.0,
            'hands_count': 80, 'min_stack': 45.0,
            'stats': stats or _good_stats(),
            'sparkline': [],
            'biggest_win': None,
            'biggest_loss': None,
            'ev_data': None,
            'leak_summary': leak_summary if leak_summary is not None else [],
        }

    def _render(self, sd, num=1, key=''):
        return _render_session_card(sd, num, session_key=key)

    # ── no button when no leaks ───────────────────────────────────────────────

    def test_no_leak_btn_when_no_leaks(self):
        sd = self._make_sd(leak_summary=[])
        html = self._render(sd)
        self.assertNotIn('leak-summary-btn', html)

    # ── button present when leaks ─────────────────────────────────────────────

    def _warning_leak(self):
        return [{
            'stat_name': 'vpip', 'label': 'VPIP', 'value': 33.0,
            'health': 'warning', 'healthy_low': 22, 'healthy_high': 30,
            'cost_bb100': 0.45, 'direction': 'too_high', 'suggestion': 'Reduza',
        }]

    def _danger_leak(self):
        return [{
            'stat_name': 'vpip', 'label': 'VPIP', 'value': 50.0,
            'health': 'danger', 'healthy_low': 22, 'healthy_high': 30,
            'cost_bb100': 3.00, 'direction': 'too_high', 'suggestion': 'Reduza',
        }]

    def test_leak_btn_present_when_warning(self):
        sd = self._make_sd(leak_summary=self._warning_leak())
        html = self._render(sd)
        self.assertIn('leak-summary-btn', html)

    def test_leak_btn_present_when_danger(self):
        sd = self._make_sd(leak_summary=self._danger_leak())
        html = self._render(sd)
        self.assertIn('leak-summary-btn', html)

    def test_warning_btn_not_danger_class(self):
        sd = self._make_sd(leak_summary=self._warning_leak())
        html = self._render(sd)
        self.assertIn('leak-summary-btn', html)
        self.assertNotIn('leak-summary-btn danger', html)

    def test_danger_btn_has_danger_class(self):
        sd = self._make_sd(leak_summary=self._danger_leak())
        html = self._render(sd)
        self.assertIn('leak-summary-btn danger', html)

    def test_leak_btn_shows_leak_count(self):
        leaks = self._warning_leak() + [{
            'stat_name': 'pfr', 'label': 'PFR', 'value': 12.0,
            'health': 'warning', 'healthy_low': 17, 'healthy_high': 25,
            'cost_bb100': 0.72, 'direction': 'too_low', 'suggestion': 'Aumente',
        }]
        sd = self._make_sd(leak_summary=leaks)
        html = self._render(sd)
        self.assertIn('Leaks (2)', html)

    def test_leak_btn_has_stop_propagation_onclick(self):
        sd = self._make_sd(leak_summary=self._warning_leak())
        html = self._render(sd)
        self.assertIn('event.stopPropagation()', html)

    def test_leak_btn_calls_open_modal(self):
        sd = self._make_sd(leak_summary=self._warning_leak())
        html = self._render(sd, key='20260115s1')
        self.assertIn("openLeakModal('20260115s1')", html)

    # ── modal appended ────────────────────────────────────────────────────────

    def test_modal_appended_when_stats_and_leaks(self):
        sd = self._make_sd(leak_summary=self._warning_leak())
        html = self._render(sd, key='mykey')
        self.assertIn('leak-modal-mykey', html)

    def test_no_modal_when_no_stats(self):
        # Build sd manually to bypass _make_sd's stats-or-default fallback
        sd = {
            'session_id': 1,
            'start_time': '2026-01-15T20:00:00',
            'end_time': '2026-01-15T22:00:00',
            'duration_minutes': 120,
            'buy_in': 50.0, 'cash_out': 60.0, 'profit': 10.0,
            'hands_count': 80, 'min_stack': 45.0,
            'stats': {},          # explicitly empty
            'sparkline': [],
            'biggest_win': None, 'biggest_loss': None, 'ev_data': None,
            'leak_summary': [],
        }
        html = self._render(sd, key='nokey')
        self.assertNotIn('leak-modal-nokey', html)

    def test_modal_id_uses_session_key(self):
        sd = self._make_sd(leak_summary=self._warning_leak())
        html = self._render(sd, key='uniquekey42')
        self.assertIn('id="leak-modal-uniquekey42"', html)

    def test_fallback_key_uses_session_id(self):
        # When no session_key provided, falls back to session_id
        sd = self._make_sd(session_id=99, leak_summary=self._warning_leak())
        html = _render_session_card(sd, 1)  # no session_key arg
        self.assertIn('leak-modal-99', html)


# ── Tests: _render_daily_report() unique keys ─────────────────────────────────

class TestRenderDailyReportUniqueKeys(unittest.TestCase):

    def _make_session_detail(self, session_id, leak_summary=None):
        return {
            'session_id': session_id,
            'start_time': '2026-01-15T20:00:00',
            'end_time': '2026-01-15T22:00:00',
            'duration_minutes': 120,
            'buy_in': 50.0, 'cash_out': 60.0, 'profit': 10.0,
            'hands_count': 80, 'min_stack': 45.0,
            'stats': _warning_stats(),
            'sparkline': [],
            'biggest_win': None, 'biggest_loss': None, 'ev_data': None,
            'leak_summary': leak_summary or [{
                'stat_name': 'vpip', 'label': 'VPIP', 'value': 33.0,
                'health': 'warning', 'healthy_low': 22, 'healthy_high': 30,
                'cost_bb100': 0.45, 'direction': 'too_high', 'suggestion': 'Reduza',
            }],
        }

    def _make_report(self, date, sessions):
        return {
            'date': date,
            'net': 10.0, 'num_sessions': len(sessions),
            'hands_count': 80, 'total_invested': 50.0,
            'sessions': sessions,
            'day_stats': _good_stats(),
            'comparison': {},
        }

    def test_two_sessions_get_different_modal_ids(self):
        sess1 = self._make_session_detail(1)
        sess2 = self._make_session_detail(2)
        report = self._make_report('2026-01-15', [sess1, sess2])
        html = _render_daily_report(report)
        # Keys should be 20260115s1 and 20260115s2
        self.assertIn('leak-modal-20260115s1', html)
        self.assertIn('leak-modal-20260115s2', html)

    def test_different_days_get_different_keys(self):
        sess = self._make_session_detail(1)
        report1 = self._make_report('2026-01-15', [sess])
        report2 = self._make_report('2026-01-16', [sess])
        html1 = _render_daily_report(report1)
        html2 = _render_daily_report(report2)
        self.assertIn('leak-modal-20260115s1', html1)
        self.assertIn('leak-modal-20260116s1', html2)
        self.assertNotIn('leak-modal-20260116', html1)


# ── Tests: JS and CSS in generate_cash_report() output ───────────────────────

class TestGenerateCashReportLeakFeature(unittest.TestCase):
    """Verify JS functions and CSS classes appear in the full report."""

    @classmethod
    def setUpClass(cls):
        """Generate a minimal full report once for all tests."""
        from src.reports.cash_report import generate_cash_report
        from src.analyzers.ev import EVAnalyzer
        import tempfile, os

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        # Insert minimal hands so the report doesn't bail out
        hd = _make_hand('H001', net=5.0)
        repo.insert_hand(hd)
        actions = [
            _make_action('H001', 'Hero', 'post_sb', 1, is_hero=1),
            _make_action('H001', 'Opp', 'post_bb', 2),
            _make_action('H001', 'Hero', 'raise', 3, amount=1.0,
                         is_hero=1, is_voluntary=1),
            _make_action('H001', 'Opp', 'fold', 4),
        ]
        repo.insert_actions_batch(actions)

        analyzer = CashAnalyzer(repo, year='2026')
        tf = tempfile.NamedTemporaryFile(suffix='.html', delete=False)
        tf.close()
        cls.output_path = tf.name
        generate_cash_report(analyzer, output_file=cls.output_path)
        with open(cls.output_path, encoding='utf-8') as f:
            cls.html = f.read()
        os.unlink(cls.output_path)

    def test_open_leak_modal_js_present(self):
        self.assertIn('function openLeakModal(', self.html)

    def test_close_leak_modal_js_present(self):
        self.assertIn('function closeLeakModal(', self.html)

    def test_close_leak_modal_overlay_js_present(self):
        self.assertIn('function closeLeakModalOverlay(', self.html)

    def test_switch_leak_tab_js_present(self):
        self.assertIn('function switchLeakTab(', self.html)

    def test_esc_listener_closes_leak_modals(self):
        self.assertIn('leak-modal-', self.html)

    def test_leak_summary_btn_css_class_present(self):
        self.assertIn('leak-summary-btn', self.html)

    def test_esc_handler_uses_queryselector_for_leak_modals(self):
        self.assertIn('[id^="leak-modal-"]', self.html)


if __name__ == '__main__':
    unittest.main()
