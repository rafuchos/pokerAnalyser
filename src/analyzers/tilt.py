"""Tilt detection and time/duration performance analysis.

Implements US-014: Detecção de Tilt e Análise de Performance por Horário/Duração.

Covers:
- Tilt detection per session (VPIP/PFR/AF spikes in second half)
- Performance by time of day (madrugada, manhã, tarde, noite)
- Win rate by session duration buckets (0-60min, 60-120min, ...)
- Post-bad-beat analysis (20 hands after big loss)
- Session duration recommendation
"""

from collections import defaultdict
from datetime import datetime

from src.db.repository import Repository

# ── Tilt Detection Thresholds ─────────────────────────────────────────────────

_TILT_VPIP_DELTA = 6.0   # pp increase from first → second half triggers signal
_TILT_PFR_DELTA = 5.0
_TILT_AF_DELTA = 0.8
_MIN_HANDS_SEGMENT = 15  # min hands per segment required for tilt detection

# ── Post-Bad-Beat ─────────────────────────────────────────────────────────────

_BAD_BEAT_BB = 30          # loss > 30 BB = bad beat
_POST_BAD_BEAT_WINDOW = 20 # hands to analyse after each bad beat

# ── Time-of-Day Buckets ───────────────────────────────────────────────────────
# Each entry: (label, start_hour_inclusive, end_hour_exclusive)
_HOUR_BUCKETS = [
    ('madrugada', 0, 6),
    ('manhã', 6, 12),
    ('tarde', 12, 18),
    ('noite', 18, 24),
]

# ── Duration Buckets ──────────────────────────────────────────────────────────
# Each entry: (label, min_minutes_inclusive, max_minutes_exclusive)
_DURATION_BUCKETS = [
    ('0-60min', 0, 60),
    ('60-120min', 60, 120),
    ('120-180min', 120, 180),
    ('180min+', 180, 9999),
]


# ── Module-Level Helpers ──────────────────────────────────────────────────────

def _get_hour(date_str: str) -> int:
    """Extract hour (0-23) from ISO datetime string; returns -1 on error."""
    try:
        return datetime.fromisoformat(date_str).hour
    except (ValueError, TypeError):
        return -1


def _get_avg_bb(hands: list[dict]) -> float:
    """Compute average big blind size across hands (fallback 1.0)."""
    bbs = [h.get('blinds_bb') or 0 for h in hands if (h.get('blinds_bb') or 0) > 0]
    return sum(bbs) / len(bbs) if bbs else 1.0


def _compute_segment_stats(hands: list[dict], actions: list[dict]) -> dict:
    """Compute VPIP%, PFR%, AF for a subset of hands and their actions.

    Returns dict: total_hands, vpip, pfr, af, net, net_bb.
    Only counts hands where hero was present (has_hero action).
    """
    if not hands:
        return {'total_hands': 0, 'vpip': 0.0, 'pfr': 0.0, 'af': 0.0,
                'net': 0.0, 'net_bb': 0.0}

    hand_ids = {h['hand_id'] for h in hands}

    # Group actions by hand_id
    by_hand: dict[str, list[dict]] = defaultdict(list)
    for a in actions:
        if a['hand_id'] in hand_ids:
            by_hand[a['hand_id']].append(a)

    vpip_count = 0
    pfr_count = 0
    agg_br = 0
    agg_calls = 0
    total_hands = 0
    net_sum = 0.0
    net_bb_sum = 0.0

    # Build hand metadata lookup
    hand_lookup = {h['hand_id']: h for h in hands}

    for hand_id in hand_ids:
        hand_actions = by_hand.get(hand_id, [])
        hand = hand_lookup.get(hand_id, {})

        # Only count hands where hero acted
        if not any(a['is_hero'] for a in hand_actions):
            continue

        total_hands += 1
        net = hand.get('net') or 0
        bb = hand.get('blinds_bb') or 1.0
        net_sum += net
        net_bb_sum += net / bb

        # Preflop VPIP / PFR (exclude posts)
        preflop = [
            a for a in hand_actions
            if a['street'] == 'preflop'
            and a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')
        ]
        hero_voluntary = any(
            a['is_hero'] and a.get('is_voluntary')
            for a in preflop
        )
        hero_raised = any(
            a['is_hero'] and a['action_type'] in ('raise', 'bet', 'all-in')
            for a in preflop
        )
        if hero_voluntary:
            vpip_count += 1
        if hero_raised:
            pfr_count += 1

        # Postflop aggression
        for a in hand_actions:
            if a['street'] in ('flop', 'turn', 'river') and a['is_hero']:
                if a['action_type'] in ('bet', 'raise'):
                    agg_br += 1
                elif a['action_type'] == 'call':
                    agg_calls += 1

    if total_hands == 0:
        return {'total_hands': 0, 'vpip': 0.0, 'pfr': 0.0, 'af': 0.0,
                'net': 0.0, 'net_bb': 0.0}

    return {
        'total_hands': total_hands,
        'vpip': round(vpip_count / total_hands * 100, 1),
        'pfr': round(pfr_count / total_hands * 100, 1),
        'af': round(agg_br / agg_calls if agg_calls > 0 else 0.0, 2),
        'net': round(net_sum, 2),
        'net_bb': round(net_bb_sum, 2),
    }


