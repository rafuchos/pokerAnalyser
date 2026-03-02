"""Tests for US-009: Decision-Tree EV Analysis.

Covers:
- EVAnalyzer.get_decision_ev_analysis(): full decision tree EV computation
- EVAnalyzer._identify_ev_leaks(): leak detection from context data
- EVAnalyzer._leak_description(): human-readable descriptions/suggestions
- EVAnalyzer._empty_decision_ev_result(): empty result structure
- Per-street EV breakdown (preflop, flop, turn, river)
- Fold/call/raise decision classification from action data
- Context detection (vs_bet vs initiative)
- Chart data for bar chart rendering
- Report rendering: _render_decision_ev_analysis, _render_decision_ev_chart
- Integration: actions + hands → decision EV → report
- Edge cases (no hands, no actions, insufficient data for leaks)
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.ev import EVAnalyzer


# ── Helpers ──────────────────────────────────────────────────────────

def _make_hand(hand_id, date='2026-01-15', hero_position='CO', **kwargs):
    """Create a HandData with sensible defaults for testing."""
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='cash',
        date=datetime.fromisoformat(f'{date}T20:00:00') if isinstance(date, str) else date,
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


def _make_action(hand_id, street, player, action_type, amount=0,
                 is_hero=False, sequence_order=0, position=None):
    """Create an ActionData with sensible defaults."""
    return ActionData(
        hand_id=hand_id,
        street=street,
        player=player,
        action_type=action_type,
        amount=amount,
        is_hero=1 if is_hero else 0,
        sequence_order=sequence_order,
        position=position,
        is_voluntary=1 if action_type in ('call', 'raise', 'bet') else 0,
    )


def _setup_db():
    """Create an in-memory DB with schema initialized."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Repository(conn)


def _insert_hand_with_actions(repo, conn, hand_id, net, actions_defs):
    """Insert a hand and its actions.

    actions_defs: list of (street, player, action_type, amount, is_hero, seq)
    """
    hand = _make_hand(hand_id, net=net, invested=abs(net) if net < 0 else 1.0,
                      won=max(0, net + 1.0))
    repo.insert_hand(hand)
    actions = []
    for street, player, atype, amount, is_hero, seq in actions_defs:
        actions.append(_make_action(
            hand_id, street, player, atype, amount, is_hero, seq))
    repo.insert_actions_batch(actions)
    return hand


# ── Empty/Edge Case Tests ────────────────────────────────────────────

class TestEmptyDecisionEVResult(unittest.TestCase):
    """Test _empty_decision_ev_result structure."""

    def test_empty_result_structure(self):
        result = EVAnalyzer._empty_decision_ev_result()
        self.assertEqual(result['total_hands'], 0)
        self.assertIn('preflop', result['by_street'])
        self.assertIn('flop', result['by_street'])
        self.assertIn('turn', result['by_street'])
        self.assertIn('river', result['by_street'])
        self.assertEqual(result['leaks'], [])
        self.assertEqual(result['chart_data'], [])

    def test_empty_street_has_fold_call_raise(self):
        result = EVAnalyzer._empty_decision_ev_result()
        for street in ('preflop', 'flop', 'turn', 'river'):
            for dec in ('fold', 'call', 'raise'):
                self.assertIn(dec, result['by_street'][street])
                self.assertEqual(result['by_street'][street][dec]['count'], 0)
                self.assertEqual(result['by_street'][street][dec]['total_net'], 0.0)
                self.assertEqual(result['by_street'][street][dec]['avg_net'], 0.0)


