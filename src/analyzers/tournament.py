"""Tournament analysis module.

Reads from database and computes statistics for reports.
Includes per-tournament preflop/postflop stats, EV analysis,
chip sparklines, and daily aggregated breakdowns.
"""

from collections import defaultdict

from src.analyzers.cash import CashAnalyzer
from src.analyzers.ev import EVAnalyzer, parse_cards, calculate_equity
from src.db.repository import Repository


class TournamentAnalyzer:
    """Analyze tournament data from the database."""

    # Reuse health ranges from CashAnalyzer
    HEALTHY_RANGES = CashAnalyzer.HEALTHY_RANGES
    WARNING_RANGES = CashAnalyzer.WARNING_RANGES
    POSTFLOP_HEALTHY_RANGES = CashAnalyzer.POSTFLOP_HEALTHY_RANGES
    POSTFLOP_WARNING_RANGES = CashAnalyzer.POSTFLOP_WARNING_RANGES

    def __init__(self, repo: Repository, year: str = '2026'):
        self.repo = repo
        self.year = year

    def get_daily_reports(self) -> list[dict]:
        """Build daily report data for HTML generation."""
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

            # Aggregate day stats (weighted by hands count)
            day_stats = self._aggregate_tournament_stats(tournament_details)

            # Build comparison
            comparison = self._build_tournament_comparison(tournament_details)

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
            })

        return reports

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
            preflop_seqs = self.repo.get_tournament_preflop_actions(self.year)
            all_seqs = self.repo.get_tournament_all_actions(self.year)

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
        all_hands = self.repo.get_tournament_hands(self.year)
        allin_hands = self.repo.get_tournament_allin_hands(self.year)

        if not all_hands:
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
        total_hands = self.repo.get_tournament_hand_count(self.year)

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
