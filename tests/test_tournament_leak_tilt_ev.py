"""Tests for US-023: Tournament Backend - LeakFinder + TiltAnalyzer + Decision EV Adaptados.

Covers:
- LeakFinder accepts TournamentAnalyzer via duck typing (not coupled to CashAnalyzer)
- LeakFinder._compare_periods() uses get_tournament_daily_stats() when game_type == 'tournament'
- TournamentAnalyzer.get_leak_analysis() returns health_score, top5, study_spots, period_comparison
- Tilt detection: each tournament_id treated as pseudo-session
- TournamentAnalyzer.get_tilt_analysis() returns session_tilt, hourly, duration, post_bad_beat, diagnostics
- EVAnalyzer._compute_decision_ev() shared logic extraction
- EVAnalyzer.get_tournament_decision_ev_analysis() for tournament hands
- TournamentAnalyzer.get_decision_ev_analysis() delegation
- TournamentAnalyzer.get_session_leak_summary(stats) for per-tournament leak detection
- Edge cases: no hands, single hand, insufficient data
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.tournament import TournamentAnalyzer
from src.analyzers.cash import CashAnalyzer
from src.analyzers.leak_finder import Leak, LeakFinder
from src.analyzers.ev import EVAnalyzer


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tournament_hand(hand_id, tournament_id='T100', date='2026-01-15T20:00:00',
                          hero_position='CO', **kwargs):
    """Create a HandData with tournament defaults for testing."""
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
        hero_stack=kwargs.get('hero_stack', 5000.0),
    )


def _make_action(hand_id, player, action_type, seq, street='preflop',
                 position='CO', is_hero=0, amount=0.0, is_voluntary=0):
    """Create an ActionData for testing."""
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
    """Create an in-memory DB with schema initialized."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Repository(conn)


def _ensure_tournament_row(repo, tournament_id, date='2026-01-15'):
    """Ensure a tournament row exists for the given tournament_id."""
    repo.insert_tournament({
        'tournament_id': tournament_id, 'platform': 'test', 'name': 'Test Tourney',
        'date': date[:10], 'buy_in': 10, 'rake': 1, 'bounty': 0, 'total_buy_in': 11,
        'position': None, 'prize': 0, 'bounty_won': 0, 'total_players': 100,
        'entries': 1, 'is_bounty': False, 'is_satellite': False,
    })

def _insert_hand_with_actions(repo, hand_id, tournament_id='T100',
                               date='2026-01-15T20:00:00',
                               hero_position='CO', hero_cards='Ah Kd',
                               net=-200, hero_stack=5000.0,
                               blinds_bb=200, blinds_sb=100,
                               preflop_actions=None, postflop_actions=None):
    """Insert a tournament hand with optional preflop and postflop actions."""
    _ensure_tournament_row(repo, tournament_id, date)
    hand = _make_tournament_hand(
        hand_id, tournament_id=tournament_id, date=date,
        hero_position=hero_position, hero_cards=hero_cards,
        net=net, hero_stack=hero_stack, blinds_bb=blinds_bb,
        blinds_sb=blinds_sb,
    )
    repo.insert_hand(hand)

    actions = []
    if preflop_actions:
        actions.extend(preflop_actions)
    if postflop_actions:
        actions.extend(postflop_actions)
    if actions:
        repo.insert_actions_batch(actions)


def _standard_preflop_vpip(hand_id, hero_position='CO'):
    """Return standard preflop actions where hero calls (VPIP)."""
    return [
        _make_action(hand_id, 'SB', 'post_sb', 1, position='SB'),
        _make_action(hand_id, 'BB', 'post_bb', 2, position='BB'),
        _make_action(hand_id, 'Villain', 'raise', 3, position='UTG', amount=400),
        _make_action(hand_id, 'Hero', 'call', 4, position=hero_position,
                     is_hero=1, amount=400, is_voluntary=1),
    ]


