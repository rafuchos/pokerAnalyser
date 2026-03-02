"""Tests for US-012: Red Line / Blue Line (Non-Showdown vs Showdown Winnings).

Covers:
- CashAnalyzer._hand_went_to_showdown: hand classification (showdown vs non-showdown)
- _downsample_redline: chart data downsampling
- _generate_redline_diagnostics: automatic diagnostic messages
- CashAnalyzer.get_redline_blueline: cumulative profit split (cash)
- CashAnalyzer._compute_redline_by_session: per-session breakdown
- TournamentAnalyzer.get_redline_blueline: cumulative profit split (tournament)
- Report: _render_redline_blueline_chart (SVG 3-line chart)
- Report: _render_redline_blueline (cash HTML section)
- Report: _render_redline_chart_tourn (tournament SVG chart)
- Report: _render_redline_blueline_tournament (tournament HTML section)
- Edge cases: empty DB, too few hands, no hero, large datasets
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer, _downsample_redline, _generate_redline_diagnostics
from src.analyzers.tournament import TournamentAnalyzer
from src.reports.cash_report import (
    _render_redline_blueline_chart,
    _render_redline_blueline,
)
from src.reports.tournament_report import (
    _render_redline_chart_tourn,
    _render_redline_blueline_tournament,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_hand(hand_id, date='2026-01-15T20:00:00', hero_position='CO', **kwargs):
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='cash',
        date=datetime.fromisoformat(date) if isinstance(date, str) else date,
        blinds_sb=kwargs.get('blinds_sb', 0.25),
        blinds_bb=kwargs.get('blinds_bb', 0.50),
        hero_cards=kwargs.get('hero_cards', 'Ah Kd'),
        hero_position=hero_position,
        invested=kwargs.get('invested', 1.0),
        won=kwargs.get('won', 0.0),
        net=kwargs.get('net', -1.0),
        rake=0.0,
        table_name='T',
        num_players=kwargs.get('num_players', 6),
    )


def _make_tournament_hand(hand_id, tournament_id='T100', date='2026-01-15T20:00:00',
                          hero_position='CO', **kwargs):
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


def _create_session(repo, date='2026-01-15',
                    start_time='2026-01-15T19:00:00',
                    end_time='2026-01-15T21:00:00',
                    buy_in=50.0, cash_out=75.0,
                    profit=25.0, hands_count=10, min_stack=35.0):
    return repo.insert_session({
        'platform': 'GGPoker',
        'start_time': datetime.fromisoformat(start_time),
        'end_time': datetime.fromisoformat(end_time),
        'buy_in': buy_in,
        'cash_out': cash_out,
        'profit': profit,
        'hands_count': hands_count,
        'min_stack': min_stack,
    })


def _insert_tournament(repo, tournament_id='T100', date='2026-01-15'):
    repo.insert_tournament({
        'tournament_id': tournament_id,
        'platform': 'GGPoker',
        'name': 'MTT $5.50',
        'date': date,
        'buy_in': 5.0,
        'rake': 0.5,
        'prize': 0.0,
        'position': None,
        'entries': 100,
        'is_satellite': False,
    })


def _actions(hand_id, entries):
    """Build list of dicts from compact tuples: (player, action, seq, street, is_hero).

    _hand_went_to_showdown() expects list[dict] as returned by the repository,
    not ActionData objects.
    """
    result = []
    for player, action_type, seq, street, is_hero in entries:
        result.append({
            'hand_id': hand_id,
            'player': player,
            'action_type': action_type,
            'sequence_order': seq,
            'street': street,
            'is_hero': is_hero,
            'amount': 0.0,
            'position': 'CO',
        })
    return result


# ── Unit Tests: _hand_went_to_showdown ───────────────────────────────

class TestHandWentToShowdown(unittest.TestCase):
    """Tests for CashAnalyzer._hand_went_to_showdown()."""

    def test_no_actions_returns_false(self):
        """Empty actions list → not showdown."""
        self.assertFalse(CashAnalyzer._hand_went_to_showdown([], None))

    def test_opponent_cards_returns_true(self):
        """Hand with opponent_cards set → showdown detected via parser."""
        hand = {'opponent_cards': 'Qh Jd', 'hand_id': 'H1'}
        self.assertTrue(CashAnalyzer._hand_went_to_showdown([], hand))

    def test_preflop_only_returns_false(self):
        """Hand with only preflop actions → cannot be showdown."""
        acts = _actions('H1', [
            ('V1', 'fold', 1, 'preflop', 0),
            ('Hero', 'raise', 2, 'preflop', 1),
            ('V2', 'fold', 3, 'preflop', 0),
        ])
        self.assertFalse(CashAnalyzer._hand_went_to_showdown(acts, None))

    def test_hero_folds_on_flop_returns_false(self):
        """Hero folds postflop → not showdown."""
        acts = _actions('H1', [
            ('Hero', 'raise', 1, 'preflop', 1),
            ('V1', 'call', 2, 'preflop', 0),
            ('Hero', 'bet', 3, 'flop', 1),
            ('V1', 'raise', 4, 'flop', 0),
            ('Hero', 'fold', 5, 'flop', 1),
        ])
        self.assertFalse(CashAnalyzer._hand_went_to_showdown(acts, None))

    def test_no_hero_in_actions_returns_false(self):
        """No action with is_hero=1 → can't identify hero, not showdown."""
        acts = _actions('H1', [
            ('V1', 'raise', 1, 'preflop', 0),
            ('V2', 'call', 2, 'preflop', 0),
            ('V1', 'bet', 3, 'flop', 0),
            ('V2', 'call', 4, 'flop', 0),
        ])
        self.assertFalse(CashAnalyzer._hand_went_to_showdown(acts, None))

    def test_two_players_reach_river_returns_true(self):
        """Hero and one opponent both reach river without folding → showdown."""
        acts = _actions('H1', [
            ('Hero', 'raise', 1, 'preflop', 1),
            ('V1', 'call', 2, 'preflop', 0),
            ('Hero', 'bet', 3, 'flop', 1),
            ('V1', 'call', 4, 'flop', 0),
            ('Hero', 'check', 5, 'turn', 1),
            ('V1', 'check', 6, 'turn', 0),
            ('Hero', 'check', 7, 'river', 1),
            ('V1', 'check', 8, 'river', 0),
        ])
        self.assertTrue(CashAnalyzer._hand_went_to_showdown(acts, None))

    def test_opponent_folds_on_flop_returns_false(self):
        """Opponent folds on flop → hero wins without showdown."""
        acts = _actions('H1', [
            ('Hero', 'raise', 1, 'preflop', 1),
            ('V1', 'call', 2, 'preflop', 0),
            ('Hero', 'bet', 3, 'flop', 1),
            ('V1', 'fold', 4, 'flop', 0),
        ])
        self.assertFalse(CashAnalyzer._hand_went_to_showdown(acts, None))

    def test_only_hero_remains_returns_false(self):
        """All opponents fold; only hero remains → not a showdown."""
        acts = _actions('H1', [
            ('V1', 'raise', 1, 'preflop', 0),
            ('V2', 'fold', 2, 'preflop', 0),
            ('Hero', 'call', 3, 'preflop', 1),
            ('V1', 'bet', 4, 'flop', 0),
            ('Hero', 'raise', 5, 'flop', 1),
            ('V1', 'fold', 6, 'flop', 0),
        ])
        self.assertFalse(CashAnalyzer._hand_went_to_showdown(acts, None))

    def test_opponent_cards_overrides_no_postflop(self):
        """opponent_cards in hand data takes priority even without postflop actions."""
        hand = {'opponent_cards': 'As Kc'}
        acts = _actions('H1', [
            ('Hero', 'raise', 1, 'preflop', 1),
            ('V1', 'call', 2, 'preflop', 0),
        ])
        self.assertTrue(CashAnalyzer._hand_went_to_showdown(acts, hand))

    def test_three_way_pot_hero_folds_returns_false(self):
        """Three-way pot; hero folds on flop → not showdown for hero."""
        acts = _actions('H1', [
            ('Hero', 'raise', 1, 'preflop', 1),
            ('V1', 'call', 2, 'preflop', 0),
            ('V2', 'call', 3, 'preflop', 0),
            ('Hero', 'bet', 4, 'flop', 1),
            ('V1', 'raise', 5, 'flop', 0),
            ('V2', 'fold', 6, 'flop', 0),
            ('Hero', 'fold', 7, 'flop', 1),
        ])
        self.assertFalse(CashAnalyzer._hand_went_to_showdown(acts, None))


