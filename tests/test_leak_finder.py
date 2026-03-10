"""Tests for US-011: Leak Finder Automatizado com Spots de Estudo Priorizados.

Covers:
- LeakFinder._check_deviation() for preflop, postflop, positional
- LeakFinder._leak_name() naming
- LeakFinder._leak_suggestion() concrete suggestions
- LeakFinder._detect_preflop_leaks() with healthy ranges
- LeakFinder._detect_postflop_leaks() with healthy ranges
- LeakFinder._detect_positional_leaks() with position-specific ranges
- LeakFinder._calculate_health_score()
- LeakFinder._generate_study_spots()
- LeakFinder._study_spot_for_leak()
- LeakFinder._compare_periods()
- LeakFinder._leak_to_dict() serialization
- CashAnalyzer.get_leak_analysis() integration
- HTML rendering: _render_leak_finder(), _render_health_score_bar(),
  _render_period_comparison(), _hex_to_rgb()
- Integration in generate_cash_report()
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer
from src.analyzers.leak_finder import Leak, LeakFinder
from src.reports.cash_report import (
    _render_leak_finder,
    _render_health_score_bar,
    _render_period_comparison,
    _hex_to_rgb,
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


# ── Unit Tests: _check_deviation ─────────────────────────────────────

class TestCheckDeviation(unittest.TestCase):
    """Tests for LeakFinder._check_deviation()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo)
        self.finder = LeakFinder(self.analyzer, self.repo)

    def tearDown(self):
        self.conn.close()

    def test_within_healthy_range_returns_none(self):
        """Value within healthy range → no leak."""
        result = self.finder._check_deviation('vpip', 25.0, 22.0, 30.0, 0.15, 'preflop')
        self.assertIsNone(result)

    def test_at_healthy_low_boundary_returns_none(self):
        """Value exactly at low boundary → no leak."""
        result = self.finder._check_deviation('vpip', 22.0, 22.0, 30.0, 0.15, 'preflop')
        self.assertIsNone(result)

    def test_at_healthy_high_boundary_returns_none(self):
        """Value exactly at high boundary → no leak."""
        result = self.finder._check_deviation('vpip', 30.0, 22.0, 30.0, 0.15, 'preflop')
        self.assertIsNone(result)

    def test_too_high_returns_leak(self):
        """Value above healthy range → leak with too_high direction."""
        result = self.finder._check_deviation('vpip', 40.0, 22.0, 30.0, 0.15, 'preflop')
        self.assertIsNotNone(result)
        self.assertEqual(result.direction, 'too_high')
        self.assertEqual(result.stat_name, 'vpip')
        self.assertAlmostEqual(result.cost_bb100, 1.50)  # 10 * 0.15

    def test_too_low_returns_leak(self):
        """Value below healthy range → leak with too_low direction."""
        result = self.finder._check_deviation('vpip', 12.0, 22.0, 30.0, 0.15, 'preflop')
        self.assertIsNotNone(result)
        self.assertEqual(result.direction, 'too_low')
        self.assertAlmostEqual(result.cost_bb100, 1.50)  # 10 * 0.15

    def test_positional_leak_includes_position(self):
        """Positional leak includes position in the Leak."""
        result = self.finder._check_deviation(
            'vpip', 60.0, 30.0, 45.0, 0.12, 'positional', position='BTN')
        self.assertIsNotNone(result)
        self.assertEqual(result.position, 'BTN')
        self.assertEqual(result.category, 'positional')

    def test_small_deviation_low_cost(self):
        """Small deviation → low cost."""
        result = self.finder._check_deviation('pfr', 25.5, 17.0, 25.0, 0.18, 'preflop')
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.cost_bb100, 0.09)  # 0.5 * 0.18

    def test_current_value_is_rounded(self):
        """Current value is stored rounded to 1 decimal."""
        result = self.finder._check_deviation('af', 1.234, 2.0, 3.5, 0.40, 'postflop')
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.current_value, 1.2)


# ── Unit Tests: _leak_name ──────────────────────────────────────────