class TestDecisionEVNoData(unittest.TestCase):
    """Test get_decision_ev_analysis with no data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_empty_database(self):
        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_decision_ev_analysis()
        self.assertEqual(result['total_hands'], 0)
        self.assertEqual(result['leaks'], [])
        self.assertEqual(result['chart_data'], [])

    def test_hands_without_actions(self):
        """Hands exist but no actions → decision counts stay at 0."""
        for i in range(3):
            hand = _make_hand(f'H{i:03d}', net=1.0)
            self.repo.insert_hand(hand)
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_decision_ev_analysis()
        self.assertEqual(result['total_hands'], 3)
        total_decisions = sum(
            result['by_street'][st][dec]['count']
            for st in ('preflop', 'flop', 'turn', 'river')
            for dec in ('fold', 'call', 'raise')
        )
        self.assertEqual(total_decisions, 0)


# ── Decision Classification Tests ────────────────────────────────────

class TestDecisionClassification(unittest.TestCase):
    """Test how hero actions are classified into fold/call/raise."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_fold_classified_as_fold(self):
        _insert_hand_with_actions(self.repo, self.conn, 'H001', -0.50, [
            ('preflop', 'Villain', 'raise', 2.0, False, 1),
            ('preflop', 'Hero', 'fold', 0, True, 2),
        ])
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_decision_ev_analysis()
        self.assertEqual(result['by_street']['preflop']['fold']['count'], 1)
        self.assertEqual(result['by_street']['preflop']['call']['count'], 0)
        self.assertEqual(result['by_street']['preflop']['raise']['count'], 0)

    def test_call_classified_as_call(self):
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 2.0, [
            ('preflop', 'Villain', 'raise', 2.0, False, 1),
            ('preflop', 'Hero', 'call', 2.0, True, 2),
        ])
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_decision_ev_analysis()
        self.assertEqual(result['by_street']['preflop']['call']['count'], 1)

    def test_raise_classified_as_raise(self):
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Villain', 'raise', 2.0, False, 1),
            ('preflop', 'Hero', 'raise', 6.0, True, 2),
        ])
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_decision_ev_analysis()
        self.assertEqual(result['by_street']['preflop']['raise']['count'], 1)

    def test_bet_classified_as_raise(self):
        """A 'bet' action (initiative) is classified as raise."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 3.0, [
            ('flop', 'Hero', 'bet', 2.0, True, 1),
        ])
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_decision_ev_analysis()
        self.assertEqual(result['by_street']['flop']['raise']['count'], 1)

    def test_allin_classified_as_raise(self):
        """An 'all-in' action is classified as raise."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 50.0, [
            ('preflop', 'Hero', 'all-in', 50.0, True, 1),
        ])
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_decision_ev_analysis()
        self.assertEqual(result['by_street']['preflop']['raise']['count'], 1)

    def test_check_not_counted(self):
        """Check actions are skipped (not a fold/call/raise decision)."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 0.0, [
            ('flop', 'Hero', 'check', 0, True, 1),
            ('flop', 'Villain', 'check', 0, False, 2),
        ])
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_decision_ev_analysis()
        total = sum(
            result['by_street']['flop'][dec]['count']
            for dec in ('fold', 'call', 'raise')
        )
        self.assertEqual(total, 0)

    def test_post_blind_not_counted(self):
        """Blind posting actions are skipped."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', -0.50, [
            ('preflop', 'Hero', 'post_bb', 0.50, True, 1),
            ('preflop', 'Villain', 'raise', 2.0, False, 2),
            ('preflop', 'Hero', 'fold', 0, True, 3),
        ])
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_decision_ev_analysis()
        # Only the fold should be counted, not the post_bb
        self.assertEqual(result['by_street']['preflop']['fold']['count'], 1)


# ── Per-Street Breakdown Tests ───────────────────────────────────────

class TestPerStreetBreakdown(unittest.TestCase):
    """Test EV breakdown across different streets."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_preflop_fold(self):
        _insert_hand_with_actions(self.repo, self.conn, 'H001', -0.50, [
            ('preflop', 'Villain', 'raise', 2.0, False, 1),
            ('preflop', 'Hero', 'fold', 0, True, 2),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        self.assertEqual(result['by_street']['preflop']['fold']['count'], 1)
        self.assertAlmostEqual(
            result['by_street']['preflop']['fold']['avg_net'], -0.50)

    def test_flop_call(self):
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Villain', 'raise', 2.0, False, 1),
            ('preflop', 'Hero', 'call', 2.0, True, 2),
            ('flop', 'Villain', 'bet', 3.0, False, 3),
            ('flop', 'Hero', 'call', 3.0, True, 4),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        self.assertEqual(result['by_street']['flop']['call']['count'], 1)
        self.assertAlmostEqual(
            result['by_street']['flop']['call']['total_net'], 5.0)

    def test_turn_raise(self):
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 10.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
            ('flop', 'Hero', 'bet', 3.0, True, 2),
            ('turn', 'Villain', 'bet', 5.0, False, 3),
            ('turn', 'Hero', 'raise', 15.0, True, 4),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        self.assertEqual(result['by_street']['turn']['raise']['count'], 1)
        self.assertAlmostEqual(
            result['by_street']['turn']['raise']['avg_net'], 10.0)

    def test_river_fold(self):
        _insert_hand_with_actions(self.repo, self.conn, 'H001', -5.0, [
            ('preflop', 'Hero', 'call', 2.0, True, 1),
            ('flop', 'Hero', 'call', 3.0, True, 2),
            ('turn', 'Hero', 'call', 5.0, True, 3),
            ('river', 'Villain', 'bet', 10.0, False, 4),
            ('river', 'Hero', 'fold', 0, True, 5),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        self.assertEqual(result['by_street']['river']['fold']['count'], 1)

    def test_multiple_streets_same_hand(self):
        """Multiple streets in same hand each record a decision."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 8.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
            ('flop', 'Hero', 'bet', 3.0, True, 2),
            ('turn', 'Villain', 'bet', 5.0, False, 3),
            ('turn', 'Hero', 'call', 5.0, True, 4),
            ('river', 'Hero', 'bet', 10.0, True, 5),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        # preflop: raise, flop: bet→raise, turn: call, river: bet→raise
        self.assertEqual(result['by_street']['preflop']['raise']['count'], 1)
        self.assertEqual(result['by_street']['flop']['raise']['count'], 1)
        self.assertEqual(result['by_street']['turn']['call']['count'], 1)
        self.assertEqual(result['by_street']['river']['raise']['count'], 1)