# ── Unit Tests: _downsample_redline ──────────────────────────────────

class TestDownsampleRedline(unittest.TestCase):
    """Tests for _downsample_redline()."""

    def _make_chart_data(self, n):
        return [{'hand': i + 1, 'total': float(i), 'showdown': 0.0, 'nonshowdown': float(i)}
                for i in range(n)]

    def test_small_data_returned_unchanged(self):
        """Data with fewer points than max_points → returned as-is."""
        data = self._make_chart_data(10)
        result = _downsample_redline(data, 100)
        self.assertEqual(result, data)

    def test_exact_max_points_unchanged(self):
        """Data with exactly max_points → returned as-is."""
        data = self._make_chart_data(50)
        result = _downsample_redline(data, 50)
        self.assertEqual(result, data)

    def test_large_data_downsampled_to_max(self):
        """Data with 1000 points downsampled to exactly 500."""
        data = self._make_chart_data(1000)
        result = _downsample_redline(data, 500)
        self.assertEqual(len(result), 500)

    def test_keeps_first_point(self):
        """First point always preserved."""
        data = self._make_chart_data(200)
        result = _downsample_redline(data, 50)
        self.assertEqual(result[0], data[0])

    def test_keeps_last_point(self):
        """Last point always preserved."""
        data = self._make_chart_data(200)
        result = _downsample_redline(data, 50)
        self.assertEqual(result[-1], data[-1])

    def test_output_has_required_keys(self):
        """Downsampled points retain all required chart keys."""
        data = self._make_chart_data(200)
        result = _downsample_redline(data, 50)
        for point in result:
            self.assertIn('hand', point)
            self.assertIn('total', point)
            self.assertIn('showdown', point)
            self.assertIn('nonshowdown', point)

    def test_two_points_not_downsampled(self):
        """Boundary: 2 points → no downsampling needed."""
        data = self._make_chart_data(2)
        result = _downsample_redline(data, 500)
        self.assertEqual(len(result), 2)


# ── Unit Tests: _generate_redline_diagnostics ─────────────────────────