class TestLeakName(unittest.TestCase):
    """Tests for LeakFinder._leak_name()."""

    def test_vpip_too_high(self):
        name = LeakFinder._leak_name('vpip', 'too_high', 'preflop')
        self.assertEqual(name, 'VPIP muito alto')

    def test_pfr_too_low(self):
        name = LeakFinder._leak_name('pfr', 'too_low', 'preflop')
        self.assertEqual(name, 'PFR muito baixo')

    def test_af_too_high_postflop(self):
        name = LeakFinder._leak_name('af', 'too_high', 'postflop')
        self.assertEqual(name, 'AF muito alto')

    def test_positional_with_position(self):
        name = LeakFinder._leak_name('vpip', 'too_high', 'positional', 'BTN')
        self.assertEqual(name, 'VPIP muito alto no BTN')

    def test_cbet_too_low(self):
        name = LeakFinder._leak_name('cbet', 'too_low', 'postflop')
        self.assertEqual(name, 'CBet muito baixo')

    def test_unknown_stat(self):
        name = LeakFinder._leak_name('mystery', 'too_high', 'preflop')
        self.assertEqual(name, 'mystery muito alto')


# ── Unit Tests: _leak_suggestion ─────────────────────────────────────

class TestLeakSuggestion(unittest.TestCase):
    """Tests for LeakFinder._leak_suggestion()."""

    def test_vpip_too_high_suggestion(self):
        s = LeakFinder._leak_suggestion('vpip', 'too_high', 'preflop')
        self.assertIn('Reduza range de abertura', s)

    def test_vpip_too_low_suggestion(self):
        s = LeakFinder._leak_suggestion('vpip', 'too_low', 'preflop')
        self.assertIn('Amplie range de abertura', s)

    def test_af_too_low_suggestion(self):
        s = LeakFinder._leak_suggestion('af', 'too_low', 'postflop')
        self.assertIn('agressividade postflop', s)

    def test_positional_suggestion_includes_position(self):
        s = LeakFinder._leak_suggestion('vpip', 'too_high', 'positional', 'UTG')
        self.assertIn('no UTG', s)

    def test_cbet_too_high_suggestion(self):
        s = LeakFinder._leak_suggestion('cbet', 'too_high', 'postflop')
        self.assertIn('c-bet', s)

    def test_unknown_stat_gets_fallback(self):
        s = LeakFinder._leak_suggestion('unknown_stat', 'too_high', 'preflop')
        self.assertIn('reduzir', s)

    def test_unknown_stat_too_low_fallback(self):
        s = LeakFinder._leak_suggestion('unknown_stat', 'too_low', 'preflop')
        self.assertIn('aumentar', s)


# ── Unit Tests: _detect_preflop_leaks ────────────────────────────────

