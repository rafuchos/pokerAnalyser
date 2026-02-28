"""Cash game analysis module.

Reads from database and computes statistics for reports.
"""

from collections import defaultdict
from datetime import datetime

from src.db.repository import Repository


class CashAnalyzer:
    """Analyze cash game data from the database."""

    def __init__(self, repo: Repository, year: str = '2026'):
        self.repo = repo
        self.year = year

    def get_daily_reports(self) -> list[dict]:
        """Build daily report data for HTML generation."""
        daily_stats = self.repo.get_cash_daily_stats(self.year)
        reports = []

        for day_stat in daily_stats:
            day = day_stat['day']
            hands = self.repo.get_cash_hands_for_day(day)
            sessions = self.repo.get_sessions_for_day(day)

            # Find biggest win/loss hands
            biggest_win = None
            biggest_loss = None
            for h in hands:
                net = h['net'] or 0
                if net > 0 and (biggest_win is None or net > biggest_win['net']):
                    biggest_win = h
                if net < 0 and (biggest_loss is None or net < biggest_loss['net']):
                    biggest_loss = h

            # Compute total invested (buy-ins)
            total_invested = self._compute_total_invested(sessions)

            reports.append({
                'date': day,
                'hands_count': day_stat['hands'],
                'total_won': day_stat['total_won'] or 0,
                'total_lost': day_stat['total_lost'] or 0,
                'net': day_stat['net'] or 0,
                'biggest_win': biggest_win,
                'biggest_loss': biggest_loss,
                'sessions': sessions,
                'num_sessions': len(sessions),
                'total_invested': total_invested,
            })

        return reports

    def get_summary(self) -> dict:
        """Get overall summary statistics."""
        stats = self.repo.get_cash_stats_summary(self.year)
        daily = self.repo.get_cash_daily_stats(self.year)

        total_days = len(daily)
        total_hands = stats.get('total_hands', 0) or 0
        total_net = stats.get('total_net', 0) or 0

        positive_days = sum(1 for d in daily if (d['net'] or 0) > 0)
        negative_days = sum(1 for d in daily if (d['net'] or 0) < 0)

        return {
            'total_hands': total_hands,
            'total_days': total_days,
            'total_net': total_net,
            'positive_days': positive_days,
            'negative_days': negative_days,
            'avg_per_day': total_net / total_days if total_days > 0 else 0,
        }

    # ── Preflop Stats ──────────────────────────────────────────────

    # Healthy ranges for 6-max NL cash games
    HEALTHY_RANGES = {
        'vpip': (22, 30),
        'pfr': (17, 25),
        'three_bet': (7, 12),
        'fold_to_3bet': (40, 55),
        'ats': (30, 45),
    }

    # Warning ranges (wider band around healthy)
    WARNING_RANGES = {
        'vpip': (18, 35),
        'pfr': (14, 28),
        'three_bet': (4, 15),
        'fold_to_3bet': (30, 65),
        'ats': (20, 55),
    }

    def get_preflop_stats(self) -> dict:
        """Calculate preflop statistics: VPIP, PFR, 3-Bet%, Fold-to-3-Bet%, ATS%.

        Returns dict with overall stats, by-position breakdown, and by-day breakdown.
        Each stat includes value, counts, and health classification.
        """
        sequences = self.repo.get_preflop_action_sequences(self.year)

        # Group by hand_id
        hands_actions = defaultdict(list)
        hand_meta = {}
        for action in sequences:
            hand_id = action['hand_id']
            hands_actions[hand_id].append(action)
            if hand_id not in hand_meta:
                hand_meta[hand_id] = {
                    'hero_position': action.get('hero_position'),
                    'day': action.get('day'),
                }

        # Counters
        total_hands = 0
        vpip_count = 0
        pfr_count = 0
        three_bet_opps = 0
        three_bet_count = 0
        fold_3bet_opps = 0
        fold_3bet_count = 0
        ats_opps = 0
        ats_count = 0

        # Per-position counters
        pos_stats = defaultdict(lambda: {
            'total': 0, 'vpip': 0, 'pfr': 0,
            'three_bet_opps': 0, 'three_bet': 0,
            'ats_opps': 0, 'ats': 0,
        })

        # Per-day counters
        day_stats = defaultdict(lambda: {
            'total': 0, 'vpip': 0, 'pfr': 0,
        })

        for hand_id, actions in hands_actions.items():
            # Only analyze hands where hero was present
            if not any(a['is_hero'] for a in actions):
                continue

            total_hands += 1
            meta = hand_meta[hand_id]
            hero_pos = meta['hero_position']
            day = meta['day']

            if hero_pos:
                pos_stats[hero_pos]['total'] += 1
            if day:
                day_stats[day]['total'] += 1

            # Filter out blind/ante posts for sequence analysis
            voluntary_actions = [
                a for a in actions
                if a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')
            ]

            result = self._analyze_preflop_hand(voluntary_actions)

            if result['vpip']:
                vpip_count += 1
                if hero_pos:
                    pos_stats[hero_pos]['vpip'] += 1
                if day:
                    day_stats[day]['vpip'] += 1

            if result['pfr']:
                pfr_count += 1
                if hero_pos:
                    pos_stats[hero_pos]['pfr'] += 1
                if day:
                    day_stats[day]['pfr'] += 1

            if result['three_bet_opp']:
                three_bet_opps += 1
                if hero_pos:
                    pos_stats[hero_pos]['three_bet_opps'] += 1
                if result['three_bet']:
                    three_bet_count += 1
                    if hero_pos:
                        pos_stats[hero_pos]['three_bet'] += 1

            if result['fold_3bet_opp']:
                fold_3bet_opps += 1
                if result['fold_3bet']:
                    fold_3bet_count += 1

            if result['ats_opp']:
                ats_opps += 1
                if hero_pos:
                    pos_stats[hero_pos]['ats_opps'] += 1
                if result['ats']:
                    ats_count += 1
                    if hero_pos:
                        pos_stats[hero_pos]['ats'] += 1

        return self._format_preflop_stats(
            total_hands, vpip_count, pfr_count,
            three_bet_opps, three_bet_count,
            fold_3bet_opps, fold_3bet_count,
            ats_opps, ats_count,
            dict(pos_stats), dict(day_stats),
        )

    @staticmethod
    def _analyze_preflop_hand(actions: list[dict]) -> dict:
        """Analyze a single hand's preflop non-blind action sequence.

        Returns dict with boolean flags for each stat event.
        """
        hero_vpip = False
        hero_pfr = False
        hero_first_acted = False
        raises_before_hero = 0
        all_fold_before_hero = True
        hero_open_raised = False
        hero_got_3bet = False
        hero_folded_to_3bet = False

        for action in actions:
            is_raise = action['action_type'] in ('raise', 'bet')

            if action['is_hero']:
                if not hero_first_acted:
                    hero_first_acted = True
                    if action.get('is_voluntary'):
                        hero_vpip = True
                    if is_raise:
                        hero_pfr = True
                        if raises_before_hero == 0:
                            hero_open_raised = True
                else:
                    # Hero's subsequent action (facing a re-raise)
                    if action['action_type'] == 'fold' and hero_got_3bet:
                        hero_folded_to_3bet = True
            else:
                if not hero_first_acted:
                    if action['action_type'] != 'fold':
                        all_fold_before_hero = False
                    if is_raise or action['action_type'] == 'all-in':
                        raises_before_hero += 1
                else:
                    # After hero's first action
                    if hero_open_raised and (is_raise or action['action_type'] == 'all-in'):
                        hero_got_3bet = True

        hero_pos = None
        for a in actions:
            if a['is_hero']:
                hero_pos = a.get('position')
                break

        three_bet_opp = raises_before_hero >= 1 and hero_first_acted
        three_bet = three_bet_opp and hero_pfr

        ats_opp = (hero_pos in ('CO', 'BTN', 'SB')
                   and all_fold_before_hero
                   and hero_first_acted)
        ats = ats_opp and hero_pfr

        return {
            'vpip': hero_vpip,
            'pfr': hero_pfr,
            'three_bet_opp': three_bet_opp,
            'three_bet': three_bet,
            'fold_3bet_opp': hero_got_3bet,
            'fold_3bet': hero_folded_to_3bet,
            'ats_opp': ats_opp,
            'ats': ats,
        }

    def _format_preflop_stats(self, total_hands, vpip_count, pfr_count,
                              three_bet_opps, three_bet_count,
                              fold_3bet_opps, fold_3bet_count,
                              ats_opps, ats_count,
                              pos_stats, day_stats) -> dict:
        """Format raw counts into percentages with health badges."""

        def pct(num, den):
            return (num / den * 100) if den > 0 else 0.0

        overall = {
            'total_hands': total_hands,
            'vpip': pct(vpip_count, total_hands),
            'vpip_hands': vpip_count,
            'pfr': pct(pfr_count, total_hands),
            'pfr_hands': pfr_count,
            'three_bet': pct(three_bet_count, three_bet_opps),
            'three_bet_hands': three_bet_count,
            'three_bet_opps': three_bet_opps,
            'fold_to_3bet': pct(fold_3bet_count, fold_3bet_opps),
            'fold_to_3bet_hands': fold_3bet_count,
            'fold_to_3bet_opps': fold_3bet_opps,
            'ats': pct(ats_count, ats_opps),
            'ats_hands': ats_count,
            'ats_opps': ats_opps,
        }

        # Add health badges
        for stat in ('vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats'):
            overall[f'{stat}_health'] = self._classify_health(stat, overall[stat])

        # Format per-position
        by_position = {}
        for pos, counts in pos_stats.items():
            t = counts['total']
            by_position[pos] = {
                'total_hands': t,
                'vpip': pct(counts['vpip'], t),
                'pfr': pct(counts['pfr'], t),
                'three_bet': pct(counts['three_bet'], counts['three_bet_opps']),
                'ats': pct(counts['ats'], counts['ats_opps']),
            }

        # Format per-day
        by_day = {}
        for day, counts in sorted(day_stats.items(), reverse=True):
            t = counts['total']
            by_day[day] = {
                'total_hands': t,
                'vpip': pct(counts['vpip'], t),
                'pfr': pct(counts['pfr'], t),
            }

        return {
            'overall': overall,
            'by_position': by_position,
            'by_day': by_day,
        }

    @classmethod
    def _classify_health(cls, stat_name: str, value: float) -> str:
        """Classify a stat value as 'good', 'warning', or 'danger'."""
        healthy = cls.HEALTHY_RANGES.get(stat_name)
        warning = cls.WARNING_RANGES.get(stat_name)
        if not healthy or not warning:
            return 'good'

        if healthy[0] <= value <= healthy[1]:
            return 'good'
        if warning[0] <= value <= warning[1]:
            return 'warning'
        return 'danger'

    def _compute_total_invested(self, sessions: list[dict]) -> float:
        """Compute total buy-in for a day's sessions."""
        total = 0.0
        prev_cash_out = 0.0
        for i, s in enumerate(sessions):
            bi = s.get('buy_in', 0) or 0
            co = s.get('cash_out', 0) or 0
            if i == 0:
                total += bi
            else:
                if prev_cash_out == 0:
                    total += bi
                else:
                    diff = bi - prev_cash_out
                    if diff > 5:
                        total += diff
            prev_cash_out = co
        return total
