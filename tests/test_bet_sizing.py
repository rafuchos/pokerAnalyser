"""Tests for US-013: Bet Sizing & Pot-Type Segmentation.

Covers:
- _classify_pot_type: pot type classification (limped, srp, 3bet, 4bet+)
- _count_active_players: non-folded preflop player count
- _compute_bet_sizing: hero preflop raise and postflop bet sizing
- _empty_pt_acc / _accumulate_pt / _format_pt_stats: accumulator helpers
- _classify_winrate_health: health badge logic
- _median / _size_distribution / _format_sizing_data: sizing stats helpers
- _generate_bet_sizing_diagnostics: automatic diagnostics
- CashAnalyzer.get_bet_sizing_analysis: integration method
- Report: _render_bet_sizing_analysis (HTML section)
- Edge cases: empty DB, too few hands, no raises, all same sizing
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import (
    CashAnalyzer,
    _classify_pot_type,
    _count_active_players,
    _compute_bet_sizing,
    _empty_pt_acc,
    _accumulate_pt,
    _format_pt_stats,
    _classify_winrate_health,
    _median,
    _size_distribution,
    _format_sizing_data,
    _generate_bet_sizing_diagnostics,
    _PREFLOP_BUCKETS,
    _POSTFLOP_BUCKETS,
)
from src.reports.cash_report import _render_bet_sizing_analysis


# ── Helpers ──────────────────────────────────────────────────────────────────

def _setup_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Repository(conn)


def _make_hand(hand_id, date='2026-01-15T20:00:00', hero_position='CO',
               net=-0.5, blinds_bb=0.5, num_players=6, **kwargs):
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='cash',
        date=datetime.fromisoformat(date),
        blinds_sb=kwargs.get('blinds_sb', 0.25),
        blinds_bb=blinds_bb,
        hero_cards=kwargs.get('hero_cards', 'Ah Kd'),
        hero_position=hero_position,
        invested=kwargs.get('invested', 1.0),
        won=kwargs.get('won', 0.0),
        net=net,
        rake=0.0,
        table_name='T',
        num_players=num_players,
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


# ── Unit tests: _classify_pot_type ────────────────────────────────────────────

class TestClassifyPotType(unittest.TestCase):

    def _actions(self, types):
        return [{'action_type': t, 'player': f'p{i}'} for i, t in enumerate(types)]

    def test_limped_all_calls(self):
        actions = self._actions(['post_sb', 'post_bb', 'call', 'call'])
        self.assertEqual(_classify_pot_type(actions), 'limped')

    def test_limped_no_actions(self):
        self.assertEqual(_classify_pot_type([]), 'limped')

    def test_srp_one_raise(self):
        actions = self._actions(['post_sb', 'post_bb', 'raise', 'fold', 'fold'])
        self.assertEqual(_classify_pot_type(actions), 'srp')

    def test_srp_one_bet(self):
        actions = self._actions(['post_sb', 'post_bb', 'bet', 'call'])
        self.assertEqual(_classify_pot_type(actions), 'srp')

    def test_3bet_two_raises(self):
        actions = self._actions(['post_sb', 'post_bb', 'raise', 'raise', 'fold'])
        self.assertEqual(_classify_pot_type(actions), '3bet')

    def test_4bet_three_raises(self):
        actions = self._actions(['post_sb', 'post_bb', 'raise', 'raise', 'raise', 'call'])
        self.assertEqual(_classify_pot_type(actions), '4bet_plus')

    def test_4bet_four_raises(self):
        actions = self._actions(['raise', 'raise', 'raise', 'raise'])
        self.assertEqual(_classify_pot_type(actions), '4bet_plus')

    def test_allin_counts_as_raise(self):
        actions = self._actions(['post_bb', 'all-in', 'call'])
        self.assertEqual(_classify_pot_type(actions), 'srp')

    def test_posts_not_counted(self):
        # Only posts, no raises
        actions = self._actions(['post_sb', 'post_bb', 'post_ante'])
        self.assertEqual(_classify_pot_type(actions), 'limped')


# ── Unit tests: _count_active_players ────────────────────────────────────────

class TestCountActivePlayers(unittest.TestCase):

    def test_two_players_no_folds(self):
        actions = [
            {'player': 'Hero', 'action_type': 'raise'},
            {'player': 'Villain', 'action_type': 'call'},
        ]
        self.assertEqual(_count_active_players(actions), 2)

    def test_one_folds(self):
        actions = [
            {'player': 'Hero', 'action_type': 'raise'},
            {'player': 'V1', 'action_type': 'fold'},
            {'player': 'V2', 'action_type': 'call'},
        ]
        self.assertEqual(_count_active_players(actions), 2)

    def test_all_fold_except_hero(self):
        actions = [
            {'player': 'Hero', 'action_type': 'raise'},
            {'player': 'V1', 'action_type': 'fold'},
        ]
        self.assertEqual(_count_active_players(actions), 1)

    def test_empty(self):
        self.assertEqual(_count_active_players([]), 0)

    def test_multiway(self):
        actions = [
            {'player': 'A', 'action_type': 'call'},
            {'player': 'B', 'action_type': 'call'},
            {'player': 'C', 'action_type': 'call'},
        ]
        self.assertEqual(_count_active_players(actions), 3)


# ── Unit tests: _compute_bet_sizing ──────────────────────────────────────────

class TestComputeBetSizing(unittest.TestCase):

    def _a(self, street, atype, amount, is_hero=0, seq=0):
        return {
            'street': street,
            'action_type': atype,
            'amount': amount,
            'is_hero': is_hero,
            'sequence_order': seq,
        }

    def test_preflop_raise_bb(self):
        actions = [
            self._a('preflop', 'post_sb', 0.25, seq=0),
            self._a('preflop', 'post_bb', 0.50, seq=1),
            self._a('preflop', 'raise', 1.5, is_hero=1, seq=2),
        ]
        result = _compute_bet_sizing(actions, blinds_bb=0.5)
        self.assertAlmostEqual(result['preflop_raise_bb'], 3.0)  # 1.5 / 0.5

    def test_preflop_raise_only_first(self):
        """Only captures first hero raise."""
        actions = [
            self._a('preflop', 'raise', 1.5, is_hero=1, seq=0),
            self._a('preflop', 'raise', 4.0, is_hero=1, seq=1),  # 4-bet
        ]
        result = _compute_bet_sizing(actions, blinds_bb=0.5)
        self.assertAlmostEqual(result['preflop_raise_bb'], 3.0)  # only first

    def test_no_preflop_raise(self):
        actions = [
            self._a('preflop', 'call', 0.5, is_hero=1),
        ]
        result = _compute_bet_sizing(actions, blinds_bb=0.5)
        self.assertIsNone(result['preflop_raise_bb'])

    def test_flop_bet_pct(self):
        """Hero bets 1.0 into pot of 2.0 → 50%."""
        actions = [
            self._a('preflop', 'post_sb', 0.25, seq=0),
            self._a('preflop', 'post_bb', 0.50, seq=1),
            self._a('preflop', 'raise', 1.5, seq=2),
            self._a('preflop', 'call', 1.5, seq=3),  # pot = 3.25
            self._a('flop', 'bet', 1.0, is_hero=1, seq=4),  # pot before = 3.25
        ]
        result = _compute_bet_sizing(actions, blinds_bb=0.5)
        # running_pot before flop bet = 0.25 + 0.50 + 1.5 + 1.5 = 3.75
        self.assertAlmostEqual(result['flop_bet_pct'], round(1.0 / 3.75 * 100, 1))

    def test_flop_only_first_bet(self):
        """Only the first hero bet per street is captured."""
        actions = [
            self._a('preflop', 'post_bb', 0.5, seq=0),
            self._a('flop', 'bet', 1.0, is_hero=1, seq=1),
            self._a('flop', 'bet', 2.0, is_hero=1, seq=2),  # second bet ignored
        ]
        result = _compute_bet_sizing(actions, blinds_bb=0.5)
        self.assertAlmostEqual(result['flop_bet_pct'], round(1.0 / 0.5 * 100, 1))

    def test_no_flop_bet_returns_none(self):
        actions = [
            self._a('flop', 'check', 0, is_hero=1),
        ]
        result = _compute_bet_sizing(actions, blinds_bb=0.5)
        self.assertIsNone(result['flop_bet_pct'])

    def test_zero_pot_flop_ignored(self):
        """Hero bet with zero accumulated pot is ignored."""
        actions = [
            self._a('flop', 'bet', 1.0, is_hero=1),  # running_pot = 0 here
        ]
        result = _compute_bet_sizing(actions, blinds_bb=0.5)
        self.assertIsNone(result['flop_bet_pct'])

    def test_turn_and_river(self):
        actions = [
            self._a('preflop', 'post_bb', 1.0, seq=0),
            self._a('flop', 'check', 0, is_hero=1, seq=1),
            self._a('turn', 'bet', 0.5, is_hero=1, seq=2),
            self._a('river', 'bet', 1.0, is_hero=1, seq=3),
        ]
        result = _compute_bet_sizing(actions, blinds_bb=1.0)
        self.assertAlmostEqual(result['turn_bet_pct'], round(0.5 / 1.0 * 100, 1))
        self.assertAlmostEqual(result['river_bet_pct'], round(1.0 / 1.5 * 100, 1))


# ── Unit tests: accumulator helpers ──────────────────────────────────────────

class TestAccumulator(unittest.TestCase):

    def _post_result(self):
        return {
            'saw_flop': False, 'went_to_showdown': False, 'won_at_showdown': False,
            'cbet_opp': False, 'cbet': False,
            'fold_to_cbet_opp': False, 'fold_to_cbet': False,
            'hero_aggression': {}, 'check_raise': {},
        }

    def test_empty_accumulator(self):
        acc = _empty_pt_acc()
        self.assertEqual(acc['hands'], 0)
        self.assertEqual(acc['net'], 0.0)

    def test_accumulate_basic(self):
        acc = _empty_pt_acc()
        pf_pre = {'vpip': True, 'pfr': True, 'three_bet_opp': False, 'three_bet': False,
                  'fold_3bet_opp': False, 'fold_3bet': False, 'ats_opp': False, 'ats': False}
        pf_post = self._post_result()
        _accumulate_pt(acc, net=5.0, blinds_bb=0.5, is_hu=True, pf_pre=pf_pre, pf_post=pf_post)
        self.assertEqual(acc['hands'], 1)
        self.assertEqual(acc['hu_hands'], 1)
        self.assertEqual(acc['multiway_hands'], 0)
        self.assertAlmostEqual(acc['net'], 5.0)
        self.assertAlmostEqual(acc['net_bb'], 10.0)
        self.assertEqual(acc['vpip'], 1)
        self.assertEqual(acc['pfr'], 1)

    def test_accumulate_multiway(self):
        acc = _empty_pt_acc()
        pf_pre = {k: False for k in ('vpip', 'pfr', 'three_bet_opp', 'three_bet',
                                      'fold_3bet_opp', 'fold_3bet', 'ats_opp', 'ats')}
        pf_post = self._post_result()
        _accumulate_pt(acc, net=-1.0, blinds_bb=0.5, is_hu=False, pf_pre=pf_pre, pf_post=pf_post)
        self.assertEqual(acc['hu_hands'], 0)
        self.assertEqual(acc['multiway_hands'], 1)

    def test_accumulate_postflop_stats(self):
        acc = _empty_pt_acc()
        pf_pre = {k: False for k in ('vpip', 'pfr', 'three_bet_opp', 'three_bet',
                                      'fold_3bet_opp', 'fold_3bet', 'ats_opp', 'ats')}
        pf_post = self._post_result()
        pf_post['saw_flop'] = True
        pf_post['cbet_opp'] = True
        pf_post['cbet'] = True
        pf_post['went_to_showdown'] = True
        pf_post['won_at_showdown'] = True
        pf_post['hero_aggression'] = {'flop': {'bets': 1, 'raises': 0, 'calls': 1, 'folds': 0}}
        _accumulate_pt(acc, net=2.0, blinds_bb=0.5, is_hu=True, pf_pre=pf_pre, pf_post=pf_post)
        self.assertEqual(acc['saw_flop'], 1)
        self.assertEqual(acc['cbet_opps'], 1)
        self.assertEqual(acc['cbet'], 1)
        self.assertEqual(acc['wtsd'], 1)
        self.assertEqual(acc['wsd'], 1)
        self.assertEqual(acc['agg_br'], 1)
        self.assertEqual(acc['agg_calls'], 1)

    def test_format_empty(self):
        acc = _empty_pt_acc()
        result = _format_pt_stats(acc)
        self.assertEqual(result['hands'], 0)
        self.assertEqual(result['vpip'], 0.0)
        self.assertEqual(result['health'], 'good')

    def test_format_basic(self):
        acc = _empty_pt_acc()
        # 2 hands, +10 net, vpip=1, pfr=1
        pf_pre = {'vpip': True, 'pfr': True, 'three_bet_opp': False, 'three_bet': False,
                  'fold_3bet_opp': False, 'fold_3bet': False, 'ats_opp': False, 'ats': False}
        pf_post = {'saw_flop': False, 'went_to_showdown': False, 'won_at_showdown': False,
                   'cbet_opp': False, 'cbet': False, 'fold_to_cbet_opp': False,
                   'fold_to_cbet': False, 'hero_aggression': {}, 'check_raise': {}}
        _accumulate_pt(acc, net=10.0, blinds_bb=1.0, is_hu=True, pf_pre=pf_pre, pf_post=pf_post)
        _accumulate_pt(acc, net=-2.0, blinds_bb=1.0, is_hu=False,
                       pf_pre={k: False for k in pf_pre}, pf_post=pf_post)
        result = _format_pt_stats(acc)
        self.assertEqual(result['hands'], 2)
        self.assertEqual(result['vpip'], 50.0)
        self.assertEqual(result['pfr'], 50.0)
        self.assertAlmostEqual(result['win_rate_bb100'], 400.0)  # 8 net_bb / 2 * 100

    def test_format_af_no_calls(self):
        """AF when no calls: equals number of bets/raises."""
        acc = _empty_pt_acc()
        acc['hands'] = 1
        acc['agg_br'] = 3
        acc['agg_calls'] = 0
        result = _format_pt_stats(acc)
        self.assertEqual(result['af'], 3.0)


# ── Unit tests: _classify_winrate_health ─────────────────────────────────────

class TestClassifyWinrateHealth(unittest.TestCase):

    def test_positive_is_good(self):
        self.assertEqual(_classify_winrate_health(10.0), 'good')

    def test_zero_is_good(self):
        self.assertEqual(_classify_winrate_health(0.0), 'good')

    def test_small_negative_is_warning(self):
        self.assertEqual(_classify_winrate_health(-3.0), 'warning')

    def test_boundary_warning(self):
        self.assertEqual(_classify_winrate_health(-5.0), 'warning')

    def test_large_negative_is_danger(self):
        self.assertEqual(_classify_winrate_health(-10.0), 'danger')


# ── Unit tests: _median ───────────────────────────────────────────────────────

class TestMedian(unittest.TestCase):

    def test_odd_length(self):
        self.assertEqual(_median([1, 2, 3]), 2)

    def test_even_length(self):
        self.assertEqual(_median([1, 2, 3, 4]), 2.5)

    def test_single(self):
        self.assertEqual(_median([5.0]), 5.0)

    def test_unsorted(self):
        self.assertEqual(_median([3, 1, 2]), 2)


# ── Unit tests: _size_distribution ───────────────────────────────────────────

class TestSizeDistribution(unittest.TestCase):

    def test_preflop_buckets(self):
        sizes = [1.5, 2.2, 2.8, 3.5, 5.0]
        dist = _size_distribution(sizes, _PREFLOP_BUCKETS)
        self.assertEqual(len(dist), 5)
        labels = [d['label'] for d in dist]
        self.assertEqual(labels, ['<2x', '2-2.5x', '2.5-3x', '3-4x', '>4x'])
        counts = [d['count'] for d in dist]
        self.assertEqual(counts, [1, 1, 1, 1, 1])

    def test_postflop_buckets(self):
        sizes = [20, 33, 66, 90, 110]
        dist = _size_distribution(sizes, _POSTFLOP_BUCKETS)
        labels = [d['label'] for d in dist]
        self.assertEqual(labels, ['<25%', '25-50%', '50-75%', '75-100%', '>100%'])
        counts = [d['count'] for d in dist]
        self.assertEqual(counts, [1, 1, 1, 1, 1])

    def test_pct_sums_to_100(self):
        sizes = [1.5, 2.0, 2.5, 3.0, 4.5]
        dist = _size_distribution(sizes, _PREFLOP_BUCKETS)
        total_pct = sum(d['pct'] for d in dist)
        self.assertAlmostEqual(total_pct, 100.0, places=0)

    def test_empty_sizes(self):
        dist = _size_distribution([], _PREFLOP_BUCKETS)
        for b in dist:
            self.assertEqual(b['count'], 0)
            self.assertEqual(b['pct'], 0.0)


# ── Unit tests: _format_sizing_data ──────────────────────────────────────────

class TestFormatSizingData(unittest.TestCase):

    def test_empty(self):
        result = _format_sizing_data([], _PREFLOP_BUCKETS)
        self.assertEqual(result['samples'], 0)
        self.assertEqual(result['avg'], 0.0)
        self.assertEqual(result['median'], 0.0)
        self.assertEqual(result['distribution'], [])

    def test_basic_stats(self):
        sizes = [2.0, 3.0, 4.0]
        result = _format_sizing_data(sizes, _PREFLOP_BUCKETS)
        self.assertEqual(result['samples'], 3)
        self.assertAlmostEqual(result['avg'], 3.0)
        self.assertAlmostEqual(result['median'], 3.0)
        self.assertEqual(len(result['distribution']), 5)


# ── Unit tests: _generate_bet_sizing_diagnostics ─────────────────────────────

class TestGenerateDiagnostics(unittest.TestCase):

    def test_too_few_hands(self):
        result = _generate_bet_sizing_diagnostics({}, [], total_hands=10)
        self.assertEqual(result, [])

    def test_uniform_sizing_warning(self):
        # All same size → very low CV
        sizes = [3.0] * 15
        result = _generate_bet_sizing_diagnostics({}, sizes, total_hands=50)
        titles = [d['title'] for d in result]
        self.assertIn('Sizing preflop uniforme', titles)

    def test_varied_sizing_no_warning(self):
        # High variance: no uniformity warning
        sizes = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 2.2, 3.3, 1.8, 4.5, 2.7, 3.1]
        result = _generate_bet_sizing_diagnostics({}, sizes, total_hands=50)
        titles = [d['title'] for d in result]
        self.assertNotIn('Sizing preflop uniforme', titles)

    def test_danger_win_rate(self):
        pot_types = {
            'srp': {'hands': 30, 'win_rate_bb100': -20.0, 'health': 'danger'},
        }
        result = _generate_bet_sizing_diagnostics(pot_types, [], total_hands=50)
        titles = [d['title'] for d in result]
        self.assertIn('Perda significativa em potes SRP', titles)
        danger = [d for d in result if 'Perda significativa em potes SRP' in d['title']][0]
        self.assertEqual(danger['type'], 'danger')

    def test_warning_win_rate(self):
        pot_types = {
            'limped': {'hands': 25, 'win_rate_bb100': -8.0, 'health': 'warning'},
        }
        result = _generate_bet_sizing_diagnostics(pot_types, [], total_hands=50)
        titles = [d['title'] for d in result]
        self.assertIn('Win rate negativo em potes Limped', titles)

    def test_good_win_rate(self):
        pot_types = {
            '3bet': {'hands': 25, 'win_rate_bb100': 25.0, 'health': 'good'},
        }
        result = _generate_bet_sizing_diagnostics(pot_types, [], total_hands=50)
        titles = [d['title'] for d in result]
        self.assertIn('Forte em potes 3-bet', titles)
        good = [d for d in result if 'Forte em potes 3-bet' in d['title']][0]
        self.assertEqual(good['type'], 'good')

    def test_too_few_hands_in_pot_type_ignored(self):
        pot_types = {
            '4bet_plus': {'hands': 5, 'win_rate_bb100': -30.0},  # too few
        }
        result = _generate_bet_sizing_diagnostics(pot_types, [], total_hands=50)
        self.assertEqual(result, [])


# ── Integration tests: CashAnalyzer.get_bet_sizing_analysis ──────────────────

def _insert_hand_with_actions(repo, hand_id, net, blinds_bb, actions_spec,
                               date='2026-01-15T20:00:00'):
    """Helper to insert a hand and its actions."""
    hand = _make_hand(hand_id, date=date, net=net, blinds_bb=blinds_bb)
    repo.insert_hand(hand)
    actions = []
    for i, (street, player, atype, amount, is_hero) in enumerate(actions_spec):
        actions.append(_make_action(
            hand_id, player, atype, seq=i, street=street,
            is_hero=is_hero, amount=amount,
            is_voluntary=1 if atype in ('call', 'raise', 'bet') else 0,
        ))
    repo.insert_actions_batch(actions)


class TestGetBetSizingAnalysisEmpty(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_empty_db(self):
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['total_hands'], 0)
        for key in ('limped', 'srp', '3bet', '4bet_plus'):
            self.assertEqual(result['pot_types'][key]['hands'], 0)
        for street in ('preflop', 'flop', 'turn', 'river'):
            self.assertEqual(result['sizing'][street]['samples'], 0)
        self.assertEqual(result['hu_vs_multiway']['heads_up']['hands'], 0)
        self.assertEqual(result['hu_vs_multiway']['multiway']['hands'], 0)
        self.assertEqual(result['diagnostics'], [])


class TestGetBetSizingAnalysisPotTypes(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_limped_hand(self):
        """Hand with only calls preflop → limped."""
        _insert_hand_with_actions(self.repo, 'H1', net=1.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'SB', 'post_sb', 0.25, 0),
            ('preflop', 'BB', 'post_bb', 0.50, 0),
            ('preflop', 'Hero', 'call', 0.50, 1),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['total_hands'], 1)
        self.assertEqual(result['pot_types']['limped']['hands'], 1)
        self.assertEqual(result['pot_types']['srp']['hands'], 0)

    def test_srp_hand(self):
        """Hand with one raise preflop → SRP."""
        _insert_hand_with_actions(self.repo, 'H1', net=-1.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'SB', 'post_sb', 0.25, 0),
            ('preflop', 'BB', 'post_bb', 0.50, 0),
            ('preflop', 'Hero', 'raise', 1.5, 1),
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['pot_types']['srp']['hands'], 1)
        self.assertEqual(result['pot_types']['limped']['hands'], 0)

    def test_3bet_hand(self):
        """Hand with two raises preflop → 3-bet pot."""
        _insert_hand_with_actions(self.repo, 'H1', net=-3.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'SB', 'post_sb', 0.25, 0),
            ('preflop', 'BB', 'post_bb', 0.50, 0),
            ('preflop', 'V1', 'raise', 1.5, 0),
            ('preflop', 'Hero', 'raise', 5.0, 1),
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['pot_types']['3bet']['hands'], 1)

    def test_4bet_hand(self):
        """Hand with three raises preflop → 4-bet+ pot."""
        _insert_hand_with_actions(self.repo, 'H1', net=-8.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'SB', 'post_sb', 0.25, 0),
            ('preflop', 'BB', 'post_bb', 0.50, 0),
            ('preflop', 'V1', 'raise', 1.5, 0),
            ('preflop', 'Hero', 'raise', 5.0, 1),
            ('preflop', 'V1', 'raise', 12.0, 0),
            ('preflop', 'Hero', 'fold', 0, 1),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['pot_types']['4bet_plus']['hands'], 1)

    def test_multiple_hands_different_types(self):
        _insert_hand_with_actions(self.repo, 'H1', net=1.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'Hero', 'call', 0.5, 1),
        ])
        _insert_hand_with_actions(self.repo, 'H2', net=-1.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'Hero', 'raise', 1.5, 1),
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        _insert_hand_with_actions(self.repo, 'H3', net=-2.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'V1', 'raise', 1.5, 0),
            ('preflop', 'Hero', 'raise', 5.0, 1),
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['total_hands'], 3)
        self.assertEqual(result['pot_types']['limped']['hands'], 1)
        self.assertEqual(result['pot_types']['srp']['hands'], 1)
        self.assertEqual(result['pot_types']['3bet']['hands'], 1)

    def test_hero_not_present_excluded(self):
        """Hands without hero actions should be ignored."""
        _insert_hand_with_actions(self.repo, 'H1', net=0.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'V1', 'raise', 1.5, 0),  # no is_hero
            ('preflop', 'V2', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['total_hands'], 0)


class TestGetBetSizingAnalysisSizing(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_preflop_sizing_captured(self):
        _insert_hand_with_actions(self.repo, 'H1', net=0.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'SB', 'post_sb', 0.25, 0),
            ('preflop', 'BB', 'post_bb', 0.50, 0),
            ('preflop', 'Hero', 'raise', 1.5, 1),  # 3x BB
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        preflop = result['sizing']['preflop']
        self.assertEqual(preflop['samples'], 1)
        self.assertAlmostEqual(preflop['avg'], 3.0)

    def test_flop_sizing_captured(self):
        """Hero bets on flop: sizing % tracked."""
        _insert_hand_with_actions(self.repo, 'H1', net=0.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'SB', 'post_sb', 0.25, 0),
            ('preflop', 'BB', 'post_bb', 0.50, 0),
            ('preflop', 'Hero', 'raise', 1.5, 1),
            ('preflop', 'V1', 'call', 1.5, 0),
            ('flop', 'Hero', 'bet', 1.5, 1),   # hero cbets
            ('flop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        flop = result['sizing']['flop']
        self.assertEqual(flop['samples'], 1)
        self.assertGreater(flop['avg'], 0)

    def test_no_bet_no_sizing(self):
        """Hand with only preflop call and fold: no sizing."""
        _insert_hand_with_actions(self.repo, 'H1', net=-0.5, blinds_bb=0.5, actions_spec=[
            ('preflop', 'Hero', 'call', 0.5, 1),
            ('preflop', 'V1', 'raise', 2.0, 0),
            ('preflop', 'Hero', 'fold', 0, 1),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['sizing']['preflop']['samples'], 0)

    def test_sizing_distribution_has_buckets(self):
        """Preflop sizing distribution has correct bucket count."""
        _insert_hand_with_actions(self.repo, 'H1', net=0.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'Hero', 'raise', 1.5, 1),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(len(result['sizing']['preflop']['distribution']), 5)


class TestGetBetSizingAnalysisHuVsMultiway(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_hu_hand_no_flop(self):
        """Preflop-only hand with 2 players → HU."""
        _insert_hand_with_actions(self.repo, 'H1', net=1.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'Hero', 'raise', 1.5, 1),
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['hu_vs_multiway']['heads_up']['hands'], 1)
        self.assertEqual(result['hu_vs_multiway']['multiway']['hands'], 0)

    def test_multiway_flop(self):
        """Flop with 3 players → multiway."""
        _insert_hand_with_actions(self.repo, 'H1', net=-1.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'Hero', 'call', 0.5, 1),
            ('preflop', 'V1', 'call', 0.5, 0),
            ('preflop', 'V2', 'call', 0.5, 0),
            ('flop', 'Hero', 'check', 0, 1),
            ('flop', 'V1', 'check', 0, 0),
            ('flop', 'V2', 'check', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['hu_vs_multiway']['multiway']['hands'], 1)
        self.assertEqual(result['hu_vs_multiway']['heads_up']['hands'], 0)

    def test_hu_flop(self):
        """Flop with exactly 2 players → HU."""
        _insert_hand_with_actions(self.repo, 'H1', net=2.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'Hero', 'raise', 1.5, 1),
            ('preflop', 'V1', 'call', 1.5, 0),
            ('flop', 'Hero', 'bet', 1.0, 1),
            ('flop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertEqual(result['hu_vs_multiway']['heads_up']['hands'], 1)
        self.assertEqual(result['hu_vs_multiway']['multiway']['hands'], 0)


class TestGetBetSizingAnalysisWinRate(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_win_rate_positive(self):
        """Winning hand → positive win rate."""
        _insert_hand_with_actions(self.repo, 'H1', net=10.0, blinds_bb=1.0, actions_spec=[
            ('preflop', 'Hero', 'raise', 3.0, 1),
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        srp = result['pot_types']['srp']
        self.assertGreater(srp['win_rate_bb100'], 0)
        self.assertEqual(srp['health'], 'good')

    def test_win_rate_negative_danger(self):
        """Consistently losing hands → danger health."""
        for i in range(5):
            _insert_hand_with_actions(
                self.repo, f'H{i}', net=-10.0, blinds_bb=1.0,
                actions_spec=[
                    ('preflop', 'Hero', 'raise', 3.0, 1),
                    ('preflop', 'V1', 'fold', 0, 0),
                ],
                date=f'2026-01-{15+i:02d}T20:00:00',
            )
        result = self.analyzer.get_bet_sizing_analysis()
        srp = result['pot_types']['srp']
        self.assertLess(srp['win_rate_bb100'], -5)
        self.assertEqual(srp['health'], 'danger')

    def test_net_accumulated_correctly(self):
        """Net profit sums across all hands of a pot type."""
        _insert_hand_with_actions(self.repo, 'H1', net=5.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'Hero', 'raise', 1.5, 1),
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        _insert_hand_with_actions(self.repo, 'H2', net=-3.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'Hero', 'raise', 1.5, 1),
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        self.assertAlmostEqual(result['pot_types']['srp']['net'], 2.0)


class TestGetBetSizingAnalysisStats(unittest.TestCase):
    """Test that VPIP/PFR/CBet/WTSD/W$SD are computed per pot type."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def test_vpip_pfr_in_srp(self):
        """Hero raises → vpip=100%, pfr=100% for that SRP hand."""
        _insert_hand_with_actions(self.repo, 'H1', net=1.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'SB', 'post_sb', 0.25, 0),
            ('preflop', 'BB', 'post_bb', 0.50, 0),
            ('preflop', 'Hero', 'raise', 1.5, 1),
            ('preflop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        srp = result['pot_types']['srp']
        self.assertEqual(srp['vpip'], 100.0)
        self.assertEqual(srp['pfr'], 100.0)

    def test_cbet_tracked(self):
        """Hero was PFA and cbets → cbet% > 0."""
        _insert_hand_with_actions(self.repo, 'H1', net=1.0, blinds_bb=0.5, actions_spec=[
            ('preflop', 'SB', 'post_sb', 0.25, 0),
            ('preflop', 'BB', 'post_bb', 0.50, 0),
            ('preflop', 'Hero', 'raise', 1.5, 1),
            ('preflop', 'V1', 'call', 1.5, 0),
            ('flop', 'Hero', 'bet', 1.0, 1),
            ('flop', 'V1', 'fold', 0, 0),
        ])
        result = self.analyzer.get_bet_sizing_analysis()
        srp = result['pot_types']['srp']
        self.assertEqual(srp['cbet'], 100.0)


# ── Report tests: _render_bet_sizing_analysis ─────────────────────────────────

class TestRenderBetSizingAnalysis(unittest.TestCase):

    def _make_data(self, total_hands=20, pot_types=None, sizing=None,
                   hu_vs_multiway=None, diagnostics=None):
        default_pt = {
            'hands': 10, 'hu_hands': 5, 'multiway_hands': 5,
            'vpip': 50.0, 'pfr': 40.0, 'af': 2.5,
            'cbet': 65.0, 'wtsd': 28.0, 'wsd': 52.0,
            'net': 5.0, 'win_rate_bb100': 8.0, 'health': 'good',
        }
        default_sizing = {
            'samples': 8,
            'avg': 3.0,
            'median': 3.0,
            'distribution': [
                {'label': '<2x', 'count': 1, 'pct': 12.5},
                {'label': '2-2.5x', 'count': 2, 'pct': 25.0},
                {'label': '2.5-3x', 'count': 3, 'pct': 37.5},
                {'label': '3-4x', 'count': 1, 'pct': 12.5},
                {'label': '>4x', 'count': 1, 'pct': 12.5},
            ],
        }
        return {
            'total_hands': total_hands,
            'pot_types': pot_types or {
                'limped': default_pt,
                'srp': default_pt,
                '3bet': {'hands': 0, 'hu_hands': 0, 'multiway_hands': 0,
                         'vpip': 0.0, 'pfr': 0.0, 'af': 0.0,
                         'cbet': 0.0, 'wtsd': 0.0, 'wsd': 0.0,
                         'net': 0.0, 'win_rate_bb100': 0.0, 'health': 'good'},
                '4bet_plus': {'hands': 0, 'hu_hands': 0, 'multiway_hands': 0,
                              'vpip': 0.0, 'pfr': 0.0, 'af': 0.0,
                              'cbet': 0.0, 'wtsd': 0.0, 'wsd': 0.0,
                              'net': 0.0, 'win_rate_bb100': 0.0, 'health': 'good'},
            },
            'sizing': sizing or {
                'preflop': default_sizing,
                'flop': {'samples': 0, 'avg': 0.0, 'median': 0.0, 'distribution': []},
                'turn': {'samples': 0, 'avg': 0.0, 'median': 0.0, 'distribution': []},
                'river': {'samples': 0, 'avg': 0.0, 'median': 0.0, 'distribution': []},
            },
            'hu_vs_multiway': hu_vs_multiway or {
                'heads_up': default_pt,
                'multiway': default_pt,
            },
            'diagnostics': diagnostics or [],
        }

    def test_returns_empty_when_too_few_hands(self):
        data = self._make_data(total_hands=4)
        result = _render_bet_sizing_analysis(data)
        self.assertEqual(result, '')

    def test_returns_empty_when_none(self):
        self.assertEqual(_render_bet_sizing_analysis(None), '')

    def test_returns_html_with_sufficient_hands(self):
        data = self._make_data(total_hands=20)
        result = _render_bet_sizing_analysis(data)
        self.assertIn('Bet Sizing', result)
        self.assertIn('Tipo de Pote', result)

    def test_contains_pot_type_labels(self):
        data = self._make_data(total_hands=20)
        result = _render_bet_sizing_analysis(data)
        self.assertIn('Limped', result)
        self.assertIn('SRP', result)

    def test_no_data_shows_sem_dados(self):
        """Pot types with 0 hands show 'Sem dados'."""
        data = self._make_data(total_hands=20)
        result = _render_bet_sizing_analysis(data)
        self.assertIn('Sem dados', result)

    def test_win_rate_shown(self):
        data = self._make_data(total_hands=20)
        result = _render_bet_sizing_analysis(data)
        self.assertIn('bb/100', result)

    def test_health_badge_shown(self):
        data = self._make_data(total_hands=20)
        result = _render_bet_sizing_analysis(data)
        self.assertIn('badge-good', result)

    def test_sizing_distribution_shown(self):
        data = self._make_data(total_hands=20)
        result = _render_bet_sizing_analysis(data)
        self.assertIn('Preflop Raise Size', result)
        self.assertIn('<2x', result)

    def test_hu_multiway_section(self):
        data = self._make_data(total_hands=20)
        result = _render_bet_sizing_analysis(data)
        self.assertIn('Heads-Up', result)
        self.assertIn('Multiway', result)

    def test_diagnostics_rendered(self):
        data = self._make_data(
            total_hands=20,
            diagnostics=[{'type': 'danger', 'title': 'Perigo Test', 'message': 'Msg test'}],
        )
        result = _render_bet_sizing_analysis(data)
        self.assertIn('Perigo Test', result)
        self.assertIn('Msg test', result)
        # Diagnostics use inline color styles, not badge classes
        self.assertIn('ff4444', result)  # danger color

    def test_warning_diagnostic_color(self):
        data = self._make_data(
            total_hands=20,
            diagnostics=[{'type': 'warning', 'title': 'Aviso', 'message': 'Warning msg'}],
        )
        result = _render_bet_sizing_analysis(data)
        self.assertIn('ffa500', result)  # warning color

    def test_good_diagnostic_color(self):
        data = self._make_data(
            total_hands=20,
            diagnostics=[{'type': 'good', 'title': 'Bom', 'message': 'Good msg'}],
        )
        result = _render_bet_sizing_analysis(data)
        self.assertIn('00ff88', result)  # good color

    def test_no_sizing_data_skips_section(self):
        """If no sizing samples, sizing section is skipped."""
        data = self._make_data(total_hands=20, sizing={
            'preflop': {'samples': 0, 'avg': 0.0, 'median': 0.0, 'distribution': []},
            'flop': {'samples': 0, 'avg': 0.0, 'median': 0.0, 'distribution': []},
            'turn': {'samples': 0, 'avg': 0.0, 'median': 0.0, 'distribution': []},
            'river': {'samples': 0, 'avg': 0.0, 'median': 0.0, 'distribution': []},
        })
        result = _render_bet_sizing_analysis(data)
        self.assertNotIn('Distribui\u00e7\u00e3o de Bet Sizing', result)

    def test_negative_win_rate_negative_class(self):
        """Negative win rate should have 'negative' CSS class."""
        losing_pt = {
            'hands': 10, 'hu_hands': 5, 'multiway_hands': 5,
            'vpip': 50.0, 'pfr': 40.0, 'af': 2.5,
            'cbet': 65.0, 'wtsd': 28.0, 'wsd': 52.0,
            'net': -5.0, 'win_rate_bb100': -8.0, 'health': 'danger',
        }
        data = self._make_data(total_hands=20, pot_types={
            'limped': losing_pt,
            'srp': {'hands': 0, 'hu_hands': 0, 'multiway_hands': 0,
                    'vpip': 0.0, 'pfr': 0.0, 'af': 0.0,
                    'cbet': 0.0, 'wtsd': 0.0, 'wsd': 0.0,
                    'net': 0.0, 'win_rate_bb100': 0.0, 'health': 'good'},
            '3bet': {'hands': 0, 'hu_hands': 0, 'multiway_hands': 0,
                     'vpip': 0.0, 'pfr': 0.0, 'af': 0.0,
                     'cbet': 0.0, 'wtsd': 0.0, 'wsd': 0.0,
                     'net': 0.0, 'win_rate_bb100': 0.0, 'health': 'good'},
            '4bet_plus': {'hands': 0, 'hu_hands': 0, 'multiway_hands': 0,
                          'vpip': 0.0, 'pfr': 0.0, 'af': 0.0,
                          'cbet': 0.0, 'wtsd': 0.0, 'wsd': 0.0,
                          'net': 0.0, 'win_rate_bb100': 0.0, 'health': 'good'},
        })
        result = _render_bet_sizing_analysis(data)
        self.assertIn('class="negative"', result)
        self.assertIn('badge-danger', result)


if __name__ == '__main__':
    unittest.main()