class TestDetectPreflopLeaks(unittest.TestCase):
    """Tests for LeakFinder._detect_preflop_leaks()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo)
        self.finder = LeakFinder(self.analyzer, self.repo)

    def tearDown(self):
        self.conn.close()

    def test_no_leaks_when_all_healthy(self):
        """All stats within healthy range → empty list."""
        overall = {
            'vpip': 26.0, 'pfr': 20.0, 'three_bet': 9.0,
            'fold_to_3bet': 48.0, 'ats': 38.0,
        }
        leaks = self.finder._detect_preflop_leaks(overall)
        self.assertEqual(len(leaks), 0)

    def test_vpip_too_high_detected(self):
        """VPIP above healthy → leak detected."""
        overall = {
            'vpip': 45.0, 'pfr': 20.0, 'three_bet': 9.0,
            'fold_to_3bet': 48.0, 'ats': 38.0,
        }
        leaks = self.finder._detect_preflop_leaks(overall)
        vpip_leaks = [l for l in leaks if l.stat_name == 'vpip']
        self.assertEqual(len(vpip_leaks), 1)
        self.assertEqual(vpip_leaks[0].direction, 'too_high')
        # 45 - 30 = 15 deviation * 0.15 weight = 2.25
        self.assertAlmostEqual(vpip_leaks[0].cost_bb100, 2.25)

    def test_pfr_too_low_detected(self):
        """PFR below healthy → leak detected."""
        overall = {
            'vpip': 26.0, 'pfr': 10.0, 'three_bet': 9.0,
            'fold_to_3bet': 48.0, 'ats': 38.0,
        }
        leaks = self.finder._detect_preflop_leaks(overall)
        pfr_leaks = [l for l in leaks if l.stat_name == 'pfr']
        self.assertEqual(len(pfr_leaks), 1)
        self.assertEqual(pfr_leaks[0].direction, 'too_low')
        # 17 - 10 = 7 deviation * 0.18 weight = 1.26
        self.assertAlmostEqual(pfr_leaks[0].cost_bb100, 1.26)

    def test_multiple_leaks_detected(self):
        """Multiple stats outside range → multiple leaks."""
        overall = {
            'vpip': 50.0, 'pfr': 5.0, 'three_bet': 2.0,
            'fold_to_3bet': 80.0, 'ats': 10.0,
        }
        leaks = self.finder._detect_preflop_leaks(overall)
        self.assertEqual(len(leaks), 5)

    def test_missing_stat_skipped(self):
        """Missing stat key → gracefully skipped."""
        overall = {'vpip': 26.0}  # Only vpip present
        leaks = self.finder._detect_preflop_leaks(overall)
        # vpip is healthy, others default to 0 (below healthy range)
        self.assertTrue(all(l.stat_name != 'vpip' for l in leaks))


# ── Unit Tests: _detect_postflop_leaks ───────────────────────────────

class TestDetectPostflopLeaks(unittest.TestCase):
    """Tests for LeakFinder._detect_postflop_leaks()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo)
        self.finder = LeakFinder(self.analyzer, self.repo)

    def tearDown(self):
        self.conn.close()

    def test_no_leaks_when_all_healthy(self):
        """All postflop stats healthy → no leaks."""
        overall = {
            'af': 2.5, 'wtsd': 28.0, 'wsd': 52.0,
            'cbet': 68.0, 'fold_to_cbet': 42.0, 'check_raise': 9.0,
        }
        leaks = self.finder._detect_postflop_leaks(overall)
        self.assertEqual(len(leaks), 0)

    def test_af_too_low_detected(self):
        """AF below healthy → leak."""
        overall = {
            'af': 1.0, 'wtsd': 28.0, 'wsd': 52.0,
            'cbet': 68.0, 'fold_to_cbet': 42.0, 'check_raise': 9.0,
        }
        leaks = self.finder._detect_postflop_leaks(overall)
        af_leaks = [l for l in leaks if l.stat_name == 'af']
        self.assertEqual(len(af_leaks), 1)
        # 2.0 - 1.0 = 1.0 deviation * 0.40 = 0.40
        self.assertAlmostEqual(af_leaks[0].cost_bb100, 0.40)

    def test_af_too_high_detected(self):
        """AF above healthy → leak."""
        overall = {
            'af': 5.5, 'wtsd': 28.0, 'wsd': 52.0,
            'cbet': 68.0, 'fold_to_cbet': 42.0, 'check_raise': 9.0,
        }
        leaks = self.finder._detect_postflop_leaks(overall)
        af_leaks = [l for l in leaks if l.stat_name == 'af']
        self.assertEqual(len(af_leaks), 1)
        self.assertEqual(af_leaks[0].direction, 'too_high')
        # 5.5 - 3.5 = 2.0 * 0.40 = 0.80
        self.assertAlmostEqual(af_leaks[0].cost_bb100, 0.80)

    def test_cbet_too_high(self):
        """CBet above healthy → leak."""
        overall = {
            'af': 2.5, 'wtsd': 28.0, 'wsd': 52.0,
            'cbet': 90.0, 'fold_to_cbet': 42.0, 'check_raise': 9.0,
        }
        leaks = self.finder._detect_postflop_leaks(overall)
        cbet_leaks = [l for l in leaks if l.stat_name == 'cbet']
        self.assertEqual(len(cbet_leaks), 1)


# ── Unit Tests: _detect_positional_leaks ─────────────────────────────