def _classify_tilt_wr_health(win_rate_bb100: float) -> str:
    """Classify win rate health: good (>=5), warning (-5 to 5), danger (<-5)."""
    if win_rate_bb100 >= 5:
        return 'good'
    if win_rate_bb100 >= -5:
        return 'warning'
    return 'danger'


def _classify_tilt_severity(signals: list[str]) -> str:
    """Classify tilt severity from signal count: danger (3+), warning (2), good (0-1)."""
    if len(signals) >= 3:
        return 'danger'
    if len(signals) >= 2:
        return 'warning'
    return 'good'


def _generate_tilt_diagnostics(session_tilt_list: list[dict],
                                hourly: dict,
                                duration: dict) -> list[dict]:
    """Generate human-readable diagnostic messages for tilt analysis."""
    diagnostics = []

    # Tilt sessions summary
    tilt_sessions = [s for s in session_tilt_list if s.get('tilt_detected')]
    if tilt_sessions:
        total_cost = sum(s.get('tilt_cost_bb', 0) for s in tilt_sessions)
        dtype = 'danger' if len(tilt_sessions) > 3 else 'warning'
        diagnostics.append({
            'type': dtype,
            'title': f'{len(tilt_sessions)} sessão(ões) com tilt detectado',
            'message': (
                f'Padrão de tilt identificado em {len(tilt_sessions)} sessões. '
                f'Custo estimado: {total_cost:.0f} BB. '
                'Considere encerrar sessões quando os stats deteriorarem.'
            ),
        })

    # Best vs worst time of day
    buckets_with_data = [
        (name, v) for name, v in hourly.get('buckets', {}).items()
        if v.get('hands', 0) >= 20
    ]
    if len(buckets_with_data) >= 2:
        best = max(buckets_with_data, key=lambda x: x[1]['win_rate_bb100'])
        worst = min(buckets_with_data, key=lambda x: x[1]['win_rate_bb100'])
        diff = best[1]['win_rate_bb100'] - worst[1]['win_rate_bb100']
        if diff > 10:
            diagnostics.append({
                'type': 'warning',
                'title': 'Grande variação de performance por horário',
                'message': (
                    f'Melhor período: {best[0]} ({best[1]["win_rate_bb100"]:+.1f} bb/100). '
                    f'Pior período: {worst[0]} ({worst[1]["win_rate_bb100"]:+.1f} bb/100). '
                    'Concentre sessões no horário mais lucrativo.'
                ),
            })

    # Duration degradation
    dur_buckets = [b for b in duration.get('buckets', []) if b.get('hands', 0) >= 10]
    if len(dur_buckets) >= 2:
        first_wr = dur_buckets[0].get('win_rate_bb100', 0)
        last_wr = dur_buckets[-1].get('win_rate_bb100', 0)
        if first_wr - last_wr > 10:
            diagnostics.append({
                'type': 'warning',
                'title': 'Performance degrada com a duração da sessão',
                'message': (
                    f'Win rate cai de {first_wr:+.1f} bb/100 ({dur_buckets[0]["label"]}) '
                    f'para {last_wr:+.1f} bb/100 ({dur_buckets[-1]["label"]}). '
                    'Sessões mais curtas tendem a ser mais lucrativas.'
                ),
            })

    return diagnostics


# ── TiltAnalyzer ──────────────────────────────────────────────────────────────