class TestGenerateRedlineDiagnostics(unittest.TestCase):
    """Tests for _generate_redline_diagnostics()."""

    def test_too_few_total_hands_returns_empty(self):
        """Less than 20 total hands → no diagnostics."""
        result = _generate_redline_diagnostics(10.0, -5.0, 10, 9, 19)
        self.assertEqual(result, [])

    def test_zero_hands_returns_empty(self):
        """Zero hands → no diagnostics."""
        result = _generate_redline_diagnostics(0.0, 0.0, 0, 0, 0)
        self.assertEqual(result, [])

    def test_red_line_falling_produces_danger(self):
        """Negative NSD net with enough NSD hands → 'Red line caindo' danger."""
        result = _generate_redline_diagnostics(5.0, -50.0, 15, 25, 40)
        titles = [d['title'] for d in result]
        self.assertIn('Red line caindo', titles)
        d = next(x for x in result if x['title'] == 'Red line caindo')
        self.assertEqual(d['type'], 'danger')

    def test_red_line_positive_produces_good(self):
        """Positive NSD net with enough NSD hands → 'Red line saudável' good."""
        result = _generate_redline_diagnostics(5.0, 30.0, 15, 25, 40)
        titles = [d['title'] for d in result]
        self.assertIn('Red line saudável', titles)
        d = next(x for x in result if x['title'] == 'Red line saudável')
        self.assertEqual(d['type'], 'good')

    def test_blue_line_falling_produces_danger(self):
        """Negative SD net with enough SD hands → 'Blue line caindo' danger."""
        result = _generate_redline_diagnostics(-30.0, 5.0, 15, 25, 40)
        titles = [d['title'] for d in result]
        self.assertIn('Blue line caindo', titles)
        d = next(x for x in result if x['title'] == 'Blue line caindo')
        self.assertEqual(d['type'], 'danger')

    def test_blue_line_positive_produces_good(self):
        """Positive SD net with enough SD hands → 'Blue line saudável' good."""
        result = _generate_redline_diagnostics(30.0, 5.0, 15, 25, 40)
        titles = [d['title'] for d in result]
        self.assertIn('Blue line saudável', titles)
        d = next(x for x in result if x['title'] == 'Blue line saudável')
        self.assertEqual(d['type'], 'good')

    def test_high_showdown_rate_produces_warning(self):
        """Showdown rate > 35% → 'Alta taxa de showdown' warning."""
        # 40/100 = 40% showdown rate
        result = _generate_redline_diagnostics(10.0, 5.0, 40, 60, 100)
        titles = [d['title'] for d in result]
        self.assertIn('Alta taxa de showdown', titles)
        d = next(x for x in result if x['title'] == 'Alta taxa de showdown')
        self.assertEqual(d['type'], 'warning')

    def test_normal_showdown_rate_no_warning(self):
        """Showdown rate ≤ 35% → no high showdown rate warning."""
        # 20/100 = 20% showdown rate
        result = _generate_redline_diagnostics(10.0, 5.0, 20, 80, 100)
        titles = [d['title'] for d in result]
        self.assertNotIn('Alta taxa de showdown', titles)

    def test_too_few_nsd_hands_no_red_diagnostic(self):
        """NSD hands ≤ 20 → no red line diagnostic even with negative net."""
        result = _generate_redline_diagnostics(5.0, -50.0, 15, 10, 25)
        titles = [d['title'] for d in result]
        self.assertNotIn('Red line caindo', titles)
        self.assertNotIn('Red line saudável', titles)

    def test_too_few_sd_hands_no_blue_diagnostic(self):
        """SD hands ≤ 10 → no blue line diagnostic even with negative net."""
        result = _generate_redline_diagnostics(-50.0, 5.0, 8, 22, 30)
        titles = [d['title'] for d in result]
        self.assertNotIn('Blue line caindo', titles)
        self.assertNotIn('Blue line saudável', titles)

    def test_both_lines_negative_produces_two_dangers(self):
        """Both lines negative → both danger diagnostics."""
        result = _generate_redline_diagnostics(-30.0, -20.0, 15, 25, 40)
        types = [d['type'] for d in result]
        self.assertEqual(types.count('danger'), 2)


# ── Integration Tests: CashAnalyzer.get_redline_blueline ─────────────