class TestDetectPositionalLeaks(unittest.TestCase):
    """Tests for LeakFinder._detect_positional_leaks()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo)
        self.finder = LeakFinder(self.analyzer, self.repo)

    def tearDown(self):
        self.conn.close()

    def test_no_leaks_when_positions_healthy(self):
        """Position stats within healthy ranges → no positional leaks."""
        by_position = {
            'BTN': {'total_hands': 50, 'vpip': 35.0, 'pfr': 30.0},
            'CO': {'total_hands': 50, 'vpip': 26.0, 'pfr': 22.0},
        }
        leaks = self.finder._detect_positional_leaks(by_position)
        self.assertEqual(len(leaks), 0)

    def test_utg_vpip_too_high(self):
        """UTG VPIP above position-specific range → leak."""
        by_position = {
            'UTG': {'total_hands': 30, 'vpip': 35.0, 'pfr': 14.0},
        }
        leaks = self.finder._detect_positional_leaks(by_position)
        vpip_leaks = [l for l in leaks if l.stat_name == 'vpip']
        self.assertEqual(len(vpip_leaks), 1)
        self.assertEqual(vpip_leaks[0].position, 'UTG')
        self.assertEqual(vpip_leaks[0].direction, 'too_high')
        # 35 - 18 = 17 * 0.12 = 2.04
        self.assertAlmostEqual(vpip_leaks[0].cost_bb100, 2.04)

    def test_btn_pfr_too_low(self):
        """BTN PFR below position-specific range → leak."""
        by_position = {
            'BTN': {'total_hands': 50, 'vpip': 35.0, 'pfr': 15.0},
        }
        leaks = self.finder._detect_positional_leaks(by_position)
        pfr_leaks = [l for l in leaks if l.stat_name == 'pfr' and l.position == 'BTN']
        self.assertEqual(len(pfr_leaks), 1)
        self.assertEqual(pfr_leaks[0].direction, 'too_low')
        # 25 - 15 = 10 * 0.14 = 1.40
        self.assertAlmostEqual(pfr_leaks[0].cost_bb100, 1.40)

    def test_too_few_hands_skipped(self):
        """Position with < MIN_HANDS_POSITION → skipped."""
        by_position = {
            'UTG': {'total_hands': 10, 'vpip': 80.0, 'pfr': 0.0},
        }
        leaks = self.finder._detect_positional_leaks(by_position)
        self.assertEqual(len(leaks), 0)

    def test_position_without_range_skipped(self):
        """Position not in POSITION_VPIP_HEALTHY → no leak for that stat."""
        by_position = {
            'Unknown': {'total_hands': 50, 'vpip': 80.0, 'pfr': 0.0},
        }
        leaks = self.finder._detect_positional_leaks(by_position)
        self.assertEqual(len(leaks), 0)


# ── Unit Tests: _calculate_health_score ──────────────────────────────

class TestCalculateHealthScore(unittest.TestCase):
    """Tests for LeakFinder._calculate_health_score()."""

    def test_no_leaks_perfect_score(self):
        """No leaks → score 100."""
        self.assertEqual(LeakFinder._calculate_health_score([]), 100)

    def test_small_leak_high_score(self):
        """One small leak → score still high."""
        leaks = [Leak('test', 'preflop', 'vpip', 31.0, 22.0, 30.0,
                       0.15, 'too_high', 'fix it')]
        score = LeakFinder._calculate_health_score(leaks)
        self.assertGreater(score, 90)

    def test_large_leaks_low_score(self):
        """Multiple large leaks → low score."""
        leaks = [
            Leak('a', 'preflop', 'vpip', 50.0, 22.0, 30.0, 3.0, 'too_high', 's'),
            Leak('b', 'preflop', 'pfr', 5.0, 17.0, 25.0, 2.0, 'too_low', 's'),
            Leak('c', 'postflop', 'af', 0.5, 2.0, 3.5, 1.5, 'too_low', 's'),
            Leak('d', 'postflop', 'cbet', 95.0, 60.0, 75.0, 2.0, 'too_high', 's'),
        ]
        score = LeakFinder._calculate_health_score(leaks)
        self.assertLess(score, 30)

    def test_score_never_below_zero(self):
        """Score never goes below 0."""
        leaks = [
            Leak('x', 'preflop', 'vpip', 90.0, 22.0, 30.0, 20.0, 'too_high', 's')
        ]
        score = LeakFinder._calculate_health_score(leaks)
        self.assertEqual(score, 0)

    def test_score_never_above_100(self):
        """Score never exceeds 100."""
        score = LeakFinder._calculate_health_score([])
        self.assertLessEqual(score, 100)


# ── Unit Tests: _generate_study_spots ────────────────────────────────

class TestGenerateStudySpots(unittest.TestCase):
    """Tests for LeakFinder._generate_study_spots()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo)
        self.finder = LeakFinder(self.analyzer, self.repo)

    def tearDown(self):
        self.conn.close()

    def test_generates_spots_for_leaks(self):
        """Each leak generates a study spot."""
        leaks = [
            Leak('VPIP muito alto', 'preflop', 'vpip', 40.0, 22.0, 30.0,
                 1.5, 'too_high', 'reduce'),
            Leak('PFR muito baixo', 'preflop', 'pfr', 10.0, 17.0, 25.0,
                 1.26, 'too_low', 'increase'),
        ]
        spots = self.finder._generate_study_spots(leaks)
        self.assertEqual(len(spots), 2)
        self.assertTrue(all('title' in s for s in spots))
        self.assertTrue(all('action' in s for s in spots))
        self.assertTrue(all('priority' in s for s in spots))

    def test_max_10_spots(self):
        """Never more than 10 study spots."""
        leaks = [
            Leak(f'leak{i}', 'preflop', 'vpip', 40.0 + i, 22.0, 30.0,
                 1.0, 'too_high', 's')
            for i in range(15)
        ]
        spots = self.finder._generate_study_spots(leaks)
        self.assertLessEqual(len(spots), 10)

    def test_deduplicates_spots(self):
        """Duplicate leak types → deduplicated study spots."""
        leaks = [
            Leak('VPIP muito alto', 'preflop', 'vpip', 40.0, 22.0, 30.0,
                 1.5, 'too_high', 's'),
            Leak('VPIP muito alto', 'preflop', 'vpip', 42.0, 22.0, 30.0,
                 1.8, 'too_high', 's'),
        ]
        spots = self.finder._generate_study_spots(leaks)
        titles = [s['title'] for s in spots]
        self.assertEqual(len(titles), len(set(titles)))

    def test_positional_spots_include_position(self):
        """Positional leaks generate position-specific spots."""
        leaks = [
            Leak('VPIP muito alto no UTG', 'positional', 'vpip', 30.0,
                 12.0, 18.0, 1.44, 'too_high', 's', position='UTG'),
        ]
        spots = self.finder._generate_study_spots(leaks)
        self.assertEqual(len(spots), 1)
        self.assertIn('UTG', spots[0]['title'])

    def test_empty_leaks_empty_spots(self):
        """No leaks → no study spots."""
        spots = self.finder._generate_study_spots([])
        self.assertEqual(len(spots), 0)