# ── Net Accumulation Tests ────────────────────────────────────────────

class TestNetAccumulation(unittest.TestCase):
    """Test that net values accumulate correctly per decision type."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_multiple_fold_decisions(self):
        """Multiple folds sum their nets correctly."""
        for i in range(3):
            _insert_hand_with_actions(self.repo, self.conn, f'H{i:03d}', -1.0, [
                ('preflop', 'Villain', 'raise', 2.0, False, 1),
                ('preflop', 'Hero', 'fold', 0, True, 2),
            ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        fold_data = result['by_street']['preflop']['fold']
        self.assertEqual(fold_data['count'], 3)
        self.assertAlmostEqual(fold_data['total_net'], -3.0)
        self.assertAlmostEqual(fold_data['avg_net'], -1.0)

    def test_mixed_positive_negative(self):
        """Mix of winning and losing calls produces correct avg."""
        # Winning call
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 10.0, [
            ('flop', 'Villain', 'bet', 5.0, False, 1),
            ('flop', 'Hero', 'call', 5.0, True, 2),
        ])
        # Losing call
        _insert_hand_with_actions(self.repo, self.conn, 'H002', -6.0, [
            ('flop', 'Villain', 'bet', 5.0, False, 1),
            ('flop', 'Hero', 'call', 5.0, True, 2),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        call_data = result['by_street']['flop']['call']
        self.assertEqual(call_data['count'], 2)
        self.assertAlmostEqual(call_data['total_net'], 4.0)
        self.assertAlmostEqual(call_data['avg_net'], 2.0)


# ── Context Detection Tests ──────────────────────────────────────────

class TestContextDetection(unittest.TestCase):
    """Test vs_bet vs initiative context detection."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_fold_vs_bet(self):
        """Hero folds facing villain bet → vs_bet context."""
        for i in range(6):
            _insert_hand_with_actions(self.repo, self.conn, f'H{i:03d}', -1.0, [
                ('flop', 'Villain', 'bet', 3.0, False, 1),
                ('flop', 'Hero', 'fold', 0, True, 2),
            ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        # The leak detection needs count >= 5 and total_net < 0
        leaks = result['leaks']
        # Should detect fold vs bet on flop as a leak since total is -6.0
        fold_leak = [l for l in leaks if 'Fold' in l['description'] and 'Flop' in l['description']]
        self.assertGreater(len(fold_leak), 0)

    def test_raise_initiative(self):
        """Hero bets (no prior villain bet) → initiative context."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('flop', 'Hero', 'bet', 3.0, True, 1),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        self.assertEqual(result['by_street']['flop']['raise']['count'], 1)


# ── Leak Detection Tests ─────────────────────────────────────────────

class TestIdentifyEVLeaks(unittest.TestCase):
    """Test _identify_ev_leaks static method."""

    def test_no_leaks_when_all_positive(self):
        contexts = {
            'preflop_raise_initiative': {'count': 10, 'wins': 7, 'total_net': 20.0},
            'flop_call_vs_bet': {'count': 8, 'wins': 5, 'total_net': 10.0},
        }
        leaks = EVAnalyzer._identify_ev_leaks(contexts)
        self.assertEqual(len(leaks), 0)

    def test_no_leaks_when_count_below_minimum(self):
        """Contexts with fewer than 5 occurrences are not reported as leaks."""
        contexts = {
            'preflop_fold_vs_bet': {'count': 3, 'wins': 0, 'total_net': -10.0},
        }
        leaks = EVAnalyzer._identify_ev_leaks(contexts)
        self.assertEqual(len(leaks), 0)

    def test_single_leak_detected(self):
        contexts = {
            'flop_fold_vs_bet': {'count': 10, 'wins': 0, 'total_net': -15.0},
        }
        leaks = EVAnalyzer._identify_ev_leaks(contexts)
        self.assertEqual(len(leaks), 1)
        self.assertEqual(leaks[0]['count'], 10)
        self.assertAlmostEqual(leaks[0]['total_loss'], -15.0)
        self.assertAlmostEqual(leaks[0]['avg_loss'], -1.5)

    def test_leaks_sorted_by_total_loss(self):
        """Leaks sorted worst first (most negative total_net)."""
        contexts = {
            'flop_fold_vs_bet': {'count': 10, 'wins': 0, 'total_net': -10.0},
            'turn_call_vs_bet': {'count': 8, 'wins': 2, 'total_net': -25.0},
            'preflop_fold_vs_bet': {'count': 6, 'wins': 0, 'total_net': -5.0},
        }
        leaks = EVAnalyzer._identify_ev_leaks(contexts)
        self.assertEqual(len(leaks), 3)
        self.assertAlmostEqual(leaks[0]['total_loss'], -25.0)  # worst
        self.assertAlmostEqual(leaks[1]['total_loss'], -10.0)
        self.assertAlmostEqual(leaks[2]['total_loss'], -5.0)   # least bad

    def test_max_five_leaks(self):
        """At most 5 leaks are returned."""
        contexts = {}
        for i in range(8):
            contexts[f'flop_fold_vs{i}_bet'] = {
                'count': 10, 'wins': 0, 'total_net': -(i + 1) * 10.0,
            }
        # Invalid key format will be skipped (less than 3 parts)
        # But well-formed keys should work
        contexts_valid = {
            f'flop_fold_vs_bet{i}': {'count': 10, 'wins': 0, 'total_net': -(i + 1) * 5.0}
            for i in range(8)
        }
        # These have 3 parts when split by '_': flop, fold, vs -- but 'vs' isn't 'bet' or 'initiative'
        # Let's use valid format
        contexts_real = {}
        for i in range(8):
            street = ['preflop', 'flop', 'turn', 'river'][i % 4]
            decision = ['fold', 'call', 'raise'][i % 3]
            context_type = 'bet' if i % 2 == 0 else 'initiative'
            contexts_real[f'{street}_{decision}_{context_type}'] = {
                'count': 10, 'wins': 0, 'total_net': -(i + 1) * 5.0,
            }
        leaks = EVAnalyzer._identify_ev_leaks(contexts_real)
        self.assertLessEqual(len(leaks), 5)

    def test_leak_has_description_and_suggestion(self):
        contexts = {
            'flop_call_vs_bet': {'count': 10, 'wins': 2, 'total_net': -20.0},
        }
        leaks = EVAnalyzer._identify_ev_leaks(contexts)
        self.assertEqual(len(leaks), 1)
        self.assertIn('description', leaks[0])
        self.assertIn('suggestion', leaks[0])
        self.assertGreater(len(leaks[0]['description']), 0)
        self.assertGreater(len(leaks[0]['suggestion']), 0)


# ── Leak Description Tests ───────────────────────────────────────────

class TestLeakDescription(unittest.TestCase):
    """Test _leak_description for different decision/context combos."""

    def test_fold_vs_bet(self):
        desc, suggestion = EVAnalyzer._leak_description(
            'flop', 'fold', 'vs_bet', 10, 0.0, -15.0)
        self.assertIn('Fold', desc)
        self.assertIn('Flop', desc)
        self.assertIn('Defenda', suggestion)

    def test_call_vs_bet(self):
        desc, suggestion = EVAnalyzer._leak_description(
            'turn', 'call', 'vs_bet', 8, 25.0, -20.0)
        self.assertIn('Calls', desc)
        self.assertIn('Turn', desc)
        self.assertIn('25%', desc)  # win rate

    def test_raise_vs_bet(self):
        desc, suggestion = EVAnalyzer._leak_description(
            'river', 'raise', 'vs_bet', 5, 40.0, -10.0)
        self.assertIn('Raise', desc)
        self.assertIn('River', desc)

    def test_fold_initiative(self):
        desc, suggestion = EVAnalyzer._leak_description(
            'flop', 'fold', 'initiative', 12, 0.0, -8.0)
        self.assertIn('Check-fold', desc)
        self.assertIn('Flop', desc)

    def test_call_initiative(self):
        desc, suggestion = EVAnalyzer._leak_description(
            'preflop', 'call', 'initiative', 7, 28.0, -12.0)
        self.assertIn('Limp', desc)
        self.assertIn('Preflop', desc)

    def test_raise_initiative(self):
        desc, suggestion = EVAnalyzer._leak_description(
            'turn', 'raise', 'initiative', 6, 33.0, -9.0)
        self.assertIn('Bet/raise', desc)
        self.assertIn('Turn', desc)


# ── Chart Data Tests ─────────────────────────────────────────────────

class TestChartData(unittest.TestCase):
    """Test chart_data structure in decision EV result."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_chart_data_has_four_streets(self):
        """Chart data should have 4 entries (one per street)."""
        # Insert at least one hand with actions on each street
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
            ('flop', 'Hero', 'bet', 3.0, True, 2),
            ('turn', 'Hero', 'bet', 5.0, True, 3),
            ('river', 'Hero', 'bet', 10.0, True, 4),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        self.assertEqual(len(result['chart_data']), 4)
        streets = [d['street'] for d in result['chart_data']]
        self.assertEqual(streets, ['preflop', 'flop', 'turn', 'river'])

    def test_chart_data_has_avg_values(self):
        """Each chart entry has fold_avg, call_avg, raise_avg."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        for entry in result['chart_data']:
            self.assertIn('fold_avg', entry)
            self.assertIn('call_avg', entry)
            self.assertIn('raise_avg', entry)
            self.assertIn('street', entry)

    def test_chart_data_matches_by_street(self):
        """Chart data avg values should match by_street avg_net."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
        ])
        _insert_hand_with_actions(self.repo, self.conn, 'H002', -3.0, [
            ('preflop', 'Villain', 'raise', 2.0, False, 1),
            ('preflop', 'Hero', 'fold', 0, True, 2),
        ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        preflop_chart = result['chart_data'][0]
        preflop_street = result['by_street']['preflop']
        self.assertAlmostEqual(
            preflop_chart['fold_avg'],
            preflop_street['fold']['avg_net'])
        self.assertAlmostEqual(
            preflop_chart['raise_avg'],
            preflop_street['raise']['avg_net'])


# ── Full Integration Tests ───────────────────────────────────────────

class TestDecisionEVIntegration(unittest.TestCase):
    """Full integration: multiple hands with actions → decision EV analysis."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_realistic_session(self):
        """Simulate a short session with various decisions."""
        # Hand 1: Hero raises preflop, bets flop, wins
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 8.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
            ('preflop', 'Villain', 'call', 2.0, False, 2),
            ('flop', 'Hero', 'bet', 3.0, True, 3),
            ('flop', 'Villain', 'fold', 0, False, 4),
        ])

        # Hand 2: Hero calls preflop, folds flop
        _insert_hand_with_actions(self.repo, self.conn, 'H002', -2.0, [
            ('preflop', 'Villain', 'raise', 2.0, False, 1),
            ('preflop', 'Hero', 'call', 2.0, True, 2),
            ('flop', 'Villain', 'bet', 4.0, False, 3),
            ('flop', 'Hero', 'fold', 0, True, 4),
        ])

        # Hand 3: Hero folds preflop
        _insert_hand_with_actions(self.repo, self.conn, 'H003', -0.50, [
            ('preflop', 'Villain', 'raise', 2.0, False, 1),
            ('preflop', 'Hero', 'fold', 0, True, 2),
        ])

        # Hand 4: Hero 3-bets preflop, calls flop, raises turn, wins
        _insert_hand_with_actions(self.repo, self.conn, 'H004', 20.0, [
            ('preflop', 'Villain', 'raise', 2.0, False, 1),
            ('preflop', 'Hero', 'raise', 6.0, True, 2),
            ('preflop', 'Villain', 'call', 6.0, False, 3),
            ('flop', 'Villain', 'bet', 5.0, False, 4),
            ('flop', 'Hero', 'call', 5.0, True, 5),
            ('turn', 'Villain', 'bet', 10.0, False, 6),
            ('turn', 'Hero', 'raise', 30.0, True, 7),
        ])

        self.conn.commit()
        result = EVAnalyzer(self.repo).get_decision_ev_analysis()

        self.assertEqual(result['total_hands'], 4)

        # Preflop: H1=raise(+8), H2=call(-2), H3=fold(-0.50), H4=raise(+20)
        self.assertEqual(result['by_street']['preflop']['raise']['count'], 2)
        self.assertEqual(result['by_street']['preflop']['call']['count'], 1)
        self.assertEqual(result['by_street']['preflop']['fold']['count'], 1)

        # Flop: H1=bet→raise(+8), H2=fold(-2), H4=call(+20)
        self.assertEqual(result['by_street']['flop']['raise']['count'], 1)
        self.assertEqual(result['by_street']['flop']['fold']['count'], 1)
        self.assertEqual(result['by_street']['flop']['call']['count'], 1)

        # Turn: H4=raise(+20)
        self.assertEqual(result['by_street']['turn']['raise']['count'], 1)

        # Verify chart data
        self.assertEqual(len(result['chart_data']), 4)

    def test_only_non_hero_actions_ignored(self):
        """Villain-only actions produce no hero decision counts."""
        hand = _make_hand('H001', net=-0.50)
        self.repo.insert_hand(hand)
        # Only villain acts
        actions = [
            _make_action('H001', 'preflop', 'Villain', 'raise', 2.0, False, 1),
        ]
        self.repo.insert_actions_batch(actions)
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        total = sum(
            result['by_street']['preflop'][dec]['count']
            for dec in ('fold', 'call', 'raise')
        )
        self.assertEqual(total, 0)

    def test_avg_net_calculation(self):
        """Verify avg_net = total_net / count."""
        # 3 hands with same preflop raise, different net
        for i, net_val in enumerate([10.0, 5.0, -3.0]):
            _insert_hand_with_actions(self.repo, self.conn, f'H{i:03d}', net_val, [
                ('preflop', 'Hero', 'raise', 2.0, True, 1),
            ])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        raise_data = result['by_street']['preflop']['raise']
        self.assertEqual(raise_data['count'], 3)
        self.assertAlmostEqual(raise_data['total_net'], 12.0)
        self.assertAlmostEqual(raise_data['avg_net'], 4.0)


# ── Report Rendering Tests ───────────────────────────────────────────

class TestRenderDecisionEV(unittest.TestCase):
    """Test HTML report rendering for Decision-Tree EV section."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _generate_report_html(self):
        """Generate report HTML and return the content."""
        from src.analyzers.cash import CashAnalyzer
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os

        cash_analyzer = CashAnalyzer(self.repo)
        ev_analyzer = EVAnalyzer(self.repo)

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            tmpfile = f.name

        try:
            generate_cash_report(cash_analyzer, tmpfile, ev_analyzer=ev_analyzer)
            with open(tmpfile, 'r', encoding='utf-8') as f:
                return f.read()
        finally:
            os.unlink(tmpfile)

    def test_decision_ev_section_rendered(self):
        """Decision-Tree EV section appears when action data exists."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
            ('flop', 'Hero', 'bet', 3.0, True, 2),
        ])
        self.conn.commit()

        html = self._generate_report_html()
        self.assertIn('EV Completo - Decision Tree', html)
        self.assertIn('EV por Street', html)

    def test_street_table_in_report(self):
        """Per-street fold/call/raise table appears."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
        ])
        self.conn.commit()

        html = self._generate_report_html()
        self.assertIn('Preflop', html)
        self.assertIn('Flop', html)
        self.assertIn('Turn', html)
        self.assertIn('River', html)
        self.assertIn('Fold: Qtd', html)
        self.assertIn('Call: Qtd', html)
        self.assertIn('Raise: Qtd', html)

    def test_bar_chart_rendered(self):
        """Decision EV bar chart SVG appears."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
        ])
        self.conn.commit()

        html = self._generate_report_html()
        self.assertIn('EV Breakdown', html)
        self.assertIn('<svg', html)
        self.assertIn('rect', html)  # bar chart uses rect elements

    def test_leaks_rendered_when_present(self):
        """EV leaks section appears when leak data exists."""
        # Create enough hands to trigger leak detection
        for i in range(8):
            _insert_hand_with_actions(self.repo, self.conn, f'H{i:03d}', -3.0, [
                ('flop', 'Villain', 'bet', 5.0, False, 1),
                ('flop', 'Hero', 'call', 5.0, True, 2),
            ])
        self.conn.commit()

        html = self._generate_report_html()
        self.assertIn('Top EV Leaks', html)
        self.assertIn('leak-card', html)
        self.assertIn('leak-suggestion', html)

    def test_insufficient_data_message_when_no_leaks(self):
        """Shows 'insuficientes' message when not enough data for leaks."""
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
        ])
        self.conn.commit()

        html = self._generate_report_html()
        self.assertIn('insuficientes', html)

    def test_allin_subsection_rendered(self):
        """All-in EV sub-section appears when all-in hands exist."""
        # Hand with all-in and showdown
        h1 = _make_hand('H001', net=50.0, invested=50.0, won=100.0,
                         hero_cards='Ah Ad')
        self.repo.insert_hand(h1)
        self.repo.update_hand_board('H001', '2c 7s 9h', '3d', 'Ts')
        self.repo.update_hand_showdown(
            'H001', pot_total=100.0, opponent_cards='Kh Kd',
            has_allin=True, allin_street='river')
        # Add action so decision tree section renders
        actions = [
            _make_action('H001', 'preflop', 'Hero', 'raise', 50.0, True, 1),
        ]
        self.repo.insert_actions_batch(actions)
        self.conn.commit()

        html = self._generate_report_html()
        self.assertIn('EV Completo - Decision Tree', html)
        self.assertIn('All-in Sub-se', html)  # Sub-seção
        self.assertIn('bb/100 Real', html)

    def test_no_decision_ev_without_actions(self):
        """No decision EV section when there are no actions."""
        hand = _make_hand('H001', net=5.0)
        self.repo.insert_hand(hand)
        self.conn.commit()

        html = self._generate_report_html()
        self.assertNotIn('EV Completo - Decision Tree', html)


class TestRenderDecisionEVChart(unittest.TestCase):
    """Test _render_decision_ev_chart function."""

    def test_renders_svg(self):
        from src.reports.cash_report import _render_decision_ev_chart
        chart_data = [
            {'street': 'preflop', 'fold_avg': -1.0, 'call_avg': 0.5, 'raise_avg': 2.0},
            {'street': 'flop', 'fold_avg': -2.0, 'call_avg': 1.0, 'raise_avg': 3.0},
            {'street': 'turn', 'fold_avg': -1.5, 'call_avg': 0.0, 'raise_avg': 4.0},
            {'street': 'river', 'fold_avg': -3.0, 'call_avg': -0.5, 'raise_avg': 5.0},
        ]
        svg = _render_decision_ev_chart(chart_data)
        self.assertIn('<svg', svg)
        self.assertIn('rect', svg)  # bars
        self.assertIn('Pre', svg)   # street labels
        self.assertIn('Flop', svg)
        self.assertIn('Turn', svg)
        self.assertIn('River', svg)
        self.assertIn('Fold', svg)  # legend
        self.assertIn('Call', svg)
        self.assertIn('Raise', svg)

    def test_empty_chart_data(self):
        from src.reports.cash_report import _render_decision_ev_chart
        result = _render_decision_ev_chart([])
        self.assertEqual(result, '')

    def test_all_zero_values(self):
        from src.reports.cash_report import _render_decision_ev_chart
        chart_data = [
            {'street': 'preflop', 'fold_avg': 0.0, 'call_avg': 0.0, 'raise_avg': 0.0},
        ]
        svg = _render_decision_ev_chart(chart_data)
        self.assertIn('<svg', svg)


class TestRenderDecisionEVAnalysis(unittest.TestCase):
    """Test _render_decision_ev_analysis function."""

    def test_renders_table_and_chart(self):
        from src.reports.cash_report import _render_decision_ev_analysis
        decision_ev = {
            'total_hands': 50,
            'by_street': {
                'preflop': {
                    'fold': {'count': 10, 'total_net': -5.0, 'avg_net': -0.5},
                    'call': {'count': 15, 'total_net': 8.0, 'avg_net': 0.53},
                    'raise': {'count': 12, 'total_net': 20.0, 'avg_net': 1.67},
                },
                'flop': {
                    'fold': {'count': 5, 'total_net': -3.0, 'avg_net': -0.6},
                    'call': {'count': 4, 'total_net': 2.0, 'avg_net': 0.5},
                    'raise': {'count': 3, 'total_net': 6.0, 'avg_net': 2.0},
                },
                'turn': {
                    'fold': {'count': 2, 'total_net': -1.0, 'avg_net': -0.5},
                    'call': {'count': 2, 'total_net': 3.0, 'avg_net': 1.5},
                    'raise': {'count': 1, 'total_net': 5.0, 'avg_net': 5.0},
                },
                'river': {
                    'fold': {'count': 1, 'total_net': -2.0, 'avg_net': -2.0},
                    'call': {'count': 1, 'total_net': 1.0, 'avg_net': 1.0},
                    'raise': {'count': 0, 'total_net': 0.0, 'avg_net': 0.0},
                },
            },
            'leaks': [
                {
                    'description': 'Fold excessivo vs bet no Flop (10 vezes)',
                    'count': 10,
                    'total_loss': -15.0,
                    'avg_loss': -1.5,
                    'suggestion': 'Defenda mais vs bets no Flop',
                },
            ],
            'chart_data': [
                {'street': 'preflop', 'fold_avg': -0.5, 'call_avg': 0.53, 'raise_avg': 1.67},
                {'street': 'flop', 'fold_avg': -0.6, 'call_avg': 0.5, 'raise_avg': 2.0},
                {'street': 'turn', 'fold_avg': -0.5, 'call_avg': 1.5, 'raise_avg': 5.0},
                {'street': 'river', 'fold_avg': -2.0, 'call_avg': 1.0, 'raise_avg': 0.0},
            ],
        }
        html = _render_decision_ev_analysis(decision_ev)
        self.assertIn('EV Completo - Decision Tree', html)
        self.assertIn('Preflop', html)
        self.assertIn('Fold: Qtd', html)
        self.assertIn('leak-card', html)
        self.assertIn('<svg', html)  # bar chart

    def test_renders_without_leaks(self):
        from src.reports.cash_report import _render_decision_ev_analysis
        decision_ev = {
            'total_hands': 10,
            'by_street': {
                st: {dec: {'count': 0, 'total_net': 0.0, 'avg_net': 0.0}
                     for dec in ('fold', 'call', 'raise')}
                for st in ('preflop', 'flop', 'turn', 'river')
            },
            'leaks': [],
            'chart_data': [],
        }
        html = _render_decision_ev_analysis(decision_ev)
        self.assertIn('insuficientes', html)
        self.assertNotIn('leak-card', html)

    def test_renders_with_allin_subsection(self):
        from src.reports.cash_report import _render_decision_ev_analysis
        decision_ev = {
            'total_hands': 10,
            'by_street': {
                st: {dec: {'count': 1, 'total_net': 1.0, 'avg_net': 1.0}
                     for dec in ('fold', 'call', 'raise')}
                for st in ('preflop', 'flop', 'turn', 'river')
            },
            'leaks': [],
            'chart_data': [
                {'street': st, 'fold_avg': 1.0, 'call_avg': 1.0, 'raise_avg': 1.0}
                for st in ('preflop', 'flop', 'turn', 'river')
            ],
        }
        allin_ev = {
            'overall': {
                'total_hands': 10, 'allin_hands': 2,
                'real_net': 30.0, 'ev_net': 25.0,
                'luck_factor': 5.0,
                'bb100_real': 60.0, 'bb100_ev': 50.0,
            },
            'by_stakes': {},
            'chart_data': [
                {'hand': 1, 'real': 0, 'ev': 0},
                {'hand': 2, 'real': 30, 'ev': 25},
            ],
        }
        html = _render_decision_ev_analysis(decision_ev, allin_ev)
        self.assertIn('All-in Sub-se', html)
        self.assertIn('bb/100 Real', html)
        self.assertIn('bb/100 EV-Adjusted', html)


# ── Tournament Exclusion Tests ────────────────────────────────────────

class TestTournamentExclusion(unittest.TestCase):
    """Verify that tournament hands don't appear in cash decision EV."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_tournament_hands_excluded(self):
        """Tournament hands should not be counted in decision EV."""
        # Cash hand
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
        ])

        # Tournament hand (inserted directly into DB)
        t_hand = HandData(
            hand_id='T001', platform='GGPoker', game_type='tournament',
            date=datetime.fromisoformat('2026-01-15T20:00:00'),
            blinds_sb=10, blinds_bb=20, hero_cards='Ah Kd',
            hero_position='CO', invested=20, won=0, net=-20,
            rake=0, table_name='T', num_players=6,
            tournament_id='TOUR1',
        )
        self.repo.insert_hand(t_hand)
        # Tournament action
        t_action = _make_action('T001', 'preflop', 'Hero', 'raise', 60, True, 1)
        self.repo.insert_actions_batch([t_action])
        self.conn.commit()

        result = EVAnalyzer(self.repo).get_decision_ev_analysis()
        # get_all_action_sequences only returns cash hands
        # get_cash_hands only returns cash hands
        self.assertEqual(result['total_hands'], 1)
        self.assertEqual(result['by_street']['preflop']['raise']['count'], 1)


# ── Year Filtering Tests ─────────────────────────────────────────────

class TestYearFiltering(unittest.TestCase):
    """Test that year filtering works for decision EV analysis."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_filters_by_year(self):
        # 2026 hand
        _insert_hand_with_actions(self.repo, self.conn, 'H001', 5.0, [
            ('preflop', 'Hero', 'raise', 2.0, True, 1),
        ])
        # 2025 hand
        h2 = _make_hand('H002', date='2025-06-15', net=-3.0)
        self.repo.insert_hand(h2)
        a2 = _make_action('H002', 'preflop', 'Hero', 'fold', 0, True, 1)
        self.repo.insert_actions_batch([a2])
        self.conn.commit()

        # Default year='2026' should only see 1 hand
        analyzer = EVAnalyzer(self.repo, year='2026')
        result = analyzer.get_decision_ev_analysis()
        self.assertEqual(result['total_hands'], 1)
        self.assertEqual(result['by_street']['preflop']['raise']['count'], 1)
        self.assertEqual(result['by_street']['preflop']['fold']['count'], 0)


if __name__ == '__main__':
    unittest.main()
