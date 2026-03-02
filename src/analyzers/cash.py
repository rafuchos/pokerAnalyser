"""Cash game analysis module.

Reads from database and computes statistics for reports.
"""

from collections import defaultdict
from datetime import datetime

from src.db.repository import Repository


class CashAnalyzer:
    """Analyze cash game data from the database."""

    def __init__(self, repo: Repository, year: str = '2026', config=None):
        """Initialise CashAnalyzer.

        Args:
            repo: Repository instance for database access.
            year: Year string used to filter hands (default '2026').
            config: Optional TargetsConfig.  When provided, health
                classification and the range dicts exposed to LeakFinder
                use the config values instead of the class-level defaults.
        """
        self.repo = repo
        self.year = year

        if config is not None:
            # ── Expose range dicts for LeakFinder access ──────────────
            self._healthy_ranges = config.healthy_ranges
            self._warning_ranges = config.warning_ranges
            self._postflop_healthy_ranges = config.postflop_healthy_ranges
            self._postflop_warning_ranges = config.postflop_warning_ranges
            self._pos_vpip_healthy = config.position_vpip_healthy
            self._pos_vpip_warning = config.position_vpip_warning
            self._pos_pfr_healthy = config.position_pfr_healthy
            self._pos_pfr_warning = config.position_pfr_warning

            # ── Override classify methods at the instance level ────────
            # Python instance attributes shadow class attributes (incl.
            # classmethods) so these lambdas are called instead of the
            # @classmethods when accessed through self.
            _h = self._healthy_ranges
            _w = self._warning_ranges
            _pfh = self._postflop_healthy_ranges
            _pfw = self._postflop_warning_ranges
            _pvh = self._pos_vpip_healthy
            _pvw = self._pos_vpip_warning
            _pph = self._pos_pfr_healthy
            _ppw = self._pos_pfr_warning

            def _classify_health(stat_name: str, value: float) -> str:
                healthy = _h.get(stat_name)
                warning = _w.get(stat_name)
                if not healthy or not warning:
                    return 'good'
                if healthy[0] <= value <= healthy[1]:
                    return 'good'
                if warning[0] <= value <= warning[1]:
                    return 'warning'
                return 'danger'

            def _classify_postflop_health(stat_name: str, value: float) -> str:
                healthy = _pfh.get(stat_name)
                warning = _pfw.get(stat_name)
                if not healthy or not warning:
                    return 'good'
                if healthy[0] <= value <= healthy[1]:
                    return 'good'
                if warning[0] <= value <= warning[1]:
                    return 'warning'
                return 'danger'

            def _classify_positional_health(stat: str, pos: str,
                                            value: float) -> str:
                if stat == 'vpip':
                    h = _pvh.get(pos, _h.get('vpip'))
                    w = _pvw.get(pos, _w.get('vpip'))
                elif stat == 'pfr':
                    h = _pph.get(pos, _h.get('pfr'))
                    w = _ppw.get(pos, _w.get('pfr'))
                else:
                    return _classify_health(stat, value)
                if h and h[0] <= value <= h[1]:
                    return 'good'
                if w and w[0] <= value <= w[1]:
                    return 'warning'
                return 'danger'

            self._classify_health = _classify_health
            self._classify_postflop_health = _classify_postflop_health
            self._classify_positional_health = _classify_positional_health
        else:
            # Point to class-level defaults (no copy overhead)
            self._healthy_ranges = type(self).HEALTHY_RANGES
            self._warning_ranges = type(self).WARNING_RANGES
            self._postflop_healthy_ranges = type(self).POSTFLOP_HEALTHY_RANGES
            self._postflop_warning_ranges = type(self).POSTFLOP_WARNING_RANGES
            self._pos_vpip_healthy = type(self).POSITION_VPIP_HEALTHY
            self._pos_vpip_warning = type(self).POSITION_VPIP_WARNING
            self._pos_pfr_healthy = type(self).POSITION_PFR_HEALTHY
            self._pos_pfr_warning = type(self).POSITION_PFR_WARNING

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

    def get_session_details(self, session: dict, ev_analyzer=None) -> dict:
        """Build full session detail: info, stats, sparkline, notable hands, EV."""
        hands = self.repo.get_hands_for_session(session)
        stats = self.get_session_stats(session)
        sparkline = self.get_session_sparkline(session)

        # Session-level EV analysis
        ev_data = None
        if ev_analyzer is not None:
            ev_data = ev_analyzer.get_session_ev_analysis(session)

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
            'ev_data': ev_data,
        }

    def get_daily_reports_with_sessions(self, ev_analyzer=None) -> list[dict]:
        """Build daily report data with session breakdown.

        Each day contains session details with stats, sparkline, notable hands, and EV.
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
                detail = self.get_session_details(s, ev_analyzer=ev_analyzer)
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

    # ── Positional Analysis ──────────────────────────────────────────

    # Per-position VPIP healthy/warning ranges for 6-max NL
    # UTG is tightest (early position), BTN is loosest (button)
    POSITION_VPIP_HEALTHY = {
        'UTG':  (12, 18), 'UTG+1': (13, 20), 'MP': (15, 22), 'MP+1': (16, 23),
        'HJ':   (17, 24), 'CO': (22, 30), 'BTN': (30, 45),
        'SB':   (20, 32), 'BB': (25, 42),
    }
    POSITION_VPIP_WARNING = {
        'UTG':  (9, 24), 'UTG+1': (10, 26), 'MP': (11, 28), 'MP+1': (12, 29),
        'HJ':   (13, 31), 'CO': (17, 37), 'BTN': (24, 55),
        'SB':   (15, 40), 'BB': (19, 52),
    }

    # Per-position PFR healthy/warning ranges
    POSITION_PFR_HEALTHY = {
        'UTG':  (10, 16), 'UTG+1': (11, 17), 'MP': (12, 19), 'MP+1': (13, 20),
        'HJ':   (14, 21), 'CO': (18, 27), 'BTN': (25, 40),
        'SB':   (15, 25), 'BB': (8, 15),
    }
    POSITION_PFR_WARNING = {
        'UTG':  (7, 20), 'UTG+1': (8, 21), 'MP': (9, 24), 'MP+1': (10, 25),
        'HJ':   (11, 26), 'CO': (13, 33), 'BTN': (19, 50),
        'SB':   (10, 32), 'BB': (5, 20),
    }

    @classmethod
    def _classify_positional_health(cls, stat: str, pos: str, value: float) -> str:
        """Classify a per-position stat using position-specific healthy ranges.

        Falls back to overall healthy/warning ranges if no per-position entry exists.
        """
        if stat == 'vpip':
            healthy = cls.POSITION_VPIP_HEALTHY.get(pos, cls.HEALTHY_RANGES.get('vpip'))
            warning = cls.POSITION_VPIP_WARNING.get(pos, cls.WARNING_RANGES.get('vpip'))
        elif stat == 'pfr':
            healthy = cls.POSITION_PFR_HEALTHY.get(pos, cls.HEALTHY_RANGES.get('pfr'))
            warning = cls.POSITION_PFR_WARNING.get(pos, cls.WARNING_RANGES.get('pfr'))
        else:
            return cls._classify_health(stat, value)

        if healthy and healthy[0] <= value <= healthy[1]:
            return 'good'
        if warning and warning[0] <= value <= warning[1]:
            return 'warning'
        return 'danger'

    @staticmethod
    def _analyze_blinds_defense(voluntary_actions: list[dict], hero_pos: str) -> dict:
        """Analyze blinds defense for BB/SB: detect steal attempts and hero's response.

        A steal attempt is a single raise from CO/BTN/SB into BB, or CO/BTN into SB,
        with all other non-raiser players having folded (no limpers).

        Returns dict with steal_opp, fold_to_steal, three_bet_vs_steal, call_vs_steal.
        """
        steal_positions = {
            'BB': ('CO', 'BTN', 'SB'),
            'SB': ('CO', 'BTN'),
        }
        valid_stealers = steal_positions.get(hero_pos, ())

        hero_first_acted = False
        all_others_folded = True   # True until a non-fold, non-raise action appears
        raises_before_hero = 0
        raiser_position = None

        for action in voluntary_actions:
            is_raise = action['action_type'] in ('raise', 'bet')

            if action['is_hero']:
                if not hero_first_acted:
                    hero_first_acted = True
                    # Steal opportunity: exactly one raise from a steal position,
                    # with all other players having folded (no limpers).
                    steal_opp = (
                        raises_before_hero == 1
                        and all_others_folded
                        and raiser_position in valid_stealers
                    )
                    if not steal_opp:
                        return {
                            'steal_opp': False, 'fold_to_steal': False,
                            'three_bet_vs_steal': False, 'call_vs_steal': False,
                        }
                    # Classify hero response
                    fold_to_steal = action['action_type'] == 'fold'
                    three_bet_vs_steal = action['action_type'] in ('raise', 'bet', 'all-in')
                    call_vs_steal = action['action_type'] == 'call'
                    return {
                        'steal_opp': True,
                        'fold_to_steal': fold_to_steal,
                        'three_bet_vs_steal': three_bet_vs_steal,
                        'call_vs_steal': call_vs_steal,
                    }
            else:
                if not hero_first_acted:
                    if is_raise or action['action_type'] == 'all-in':
                        raises_before_hero += 1
                        raiser_position = action.get('position')
                    elif action['action_type'] != 'fold':
                        # Someone called (limped) - not a clean steal
                        all_others_folded = False

        return {
            'steal_opp': False, 'fold_to_steal': False,
            'three_bet_vs_steal': False, 'call_vs_steal': False,
        }

    def get_positional_stats(self) -> dict:
        """Calculate per-position stats: VPIP, PFR, 3-Bet, AF, CBet, WTSD, W$SD, win rate.

        Also computes:
        - Health badges using position-specific ranges
        - ATS% per steal position (CO, BTN, SB)
        - Blinds defense: fold-to-steal%, 3-bet-vs-steal%, call-vs-steal% for BB/SB
        - Most profitable vs most deficitary position comparison
        - Radar chart data (normalized stats per position)

        Returns dict with by_position, blinds_defense, ats_by_pos, comparison, radar.
        Works for both cash games (game_type='cash') and is structured for reuse.
        """
        sequences = self.repo.get_all_action_sequences(self.year)
        hands_financial = self.repo.get_cash_hands_with_position(self.year)

        # Build hand-level financial lookup: hand_id → (blinds_bb, hero_position)
        hand_bb = {}
        for h in hands_financial:
            hand_bb[h['hand_id']] = h.get('blinds_bb') or 0.50

        # Group actions by hand_id
        hands_actions = defaultdict(list)
        hand_meta = {}
        for action in sequences:
            hand_id = action['hand_id']
            hands_actions[hand_id].append(action)
            if hand_id not in hand_meta:
                hand_meta[hand_id] = {
                    'hero_position': action.get('hero_position'),
                    'hero_net': action.get('hero_net', 0) or 0,
                }

        # Per-position counters
        pos_data = defaultdict(lambda: {
            'total': 0,
            'vpip': 0, 'pfr': 0,
            'three_bet_opps': 0, 'three_bet': 0,
            'ats_opps': 0, 'ats': 0,
            'fold_steal_opps': 0, 'fold_steal': 0,
            'three_bet_steal_opps': 0, 'three_bet_steal': 0,
            'call_steal_opps': 0, 'call_steal': 0,
            'saw_flop': 0, 'wtsd': 0, 'wsd': 0,
            'cbet_opps': 0, 'cbet': 0,
            'agg_br': 0, 'agg_calls': 0,
            'net': 0.0, 'bb_net': 0.0,
        })

        for hand_id, actions in hands_actions.items():
            if not any(a['is_hero'] for a in actions):
                continue

            meta = hand_meta[hand_id]
            hero_pos = meta['hero_position']
            hero_net = meta['hero_net']
            if not hero_pos:
                hero_pos = 'Unknown'

            pd = pos_data[hero_pos]
            pd['total'] += 1
            pd['net'] += hero_net
            bb = hand_bb.get(hand_id, 0.50)
            pd['bb_net'] += (hero_net / bb) if bb > 0 else 0.0

            # Preflop analysis
            preflop_vol = [
                a for a in actions
                if a['street'] == 'preflop'
                and a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')
            ]
            pre = self._analyze_preflop_hand(preflop_vol)

            if pre['vpip']:
                pd['vpip'] += 1
            if pre['pfr']:
                pd['pfr'] += 1
            if pre['three_bet_opp']:
                pd['three_bet_opps'] += 1
                if pre['three_bet']:
                    pd['three_bet'] += 1
            if pre['ats_opp']:
                pd['ats_opps'] += 1
                if pre['ats']:
                    pd['ats'] += 1

            # Blinds defense for BB/SB
            if hero_pos in ('BB', 'SB'):
                bd = self._analyze_blinds_defense(preflop_vol, hero_pos)
                if bd['steal_opp']:
                    pd['fold_steal_opps'] += 1
                    pd['three_bet_steal_opps'] += 1
                    pd['call_steal_opps'] += 1
                    if bd['fold_to_steal']:
                        pd['fold_steal'] += 1
                    if bd['three_bet_vs_steal']:
                        pd['three_bet_steal'] += 1
                    if bd['call_vs_steal']:
                        pd['call_steal'] += 1

            # Postflop analysis
            post = self._analyze_postflop_hand(actions, hero_net)
            if post['saw_flop']:
                pd['saw_flop'] += 1
            if post['went_to_showdown']:
                pd['wtsd'] += 1
            if post['won_at_showdown']:
                pd['wsd'] += 1
            if post['cbet_opp']:
                pd['cbet_opps'] += 1
                if post['cbet']:
                    pd['cbet'] += 1
            for street in ('flop', 'turn', 'river'):
                if street in post['hero_aggression']:
                    ha = post['hero_aggression'][street]
                    pd['agg_br'] += ha['bets'] + ha['raises']
                    pd['agg_calls'] += ha['calls']

        return self._format_positional_stats(dict(pos_data))

    def _format_positional_stats(self, pos_data: dict) -> dict:
        """Format raw positional counters into percentages with health badges.

        Returns dict with by_position, blinds_defense, ats_by_pos, comparison, radar.
        """
        def pct(num, den):
            return (num / den * 100) if den > 0 else 0.0

        position_order = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']

        by_position = {}
        for pos in position_order:
            if pos not in pos_data:
                continue
            pd = pos_data[pos]
            t = pd['total']
            if t == 0:
                continue

            vpip = pct(pd['vpip'], t)
            pfr = pct(pd['pfr'], t)
            three_bet = pct(pd['three_bet'], pd['three_bet_opps'])
            af = pd['agg_br'] / pd['agg_calls'] if pd['agg_calls'] > 0 else 0.0
            cbet = pct(pd['cbet'], pd['cbet_opps'])
            wtsd = pct(pd['wtsd'], pd['saw_flop'])
            wsd = pct(pd['wsd'], pd['wtsd'])
            net_per_hand = pd['net'] / t
            bb_per_100 = (pd['bb_net'] / t) * 100  # bb/100

            by_position[pos] = {
                'total_hands': t,
                'vpip': vpip,
                'vpip_health': self._classify_positional_health('vpip', pos, vpip),
                'pfr': pfr,
                'pfr_health': self._classify_positional_health('pfr', pos, pfr),
                'three_bet': three_bet,
                'three_bet_health': self._classify_health('three_bet', three_bet),
                'af': af,
                'af_health': self._classify_postflop_health('af', af),
                'cbet': cbet,
                'cbet_health': self._classify_postflop_health('cbet', cbet),
                'wtsd': wtsd,
                'wtsd_health': self._classify_postflop_health('wtsd', wtsd),
                'wsd': wsd,
                'wsd_health': self._classify_postflop_health('wsd', wsd),
                'net': pd['net'],
                'net_per_hand': net_per_hand,
                'bb_per_100': bb_per_100,
                'winrate_health': 'good' if net_per_hand >= 0 else 'danger',
                'ats': pct(pd['ats'], pd['ats_opps']),
                'ats_opps': pd['ats_opps'],
                'ats_count': pd['ats'],
            }

        # Blinds defense breakdown (BB and SB only)
        blinds_defense = {}
        for pos in ('BB', 'SB'):
            if pos not in pos_data:
                continue
            pd = pos_data[pos]
            opps = pd['fold_steal_opps']
            if opps > 0:
                blinds_defense[pos] = {
                    'steal_opps': opps,
                    'fold_to_steal': pct(pd['fold_steal'], opps),
                    'fold_to_steal_count': pd['fold_steal'],
                    'three_bet_vs_steal': pct(pd['three_bet_steal'], opps),
                    'three_bet_vs_steal_count': pd['three_bet_steal'],
                    'call_vs_steal': pct(pd['call_steal'], opps),
                    'call_vs_steal_count': pd['call_steal'],
                }

        # ATS by steal position (CO, BTN, SB)
        ats_by_pos = {}
        for pos in ('CO', 'BTN', 'SB'):
            if pos in by_position and by_position[pos]['ats_opps'] > 0:
                ats_by_pos[pos] = {
                    'ats': by_position[pos]['ats'],
                    'ats_opps': by_position[pos]['ats_opps'],
                    'ats_count': by_position[pos]['ats_count'],
                }

        # Most profitable vs most deficitary comparison
        comparison = {}
        if by_position:
            profitable = max(by_position.items(), key=lambda x: x[1]['bb_per_100'])
            deficitary = min(by_position.items(), key=lambda x: x[1]['bb_per_100'])
            if profitable[0] != deficitary[0]:
                comparison = {
                    'most_profitable': {'position': profitable[0], **profitable[1]},
                    'most_deficitary': {'position': deficitary[0], **deficitary[1]},
                }

        # Radar chart data: normalized key stats per position
        radar = self._build_radar_data(by_position)

        return {
            'by_position': by_position,
            'blinds_defense': blinds_defense,
            'ats_by_pos': ats_by_pos,
            'comparison': comparison,
            'radar': radar,
        }

    @staticmethod
    def _build_radar_data(by_position: dict) -> list[dict]:
        """Build radar/spider chart data: normalized key stats per position.

        Stats normalized to 0-100 scale relative to the observed range.
        Returns list of dicts with position and normalized axis values.
        """
        if not by_position:
            return []

        # Axes: stat_key, display_label, max expected value for normalization
        axes = [
            ('vpip', 'VPIP', 60.0),
            ('pfr', 'PFR', 50.0),
            ('three_bet', '3-Bet', 20.0),
            ('af', 'AF', 5.0),
            ('cbet', 'CBet', 100.0),
            ('wtsd', 'WTSD', 50.0),
            ('wsd', 'W$SD', 70.0),
        ]

        radar = []
        position_order = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']
        for pos in position_order:
            if pos not in by_position:
                continue
            pd = by_position[pos]
            normalized = {}
            for key, label, max_val in axes:
                raw = pd.get(key, 0)
                normalized[key] = min(raw / max_val * 100, 100) if max_val > 0 else 0
            radar.append({
                'position': pos,
                'values': normalized,
                'hands': pd['total_hands'],
                'bb_per_100': pd['bb_per_100'],
            })

        return radar

    # ── Hand Matrix (Preflop Range Visualization) ──────────────────

    def get_hand_matrix(self) -> dict:
        """Build 13x13 hand matrix data grouped by position.

        For each position and each hand category (e.g. 'AKs', 'AKo', 'AA'),
        computes:
        - times_dealt / times_played / frequency
        - action breakdown: open_raise, call, three_bet counts
        - net and win_rate (bb/100)

        Returns dict with:
        - by_position: {pos: {hand_cat: {...stats...}}}
        - overall: {hand_cat: {...stats...}}
        - top_profitable: list of top 10 most profitable hands
        - top_deficit: list of top 10 most deficit hands
        """
        hands = self.repo.get_cash_hands_with_cards(self.year)
        preflop_seqs = self.repo.get_preflop_action_sequences(self.year)

        # Group preflop actions by hand_id
        hand_preflop = defaultdict(list)
        for a in preflop_seqs:
            hand_preflop[a['hand_id']].append(a)

        # Accumulators: overall and per-position
        overall = defaultdict(lambda: {
            'dealt': 0, 'played': 0,
            'open_raise': 0, 'call': 0, 'three_bet': 0,
            'net': 0.0, 'bb_net': 0.0,
        })
        by_position = defaultdict(lambda: defaultdict(lambda: {
            'dealt': 0, 'played': 0,
            'open_raise': 0, 'call': 0, 'three_bet': 0,
            'net': 0.0, 'bb_net': 0.0,
        }))

        for hand in hands:
            hero_cards = hand.get('hero_cards')
            if not hero_cards:
                continue
            cat = _categorize_hand(hero_cards)
            if not cat:
                continue

            pos = hand.get('hero_position') or 'Unknown'
            net = hand.get('net') or 0.0
            bb = hand.get('blinds_bb') or 0.50
            bb_net = net / bb if bb > 0 else 0.0

            # Count dealt
            overall[cat]['dealt'] += 1
            by_position[pos][cat]['dealt'] += 1

            # Determine preflop action from action sequences
            actions = hand_preflop.get(hand['hand_id'], [])
            action_type = _classify_preflop_action(actions)

            if action_type:
                overall[cat]['played'] += 1
                by_position[pos][cat]['played'] += 1
                if action_type == 'open_raise':
                    overall[cat]['open_raise'] += 1
                    by_position[pos][cat]['open_raise'] += 1
                elif action_type == 'call':
                    overall[cat]['call'] += 1
                    by_position[pos][cat]['call'] += 1
                elif action_type == 'three_bet':
                    overall[cat]['three_bet'] += 1
                    by_position[pos][cat]['three_bet'] += 1

            overall[cat]['net'] += net
            overall[cat]['bb_net'] += bb_net
            by_position[pos][cat]['net'] += net
            by_position[pos][cat]['bb_net'] += bb_net

        # Format results
        def _format_matrix(data):
            result = {}
            for cat, d in data.items():
                dealt = d['dealt']
                played = d['played']
                result[cat] = {
                    'dealt': dealt,
                    'played': played,
                    'frequency': round(played / dealt * 100, 1) if dealt > 0 else 0.0,
                    'open_raise': d['open_raise'],
                    'call': d['call'],
                    'three_bet': d['three_bet'],
                    'net': round(d['net'], 2),
                    'bb_net': round(d['bb_net'], 2),
                    'win_rate': round(d['bb_net'] / dealt * 100, 2) if dealt > 0 else 0.0,
                }
            return result

        overall_formatted = _format_matrix(overall)
        by_pos_formatted = {}
        for pos, cats in by_position.items():
            by_pos_formatted[pos] = _format_matrix(cats)

        # Top 10 most profitable and top 10 most deficit
        sorted_by_winrate = sorted(
            overall_formatted.items(),
            key=lambda x: x[1]['win_rate'],
            reverse=True,
        )
        top_profitable = [
            {'hand': cat, **stats}
            for cat, stats in sorted_by_winrate
            if stats['dealt'] >= 3 and stats['win_rate'] > 0
        ][:10]
        top_deficit = [
            {'hand': cat, **stats}
            for cat, stats in reversed(sorted_by_winrate)
            if stats['dealt'] >= 3 and stats['win_rate'] < 0
        ][:10]

        return {
            'overall': overall_formatted,
            'by_position': dict(by_pos_formatted),
            'top_profitable': top_profitable,
            'top_deficit': top_deficit,
            'total_hands': sum(d['dealt'] for d in overall_formatted.values()),
        }

    # ── Leak Finder ──────────────────────────────────────────────────

    def get_leak_analysis(self) -> dict:
        """Run leak finder analysis.

        Returns dict with leaks, top5, study_spots, health_score,
        period_comparison, and total_leaks.
        """
        from src.analyzers.leak_finder import LeakFinder
        finder = LeakFinder(self, self.repo, self.year)
        return finder.find_leaks()

    # ── Tilt Detection & Time/Duration Performance ────────────────────

    def get_tilt_analysis(self) -> dict:
        """Run tilt detection and performance-timing analysis.

        Returns dict with session_tilt, hourly, duration, post_bad_beat,
        recommendation, diagnostics, and tilt_sessions_count.
        """
        from src.analyzers.tilt import TiltAnalyzer
        tilt = TiltAnalyzer(self.repo, self.year)
        return tilt.get_tilt_analysis()

    # ── Bet Sizing & Pot-Type Segmentation ───────────────────────────

    def get_bet_sizing_analysis(self) -> dict:
        """Compute bet sizing and pot-type segmentation statistics.

        Classifies each hand by pot type (limped, SRP, 3-bet, 4-bet+) and
        computes per-type stats: VPIP, PFR, AF, CBet, WTSD, W$SD, win rate.
        Also tracks bet sizing distributions by street and separates
        heads-up vs multiway results.

        Returns dict with pot_types, sizing, hu_vs_multiway, diagnostics.
        """
        hands = self.repo.get_cash_hands(self.year)
        actions_list = self.repo.get_all_action_sequences(self.year)

        # Build per-hand lookup
        hand_meta = {h['hand_id']: h for h in hands}
        hand_acts = defaultdict(list)
        for a in actions_list:
            hand_acts[a['hand_id']].append(a)

        pot_type_keys = ('limped', 'srp', '3bet', '4bet_plus')
        pt_data = {k: _empty_pt_acc() for k in pot_type_keys}
        hu_data = _empty_pt_acc()
        mw_data = _empty_pt_acc()

        preflop_sizes: list[float] = []
        flop_sizes: list[float] = []
        turn_sizes: list[float] = []
        river_sizes: list[float] = []

        total_hands = 0

        for hand_id, actions in hand_acts.items():
            if not any(a['is_hero'] for a in actions):
                continue
            meta = hand_meta.get(hand_id)
            if not meta:
                continue

            total_hands += 1
            net = meta['net'] or 0.0
            blinds_bb = meta['blinds_bb'] or 0.5

            preflop = [a for a in actions if a['street'] == 'preflop']
            pot_type = _classify_pot_type(preflop)

            # Determine HU vs multiway based on players who saw the flop
            flop_players = {a['player'] for a in actions if a['street'] == 'flop'}
            if flop_players:
                is_hu = len(flop_players) <= 2
            else:
                # Preflop-only hand: use non-folded preflop players
                is_hu = _count_active_players(preflop) <= 2

            # Preflop analysis (exclude blind posts)
            voluntary = [a for a in preflop
                         if a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')]
            pf_pre = self._analyze_preflop_hand(voluntary)

            # Postflop analysis
            hero_net = (actions[0].get('hero_net') or 0.0) if actions else 0.0
            pf_post = self._analyze_postflop_hand(actions, hero_net)

            # Accumulate pot-type stats
            _accumulate_pt(pt_data[pot_type], net, blinds_bb, is_hu, pf_pre, pf_post)

            # Accumulate HU / multiway
            if is_hu:
                _accumulate_pt(hu_data, net, blinds_bb, True, pf_pre, pf_post)
            else:
                _accumulate_pt(mw_data, net, blinds_bb, False, pf_pre, pf_post)

            # Collect sizing data
            sizing = _compute_bet_sizing(actions, blinds_bb)
            if sizing['preflop_raise_bb'] is not None:
                preflop_sizes.append(sizing['preflop_raise_bb'])
            for street, lst in (('flop', flop_sizes), ('turn', turn_sizes), ('river', river_sizes)):
                val = sizing.get(f'{street}_bet_pct')
                if val is not None:
                    lst.append(val)

        pot_types_fmt = {k: _format_pt_stats(pt_data[k]) for k in pot_type_keys}

        return {
            'total_hands': total_hands,
            'pot_types': pot_types_fmt,
            'sizing': {
                'preflop': _format_sizing_data(preflop_sizes, _PREFLOP_BUCKETS),
                'flop': _format_sizing_data(flop_sizes, _POSTFLOP_BUCKETS),
                'turn': _format_sizing_data(turn_sizes, _POSTFLOP_BUCKETS),
                'river': _format_sizing_data(river_sizes, _POSTFLOP_BUCKETS),
            },
            'hu_vs_multiway': {
                'heads_up': _format_pt_stats(hu_data),
                'multiway': _format_pt_stats(mw_data),
            },
            'diagnostics': _generate_bet_sizing_diagnostics(pot_types_fmt, preflop_sizes, total_hands),
        }

    # ── Red Line / Blue Line ──────────────────────────────────────────

    def get_redline_blueline(self) -> dict:
        """Compute Red Line / Blue Line cumulative profit statistics.

        Red line  = cumulative profit from non-showdown hands.
        Blue line = cumulative profit from showdown hands.
        Green line = total profit (red + blue).

        Returns dict with chart_data (3 cumulative lines), summary totals,
        diagnostic messages, and per-session breakdown.
        """
        hands = self.repo.get_cash_hands(self.year)
        actions = self.repo.get_all_action_sequences(self.year)

        # Group actions by hand_id
        hand_acts = defaultdict(list)
        for a in actions:
            hand_acts[a['hand_id']].append(a)

        cum_total = 0.0
        cum_showdown = 0.0
        cum_nonshowdown = 0.0
        total_hands = 0
        showdown_hands = 0
        nonshowdown_hands = 0
        showdown_net = 0.0
        nonshowdown_net = 0.0
        chart_data = []

        for h in hands:
            hand_id = h['hand_id']
            net = h['net'] or 0.0
            went_to_sd = self._hand_went_to_showdown(hand_acts.get(hand_id, []), h)

            cum_total += net
            total_hands += 1

            if went_to_sd:
                cum_showdown += net
                showdown_hands += 1
                showdown_net += net
            else:
                cum_nonshowdown += net
                nonshowdown_hands += 1
                nonshowdown_net += net

            chart_data.append({
                'hand': total_hands,
                'total': round(cum_total, 2),
                'showdown': round(cum_showdown, 2),
                'nonshowdown': round(cum_nonshowdown, 2),
            })

        if len(chart_data) > 500:
            chart_data = _downsample_redline(chart_data, 500)

        sessions = self.repo.get_sessions(self.year)
        by_session = self._compute_redline_by_session(sessions, hand_acts)

        diagnostics = _generate_redline_diagnostics(
            showdown_net, nonshowdown_net,
            showdown_hands, nonshowdown_hands, total_hands,
        )

        return {
            'chart_data': chart_data,
            'total_hands': total_hands,
            'showdown_hands': showdown_hands,
            'nonshowdown_hands': nonshowdown_hands,
            'total_net': round(cum_total, 2),
            'showdown_net': round(showdown_net, 2),
            'nonshowdown_net': round(nonshowdown_net, 2),
            'diagnostics': diagnostics,
            'by_session': by_session,
        }

    def _compute_redline_by_session(self, sessions: list[dict],
                                     hand_acts: dict) -> list[dict]:
        """Compute red/blue line stats per cash session."""
        result = []
        for session in sessions:
            hands = self.repo.get_hands_for_session(session)
            sd_net = 0.0
            nsd_net = 0.0
            sd_count = 0
            nsd_count = 0
            for h in hands:
                hand_id = h['hand_id']
                net = h['net'] or 0.0
                went_to_sd = self._hand_went_to_showdown(
                    hand_acts.get(hand_id, []), h
                )
                if went_to_sd:
                    sd_net += net
                    sd_count += 1
                else:
                    nsd_net += net
                    nsd_count += 1

            total = sd_count + nsd_count
            if total > 0:
                result.append({
                    'session_id': session.get('session_id'),
                    'date': session.get('date', ''),
                    'start_time': session.get('start_time', ''),
                    'hands': total,
                    'showdown_hands': sd_count,
                    'nonshowdown_hands': nsd_count,
                    'showdown_net': round(sd_net, 2),
                    'nonshowdown_net': round(nsd_net, 2),
                    'total_net': round(sd_net + nsd_net, 2),
                })
        return result

    @staticmethod
    def _hand_went_to_showdown(actions: list[dict], hand: dict = None) -> bool:
        """Determine if a hand went to showdown.

        Returns True if:
        - opponent_cards is visible in hand data (parser detected showdown), OR
        - There were postflop actions AND 2+ players remained AND hero was among them.
        """
        if hand and hand.get('opponent_cards'):
            return True

        if not actions:
            return False

        hero_name = None
        for a in actions:
            if a.get('is_hero'):
                hero_name = a['player']
                break
        if not hero_name:
            return False

        all_players = set()
        folded_players = set()
        has_postflop = False
        for a in actions:
            all_players.add(a['player'])
            if a['street'] in ('flop', 'turn', 'river'):
                has_postflop = True
            if a['action_type'] == 'fold':
                folded_players.add(a['player'])

        if not has_postflop:
            return False

        remaining = all_players - folded_players
        return len(remaining) >= 2 and hero_name in remaining


# ── Module-level helpers for Red Line / Blue Line ────────────────────────────

def _downsample_redline(data: list, max_points: int) -> list:
    """Downsample chart data keeping first, last, and evenly-spaced points."""
    n = len(data)
    if n <= max_points:
        return data
    indices = [0]
    step = (n - 1) / (max_points - 1)
    for i in range(1, max_points - 1):
        indices.append(round(i * step))
    indices.append(n - 1)
    return [data[i] for i in indices]


def _generate_redline_diagnostics(showdown_net: float, nonshowdown_net: float,
                                   showdown_hands: int, nonshowdown_hands: int,
                                   total_hands: int) -> list[dict]:
    """Generate diagnostic messages for red/blue line analysis."""
    diagnostics = []
    if total_hands < 20:
        return diagnostics

    # Red line (non-showdown) diagnosis
    if nonshowdown_net < 0 and nonshowdown_hands > 20:
        diagnostics.append({
            'type': 'danger',
            'title': 'Red line caindo',
            'message': (
                'Não está blefando/defendendo o suficiente. '
                'Muitas mãos são perdidas sem ir ao showdown.'
            ),
        })
    elif nonshowdown_net >= 0 and nonshowdown_hands > 20:
        diagnostics.append({
            'type': 'good',
            'title': 'Red line saudável',
            'message': 'Bom equilíbrio entre blefes e defesas sem ir ao showdown.',
        })

    # Blue line (showdown) diagnosis
    if showdown_net < 0 and showdown_hands > 10:
        diagnostics.append({
            'type': 'danger',
            'title': 'Blue line caindo',
            'message': (
                'Indo ao showdown com mãos fracas. '
                'Considere ser mais seletivo ao ir ao showdown.'
            ),
        })
    elif showdown_net >= 0 and showdown_hands > 10:
        diagnostics.append({
            'type': 'good',
            'title': 'Blue line saudável',
            'message': 'Boa seletividade ao ir ao showdown.',
        })

    # High showdown rate warning
    if total_hands > 0:
        sd_pct = showdown_hands / total_hands * 100
        if sd_pct > 35:
            diagnostics.append({
                'type': 'warning',
                'title': 'Alta taxa de showdown',
                'message': (
                    f'Indo ao showdown em {sd_pct:.1f}% das mãos. '
                    'Considere foldar mais mãos fracas antes do showdown.'
                ),
            })

    return diagnostics


# ── Module-level helpers for Bet Sizing & Pot-Type Segmentation ──────────────

_PREFLOP_BUCKETS = [
    ('<2x', 0, 2),
    ('2-2.5x', 2, 2.5),
    ('2.5-3x', 2.5, 3),
    ('3-4x', 3, 4),
    ('>4x', 4, float('inf')),
]

_POSTFLOP_BUCKETS = [
    ('<25%', 0, 25),
    ('25-50%', 25, 50),
    ('50-75%', 50, 75),
    ('75-100%', 75, 100),
    ('>100%', 100, float('inf')),
]


def _classify_pot_type(preflop_actions: list) -> str:
    """Classify pot type based on number of preflop raises (all players)."""
    n_raises = sum(
        1 for a in preflop_actions
        if a['action_type'] in ('raise', 'bet', 'all-in')
    )
    if n_raises == 0:
        return 'limped'
    if n_raises == 1:
        return 'srp'
    if n_raises == 2:
        return '3bet'
    return '4bet_plus'


def _count_active_players(preflop_actions: list) -> int:
    """Count players who did not fold preflop."""
    players: set = set()
    folded: set = set()
    for a in preflop_actions:
        players.add(a['player'])
        if a['action_type'] == 'fold':
            folded.add(a['player'])
    return len(players - folded)


def _compute_bet_sizing(actions: list, blinds_bb: float) -> dict:
    """Extract hero's first bet sizes per street.

    Preflop: raise size in units of BB.
    Postflop: first hero bet as % of pot accumulated before that action.
    """
    result: dict = {
        'preflop_raise_bb': None,
        'flop_bet_pct': None,
        'turn_bet_pct': None,
        'river_bet_pct': None,
    }
    street_seen: dict = {'flop': False, 'turn': False, 'river': False}
    running_pot = 0.0

    for a in actions:
        amt = a.get('amount') or 0.0
        street = a.get('street', '')
        atype = a.get('action_type', '')

        # Preflop: first hero raise
        if (street == 'preflop'
                and a.get('is_hero')
                and atype in ('raise', 'bet')
                and result['preflop_raise_bb'] is None
                and blinds_bb > 0
                and amt > 0):
            result['preflop_raise_bb'] = round(amt / blinds_bb, 2)

        # Postflop: first hero bet per street
        if (street in ('flop', 'turn', 'river')
                and a.get('is_hero')
                and atype == 'bet'
                and not street_seen[street]
                and running_pot > 0
                and amt > 0):
            result[f'{street}_bet_pct'] = round(amt / running_pot * 100, 1)
            street_seen[street] = True

        running_pot += amt

    return result


def _empty_pt_acc() -> dict:
    """Return a zeroed pot-type/segment accumulator."""
    return {
        'hands': 0,
        'hu_hands': 0,
        'multiway_hands': 0,
        'net': 0.0,
        'net_bb': 0.0,
        'vpip': 0,
        'pfr': 0,
        'saw_flop': 0,
        'cbet_opps': 0,
        'cbet': 0,
        'wtsd': 0,
        'wsd': 0,
        'agg_br': 0,
        'agg_calls': 0,
    }


def _accumulate_pt(acc: dict, net: float, blinds_bb: float,
                   is_hu: bool, pf_pre: dict, pf_post: dict) -> None:
    """Update a pot-type accumulator in-place."""
    acc['hands'] += 1
    acc['net'] += net
    if blinds_bb > 0:
        acc['net_bb'] += net / blinds_bb
    if is_hu:
        acc['hu_hands'] += 1
    else:
        acc['multiway_hands'] += 1
    if pf_pre.get('vpip'):
        acc['vpip'] += 1
    if pf_pre.get('pfr'):
        acc['pfr'] += 1
    if pf_post.get('saw_flop'):
        acc['saw_flop'] += 1
    if pf_post.get('cbet_opp'):
        acc['cbet_opps'] += 1
        if pf_post.get('cbet'):
            acc['cbet'] += 1
    if pf_post.get('went_to_showdown'):
        acc['wtsd'] += 1
        if pf_post.get('won_at_showdown'):
            acc['wsd'] += 1
    for street in ('flop', 'turn', 'river'):
        ha = pf_post.get('hero_aggression', {}).get(street)
        if ha:
            acc['agg_br'] += ha['bets'] + ha['raises']
            acc['agg_calls'] += ha['calls']


def _format_pt_stats(acc: dict) -> dict:
    """Format a pot-type accumulator into output stats dict."""
    h = acc['hands']
    if h == 0:
        return {
            'hands': 0, 'hu_hands': 0, 'multiway_hands': 0,
            'vpip': 0.0, 'pfr': 0.0, 'af': 0.0,
            'cbet': 0.0, 'wtsd': 0.0, 'wsd': 0.0,
            'net': 0.0, 'win_rate_bb100': 0.0, 'health': 'good',
        }
    af = (acc['agg_br'] / acc['agg_calls'] if acc['agg_calls'] > 0
          else float(acc['agg_br']))
    wr = acc['net_bb'] / h * 100
    return {
        'hands': h,
        'hu_hands': acc['hu_hands'],
        'multiway_hands': acc['multiway_hands'],
        'vpip': round(acc['vpip'] / h * 100, 1),
        'pfr': round(acc['pfr'] / h * 100, 1),
        'af': round(af, 2),
        'cbet': round(acc['cbet'] / acc['cbet_opps'] * 100, 1) if acc['cbet_opps'] else 0.0,
        'wtsd': round(acc['wtsd'] / acc['saw_flop'] * 100, 1) if acc['saw_flop'] else 0.0,
        'wsd': round(acc['wsd'] / acc['wtsd'] * 100, 1) if acc['wtsd'] else 0.0,
        'net': round(acc['net'], 2),
        'win_rate_bb100': round(wr, 1),
        'health': _classify_winrate_health(wr),
    }


def _classify_winrate_health(win_rate_bb100: float) -> str:
    """Classify win rate (bb/100) as good, warning, or danger."""
    if win_rate_bb100 >= 0:
        return 'good'
    if win_rate_bb100 >= -5:
        return 'warning'
    return 'danger'


def _median(lst: list) -> float:
    """Compute median of a non-empty list."""
    s = sorted(lst)
    n = len(s)
    mid = n // 2
    return (s[mid - 1] + s[mid]) / 2 if n % 2 == 0 else s[mid]


def _size_distribution(sizes: list, buckets: list) -> list:
    """Bucket sizes into ranges and return distribution."""
    counts = [0] * len(buckets)
    for s in sizes:
        placed = False
        for i, (_, lo, hi) in enumerate(buckets):
            if lo <= s < hi:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    total = sum(counts)
    return [
        {'label': buckets[i][0], 'count': counts[i],
         'pct': round(counts[i] / total * 100, 1) if total > 0 else 0.0}
        for i in range(len(buckets))
    ]


def _format_sizing_data(sizes: list, buckets: list) -> dict:
    """Format raw sizing samples into stats + distribution dict."""
    if not sizes:
        return {'samples': 0, 'avg': 0.0, 'median': 0.0, 'distribution': []}
    avg = sum(sizes) / len(sizes)
    return {
        'samples': len(sizes),
        'avg': round(avg, 2),
        'median': round(_median(sizes), 2),
        'distribution': _size_distribution(sizes, buckets),
    }


def _generate_bet_sizing_diagnostics(pot_types: dict, preflop_sizes: list,
                                      total_hands: int) -> list[dict]:
    """Generate diagnostic messages for bet sizing & pot-type analysis."""
    diagnostics = []
    if total_hands < 20:
        return diagnostics

    # Sizing uniformity check
    if len(preflop_sizes) >= 10:
        avg = sum(preflop_sizes) / len(preflop_sizes)
        variance = sum((x - avg) ** 2 for x in preflop_sizes) / len(preflop_sizes)
        std = variance ** 0.5
        cv = std / avg if avg > 0 else 0
        if cv < 0.15:
            diagnostics.append({
                'type': 'warning',
                'title': 'Sizing preflop uniforme',
                'message': (
                    f'Raise size médio de {avg:.1f}x BB com baixa variação. '
                    'Variar o sizing por posição/board dificulta a leitura pelos adversários.'
                ),
            })

    # Win rate per pot type
    labels = {
        'limped': 'Limped', 'srp': 'SRP',
        '3bet': '3-bet', '4bet_plus': '4-bet+',
    }
    for key, label in labels.items():
        pt = pot_types.get(key, {})
        h = pt.get('hands', 0)
        if h < 20:
            continue
        wr = pt.get('win_rate_bb100', 0)
        if wr < -15:
            diagnostics.append({
                'type': 'danger',
                'title': f'Perda significativa em potes {label}',
                'message': (
                    f'Win rate de {wr:.1f} bb/100 em {h} potes {label}. '
                    'Spot crítico para revisão de estratégia.'
                ),
            })
        elif wr < -5:
            diagnostics.append({
                'type': 'warning',
                'title': f'Win rate negativo em potes {label}',
                'message': f'Win rate de {wr:.1f} bb/100 em {h} potes {label}. Monitorar evolução.',
            })
        elif wr > 20:
            diagnostics.append({
                'type': 'good',
                'title': f'Forte em potes {label}',
                'message': f'Win rate de +{wr:.1f} bb/100 em {h} potes {label}. Ponto forte do jogo.',
            })

    return diagnostics


# ── Module-level helpers for Hand Matrix ─────────────────────────────────

# Card rank order for 13x13 matrix (rows/columns)
RANKS = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']


def _categorize_hand(hero_cards: str) -> str | None:
    """Convert hero cards like 'Ah Kd' to standard category notation.

    Returns e.g. 'AKs' (suited), 'AKo' (offsuit), 'AA' (pair), or None if invalid.
    """
    parts = hero_cards.strip().split()
    if len(parts) != 2:
        return None

    card1, card2 = parts
    if len(card1) < 2 or len(card2) < 2:
        return None

    rank1, suit1 = card1[0], card1[1]
    rank2, suit2 = card2[0], card2[1]

    if rank1 not in RANKS or rank2 not in RANKS:
        return None

    # Order by rank (higher first)
    idx1 = RANKS.index(rank1)
    idx2 = RANKS.index(rank2)
    if idx1 > idx2:
        rank1, rank2 = rank2, rank1
        suit1, suit2 = suit2, suit1

    if rank1 == rank2:
        return f'{rank1}{rank2}'
    elif suit1 == suit2:
        return f'{rank1}{rank2}s'
    else:
        return f'{rank1}{rank2}o'


def _classify_preflop_action(actions: list[dict]) -> str | None:
    """Classify the hero's preflop action type.

    Returns 'open_raise', 'call', 'three_bet', or None (hero folded/posted only).
    """
    hero_first_acted = False
    raises_before_hero = 0

    for a in actions:
        atype = a.get('action_type', '')
        if atype in ('post_sb', 'post_bb', 'post_ante'):
            continue

        if a.get('is_hero'):
            if not hero_first_acted:
                hero_first_acted = True
                if atype in ('raise', 'bet'):
                    if raises_before_hero == 0:
                        return 'open_raise'
                    else:
                        return 'three_bet'
                elif atype == 'call':
                    return 'call'
                elif atype == 'all-in':
                    if raises_before_hero == 0:
                        return 'open_raise'
                    else:
                        return 'three_bet'
                else:
                    return None  # fold or check
        else:
            if atype in ('raise', 'bet', 'all-in'):
                raises_before_hero += 1

    return None