# ── Unit Tests: _study_spot_for_leak ────────────────────────────────

class TestStudySpotForLeak(unittest.TestCase):
    """Tests for LeakFinder._study_spot_for_leak()."""

    def test_preflop_vpip_high(self):
        leak = Leak('VPIP alto', 'preflop', 'vpip', 40.0, 22.0, 30.0,
                    1.5, 'too_high', 's')
        spot = LeakFinder._study_spot_for_leak(leak)
        self.assertIn('ranges de abertura', spot['title'])
        self.assertEqual(spot['priority'], 'alta')

    def test_postflop_af_low(self):
        leak = Leak('AF baixo', 'postflop', 'af', 1.0, 2.0, 3.5,
                    0.4, 'too_low', 's')
        spot = LeakFinder._study_spot_for_leak(leak)
        self.assertIn('agressividade', spot['title'])

    def test_positional_leak_format(self):
        leak = Leak('VPIP alto no BB', 'positional', 'vpip', 60.0,
                    25.0, 42.0, 2.16, 'too_high', 's', position='BB')
        spot = LeakFinder._study_spot_for_leak(leak)
        self.assertIn('BB', spot['title'])
        self.assertIn('60.0%', spot['action'])
        self.assertIn('25-42', spot['action'])

    def test_unknown_category_fallback(self):
        leak = Leak('unknown', 'sizing', 'bet_size', 10.0, 5.0, 8.0,
                    0.5, 'too_high', 'fix sizing')
        spot = LeakFinder._study_spot_for_leak(leak)
        self.assertIn('title', spot)
        self.assertIn('action', spot)


# ── Unit Tests: _leak_to_dict ────────────────────────────────────────

class TestLeakToDict(unittest.TestCase):
    """Tests for LeakFinder._leak_to_dict()."""

    def test_converts_all_fields(self):
        leak = Leak(
            name='VPIP alto', category='preflop', stat_name='vpip',
            current_value=40.0, healthy_low=22.0, healthy_high=30.0,
            cost_bb100=1.5, direction='too_high',
            suggestion='Reduce range', position='',
        )
        d = LeakFinder._leak_to_dict(leak)
        self.assertEqual(d['name'], 'VPIP alto')
        self.assertEqual(d['category'], 'preflop')
        self.assertEqual(d['stat_name'], 'vpip')
        self.assertEqual(d['current_value'], 40.0)
        self.assertEqual(d['healthy_low'], 22.0)
        self.assertEqual(d['healthy_high'], 30.0)
        self.assertEqual(d['cost_bb100'], 1.5)
        self.assertEqual(d['direction'], 'too_high')
        self.assertEqual(d['suggestion'], 'Reduce range')
        self.assertEqual(d['position'], '')

    def test_positional_leak_has_position(self):
        leak = Leak('x', 'positional', 'vpip', 30.0, 12.0, 18.0,
                    1.0, 'too_high', 's', position='UTG')
        d = LeakFinder._leak_to_dict(leak)
        self.assertEqual(d['position'], 'UTG')


