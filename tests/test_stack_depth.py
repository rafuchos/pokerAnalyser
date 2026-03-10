"""Tests for US-017: Stats Segmentadas por Stack Depth (BB Count) e Posição.

Covers:
- CashAnalyzer._classify_stack_tier() — tier classification
- CashAnalyzer._classify_stack_depth_health() — health badge with tier-specific ranges
- CashAnalyzer.get_stack_depth_stats() — full calculation with all tiers
- Per-tier VPIP, PFR, 3-Bet, AF, CBet, WTSD, W$SD, win rate
- by_position_tier cross-table
- hands_with_stack / hands_total counts
- TargetsConfig stack_depth section loading
- Stack depth ranges in TargetsConfig (YAML and default)
- LeakFinder._detect_stack_depth_leaks() — leak detection per tier
- LeakFinder with stack depth integration in find_leaks()
- Repository.get_cash_hands_with_position() includes hero_stack
- Repository.insert_hand() saves hero_stack
- HandData hero_stack field
- GGPoker parser hero_stack extraction
- HTML rendering: _render_stack_depth_analysis()
- Health badges in HTML output
- Position x tier cross-table in HTML
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer
from src.config import TargetsConfig, _default_data
from src.reports.cash_report import _render_stack_depth_analysis


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _insert_raise_fold_hand(repo, hand_id, hero_stack, net=0.0,
                             blinds_bb=0.50, hero_position='BTN',
                             hero_raises=True):
    """Insert a hand + actions where hero either raises (VPIP+PFR) or folds."""
    hand = _make_hand(
        hand_id, hero_position=hero_position,
        net=net, blinds_bb=blinds_bb, hero_stack=hero_stack,
    )
    repo.insert_hand(hand)

    actions = [
        _make_action(hand_id, 'UTG', 'fold', 1, position='UTG'),
        _make_action(hand_id, 'CO', 'fold', 2, position='CO'),
    ]
    if hero_raises:
        actions.append(
            _make_action(hand_id, 'Hero', 'raise', 3, position=hero_position,
                         is_hero=1, amount=1.0, is_voluntary=1)
        )
        actions.append(
            _make_action(hand_id, 'SB', 'fold', 4, position='SB')
        )
        actions.append(
            _make_action(hand_id, 'BB', 'fold', 5, position='BB')
        )
    else:
        actions.append(
            _make_action(hand_id, 'Hero', 'fold', 3, position=hero_position,
                         is_hero=1, amount=0.0)
        )
    repo.insert_actions_batch(actions)


# ── Unit Tests: _classify_stack_tier ─────────────────────────────────────────

class TestClassifyStackTier(unittest.TestCase):
    """Tests for CashAnalyzer._classify_stack_tier()."""

    def test_deep_stack_50bb(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(50.0), 'deep')

    def test_deep_stack_100bb(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(100.0), 'deep')

    def test_deep_stack_exactly_50(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(50.0), 'deep')

    def test_medium_stack_49bb(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(49.9), 'medium')

    def test_medium_stack_25bb(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(25.0), 'medium')

    def test_medium_stack_exactly_25(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(25.0), 'medium')

    def test_shallow_24bb(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(24.9), 'shallow')

    def test_shallow_15bb(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(15.0), 'shallow')

    def test_shove_14bb(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(14.9), 'shove')

    def test_shove_1bb(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(1.0), 'shove')

    def test_shove_0bb(self):
        self.assertEqual(CashAnalyzer._classify_stack_tier(0.0), 'shove')


# ── Unit Tests: _classify_stack_depth_health ─────────────────────────────────

class TestClassifyStackDepthHealth(unittest.TestCase):
    """Tests for CashAnalyzer._classify_stack_depth_health()."""

    def setUp(self):
        conn, repo = _setup_db()
        self.analyzer = CashAnalyzer(repo, year='2026')

    def test_deep_vpip_healthy(self):
        # deep healthy: [22, 30]
        result = self.analyzer._classify_stack_depth_health('vpip', 'deep', 25.0)
        self.assertEqual(result, 'good')

    def test_deep_vpip_warning(self):
        # deep warning: [18, 35], not in healthy
        result = self.analyzer._classify_stack_depth_health('vpip', 'deep', 33.0)
        self.assertEqual(result, 'warning')

    def test_deep_vpip_danger(self):
        # below warning range for deep
        result = self.analyzer._classify_stack_depth_health('vpip', 'deep', 10.0)
        self.assertEqual(result, 'danger')

    def test_shove_vpip_high_is_healthy(self):
        # shove healthy: [25, 55] — 40% is perfectly fine with short stack
        result = self.analyzer._classify_stack_depth_health('vpip', 'shove', 40.0)
        self.assertEqual(result, 'good')

    def test_shove_vpip_20_is_warning(self):
        # shove healthy [25,55], warning [20,70]. 20 is in warning but not healthy
        result = self.analyzer._classify_stack_depth_health('vpip', 'shove', 20.0)
        self.assertEqual(result, 'warning')

    def test_pfr_deep_healthy(self):
        result = self.analyzer._classify_stack_depth_health('pfr', 'deep', 20.0)
        self.assertEqual(result, 'good')

    def test_three_bet_shove_high_is_danger(self):
        # shove 3-bet healthy [0,5], warning [0,10]
        result = self.analyzer._classify_stack_depth_health('three_bet', 'shove', 15.0)
        self.assertEqual(result, 'danger')

    def test_three_bet_deep_healthy(self):
        result = self.analyzer._classify_stack_depth_health('three_bet', 'deep', 9.0)
        self.assertEqual(result, 'good')

    def test_unknown_stat_falls_back(self):
        # af uses postflop health, not stack depth
        result = self.analyzer._classify_stack_depth_health('af', 'deep', 3.0)
        self.assertEqual(result, 'good')


# ── Unit Tests: get_stack_depth_stats ────────────────────────────────────────

class TestGetStackDepthStats(unittest.TestCase):
    """Tests for CashAnalyzer.get_stack_depth_stats()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def _insert_hands(self, specs):
        """Insert hands+actions from spec list: (hand_id, stack_bb, raises, net, pos)."""
        for hand_id, stack_bb, raises, net, pos in specs:
            blinds_bb = 0.50
            hero_stack = stack_bb * blinds_bb
            _insert_raise_fold_hand(
                self.repo, hand_id, hero_stack=hero_stack,
                net=net, blinds_bb=blinds_bb,
                hero_position=pos, hero_raises=raises,
            )

    def test_empty_db_returns_empty(self):
        result = self.analyzer.get_stack_depth_stats()
        self.assertEqual(result['by_tier'], {})
        self.assertEqual(result['hands_with_stack'], 0)

    def test_deep_stack_hands_classified(self):
        """Hands with 60BB stack → deep tier."""
        self._insert_hands([
            ('H1', 60.0, True,  1.0, 'BTN'),
            ('H2', 70.0, True, -0.5, 'BTN'),
            ('H3', 80.0, False, 0.0, 'BTN'),
        ])
        result = self.analyzer.get_stack_depth_stats()
        by_tier = result['by_tier']
        self.assertIn('deep', by_tier)
        self.assertEqual(by_tier['deep']['total_hands'], 3)
        self.assertNotIn('medium', by_tier)

    def test_shove_stack_classified(self):
        """Hands with 10BB stack → shove tier."""
        self._insert_hands([
            ('H1', 10.0, True,  1.0, 'BTN'),
            ('H2',  8.0, False, 0.0, 'SB'),
        ])
        result = self.analyzer.get_stack_depth_stats()
        by_tier = result['by_tier']
        self.assertIn('shove', by_tier)
        self.assertEqual(by_tier['shove']['total_hands'], 2)

    def test_multiple_tiers(self):
        """Hands across all 4 tiers."""
        self._insert_hands([
            ('H1', 60.0, True,  1.0, 'BTN'),   # deep
            ('H2', 30.0, True,  0.5, 'CO'),     # medium
            ('H3', 20.0, False, 0.0, 'SB'),     # shallow
            ('H4',  8.0, True, -1.0, 'BTN'),    # shove
        ])
        result = self.analyzer.get_stack_depth_stats()
        by_tier = result['by_tier']
        self.assertIn('deep', by_tier)
        self.assertIn('medium', by_tier)
        self.assertIn('shallow', by_tier)
        self.assertIn('shove', by_tier)

    def test_vpip_per_tier(self):
        """VPIP computation: 2 raises out of 3 hands → ~66.7%."""
        self._insert_hands([
            ('H1', 60.0, True,  0.0, 'BTN'),
            ('H2', 60.0, True,  0.0, 'CO'),
            ('H3', 60.0, False, 0.0, 'BTN'),
        ])
        result = self.analyzer.get_stack_depth_stats()
        vpip = result['by_tier']['deep']['vpip']
        self.assertAlmostEqual(vpip, 66.7, delta=0.5)

    def test_pfr_per_tier(self):
        """PFR equals VPIP when all VPIP actions are raises."""
        self._insert_hands([
            ('H1', 60.0, True,  0.0, 'BTN'),
            ('H2', 60.0, False, 0.0, 'BTN'),
        ])
        result = self.analyzer.get_stack_depth_stats()
        tier = result['by_tier']['deep']
        self.assertAlmostEqual(tier['pfr'], 50.0, delta=0.1)
        self.assertAlmostEqual(tier['vpip'], 50.0, delta=0.1)

    def test_winrate_per_tier(self):
        """Win rate (bb/100) computed per tier."""
        self._insert_hands([
            ('H1', 60.0, True,  1.0, 'BTN'),
            ('H2', 60.0, True,  1.0, 'CO'),
        ])
        result = self.analyzer.get_stack_depth_stats()
        tier = result['by_tier']['deep']
        # net_per_hand = (1+1)/2 = 1.0, bb_per_100 = (1.0/0.50)/2*100 = 100
        self.assertAlmostEqual(tier['net_per_hand'], 1.0, delta=0.01)
        self.assertGreater(tier['bb_per_100'], 0)

    def test_negative_winrate(self):
        result_tier = self._get_tier_with_losses()
        self.assertEqual(result_tier['winrate_health'], 'danger')

    def _get_tier_with_losses(self):
        self._insert_hands([
            ('H1', 60.0, True, -2.0, 'BTN'),
            ('H2', 60.0, True, -1.0, 'BTN'),
        ])
        result = self.analyzer.get_stack_depth_stats()
        return result['by_tier']['deep']

    def test_hands_with_stack_counted(self):
        """Only hands with known hero_stack counted in hands_with_stack."""
        # Insert one hand with stack, one without
        hand_with = _make_hand('HW', hero_stack=50.0, net=0.0, hero_position='BTN')
        self.repo.insert_hand(hand_with)
        actions_w = [
            _make_action('HW', 'Hero', 'raise', 1, position='BTN',
                         is_hero=1, is_voluntary=1),
        ]
        self.repo.insert_actions_batch(actions_w)

        hand_no = _make_hand('HN', hero_stack=None, net=0.0, hero_position='BTN')
        self.repo.insert_hand(hand_no)
        actions_n = [
            _make_action('HN', 'Hero', 'fold', 1, position='BTN', is_hero=1),
        ]
        self.repo.insert_actions_batch(actions_n)

        result = self.analyzer.get_stack_depth_stats()
        self.assertEqual(result['hands_with_stack'], 1)
        self.assertEqual(result['hands_total'], 2)

    def test_hands_without_stack_excluded(self):
        """Hands with NULL hero_stack are not in by_tier."""
        hand = _make_hand('HN', hero_stack=None)
        self.repo.insert_hand(hand)
        self.repo.insert_actions_batch([
            _make_action('HN', 'Hero', 'fold', 1, is_hero=1),
        ])
        result = self.analyzer.get_stack_depth_stats()
        self.assertEqual(result['by_tier'], {})

    def test_tier_labels_present(self):
        self._insert_hands([('H1', 60.0, True, 0.0, 'BTN')])
        result = self.analyzer.get_stack_depth_stats()
        self.assertIn('50+ BB', result['by_tier']['deep']['label'])

    def test_health_badges_in_by_tier(self):
        self._insert_hands([('H1', 60.0, True, 0.0, 'BTN')])
        result = self.analyzer.get_stack_depth_stats()
        tier = result['by_tier']['deep']
        for badge_key in ('vpip_health', 'pfr_health', 'three_bet_health',
                          'af_health', 'wtsd_health', 'wsd_health', 'cbet_health'):
            self.assertIn(tier[badge_key], ('good', 'warning', 'danger'),
                          f'{badge_key} not a valid health badge')

    def test_by_position_tier_structure(self):
        """by_position_tier populated with minimum 5 hands per cell."""
        # Insert 6 hands with BTN deep stack
        specs = [(f'H{i}', 60.0, True, 0.0, 'BTN') for i in range(6)]
        self._insert_hands(specs)
        result = self.analyzer.get_stack_depth_stats()
        bpt = result['by_position_tier']
        self.assertIn('BTN', bpt)
        self.assertIn('deep', bpt['BTN'])

    def test_by_position_tier_small_sample_excluded(self):
        """Position tiers with fewer than 5 hands are excluded."""
        # Insert only 4 BTN hands → below 5-hand minimum
        specs = [(f'H{i}', 60.0, True, 0.0, 'BTN') for i in range(4)]
        self._insert_hands(specs)
        result = self.analyzer.get_stack_depth_stats()
        bpt = result['by_position_tier']
        # BTN should not appear (only 4 hands)
        self.assertNotIn('BTN', bpt)

    def test_by_position_tier_vpip_pfr(self):
        """by_position_tier has vpip and pfr fields."""
        specs = [(f'H{i}', 60.0, True, 0.0, 'BTN') for i in range(6)]
        self._insert_hands(specs)
        result = self.analyzer.get_stack_depth_stats()
        bpt = result['by_position_tier']
        entry = bpt['BTN']['deep']
        self.assertIn('vpip', entry)
        self.assertIn('pfr', entry)
        self.assertIn('bb_per_100', entry)

    def test_tier_order_key_in_result(self):
        result = self.analyzer.get_stack_depth_stats()
        self.assertEqual(result['tier_order'], ['deep', 'medium', 'shallow', 'shove'])


