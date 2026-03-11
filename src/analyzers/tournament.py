"""Tournament analysis module.

Reads from database and computes statistics for reports.
Includes per-tournament preflop/postflop stats, EV analysis,
chip sparklines, daily session-level aggregation, and session comparisons.
"""

from collections import defaultdict
from datetime import datetime

from src.analyzers.cash import (
    CashAnalyzer,
    _downsample_redline,
    _generate_redline_diagnostics,
    _categorize_hand,
    _classify_preflop_action,
    _classify_pot_type,
    _count_active_players,
    _compute_bet_sizing,
    _empty_pt_acc,
    _accumulate_pt,
    _format_pt_stats,
    _classify_winrate_health,
    _format_sizing_data,
    _generate_bet_sizing_diagnostics,
    _PREFLOP_BUCKETS,
    _POSTFLOP_BUCKETS,
)
from src.analyzers.ev import EVAnalyzer, parse_cards, calculate_equity
from src.db.repository import Repository


class TournamentAnalyzer:
    """Analyze tournament data from the database."""

    game_type = 'tournament'

    # Reuse health ranges from CashAnalyzer
    HEALTHY_RANGES = CashAnalyzer.HEALTHY_RANGES
    WARNING_RANGES = CashAnalyzer.WARNING_RANGES
    POSTFLOP_HEALTHY_RANGES = CashAnalyzer.POSTFLOP_HEALTHY_RANGES
    POSTFLOP_WARNING_RANGES = CashAnalyzer.POSTFLOP_WARNING_RANGES

    # Reuse positional/stack depth ranges from CashAnalyzer
    POSITION_VPIP_HEALTHY = CashAnalyzer.POSITION_VPIP_HEALTHY
    POSITION_VPIP_WARNING = CashAnalyzer.POSITION_VPIP_WARNING
    POSITION_PFR_HEALTHY = CashAnalyzer.POSITION_PFR_HEALTHY
    POSITION_PFR_WARNING = CashAnalyzer.POSITION_PFR_WARNING
    STACK_VPIP_HEALTHY = CashAnalyzer.STACK_VPIP_HEALTHY
    STACK_VPIP_WARNING = CashAnalyzer.STACK_VPIP_WARNING
    STACK_PFR_HEALTHY = CashAnalyzer.STACK_PFR_HEALTHY
    STACK_PFR_WARNING = CashAnalyzer.STACK_PFR_WARNING
    STACK_3BET_HEALTHY = CashAnalyzer.STACK_3BET_HEALTHY
    STACK_3BET_WARNING = CashAnalyzer.STACK_3BET_WARNING

    def __init__(self, repo: Repository, year: str = '2026', skip_ev: bool = False,
                 exclude_satellites: bool = True):
        self.repo = repo
        self.year = year
        self.skip_ev = skip_ev
        self.exclude_satellites = exclude_satellites
        self._healthy_ranges = type(self).HEALTHY_RANGES
        self._warning_ranges = type(self).WARNING_RANGES
        self._postflop_healthy_ranges = type(self).POSTFLOP_HEALTHY_RANGES
        self._postflop_warning_ranges = type(self).POSTFLOP_WARNING_RANGES
        self._pos_vpip_healthy = type(self).POSITION_VPIP_HEALTHY
        self._pos_vpip_warning = type(self).POSITION_VPIP_WARNING
        self._pos_pfr_healthy = type(self).POSITION_PFR_HEALTHY
        self._pos_pfr_warning = type(self).POSITION_PFR_WARNING
        self._stack_vpip_healthy = type(self).STACK_VPIP_HEALTHY
        self._stack_vpip_warning = type(self).STACK_VPIP_WARNING
        self._stack_pfr_healthy = type(self).STACK_PFR_HEALTHY
        self._stack_pfr_warning = type(self).STACK_PFR_WARNING
        self._stack_3bet_healthy = type(self).STACK_3BET_HEALTHY
        self._stack_3bet_warning = type(self).STACK_3BET_WARNING

    # ── Preflop Stats ──────────────────────────────────────────────

    def get_preflop_stats(self) -> dict:
        """Calculate preflop statistics for tournament hands.

        Returns dict with overall stats, by_position breakdown, and by_day breakdown.
        Each stat includes value, counts, and health classification.
        Reuses CashAnalyzer._analyze_preflop_hand() for per-hand analysis.
        """
        sequences = self.repo.get_tournament_preflop_actions(self.year, exclude_satellites=self.exclude_satellites)

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
        # US-032
        open_shove_count = 0
        rbw_opps = 0
        rbw_count = 0

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

            result = CashAnalyzer._analyze_preflop_hand(voluntary_actions)

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

            # US-032
            if result['open_shove']:
                open_shove_count += 1
            if result['rbw_opp']:
                rbw_opps += 1
                if result['rbw']:
                    rbw_count += 1

        return self._format_preflop_stats(
            total_hands, vpip_count, pfr_count,
            three_bet_opps, three_bet_count,
            fold_3bet_opps, fold_3bet_count,
            ats_opps, ats_count,
            dict(pos_stats), dict(day_stats),
            open_shove_count=open_shove_count,
            rbw_opps=rbw_opps, rbw_count=rbw_count,
        )

    def _format_preflop_stats(self, total_hands, vpip_count, pfr_count,
                              three_bet_opps, three_bet_count,
                              fold_3bet_opps, fold_3bet_count,
                              ats_opps, ats_count,
                              pos_stats, day_stats,
                              open_shove_count=0,
                              rbw_opps=0, rbw_count=0) -> dict:
        """Format raw preflop counts into percentages with health badges."""

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
            # US-032
            'open_shove': pct(open_shove_count, total_hands),
            'open_shove_hands': open_shove_count,
            'rbw': pct(rbw_count, rbw_opps),
            'rbw_hands': rbw_count,
            'rbw_opps': rbw_opps,
        }

        # Add health badges
        for stat in ('vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats',
                     'open_shove', 'rbw'):
            overall[f'{stat}_health'] = CashAnalyzer._classify_health(stat, overall[stat])

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

    # ── Postflop Stats ──────────────────────────────────────────────

    def get_postflop_stats(self) -> dict:
        """Calculate postflop statistics for tournament hands.

        Returns dict with overall stats, by_street breakdown, and by_week trends.
        Reuses CashAnalyzer._analyze_postflop_hand() for per-hand analysis.
        """
        sequences = self.repo.get_tournament_all_actions(self.year, exclude_satellites=self.exclude_satellites)

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
        won_saw_flop_count = 0
        cbet_opps = 0
        cbet_count = 0
        fold_cbet_opps = 0
        fold_cbet_count = 0
        # US-032 counters
        bet_river_opps = 0
        bet_river_count = 0
        call_river_opps = 0
        call_river_count = 0
        probe_opps = 0
        probe_count = 0
        fold_to_probe_opps = 0
        fold_to_probe_count = 0
        bet_vs_missed_cbet_opps = 0
        bet_vs_missed_cbet_count = 0
        xf_oop_opps = 0
        xf_oop_count = 0

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

            result = CashAnalyzer._analyze_postflop_hand(actions, meta['hero_net'])

            if result['saw_flop']:
                saw_flop_count += 1
                week_stats[week]['saw_flop'] += 1
                if result.get('won_saw_flop'):
                    won_saw_flop_count += 1

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

            # US-032: accumulate new stats
            if result.get('bet_river_opp'):
                bet_river_opps += 1
                if result.get('bet_river'):
                    bet_river_count += 1
            if result.get('call_river_opp'):
                call_river_opps += 1
                if result.get('call_river'):
                    call_river_count += 1
            if result.get('probe_opp'):
                probe_opps += 1
                if result.get('probe'):
                    probe_count += 1
            if result.get('fold_to_probe_opp'):
                fold_to_probe_opps += 1
                if result.get('fold_to_probe'):
                    fold_to_probe_count += 1
            if result.get('bet_vs_missed_cbet_opp'):
                bet_vs_missed_cbet_opps += 1
                if result.get('bet_vs_missed_cbet'):
                    bet_vs_missed_cbet_count += 1
            if result.get('xf_oop_opp'):
                xf_oop_opps += 1
                if result.get('xf_oop'):
                    xf_oop_count += 1

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
            won_saw_flop_count=won_saw_flop_count,
            bet_river_opps=bet_river_opps, bet_river_count=bet_river_count,
            call_river_opps=call_river_opps, call_river_count=call_river_count,
            probe_opps=probe_opps, probe_count=probe_count,
            fold_to_probe_opps=fold_to_probe_opps, fold_to_probe_count=fold_to_probe_count,
            bet_vs_missed_cbet_opps=bet_vs_missed_cbet_opps,
            bet_vs_missed_cbet_count=bet_vs_missed_cbet_count,
            xf_oop_opps=xf_oop_opps, xf_oop_count=xf_oop_count,
        )

    def _format_postflop_stats(self, total_hands, saw_flop_count, wtsd_count, wsd_count,
                               cbet_opps, cbet_count, fold_cbet_opps, fold_cbet_count,
                               agg, cr, week_stats,
                               won_saw_flop_count=0,
                               bet_river_opps=0, bet_river_count=0,
                               call_river_opps=0, call_river_count=0,
                               probe_opps=0, probe_count=0,
                               fold_to_probe_opps=0, fold_to_probe_count=0,
                               bet_vs_missed_cbet_opps=0, bet_vs_missed_cbet_count=0,
                               xf_oop_opps=0, xf_oop_count=0) -> dict:
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
            # US-032: new stats
            'won_saw_flop': pct(won_saw_flop_count, saw_flop_count),
            'won_saw_flop_hands': won_saw_flop_count,
            'won_saw_flop_opps': saw_flop_count,
            'bet_river': pct(bet_river_count, bet_river_opps),
            'bet_river_hands': bet_river_count,
            'bet_river_opps': bet_river_opps,
            'call_river': pct(call_river_count, call_river_opps),
            'call_river_hands': call_river_count,
            'call_river_opps': call_river_opps,
            'probe': pct(probe_count, probe_opps),
            'probe_hands': probe_count,
            'probe_opps': probe_opps,
            'fold_to_probe': pct(fold_to_probe_count, fold_to_probe_opps),
            'fold_to_probe_hands': fold_to_probe_count,
            'fold_to_probe_opps': fold_to_probe_opps,
            'bet_vs_missed_cbet': pct(bet_vs_missed_cbet_count, bet_vs_missed_cbet_opps),
            'bet_vs_missed_cbet_hands': bet_vs_missed_cbet_count,
            'bet_vs_missed_cbet_opps': bet_vs_missed_cbet_opps,
            'xf_oop': pct(xf_oop_count, xf_oop_opps),
            'xf_oop_hands': xf_oop_count,
            'xf_oop_opps': xf_oop_opps,
        }

        # Health badges
        for stat in ('af', 'wtsd', 'wsd', 'cbet', 'fold_to_cbet', 'check_raise',
                     'won_saw_flop', 'bet_river', 'call_river', 'probe',
                     'fold_to_probe', 'bet_vs_missed_cbet', 'xf_oop'):
            overall[f'{stat}_health'] = CashAnalyzer._classify_postflop_health(stat, overall[stat])

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

    # ── Daily Reports ──────────────────────────────────────────────

    def get_daily_reports(self) -> list[dict]:
        """Build daily report data with session-level focus.

        Each day is treated as a session, with aggregated stats as the primary view
        and individual tournament details in accordion sections.
        """
        tournaments = self.repo.get_tournaments(self.year, exclude_satellites=True)

        # Group by day
        by_day = defaultdict(list)
        for t in tournaments:
            day = (t['date'] or '')[:10]
            if day:
                by_day[day].append(t)

        reports = []
        for day in sorted(by_day.keys(), reverse=True):
            day_tournaments = by_day[day]
            total_buy_in = sum(
                (t.get('total_buy_in', 0) or 0) * (t.get('entries', 1) or 1)
                for t in day_tournaments
            )
            total_won = sum(t.get('prize', 0) or 0 for t in day_tournaments)
            net = total_won - total_buy_in
            total_rake = sum(
                (t.get('rake', 0) or 0) * (t.get('entries', 1) or 1)
                for t in day_tournaments
            )
            rebuys = sum((t.get('entries', 1) or 1) - 1 for t in day_tournaments)
            total_entries = sum(t.get('entries', 1) or 1 for t in day_tournaments)
            itm_count = sum(
                1 for t in day_tournaments
                if (t.get('prize', 0) or 0) > 0 and
                   (t.get('prize', 0) or 0) >= (t.get('total_buy_in', 0) or 0) * (t.get('entries', 1) or 1)
            )

            # Get per-tournament stats
            tournament_details = []
            for t in day_tournaments:
                tid = t.get('tournament_id')
                detail = self._get_tournament_detail(t, tid)
                tournament_details.append(detail)

            # Aggregate day stats (weighted by hands count) with health badges
            day_stats = self._aggregate_tournament_stats_with_health(tournament_details)

            # Build tournament comparison
            comparison = self._build_tournament_comparison(tournament_details)

            # Session sparkline (aggregated chips across all tournaments of the day)
            session_sparkline = self._get_session_sparkline(tournament_details)

            # Session-level notable hands (biggest win/loss across all day's tournaments)
            session_notable = self._get_daily_notable_hands(tournament_details)

            # Session ROI
            session_roi = ((net / total_buy_in) * 100) if total_buy_in > 0 else 0.0

            # Day-level EV analysis
            day_ev = self._get_daily_ev_analysis(day)

            # Total hands for the session
            total_hands = sum(td.get('hands_count', 0) for td in tournament_details)

            reports.append({
                'date': day,
                'tournament_count': len(day_tournaments),
                'total_buy_in': total_buy_in,
                'total_won': total_won,
                'net': net,
                'total_rake': total_rake,
                'rebuys': rebuys,
                'total_entries': total_entries,
                'itm_count': itm_count,
                'itm_rate': (itm_count / len(day_tournaments) * 100) if day_tournaments else 0,
                'tournaments': tournament_details,
                'day_stats': day_stats,
                'comparison': comparison,
                'session_sparkline': session_sparkline,
                'session_notable': session_notable,
                'session_roi': round(session_roi, 1),
                'day_ev': day_ev,
                'total_hands': total_hands,
            })

        return reports

    def get_session_comparison(self, daily_reports: list[dict]) -> dict:
        """Compare sessions across different days to find best/worst of month.

        Returns dict with best/worst session indices per metric.
        """
        if len(daily_reports) < 2:
            return {}

        comparison = {}

        # Net comparison
        net_values = [(i, r.get('net', 0)) for i, r in enumerate(daily_reports)]
        comparison['net'] = {
            'best': max(net_values, key=lambda x: x[1])[0],
            'worst': min(net_values, key=lambda x: x[1])[0],
            'best_value': max(net_values, key=lambda x: x[1])[1],
            'worst_value': min(net_values, key=lambda x: x[1])[1],
        }

        # ROI comparison
        roi_values = [(i, r.get('session_roi', 0)) for i, r in enumerate(daily_reports)]
        comparison['roi'] = {
            'best': max(roi_values, key=lambda x: x[1])[0],
            'worst': min(roi_values, key=lambda x: x[1])[0],
            'best_value': max(roi_values, key=lambda x: x[1])[1],
            'worst_value': min(roi_values, key=lambda x: x[1])[1],
        }

        # ITM comparison
        itm_values = [(i, r.get('itm_rate', 0)) for i, r in enumerate(daily_reports)]
        comparison['itm'] = {
            'best': max(itm_values, key=lambda x: x[1])[0],
            'worst': min(itm_values, key=lambda x: x[1])[0],
            'best_value': max(itm_values, key=lambda x: x[1])[1],
            'worst_value': min(itm_values, key=lambda x: x[1])[1],
        }

        # Hands count comparison
        hands_values = [(i, r.get('total_hands', 0)) for i, r in enumerate(daily_reports)]
        comparison['hands'] = {
            'best': max(hands_values, key=lambda x: x[1])[0],
            'worst': min(hands_values, key=lambda x: x[1])[0],
            'best_value': max(hands_values, key=lambda x: x[1])[1],
            'worst_value': min(hands_values, key=lambda x: x[1])[1],
        }

        # Stats comparison (VPIP, PFR, AF from day_stats)
        for stat_key in ('vpip', 'pfr', 'af'):
            stat_values = [
                (i, r.get('day_stats', {}).get(stat_key, 0))
                for i, r in enumerate(daily_reports)
                if r.get('day_stats', {}).get('total_hands', 0) > 0
            ]
            if len(stat_values) >= 2:
                comparison[stat_key] = {
                    'best': max(stat_values, key=lambda x: x[1])[0],
                    'worst': min(stat_values, key=lambda x: x[1])[0],
                    'best_value': max(stat_values, key=lambda x: x[1])[1],
                    'worst_value': min(stat_values, key=lambda x: x[1])[1],
                }

        return comparison

    def _get_tournament_detail(self, tournament: dict, tournament_id: str) -> dict:
        """Build full detail for a single tournament including stats and sparkline."""
        hands = self.repo.get_tournament_hands(self.year, tournament_id)
        stats = self.get_tournament_game_stats(tournament_id)
        sparkline = self._get_chip_sparkline(hands)

        # Notable hands
        biggest_win = None
        biggest_loss = None
        for h in hands:
            net = h.get('net') or 0
            if net > 0 and (biggest_win is None or net > biggest_win['net']):
                biggest_win = h
            if net < 0 and (biggest_loss is None or net < biggest_loss['net']):
                biggest_loss = h

        prize = tournament.get('prize', 0) or 0
        t_buy_in = (tournament.get('total_buy_in', 0) or 0)
        entries = tournament.get('entries', 1) or 1
        total_cost = t_buy_in * entries
        net_profit = prize - total_cost

        return {
            'tournament_id': tournament_id,
            'name': tournament.get('name', 'Unknown'),
            'date': tournament.get('date', ''),
            'buy_in': t_buy_in,
            'entries': entries,
            'total_cost': total_cost,
            'prize': prize,
            'net': net_profit,
            'position': tournament.get('position'),
            'total_players': tournament.get('total_players', 0),
            'is_bounty': tournament.get('is_bounty', False),
            'rake': tournament.get('rake', 0) or 0,
            'bounty': tournament.get('bounty', 0) or 0,
            'hands_count': len(hands),
            'stats': stats,
            'sparkline': sparkline,
            'biggest_win': biggest_win,
            'biggest_loss': biggest_loss,
        }

    @staticmethod
    def _get_chip_sparkline(hands: list[dict]) -> list[dict]:
        """Generate sparkline data for chip evolution across a tournament."""
        if not hands:
            return []
        cumulative = 0
        points = []
        for i, h in enumerate(hands, 1):
            cumulative += (h.get('net') or 0)
            points.append({'hand': i, 'chips': cumulative})
        return points

    @staticmethod
    def _get_session_sparkline(tournament_details: list[dict]) -> list[dict]:
        """Generate aggregated sparkline for all tournaments in a day session.

        Merges chip data from all tournaments into a single cumulative line.
        """
        all_nets = []
        for td in tournament_details:
            sparkline = td.get('sparkline', [])
            for point in sparkline:
                all_nets.append(point.get('chips', 0) - (
                    sparkline[sparkline.index(point) - 1].get('chips', 0)
                    if sparkline.index(point) > 0 else 0
                ))
        if not all_nets:
            return []
        cumulative = 0
        points = []
        for i, net in enumerate(all_nets, 1):
            cumulative += net
            points.append({'hand': i, 'chips': cumulative})
        return points

    @staticmethod
    def _get_daily_notable_hands(tournament_details: list[dict]) -> dict:
        """Find biggest win and biggest loss across all tournaments of a day."""
        biggest_win = None
        biggest_loss = None
        for td in tournament_details:
            bw = td.get('biggest_win')
            bl = td.get('biggest_loss')
            if bw:
                net = bw.get('net', 0) or 0
                if biggest_win is None or net > (biggest_win.get('net', 0) or 0):
                    biggest_win = bw
            if bl:
                net = bl.get('net', 0) or 0
                if biggest_loss is None or net < (biggest_loss.get('net', 0) or 0):
                    biggest_loss = bl
        return {
            'biggest_win': biggest_win,
            'biggest_loss': biggest_loss,
        }

    def _get_daily_ev_analysis(self, day: str) -> dict:
        """Calculate EV analysis for a single day's tournament hands.

        Returns same structure as get_ev_analysis but filtered to one day.
        Includes chart_data for mini EV sparkline and luck badge info.
        """
        if self.skip_ev:
            return {
                'total_hands': 0, 'allin_hands': 0,
                'real_net': 0, 'ev_net': 0, 'luck_factor': 0,
                'bb100_real': 0, 'bb100_ev': 0,
                'chart_data': [],
            }

        all_hands = self.repo.get_tournament_hands(self.year, exclude_satellites=self.exclude_satellites)
        allin_hands = self.repo.get_tournament_allin_hands(self.year, exclude_satellites=self.exclude_satellites)

        # Filter to the specific day
        day_hands = [h for h in all_hands if (h.get('date') or '')[:10] == day]
        day_allin = [h for h in allin_hands if (h.get('date') or '')[:10] == day]

        if not day_hands:
            return {
                'total_hands': 0, 'allin_hands': 0,
                'real_net': 0, 'ev_net': 0, 'luck_factor': 0,
                'bb100_real': 0, 'bb100_ev': 0,
                'chart_data': [],
            }

        # Calculate equity for each all-in hand
        allin_ev = {}
        for h in day_allin:
            ev_data = self._compute_hand_ev(h)
            if ev_data is not None:
                allin_ev[h['hand_id']] = ev_data

        cumulative_real = 0.0
        cumulative_ev = 0.0
        total_bb_real = 0.0
        total_bb_ev = 0.0
        chart_data = []

        for i, h in enumerate(day_hands):
            net = h.get('net', 0) or 0
            bb = h.get('blinds_bb') or 100
            if bb <= 0:
                bb = 100

            cumulative_real += net
            if h['hand_id'] in allin_ev:
                ev_net_hand = allin_ev[h['hand_id']]['ev_net']
                cumulative_ev += ev_net_hand
            else:
                ev_net_hand = net
                cumulative_ev += net

            total_bb_real += net / bb
            total_bb_ev += ev_net_hand / bb

            chart_data.append({
                'hand': i + 1,
                'real': round(cumulative_real, 2),
                'ev': round(cumulative_ev, 2),
            })

        total_hands = len(day_hands)
        total_allin = len(allin_ev)
        luck_factor = cumulative_real - cumulative_ev
        bb100_real = (total_bb_real / total_hands * 100) if total_hands > 0 else 0
        bb100_ev = (total_bb_ev / total_hands * 100) if total_hands > 0 else 0

        # Downsample chart for mini SVG (max 100 points)
        chart_sampled = EVAnalyzer._downsample(chart_data, 100)

        return {
            'total_hands': total_hands,
            'allin_hands': total_allin,
            'real_net': round(cumulative_real, 2),
            'ev_net': round(cumulative_ev, 2),
            'luck_factor': round(luck_factor, 2),
            'bb100_real': round(bb100_real, 2),
            'bb100_ev': round(bb100_ev, 2),
            'chart_data': chart_sampled,
        }

    @staticmethod
    def _aggregate_tournament_stats_with_health(tournament_details: list[dict]) -> dict:
        """Compute weighted average stats across tournaments with health badges.

        Like _aggregate_tournament_stats but includes health classification.
        """
        stats_keys = ['vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats',
                       'af', 'wtsd', 'wsd', 'cbet', 'fold_to_cbet', 'check_raise']
        total_hands = 0
        weighted = {k: 0.0 for k in stats_keys}

        for td in tournament_details:
            st = td.get('stats', {})
            h = st.get('total_hands', 0)
            if h == 0:
                continue
            total_hands += h
            for k in stats_keys:
                weighted[k] += st.get(k, 0) * h

        if total_hands == 0:
            return {}

        result = {'total_hands': total_hands}
        preflop_keys = {'vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats'}
        for k in stats_keys:
            val = weighted[k] / total_hands
            result[k] = val
            if k in preflop_keys:
                result[f'{k}_health'] = CashAnalyzer._classify_health(k, val)
            else:
                result[f'{k}_health'] = CashAnalyzer._classify_postflop_health(k, val)

        return result

    def get_tournament_game_stats(self, tournament_id: str = None) -> dict:
        """Calculate preflop + postflop stats for a tournament (or all tournaments).

        Returns a dict with VPIP%, PFR%, 3-Bet%, Fold-to-3-Bet%, ATS%,
        AF, WTSD%, W$SD%, CBet%, Fold-to-CBet%, Check-Raise%,
        each with a health classification badge.
        """
        if tournament_id:
            preflop_seqs = self.repo.get_tournament_preflop_actions(
                self.year, tournament_id)
            all_seqs = self.repo.get_tournament_all_actions(
                self.year, tournament_id)
        else:
            preflop_seqs = self.repo.get_tournament_preflop_actions(self.year, exclude_satellites=self.exclude_satellites)
            all_seqs = self.repo.get_tournament_all_actions(self.year, exclude_satellites=self.exclude_satellites)

        if not preflop_seqs and not all_seqs:
            return {}

        # Group preflop by hand_id
        pf_hands = defaultdict(list)
        for action in preflop_seqs:
            pf_hands[action['hand_id']].append(action)

        # Group all actions by hand_id
        all_hands = defaultdict(list)
        hand_meta = {}
        for action in all_seqs:
            hid = action['hand_id']
            all_hands[hid].append(action)
            if hid not in hand_meta:
                hand_meta[hid] = {
                    'hero_position': action.get('hero_position'),
                    'hero_net': action.get('hero_net', 0) or 0,
                    'day': action.get('day'),
                }

        # Preflop stats counters
        total_hands = 0
        vpip_count = 0
        pfr_count = 0
        three_bet_opps = 0
        three_bet_count = 0
        fold_3bet_opps = 0
        fold_3bet_count = 0
        ats_opps = 0
        ats_count = 0

        for hand_id, actions in pf_hands.items():
            if not any(a['is_hero'] for a in actions):
                continue
            total_hands += 1
            voluntary = [
                a for a in actions
                if a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')
            ]
            result = CashAnalyzer._analyze_preflop_hand(voluntary)

            if result['vpip']:
                vpip_count += 1
            if result['pfr']:
                pfr_count += 1
            if result['three_bet_opp']:
                three_bet_opps += 1
                if result['three_bet']:
                    three_bet_count += 1
            if result['fold_3bet_opp']:
                fold_3bet_opps += 1
                if result['fold_3bet']:
                    fold_3bet_count += 1
            if result['ats_opp']:
                ats_opps += 1
                if result['ats']:
                    ats_count += 1

        # Postflop stats counters
        saw_flop_count = 0
        wtsd_count = 0
        wsd_count = 0
        cbet_opps = 0
        cbet_count = 0
        fold_cbet_opps = 0
        fold_cbet_count = 0
        agg_br = 0
        agg_calls = 0
        agg_total = 0
        cr_opps = 0
        cr_did = 0

        for hand_id, actions in all_hands.items():
            if not any(a['is_hero'] for a in actions):
                continue
            meta = hand_meta.get(hand_id, {})
            hero_net = meta.get('hero_net', 0)
            result = CashAnalyzer._analyze_postflop_hand(actions, hero_net)

            if result['saw_flop']:
                saw_flop_count += 1
            if result['went_to_showdown']:
                wtsd_count += 1
            if result['won_at_showdown']:
                wsd_count += 1
            if result['cbet_opp']:
                cbet_opps += 1
                if result['cbet']:
                    cbet_count += 1
            if result['fold_to_cbet_opp']:
                fold_cbet_opps += 1
                if result['fold_to_cbet']:
                    fold_cbet_count += 1
            for street in ('flop', 'turn', 'river'):
                if street in result['hero_aggression']:
                    ha = result['hero_aggression'][street]
                    br = ha['bets'] + ha['raises']
                    c = ha['calls']
                    f = ha['folds']
                    agg_br += br
                    agg_calls += c
                    agg_total += br + c + f
                if street in result['check_raise']:
                    cr_data = result['check_raise'][street]
                    if cr_data['opp']:
                        cr_opps += 1
                        if cr_data['did']:
                            cr_did += 1

        if total_hands == 0:
            return {}

        def pct(num, den):
            return (num / den * 100) if den > 0 else 0.0

        vpip = pct(vpip_count, total_hands)
        pfr = pct(pfr_count, total_hands)
        three_bet = pct(three_bet_count, three_bet_opps)
        fold_to_3bet = pct(fold_3bet_count, fold_3bet_opps)
        ats = pct(ats_count, ats_opps)
        af = agg_br / agg_calls if agg_calls > 0 else 0.0
        afq = pct(agg_br, agg_total)
        wtsd = pct(wtsd_count, saw_flop_count)
        wsd = pct(wsd_count, wtsd_count)
        cbet_val = pct(cbet_count, cbet_opps)
        fold_to_cbet = pct(fold_cbet_count, fold_cbet_opps)
        check_raise = pct(cr_did, cr_opps)

        return {
            'total_hands': total_hands,
            'vpip': vpip,
            'vpip_health': CashAnalyzer._classify_health('vpip', vpip),
            'pfr': pfr,
            'pfr_health': CashAnalyzer._classify_health('pfr', pfr),
            'three_bet': three_bet,
            'three_bet_health': CashAnalyzer._classify_health('three_bet', three_bet),
            'fold_to_3bet': fold_to_3bet,
            'fold_to_3bet_health': CashAnalyzer._classify_health('fold_to_3bet', fold_to_3bet),
            'ats': ats,
            'ats_health': CashAnalyzer._classify_health('ats', ats),
            'af': af,
            'af_health': CashAnalyzer._classify_postflop_health('af', af),
            'afq': afq,
            'wtsd': wtsd,
            'wtsd_health': CashAnalyzer._classify_postflop_health('wtsd', wtsd),
            'wsd': wsd,
            'wsd_health': CashAnalyzer._classify_postflop_health('wsd', wsd),
            'cbet': cbet_val,
            'cbet_health': CashAnalyzer._classify_postflop_health('cbet', cbet_val),
            'fold_to_cbet': fold_to_cbet,
            'fold_to_cbet_health': CashAnalyzer._classify_postflop_health('fold_to_cbet', fold_to_cbet),
            'check_raise': check_raise,
            'check_raise_health': CashAnalyzer._classify_postflop_health('check_raise', check_raise),
        }

    def get_ev_analysis(self) -> dict:
        """Calculate EV analysis for all tournament hands.

        Adapted from EVAnalyzer for variable tournament blinds.
        bb/100 uses per-hand BB value (escalating blinds).
        """
        all_hands = self.repo.get_tournament_hands(self.year, exclude_satellites=self.exclude_satellites)
        allin_hands = self.repo.get_tournament_allin_hands(self.year, exclude_satellites=self.exclude_satellites)

        if self.skip_ev or not all_hands:
            return {
                'overall': {
                    'total_hands': 0, 'allin_hands': 0,
                    'real_net': 0, 'ev_net': 0, 'luck_factor': 0,
                    'bb100_real': 0, 'bb100_ev': 0,
                },
                'chart_data': [],
            }

        # Calculate equity for each all-in hand
        allin_ev = {}
        for h in allin_hands:
            ev_data = self._compute_hand_ev(h)
            if ev_data is not None:
                allin_ev[h['hand_id']] = ev_data

        # Build cumulative data with per-hand BB normalization
        cumulative_real = 0.0
        cumulative_ev = 0.0
        total_bb_real = 0.0
        total_bb_ev = 0.0
        chart_data = []

        for i, h in enumerate(all_hands):
            net = h.get('net', 0) or 0
            bb = h.get('blinds_bb') or 100
            if bb <= 0:
                bb = 100

            cumulative_real += net

            if h['hand_id'] in allin_ev:
                ev_net_hand = allin_ev[h['hand_id']]['ev_net']
                cumulative_ev += ev_net_hand
            else:
                ev_net_hand = net
                cumulative_ev += net

            # Normalize to BB for bb/100
            total_bb_real += net / bb
            total_bb_ev += ev_net_hand / bb

            chart_data.append({
                'hand': i + 1,
                'real': round(cumulative_real, 2),
                'ev': round(cumulative_ev, 2),
            })

        total_hands = len(all_hands)
        total_allin = len(allin_ev)
        luck_factor = cumulative_real - cumulative_ev

        bb100_real = (total_bb_real / total_hands * 100) if total_hands > 0 else 0
        bb100_ev = (total_bb_ev / total_hands * 100) if total_hands > 0 else 0

        # Downsample chart data
        chart_sampled = EVAnalyzer._downsample(chart_data, 500)

        return {
            'overall': {
                'total_hands': total_hands,
                'allin_hands': total_allin,
                'real_net': round(cumulative_real, 2),
                'ev_net': round(cumulative_ev, 2),
                'luck_factor': round(luck_factor, 2),
                'bb100_real': round(bb100_real, 2),
                'bb100_ev': round(bb100_ev, 2),
            },
            'chart_data': chart_sampled,
        }

    @staticmethod
    def _compute_hand_ev(hand: dict):
        """Compute EV for a single all-in tournament hand."""
        hero_str = hand.get('hero_cards')
        opp_str = hand.get('opponent_cards')
        if not hero_str or not opp_str:
            return None

        try:
            hero_cards = parse_cards(hero_str)
            if len(hero_cards) != 2:
                return None

            opp_groups = opp_str.split('|')
            opponents = []
            for group in opp_groups:
                cards = parse_cards(group.strip())
                if len(cards) == 2:
                    opponents.append(cards)

            if not opponents:
                return None

            board = EVAnalyzer._get_board_at_allin(hand)
            equity = calculate_equity(hero_cards, opponents, board)

            pot = hand.get('pot_total', 0) or 0
            invested = hand.get('invested', 0) or 0
            actual_net = hand.get('net', 0) or 0

            ev_net = equity * pot - invested
            ev_diff = actual_net - ev_net

            return {
                'equity': round(equity, 4),
                'ev_net': round(ev_net, 2),
                'ev_diff': round(ev_diff, 2),
            }
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _aggregate_tournament_stats(tournament_details: list[dict]) -> dict:
        """Compute weighted average stats across tournaments (weighted by hands count)."""
        stats_keys = ['vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats',
                       'af', 'wtsd', 'wsd', 'cbet', 'fold_to_cbet', 'check_raise']
        total_hands = 0
        weighted = {k: 0.0 for k in stats_keys}

        for td in tournament_details:
            st = td.get('stats', {})
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
    def _build_tournament_comparison(tournament_details: list[dict]) -> dict:
        """Build comparison data identifying best/worst tournaments per stat."""
        if len(tournament_details) < 2:
            return {}

        stats_keys = ['vpip', 'pfr', 'af', 'wtsd', 'wsd', 'cbet']
        comparison = {}

        for key in stats_keys:
            tournaments_with_stat = [
                (i, td['stats'].get(key, 0))
                for i, td in enumerate(tournament_details)
                if td.get('stats', {}).get('total_hands', 0) > 0
            ]
            if len(tournaments_with_stat) < 2:
                continue
            best_idx = max(tournaments_with_stat, key=lambda x: x[1])[0]
            worst_idx = min(tournaments_with_stat, key=lambda x: x[1])[0]
            comparison[key] = {'best': best_idx, 'worst': worst_idx}

        # Net profit comparison
        net_tournaments = [
            (i, td.get('net', 0))
            for i, td in enumerate(tournament_details)
        ]
        if len(net_tournaments) >= 2:
            comparison['net'] = {
                'best': max(net_tournaments, key=lambda x: x[1])[0],
                'worst': min(net_tournaments, key=lambda x: x[1])[0],
            }

        return comparison

    def get_summary(self) -> dict:
        """Get overall tournament summary."""
        stats = self.repo.get_tournament_stats_summary(self.year)
        tournaments = self.repo.get_tournaments(self.year, exclude_satellites=True)

        total_tournaments = stats.get('total_tournaments', 0) or 0
        total_invested = stats.get('total_invested', 0) or 0
        total_won = stats.get('total_won', 0) or 0
        total_net = stats.get('total_net', 0) or 0
        total_entries = stats.get('total_entries', 0) or 0
        total_rebuys = stats.get('total_rebuys', 0) or 0
        total_rake = stats.get('total_rake', 0) or 0

        # Count unique days
        days = set()
        for t in tournaments:
            day = (t.get('date') or '')[:10]
            if day:
                days.add(day)
        total_days = len(days)

        # ITM
        itm_count = sum(
            1 for t in tournaments
            if (t.get('prize', 0) or 0) > 0 and
               (t.get('prize', 0) or 0) >= (t.get('total_buy_in', 0) or 0) * (t.get('entries', 1) or 1)
        )

        # Total tournament hands
        total_hands = self.repo.get_tournament_hand_count(self.year, exclude_satellites=self.exclude_satellites)

        return {
            'total_tournaments': total_tournaments,
            'total_invested': total_invested,
            'total_won': total_won,
            'total_net': total_net,
            'total_entries': total_entries,
            'total_rebuys': total_rebuys,
            'total_rake': total_rake,
            'total_days': total_days,
            'total_hands': total_hands,
            'itm_count': itm_count,
            'itm_rate': (itm_count / total_tournaments * 100) if total_tournaments > 0 else 0,
            'avg_buy_in_per_day': total_invested / total_days if total_days > 0 else 0,
            'avg_tournaments_per_day': total_tournaments / total_days if total_days > 0 else 0,
        }

    def get_satellite_summary(self) -> dict:
        """Get satellite tournament summary."""
        satellites = self.repo.get_tournaments(self.year, exclude_satellites=False)
        satellites = [t for t in satellites if t.get('is_satellite')]

        if not satellites:
            return {}

        total_invested = sum(
            (t.get('total_buy_in', 0) or 0) * (t.get('entries', 1) or 1)
            for t in satellites
        )
        total_won = sum(t.get('prize', 0) or 0 for t in satellites)
        total_rake = sum(
            (t.get('rake', 0) or 0) * (t.get('entries', 1) or 1)
            for t in satellites
        )

        return {
            'count': len(satellites),
            'total_invested': total_invested,
            'total_won': total_won,
            'net': total_won - total_invested,
            'total_rake': total_rake,
            'roi': ((total_won - total_invested) / total_invested * 100) if total_invested > 0 else 0,
        }

    # ── Red Line / Blue Line ──────────────────────────────────────────

    def get_redline_blueline(self) -> dict:
        """Compute Red Line / Blue Line cumulative profit for tournament hands.

        Red line  = cumulative profit from non-showdown hands.
        Blue line = cumulative profit from showdown hands.
        Green line = total profit (red + blue).

        Returns dict with chart_data, summary totals, diagnostics,
        and per-day breakdown (each day = one tournament session).
        """
        hands = self.repo.get_tournament_hands(self.year, exclude_satellites=self.exclude_satellites)
        actions = self.repo.get_tournament_all_actions(self.year, exclude_satellites=self.exclude_satellites)

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

        # Per-day aggregation (tournament sessions are grouped by day)
        by_day = defaultdict(lambda: {
            'sd_net': 0.0, 'nsd_net': 0.0, 'sd_count': 0, 'nsd_count': 0,
        })

        for h in hands:
            hand_id = h['hand_id']
            net = h['net'] or 0.0
            day = (h.get('date') or '')[:10]
            went_to_sd = CashAnalyzer._hand_went_to_showdown(
                hand_acts.get(hand_id, []), h
            )

            cum_total += net
            total_hands += 1

            if went_to_sd:
                cum_showdown += net
                showdown_hands += 1
                showdown_net += net
                by_day[day]['sd_net'] += net
                by_day[day]['sd_count'] += 1
            else:
                cum_nonshowdown += net
                nonshowdown_hands += 1
                nonshowdown_net += net
                by_day[day]['nsd_net'] += net
                by_day[day]['nsd_count'] += 1

            chart_data.append({
                'hand': total_hands,
                'total': round(cum_total, 2),
                'showdown': round(cum_showdown, 2),
                'nonshowdown': round(cum_nonshowdown, 2),
            })

        if len(chart_data) > 500:
            chart_data = _downsample_redline(chart_data, 500)

        by_session = [
            {
                'date': day,
                'hands': d['sd_count'] + d['nsd_count'],
                'showdown_hands': d['sd_count'],
                'nonshowdown_hands': d['nsd_count'],
                'showdown_net': round(d['sd_net'], 2),
                'nonshowdown_net': round(d['nsd_net'], 2),
                'total_net': round(d['sd_net'] + d['nsd_net'], 2),
            }
            for day, d in sorted(by_day.items(), reverse=True)
            if d['sd_count'] + d['nsd_count'] > 0
        ]

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

    # ── Positional Stats ─────────────────────────────────────────────

    def get_positional_stats(self) -> dict:
        """Calculate per-position stats for tournament hands.

        Computes VPIP, PFR, 3-Bet, AF, CBet, WTSD, W$SD, win rate per position.
        Also computes blinds defense, ATS, comparison, radar data, and 3-bet matrix.

        Returns dict with by_position, blinds_defense, ats_by_pos, comparison, radar,
        three_bet_matrix.
        """
        sequences = self.repo.get_tournament_all_actions(self.year, exclude_satellites=self.exclude_satellites)
        hands_financial = self.repo.get_tournament_hands_with_position(self.year, exclude_satellites=self.exclude_satellites)

        # Build hand-level financial lookup
        hand_bb = {}
        for h in hands_financial:
            hand_bb[h['hand_id']] = h.get('blinds_bb') or 200

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

        # Position vs position matrix for 3-bet drill-down
        pos_vs_pos: dict = defaultdict(lambda: defaultdict(lambda: {
            'three_bet_opps': 0, 'three_bet': 0,
        }))

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
            bb = hand_bb.get(hand_id, 200)
            pd['bb_net'] += (hero_net / bb) if bb > 0 else 0.0

            # Preflop analysis
            preflop_vol = [
                a for a in actions
                if a['street'] == 'preflop'
                and a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')
            ]
            pre = CashAnalyzer._analyze_preflop_hand(preflop_vol)

            if pre['vpip']:
                pd['vpip'] += 1
            if pre['pfr']:
                pd['pfr'] += 1
            if pre['three_bet_opp']:
                pd['three_bet_opps'] += 1
                if pre['three_bet']:
                    pd['three_bet'] += 1
                raiser_pos = pre.get('raiser_position')
                if raiser_pos:
                    cell = pos_vs_pos[hero_pos][raiser_pos]
                    cell['three_bet_opps'] += 1
                    if pre['three_bet']:
                        cell['three_bet'] += 1
            if pre['ats_opp']:
                pd['ats_opps'] += 1
                if pre['ats']:
                    pd['ats'] += 1

            # Blinds defense for BB/SB
            if hero_pos in ('BB', 'SB'):
                bd = CashAnalyzer._analyze_blinds_defense(preflop_vol, hero_pos)
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
            post = CashAnalyzer._analyze_postflop_hand(actions, hero_net)
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

        result = self._format_positional_stats(dict(pos_data))
        result['three_bet_matrix'] = self._format_three_bet_matrix(
            {hp: dict(opps) for hp, opps in pos_vs_pos.items()}
        )
        return result

    def _format_positional_stats(self, pos_data: dict) -> dict:
        """Format raw positional counters into percentages with health badges."""
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
            bb_per_100 = (pd['bb_net'] / t) * 100

            by_position[pos] = {
                'total_hands': t,
                'vpip': vpip,
                'vpip_health': CashAnalyzer._classify_positional_health('vpip', pos, vpip),
                'pfr': pfr,
                'pfr_health': CashAnalyzer._classify_positional_health('pfr', pos, pfr),
                'three_bet': three_bet,
                'three_bet_health': CashAnalyzer._classify_health('three_bet', three_bet),
                'af': af,
                'af_health': CashAnalyzer._classify_postflop_health('af', af),
                'cbet': cbet,
                'cbet_health': CashAnalyzer._classify_postflop_health('cbet', cbet),
                'wtsd': wtsd,
                'wtsd_health': CashAnalyzer._classify_postflop_health('wtsd', wtsd),
                'wsd': wsd,
                'wsd_health': CashAnalyzer._classify_postflop_health('wsd', wsd),
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

        # Radar chart data
        radar = CashAnalyzer._build_radar_data(by_position)

        return {
            'by_position': by_position,
            'blinds_defense': blinds_defense,
            'ats_by_pos': ats_by_pos,
            'comparison': comparison,
            'radar': radar,
        }

    @staticmethod
    def _format_three_bet_matrix(raw: dict) -> dict:
        """Format position-vs-position 3-bet counters into a percentage matrix."""
        def pct(num, den):
            return (num / den * 100) if den > 0 else 0.0

        matrix: dict = {}
        position_order = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']
        for h_pos in position_order:
            if h_pos not in raw:
                continue
            row: dict = {}
            for o_pos in position_order:
                cell = raw[h_pos].get(o_pos)
                if not cell or cell['three_bet_opps'] == 0:
                    continue
                row[o_pos] = {
                    'three_bet_opps': cell['three_bet_opps'],
                    'three_bet_count': cell['three_bet'],
                    'three_bet_pct': pct(cell['three_bet'], cell['three_bet_opps']),
                }
            if row:
                matrix[h_pos] = row
        return matrix

    # ── Stack Depth Analysis ─────────────────────────────────────────

    def get_stack_depth_stats(self) -> dict:
        """Calculate stats segmented by stack depth (BB count) and position.

        Stack depth tiers: deep (50+ BB), medium (25-50 BB),
        shallow (15-25 BB), shove-zone (<15 BB).

        Returns dict with by_tier, by_position_tier, tier_order, tier_labels,
        hands_with_stack, hands_total.
        """
        sequences = self.repo.get_tournament_all_actions(self.year, exclude_satellites=self.exclude_satellites)
        hands_financial = self.repo.get_tournament_hands_with_position(self.year, exclude_satellites=self.exclude_satellites)

        # Build per-hand lookups
        hand_info = {}
        for h in hands_financial:
            bb = h.get('blinds_bb') or 200
            stack = h.get('hero_stack')
            hand_info[h['hand_id']] = {
                'bb': bb,
                'stack_bb': (stack / bb) if (stack and bb > 0) else None,
            }

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

        # Per-tier counters
        def _empty_tier():
            return {
                'total': 0, 'vpip': 0, 'pfr': 0,
                'three_bet_opps': 0, 'three_bet': 0,
                'saw_flop': 0, 'wtsd': 0, 'wsd': 0,
                'cbet_opps': 0, 'cbet': 0,
                'agg_br': 0, 'agg_calls': 0,
                'net': 0.0, 'bb_net': 0.0,
            }

        tier_data = defaultdict(_empty_tier)

        # Per-position x tier counters
        def _empty_pos_tier():
            return {
                'total': 0, 'vpip': 0, 'pfr': 0,
                'net': 0.0, 'bb_net': 0.0,
            }

        pos_tier_data = defaultdict(lambda: defaultdict(_empty_pos_tier))

        total_hands = len(hands_financial)
        hands_with_stack = 0

        for hand_id, actions in hands_actions.items():
            if not any(a['is_hero'] for a in actions):
                continue

            info = hand_info.get(hand_id, {})
            stack_bb = info.get('stack_bb')
            if stack_bb is None:
                continue

            hands_with_stack += 1
            tier = CashAnalyzer._classify_stack_tier(stack_bb)
            meta = hand_meta[hand_id]
            hero_pos = meta['hero_position'] or 'Unknown'
            hero_net = meta['hero_net']
            bb = info.get('bb', 200)

            td = tier_data[tier]
            td['total'] += 1
            td['net'] += hero_net
            td['bb_net'] += (hero_net / bb) if bb > 0 else 0.0

            ptd = pos_tier_data[hero_pos][tier]
            ptd['total'] += 1
            ptd['net'] += hero_net
            ptd['bb_net'] += (hero_net / bb) if bb > 0 else 0.0

            # Preflop analysis
            preflop_vol = [
                a for a in actions
                if a['street'] == 'preflop'
                and a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')
            ]
            pre = CashAnalyzer._analyze_preflop_hand(preflop_vol)

            if pre['vpip']:
                td['vpip'] += 1
                ptd['vpip'] += 1
            if pre['pfr']:
                td['pfr'] += 1
                ptd['pfr'] += 1
            if pre['three_bet_opp']:
                td['three_bet_opps'] += 1
                if pre['three_bet']:
                    td['three_bet'] += 1

            # Postflop analysis
            post = CashAnalyzer._analyze_postflop_hand(actions, hero_net)
            if post['saw_flop']:
                td['saw_flop'] += 1
            if post['went_to_showdown']:
                td['wtsd'] += 1
            if post['won_at_showdown']:
                td['wsd'] += 1
            if post['cbet_opp']:
                td['cbet_opps'] += 1
                if post['cbet']:
                    td['cbet'] += 1
            for street in ('flop', 'turn', 'river'):
                if street in post['hero_aggression']:
                    ha = post['hero_aggression'][street]
                    td['agg_br'] += ha['bets'] + ha['raises']
                    td['agg_calls'] += ha['calls']

        return self._format_stack_depth_stats(
            dict(tier_data), dict(pos_tier_data),
            total_hands, hands_with_stack,
        )

    def _format_stack_depth_stats(self, tier_data: dict,
                                   pos_tier_data: dict,
                                   total_hands: int,
                                   hands_with_stack: int) -> dict:
        """Format raw stack depth counters into percentages with health badges."""
        def pct(num, den):
            return (num / den * 100) if den > 0 else 0.0

        tier_order = ['deep', 'medium', 'shallow', 'shove']
        tier_labels = {
            'deep': '50+ BB',
            'medium': '25-50 BB',
            'shallow': '15-25 BB',
            'shove': '<15 BB',
        }

        by_tier = {}
        for tier in tier_order:
            if tier not in tier_data:
                continue
            td = tier_data[tier]
            t = td['total']
            if t == 0:
                continue

            vpip = pct(td['vpip'], t)
            pfr = pct(td['pfr'], t)
            three_bet = pct(td['three_bet'], td['three_bet_opps'])
            af = td['agg_br'] / td['agg_calls'] if td['agg_calls'] > 0 else 0.0
            cbet = pct(td['cbet'], td['cbet_opps'])
            wtsd = pct(td['wtsd'], td['saw_flop'])
            wsd = pct(td['wsd'], td['wtsd'])
            net_per_hand = td['net'] / t
            bb_per_100 = (td['bb_net'] / t) * 100

            by_tier[tier] = {
                'label': tier_labels[tier],
                'total_hands': t,
                'vpip': vpip,
                'vpip_health': self._classify_stack_depth_health('vpip', tier, vpip),
                'pfr': pfr,
                'pfr_health': self._classify_stack_depth_health('pfr', tier, pfr),
                'three_bet': three_bet,
                'three_bet_health': self._classify_stack_depth_health('three_bet', tier, three_bet),
                'af': af,
                'af_health': CashAnalyzer._classify_postflop_health('af', af),
                'cbet': cbet,
                'cbet_health': CashAnalyzer._classify_postflop_health('cbet', cbet),
                'wtsd': wtsd,
                'wtsd_health': CashAnalyzer._classify_postflop_health('wtsd', wtsd),
                'wsd': wsd,
                'wsd_health': CashAnalyzer._classify_postflop_health('wsd', wsd),
                'net': td['net'],
                'net_per_hand': net_per_hand,
                'bb_per_100': bb_per_100,
                'winrate_health': 'good' if net_per_hand >= 0 else 'danger',
            }

        # Per-position x tier
        position_order = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']
        by_position_tier = {}
        for pos in position_order:
            if pos not in pos_tier_data:
                continue
            pos_tiers = {}
            for tier in tier_order:
                if tier not in pos_tier_data[pos]:
                    continue
                ptd = pos_tier_data[pos][tier]
                t = ptd['total']
                if t < 5:
                    continue
                bb_per_100 = (ptd['bb_net'] / t) * 100
                pos_tiers[tier] = {
                    'label': tier_labels[tier],
                    'total_hands': t,
                    'vpip': pct(ptd['vpip'], t),
                    'pfr': pct(ptd['pfr'], t),
                    'bb_per_100': bb_per_100,
                    'winrate_health': 'good' if bb_per_100 >= 0 else 'danger',
                }
            if pos_tiers:
                by_position_tier[pos] = pos_tiers

        return {
            'by_tier': by_tier,
            'by_position_tier': by_position_tier,
            'tier_order': tier_order,
            'tier_labels': tier_labels,
            'hands_with_stack': hands_with_stack,
            'hands_total': total_hands,
        }

    def _classify_stack_depth_health(self, stat: str, tier: str,
                                     value: float) -> str:
        """Classify a stat's health against the tier-specific range."""
        if stat == 'vpip':
            h = self._stack_vpip_healthy.get(tier, self._healthy_ranges.get('vpip'))
            w = self._stack_vpip_warning.get(tier, self._warning_ranges.get('vpip'))
        elif stat == 'pfr':
            h = self._stack_pfr_healthy.get(tier, self._healthy_ranges.get('pfr'))
            w = self._stack_pfr_warning.get(tier, self._warning_ranges.get('pfr'))
        elif stat == 'three_bet':
            h = self._stack_3bet_healthy.get(tier, self._healthy_ranges.get('three_bet'))
            w = self._stack_3bet_warning.get(tier, self._warning_ranges.get('three_bet'))
        else:
            return CashAnalyzer._classify_health(stat, value)

        if h and h[0] <= value <= h[1]:
            return 'good'
        if w and w[0] <= value <= w[1]:
            return 'warning'
        return 'danger'

    # ── Hand Matrix ──────────────────────────────────────────────────

    def get_hand_matrix(self) -> dict:
        """Build 13x13 hand matrix data grouped by position for tournament hands.

        For each position and each hand category (e.g. 'AKs', 'AKo', 'AA'),
        computes times_dealt, times_played, frequency, action breakdown,
        net and win_rate (bb/100).

        Returns dict with overall, by_position, top_profitable, top_deficit, total_hands.
        """
        hands = self.repo.get_tournament_hands_with_cards(self.year, exclude_satellites=self.exclude_satellites)
        preflop_seqs = self.repo.get_tournament_preflop_actions(self.year, exclude_satellites=self.exclude_satellites)

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
            bb = hand.get('blinds_bb') or 200
            bb_net = net / bb if bb > 0 else 0.0

            overall[cat]['dealt'] += 1
            by_position[pos][cat]['dealt'] += 1

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

    # ── Bet Sizing & Pot-Type Segmentation ───────────────────────────

    def get_bet_sizing_analysis(self) -> dict:
        """Compute bet sizing and pot-type segmentation for tournament hands.

        Classifies each hand by pot type (limped, SRP, 3-bet, 4-bet+) and
        computes per-type stats: VPIP, PFR, AF, CBet, WTSD, W$SD, win rate.
        Also tracks bet sizing distributions by street and separates
        heads-up vs multiway results.

        Returns dict with pot_types, sizing, hu_vs_multiway, diagnostics.
        """
        hands = self.repo.get_tournament_hands(self.year, exclude_satellites=self.exclude_satellites)
        actions_list = self.repo.get_tournament_all_actions(self.year, exclude_satellites=self.exclude_satellites)

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
            blinds_bb = meta['blinds_bb'] or 200

            preflop = [a for a in actions if a['street'] == 'preflop']
            pot_type = _classify_pot_type(preflop)

            # Determine HU vs multiway
            flop_players = {a['player'] for a in actions if a['street'] == 'flop'}
            if flop_players:
                is_hu = len(flop_players) <= 2
            else:
                is_hu = _count_active_players(preflop) <= 2

            # Preflop analysis
            voluntary = [a for a in preflop
                         if a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')]
            pf_pre = CashAnalyzer._analyze_preflop_hand(voluntary)

            # Postflop analysis
            hero_net = (actions[0].get('hero_net') or 0.0) if actions else 0.0
            pf_post = CashAnalyzer._analyze_postflop_hand(actions, hero_net)

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

    # ── Leak Finder Integration ──────────────────────────────────────

    def get_leak_analysis(self) -> dict:
        """Run leak finder analysis for tournament hands.

        LeakFinder accepts this analyzer via duck typing (not coupled to CashAnalyzer).
        Uses get_tournament_daily_stats() for period comparison.

        Returns dict with:
        - health_score: 0-100 overall health score
        - top5: top 5 leaks sorted by cost
        - study_spots: concrete study actions
        - period_comparison: last 30 days vs overall
        - leaks: all detected leaks
        - total_leaks: count
        """
        from src.analyzers.leak_finder import LeakFinder
        finder = LeakFinder(self, self.repo, self.year)
        return finder.find_leaks()

    # ── Tilt Analysis Integration ────────────────────────────────────

    def get_tilt_analysis(self) -> dict:
        """Run tilt detection for tournament hands.

        Each tournament_id is treated as a pseudo-session for tilt detection.
        Hourly/duration analysis uses all tournament hands.

        Returns dict with:
        - session_tilt: per-tournament tilt detection (each tournament = session)
        - tilt_sessions_count: tournaments with tilt detected
        - hourly: performance by hour/bucket
        - duration: performance by pseudo-duration bucket
        - post_bad_beat: post-bad-beat performance stats
        - recommendation: session duration advice
        - diagnostics: auto-generated diagnostic messages
        """
        from src.analyzers.tilt import (
            TiltAnalyzer, _compute_segment_stats, _classify_tilt_severity,
            _generate_tilt_diagnostics, _get_hour, _get_avg_bb,
            _classify_tilt_wr_health, _MIN_HANDS_SEGMENT,
            _TILT_VPIP_DELTA, _TILT_PFR_DELTA, _TILT_AF_DELTA,
            _HOUR_BUCKETS, _DURATION_BUCKETS,
            _BAD_BEAT_BB, _POST_BAD_BEAT_WINDOW,
        )
        from collections import defaultdict

        all_hands = self.repo.get_tournament_hands(self.year, exclude_satellites=self.exclude_satellites)
        if not all_hands:
            return {}

        # Build pseudo-sessions: one per tournament_id
        tournaments_map = defaultdict(list)
        for h in all_hands:
            tid = h.get('tournament_id') or 'unknown'
            tournaments_map[tid].append(h)

        all_actions = self.repo.get_tournament_all_actions(self.year, exclude_satellites=self.exclude_satellites)
        actions_by_tid = defaultdict(list)
        for a in all_actions:
            tid = a.get('tournament_id') or 'unknown'
            actions_by_tid[tid].append(a)

        # Per-tournament tilt detection (pseudo-session)
        session_tilt_list = []
        for tid, hands in tournaments_map.items():
            hands_sorted = sorted(hands, key=lambda x: x.get('date', ''))
            tid_actions = actions_by_tid.get(tid, [])
            n = len(hands_sorted)

            if n < _MIN_HANDS_SEGMENT * 2:
                session_tilt_list.append({
                    'session_id': tid,
                    'session_date': hands_sorted[0].get('date', '')[:10] if hands_sorted else '',
                    'start_time': hands_sorted[0].get('date', '') if hands_sorted else '',
                    'tilt_detected': False,
                    'tilt_signals': [],
                    'severity': 'good',
                    'total_hands': n,
                    'reason': 'insufficient_hands',
                })
                continue

            mid = n // 2
            first_half = hands_sorted[:mid]
            second_half = hands_sorted[mid:]

            first_stats = _compute_segment_stats(first_half, tid_actions)
            second_stats = _compute_segment_stats(second_half, tid_actions)

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

            tilt_cost_bb = 0.0
            if tilt_detected:
                avg_bb = _get_avg_bb(hands_sorted)
                n_first = first_stats['total_hands']
                n_second = second_stats['total_hands']
                if avg_bb > 0 and n_first > 0 and n_second > 0:
                    first_bb100 = (first_stats['net'] / avg_bb) / (n_first / 100)
                    second_bb100 = (second_stats['net'] / avg_bb) / (n_second / 100)
                    degradation_bb100 = max(0.0, first_bb100 - second_bb100)
                    tilt_cost_bb = round(degradation_bb100 * n_second / 100, 1)

            session_tilt_list.append({
                'session_id': tid,
                'session_date': hands_sorted[0].get('date', '')[:10] if hands_sorted else '',
                'start_time': hands_sorted[0].get('date', '') if hands_sorted else '',
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
            })

        # Hourly performance (all tournament hands)
        by_hour = defaultdict(lambda: {'hands': 0, 'net': 0.0, 'net_bb': 0.0})
        by_bucket = defaultdict(lambda: {'hands': 0, 'net': 0.0, 'net_bb': 0.0})

        for h in all_hands:
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

        hourly_data = []
        for hour_num in range(24):
            d = by_hour[hour_num]
            hc = d['hands']
            wr = (d['net_bb'] / hc * 100) if hc > 0 else 0.0
            hourly_data.append({
                'hour': hour_num, 'hands': hc,
                'net': round(d['net'], 2),
                'win_rate_bb100': round(wr, 1),
            })

        buckets = {}
        for name, _, _ in _HOUR_BUCKETS:
            d = by_bucket.get(name, {'hands': 0, 'net': 0.0, 'net_bb': 0.0})
            hc = d['hands']
            wr = (d['net_bb'] / hc * 100) if hc > 0 else 0.0
            buckets[name] = {
                'hands': hc, 'net': round(d['net'], 2),
                'win_rate_bb100': round(wr, 1),
                'health': _classify_tilt_wr_health(wr),
            }

        hourly = {'hourly': hourly_data, 'buckets': buckets}

        # Duration: use per-tournament elapsed time
        dur_acc = defaultdict(lambda: {'hands': 0, 'net': 0.0, 'net_bb': 0.0})
        for tid, hands in tournaments_map.items():
            hands_sorted = sorted(hands, key=lambda x: x.get('date', ''))
            if not hands_sorted:
                continue
            try:
                start_dt = datetime.fromisoformat(hands_sorted[0].get('date', ''))
            except (ValueError, TypeError):
                continue
            for h in hands_sorted:
                try:
                    hand_dt = datetime.fromisoformat(h.get('date', ''))
                except (ValueError, TypeError):
                    continue
                elapsed_min = max(0.0, (hand_dt - start_dt).total_seconds() / 60)
                net = h.get('net') or 0
                bb = h.get('blinds_bb') or 1.0
                for label, lo, hi in _DURATION_BUCKETS:
                    if lo <= elapsed_min < hi:
                        dur_acc[label]['hands'] += 1
                        dur_acc[label]['net'] += net
                        dur_acc[label]['net_bb'] += net / bb
                        break

        dur_buckets = []
        for label, _, _ in _DURATION_BUCKETS:
            d = dur_acc.get(label, {'hands': 0, 'net': 0.0, 'net_bb': 0.0})
            hc = d['hands']
            wr = (d['net_bb'] / hc * 100) if hc > 0 else 0.0
            dur_buckets.append({
                'label': label, 'hands': hc,
                'net': round(d['net'], 2),
                'win_rate_bb100': round(wr, 1),
                'health': _classify_tilt_wr_health(wr),
            })
        duration = {'buckets': dur_buckets}

        # Post-bad-beat
        all_hands_sorted = sorted(all_hands, key=lambda x: x.get('date', ''))
        if not all_hands_sorted:
            post_bad_beat = {
                'bad_beats': 0, 'post_bb_win_rate': 0.0,
                'baseline_win_rate': 0.0, 'post_hands_analyzed': 0,
                'degradation_bb100': 0.0,
            }
        else:
            total_net_bb = sum(
                (h.get('net') or 0) / (h.get('blinds_bb') or 1.0)
                for h in all_hands_sorted
            )
            baseline_wr = round(total_net_bb / len(all_hands_sorted) * 100, 1)
            bad_beat_indices = [
                i for i, h in enumerate(all_hands_sorted)
                if (h.get('net') or 0) / (h.get('blinds_bb') or 1.0) <= -_BAD_BEAT_BB
            ]
            if not bad_beat_indices:
                post_bad_beat = {
                    'bad_beats': 0, 'post_bb_win_rate': 0.0,
                    'baseline_win_rate': baseline_wr, 'post_hands_analyzed': 0,
                    'degradation_bb100': 0.0,
                }
            else:
                post_net_bb = 0.0
                post_count = 0
                for idx in bad_beat_indices:
                    window = all_hands_sorted[idx + 1: idx + 1 + _POST_BAD_BEAT_WINDOW]
                    for h in window:
                        post_net_bb += (h.get('net') or 0) / (h.get('blinds_bb') or 1.0)
                        post_count += 1
                post_wr = round(post_net_bb / post_count * 100, 1) if post_count > 0 else 0.0
                post_bad_beat = {
                    'bad_beats': len(bad_beat_indices),
                    'post_bb_win_rate': post_wr,
                    'baseline_win_rate': baseline_wr,
                    'post_hands_analyzed': post_count,
                    'degradation_bb100': round(post_wr - baseline_wr, 1),
                }

        # Recommendation
        valid_dur = [b for b in dur_buckets if b.get('hands', 0) >= 10]
        if not valid_dur:
            recommendation = {
                'text': 'Dados insuficientes para recomendação (mínimo 10 mãos por período).',
                'ideal_duration': None,
            }
        else:
            best = max(valid_dur, key=lambda b: b['win_rate_bb100'])
            positive = [b for b in valid_dur if b['win_rate_bb100'] >= 0]
            if not positive:
                recommendation = {
                    'text': (
                        'Performance negativa em todos os períodos analisados. '
                        'Considere revisar a estratégia geral antes de aumentar volume.'
                    ),
                    'ideal_duration': None,
                }
            else:
                degradation = any(
                    valid_dur[i + 1]['win_rate_bb100'] < valid_dur[i]['win_rate_bb100'] - 5
                    for i in range(len(valid_dur) - 1)
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
                recommendation = {
                    'text': text,
                    'ideal_duration': best['label'],
                    'best_bucket': best,
                }

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

    # ── Decision EV Integration ──────────────────────────────────────

    def get_decision_ev_analysis(self) -> dict:
        """Run decision-tree EV analysis for tournament hands.

        Uses EVAnalyzer._compute_decision_ev() with tournament data.

        Returns dict with total_hands, by_street, leaks, chart_data.
        """
        ev = EVAnalyzer(self.repo, self.year)
        return ev.get_tournament_decision_ev_analysis()

    # ── Session Leak Summary ─────────────────────────────────────────

    def get_session_leak_summary(self, stats: dict) -> list[dict]:
        """Compute a leak summary for a single tournament's stats.

        Checks VPIP, PFR, 3-Bet, AF, WTSD, W$SD, CBet against healthy ranges.
        Returns a list of dicts for stats that are 'warning' or 'danger',
        sorted by estimated cost in bb/100 (highest first).

        Each entry contains:
          stat_name, label, value, health, healthy_low, healthy_high,
          cost_bb100, direction ('too_high'|'too_low'), suggestion.
        """
        if not stats or stats.get('total_hands', 0) == 0:
            return []

        STAT_META = {
            'vpip':      ('VPIP',  'preflop',  0.15),
            'pfr':       ('PFR',   'preflop',  0.18),
            'three_bet': ('3-Bet', 'preflop',  0.12),
            'af':        ('AF',    'postflop', 0.40),
            'wtsd':      ('WTSD%', 'postflop', 0.12),
            'wsd':       ('W$SD%', 'postflop', 0.10),
            'cbet':      ('CBet%', 'postflop', 0.10),
        }

        SUGGESTIONS = {
            ('vpip', 'too_high'):      'Reduza range de abertura: revise mãos marginais que está jogando.',
            ('vpip', 'too_low'):       'Amplie range de abertura: adicione mãos com bom playability.',
            ('pfr', 'too_high'):       'Reduza frequência de raise: identifique spots de call ou limp.',
            ('pfr', 'too_low'):        'Aumente agressividade preflop: substitua calls por raises.',
            ('three_bet', 'too_high'): 'Reduza 3-bets: polarize entre value e bluffs equilibrados.',
            ('three_bet', 'too_low'):  'Aumente 3-bets: adicione bluffs com Axs e suited connectors.',
            ('af', 'too_high'):        'Reduza agressividade postflop: adicione mais checks e calls ao range.',
            ('af', 'too_low'):         'Aumente agressividade postflop: aposte mais com value e bluffs.',
            ('wtsd', 'too_high'):      'Vá ao showdown menos: folde mãos fracas no river.',
            ('wtsd', 'too_low'):       'Defenda mais: não folde em excesso com mãos com equity suficiente.',
            ('wsd', 'too_high'):       'W$SD alto indica range tight: considere adicionar bluffs ao showdown.',
            ('wsd', 'too_low'):        'Melhore seleção de mãos para showdown: folde bluff-catchers fracos.',
            ('cbet', 'too_high'):      'Reduza c-bets: check em boards wet/low desfavoráveis ao seu range.',
            ('cbet', 'too_low'):       'Aumente c-bets: aposte mais em boards favoráveis como PFA.',
        }

        leaks = []
        for stat_name, (label, category, weight) in STAT_META.items():
            if stat_name not in stats:
                continue
            value = stats[stat_name]
            health = stats.get(f'{stat_name}_health', 'good')
            if health == 'good':
                continue

            healthy = (
                self._healthy_ranges.get(stat_name)
                if category == 'preflop'
                else self._postflop_healthy_ranges.get(stat_name)
            )
            if not healthy:
                continue

            low, high = healthy
            if value < low:
                direction = 'too_low'
                deviation = low - value
            else:
                direction = 'too_high'
                deviation = value - high

            cost = round(deviation * weight, 2)
            suggestion = SUGGESTIONS.get(
                (stat_name, direction),
                f'Ajuste {label} neste torneio.',
            )

            leaks.append({
                'stat_name': stat_name,
                'label': label,
                'value': value,
                'health': health,
                'healthy_low': low,
                'healthy_high': high,
                'cost_bb100': cost,
                'direction': direction,
                'suggestion': suggestion,
            })

        leaks.sort(key=lambda x: x['cost_bb100'], reverse=True)
        return leaks