# ── Integration Tests: find_leaks ────────────────────────────────────

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


class TestFindLeaksIntegration(unittest.TestCase):
    """Integration tests for LeakFinder.find_leaks() with DB data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo)
        self.finder = LeakFinder(self.analyzer, self.repo)

    def tearDown(self):
        self.conn.close()

    def test_empty_db_returns_no_leaks(self):
        """Empty database → no leaks, health score 100."""
        result = self.finder.find_leaks()
        self.assertEqual(result['total_leaks'], 0)
        self.assertEqual(result['health_score'], 100)
        self.assertEqual(len(result['leaks']), 0)
        self.assertEqual(len(result['top5']), 0)
        self.assertEqual(len(result['study_spots']), 0)

    def _populate_hands(self, n=60, vpip_pct=50, pfr_pct=10,
                        hero_pos='CO', date='2026-01-15'):
        """Insert n hands with specified VPIP/PFR percentages."""
        for i in range(n):
            hand_id = f'hand_{date}_{i}'
            is_vpip = i < (n * vpip_pct / 100)
            is_pfr = i < (n * pfr_pct / 100)

            if is_pfr:
                hero_action = ('Hero', 'raise', 1, hero_pos)
            elif is_vpip:
                hero_action = ('Hero', 'call', 1, hero_pos)
            else:
                hero_action = ('Hero', 'fold', 1, hero_pos)

            _insert_hand_with_actions(
                self.repo, hand_id, hero_pos=hero_pos,
                net=0.50 if i % 2 == 0 else -0.30,
                date=date,
                preflop_actions=[
                    ('V1', 'fold', 0, 'UTG'),
                    ('V2', 'fold', 0, 'MP'),
                    hero_action,
                ],
            )

    def test_detects_leaks_with_bad_stats(self):
        """Hands with very high VPIP and low PFR → leaks detected."""
        self._populate_hands(n=60, vpip_pct=80, pfr_pct=5)

        result = self.finder.find_leaks()
        self.assertGreater(result['total_leaks'], 0)
        self.assertLess(result['health_score'], 100)

        # At least we should see some preflop leaks
        categories = [l['category'] for l in result['leaks']]
        self.assertIn('preflop', categories)

    def test_top5_limited_to_five(self):
        """Top5 never exceeds 5 entries."""
        self._populate_hands(n=60, vpip_pct=90, pfr_pct=2)
        result = self.finder.find_leaks()
        self.assertLessEqual(len(result['top5']), 5)

    def test_leaks_sorted_by_cost_descending(self):
        """Leaks are sorted by cost_bb100 descending."""
        self._populate_hands(n=60, vpip_pct=80, pfr_pct=5)
        result = self.finder.find_leaks()
        costs = [l['cost_bb100'] for l in result['leaks']]
        self.assertEqual(costs, sorted(costs, reverse=True))


# ── Integration Tests: CashAnalyzer.get_leak_analysis() ──────────────

class TestCashAnalyzerGetLeakAnalysis(unittest.TestCase):
    """Tests for CashAnalyzer.get_leak_analysis() integration."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo)

    def tearDown(self):
        self.conn.close()

    def test_returns_dict_with_required_keys(self):
        """get_leak_analysis returns dict with all expected keys."""
        result = self.analyzer.get_leak_analysis()
        self.assertIn('leaks', result)
        self.assertIn('top5', result)
        self.assertIn('study_spots', result)
        self.assertIn('health_score', result)
        self.assertIn('period_comparison', result)
        self.assertIn('total_leaks', result)

    def test_empty_db_returns_empty_leaks(self):
        """Empty DB → no leaks detected."""
        result = self.analyzer.get_leak_analysis()
        self.assertEqual(result['total_leaks'], 0)
        self.assertEqual(result['health_score'], 100)


# ── HTML Rendering Tests ─────────────────────────────────────────────