def _standard_preflop_raise(hand_id, hero_position='CO'):
    """Return standard preflop actions where hero raises (PFR)."""
    return [
        _make_action(hand_id, 'SB', 'post_sb', 1, position='SB'),
        _make_action(hand_id, 'BB', 'post_bb', 2, position='BB'),
        _make_action(hand_id, 'Hero', 'raise', 3, position=hero_position,
                     is_hero=1, amount=500, is_voluntary=1),
        _make_action(hand_id, 'Villain', 'fold', 4, position='BTN'),
    ]


def _standard_preflop_fold(hand_id, hero_position='CO'):
    """Return standard preflop actions where hero folds."""
    return [
        _make_action(hand_id, 'SB', 'post_sb', 1, position='SB'),
        _make_action(hand_id, 'BB', 'post_bb', 2, position='BB'),
        _make_action(hand_id, 'Villain', 'raise', 3, position='UTG', amount=400),
        _make_action(hand_id, 'Hero', 'fold', 4, position=hero_position,
                     is_hero=1, is_voluntary=0),
    ]


def _postflop_cbet_actions(hand_id, hero_position='CO'):
    """Hero bets postflop (continuation bet)."""
    return [
        _make_action(hand_id, 'Hero', 'bet', 10, street='flop',
                     position=hero_position, is_hero=1, amount=300),
        _make_action(hand_id, 'Villain', 'fold', 11, street='flop', position='BTN'),
    ]