class TiltAnalyzer:
    """Detect tilt patterns and analyse performance by time of day and session duration."""

    def __init__(self, repo: Repository, year: str = '2026'):
        self.repo = repo
        self.year = year

    # ── Public API ───────────────────────────────────────────────────────────

    def get_tilt_analysis(self) -> dict:
        """Return full tilt and performance-timing analysis.

        Keys returned:
          session_tilt: list[dict]   – per-session tilt detection results
          tilt_sessions_count: int   – number of sessions with tilt detected
          hourly: dict               – performance by hour/bucket
          duration: dict             – performance by session-duration bucket
          post_bad_beat: dict        – post-bad-beat performance stats
          recommendation: dict       – ideal session duration advice
          diagnostics: list[dict]    – auto-generated diagnostic messages
        """
        sessions = self.repo.get_sessions(self.year)
        all_hands = self.repo.get_cash_hands(self.year)

        if not all_hands:
            return {}

        session_tilt_list = self._analyze_all_sessions(sessions)
        hourly = self._analyze_hourly_performance(all_hands)
        duration = self._analyze_duration_performance(sessions)
        post_bad_beat = self._analyze_post_bad_beat(all_hands)
        recommendation = self._generate_recommendation(duration)
        diagnostics = _generate_tilt_diagnostics(session_tilt_list, hourly, duration)

        return {
            'session_tilt': session_tilt_list,
            'tilt_sessions_count': sum(
                1 for s in session_tilt_list if s.get('tilt_detected')
            ),
            'hourly': hourly,
            'duration': duration,
            'post_bad_beat': post_bad_beat,
            'recommendation': recommendation,
            'diagnostics': diagnostics,
        }

    def detect_session_tilt(self, session: dict) -> dict:
        """Detect tilt in a single session by comparing first-half vs second-half stats.

        Requires at least 2 × _MIN_HANDS_SEGMENT hands; otherwise returns
        tilt_detected=False with reason='insufficient_hands'.

        Returns dict with:
          tilt_detected, tilt_signals, severity, first_stats, second_stats,
          vpip_delta, pfr_delta, af_delta, tilt_cost_bb.
        """
        hands = self.repo.get_hands_for_session(session)
        actions = self.repo.get_actions_for_session(session)

        session_id = session.get('session_id')
        n = len(hands)

        if n < _MIN_HANDS_SEGMENT * 2:
            return {
                'session_id': session_id,
                'session_date': session.get('date', ''),
                'start_time': session.get('start_time', ''),
                'tilt_detected': False,
                'tilt_signals': [],
                'severity': 'good',
                'total_hands': n,
                'reason': 'insufficient_hands',
            }

        mid = n // 2
        first_hands = hands[:mid]
        second_hands = hands[mid:]

        first_stats = _compute_segment_stats(first_hands, actions)
        second_stats = _compute_segment_stats(second_hands, actions)

        vpip_delta = second_stats['vpip'] - first_stats['vpip']
        pfr_delta = second_stats['pfr'] - first_stats['pfr']
        af_delta = second_stats['af'] - first_stats['af']

        tilt_signals = []
        if vpip_delta >= _TILT_VPIP_DELTA:
            tilt_signals.append('vpip_spike')
        if pfr_delta >= _TILT_PFR_DELTA:
            tilt_signals.append('pfr_spike')
        if af_delta >= _TILT_AF_DELTA:
            tilt_signals.append('af_spike')

        tilt_detected = len(tilt_signals) >= 2
        severity = _classify_tilt_severity(tilt_signals)

        # Estimated tilt cost in BB
        tilt_cost_bb = 0.0
        if tilt_detected:
            avg_bb = _get_avg_bb(hands)
            n_first = first_stats['total_hands']
            n_second = second_stats['total_hands']
            if avg_bb > 0 and n_first > 0 and n_second > 0:
                first_bb100 = (first_stats['net'] / avg_bb) / (n_first / 100)
                second_bb100 = (second_stats['net'] / avg_bb) / (n_second / 100)
                # Cost = lost bb/100 above first-half baseline × second-half hands
                degradation_bb100 = max(0.0, first_bb100 - second_bb100)
                tilt_cost_bb = round(degradation_bb100 * n_second / 100, 1)

        return {
            'session_id': session_id,
            'session_date': session.get('date', ''),
            'start_time': session.get('start_time', ''),
            'tilt_detected': tilt_detected,
            'tilt_signals': tilt_signals,
            'severity': severity,
            'total_hands': n,
            'first_stats': first_stats,
            'second_stats': second_stats,
            'vpip_delta': round(vpip_delta, 1),
            'pfr_delta': round(pfr_delta, 1),
            'af_delta': round(af_delta, 2),
            'tilt_cost_bb': tilt_cost_bb,
        }

    # ── Private Helpers ──────────────────────────────────────────────────────

    def _analyze_all_sessions(self, sessions: list[dict]) -> list[dict]:
        """Run tilt detection across all sessions."""
        return [self.detect_session_tilt(s) for s in sessions]

    def _analyze_hourly_performance(self, hands: list[dict]) -> dict:
        """Compute win rate by hour (0-23) and by time-of-day bucket.

        Returns:
          hourly: list[dict]  – one entry per hour 0-23 (hands, net, win_rate_bb100)
          buckets: dict       – keyed by bucket label (madrugada/manhã/tarde/noite)
        """
        by_hour: dict[int, dict] = defaultdict(
            lambda: {'hands': 0, 'net': 0.0, 'net_bb': 0.0}
        )
        by_bucket: dict[str, dict] = defaultdict(
            lambda: {'hands': 0, 'net': 0.0, 'net_bb': 0.0}
        )

        for h in hands:
            hour = _get_hour(h.get('date', ''))
            if hour < 0:
                continue

            net = h.get('net') or 0
            bb = h.get('blinds_bb') or 1.0
            net_bb = net / bb

            by_hour[hour]['hands'] += 1
            by_hour[hour]['net'] += net
            by_hour[hour]['net_bb'] += net_bb

            bucket_name = 'noite'
            for name, start, end in _HOUR_BUCKETS:
                if start <= hour < end:
                    bucket_name = name
                    break

            by_bucket[bucket_name]['hands'] += 1
            by_bucket[bucket_name]['net'] += net
            by_bucket[bucket_name]['net_bb'] += net_bb

        # Format per-hour list
        hourly_data = []
        for hour_num in range(24):
            d = by_hour[hour_num]
            hc = d['hands']
            wr = (d['net_bb'] / hc * 100) if hc > 0 else 0.0
            hourly_data.append({
                'hour': hour_num,
                'hands': hc,
                'net': round(d['net'], 2),
                'win_rate_bb100': round(wr, 1),
            })

        # Format bucket dict
        buckets = {}
        for name, _, _ in _HOUR_BUCKETS:
            d = by_bucket.get(name, {'hands': 0, 'net': 0.0, 'net_bb': 0.0})
            hc = d['hands']
            wr = (d['net_bb'] / hc * 100) if hc > 0 else 0.0
            buckets[name] = {
                'hands': hc,
                'net': round(d['net'], 2),
                'win_rate_bb100': round(wr, 1),
                'health': _classify_tilt_wr_health(wr),
            }

        return {'hourly': hourly_data, 'buckets': buckets}

    def _analyze_duration_performance(self, sessions: list[dict]) -> dict:
        """Compute win rate by elapsed time within session.

        Buckets: 0-60min, 60-120min, 120-180min, 180min+.
        For each hand, the elapsed time is (hand.date - session.start_time) in minutes.
        """
        bucket_acc: dict[str, dict] = defaultdict(
            lambda: {'hands': 0, 'net': 0.0, 'net_bb': 0.0}
        )

        for session in sessions:
            start_str = session.get('start_time', '')
            try:
                start_dt = datetime.fromisoformat(start_str)
            except (ValueError, TypeError):
                continue

            session_hands = self.repo.get_hands_for_session(session)
            for h in session_hands:
                date_str = h.get('date', '')
                try:
                    hand_dt = datetime.fromisoformat(date_str)
                except (ValueError, TypeError):
                    continue

                elapsed_min = max(0.0, (hand_dt - start_dt).total_seconds() / 60)
                net = h.get('net') or 0
                bb = h.get('blinds_bb') or 1.0
                net_bb = net / bb

                for label, lo, hi in _DURATION_BUCKETS:
                    if lo <= elapsed_min < hi:
                        bucket_acc[label]['hands'] += 1
                        bucket_acc[label]['net'] += net
                        bucket_acc[label]['net_bb'] += net_bb
                        break

        result_buckets = []
        for label, _, _ in _DURATION_BUCKETS:
            d = bucket_acc.get(label, {'hands': 0, 'net': 0.0, 'net_bb': 0.0})
            hc = d['hands']
            wr = (d['net_bb'] / hc * 100) if hc > 0 else 0.0
            result_buckets.append({
                'label': label,
                'hands': hc,
                'net': round(d['net'], 2),
                'win_rate_bb100': round(wr, 1),
                'health': _classify_tilt_wr_health(wr),
            })

        return {'buckets': result_buckets}

    def _analyze_post_bad_beat(self, hands: list[dict]) -> dict:
        """Analyse performance in the _POST_BAD_BEAT_WINDOW hands after each big loss.

        A 'bad beat' is a hand where net < -_BAD_BEAT_BB × blinds_bb.
        Returns:
          bad_beats: int
          post_bb_win_rate: float (bb/100 in post-bad-beat windows)
          baseline_win_rate: float (bb/100 across all hands)
          post_hands_analyzed: int
          degradation_bb100: float (post_wr - baseline_wr; negative = worse)
        """
        if not hands:
            return {
                'bad_beats': 0,
                'post_bb_win_rate': 0.0,
                'baseline_win_rate': 0.0,
                'post_hands_analyzed': 0,
                'degradation_bb100': 0.0,
            }

        # Baseline win rate over all hands
        total_net_bb = sum(
            (h.get('net') or 0) / (h.get('blinds_bb') or 1.0)
            for h in hands
        )
        baseline_wr = round(total_net_bb / len(hands) * 100, 1)

        # Identify bad-beat hand indices
        bad_beat_indices = [
            i for i, h in enumerate(hands)
            if (h.get('net') or 0) / (h.get('blinds_bb') or 1.0) <= -_BAD_BEAT_BB
        ]

        if not bad_beat_indices:
            return {
                'bad_beats': 0,
                'post_bb_win_rate': 0.0,
                'baseline_win_rate': baseline_wr,
                'post_hands_analyzed': 0,
                'degradation_bb100': 0.0,
            }

        # Collect post-bad-beat windows
        post_net_bb = 0.0
        post_count = 0
        for idx in bad_beat_indices:
            window = hands[idx + 1: idx + 1 + _POST_BAD_BEAT_WINDOW]
            for h in window:
                post_net_bb += (h.get('net') or 0) / (h.get('blinds_bb') or 1.0)
                post_count += 1

        post_wr = round(post_net_bb / post_count * 100, 1) if post_count > 0 else 0.0
        degradation = round(post_wr - baseline_wr, 1)

        return {
            'bad_beats': len(bad_beat_indices),
            'post_bb_win_rate': post_wr,
            'baseline_win_rate': baseline_wr,
            'post_hands_analyzed': post_count,
            'degradation_bb100': degradation,
        }

    def _generate_recommendation(self, duration: dict) -> dict:
        """Generate session-duration recommendation based on duration performance.

        Finds the best win-rate duration bucket with enough hands and checks
        for degradation patterns across buckets.
        """
        buckets = duration.get('buckets', [])
        valid = [b for b in buckets if b.get('hands', 0) >= 10]

        if not valid:
            return {
                'text': 'Dados insuficientes para recomendação (mínimo 10 mãos por período).',
                'ideal_duration': None,
            }

        best = max(valid, key=lambda b: b['win_rate_bb100'])
        positive = [b for b in valid if b['win_rate_bb100'] >= 0]

        if not positive:
            return {
                'text': (
                    'Performance negativa em todos os períodos analisados. '
                    'Considere revisar a estratégia geral antes de aumentar volume.'
                ),
                'ideal_duration': None,
            }

        # Detect degradation: any adjacent pair drops > 5 bb/100
        degradation = any(
            valid[i + 1]['win_rate_bb100'] < valid[i]['win_rate_bb100'] - 5
            for i in range(len(valid) - 1)
        )

        last_positive = positive[-1]

        if degradation:
            text = (
                f'Melhor desempenho no período {best["label"]} '
                f'({best["win_rate_bb100"]:+.1f} bb/100). '
                f'Performance degrada após {last_positive["label"]}. '
                'Encerrar sessões dentro desse período para maximizar resultados.'
            )
        else:
            text = (
                f'Performance consistente até {last_positive["label"]}. '
                f'Melhor período: {best["label"]} ({best["win_rate_bb100"]:+.1f} bb/100). '
                'Continue monitorando conforme o volume de sessões longas aumenta.'
            )

        return {
            'text': text,
            'ideal_duration': best['label'],
            'best_bucket': best,
        }