class TestRenderLeakFinder(unittest.TestCase):
    """Tests for _render_leak_finder() HTML output."""

    def test_renders_health_score(self):
        """Output contains health score."""
        data = {
            'health_score': 75,
            'total_leaks': 3,
            'top5': [],
            'study_spots': [],
            'period_comparison': {},
        }
        html = _render_leak_finder(data)
        self.assertIn('75/100', html)
        self.assertIn('Leak Finder', html)

    def test_renders_top5_leaks(self):
        """Output renders top 5 leak cards."""
        data = {
            'health_score': 50,
            'total_leaks': 2,
            'top5': [
                {
                    'name': 'VPIP muito alto', 'category': 'preflop',
                    'stat_name': 'vpip', 'current_value': 40.0,
                    'healthy_low': 22.0, 'healthy_high': 30.0,
                    'cost_bb100': 1.50, 'direction': 'too_high',
                    'suggestion': 'Reduza range de abertura',
                    'position': '',
                },
                {
                    'name': 'PFR muito baixo', 'category': 'preflop',
                    'stat_name': 'pfr', 'current_value': 10.0,
                    'healthy_low': 17.0, 'healthy_high': 25.0,
                    'cost_bb100': 1.26, 'direction': 'too_low',
                    'suggestion': 'Aumente agressividade preflop',
                    'position': '',
                },
            ],
            'study_spots': [],
            'period_comparison': {},
        }
        html = _render_leak_finder(data)
        self.assertIn('VPIP muito alto', html)
        self.assertIn('PFR muito baixo', html)
        self.assertIn('#1', html)
        self.assertIn('#2', html)
        self.assertIn('1.50 bb/100', html)
        self.assertIn('Preflop', html)
        self.assertIn('Reduza range de abertura', html)

    def test_renders_study_spots(self):
        """Output renders study spots."""
        data = {
            'health_score': 60,
            'total_leaks': 1,
            'top5': [],
            'study_spots': [
                {
                    'title': 'Estudar ranges de abertura preflop',
                    'action': 'Revise a tabela de open-raise ranges',
                    'priority': 'alta',
                },
            ],
            'period_comparison': {},
        }
        html = _render_leak_finder(data)
        self.assertIn('Spots para Estudar', html)
        self.assertIn('Estudar ranges de abertura preflop', html)
        self.assertIn('badge-danger', html)  # alta priority

    def test_renders_period_comparison(self):
        """Output renders period comparison table when data present."""
        data = {
            'health_score': 80,
            'total_leaks': 1,
            'top5': [],
            'study_spots': [],
            'period_comparison': {
                'overall': {'vpip': 26.0, 'pfr': 20.0},
                'recent': {'vpip': 30.0, 'pfr': 18.0},
                'period_label': 'Últimos 30 dias',
            },
        }
        html = _render_leak_finder(data)
        self.assertIn('Comparação de Períodos', html)
        self.assertIn('Overall', html)
        self.assertIn('Recente', html)

    def test_no_period_comparison_without_data(self):
        """No period comparison when data is empty."""
        data = {
            'health_score': 100,
            'total_leaks': 0,
            'top5': [],
            'study_spots': [],
            'period_comparison': {},
        }
        html = _render_leak_finder(data)
        self.assertNotIn('Comparação de Períodos', html)

    def test_empty_top5_no_leaks_section(self):
        """Empty top5 → no leaks section header."""
        data = {
            'health_score': 100,
            'total_leaks': 0,
            'top5': [],
            'study_spots': [],
            'period_comparison': {},
        }
        html = _render_leak_finder(data)
        self.assertNotIn('Top 5 Leaks', html)

    def test_leak_direction_labels(self):
        """Leak cards show direction labels (above/below)."""
        data = {
            'health_score': 50,
            'total_leaks': 2,
            'top5': [
                {
                    'name': 'VPIP alto', 'category': 'preflop',
                    'stat_name': 'vpip', 'current_value': 40.0,
                    'healthy_low': 22.0, 'healthy_high': 30.0,
                    'cost_bb100': 1.5, 'direction': 'too_high',
                    'suggestion': 's', 'position': '',
                },
                {
                    'name': 'PFR baixo', 'category': 'preflop',
                    'stat_name': 'pfr', 'current_value': 10.0,
                    'healthy_low': 17.0, 'healthy_high': 25.0,
                    'cost_bb100': 1.26, 'direction': 'too_low',
                    'suggestion': 's', 'position': '',
                },
            ],
            'study_spots': [],
            'period_comparison': {},
        }
        html = _render_leak_finder(data)
        self.assertIn('acima', html)
        self.assertIn('abaixo', html)


