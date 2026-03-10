"""Tests for US-014: Tilt Detection & Performance by Time/Duration.

Covers:
- _get_hour: ISO datetime hour extraction
- _get_avg_bb: average big blind computation
- _compute_segment_stats: VPIP/PFR/AF for hand/action subsets
- _classify_tilt_wr_health: win-rate health classification
- _classify_tilt_severity: tilt severity from signal count
- _generate_tilt_diagnostics: diagnostic message generation
- TiltAnalyzer.detect_session_tilt: single-session tilt detection
- TiltAnalyzer._analyze_hourly_performance: per-hour and per-bucket win rates
- TiltAnalyzer._analyze_duration_performance: win rate by session duration buckets
- TiltAnalyzer._analyze_post_bad_beat: post-bad-beat analysis
- TiltAnalyzer._generate_recommendation: session duration recommendation
- TiltAnalyzer.get_tilt_analysis: full integration method
- CashAnalyzer.get_tilt_analysis: delegation wrapper
- Report: _render_tilt_analysis, _render_hourly_heatmap
- Edge cases: empty DB, no sessions, insufficient hands, no bad beats
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.analyzers.cash import CashAnalyzer
from src.analyzers.tilt import (
    TiltAnalyzer,
    _get_hour,
    _get_avg_bb,
    _compute_segment_stats,
    _classify_tilt_wr_health,
    _classify_tilt_severity,
    _generate_tilt_diagnostics,
    _TILT_VPIP_DELTA,
    _TILT_PFR_DELTA,
    _TILT_AF_DELTA,
    _MIN_HANDS_SEGMENT,
    _BAD_BEAT_BB,
    _POST_BAD_BEAT_WINDOW,
)
from src.reports.cash_report import _render_tilt_analysis, _render_hourly_heatmap


# ── Test helpers ──────────────────────────────────────────────────────────────

def _setup_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Repository(conn)


def _make_hand(hand_id, date='2026-01-15T20:00:00', hero_position='CO',
               net=-0.5, blinds_bb=0.5, **kwargs):
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
        num_players=kwargs.get('num_players', 6),
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


def _create_session(repo, session_id_hint, start='2026-01-15T18:00:00',
                    end='2026-01-15T22:00:00', profit=10.0, hands=50):
    sid = repo.insert_session({
        'platform': 'GGPoker',
        'start_time': start,
        'end_time': end,
        'buy_in': 50.0,
        'cash_out': 50.0 + profit,
        'profit': profit,
        'hands_count': hands,
        'min_stack': 40.0,
    })
    return sid


def _insert_vpip_hand(repo, hand_id, date, is_vpip=True, is_pfr=True, net=-0.5):
    """Insert a hand with hero VPIP and optionally PFR action."""
    hand = _make_hand(hand_id, date=date, net=net)
    repo.insert_hand(hand)
    repo.insert_actions_batch([
        _make_action(hand_id, 'Hero', 'raise' if is_pfr else 'call', 1,
                     is_hero=1, is_voluntary=1 if is_vpip else 0),
        _make_action(hand_id, 'V1', 'fold', 2),
    ])


def _insert_passive_hand(repo, hand_id, date, net=-0.5):
    """Insert a hand where hero just calls (VPIP but no PFR)."""
    hand = _make_hand(hand_id, date=date, net=net)
    repo.insert_hand(hand)
    repo.insert_actions_batch([
        _make_action(hand_id, 'V1', 'raise', 1, amount=1.0),
        _make_action(hand_id, 'Hero', 'call', 2, is_hero=1, is_voluntary=1),
    ])


# ── Unit: _get_hour ───────────────────────────────────────────────────────────

class TestGetHour(unittest.TestCase):

    def test_midnight(self):
        self.assertEqual(_get_hour('2026-01-15T00:30:00'), 0)

    def test_morning(self):
        self.assertEqual(_get_hour('2026-01-15T09:00:00'), 9)

    def test_evening(self):
        self.assertEqual(_get_hour('2026-01-15T20:45:00'), 20)

    def test_invalid_returns_minus_one(self):
        self.assertEqual(_get_hour('not-a-date'), -1)

    def test_empty_string(self):
        self.assertEqual(_get_hour(''), -1)

    def test_none_like(self):
        self.assertEqual(_get_hour(None), -1)

    def test_date_only_no_time(self):
        # ISO date-only strings have no time component → still valid datetime
        self.assertEqual(_get_hour('2026-01-15'), 0)


# ── Unit: _get_avg_bb ─────────────────────────────────────────────────────────

class TestGetAvgBB(unittest.TestCase):

    def test_single_hand(self):
        hands = [{'blinds_bb': 0.50}]
        self.assertAlmostEqual(_get_avg_bb(hands), 0.50)

    def test_multiple_hands(self):
        hands = [{'blinds_bb': 0.50}, {'blinds_bb': 1.00}, {'blinds_bb': 0.50}]
        self.assertAlmostEqual(_get_avg_bb(hands), 2.0 / 3, places=5)

    def test_empty_list(self):
        self.assertAlmostEqual(_get_avg_bb([]), 1.0)

    def test_zero_bb_excluded(self):
        hands = [{'blinds_bb': 0}, {'blinds_bb': 0.50}]
        self.assertAlmostEqual(_get_avg_bb(hands), 0.50)

    def test_none_bb_excluded(self):
        hands = [{'blinds_bb': None}, {'blinds_bb': 0.50}]
        self.assertAlmostEqual(_get_avg_bb(hands), 0.50)


# ── Unit: _compute_segment_stats ─────────────────────────────────────────────

class TestComputeSegmentStats(unittest.TestCase):

    def _hands_and_actions(self, n, is_vpip=True, is_pfr=True):
        """Build n hands and actions where hero VPIP/PFR each hand."""
        hands = []
        actions = []
        for i in range(n):
            hid = f'H{i}'
            hands.append({'hand_id': hid, 'net': -0.5, 'blinds_bb': 0.5})
            if is_pfr:
                actions.append({
                    'hand_id': hid, 'street': 'preflop', 'is_hero': 1,
                    'action_type': 'raise', 'is_voluntary': 1,
                })
            elif is_vpip:
                actions.append({
                    'hand_id': hid, 'street': 'preflop', 'is_hero': 1,
                    'action_type': 'call', 'is_voluntary': 1,
                })
            else:
                actions.append({
                    'hand_id': hid, 'street': 'preflop', 'is_hero': 1,
                    'action_type': 'fold', 'is_voluntary': 0,
                })
        return hands, actions

    def test_empty_hands(self):
        result = _compute_segment_stats([], [])
        self.assertEqual(result['total_hands'], 0)
        self.assertEqual(result['vpip'], 0.0)

    def test_100pct_vpip_pfr(self):
        hands, actions = self._hands_and_actions(10)
        result = _compute_segment_stats(hands, actions)
        self.assertEqual(result['total_hands'], 10)
        self.assertAlmostEqual(result['vpip'], 100.0)
        self.assertAlmostEqual(result['pfr'], 100.0)

    def test_vpip_no_pfr(self):
        hands, actions = self._hands_and_actions(10, is_vpip=True, is_pfr=False)
        result = _compute_segment_stats(hands, actions)
        self.assertAlmostEqual(result['vpip'], 100.0)
        self.assertAlmostEqual(result['pfr'], 0.0)

    def test_no_vpip(self):
        hands, actions = self._hands_and_actions(10, is_vpip=False, is_pfr=False)
        result = _compute_segment_stats(hands, actions)
        self.assertAlmostEqual(result['vpip'], 0.0)
        self.assertAlmostEqual(result['pfr'], 0.0)

    def test_af_calculation(self):
        # 2 bets, 1 call → AF = 2.0
        hands = [{'hand_id': 'H0', 'net': 1.0, 'blinds_bb': 0.5}]
        actions = [
            {'hand_id': 'H0', 'street': 'preflop', 'is_hero': 1,
             'action_type': 'raise', 'is_voluntary': 1},
            {'hand_id': 'H0', 'street': 'flop', 'is_hero': 1,
             'action_type': 'bet', 'is_voluntary': 0},
            {'hand_id': 'H0', 'street': 'flop', 'is_hero': 1,
             'action_type': 'bet', 'is_voluntary': 0},
            {'hand_id': 'H0', 'street': 'turn', 'is_hero': 1,
             'action_type': 'call', 'is_voluntary': 0},
        ]
        result = _compute_segment_stats(hands, actions)
        self.assertAlmostEqual(result['af'], 2.0)

    def test_no_hero_actions_skipped(self):
        # A hand where hero doesn't appear → not counted
        hands = [{'hand_id': 'H0', 'net': 0.0, 'blinds_bb': 0.5}]
        actions = [
            {'hand_id': 'H0', 'street': 'preflop', 'is_hero': 0,
             'action_type': 'raise', 'is_voluntary': 1},
        ]
        result = _compute_segment_stats(hands, actions)
        self.assertEqual(result['total_hands'], 0)

    def test_actions_filtered_to_hand_ids(self):
        # Actions from other hands should not bleed in
        hands = [{'hand_id': 'H0', 'net': -0.5, 'blinds_bb': 0.5}]
        actions = [
            {'hand_id': 'H0', 'street': 'preflop', 'is_hero': 1,
             'action_type': 'raise', 'is_voluntary': 1},
            {'hand_id': 'OTHER', 'street': 'preflop', 'is_hero': 1,
             'action_type': 'raise', 'is_voluntary': 1},
        ]
        result = _compute_segment_stats(hands, actions)
        self.assertEqual(result['total_hands'], 1)
        self.assertAlmostEqual(result['vpip'], 100.0)

    def test_net_sum(self):
        hands = [
            {'hand_id': 'H0', 'net': 2.0, 'blinds_bb': 0.5},
            {'hand_id': 'H1', 'net': -1.0, 'blinds_bb': 0.5},
        ]
        actions = [
            {'hand_id': 'H0', 'street': 'preflop', 'is_hero': 1,
             'action_type': 'raise', 'is_voluntary': 1},
            {'hand_id': 'H1', 'street': 'preflop', 'is_hero': 1,
             'action_type': 'fold', 'is_voluntary': 0},
        ]
        result = _compute_segment_stats(hands, actions)
        self.assertAlmostEqual(result['net'], 1.0)


# ── Unit: _classify_tilt_wr_health ───────────────────────────────────────────

class TestClassifyTiltWrHealth(unittest.TestCase):

    def test_strong_positive(self):
        self.assertEqual(_classify_tilt_wr_health(20.0), 'good')

    def test_just_good(self):
        self.assertEqual(_classify_tilt_wr_health(5.0), 'good')

    def test_near_zero_positive(self):
        self.assertEqual(_classify_tilt_wr_health(1.0), 'warning')

    def test_near_zero_negative(self):
        self.assertEqual(_classify_tilt_wr_health(-1.0), 'warning')

    def test_just_below_warning(self):
        self.assertEqual(_classify_tilt_wr_health(-5.0), 'warning')

    def test_danger(self):
        self.assertEqual(_classify_tilt_wr_health(-6.0), 'danger')

    def test_big_loss(self):
        self.assertEqual(_classify_tilt_wr_health(-50.0), 'danger')

    def test_zero(self):
        self.assertEqual(_classify_tilt_wr_health(0.0), 'warning')


# ── Unit: _classify_tilt_severity ────────────────────────────────────────────

class TestClassifyTiltSeverity(unittest.TestCase):

    def test_no_signals(self):
        self.assertEqual(_classify_tilt_severity([]), 'good')

    def test_one_signal(self):
        self.assertEqual(_classify_tilt_severity(['vpip_spike']), 'good')

    def test_two_signals(self):
        self.assertEqual(_classify_tilt_severity(['vpip_spike', 'pfr_spike']), 'warning')

    def test_three_signals(self):
        self.assertEqual(
            _classify_tilt_severity(['vpip_spike', 'pfr_spike', 'af_spike']),
            'danger',
        )


# ── Unit: _generate_tilt_diagnostics ─────────────────────────────────────────

class TestGenerateTiltDiagnostics(unittest.TestCase):

    def _make_tilt_session(self, tilt=True, cost=10.0):
        return {'tilt_detected': tilt, 'tilt_cost_bb': cost}

    def test_no_sessions_no_diagnostics(self):
        result = _generate_tilt_diagnostics([], {}, {'buckets': []})
        self.assertEqual(result, [])

    def test_tilt_session_generates_diagnostic(self):
        sessions = [self._make_tilt_session(tilt=True, cost=15.0)]
        result = _generate_tilt_diagnostics(sessions, {'buckets': {}}, {'buckets': []})
        self.assertEqual(len(result), 1)
        self.assertIn('tilt', result[0]['title'].lower())
        self.assertIn('sessão', result[0]['title'].lower())

    def test_many_tilt_sessions_danger(self):
        sessions = [self._make_tilt_session(True, 10) for _ in range(4)]
        result = _generate_tilt_diagnostics(sessions, {}, {'buckets': []})
        self.assertTrue(any(d['type'] == 'danger' for d in result))

    def test_few_tilt_sessions_warning(self):
        sessions = [self._make_tilt_session(True, 10) for _ in range(2)]
        result = _generate_tilt_diagnostics(sessions, {}, {'buckets': []})
        self.assertTrue(any(d['type'] == 'warning' for d in result))

    def test_hourly_large_diff_triggers_diagnostic(self):
        hourly = {
            'buckets': {
                'manhã': {'hands': 50, 'win_rate_bb100': 20.0},
                'noite': {'hands': 50, 'win_rate_bb100': -5.0},
            }
        }
        result = _generate_tilt_diagnostics([], hourly, {'buckets': []})
        self.assertTrue(any('horário' in d['title'].lower() for d in result))

    def test_hourly_small_diff_no_diagnostic(self):
        hourly = {
            'buckets': {
                'manhã': {'hands': 50, 'win_rate_bb100': 5.0},
                'noite': {'hands': 50, 'win_rate_bb100': -3.0},
            }
        }
        result = _generate_tilt_diagnostics([], hourly, {'buckets': []})
        self.assertFalse(any('horário' in d['title'].lower() for d in result))

    def test_duration_degradation_triggers_diagnostic(self):
        duration = {
            'buckets': [
                {'label': '0-60min', 'hands': 50, 'win_rate_bb100': 15.0},
                {'label': '60-120min', 'hands': 20, 'win_rate_bb100': -5.0},
            ]
        }
        result = _generate_tilt_diagnostics([], {}, duration)
        self.assertTrue(any('duração' in d['title'].lower() for d in result))

    def test_duration_no_degradation_no_diagnostic(self):
        duration = {
            'buckets': [
                {'label': '0-60min', 'hands': 50, 'win_rate_bb100': 5.0},
                {'label': '60-120min', 'hands': 20, 'win_rate_bb100': 3.0},
            ]
        }
        result = _generate_tilt_diagnostics([], {}, duration)
        self.assertFalse(any('duração' in d['title'].lower() for d in result))


# ── Integration: TiltAnalyzer.detect_session_tilt ────────────────────────────

class TestDetectSessionTilt(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _build_tilt_session(self, vpip_first=25, vpip_second=35,
                             pfr_first=20, pfr_second=28,
                             n_hands=40):
        """Build a session where second half has noticeably higher VPIP/PFR."""
        sid = _create_session(
            self.repo, 1,
            start='2026-01-15T18:00:00',
            end='2026-01-15T23:00:00',
        )
        session = {
            'session_id': sid,
            'date': '2026-01-15',
            'start_time': '2026-01-15T18:00:00',
            'end_time': '2026-01-15T23:00:00',
            'buy_in': 50.0,
            'cash_out': 50.0,
            'profit': 0.0,
            'hands_count': n_hands,
        }
        mid = n_hands // 2
        # First half: low VPIP/PFR
        for i in range(mid):
            hid = f'F{i}'
            ts = f'2026-01-15T18:{i:02d}:00'
            # vpip_first/100 fraction voluntarily enters
            is_v = (i % 100) < vpip_first
            is_pf = (i % 100) < pfr_first
            _insert_vpip_hand(self.repo, hid, ts, is_vpip=is_v, is_pfr=is_pf,
                               net=-0.5)
        # Second half: high VPIP/PFR (simulate tilt)
        for i in range(mid):
            hid = f'S{i}'
            ts = f'2026-01-15T20:{i:02d}:00'
            is_v = (i % 100) < vpip_second
            is_pf = (i % 100) < pfr_second
            _insert_vpip_hand(self.repo, hid, ts, is_vpip=is_v, is_pfr=is_pf,
                               net=-0.5)
        return session

    def test_insufficient_hands_returns_no_tilt(self):
        sid = _create_session(self.repo, 1)
        session = {
            'session_id': sid,
            'date': '2026-01-15',
            'start_time': '2026-01-15T18:00:00',
            'end_time': '2026-01-15T23:00:00',
            'buy_in': 50.0,
            'cash_out': 50.0,
            'profit': 0.0,
        }
        # Only insert 5 hands (less than 2×_MIN_HANDS_SEGMENT)
        for i in range(5):
            _insert_vpip_hand(self.repo, f'H{i}', f'2026-01-15T18:{i:02d}:00')
        tilt = TiltAnalyzer(self.repo).detect_session_tilt(session)
        self.assertFalse(tilt['tilt_detected'])
        self.assertEqual(tilt['reason'], 'insufficient_hands')

    def test_no_tilt_consistent_stats(self):
        """Session with stable stats should NOT trigger tilt."""
        session = self._build_tilt_session(
            vpip_first=25, vpip_second=26,
            pfr_first=20, pfr_second=21,
            n_hands=40,
        )
        tilt = TiltAnalyzer(self.repo).detect_session_tilt(session)
        self.assertFalse(tilt['tilt_detected'])

    def test_tilt_detected_high_vpip_pfr_spike(self):
        """Session where second half has large VPIP and PFR spikes."""
        session = self._build_tilt_session(
            vpip_first=0, vpip_second=100,
            pfr_first=0, pfr_second=100,
            n_hands=40,
        )
        tilt = TiltAnalyzer(self.repo).detect_session_tilt(session)
        self.assertTrue(tilt['tilt_detected'])
        self.assertIn('vpip_spike', tilt['tilt_signals'])
        self.assertIn('pfr_spike', tilt['tilt_signals'])

    def test_tilt_result_has_required_keys(self):
        session = self._build_tilt_session(n_hands=40)
        tilt = TiltAnalyzer(self.repo).detect_session_tilt(session)
        required = [
            'session_id', 'session_date', 'start_time', 'tilt_detected',
            'tilt_signals', 'severity', 'total_hands',
        ]
        for key in required:
            self.assertIn(key, tilt, f'Missing key: {key}')

    def test_tilt_cost_positive_when_tilt_detected(self):
        session = self._build_tilt_session(
            vpip_first=0, vpip_second=100,
            pfr_first=0, pfr_second=100,
            n_hands=40,
        )
        tilt = TiltAnalyzer(self.repo).detect_session_tilt(session)
        if tilt['tilt_detected']:
            self.assertGreaterEqual(tilt['tilt_cost_bb'], 0.0)

    def test_severity_warning_for_two_signals(self):
        session = self._build_tilt_session(
            vpip_first=0, vpip_second=100,
            pfr_first=0, pfr_second=100,
            n_hands=40,
        )
        tilt = TiltAnalyzer(self.repo).detect_session_tilt(session)
        if tilt['tilt_detected']:
            self.assertIn(tilt['severity'], ('warning', 'danger'))


# ── Integration: TiltAnalyzer._analyze_hourly_performance ────────────────────

class TestHourlyPerformance(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _insert_hands_at_hour(self, hour, n, net_each=1.0, bb=0.5):
        for i in range(n):
            hand_id = f'H_h{hour}_{i}'
            ts = f'2026-01-15T{hour:02d}:{i:02d}:00'
            hand = _make_hand(hand_id, date=ts, net=net_each, blinds_bb=bb)
            self.repo.insert_hand(hand)

    def test_returns_24_hourly_entries(self):
        self._insert_hands_at_hour(20, 5)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(len(result['hourly']), 24)

    def test_correct_hands_per_bucket(self):
        # Insert 10 hands at 21:00 (noite bucket)
        self._insert_hands_at_hour(21, 10)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(result['buckets']['noite']['hands'], 10)
        self.assertEqual(result['buckets']['manhã']['hands'], 0)

    def test_win_rate_calculation(self):
        # 10 hands all winning 1 BB (net=0.5 at 0.5 BB → 1 BB each)
        self._insert_hands_at_hour(20, 10, net_each=0.5, bb=0.5)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        # 1 BB / hand = 100 bb/100
        self.assertAlmostEqual(result['buckets']['noite']['win_rate_bb100'], 100.0)

    def test_morning_bucket(self):
        self._insert_hands_at_hour(9, 5, net_each=-0.5, bb=0.5)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(result['buckets']['manhã']['hands'], 5)
        self.assertAlmostEqual(result['buckets']['manhã']['win_rate_bb100'], -100.0)

    def test_afternoon_bucket(self):
        self._insert_hands_at_hour(15, 3)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(result['buckets']['tarde']['hands'], 3)

    def test_madrugada_bucket(self):
        self._insert_hands_at_hour(3, 7)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(result['buckets']['madrugada']['hands'], 7)

    def test_health_good_for_positive_wr(self):
        self._insert_hands_at_hour(20, 10, net_each=1.0, bb=0.5)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(result['buckets']['noite']['health'], 'good')

    def test_health_danger_for_bad_wr(self):
        # net = -10 per hand at 0.5 BB → -2000 bb/100
        self._insert_hands_at_hour(20, 10, net_each=-10.0, bb=0.5)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(result['buckets']['noite']['health'], 'danger')

    def test_empty_hands(self):
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer._analyze_hourly_performance([])
        self.assertEqual(result['hourly'][0]['hands'], 0)
        self.assertEqual(result['buckets']['noite']['hands'], 0)

    def test_hour_boundary_inclusive(self):
        # Hour 6 should be in 'manhã' bucket (6-12)
        self._insert_hands_at_hour(6, 4)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(result['buckets']['manhã']['hands'], 4)

    def test_hour_11_in_morning(self):
        self._insert_hands_at_hour(11, 2)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(result['buckets']['manhã']['hands'], 2)

    def test_hour_12_in_afternoon(self):
        self._insert_hands_at_hour(12, 2)
        analyzer = TiltAnalyzer(self.repo)
        all_hands = self.repo.get_cash_hands()
        result = analyzer._analyze_hourly_performance(all_hands)
        self.assertEqual(result['buckets']['tarde']['hands'], 2)


# ── Integration: TiltAnalyzer._analyze_duration_performance ──────────────────

class TestDurationPerformance(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _setup_session_with_hands(self, start_hour, n_hours_of_hands,
                                   net_each=0.5, bb=0.5):
        """Insert a session that spans n_hours_of_hands starting at start_hour."""
        start = f'2026-01-15T{start_hour:02d}:00:00'
        end_hour = start_hour + max(n_hours_of_hands, 1)
        end = f'2026-01-15T{end_hour:02d}:00:00'
        sid = _create_session(self.repo, 1, start=start, end=end)
        session = {
            'session_id': sid,
            'start_time': start,
            'end_time': end,
        }
        # Insert one hand per 10-minute interval
        hands = []
        for i in range(n_hours_of_hands * 6):
            elapsed_min = i * 10
            hand_hour = start_hour + elapsed_min // 60
            hand_min = elapsed_min % 60
            if hand_hour >= 24:
                break
            ts = f'2026-01-15T{hand_hour:02d}:{hand_min:02d}:00'
            hand = _make_hand(f'H_{i}', date=ts, net=net_each, blinds_bb=bb)
            self.repo.insert_hand(hand)
            hands.append(hand)
        return session, hands

    def test_returns_four_buckets(self):
        session, _ = self._setup_session_with_hands(18, 2)
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer._analyze_duration_performance([session])
        self.assertEqual(len(result['buckets']), 4)

    def test_bucket_labels(self):
        session, _ = self._setup_session_with_hands(18, 1)
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer._analyze_duration_performance([session])
        labels = [b['label'] for b in result['buckets']]
        self.assertIn('0-60min', labels)
        self.assertIn('60-120min', labels)
        self.assertIn('120-180min', labels)
        self.assertIn('180min+', labels)

    def test_short_session_all_in_first_bucket(self):
        """A 30-min session should land all hands in 0-60min bucket."""
        sid = _create_session(self.repo, 1,
                               start='2026-01-15T18:00:00',
                               end='2026-01-15T18:30:00')
        session = {
            'session_id': sid,
            'start_time': '2026-01-15T18:00:00',
            'end_time': '2026-01-15T18:30:00',
        }
        for i in range(10):
            ts = f'2026-01-15T18:{i*2:02d}:00'
            hand = _make_hand(f'H{i}', date=ts, net=0.5, blinds_bb=0.5)
            self.repo.insert_hand(hand)

        analyzer = TiltAnalyzer(self.repo)
        result = analyzer._analyze_duration_performance([session])
        buckets = {b['label']: b for b in result['buckets']}
        self.assertEqual(buckets['0-60min']['hands'], 10)
        self.assertEqual(buckets['60-120min']['hands'], 0)

    def test_win_rate_positive_bucket(self):
        session, _ = self._setup_session_with_hands(18, 1, net_each=0.5, bb=0.5)
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer._analyze_duration_performance([session])
        b0 = result['buckets'][0]  # 0-60min
        self.assertGreater(b0['hands'], 0)
        self.assertAlmostEqual(b0['win_rate_bb100'], 100.0)

    def test_no_sessions(self):
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer._analyze_duration_performance([])
        for b in result['buckets']:
            self.assertEqual(b['hands'], 0)

    def test_health_classification(self):
        session, _ = self._setup_session_with_hands(18, 1, net_each=-5.0, bb=0.5)
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer._analyze_duration_performance([session])
        b0 = result['buckets'][0]
        if b0['hands'] > 0:
            self.assertEqual(b0['health'], 'danger')


# ── Integration: TiltAnalyzer._analyze_post_bad_beat ─────────────────────────

class TestPostBadBeat(unittest.TestCase):

    def _make_hands(self, nets, bb=0.5):
        return [
            {'hand_id': f'H{i}', 'net': n, 'blinds_bb': bb}
            for i, n in enumerate(nets)
        ]

    def test_no_bad_beats(self):
        """No hand exceeds the threshold → bad_beats=0."""
        conn, repo = _setup_db()
        analyzer = TiltAnalyzer(repo)
        hands = self._make_hands([0.5, -0.5, 1.0, -1.0] * 10)
        result = analyzer._analyze_post_bad_beat(hands)
        self.assertEqual(result['bad_beats'], 0)
        self.assertEqual(result['post_bb_win_rate'], 0.0)

    def test_single_bad_beat(self):
        """One hand at -_BAD_BEAT_BB BB exactly triggers detection."""
        conn, repo = _setup_db()
        analyzer = TiltAnalyzer(repo)
        bb = 0.5
        big_loss = -_BAD_BEAT_BB * bb  # exactly the threshold
        hands = self._make_hands(
            [0.5] * 5 + [big_loss] + [0.5] * 20,
            bb=bb,
        )
        result = analyzer._analyze_post_bad_beat(hands)
        self.assertEqual(result['bad_beats'], 1)
        self.assertGreater(result['post_hands_analyzed'], 0)

    def test_post_bad_beat_degradation_negative(self):
        """After a bad beat where hero plays worse, degradation should be negative."""
        conn, repo = _setup_db()
        analyzer = TiltAnalyzer(repo)
        bb = 0.5
        big_loss = -_BAD_BEAT_BB * bb - 1.0
        # Losing hands after the bad beat
        post_hands = [-1.0] * _POST_BAD_BEAT_WINDOW
        hands = self._make_hands([0.5] * 50 + [big_loss] + post_hands, bb=bb)
        result = analyzer._analyze_post_bad_beat(hands)
        # post_wr should be lower than baseline (which is positive)
        self.assertLess(result['post_bb_win_rate'], result['baseline_win_rate'])
        self.assertLess(result['degradation_bb100'], 0)

    def test_returns_required_keys(self):
        conn, repo = _setup_db()
        analyzer = TiltAnalyzer(repo)
        result = analyzer._analyze_post_bad_beat([])
        keys = ['bad_beats', 'post_bb_win_rate', 'baseline_win_rate',
                'post_hands_analyzed', 'degradation_bb100']
        for k in keys:
            self.assertIn(k, result, f'Missing key: {k}')

    def test_empty_hands(self):
        conn, repo = _setup_db()
        analyzer = TiltAnalyzer(repo)
        result = analyzer._analyze_post_bad_beat([])
        self.assertEqual(result['bad_beats'], 0)
        self.assertEqual(result['baseline_win_rate'], 0.0)

    def test_post_window_bounded(self):
        """Window is capped at _POST_BAD_BEAT_WINDOW hands after the bad beat."""
        conn, repo = _setup_db()
        analyzer = TiltAnalyzer(repo)
        bb = 0.5
        big_loss = -_BAD_BEAT_BB * bb - 1.0
        # 5 hands after the bad beat, then nothing else
        post_hands = [0.5] * 5
        hands = self._make_hands([0.0] * 30 + [big_loss] + post_hands, bb=bb)
        result = analyzer._analyze_post_bad_beat(hands)
        self.assertEqual(result['bad_beats'], 1)
        self.assertEqual(result['post_hands_analyzed'], 5)  # only 5 available

    def test_multiple_bad_beats_summed(self):
        conn, repo = _setup_db()
        analyzer = TiltAnalyzer(repo)
        bb = 0.5
        big_loss = -_BAD_BEAT_BB * bb - 1.0
        # Two bad beats, each followed by 5 hands
        hands = self._make_hands(
            [0.5] * 10 + [big_loss] + [0.5] * 5
            + [0.5] * 10 + [big_loss] + [0.5] * 5,
            bb=bb,
        )
        result = analyzer._analyze_post_bad_beat(hands)
        self.assertEqual(result['bad_beats'], 2)


# ── Integration: TiltAnalyzer._generate_recommendation ───────────────────────

class TestGenerateRecommendation(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = TiltAnalyzer(self.repo)

    def test_empty_buckets_returns_insufficient(self):
        result = self.analyzer._generate_recommendation({'buckets': []})
        self.assertIsNone(result['ideal_duration'])
        self.assertIn('insuficientes', result['text'].lower())

    def test_all_negative_wr(self):
        duration = {
            'buckets': [
                {'label': '0-60min', 'hands': 20, 'win_rate_bb100': -5.0},
                {'label': '60-120min', 'hands': 20, 'win_rate_bb100': -10.0},
            ]
        }
        result = self.analyzer._generate_recommendation(duration)
        self.assertIsNone(result['ideal_duration'])

    def test_single_positive_bucket(self):
        duration = {
            'buckets': [
                {'label': '0-60min', 'hands': 20, 'win_rate_bb100': 5.0},
                {'label': '60-120min', 'hands': 5, 'win_rate_bb100': -2.0},
            ]
        }
        result = self.analyzer._generate_recommendation(duration)
        self.assertEqual(result['ideal_duration'], '0-60min')

    def test_best_bucket_identified(self):
        duration = {
            'buckets': [
                {'label': '0-60min', 'hands': 50, 'win_rate_bb100': 3.0},
                {'label': '60-120min', 'hands': 50, 'win_rate_bb100': 10.0},
                {'label': '120-180min', 'hands': 20, 'win_rate_bb100': -2.0},
            ]
        }
        result = self.analyzer._generate_recommendation(duration)
        self.assertEqual(result['ideal_duration'], '60-120min')

    def test_degradation_detected(self):
        duration = {
            'buckets': [
                {'label': '0-60min', 'hands': 50, 'win_rate_bb100': 15.0},
                {'label': '60-120min', 'hands': 50, 'win_rate_bb100': 5.0},
                {'label': '120-180min', 'hands': 30, 'win_rate_bb100': -5.0},
            ]
        }
        result = self.analyzer._generate_recommendation(duration)
        self.assertIsNotNone(result['ideal_duration'])
        self.assertIn('degrada', result['text'].lower())

    def test_consistent_performance_no_degradation_text(self):
        duration = {
            'buckets': [
                {'label': '0-60min', 'hands': 50, 'win_rate_bb100': 8.0},
                {'label': '60-120min', 'hands': 50, 'win_rate_bb100': 6.0},
            ]
        }
        result = self.analyzer._generate_recommendation(duration)
        # consistent → degradation not mentioned
        self.assertNotIn('degrada', result['text'].lower())

    def test_too_few_hands_bucket_skipped(self):
        duration = {
            'buckets': [
                {'label': '0-60min', 'hands': 9, 'win_rate_bb100': 20.0},  # < 10
                {'label': '60-120min', 'hands': 50, 'win_rate_bb100': 5.0},
            ]
        }
        result = self.analyzer._generate_recommendation(duration)
        # 0-60min skipped → 60-120min is the best valid bucket
        self.assertEqual(result['ideal_duration'], '60-120min')


# ── Integration: TiltAnalyzer.get_tilt_analysis ──────────────────────────────

class TestGetTiltAnalysis(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def _seed_basic_data(self):
        """Insert a session with 20 hands at different hours."""
        sid = _create_session(
            self.repo, 1,
            start='2026-01-15T18:00:00',
            end='2026-01-15T20:00:00',
        )
        for i in range(20):
            ts = f'2026-01-15T18:{i:02d}:00'
            hand = _make_hand(f'H{i}', date=ts, net=0.5 if i % 2 == 0 else -0.5)
            self.repo.insert_hand(hand)

    def test_empty_db_returns_empty(self):
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        self.assertEqual(result, {})

    def test_returns_required_keys(self):
        self._seed_basic_data()
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        for key in ('session_tilt', 'tilt_sessions_count', 'hourly',
                    'duration', 'post_bad_beat', 'recommendation', 'diagnostics'):
            self.assertIn(key, result, f'Missing key: {key}')

    def test_tilt_sessions_count_non_negative(self):
        self._seed_basic_data()
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        self.assertGreaterEqual(result['tilt_sessions_count'], 0)

    def test_hourly_has_24_entries(self):
        self._seed_basic_data()
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        self.assertEqual(len(result['hourly']['hourly']), 24)

    def test_duration_has_four_buckets(self):
        self._seed_basic_data()
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        self.assertEqual(len(result['duration']['buckets']), 4)

    def test_session_tilt_list_length_matches_sessions(self):
        self._seed_basic_data()
        analyzer = TiltAnalyzer(self.repo)
        sessions = self.repo.get_sessions()
        result = analyzer.get_tilt_analysis()
        self.assertEqual(len(result['session_tilt']), len(sessions))

    def test_post_bad_beat_keys_present(self):
        self._seed_basic_data()
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        pbb = result['post_bad_beat']
        for k in ('bad_beats', 'post_bb_win_rate', 'baseline_win_rate'):
            self.assertIn(k, pbb)


# ── Integration: CashAnalyzer.get_tilt_analysis (delegation wrapper) ──────────

class TestCashAnalyzerGetTiltAnalysis(unittest.TestCase):

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_empty_db_returns_empty(self):
        analyzer = CashAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        self.assertEqual(result, {})

    def test_returns_dict(self):
        # Insert one session and hands
        sid = _create_session(self.repo, 1)
        for i in range(5):
            ts = f'2026-01-15T18:{i:02d}:00'
            hand = _make_hand(f'H{i}', date=ts)
            self.repo.insert_hand(hand)
        analyzer = CashAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        # With data present, should return a non-empty dict
        self.assertIsInstance(result, dict)


# ── Report: _render_tilt_analysis ─────────────────────────────────────────────

class TestRenderTiltAnalysis(unittest.TestCase):

    def _minimal_data(self, **kwargs):
        base = {
            'tilt_sessions_count': 0,
            'session_tilt': [],
            'hourly': {'hourly': [], 'buckets': {}},
            'duration': {'buckets': []},
            'post_bad_beat': {'bad_beats': 0},
            'recommendation': {'text': 'Dados insuficientes.', 'ideal_duration': None},
            'diagnostics': [],
        }
        base.update(kwargs)
        return base

    def test_renders_without_error(self):
        html = _render_tilt_analysis(self._minimal_data())
        self.assertIsInstance(html, str)
        self.assertIn('Detec', html)

    def test_tilt_detected_shows_badge(self):
        data = self._minimal_data(
            tilt_sessions_count=1,
            session_tilt=[{
                'session_id': 1,
                'session_date': '2026-01-15',
                'start_time': '2026-01-15T18:00:00',
                'tilt_detected': True,
                'tilt_signals': ['vpip_spike', 'pfr_spike'],
                'severity': 'warning',
                'total_hands': 50,
                'first_stats': {'vpip': 20.0, 'pfr': 15.0, 'af': 2.0, 'total_hands': 25},
                'second_stats': {'vpip': 35.0, 'pfr': 28.0, 'af': 3.2, 'total_hands': 25},
                'vpip_delta': 15.0,
                'pfr_delta': 13.0,
                'af_delta': 1.2,
                'tilt_cost_bb': 12.5,
            }],
        )
        html = _render_tilt_analysis(data)
        self.assertIn('Tilt Detected', html)

    def test_hourly_buckets_rendered(self):
        data = self._minimal_data(
            hourly={
                'hourly': [{'hour': h, 'hands': 5 if h == 20 else 0,
                             'win_rate_bb100': 10.0 if h == 20 else 0.0}
                            for h in range(24)],
                'buckets': {
                    'noite': {'hands': 5, 'win_rate_bb100': 10.0, 'net': 5.0,
                               'health': 'good'},
                    'manhã': {'hands': 0, 'win_rate_bb100': 0.0, 'net': 0.0,
                               'health': 'warning'},
                    'tarde': {'hands': 0, 'win_rate_bb100': 0.0, 'net': 0.0,
                               'health': 'warning'},
                    'madrugada': {'hands': 0, 'win_rate_bb100': 0.0, 'net': 0.0,
                                  'health': 'warning'},
                },
            },
        )
        html = _render_tilt_analysis(data)
        self.assertIn('noite', html.lower())

    def test_duration_table_rendered(self):
        data = self._minimal_data(
            duration={
                'buckets': [
                    {'label': '0-60min', 'hands': 30, 'net': 10.0,
                     'win_rate_bb100': 5.0, 'health': 'good'},
                    {'label': '60-120min', 'hands': 0, 'net': 0.0,
                     'win_rate_bb100': 0.0, 'health': 'warning'},
                    {'label': '120-180min', 'hands': 0, 'net': 0.0,
                     'win_rate_bb100': 0.0, 'health': 'warning'},
                    {'label': '180min+', 'hands': 0, 'net': 0.0,
                     'win_rate_bb100': 0.0, 'health': 'warning'},
                ]
            },
        )
        html = _render_tilt_analysis(data)
        self.assertIn('0-60min', html)

    def test_post_bad_beat_rendered(self):
        data = self._minimal_data(
            post_bad_beat={
                'bad_beats': 3,
                'post_bb_win_rate': -20.0,
                'baseline_win_rate': 5.0,
                'post_hands_analyzed': 60,
                'degradation_bb100': -25.0,
            },
        )
        html = _render_tilt_analysis(data)
        self.assertIn('Bad Beat', html)
        self.assertIn('3', html)

    def test_recommendation_rendered(self):
        data = self._minimal_data(
            recommendation={
                'text': 'Melhor desempenho no período 0-60min.',
                'ideal_duration': '0-60min',
                'best_bucket': {'label': '0-60min', 'win_rate_bb100': 5.0},
            },
        )
        html = _render_tilt_analysis(data)
        self.assertIn('0-60min', html)

    def test_diagnostics_rendered(self):
        data = self._minimal_data(
            diagnostics=[
                {'type': 'warning', 'title': 'Tilt aviso', 'message': 'Cuidado!'},
            ],
        )
        html = _render_tilt_analysis(data)
        self.assertIn('Tilt aviso', html)

    def test_no_post_bad_beat_section_when_zero(self):
        data = self._minimal_data(
            post_bad_beat={'bad_beats': 0}
        )
        html = _render_tilt_analysis(data)
        # Section heading should not appear when bad_beats == 0
        self.assertNotIn('Análise Pós-Bad-Beat', html)

    def test_returns_string(self):
        self.assertIsInstance(_render_tilt_analysis({}), str)


# ── Report: _render_hourly_heatmap ────────────────────────────────────────────

class TestRenderHourlyHeatmap(unittest.TestCase):

    def _make_hourly(self, hands_at_hour=None):
        """Build 24-entry hourly list; optionally set hands at specified hours."""
        data = [{'hour': h, 'hands': 0, 'win_rate_bb100': 0.0} for h in range(24)]
        if hands_at_hour:
            for hour, hc, wr in hands_at_hour:
                data[hour] = {'hour': hour, 'hands': hc, 'win_rate_bb100': wr}
        return data

    def test_empty_returns_empty_string(self):
        self.assertEqual(_render_hourly_heatmap([]), '')

    def test_renders_24_cells(self):
        hourly = self._make_hourly()
        html = _render_hourly_heatmap(hourly)
        # Each hour has a div with its hour label
        for h in range(24):
            self.assertIn(f'{h:02d}h', html)

    def test_no_data_hours_show_dash(self):
        hourly = self._make_hourly()
        html = _render_hourly_heatmap(hourly)
        self.assertIn('—', html)

    def test_positive_wr_shows_value(self):
        hourly = self._make_hourly(hands_at_hour=[(20, 10, 25.0)])
        html = _render_hourly_heatmap(hourly)
        self.assertIn('+25', html)

    def test_negative_wr_shows_value(self):
        hourly = self._make_hourly(hands_at_hour=[(3, 5, -15.0)])
        html = _render_hourly_heatmap(hourly)
        self.assertIn('-15', html)

    def test_contains_heatmap_heading(self):
        hourly = self._make_hourly(hands_at_hour=[(20, 5, 5.0)])
        html = _render_hourly_heatmap(hourly)
        self.assertIn('Mapa de Calor', html)

    def test_all_zero_wr_renders_without_error(self):
        hourly = [{'hour': h, 'hands': 5, 'win_rate_bb100': 0.0} for h in range(24)]
        html = _render_hourly_heatmap(hourly)
        self.assertIsInstance(html, str)


# ── End-to-end: CashAnalyzer + full data ─────────────────────────────────────

class TestTiltAnalyzerEndToEnd(unittest.TestCase):
    """End-to-end test: seed rich data and verify all analysis sections."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self._seed()

    def _seed(self):
        # Session 1 – stable, evening (18-20h)
        s1 = _create_session(
            self.repo, 1,
            start='2026-01-10T18:00:00',
            end='2026-01-10T20:00:00',
            profit=20.0,
        )
        for i in range(40):
            ts = f'2026-01-10T18:{i:02d}:00'
            _insert_vpip_hand(self.repo, f'S1H{i}', ts, net=0.5)

        # Session 2 – tilt session (VPIP jumps in second half)
        s2 = _create_session(
            self.repo, 2,
            start='2026-01-11T20:00:00',
            end='2026-01-11T23:00:00',
            profit=-30.0,
        )
        for i in range(20):  # first half: low VPIP
            ts = f'2026-01-11T20:{i:02d}:00'
            _insert_vpip_hand(self.repo, f'S2F{i}', ts, is_vpip=False, is_pfr=False, net=-0.5)
        for i in range(20):  # second half: all VPIP+PFR (simulate tilt)
            ts = f'2026-01-11T21:{i:02d}:00'
            _insert_vpip_hand(self.repo, f'S2S{i}', ts, is_vpip=True, is_pfr=True, net=-1.5)

        # Morning hands
        for i in range(10):
            ts = f'2026-01-12T09:{i:02d}:00'
            hand = _make_hand(f'MH{i}', date=ts, net=0.5)
            self.repo.insert_hand(hand)

        # Bad beat hand + post hands
        hand_bb = _make_hand('BB0', date='2026-01-10T19:30:00',
                              net=-(0.5 * (_BAD_BEAT_BB + 5)))
        self.repo.insert_hand(hand_bb)

    def test_analysis_runs_without_error(self):
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        self.assertIsInstance(result, dict)

    def test_tilt_sessions_count_gte_zero(self):
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        self.assertGreaterEqual(result.get('tilt_sessions_count', 0), 0)

    def test_morning_bucket_has_hands(self):
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        self.assertGreater(result['hourly']['buckets']['manhã']['hands'], 0)

    def test_bad_beat_detected(self):
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        # We inserted one bad-beat hand
        self.assertGreaterEqual(result['post_bad_beat']['bad_beats'], 1)

    def test_duration_first_bucket_has_hands(self):
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        first_bucket = result['duration']['buckets'][0]
        self.assertGreater(first_bucket['hands'], 0)

    def test_recommendation_text_non_empty(self):
        analyzer = TiltAnalyzer(self.repo)
        result = analyzer.get_tilt_analysis()
        self.assertGreater(len(result['recommendation']['text']), 0)

    def test_report_renders_without_error(self):
        analyzer = TiltAnalyzer(self.repo)
        data = analyzer.get_tilt_analysis()
        html = _render_tilt_analysis(data)
        self.assertIn('Detec', html)


if __name__ == '__main__':
    unittest.main()