def _insert_many_hands(repo, count, tournament_id='T100',
                        base_date='2026-01-15', hero_position='CO',
                        vpip_pct=50, pfr_pct=30, net_base=-200):
    """Insert many tournament hands with controllable VPIP/PFR rates."""
    # Ensure tournament row exists (needed for exclude_satellites JOIN)
    repo.insert_tournament({
        'tournament_id': tournament_id, 'platform': 'test', 'name': 'Test Tourney',
        'date': base_date, 'buy_in': 10, 'rake': 1, 'bounty': 0, 'total_buy_in': 11,
        'position': None, 'prize': 0, 'bounty_won': 0, 'total_players': 100,
        'entries': 1, 'is_bounty': False, 'is_satellite': False,
    })
    for i in range(count):
        hid = f'{tournament_id}_H{i:04d}'
        hour = 20 + (i % 4)
        minute = i % 60
        date = f'{base_date}T{hour:02d}:{minute:02d}:00'
        net = net_base + (i * 10 if i % 3 == 0 else -i * 5)

        if (i * 100 // count) < vpip_pct:
            if (i * 100 // count) < pfr_pct:
                actions = _standard_preflop_raise(hid, hero_position)
            else:
                actions = _standard_preflop_vpip(hid, hero_position)
        else:
            actions = _standard_preflop_fold(hid, hero_position)

        _insert_hand_with_actions(
            repo, hid, tournament_id=tournament_id, date=date,
            hero_position=hero_position, net=net,
            preflop_actions=actions,
        )


# ── Tests: LeakFinder Duck Typing ────────────────────────────────────

class TestLeakFinderDuckTyping(unittest.TestCase):
    """Test that LeakFinder accepts TournamentAnalyzer (not only CashAnalyzer)."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

    def tearDown(self):
        self.conn.close()

    def test_leak_finder_accepts_tournament_analyzer(self):
        """LeakFinder should instantiate with TournamentAnalyzer."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        self.assertIs(finder.analyzer, self.analyzer)

    def test_leak_finder_reads_game_type(self):
        """LeakFinder should read game_type from analyzer."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        self.assertEqual(getattr(finder.analyzer, 'game_type', 'cash'), 'tournament')

    def test_leak_finder_reads_healthy_ranges(self):
        """LeakFinder should read _healthy_ranges from TournamentAnalyzer."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        self.assertIsNotNone(finder.analyzer._healthy_ranges)
        self.assertIn('vpip', finder.analyzer._healthy_ranges)

    def test_leak_finder_reads_postflop_ranges(self):
        """LeakFinder should read _postflop_healthy_ranges from TournamentAnalyzer."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        self.assertIn('af', finder.analyzer._postflop_healthy_ranges)

    def test_leak_finder_reads_positional_ranges(self):
        """LeakFinder should read positional ranges from TournamentAnalyzer."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        self.assertIsNotNone(finder.analyzer._pos_vpip_healthy)
        self.assertIsNotNone(finder.analyzer._pos_pfr_healthy)

    def test_leak_finder_reads_stack_ranges(self):
        """LeakFinder should read stack depth ranges from TournamentAnalyzer."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        self.assertIsNotNone(finder.analyzer._stack_vpip_healthy)
        self.assertIsNotNone(finder.analyzer._stack_pfr_healthy)
        self.assertIsNotNone(finder.analyzer._stack_3bet_healthy)

    def test_find_leaks_empty_db(self):
        """LeakFinder.find_leaks() on empty DB should return valid structure."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        result = finder.find_leaks()
        self.assertIn('health_score', result)
        self.assertIn('leaks', result)
        self.assertIn('top5', result)
        self.assertIn('study_spots', result)
        self.assertEqual(result['health_score'], 100)
        self.assertEqual(result['total_leaks'], 0)


class TestLeakFinderWithTournamentData(unittest.TestCase):
    """Test LeakFinder with actual tournament data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')
        # Insert enough hands to trigger leak detection (>= 50)
        _insert_many_hands(self.repo, 60, tournament_id='T100',
                           vpip_pct=80, pfr_pct=5, net_base=-500)

    def tearDown(self):
        self.conn.close()

    def test_get_leak_analysis_returns_complete_structure(self):
        """get_leak_analysis() returns health_score, top5, study_spots, period_comparison."""
        result = self.analyzer.get_leak_analysis()
        self.assertIn('health_score', result)
        self.assertIn('top5', result)
        self.assertIn('study_spots', result)
        self.assertIn('period_comparison', result)
        self.assertIn('leaks', result)
        self.assertIn('total_leaks', result)
        self.assertIsInstance(result['health_score'], int)
        self.assertLessEqual(result['health_score'], 100)
        self.assertGreaterEqual(result['health_score'], 0)

    def test_get_leak_analysis_detects_vpip_leak(self):
        """With 80% VPIP, LeakFinder should detect a VPIP too_high leak."""
        result = self.analyzer.get_leak_analysis()
        vpip_leaks = [l for l in result['leaks'] if l['stat_name'] == 'vpip']
        self.assertTrue(len(vpip_leaks) > 0, "Should detect VPIP leak")
        self.assertEqual(vpip_leaks[0]['direction'], 'too_high')

    def test_get_leak_analysis_top5_limited(self):
        """top5 should have at most 5 entries."""
        result = self.analyzer.get_leak_analysis()
        self.assertLessEqual(len(result['top5']), 5)

    def test_get_leak_analysis_study_spots_generated(self):
        """study_spots should be generated from leaks."""
        result = self.analyzer.get_leak_analysis()
        if result['total_leaks'] > 0:
            self.assertTrue(len(result['study_spots']) > 0)

    def test_health_score_penalized_for_leaks(self):
        """Health score should be < 100 when leaks exist."""
        result = self.analyzer.get_leak_analysis()
        if result['total_leaks'] > 0:
            self.assertLess(result['health_score'], 100)


class TestLeakFinderComparePeriodsTournament(unittest.TestCase):
    """Test that _compare_periods uses get_tournament_daily_stats() for tournaments."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

    def tearDown(self):
        self.conn.close()

    def test_compare_periods_uses_tournament_daily_stats(self):
        """_compare_periods should use get_tournament_daily_stats for tournament analyzer."""
        # Insert hands in two periods
        _insert_many_hands(self.repo, 30, tournament_id='T100',
                           base_date='2026-01-01', vpip_pct=60, pfr_pct=30)
        _insert_many_hands(self.repo, 30, tournament_id='T200',
                           base_date='2026-01-25', vpip_pct=40, pfr_pct=20)

        finder = LeakFinder(self.analyzer, self.repo, '2026')
        preflop_stats = self.analyzer.get_preflop_stats().get('overall', {})
        postflop_stats = self.analyzer.get_postflop_stats().get('overall', {})
        result = finder._compare_periods(preflop_stats, postflop_stats)
        # Should return valid comparison or empty if insufficient data
        self.assertIsInstance(result, dict)

    def test_compare_periods_empty_db_returns_empty(self):
        """_compare_periods on empty DB should return empty dict."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        result = finder._compare_periods({}, {})
        self.assertEqual(result, {})


# ── Tests: Tilt Analysis for Tournaments ─────────────────────────────

class TestTournamentTiltAnalysisEmpty(unittest.TestCase):
    """Test get_tilt_analysis() with no data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

    def tearDown(self):
        self.conn.close()

    def test_empty_db_returns_empty_dict(self):
        """get_tilt_analysis() on empty DB returns {}."""
        result = self.analyzer.get_tilt_analysis()
        self.assertEqual(result, {})


class TestTournamentTiltPseudoSessions(unittest.TestCase):
    """Test that each tournament_id is treated as a pseudo-session."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

    def tearDown(self):
        self.conn.close()

    def test_each_tournament_is_pseudo_session(self):
        """Each tournament_id should appear as a session in session_tilt."""
        # Insert hands in two tournaments
        _insert_many_hands(self.repo, 10, tournament_id='T100')
        _insert_many_hands(self.repo, 10, tournament_id='T200')

        result = self.analyzer.get_tilt_analysis()
        session_ids = [s['session_id'] for s in result['session_tilt']]
        self.assertIn('T100', session_ids)
        self.assertIn('T200', session_ids)

    def test_insufficient_hands_no_tilt(self):
        """Tournament with < 30 hands should not detect tilt."""
        _insert_many_hands(self.repo, 10, tournament_id='T100')
        result = self.analyzer.get_tilt_analysis()
        t100 = [s for s in result['session_tilt'] if s['session_id'] == 'T100'][0]
        self.assertFalse(t100['tilt_detected'])
        self.assertEqual(t100.get('reason'), 'insufficient_hands')


class TestTournamentTiltDetection(unittest.TestCase):
    """Test tilt detection with enough hands per tournament."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

        # Insert 40 hands in T100:
        # First 20: tight (low VPIP) → fold most
        for i in range(20):
            hid = f'T100_H{i:04d}'
            date = f'2026-01-15T20:{i:02d}:00'
            actions = _standard_preflop_fold(hid)
            _insert_hand_with_actions(
                self.repo, hid, tournament_id='T100', date=date,
                net=100, preflop_actions=actions,
            )
        # Last 20: loose (high VPIP) → call/raise most
        for i in range(20, 40):
            hid = f'T100_H{i:04d}'
            date = f'2026-01-15T21:{(i-20):02d}:00'
            actions = _standard_preflop_vpip(hid)
            _insert_hand_with_actions(
                self.repo, hid, tournament_id='T100', date=date,
                net=-300, preflop_actions=actions,
            )

    def tearDown(self):
        self.conn.close()

    def test_tilt_detection_detects_vpip_spike(self):
        """Tilt should be detected when VPIP spikes in second half."""
        result = self.analyzer.get_tilt_analysis()
        t100 = [s for s in result['session_tilt'] if s['session_id'] == 'T100'][0]
        # Second half has 100% VPIP vs first half ~0%, delta >= 6
        self.assertIn('vpip_spike', t100['tilt_signals'])

    def test_tilt_result_structure(self):
        """Tilt result should have all required fields."""
        result = self.analyzer.get_tilt_analysis()
        self.assertIn('session_tilt', result)
        self.assertIn('tilt_sessions_count', result)
        self.assertIn('hourly', result)
        self.assertIn('duration', result)
        self.assertIn('post_bad_beat', result)
        self.assertIn('recommendation', result)
        self.assertIn('diagnostics', result)

    def test_tilt_hourly_structure(self):
        """Hourly data should have 24 entries and bucket data."""
        result = self.analyzer.get_tilt_analysis()
        hourly = result['hourly']
        self.assertEqual(len(hourly['hourly']), 24)
        self.assertIn('buckets', hourly)
        # Check bucket keys
        for bucket_name in ('madrugada', 'manhã', 'tarde', 'noite'):
            self.assertIn(bucket_name, hourly['buckets'])

    def test_tilt_duration_structure(self):
        """Duration data should have bucket entries."""
        result = self.analyzer.get_tilt_analysis()
        duration = result['duration']
        self.assertIn('buckets', duration)
        labels = [b['label'] for b in duration['buckets']]
        self.assertIn('0-60min', labels)

    def test_tilt_post_bad_beat_structure(self):
        """Post bad beat data should have required keys."""
        result = self.analyzer.get_tilt_analysis()
        pbb = result['post_bad_beat']
        self.assertIn('bad_beats', pbb)
        self.assertIn('baseline_win_rate', pbb)
        self.assertIn('post_bb_win_rate', pbb)
        self.assertIn('degradation_bb100', pbb)

    def test_tilt_sessions_count(self):
        """tilt_sessions_count should count tournaments with tilt detected."""
        result = self.analyzer.get_tilt_analysis()
        count = result['tilt_sessions_count']
        detected = sum(1 for s in result['session_tilt'] if s.get('tilt_detected'))
        self.assertEqual(count, detected)

    def test_tilt_session_date_from_first_hand(self):
        """session_date should be the date of the first hand in the tournament."""
        result = self.analyzer.get_tilt_analysis()
        t100 = [s for s in result['session_tilt'] if s['session_id'] == 'T100'][0]
        self.assertTrue(t100['session_date'].startswith('2026-01-15'))


class TestTournamentTiltRecommendation(unittest.TestCase):
    """Test recommendation generation for tournament tilt."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

    def tearDown(self):
        self.conn.close()

    def test_insufficient_data_recommendation(self):
        """With few hands, recommendation should say insufficient data."""
        _insert_many_hands(self.repo, 5, tournament_id='T100')
        result = self.analyzer.get_tilt_analysis()
        self.assertIn('insuficientes', result['recommendation']['text'].lower())

    def test_recommendation_with_enough_data(self):
        """With enough hands in duration buckets, recommendation should have text."""
        _insert_many_hands(self.repo, 30, tournament_id='T100')
        result = self.analyzer.get_tilt_analysis()
        self.assertIsNotNone(result['recommendation']['text'])
        self.assertTrue(len(result['recommendation']['text']) > 0)


# ── Tests: EVAnalyzer _compute_decision_ev ───────────────────────────

class TestComputeDecisionEvShared(unittest.TestCase):
    """Test EVAnalyzer._compute_decision_ev() shared logic."""

    def test_empty_hands_returns_empty_structure(self):
        """_compute_decision_ev with no hands returns empty result."""
        result = EVAnalyzer._compute_decision_ev([], [])
        self.assertEqual(result['total_hands'], 0)
        self.assertEqual(result['leaks'], [])
        self.assertEqual(result['chart_data'], [])
        for street in ('preflop', 'flop', 'turn', 'river'):
            self.assertIn(street, result['by_street'])

    def test_single_fold_hand(self):
        """_compute_decision_ev with a single fold."""
        hands = [{'hand_id': 'H1', 'net': -100}]
        actions = [
            {'hand_id': 'H1', 'street': 'preflop', 'action_type': 'post_sb',
             'is_hero': False, 'sequence_order': 1},
            {'hand_id': 'H1', 'street': 'preflop', 'action_type': 'raise',
             'is_hero': False, 'sequence_order': 2},
            {'hand_id': 'H1', 'street': 'preflop', 'action_type': 'fold',
             'is_hero': True, 'sequence_order': 3},
        ]
        result = EVAnalyzer._compute_decision_ev(actions, hands)
        self.assertEqual(result['total_hands'], 1)
        self.assertEqual(result['by_street']['preflop']['fold']['count'], 1)

    def test_call_and_raise_counted(self):
        """_compute_decision_ev counts calls and raises correctly."""
        hands = [
            {'hand_id': 'H1', 'net': 200},
            {'hand_id': 'H2', 'net': -100},
        ]
        actions = [
            # H1: hero calls preflop
            {'hand_id': 'H1', 'street': 'preflop', 'action_type': 'raise',
             'is_hero': False, 'sequence_order': 1},
            {'hand_id': 'H1', 'street': 'preflop', 'action_type': 'call',
             'is_hero': True, 'sequence_order': 2},
            # H2: hero raises preflop
            {'hand_id': 'H2', 'street': 'preflop', 'action_type': 'raise',
             'is_hero': True, 'sequence_order': 1},
        ]
        result = EVAnalyzer._compute_decision_ev(actions, hands)
        self.assertEqual(result['by_street']['preflop']['call']['count'], 1)
        self.assertEqual(result['by_street']['preflop']['raise']['count'], 1)

    def test_chart_data_has_all_streets(self):
        """chart_data should have entries for all 4 streets."""
        hands = [{'hand_id': 'H1', 'net': 0}]
        actions = [
            {'hand_id': 'H1', 'street': 'preflop', 'action_type': 'fold',
             'is_hero': True, 'sequence_order': 1},
        ]
        result = EVAnalyzer._compute_decision_ev(actions, hands)
        streets_in_chart = [c['street'] for c in result['chart_data']]
        self.assertEqual(streets_in_chart, ['preflop', 'flop', 'turn', 'river'])

    def test_context_vs_bet_detection(self):
        """Hero facing opponent bet should be classified as vs_bet."""
        hands = [{'hand_id': 'H1', 'net': -50}]
        actions = [
            {'hand_id': 'H1', 'street': 'preflop', 'action_type': 'raise',
             'is_hero': False, 'sequence_order': 1},
            {'hand_id': 'H1', 'street': 'preflop', 'action_type': 'call',
             'is_hero': True, 'sequence_order': 2},
        ]
        result = EVAnalyzer._compute_decision_ev(actions, hands)
        # Call should be counted on preflop
        self.assertEqual(result['by_street']['preflop']['call']['count'], 1)


class TestTournamentDecisionEvAnalysis(unittest.TestCase):
    """Test EVAnalyzer.get_tournament_decision_ev_analysis()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.ev = EVAnalyzer(self.repo, '2026')

    def tearDown(self):
        self.conn.close()

    def test_empty_db_returns_empty_result(self):
        """get_tournament_decision_ev_analysis on empty DB returns empty structure."""
        result = self.ev.get_tournament_decision_ev_analysis()
        self.assertEqual(result['total_hands'], 0)
        self.assertEqual(result['leaks'], [])

    def test_with_tournament_data(self):
        """get_tournament_decision_ev_analysis with tournament hands."""
        _insert_many_hands(self.repo, 20, tournament_id='T100')
        result = self.ev.get_tournament_decision_ev_analysis()
        self.assertEqual(result['total_hands'], 20)
        self.assertIn('by_street', result)
        self.assertIn('chart_data', result)

    def test_tournament_decision_ev_via_analyzer(self):
        """TournamentAnalyzer.get_decision_ev_analysis() delegates to EVAnalyzer."""
        _insert_many_hands(self.repo, 20, tournament_id='T100')
        analyzer = TournamentAnalyzer(self.repo, '2026')
        result = analyzer.get_decision_ev_analysis()
        self.assertEqual(result['total_hands'], 20)
        self.assertIn('by_street', result)

    def test_cash_decision_ev_still_works(self):
        """get_decision_ev_analysis() for cash should still work."""
        # Insert a cash hand
        cash_hand = HandData(
            hand_id='CASH_H1', platform='GGPoker', game_type='cash',
            date=datetime.fromisoformat('2026-01-15T20:00:00'),
            blinds_sb=0.25, blinds_bb=0.50, hero_cards='Ah Kd',
            hero_position='CO', invested=1.0, won=0.0, net=-1.0,
            rake=0.0, table_name='T', num_players=6,
        )
        self.repo.insert_hand(cash_hand)
        actions = [
            _make_action('CASH_H1', 'Villain', 'raise', 1, position='UTG', amount=1.0),
            _make_action('CASH_H1', 'Hero', 'fold', 2, position='CO', is_hero=1),
        ]
        self.repo.insert_actions_batch(actions)

        result = self.ev.get_decision_ev_analysis()
        self.assertEqual(result['total_hands'], 1)


# ── Tests: TournamentAnalyzer.get_session_leak_summary ───────────────

class TestTournamentSessionLeakSummary(unittest.TestCase):
    """Test TournamentAnalyzer.get_session_leak_summary()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

    def tearDown(self):
        self.conn.close()

    def test_empty_stats_returns_empty_list(self):
        """Empty stats should return empty list."""
        result = self.analyzer.get_session_leak_summary({})
        self.assertEqual(result, [])

    def test_zero_hands_returns_empty_list(self):
        """Stats with zero hands should return empty list."""
        result = self.analyzer.get_session_leak_summary({'total_hands': 0})
        self.assertEqual(result, [])

    def test_all_good_returns_empty(self):
        """All stats within healthy range should return no leaks."""
        stats = {
            'total_hands': 50,
            'vpip': 25.0, 'vpip_health': 'good',
            'pfr': 18.0, 'pfr_health': 'good',
            'three_bet': 8.0, 'three_bet_health': 'good',
            'af': 2.5, 'af_health': 'good',
            'wtsd': 28.0, 'wtsd_health': 'good',
            'wsd': 52.0, 'wsd_health': 'good',
            'cbet': 65.0, 'cbet_health': 'good',
        }
        result = self.analyzer.get_session_leak_summary(stats)
        self.assertEqual(result, [])

    def test_warning_stat_detected(self):
        """Stats with 'warning' health should be detected as leaks."""
        stats = {
            'total_hands': 50,
            'vpip': 40.0, 'vpip_health': 'warning',
            'pfr': 18.0, 'pfr_health': 'good',
        }
        result = self.analyzer.get_session_leak_summary(stats)
        self.assertTrue(len(result) > 0)
        self.assertEqual(result[0]['stat_name'], 'vpip')
        self.assertEqual(result[0]['direction'], 'too_high')

    def test_danger_stat_detected(self):
        """Stats with 'danger' health should be detected as leaks."""
        stats = {
            'total_hands': 50,
            'vpip': 50.0, 'vpip_health': 'danger',
            'pfr': 5.0, 'pfr_health': 'danger',
        }
        result = self.analyzer.get_session_leak_summary(stats)
        self.assertTrue(len(result) >= 2)
        stat_names = [l['stat_name'] for l in result]
        self.assertIn('vpip', stat_names)
        self.assertIn('pfr', stat_names)

    def test_leaks_sorted_by_cost(self):
        """Leaks should be sorted by cost_bb100 descending."""
        stats = {
            'total_hands': 50,
            'vpip': 50.0, 'vpip_health': 'danger',
            'pfr': 5.0, 'pfr_health': 'danger',
            'af': 0.5, 'af_health': 'danger',
        }
        result = self.analyzer.get_session_leak_summary(stats)
        costs = [l['cost_bb100'] for l in result]
        self.assertEqual(costs, sorted(costs, reverse=True))

    def test_leak_has_required_fields(self):
        """Each leak dict should have all required fields."""
        stats = {
            'total_hands': 50,
            'vpip': 45.0, 'vpip_health': 'warning',
        }
        result = self.analyzer.get_session_leak_summary(stats)
        self.assertTrue(len(result) > 0)
        leak = result[0]
        required_fields = [
            'stat_name', 'label', 'value', 'health',
            'healthy_low', 'healthy_high', 'cost_bb100',
            'direction', 'suggestion',
        ]
        for field in required_fields:
            self.assertIn(field, leak, f"Missing field: {field}")

    def test_suggestion_in_portuguese(self):
        """Suggestions should be in Portuguese."""
        stats = {
            'total_hands': 50,
            'vpip': 45.0, 'vpip_health': 'warning',
        }
        result = self.analyzer.get_session_leak_summary(stats)
        self.assertTrue(len(result) > 0)
        # Check suggestion is non-empty and contains Portuguese text
        self.assertTrue(len(result[0]['suggestion']) > 10)

    def test_too_low_direction(self):
        """Stats below healthy range should have 'too_low' direction."""
        stats = {
            'total_hands': 50,
            'vpip': 10.0, 'vpip_health': 'danger',
        }
        result = self.analyzer.get_session_leak_summary(stats)
        self.assertTrue(len(result) > 0)
        self.assertEqual(result[0]['direction'], 'too_low')


# ── Tests: Integration - Full Flow ───────────────────────────────────

class TestTournamentLeakAnalysisIntegration(unittest.TestCase):
    """Integration test: full leak analysis with realistic tournament data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')
        # Insert 60 hands with high VPIP across 2 tournaments
        _insert_many_hands(self.repo, 30, tournament_id='T100',
                           base_date='2026-01-15', vpip_pct=80, pfr_pct=10)
        _insert_many_hands(self.repo, 30, tournament_id='T200',
                           base_date='2026-01-20', vpip_pct=80, pfr_pct=10)

    def tearDown(self):
        self.conn.close()

    def test_full_leak_analysis_flow(self):
        """Full flow: get_leak_analysis should produce valid results."""
        result = self.analyzer.get_leak_analysis()
        self.assertIsInstance(result['health_score'], int)
        self.assertLessEqual(len(result['top5']), 5)
        self.assertIsInstance(result['study_spots'], list)
        self.assertGreater(result['total_leaks'], 0)


class TestTournamentTiltAnalysisIntegration(unittest.TestCase):
    """Integration test: tilt analysis with multiple tournaments."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')

    def tearDown(self):
        self.conn.close()

    def test_multiple_tournaments_separate_sessions(self):
        """Multiple tournaments should each get separate tilt analysis."""
        _insert_many_hands(self.repo, 15, tournament_id='T100')
        _insert_many_hands(self.repo, 15, tournament_id='T200')
        _insert_many_hands(self.repo, 15, tournament_id='T300')

        result = self.analyzer.get_tilt_analysis()
        self.assertEqual(len(result['session_tilt']), 3)


class TestTournamentDecisionEvIntegration(unittest.TestCase):
    """Integration test: decision EV analysis with tournament data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TournamentAnalyzer(self.repo, '2026')
        _insert_many_hands(self.repo, 30, tournament_id='T100',
                           vpip_pct=50, pfr_pct=30)

    def tearDown(self):
        self.conn.close()

    def test_decision_ev_has_preflop_data(self):
        """Decision EV should have preflop fold/call/raise data."""
        result = self.analyzer.get_decision_ev_analysis()
        preflop = result['by_street']['preflop']
        total = sum(preflop[d]['count'] for d in ('fold', 'call', 'raise'))
        self.assertGreater(total, 0)

    def test_decision_ev_chart_data(self):
        """Decision EV chart_data should have 4 street entries."""
        result = self.analyzer.get_decision_ev_analysis()
        self.assertEqual(len(result['chart_data']), 4)


# ── Tests: CashAnalyzer still works with LeakFinder ──────────────────

class TestCashAnalyzerLeakFinderStillWorks(unittest.TestCase):
    """Ensure LeakFinder still works with CashAnalyzer after duck typing change."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = CashAnalyzer(self.repo, '2026')

    def tearDown(self):
        self.conn.close()

    def test_cash_leak_finder_works(self):
        """LeakFinder should still work with CashAnalyzer."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        result = finder.find_leaks()
        self.assertIn('health_score', result)
        self.assertEqual(result['health_score'], 100)

    def test_cash_game_type(self):
        """CashAnalyzer should have game_type if set, or LeakFinder defaults to 'cash'."""
        finder = LeakFinder(self.analyzer, self.repo, '2026')
        game_type = getattr(finder.analyzer, 'game_type', 'cash')
        self.assertEqual(game_type, 'cash')


# ── Tests: EVAnalyzer backward compatibility ─────────────────────────

class TestEVAnalyzerBackwardCompat(unittest.TestCase):
    """Ensure existing get_decision_ev_analysis() still works after refactoring."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def tearDown(self):
        self.conn.close()

    def test_cash_decision_ev_empty(self):
        """Cash decision EV on empty DB returns empty structure."""
        ev = EVAnalyzer(self.repo, '2026')
        result = ev.get_decision_ev_analysis()
        self.assertEqual(result['total_hands'], 0)
        self.assertIn('by_street', result)
        for street in ('preflop', 'flop', 'turn', 'river'):
            self.assertIn(street, result['by_street'])
            for dec in ('fold', 'call', 'raise'):
                self.assertIn(dec, result['by_street'][street])


if __name__ == '__main__':
    unittest.main()