class TestRenderHealthScoreBar(unittest.TestCase):
    """Tests for _render_health_score_bar()."""

    def test_excellent_score(self):
        html = _render_health_score_bar(90, 1)
        self.assertIn('90/100', html)
        self.assertIn('Excelente', html)
        self.assertIn('#00ff88', html)

    def test_good_score(self):
        html = _render_health_score_bar(70, 3)
        self.assertIn('70/100', html)
        self.assertIn('Bom', html)

    def test_attention_score(self):
        html = _render_health_score_bar(50, 5)
        self.assertIn('50/100', html)
        self.assertIn('Atenção', html)

    def test_critical_score(self):
        html = _render_health_score_bar(20, 10)
        self.assertIn('20/100', html)
        self.assertIn('Crítico', html)
        self.assertIn('#ff4444', html)

    def test_shows_leak_count(self):
        html = _render_health_score_bar(60, 4)
        self.assertIn('4 leak(s)', html)

    def test_bar_width_matches_score(self):
        html = _render_health_score_bar(75, 2)
        self.assertIn('width:75%', html)


class TestHexToRgb(unittest.TestCase):
    """Tests for _hex_to_rgb()."""

    def test_red(self):
        self.assertEqual(_hex_to_rgb('#ff0000'), '255,0,0')

    def test_green(self):
        self.assertEqual(_hex_to_rgb('#00ff88'), '0,255,136')

    def test_ff4444(self):
        self.assertEqual(_hex_to_rgb('#ff4444'), '255,68,68')

    def test_without_hash(self):
        self.assertEqual(_hex_to_rgb('ffa500'), '255,165,0')


class TestRenderPeriodComparison(unittest.TestCase):
    """Tests for _render_period_comparison()."""

    def test_renders_stat_rows(self):
        period = {
            'overall': {'vpip': 26.0, 'pfr': 20.0, 'af': 2.5},
            'recent': {'vpip': 30.0, 'pfr': 18.0, 'af': 3.0},
            'period_label': 'Últimos 30 dias',
        }
        html = _render_period_comparison(period)
        self.assertIn('VPIP', html)
        self.assertIn('PFR', html)
        self.assertIn('26.0%', html)
        self.assertIn('30.0%', html)
        self.assertIn('Overall', html)
        self.assertIn('Recente', html)

    def test_shows_variation(self):
        period = {
            'overall': {'vpip': 26.0},
            'recent': {'vpip': 30.0},
            'period_label': 'Últimos 30 dias',
        }
        html = _render_period_comparison(period)
        self.assertIn('+4.0', html)

    def test_skips_missing_stats(self):
        period = {
            'overall': {'vpip': 26.0},
            'recent': {},
            'period_label': 'Últimos 30 dias',
        }
        html = _render_period_comparison(period)
        # vpip not rendered since recent is missing
        self.assertNotIn('26.0%', html)


# ── Full Report Integration ──────────────────────────────────────────

class TestReportIntegration(unittest.TestCase):
    """Integration test: leak finder section in full cash report."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo)

    def tearDown(self):
        self.conn.close()

    def test_leak_finder_section_appears_in_report(self):
        """When leaks exist, the section appears in the full HTML report."""
        import tempfile
        import os

        # Create 60 hands with extreme stats to trigger leaks
        for i in range(60):
            hand_id = f'rpt_hand_{i}'
            _insert_hand_with_actions(
                self.repo, hand_id, hero_pos='CO',
                net=0.50 if i % 2 == 0 else -0.30,
                date='2026-01-15',
                preflop_actions=[
                    ('V1', 'fold', 0, 'UTG'),
                    ('Hero', 'call', 1, 'CO'),
                ],
            )

        from src.reports.cash_report import generate_cash_report

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            tmp_path = f.name

        try:
            generate_cash_report(self.analyzer, output_file=tmp_path)
            with open(tmp_path, 'r', encoding='utf-8') as f:
                html = f.read()
            self.assertIn('Leak Finder', html)
            self.assertIn('Score de Saúde', html)
        finally:
            os.unlink(tmp_path)

    def test_no_leak_section_without_leaks(self):
        """When no leaks, leak finder section is not rendered."""
        import tempfile
        import os

        from src.reports.cash_report import generate_cash_report

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            tmp_path = f.name

        try:
            generate_cash_report(self.analyzer, output_file=tmp_path)
            with open(tmp_path, 'r', encoding='utf-8') as f:
                html = f.read()
            # No leaks → no leak finder section
            self.assertNotIn('Leak Finder', html)
        finally:
            os.unlink(tmp_path)


if __name__ == '__main__':
    unittest.main()