# ── Unit Tests: TargetsConfig stack depth ────────────────────────────────────

class TestTargetsConfigStackDepth(unittest.TestCase):
    """Tests for TargetsConfig with stack_depth section."""

    def setUp(self):
        self.cfg = TargetsConfig.get_default()

    def test_stack_depth_tiers_present(self):
        for tier in ('deep', 'medium', 'shallow', 'shove'):
            self.assertIn(tier, self.cfg.stack_depth_tiers,
                          f"Missing tier: {tier}")

    def test_stack_depth_tier_min_bb(self):
        self.assertEqual(self.cfg.stack_depth_tiers['deep'], 50)
        self.assertEqual(self.cfg.stack_depth_tiers['shove'], 0)

    def test_stack_depth_vpip_healthy_all_tiers(self):
        for tier in ('deep', 'medium', 'shallow', 'shove'):
            self.assertIn(tier, self.cfg.stack_depth_vpip_healthy,
                          f"Missing vpip healthy for tier: {tier}")

    def test_stack_depth_pfr_healthy_all_tiers(self):
        for tier in ('deep', 'medium', 'shallow', 'shove'):
            self.assertIn(tier, self.cfg.stack_depth_pfr_healthy)

    def test_stack_depth_three_bet_healthy_all_tiers(self):
        for tier in ('deep', 'medium', 'shallow', 'shove'):
            self.assertIn(tier, self.cfg.stack_depth_three_bet_healthy)

    def test_deep_vpip_range_makes_sense(self):
        low, high = self.cfg.stack_depth_vpip_healthy['deep']
        self.assertLess(low, high)
        self.assertGreater(low, 0)

    def test_shove_vpip_wider_than_deep(self):
        shove_low, shove_high = self.cfg.stack_depth_vpip_healthy['shove']
        deep_low, deep_high = self.cfg.stack_depth_vpip_healthy['deep']
        # shove zone should accept higher VPIP (push/fold dynamics)
        self.assertGreater(shove_high, deep_high)

    def test_stack_depth_ranges_are_tuples(self):
        for tier, rng in self.cfg.stack_depth_vpip_healthy.items():
            self.assertIsInstance(rng, tuple, f"{tier} vpip range not a tuple")
            self.assertEqual(len(rng), 2)

    def test_default_data_has_stack_depth(self):
        data = _default_data()
        self.assertIn('stack_depth', data)
        self.assertIn('tiers', data['stack_depth'])
        self.assertIn('vpip', data['stack_depth'])
        self.assertIn('pfr', data['stack_depth'])

    def test_config_integration_with_analyzer(self):
        """CashAnalyzer uses config stack depth ranges when provided."""
        conn, repo = _setup_db()
        cfg = TargetsConfig.get_default()
        analyzer = CashAnalyzer(repo, year='2026', config=cfg)
        # Should use config ranges
        self.assertEqual(
            analyzer._stack_vpip_healthy,
            cfg.stack_depth_vpip_healthy
        )


