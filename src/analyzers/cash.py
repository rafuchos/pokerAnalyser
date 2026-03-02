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

    # Healthy ranges for 6-max NL postflop stats
    POSTFLOP_HEALTHY_RANGES = {
        'af': (2.0, 3.5),
        'wtsd': (25, 33),
        'wsd': (48, 55),
        'cbet': (60, 75),
        'fold_to_cbet': (35, 50),
        'check_raise': (6, 12),
    }

    POSTFLOP_WARNING_RANGES = {
        'af': (1.5, 4.5),
        'wtsd': (20, 38),
        'wsd': (42, 60),
        'cbet': (50, 85),
        'fold_to_cbet': (25, 60),
        'check_raise': (3, 18),
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

    @classmethod
    def _classify_postflop_health(cls, stat_name: str, value: float) -> str:
        """Classify a postflop stat value as 'good', 'warning', or 'danger'."""
        healthy = cls.POSTFLOP_HEALTHY_RANGES.get(stat_name)
        warning = cls.POSTFLOP_WARNING_RANGES.get(stat_name)
        if not healthy or not warning:
            return 'good'

        if healthy[0] <= value <= healthy[1]:
            return 'good'
        if warning[0] <= value <= warning[1]:
            return 'warning'
        return 'danger'

    # ── Postflop Stats ──────────────────────────────────────────────

    def get_postflop_stats(self) -> dict:
        """Calculate postflop statistics: AF, AFq, WTSD%, W$SD%, CBet%, Fold-to-CBet%, Check-Raise%.

        Returns dict with overall stats, by-street breakdown, and by-week trends.
        """
        sequences = self.repo.get_all_action_sequences(self.year)

        # Group by hand_id
        hands_actions = defaultdict(list)
        hand_meta = {}
        for action in sequences:
            hand_id = action['hand_id']
            hands_actions[hand_id].append(action)
            if hand_id not in hand_meta:
                hand_meta[hand_id] = {
                    'hero_position': action.get('hero_position'),
                    'hero_net': action.get('hero_net', 0) or 0,
                    'day': action.get('day'),
                }

        # Overall counters
        total_hands = 0
        saw_flop_count = 0
        wtsd_count = 0
        wsd_count = 0
        cbet_opps = 0
        cbet_count = 0
        fold_cbet_opps = 0
        fold_cbet_count = 0

        # Aggression counters per street
        agg = {s: {'bets_raises': 0, 'calls': 0, 'total_actions': 0}
               for s in ('flop', 'turn', 'river')}

        # Check-raise counters per street
        cr = {s: {'opps': 0, 'did': 0} for s in ('flop', 'turn', 'river')}

        # Weekly counters
        week_stats = defaultdict(lambda: {
            'total': 0, 'saw_flop': 0, 'wtsd': 0, 'wsd': 0,
            'cbet_opps': 0, 'cbet': 0,
            'bets_raises': 0, 'calls': 0,
        })

        for hand_id, actions in hands_actions.items():
            if not any(a['is_hero'] for a in actions):
                continue

            total_hands += 1
            meta = hand_meta[hand_id]
            week = self._get_week(meta['day'])
            week_stats[week]['total'] += 1

            result = self._analyze_postflop_hand(actions, meta['hero_net'])

            if result['saw_flop']:
                saw_flop_count += 1
                week_stats[week]['saw_flop'] += 1

            if result['went_to_showdown']:
                wtsd_count += 1
                week_stats[week]['wtsd'] += 1

            if result['won_at_showdown']:
                wsd_count += 1
                week_stats[week]['wsd'] += 1

            if result['cbet_opp']:
                cbet_opps += 1
                week_stats[week]['cbet_opps'] += 1
                if result['cbet']:
                    cbet_count += 1
                    week_stats[week]['cbet'] += 1

            if result['fold_to_cbet_opp']:
                fold_cbet_opps += 1
                if result['fold_to_cbet']:
                    fold_cbet_count += 1

            # Aggregate aggression
            for street in ('flop', 'turn', 'river'):
                if street in result['hero_aggression']:
                    ha = result['hero_aggression'][street]
                    br = ha['bets'] + ha['raises']
                    c = ha['calls']
                    f = ha['folds']
                    agg[street]['bets_raises'] += br
                    agg[street]['calls'] += c
                    agg[street]['total_actions'] += br + c + f
                    week_stats[week]['bets_raises'] += br
                    week_stats[week]['calls'] += c

            # Aggregate check-raises
            for street in ('flop', 'turn', 'river'):
                if street in result['check_raise']:
                    cr_data = result['check_raise'][street]
                    if cr_data['opp']:
                        cr[street]['opps'] += 1
                        if cr_data['did']:
                            cr[street]['did'] += 1

        return self._format_postflop_stats(
            total_hands, saw_flop_count, wtsd_count, wsd_count,
            cbet_opps, cbet_count, fold_cbet_opps, fold_cbet_count,
            agg, cr, dict(week_stats),
        )

    @staticmethod
    def _analyze_postflop_hand(all_actions: list[dict], hero_net: float) -> dict:
        """Analyze a single hand for postflop statistics.

        Args:
            all_actions: All actions for the hand (preflop + postflop), ordered by street/sequence.
            hero_net: Hero's net result for the hand (for W$SD detection).

        Returns dict with saw_flop, went_to_showdown, won_at_showdown, CBet info,
        aggression counts per street, and check-raise info per street.

        Note: All-in preflop hands where no postflop actions exist won't count
        as "saw flop" since there are no flop actions to detect.
        """
        preflop = [a for a in all_actions
                   if a['street'] == 'preflop'
                   and a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')]
        postflop = [a for a in all_actions if a['street'] in ('flop', 'turn', 'river')]

        empty_result = {
            'saw_flop': False, 'went_to_showdown': False, 'won_at_showdown': False,
            'cbet_opp': False, 'cbet': False,
            'fold_to_cbet_opp': False, 'fold_to_cbet': False,
            'hero_aggression': {}, 'check_raise': {},
        }

        # Check if hero saw the flop
        hero_flop_actions = [a for a in postflop if a['street'] == 'flop' and a['is_hero']]
        if not hero_flop_actions:
            return empty_result

        # Identify hero name
        hero_name = None
        for a in all_actions:
            if a['is_hero']:
                hero_name = a['player']
                break

        # Find last preflop raiser (PFA = preflop aggressor)
        last_raiser = None
        for a in preflop:
            if a['action_type'] in ('raise', 'bet'):
                last_raiser = a['player']
        hero_is_pfa = last_raiser == hero_name and last_raiser is not None

        # Detect showdown: 2+ players remain (didn't fold) after all postflop action
        flop_players = set()
        folded_players = set()
        for a in postflop:
            if a['street'] == 'flop':
                flop_players.add(a['player'])
            if a['action_type'] == 'fold':
                folded_players.add(a['player'])

        remaining = flop_players - folded_players
        went_to_showdown = len(remaining) >= 2 and hero_name in remaining
        won_at_showdown = went_to_showdown and hero_net > 0

        # CBet detection: hero was PFA and hero made first bet on flop
        cbet_opp = hero_is_pfa
        cbet = False
        flop_actions = [a for a in postflop if a['street'] == 'flop']

        if hero_is_pfa:
            for a in flop_actions:
                if a['action_type'] in ('bet', 'all-in'):
                    if a['is_hero']:
                        cbet = True
                    break  # Only check first money action

        # Fold to CBet: opponent was PFA, opponent bet on flop, hero folded
        fold_to_cbet_opp = False
        fold_to_cbet = False
        if not hero_is_pfa and last_raiser is not None:
            cbet_idx = None
            for i, a in enumerate(flop_actions):
                if a['action_type'] in ('bet', 'all-in'):
                    if not a['is_hero'] and a['player'] == last_raiser:
                        cbet_idx = i
                    break  # Only check first money action

            if cbet_idx is not None:
                for a in flop_actions[cbet_idx + 1:]:
                    if a['is_hero']:
                        fold_to_cbet_opp = True
                        if a['action_type'] == 'fold':
                            fold_to_cbet = True
                        break

        # Hero aggression by street (bets, raises, calls, folds)
        hero_aggression = {}
        for street in ('flop', 'turn', 'river'):
            street_hero = [a for a in postflop if a['street'] == street and a['is_hero']]
            if not street_hero:
                continue
            bets = sum(1 for a in street_hero if a['action_type'] == 'bet')
            raises = sum(1 for a in street_hero if a['action_type'] in ('raise', 'all-in'))
            calls = sum(1 for a in street_hero if a['action_type'] == 'call')
            folds = sum(1 for a in street_hero if a['action_type'] == 'fold')
            hero_aggression[street] = {
                'bets': bets, 'raises': raises, 'calls': calls, 'folds': folds,
            }

        # Check-raise detection by street
        check_raise = {}
        for street in ('flop', 'turn', 'river'):
            street_actions = [a for a in postflop if a['street'] == street]
            hero_checked = False
            opp_bet_after = False
            cr_opp = False
            cr_did = False

            for a in street_actions:
                if a['is_hero']:
                    if a['action_type'] == 'check' and not hero_checked:
                        hero_checked = True
                    elif hero_checked and opp_bet_after:
                        cr_opp = True
                        if a['action_type'] in ('raise', 'all-in'):
                            cr_did = True
                        break
                else:
                    if hero_checked and not opp_bet_after:
                        if a['action_type'] in ('bet', 'raise', 'all-in'):
                            opp_bet_after = True

            if cr_opp:
                check_raise[street] = {'opp': True, 'did': cr_did}

        return {
            'saw_flop': True,
            'went_to_showdown': went_to_showdown,
            'won_at_showdown': won_at_showdown,
            'cbet_opp': cbet_opp,
            'cbet': cbet,
            'fold_to_cbet_opp': fold_to_cbet_opp,
            'fold_to_cbet': fold_to_cbet,
            'hero_aggression': hero_aggression,
            'check_raise': check_raise,
        }

    def _format_postflop_stats(self, total_hands, saw_flop_count, wtsd_count, wsd_count,
                               cbet_opps, cbet_count, fold_cbet_opps, fold_cbet_count,
                               agg, cr, week_stats) -> dict:
        """Format raw postflop counts into percentages with health badges."""

        def pct(num, den):
            return (num / den * 100) if den > 0 else 0.0

        # Overall AF / AFq
        total_br = sum(agg[s]['bets_raises'] for s in ('flop', 'turn', 'river'))
        total_calls = sum(agg[s]['calls'] for s in ('flop', 'turn', 'river'))
        total_actions = sum(agg[s]['total_actions'] for s in ('flop', 'turn', 'river'))

        overall_af = total_br / total_calls if total_calls > 0 else 0.0
        overall_afq = pct(total_br, total_actions)

        # Overall check-raise
        total_cr_opps = sum(cr[s]['opps'] for s in ('flop', 'turn', 'river'))
        total_cr_did = sum(cr[s]['did'] for s in ('flop', 'turn', 'river'))

        overall = {
            'total_hands': total_hands,
            'saw_flop_hands': saw_flop_count,
            'af': overall_af,
            'af_bets_raises': total_br,
            'af_calls': total_calls,
            'afq': overall_afq,
            'wtsd': pct(wtsd_count, saw_flop_count),
            'wtsd_hands': wtsd_count,
            'wtsd_opps': saw_flop_count,
            'wsd': pct(wsd_count, wtsd_count),
            'wsd_hands': wsd_count,
            'wsd_opps': wtsd_count,
            'cbet': pct(cbet_count, cbet_opps),
            'cbet_hands': cbet_count,
            'cbet_opps': cbet_opps,
            'fold_to_cbet': pct(fold_cbet_count, fold_cbet_opps),
            'fold_to_cbet_hands': fold_cbet_count,
            'fold_to_cbet_opps': fold_cbet_opps,
            'check_raise': pct(total_cr_did, total_cr_opps),
            'check_raise_hands': total_cr_did,
            'check_raise_opps': total_cr_opps,
        }

        # Health badges
        for stat in ('af', 'wtsd', 'wsd', 'cbet', 'fold_to_cbet', 'check_raise'):
            overall[f'{stat}_health'] = self._classify_postflop_health(stat, overall[stat])

        # By street
        by_street = {}
        for street in ('flop', 'turn', 'river'):
            s_br = agg[street]['bets_raises']
            s_calls = agg[street]['calls']
            s_total = agg[street]['total_actions']
            s_cr_opps = cr[street]['opps']
            s_cr_did = cr[street]['did']
            by_street[street] = {
                'af': s_br / s_calls if s_calls > 0 else 0.0,
                'afq': pct(s_br, s_total),
                'check_raise': pct(s_cr_did, s_cr_opps),
                'check_raise_hands': s_cr_did,
                'check_raise_opps': s_cr_opps,
            }

        # By week
        by_week = {}
        for week, counts in sorted(week_stats.items()):
            sf = counts['saw_flop']
            w_br = counts['bets_raises']
            w_calls = counts['calls']
            by_week[week] = {
                'total_hands': counts['total'],
                'saw_flop': sf,
                'af': w_br / w_calls if w_calls > 0 else 0.0,
                'wtsd': pct(counts['wtsd'], sf),
                'wsd': pct(counts['wsd'], counts['wtsd']),
                'cbet': pct(counts['cbet'], counts['cbet_opps']),
            }

        return {
            'overall': overall,
            'by_street': by_street,
            'by_week': by_week,
        }

    @staticmethod
    def _get_week(day: str) -> str:
        """Get ISO week string from a date string (YYYY-MM-DD)."""
        if not day:
            return 'unknown'
        d = datetime.strptime(day, '%Y-%m-%d')
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"

    def get_session_stats(self, session: dict) -> dict:
        """Calculate preflop + postflop stats for a single session.

        Returns a dict with VPIP%, PFR%, 3-Bet%, AF, WTSD%, W$SD%, CBet%,
        each with a health classification badge.
        """
        actions = self.repo.get_actions_for_session(session)
        if not actions:
            return {}

        hands_actions = defaultdict(list)
        hand_meta = {}
        for action in actions:
            hand_id = action['hand_id']
            hands_actions[hand_id].append(action)
            if hand_id not in hand_meta:
                hand_meta[hand_id] = {
                    'hero_position': action.get('hero_position'),
                    'hero_net': action.get('hero_net', 0) or 0,
                    'day': action.get('day'),
                }

        total_hands = 0
        vpip_count = 0
        pfr_count = 0
        three_bet_opps = 0
        three_bet_count = 0

        # Postflop counters
        saw_flop_count = 0
        wtsd_count = 0
        wsd_count = 0
        cbet_opps = 0
        cbet_count = 0
        agg_br = 0
        agg_calls = 0

        for hand_id, hand_actions in hands_actions.items():
            if not any(a['is_hero'] for a in hand_actions):
                continue
            total_hands += 1
            meta = hand_meta[hand_id]

            # Preflop analysis
            preflop_voluntary = [
                a for a in hand_actions
                if a['street'] == 'preflop'
                and a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')
            ]
            pre_result = self._analyze_preflop_hand(preflop_voluntary)
            if pre_result['vpip']:
                vpip_count += 1
            if pre_result['pfr']:
                pfr_count += 1
            if pre_result['three_bet_opp']:
                three_bet_opps += 1
                if pre_result['three_bet']:
                    three_bet_count += 1

            # Postflop analysis
            post_result = self._analyze_postflop_hand(hand_actions, meta['hero_net'])
            if post_result['saw_flop']:
                saw_flop_count += 1
            if post_result['went_to_showdown']:
                wtsd_count += 1
            if post_result['won_at_showdown']:
                wsd_count += 1
            if post_result['cbet_opp']:
                cbet_opps += 1
                if post_result['cbet']:
                    cbet_count += 1
            for street in ('flop', 'turn', 'river'):
                if street in post_result['hero_aggression']:
                    ha = post_result['hero_aggression'][street]
                    agg_br += ha['bets'] + ha['raises']
                    agg_calls += ha['calls']

        if total_hands == 0:
            return {}

        def pct(num, den):
            return (num / den * 100) if den > 0 else 0.0

        vpip = pct(vpip_count, total_hands)
        pfr = pct(pfr_count, total_hands)
        three_bet = pct(three_bet_count, three_bet_opps)
        af = agg_br / agg_calls if agg_calls > 0 else 0.0
        wtsd = pct(wtsd_count, saw_flop_count)
        wsd = pct(wsd_count, wtsd_count)
        cbet = pct(cbet_count, cbet_opps)

        return {
            'total_hands': total_hands,
            'vpip': vpip,
            'vpip_health': self._classify_health('vpip', vpip),
            'pfr': pfr,
            'pfr_health': self._classify_health('pfr', pfr),
            'three_bet': three_bet,
            'three_bet_health': self._classify_health('three_bet', three_bet),
            'af': af,
            'af_health': self._classify_postflop_health('af', af),
            'wtsd': wtsd,
            'wtsd_health': self._classify_postflop_health('wtsd', wtsd),
            'wsd': wsd,
            'wsd_health': self._classify_postflop_health('wsd', wsd),
            'cbet': cbet,
            'cbet_health': self._classify_postflop_health('cbet', cbet),
        }

    def get_session_sparkline(self, session: dict) -> list[dict]:
        """Generate sparkline data for a session's stack evolution.

        Returns a list of dicts with 'hand' (1-indexed) and 'profit' (cumulative net).
        """
        hands = self.repo.get_hands_for_session(session)
        if not hands:
            return []
        cumulative = 0.0
        points = []
        for i, h in enumerate(hands, 1):
            cumulative += (h.get('net') or 0)
            points.append({'hand': i, 'profit': cumulative})
        return points

    def get_session_details(self, session: dict) -> dict:
        """Build full session detail: info, stats, sparkline, notable hands."""
        hands = self.repo.get_hands_for_session(session)
        stats = self.get_session_stats(session)
        sparkline = self.get_session_sparkline(session)

        # Notable hands within session
        biggest_win = None
        biggest_loss = None
        for h in hands:
            net = h.get('net') or 0
            if net > 0 and (biggest_win is None or net > biggest_win['net']):
                biggest_win = h
            if net < 0 and (biggest_loss is None or net < biggest_loss['net']):
                biggest_loss = h

        # Parse times for duration
        start = session.get('start_time', '')
        end = session.get('end_time', '')
        duration_minutes = 0
        try:
            st = datetime.fromisoformat(start)
            et = datetime.fromisoformat(end)
            duration_minutes = int((et - st).total_seconds() / 60)
        except (ValueError, TypeError):
            pass

        return {
            'session_id': session.get('session_id'),
            'start_time': start,
            'end_time': end,
            'duration_minutes': duration_minutes,
            'buy_in': session.get('buy_in', 0) or 0,
            'cash_out': session.get('cash_out', 0) or 0,
            'profit': session.get('profit', 0) or 0,
            'hands_count': session.get('hands_count', 0) or 0,
            'min_stack': session.get('min_stack', 0) or 0,
            'stats': stats,
            'sparkline': sparkline,
            'biggest_win': biggest_win,
            'biggest_loss': biggest_loss,
        }

    def get_daily_reports_with_sessions(self) -> list[dict]:
        """Build daily report data with session breakdown.

        Each day contains session details with stats, sparkline, and notable hands.
        Day-level stats are weighted averages of session stats (by hands count).
        """
        daily_stats = self.repo.get_cash_daily_stats(self.year)
        reports = []

        for day_stat in daily_stats:
            day = day_stat['day']
            sessions_raw = self.repo.get_sessions_for_day(day)

            # Build session details
            session_details = []
            for s in sessions_raw:
                detail = self.get_session_details(s)
                session_details.append(detail)

            # Weighted average day stats from sessions
            day_stats_agg = self._aggregate_session_stats(session_details)

            # Total invested
            total_invested = self._compute_total_invested(sessions_raw)

            # Session comparison data
            comparison = self._build_session_comparison(session_details)

            reports.append({
                'date': day,
                'hands_count': day_stat['hands'],
                'total_won': day_stat['total_won'] or 0,
                'total_lost': day_stat['total_lost'] or 0,
                'net': day_stat['net'] or 0,
                'sessions': session_details,
                'num_sessions': len(session_details),
                'total_invested': total_invested,
                'day_stats': day_stats_agg,
                'comparison': comparison,
            })

        return reports

    @staticmethod
    def _aggregate_session_stats(session_details: list[dict]) -> dict:
        """Compute weighted average stats across sessions (weighted by hands count)."""
        stats_keys = ['vpip', 'pfr', 'three_bet', 'af', 'wtsd', 'wsd', 'cbet']
        total_hands = 0
        weighted = {k: 0.0 for k in stats_keys}

        for sd in session_details:
            st = sd.get('stats', {})
            h = st.get('total_hands', 0)
            if h == 0:
                continue
            total_hands += h
            for k in stats_keys:
                weighted[k] += st.get(k, 0) * h

        if total_hands == 0:
            return {}

        result = {'total_hands': total_hands}
        for k in stats_keys:
            result[k] = weighted[k] / total_hands
        return result

    @staticmethod
    def _build_session_comparison(session_details: list[dict]) -> dict:
        """Build comparison data identifying best/worst sessions per stat."""
        if len(session_details) < 2:
            return {}

        stats_keys = ['vpip', 'pfr', 'af', 'wtsd', 'wsd', 'cbet']
        comparison = {}

        for key in stats_keys:
            sessions_with_stat = [
                (i, sd['stats'].get(key, 0))
                for i, sd in enumerate(session_details)
                if sd.get('stats', {}).get('total_hands', 0) > 0
            ]
            if len(sessions_with_stat) < 2:
                continue
            best_idx = max(sessions_with_stat, key=lambda x: x[1])[0]
            worst_idx = min(sessions_with_stat, key=lambda x: x[1])[0]
            comparison[key] = {'best': best_idx, 'worst': worst_idx}

        # Profit comparison
        profit_sessions = [
            (i, sd.get('profit', 0))
            for i, sd in enumerate(session_details)
        ]
        if len(profit_sessions) >= 2:
            comparison['profit'] = {
                'best': max(profit_sessions, key=lambda x: x[1])[0],
                'worst': min(profit_sessions, key=lambda x: x[1])[0],
            }

        return comparison

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