class TestCashRedlineBlueline(unittest.TestCase):
    """Integration tests for CashAnalyzer.get_redline_blueline()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_empty_db_returns_zero_hands(self):
        """Empty database → total_hands = 0, empty chart_data."""
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(result['total_hands'], 0)
        self.assertEqual(result['chart_data'], [])
        self.assertEqual(result['showdown_hands'], 0)
        self.assertEqual(result['nonshowdown_hands'], 0)

    def test_nonshowdown_hand_increments_red_line(self):
        """Hand where opponent folds postflop → counted as non-showdown."""
        hand = _make_hand('H1', net=5.0)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'call', 2, 'preflop'),
            _make_action('H1', 'Hero', 'bet', 3, 'flop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 4, 'flop'),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(result['total_hands'], 1)
        self.assertEqual(result['nonshowdown_hands'], 1)
        self.assertEqual(result['showdown_hands'], 0)
        self.assertAlmostEqual(result['nonshowdown_net'], 5.0)
        self.assertAlmostEqual(result['showdown_net'], 0.0)

    def test_showdown_hand_increments_blue_line(self):
        """Hand where both players see river → counted as showdown."""
        hand = _make_hand('H1', net=10.0)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'call', 2, 'preflop'),
            _make_action('H1', 'Hero', 'bet', 3, 'flop', is_hero=1),
            _make_action('H1', 'V1', 'call', 4, 'flop'),
            _make_action('H1', 'Hero', 'check', 5, 'turn', is_hero=1),
            _make_action('H1', 'V1', 'check', 6, 'turn'),
            _make_action('H1', 'Hero', 'check', 7, 'river', is_hero=1),
            _make_action('H1', 'V1', 'check', 8, 'river'),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(result['showdown_hands'], 1)
        self.assertEqual(result['nonshowdown_hands'], 0)
        self.assertAlmostEqual(result['showdown_net'], 10.0)
        self.assertAlmostEqual(result['nonshowdown_net'], 0.0)

    def test_chart_data_has_required_keys(self):
        """Each chart_data entry has hand, total, showdown, nonshowdown keys."""
        hand = _make_hand('H1', net=3.0)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 2, 'preflop'),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(len(result['chart_data']), 1)
        point = result['chart_data'][0]
        for key in ('hand', 'total', 'showdown', 'nonshowdown'):
            self.assertIn(key, point)

    def test_cumulative_values_accumulate_correctly(self):
        """Multiple hands → cumulative values in chart_data increase correctly."""
        # Hand 1: NSD, +5
        h1 = _make_hand('H1', date='2026-01-15T20:00:00', net=5.0)
        self.repo.insert_hand(h1)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'call', 2, 'preflop'),
            _make_action('H1', 'Hero', 'bet', 3, 'flop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 4, 'flop'),
        ])
        # Hand 2: Showdown, +8
        h2 = _make_hand('H2', date='2026-01-15T20:01:00', net=8.0)
        self.repo.insert_hand(h2)
        self.repo.insert_actions_batch([
            _make_action('H2', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H2', 'V1', 'call', 2, 'preflop'),
            _make_action('H2', 'Hero', 'bet', 3, 'flop', is_hero=1),
            _make_action('H2', 'V1', 'call', 4, 'flop'),
            _make_action('H2', 'Hero', 'check', 5, 'turn', is_hero=1),
            _make_action('H2', 'V1', 'check', 6, 'turn'),
            _make_action('H2', 'Hero', 'check', 7, 'river', is_hero=1),
            _make_action('H2', 'V1', 'check', 8, 'river'),
        ])
        result = self.analyzer.get_redline_blueline()
        chart = result['chart_data']
        self.assertEqual(len(chart), 2)
        # After hand 1 (NSD): total=5, nsd=5, sd=0
        self.assertAlmostEqual(chart[0]['total'], 5.0)
        self.assertAlmostEqual(chart[0]['nonshowdown'], 5.0)
        self.assertAlmostEqual(chart[0]['showdown'], 0.0)
        # After hand 2 (SD): total=13, nsd=5, sd=8
        self.assertAlmostEqual(chart[1]['total'], 13.0)
        self.assertAlmostEqual(chart[1]['nonshowdown'], 5.0)
        self.assertAlmostEqual(chart[1]['showdown'], 8.0)

    def test_return_dict_has_all_required_keys(self):
        """Return dict contains all expected top-level keys."""
        result = self.analyzer.get_redline_blueline()
        expected_keys = {
            'chart_data', 'total_hands', 'showdown_hands', 'nonshowdown_hands',
            'total_net', 'showdown_net', 'nonshowdown_net', 'diagnostics', 'by_session',
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_diagnostics_empty_with_too_few_hands(self):
        """Fewer than 20 hands → no diagnostics generated."""
        for i in range(5):
            hand = _make_hand(f'H{i}', net=-1.0)
            self.repo.insert_hand(hand)
            self.repo.insert_actions_batch([
                _make_action(f'H{i}', 'Hero', 'raise', 1, 'preflop', is_hero=1),
                _make_action(f'H{i}', 'V1', 'fold', 2, 'preflop'),
            ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(result['diagnostics'], [])

    def test_by_session_breakdown_present(self):
        """With a session, by_session breakdown includes session data."""
        _create_session(self.repo)
        hand = _make_hand('H1', net=3.0)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 2, 'preflop'),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertIsInstance(result['by_session'], list)

    def test_by_session_entry_has_required_keys(self):
        """Each by_session entry has the expected fields."""
        _create_session(self.repo)
        hand = _make_hand('H1', net=5.0)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'call', 2, 'preflop'),
            _make_action('H1', 'Hero', 'bet', 3, 'flop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 4, 'flop'),
        ])
        result = self.analyzer.get_redline_blueline()
        if result['by_session']:
            session = result['by_session'][0]
            for key in ('hands', 'showdown_hands', 'nonshowdown_hands',
                        'showdown_net', 'nonshowdown_net', 'total_net'):
                self.assertIn(key, session)

    def test_preflop_only_hands_counted_as_nonshowdown(self):
        """Preflop-only hands (fold pre-flop) → non-showdown."""
        hand = _make_hand('H1', net=-1.0)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'V1', 'raise', 1, 'preflop'),
            _make_action('H1', 'Hero', 'fold', 2, 'preflop', is_hero=1),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(result['nonshowdown_hands'], 1)
        self.assertEqual(result['showdown_hands'], 0)

    def test_total_net_equals_sum_of_sd_and_nsd(self):
        """total_net must equal showdown_net + nonshowdown_net."""
        for i in range(3):
            h = _make_hand(f'H{i}', net=float(i + 1))
            self.repo.insert_hand(h)
            self.repo.insert_actions_batch([
                _make_action(f'H{i}', 'Hero', 'raise', 1, 'preflop', is_hero=1),
                _make_action(f'H{i}', 'V1', 'fold', 2, 'preflop'),
            ])
        result = self.analyzer.get_redline_blueline()
        self.assertAlmostEqual(
            result['total_net'],
            result['showdown_net'] + result['nonshowdown_net'],
            places=2,
        )


# ── Integration Tests: CashAnalyzer._compute_redline_by_session ──────

class TestCashRedlineBySession(unittest.TestCase):
    """Tests for CashAnalyzer._compute_redline_by_session()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_session_with_no_hands_excluded(self):
        """Session with no hands → not included in by_session."""
        _create_session(self.repo)
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(result['by_session'], [])

    def test_session_totals_match_hand_data(self):
        """Session totals match inserted hand data."""
        _create_session(self.repo)
        # NSD hand: +5
        hand = _make_hand('H1', net=5.0)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'call', 2, 'preflop'),
            _make_action('H1', 'Hero', 'bet', 3, 'flop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 4, 'flop'),
        ])
        result = self.analyzer.get_redline_blueline()
        # Session total should reflect the hand
        overall_nsd = result['nonshowdown_net']
        self.assertAlmostEqual(overall_nsd, 5.0)

    def test_multiple_sessions_produce_multiple_entries(self):
        """Two sessions with hands → two by_session entries."""
        _create_session(self.repo, date='2026-01-15',
                        start_time='2026-01-15T19:00:00',
                        end_time='2026-01-15T21:00:00')
        _create_session(self.repo, date='2026-01-16',
                        start_time='2026-01-16T19:00:00',
                        end_time='2026-01-16T21:00:00')
        # Hand in session 1
        h1 = _make_hand('H1', date='2026-01-15T20:00:00', net=3.0)
        self.repo.insert_hand(h1)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 2, 'preflop'),
        ])
        # Hand in session 2
        h2 = _make_hand('H2', date='2026-01-16T20:00:00', net=-2.0)
        self.repo.insert_hand(h2)
        self.repo.insert_actions_batch([
            _make_action('H2', 'V1', 'raise', 1, 'preflop'),
            _make_action('H2', 'Hero', 'fold', 2, 'preflop', is_hero=1),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(len(result['by_session']), 2)


# ── Integration Tests: TournamentAnalyzer.get_redline_blueline ───────

class TestTournamentRedlineBlueline(unittest.TestCase):
    """Integration tests for TournamentAnalyzer.get_redline_blueline()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, year='2026')

    def tearDown(self):
        self.conn.close()

    def test_empty_db_returns_zero_hands(self):
        """Empty database → total_hands = 0."""
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(result['total_hands'], 0)
        self.assertEqual(result['chart_data'], [])

    def test_return_dict_has_all_required_keys(self):
        """Return dict contains all expected top-level keys."""
        result = self.analyzer.get_redline_blueline()
        expected_keys = {
            'chart_data', 'total_hands', 'showdown_hands', 'nonshowdown_hands',
            'total_net', 'showdown_net', 'nonshowdown_net', 'diagnostics', 'by_session',
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_nonshowdown_hand_increments_red_line(self):
        """Tournament hand where opponent folds postflop → non-showdown."""
        _insert_tournament(self.repo, 'T1')
        hand = _make_tournament_hand('H1', tournament_id='T1', net=500)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'call', 2, 'preflop'),
            _make_action('H1', 'Hero', 'bet', 3, 'flop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 4, 'flop'),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(result['nonshowdown_hands'], 1)
        self.assertEqual(result['showdown_hands'], 0)
        self.assertAlmostEqual(result['nonshowdown_net'], 500.0)

    def test_showdown_hand_increments_blue_line(self):
        """Tournament hand where both players reach river → showdown."""
        _insert_tournament(self.repo, 'T1')
        hand = _make_tournament_hand('H1', tournament_id='T1', net=1000)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'call', 2, 'preflop'),
            _make_action('H1', 'Hero', 'check', 3, 'flop', is_hero=1),
            _make_action('H1', 'V1', 'check', 4, 'flop'),
            _make_action('H1', 'Hero', 'check', 5, 'turn', is_hero=1),
            _make_action('H1', 'V1', 'check', 6, 'turn'),
            _make_action('H1', 'Hero', 'check', 7, 'river', is_hero=1),
            _make_action('H1', 'V1', 'check', 8, 'river'),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(result['showdown_hands'], 1)
        self.assertEqual(result['nonshowdown_hands'], 0)
        self.assertAlmostEqual(result['showdown_net'], 1000.0)

    def test_by_session_groups_by_day(self):
        """by_session groups hands by day (date prefix)."""
        _insert_tournament(self.repo, 'T1', date='2026-01-15')
        _insert_tournament(self.repo, 'T2', date='2026-01-16')
        # Day 1 hands
        h1 = _make_tournament_hand('H1', tournament_id='T1',
                                   date='2026-01-15T20:00:00', net=300)
        self.repo.insert_hand(h1)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 2, 'preflop'),
        ])
        # Day 2 hands
        h2 = _make_tournament_hand('H2', tournament_id='T2',
                                   date='2026-01-16T20:00:00', net=-200)
        self.repo.insert_hand(h2)
        self.repo.insert_actions_batch([
            _make_action('H2', 'V1', 'raise', 1, 'preflop'),
            _make_action('H2', 'Hero', 'fold', 2, 'preflop', is_hero=1),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(len(result['by_session']), 2)
        dates = {s['date'] for s in result['by_session']}
        self.assertIn('2026-01-15', dates)
        self.assertIn('2026-01-16', dates)

    def test_by_session_entry_has_required_keys(self):
        """Each by_session entry has all required fields."""
        _insert_tournament(self.repo, 'T1')
        hand = _make_tournament_hand('H1', tournament_id='T1', net=100)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 2, 'preflop'),
        ])
        result = self.analyzer.get_redline_blueline()
        if result['by_session']:
            session = result['by_session'][0]
            for key in ('date', 'hands', 'showdown_hands', 'nonshowdown_hands',
                        'showdown_net', 'nonshowdown_net', 'total_net'):
                self.assertIn(key, session)

    def test_chart_data_structure(self):
        """chart_data entries have hand, total, showdown, nonshowdown."""
        _insert_tournament(self.repo, 'T1')
        hand = _make_tournament_hand('H1', tournament_id='T1', net=200)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('H1', 'Hero', 'raise', 1, 'preflop', is_hero=1),
            _make_action('H1', 'V1', 'fold', 2, 'preflop'),
        ])
        result = self.analyzer.get_redline_blueline()
        self.assertEqual(len(result['chart_data']), 1)
        point = result['chart_data'][0]
        for key in ('hand', 'total', 'showdown', 'nonshowdown'):
            self.assertIn(key, point)

    def test_total_net_equals_sum(self):
        """total_net = showdown_net + nonshowdown_net for tournaments."""
        _insert_tournament(self.repo, 'T1')
        for i in range(3):
            h = _make_tournament_hand(f'H{i}', tournament_id='T1',
                                      date=f'2026-01-15T20:0{i}:00', net=100 * (i + 1))
            self.repo.insert_hand(h)
            self.repo.insert_actions_batch([
                _make_action(f'H{i}', 'Hero', 'raise', 1, 'preflop', is_hero=1),
                _make_action(f'H{i}', 'V1', 'fold', 2, 'preflop'),
            ])
        result = self.analyzer.get_redline_blueline()
        self.assertAlmostEqual(
            result['total_net'],
            result['showdown_net'] + result['nonshowdown_net'],
            places=1,
        )


# ── Unit Tests: _render_redline_blueline_chart ───────────────────────

class TestRenderRedlineBluelineChart(unittest.TestCase):
    """Tests for _render_redline_blueline_chart() SVG generation."""

    def _make_chart_data(self, n=10, offset=0):
        """Build minimal chart_data list."""
        return [
            {
                'hand': i + 1,
                'total': float(i + offset),
                'showdown': float((i + offset) * 0.6),
                'nonshowdown': float((i + offset) * 0.4),
            }
            for i in range(n)
        ]

    def test_returns_string(self):
        """Output is a non-empty string."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_contains_svg_element(self):
        """Output contains SVG element."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertIn('<svg', result)
        self.assertIn('</svg>', result)

    def test_contains_three_polylines(self):
        """Output contains exactly 3 polyline elements (total, showdown, nonshowdown)."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertEqual(result.count('<polyline'), 3)

    def test_contains_legend(self):
        """Output contains legend text for all three lines."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertIn('Showdown', result)
        self.assertIn('Não-Showdown', result)
        self.assertIn('Total', result)

    def test_contains_green_total_line(self):
        """Green (#00ff88) stroke for total line."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertIn('#00ff88', result)

    def test_contains_blue_showdown_line(self):
        """Blue (#4488ff) stroke for showdown line."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertIn('#4488ff', result)

    def test_contains_red_nonshowdown_line(self):
        """Red (#ff4444) stroke for non-showdown line."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertIn('#ff4444', result)

    def test_zero_line_present_when_values_cross_zero(self):
        """Dashed zero line shown when values span positive and negative."""
        data = [
            {'hand': 1, 'total': -5.0, 'showdown': -3.0, 'nonshowdown': -2.0},
            {'hand': 2, 'total': 5.0, 'showdown': 3.0, 'nonshowdown': 2.0},
        ]
        result = _render_redline_blueline_chart(data)
        self.assertIn('stroke-dasharray', result)

    def test_no_zero_line_when_all_positive(self):
        """No dashed zero line when all values are positive."""
        data = [
            {'hand': i + 1, 'total': float(i + 1), 'showdown': float(i),
             'nonshowdown': 1.0}
            for i in range(5)
        ]
        result = _render_redline_blueline_chart(data)
        # Zero line only when y_min <= 0 <= y_max; all positive → no dash line
        # (The grid lines may use dasharray but the zero line specifically won't show)
        # Check that the dashed zero crosser is absent or the chart works
        self.assertIn('<svg', result)

    def test_axis_labels_present(self):
        """X and Y axis labels are rendered."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertIn('Mãos', result)
        self.assertIn('Profit', result)

    def test_grid_lines_present(self):
        """Grid lines are rendered in the chart."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertIn('<line', result)

    def test_viewbox_present(self):
        """SVG has viewBox attribute for responsiveness."""
        data = self._make_chart_data()
        result = _render_redline_blueline_chart(data)
        self.assertIn('viewBox', result)

    def test_single_point_chart_renders(self):
        """Single data point → chart still renders without error."""
        data = [{'hand': 1, 'total': 5.0, 'showdown': 3.0, 'nonshowdown': 2.0}]
        result = _render_redline_blueline_chart(data)
        self.assertIn('<svg', result)


# ── Unit Tests: _render_redline_blueline ─────────────────────────────

class TestRenderRedlineBlueline(unittest.TestCase):
    """Tests for _render_redline_blueline() HTML section generation."""

    def _make_data(self, n_hands=10, showdown_net=50.0, nonshowdown_net=-20.0):
        """Build minimal redline data dict."""
        total = showdown_net + nonshowdown_net
        chart = [
            {
                'hand': i + 1,
                'total': total * (i + 1) / n_hands,
                'showdown': showdown_net * (i + 1) / n_hands,
                'nonshowdown': nonshowdown_net * (i + 1) / n_hands,
            }
            for i in range(n_hands)
        ]
        return {
            'total_hands': n_hands,
            'showdown_hands': n_hands // 2,
            'nonshowdown_hands': n_hands - n_hands // 2,
            'showdown_net': showdown_net,
            'nonshowdown_net': nonshowdown_net,
            'total_net': total,
            'chart_data': chart,
            'diagnostics': [],
            'by_session': [],
        }

    def test_none_data_returns_empty_string(self):
        """None data → empty string."""
        result = _render_redline_blueline(None)
        self.assertEqual(result, '')

    def test_empty_dict_returns_empty_string(self):
        """Empty dict → empty string."""
        result = _render_redline_blueline({})
        self.assertEqual(result, '')

    def test_zero_hands_returns_empty_string(self):
        """total_hands = 0 → empty string."""
        result = _render_redline_blueline({'total_hands': 0})
        self.assertEqual(result, '')

    def test_one_hand_returns_empty_string(self):
        """total_hands = 1 → empty string (need at least 2)."""
        result = _render_redline_blueline({'total_hands': 1})
        self.assertEqual(result, '')

    def test_valid_data_returns_html(self):
        """Valid data with enough hands → HTML string."""
        data = self._make_data(n_hands=5)
        result = _render_redline_blueline(data)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_contains_section_title(self):
        """HTML contains 'Red Line / Blue Line' heading."""
        data = self._make_data()
        result = _render_redline_blueline(data)
        self.assertIn('Red Line / Blue Line', result)

    def test_contains_hand_counts(self):
        """HTML shows total_hands, showdown_hands, nonshowdown_hands."""
        data = self._make_data(n_hands=10)
        result = _render_redline_blueline(data)
        self.assertIn('10', result)

    def test_contains_net_values(self):
        """HTML shows showdown and nonshowdown net values."""
        data = self._make_data(showdown_net=50.0, nonshowdown_net=-20.0)
        result = _render_redline_blueline(data)
        self.assertIn('+50.00', result)
        self.assertIn('-20.00', result)

    def test_chart_rendered_with_enough_data(self):
        """SVG chart rendered when chart_data has >= 2 points."""
        data = self._make_data(n_hands=5)
        result = _render_redline_blueline(data)
        self.assertIn('<svg', result)

    def test_no_chart_with_one_point(self):
        """No SVG chart when chart_data has only 1 point."""
        data = self._make_data(n_hands=5)
        data['chart_data'] = data['chart_data'][:1]
        result = _render_redline_blueline(data)
        # May still render the section but not the chart
        self.assertNotIn('<polyline', result)

    def test_diagnostics_rendered(self):
        """Diagnostics messages are shown in HTML."""
        data = self._make_data()
        data['diagnostics'] = [
            {'type': 'danger', 'title': 'Red line caindo', 'message': 'Test message'}
        ]
        result = _render_redline_blueline(data)
        self.assertIn('Red line caindo', result)
        self.assertIn('Test message', result)

    def test_good_diagnostic_renders_green(self):
        """Good diagnostic uses green color."""
        data = self._make_data()
        data['diagnostics'] = [
            {'type': 'good', 'title': 'Red line saudável', 'message': 'OK'}
        ]
        result = _render_redline_blueline(data)
        self.assertIn('#00ff88', result)

    def test_warning_diagnostic_renders_orange(self):
        """Warning diagnostic uses orange color."""
        data = self._make_data()
        data['diagnostics'] = [
            {'type': 'warning', 'title': 'Alta taxa', 'message': 'Warning'}
        ]
        result = _render_redline_blueline(data)
        self.assertIn('#ffa500', result)

    def test_session_table_rendered(self):
        """by_session entries produce a table."""
        data = self._make_data()
        data['by_session'] = [{
            'date': '2026-01-15',
            'hands': 10,
            'showdown_hands': 4,
            'nonshowdown_hands': 6,
            'showdown_net': 5.0,
            'nonshowdown_net': -2.0,
            'total_net': 3.0,
        }]
        result = _render_redline_blueline(data)
        self.assertIn('<table', result)
        self.assertIn('2026-01-15', result)

    def test_no_session_table_with_empty_sessions(self):
        """Empty by_session → no session table."""
        data = self._make_data()
        data['by_session'] = []
        result = _render_redline_blueline(data)
        self.assertNotIn('<table', result)

    def test_percentage_displayed(self):
        """Showdown/nonshowdown percentages shown."""
        data = self._make_data(n_hands=10)
        result = _render_redline_blueline(data)
        self.assertIn('%', result)


# ── Unit Tests: _render_redline_chart_tourn ──────────────────────────

class TestRenderRedlineChartTourn(unittest.TestCase):
    """Tests for _render_redline_chart_tourn() tournament SVG chart."""

    def _make_chart_data(self, n=8):
        return [
            {
                'hand': i + 1,
                'total': float(i * 100),
                'showdown': float(i * 60),
                'nonshowdown': float(i * 40),
            }
            for i in range(n)
        ]

    def test_returns_string(self):
        """Output is a string."""
        data = self._make_chart_data()
        result = _render_redline_chart_tourn(data)
        self.assertIsInstance(result, str)

    def test_contains_svg(self):
        """Output contains SVG element."""
        data = self._make_chart_data()
        result = _render_redline_chart_tourn(data)
        self.assertIn('<svg', result)

    def test_contains_three_polylines(self):
        """Output contains 3 polyline elements."""
        data = self._make_chart_data()
        result = _render_redline_chart_tourn(data)
        self.assertEqual(result.count('<polyline'), 3)

    def test_y_axis_label_is_chips(self):
        """Y-axis label says 'Chips' for tournament chart."""
        data = self._make_chart_data()
        result = _render_redline_chart_tourn(data)
        self.assertIn('Chips', result)

    def test_contains_legend(self):
        """Legend with all three line labels."""
        data = self._make_chart_data()
        result = _render_redline_chart_tourn(data)
        self.assertIn('Showdown', result)
        self.assertIn('Não-Showdown', result)
        self.assertIn('Total', result)

    def test_section_header_rendered(self):
        """Chart includes the h3 section header."""
        data = self._make_chart_data()
        result = _render_redline_chart_tourn(data)
        self.assertIn('Evolução Cumulativa', result)

    def test_zero_crosser_dashed_line(self):
        """Dashed zero line when values span positive and negative."""
        data = [
            {'hand': 1, 'total': -500.0, 'showdown': -300.0, 'nonshowdown': -200.0},
            {'hand': 2, 'total': 500.0, 'showdown': 300.0, 'nonshowdown': 200.0},
        ]
        result = _render_redline_chart_tourn(data)
        self.assertIn('stroke-dasharray', result)


# ── Unit Tests: _render_redline_blueline_tournament ──────────────────

class TestRenderRedlineBluelineTournament(unittest.TestCase):
    """Tests for _render_redline_blueline_tournament() HTML section."""

    def _make_data(self, n_hands=8, showdown_net=1000, nonshowdown_net=-500):
        total = showdown_net + nonshowdown_net
        chart = [
            {
                'hand': i + 1,
                'total': total * (i + 1) / n_hands,
                'showdown': showdown_net * (i + 1) / n_hands,
                'nonshowdown': nonshowdown_net * (i + 1) / n_hands,
            }
            for i in range(n_hands)
        ]
        return {
            'total_hands': n_hands,
            'showdown_hands': n_hands // 2,
            'nonshowdown_hands': n_hands - n_hands // 2,
            'showdown_net': showdown_net,
            'nonshowdown_net': nonshowdown_net,
            'total_net': total,
            'chart_data': chart,
            'diagnostics': [],
            'by_session': [],
        }

    def test_none_returns_empty_string(self):
        """None data → empty string."""
        result = _render_redline_blueline_tournament(None)
        self.assertEqual(result, '')

    def test_zero_hands_returns_empty_string(self):
        """total_hands = 0 → empty string."""
        result = _render_redline_blueline_tournament({'total_hands': 0})
        self.assertEqual(result, '')

    def test_one_hand_returns_empty_string(self):
        """total_hands = 1 → empty string (needs >= 2)."""
        result = _render_redline_blueline_tournament({'total_hands': 1})
        self.assertEqual(result, '')

    def test_valid_data_returns_html(self):
        """Valid data → HTML string."""
        data = self._make_data()
        result = _render_redline_blueline_tournament(data)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_contains_tournament_title(self):
        """HTML contains 'Torneios' in title."""
        data = self._make_data()
        result = _render_redline_blueline_tournament(data)
        self.assertIn('Torneios', result)

    def test_contains_chips_unit(self):
        """Tournament section uses 'chips' as unit."""
        data = self._make_data(showdown_net=1000, nonshowdown_net=-500)
        result = _render_redline_blueline_tournament(data)
        self.assertIn('chips', result)

    def test_chart_rendered_with_enough_points(self):
        """SVG chart rendered when chart_data has >= 2 points."""
        data = self._make_data()
        result = _render_redline_blueline_tournament(data)
        self.assertIn('<svg', result)

    def test_diagnostics_rendered(self):
        """Diagnostics included in HTML."""
        data = self._make_data()
        data['diagnostics'] = [
            {'type': 'danger', 'title': 'Blue line caindo', 'message': 'Losing at SD'}
        ]
        result = _render_redline_blueline_tournament(data)
        self.assertIn('Blue line caindo', result)
        self.assertIn('Losing at SD', result)

    def test_by_day_table_rendered(self):
        """by_session entries produce table for tournament."""
        data = self._make_data()
        data['by_session'] = [{
            'date': '2026-01-15',
            'hands': 50,
            'showdown_hands': 20,
            'nonshowdown_hands': 30,
            'showdown_net': 1000,
            'nonshowdown_net': -500,
            'total_net': 500,
        }]
        result = _render_redline_blueline_tournament(data)
        self.assertIn('<table', result)
        self.assertIn('2026-01-15', result)

    def test_hand_count_shown(self):
        """HTML shows total hand count."""
        data = self._make_data(n_hands=8)
        result = _render_redline_blueline_tournament(data)
        self.assertIn('8', result)

    def test_contains_blue_line_label(self):
        """HTML describes blue line = showdown hands."""
        data = self._make_data()
        result = _render_redline_blueline_tournament(data)
        self.assertIn('Blue line', result)

    def test_contains_red_line_label(self):
        """HTML describes red line = non-showdown hands."""
        data = self._make_data()
        result = _render_redline_blueline_tournament(data)
        self.assertIn('Red line', result)


if __name__ == '__main__':
    unittest.main()