# ── Unit Tests: Repository hero_stack ────────────────────────────────────────

class TestRepositoryHeroStack(unittest.TestCase):
    """Tests that hero_stack is saved and retrieved by the Repository."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_insert_hand_with_hero_stack(self):
        hand = _make_hand('H1', hero_stack=100.0)
        inserted = self.repo.insert_hand(hand)
        self.assertTrue(inserted)

    def test_retrieve_hero_stack_from_position_query(self):
        hand = _make_hand('H1', hero_stack=75.0, blinds_bb=0.50)
        self.repo.insert_hand(hand)
        hands = self.repo.get_cash_hands_with_position(year='2026')
        self.assertEqual(len(hands), 1)
        self.assertIn('hero_stack', hands[0])
        self.assertAlmostEqual(hands[0]['hero_stack'], 75.0, delta=0.01)

    def test_hero_stack_none_saved_as_null(self):
        hand = _make_hand('H2', hero_stack=None)
        self.repo.insert_hand(hand)
        hands = self.repo.get_cash_hands_with_position(year='2026')
        self.assertEqual(len(hands), 1)
        self.assertIsNone(hands[0]['hero_stack'])

    def test_stack_bb_computation(self):
        """Stack in BB = hero_stack / blinds_bb."""
        hand = _make_hand('H1', hero_stack=50.0, blinds_bb=1.0)
        self.repo.insert_hand(hand)
        hands = self.repo.get_cash_hands_with_position(year='2026')
        h = hands[0]
        stack_bb = h['hero_stack'] / h['blinds_bb']
        self.assertAlmostEqual(stack_bb, 50.0)


# ── Unit Tests: HandData hero_stack field ────────────────────────────────────

class TestHandDataHeroStack(unittest.TestCase):

    def test_hero_stack_in_slots(self):
        self.assertIn('hero_stack', HandData.__slots__)

    def test_hero_stack_set_in_constructor(self):
        hand = HandData(
            hand_id='H1', platform='GGPoker', game_type='cash',
            date='2026-01-15', blinds_sb=0.25, blinds_bb=0.50,
            hero_cards='Ah Kd', hero_position='BTN',
            invested=1.0, won=0.0, net=-1.0, rake=0.0,
            table_name='T', num_players=6,
            hero_stack=100.0,
        )
        self.assertEqual(hand.hero_stack, 100.0)

    def test_hero_stack_defaults_to_none(self):
        hand = HandData(hand_id='H1', platform='GGPoker')
        self.assertIsNone(hand.hero_stack)


# ── Unit Tests: GGPoker parser hero_stack ────────────────────────────────────

class TestGGPokerParserHeroStack(unittest.TestCase):
    """Tests that GGPoker parser extracts and saves hero_stack."""

    def _make_hand_text(self, stack='$50.00'):
        return f"""Poker Hand #RC0000001: Hold'em No Limit ($0.25/$0.50) - 2026/01/15 20:00:00
Table 'TestTable' 6-max Seat #3 is the button
Seat 1: Player1 ($50.00 in chips)
Seat 3: Hero ({stack} in chips)
Hero: posts small blind $0.25
Player1: posts big blind $0.50
*** HOLE CARDS ***
Dealt to Hero [Ah Kd]
Hero: raises $1.50 to $2.00
Player1: folds
Hero collected $1.00 from pot
*** SUMMARY ***
"""

    def test_hero_stack_extracted(self):
        from src.parsers.ggpoker import GGPokerParser
        parser = GGPokerParser()
        hand = parser.parse_single_hand(self._make_hand_text('$50.00'))
        self.assertIsNotNone(hand)
        self.assertIsNotNone(hand.hero_stack)
        self.assertAlmostEqual(hand.hero_stack, 50.0, delta=0.01)

    def test_hero_stack_large_value(self):
        from src.parsers.ggpoker import GGPokerParser
        parser = GGPokerParser()
        hand = parser.parse_single_hand(self._make_hand_text('$1,234.56'))
        self.assertIsNotNone(hand)
        self.assertAlmostEqual(hand.hero_stack, 1234.56, delta=0.01)

    def test_hero_stack_small_shove_zone(self):
        from src.parsers.ggpoker import GGPokerParser
        parser = GGPokerParser()
        hand = parser.parse_single_hand(self._make_hand_text('$6.00'))
        self.assertIsNotNone(hand)
        self.assertAlmostEqual(hand.hero_stack, 6.0, delta=0.01)
        # 6.0 / 0.50 = 12 BB → shove zone
        stack_bb = hand.hero_stack / hand.blinds_bb
        self.assertEqual(CashAnalyzer._classify_stack_tier(stack_bb), 'shove')


# ── Unit Tests: LeakFinder stack depth ───────────────────────────────────────

class TestLeakFinderStackDepth(unittest.TestCase):
    """Tests for LeakFinder._detect_stack_depth_leaks()."""

    def _setup_analyzer_with_many_hands(self, tier='deep', stack_bb=60.0,
                                         raises=True):
        conn, repo = _setup_db()
        blinds_bb = 0.50
        for i in range(20):
            hero_stack = stack_bb * blinds_bb
            _insert_raise_fold_hand(
                repo, f'H{i}', hero_stack=hero_stack,
                blinds_bb=blinds_bb, hero_position='BTN',
                hero_raises=raises,
            )
        return CashAnalyzer(repo, year='2026')

    def test_detect_stack_depth_leaks_called_in_find_leaks(self):
        """find_leaks() result has no errors from stack depth analysis."""
        from src.analyzers.leak_finder import LeakFinder
        conn, repo = _setup_db()
        # Insert enough hands for overall stats
        for i in range(60):
            _insert_raise_fold_hand(
                repo, f'H{i}', hero_stack=30.0 * 0.50,
                blinds_bb=0.50, hero_position='BTN',
                hero_raises=(i % 2 == 0),
            )
        analyzer = CashAnalyzer(repo, year='2026')
        finder = LeakFinder(analyzer, repo, year='2026')
        result = finder.find_leaks()
        self.assertIn('leaks', result)
        self.assertIn('health_score', result)

    def test_stack_depth_leak_name_has_tier_label(self):
        """Leak names for stack_depth category include tier label."""
        from src.analyzers.leak_finder import LeakFinder
        name = LeakFinder._leak_name('vpip', 'too_low', 'stack_depth', '25-50 BB')
        self.assertIn('25-50 BB', name)
        self.assertIn('VPIP', name)

    def test_stack_depth_suggestion_has_tier_label(self):
        """Suggestions for stack_depth include tier info."""
        from src.analyzers.leak_finder import LeakFinder
        suggestion = LeakFinder._leak_suggestion('vpip', 'too_high', 'stack_depth', '<15 BB')
        self.assertIn('<15 BB', suggestion)

    def test_tier_with_few_hands_skipped(self):
        """Stack depth tier with < MIN_HANDS_STACK_TIER hands not checked."""
        from src.analyzers.leak_finder import LeakFinder
        conn, repo = _setup_db()
        # Only 5 hands with stack → below threshold of 15
        for i in range(5):
            _insert_raise_fold_hand(
                repo, f'H{i}', hero_stack=30.0 * 0.50,
                blinds_bb=0.50, hero_position='BTN', hero_raises=False,
            )
        analyzer = CashAnalyzer(repo, year='2026')
        finder = LeakFinder(analyzer, repo, year='2026')
        # Should not crash
        stack_data = analyzer.get_stack_depth_stats()
        leaks = finder._detect_stack_depth_leaks(stack_data.get('by_tier', {}))
        # With 5 hands, no tier should exceed MIN_HANDS_STACK_TIER
        self.assertEqual(leaks, [])


# ── Unit Tests: HTML rendering ───────────────────────────────────────────────

class TestRenderStackDepthAnalysis(unittest.TestCase):
    """Tests for _render_stack_depth_analysis()."""

    def _make_stack_data(self, tiers=None):
        if tiers is None:
            tiers = {
                'deep': {
                    'label': '50+ BB', 'total_hands': 100,
                    'vpip': 24.0, 'vpip_health': 'good',
                    'pfr': 20.0, 'pfr_health': 'good',
                    'three_bet': 8.0, 'three_bet_health': 'good',
                    'af': 2.5, 'af_health': 'good',
                    'cbet': 65.0, 'cbet_health': 'good',
                    'wtsd': 28.0, 'wtsd_health': 'good',
                    'wsd': 50.0, 'wsd_health': 'good',
                    'net': 50.0, 'net_per_hand': 0.5, 'bb_per_100': 5.0,
                    'winrate_health': 'good',
                },
                'shove': {
                    'label': '<15 BB', 'total_hands': 30,
                    'vpip': 40.0, 'vpip_health': 'good',
                    'pfr': 38.0, 'pfr_health': 'good',
                    'three_bet': 2.0, 'three_bet_health': 'good',
                    'af': 0.5, 'af_health': 'danger',
                    'cbet': 50.0, 'cbet_health': 'warning',
                    'wtsd': 60.0, 'wtsd_health': 'warning',
                    'wsd': 45.0, 'wsd_health': 'warning',
                    'net': -10.0, 'net_per_hand': -0.33, 'bb_per_100': -5.0,
                    'winrate_health': 'danger',
                },
            }
        return {
            'by_tier': tiers,
            'by_position_tier': {
                'BTN': {
                    'deep': {
                        'label': '50+ BB', 'total_hands': 50,
                        'vpip': 30.0, 'pfr': 25.0,
                        'bb_per_100': 8.0, 'winrate_health': 'good',
                    }
                }
            },
            'tier_order': ['deep', 'medium', 'shallow', 'shove'],
            'tier_labels': {
                'deep': '50+ BB', 'medium': '25-50 BB',
                'shallow': '15-25 BB', 'shove': '<15 BB',
            },
            'hands_with_stack': 130,
            'hands_total': 150,
        }

    def test_renders_non_empty(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertTrue(len(html) > 0)

    def test_contains_section_header(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('Stack Depth', html)

    def test_contains_deep_tier_label(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('50+ BB', html)

    def test_contains_shove_tier_label(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('<15 BB', html)

    def test_contains_health_badge_good(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('badge-good', html)

    def test_contains_health_badge_warning(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('badge-warning', html)

    def test_contains_danger_badge_for_losses(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('badge-danger', html)

    def test_contains_vpip_values(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('24.0%', html)   # deep VPIP
        self.assertIn('40.0%', html)   # shove VPIP

    def test_contains_position_tier_table(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('BTN', html)
        self.assertIn('30.0%', html)   # BTN deep VPIP

    def test_empty_by_tier_returns_empty(self):
        result = _render_stack_depth_analysis({'by_tier': {}})
        self.assertEqual(result, '')

    def test_coverage_shown(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        # Coverage: 130/150 hands
        self.assertIn('130', html)
        self.assertIn('150', html)

    def test_winrate_bb100_positive(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('+5.0', html)  # deep bb_per_100 = +5.0

    def test_winrate_bb100_negative(self):
        html = _render_stack_depth_analysis(self._make_stack_data())
        self.assertIn('-5.0', html)  # shove bb_per_100 = -5.0

    def test_no_position_tier_table_when_empty(self):
        data = self._make_stack_data()
        data['by_position_tier'] = {}
        html = _render_stack_depth_analysis(data)
        # Should still render tier table but no position table
        self.assertIn('50+ BB', html)
        self.assertNotIn('VPIP e PFR por Posi', html)


# ── Integration Tests ─────────────────────────────────────────────────────────

class TestStackDepthIntegration(unittest.TestCase):
    """Integration tests: end-to-end from DB insertion to HTML."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, year='2026')

    def _insert_batch(self, n_deep=20, n_shove=15):
        """Insert n_deep deep-stack hands and n_shove shove-zone hands."""
        for i in range(n_deep):
            _insert_raise_fold_hand(
                self.repo, f'D{i}', hero_stack=60.0 * 0.50,
                blinds_bb=0.50, hero_position='BTN',
                hero_raises=(i % 2 == 0),
                net=1.0 if i % 2 == 0 else -0.5,
            )
        for i in range(n_shove):
            _insert_raise_fold_hand(
                self.repo, f'S{i}', hero_stack=8.0 * 0.50,
                blinds_bb=0.50, hero_position='BTN',
                hero_raises=(i % 3 != 0),
                net=-0.5 if i % 3 == 0 else 1.5,
            )

    def test_full_pipeline_produces_tiers(self):
        self._insert_batch()
        result = self.analyzer.get_stack_depth_stats()
        self.assertIn('deep', result['by_tier'])
        self.assertIn('shove', result['by_tier'])
        self.assertEqual(result['by_tier']['deep']['total_hands'], 20)
        self.assertEqual(result['by_tier']['shove']['total_hands'], 15)

    def test_hands_with_stack_accurate(self):
        self._insert_batch(n_deep=20, n_shove=15)
        result = self.analyzer.get_stack_depth_stats()
        self.assertEqual(result['hands_with_stack'], 35)

    def test_health_badges_applied(self):
        self._insert_batch()
        result = self.analyzer.get_stack_depth_stats()
        for tier_name, tier_data in result['by_tier'].items():
            for badge in ('vpip_health', 'pfr_health'):
                self.assertIn(tier_data[badge], ('good', 'warning', 'danger'))

    def test_html_renders_from_db(self):
        self._insert_batch()
        result = self.analyzer.get_stack_depth_stats()
        html = _render_stack_depth_analysis(result)
        self.assertIn('Stack Depth', html)
        self.assertIn('50+ BB', html)
        self.assertIn('<15 BB', html)

    def test_config_affects_health_badges(self):
        """Using custom config changes health classification."""
        import json
        import tempfile
        import os

        # Create config with very narrow deep VPIP range → will be 'danger' for most values
        custom = _default_data()
        custom['stack_depth']['vpip']['deep'] = {'healthy': [24, 26], 'warning': [23, 27]}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(custom, f)
            cfg_path = f.name

        try:
            cfg = TargetsConfig.load(cfg_path)
            conn, repo = _setup_db()
            analyzer = CashAnalyzer(repo, year='2026', config=cfg)
            # Insert hands with VPIP outside the narrow range
            for i in range(20):
                _insert_raise_fold_hand(
                    repo, f'H{i}', hero_stack=30.0,
                    blinds_bb=0.50, hero_position='BTN',
                    hero_raises=(i % 2 == 0),  # 50% VPIP — way above [24,26]
                )
            result = analyzer.get_stack_depth_stats()
            if 'deep' in result['by_tier']:
                health = result['by_tier']['deep']['vpip_health']
                # 50% VPIP with healthy [24,26] → danger
                self.assertIn(health, ('warning', 'danger'))
        finally:
            os.unlink(cfg_path)


if __name__ == '__main__':
    unittest.main()
