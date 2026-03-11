"""Spin & Gold cycle analysis module.

Reads from database and computes Spin & Gold + WSOP Express + satellite statistics.
"""

from collections import defaultdict

from src.db.repository import Repository


def _classify_tournament_category(name: str) -> str:
    """Classify a tournament by name into a category.

    Returns one of: 'spin_gold', 'wsop_express', 'regular_satellite', 'other'.
    """
    lower = (name or '').lower()
    if 'spin' in lower and 'gold' in lower:
        return 'spin_gold'
    if 'sop' in lower and 'express' in lower:
        return 'wsop_express'
    return 'regular_satellite'


def _compute_category_stats(tournaments: list[dict], category_name: str) -> dict:
    """Compute stats for a list of tournaments in a category."""
    count = len(tournaments)
    if count == 0:
        return {
            'category': category_name,
            'count': 0,
            'total_invested': 0,
            'total_won': 0,
            'net': 0,
            'total_rake': 0,
            'roi': 0,
            'itm_count': 0,
            'itm_rate': 0,
            'win_count': 0,
            'win_rate': 0,
            'avg_buy_in': 0,
            'avg_prize': 0,
        }

    total_invested = sum(
        (t.get('total_buy_in', 0) or 0) * (t.get('entries', 1) or 1)
        for t in tournaments
    )
    total_won = sum(t.get('prize', 0) or 0 for t in tournaments)
    total_rake = sum(
        (t.get('rake', 0) or 0) * (t.get('entries', 1) or 1)
        for t in tournaments
    )
    itm_count = sum(1 for t in tournaments if (t.get('prize', 0) or 0) > 0)
    win_count = sum(1 for t in tournaments if t.get('position') == 1)
    net = total_won - total_invested

    return {
        'category': category_name,
        'count': count,
        'total_invested': round(total_invested, 2),
        'total_won': round(total_won, 2),
        'net': round(net, 2),
        'total_rake': round(total_rake, 2),
        'roi': round(net / total_invested * 100, 1) if total_invested > 0 else 0,
        'itm_count': itm_count,
        'itm_rate': round(itm_count / count * 100, 1) if count > 0 else 0,
        'win_count': win_count,
        'win_rate': round(win_count / count * 100, 1) if count > 0 else 0,
        'avg_buy_in': round(total_invested / count, 2) if count > 0 else 0,
        'avg_prize': round(total_won / count, 2) if count > 0 else 0,
    }


_CATEGORY_LABELS = {
    'spin_gold': 'Spin & Gold',
    'wsop_express': 'WSOP Express',
    'regular_satellite': 'Other Satellites',
}


class SpinAnalyzer:
    """Analyze Spin & Gold satellite cycle data."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def get_stats(self) -> dict:
        """Compute Spin & Gold + WSOP Express cycle statistics."""
        summaries = self.repo.get_tournament_summaries()

        spin_results = []
        wsop_results = []

        for tid, s in summaries.items():
            name = (s.get('name') or '').lower()
            if 'spin' in name and 'gold' in name:
                spin_results.append(s)
            elif 'sop' in name and 'express' in name:
                wsop_results.append(s)

        # Spin stats
        spin_count = len(spin_results)
        spin_invested = sum(s.get('total_buy_in', 0) or 0 for s in spin_results)
        spin_rake = sum(s.get('rake', 0) or 0 for s in spin_results)
        spin_wins = sum(1 for s in spin_results if s.get('position') == 1)
        spin_tickets_value = spin_wins * 10  # Each ticket = $10

        spin_win_rate = (spin_wins / spin_count * 100) if spin_count > 0 else 0

        # WSOP stats
        wsop_count = len(wsop_results)
        wsop_invested = sum(s.get('total_buy_in', 0) or 0 for s in wsop_results)
        wsop_rake = sum(s.get('rake', 0) or 0 for s in wsop_results)
        wsop_itm = sum(1 for s in wsop_results if (s.get('prize', 0) or 0) > 0)
        wsop_prizes = sum(s.get('prize', 0) or 0 for s in wsop_results)
        wsop_itm_rate = (wsop_itm / wsop_count * 100) if wsop_count > 0 else 0

        # Cycle
        tickets_used = min(spin_wins, wsop_count)
        extra_cash = max(0, wsop_count - spin_wins) * 10
        total_cost = spin_invested + extra_cash
        net_profit = wsop_prizes - total_cost
        roi = ((wsop_prizes - total_cost) / total_cost * 100) if total_cost > 0 else 0

        return {
            'spin': {
                'count': spin_count,
                'total_invested': spin_invested,
                'total_rake': spin_rake,
                'wins': spin_wins,
                'tickets_won': spin_wins,
                'ticket_value': 10,
                'tickets_value': spin_tickets_value,
                'win_rate': spin_win_rate,
                'results': spin_results,
            },
            'wsop': {
                'count': wsop_count,
                'total_invested': wsop_invested,
                'total_rake': wsop_rake,
                'itm_count': wsop_itm,
                'total_prizes': wsop_prizes,
                'itm_rate': wsop_itm_rate,
                'results': wsop_results,
            },
            'cycle': {
                'real_investment': spin_invested,
                'tickets_generated': spin_wins,
                'tickets_used': tickets_used,
                'extra_cash_wsop': extra_cash,
                'total_return': wsop_prizes,
                'net_profit': net_profit,
                'roi': roi,
            },
        }

    def get_satellite_analysis(self) -> dict:
        """Compute comprehensive satellite & spin analysis.

        Returns a dict with:
          - summary: overall satellite stats
          - by_category: per-category breakdown
          - cycle: spin→WSOP cycle analysis
          - timeline: daily aggregation for chart
          - recent_results: last 20 satellite results
        """
        # Get all tournaments, then filter to satellites
        all_tournaments = self.repo.get_tournaments(exclude_satellites=False)
        satellites = [t for t in all_tournaments if t.get('is_satellite')]

        if not satellites:
            return {}

        # Get summaries for cycle analysis
        summaries = self.repo.get_tournament_summaries()

        # ── Categorize ──────────────────────────────────────────
        by_cat = defaultdict(list)
        for t in satellites:
            cat = _classify_tournament_category(t.get('name', ''))
            by_cat[cat].append(t)

        # ── Per-Category Stats ──────────────────────────────────
        categories = {}
        for cat_key in ['spin_gold', 'wsop_express', 'regular_satellite']:
            cat_tournaments = by_cat.get(cat_key, [])
            if cat_tournaments:
                categories[cat_key] = _compute_category_stats(
                    cat_tournaments, _CATEGORY_LABELS[cat_key],
                )

        # ── Overall Summary ─────────────────────────────────────
        total_invested = sum(
            (t.get('total_buy_in', 0) or 0) * (t.get('entries', 1) or 1)
            for t in satellites
        )
        total_won = sum(t.get('prize', 0) or 0 for t in satellites)
        total_rake = sum(
            (t.get('rake', 0) or 0) * (t.get('entries', 1) or 1)
            for t in satellites
        )
        total_net = total_won - total_invested
        itm_count = sum(1 for t in satellites if (t.get('prize', 0) or 0) > 0)
        win_count = sum(1 for t in satellites if t.get('position') == 1)

        summary = {
            'count': len(satellites),
            'total_invested': round(total_invested, 2),
            'total_won': round(total_won, 2),
            'net': round(total_net, 2),
            'total_rake': round(total_rake, 2),
            'roi': round(total_net / total_invested * 100, 1) if total_invested > 0 else 0,
            'itm_count': itm_count,
            'itm_rate': round(itm_count / len(satellites) * 100, 1) if satellites else 0,
            'win_count': win_count,
            'win_rate': round(win_count / len(satellites) * 100, 1) if satellites else 0,
        }

        # ── Cycle Analysis (Spin → WSOP) ────────────────────────
        spin_results = []
        wsop_results = []
        for tid, s in summaries.items():
            name = (s.get('name') or '').lower()
            if 'spin' in name and 'gold' in name:
                spin_results.append(s)
            elif 'sop' in name and 'express' in name:
                wsop_results.append(s)

        spin_wins = sum(1 for s in spin_results if s.get('position') == 1)
        spin_invested = sum(s.get('total_buy_in', 0) or 0 for s in spin_results)
        wsop_prizes = sum(s.get('prize', 0) or 0 for s in wsop_results)
        tickets_used = min(spin_wins, len(wsop_results))
        extra_cash = max(0, len(wsop_results) - spin_wins) * 10
        cycle_total_cost = spin_invested + extra_cash
        cycle_net = wsop_prizes - cycle_total_cost

        cycle = {
            'spin_count': len(spin_results),
            'spin_invested': round(spin_invested, 2),
            'spin_wins': spin_wins,
            'wsop_count': len(wsop_results),
            'wsop_prizes': round(wsop_prizes, 2),
            'tickets_used': tickets_used,
            'extra_cash': round(extra_cash, 2),
            'total_cost': round(cycle_total_cost, 2),
            'net': round(cycle_net, 2),
            'roi': round(cycle_net / cycle_total_cost * 100, 1) if cycle_total_cost > 0 else 0,
        }

        # ── Timeline (daily aggregation) ────────────────────────
        daily = defaultdict(lambda: {'count': 0, 'invested': 0, 'won': 0, 'net': 0})
        for t in satellites:
            day = (t.get('date') or '')[:10]
            if not day:
                continue
            inv = (t.get('total_buy_in', 0) or 0) * (t.get('entries', 1) or 1)
            won = t.get('prize', 0) or 0
            daily[day]['count'] += 1
            daily[day]['invested'] += inv
            daily[day]['won'] += won
            daily[day]['net'] += won - inv

        timeline = []
        cum_net = 0.0
        for day in sorted(daily):
            d = daily[day]
            cum_net += d['net']
            timeline.append({
                'date': day,
                'count': d['count'],
                'invested': round(d['invested'], 2),
                'won': round(d['won'], 2),
                'net': round(d['net'], 2),
                'cumulative': round(cum_net, 2),
            })

        # ── Recent Results ──────────────────────────────────────
        sorted_sats = sorted(satellites, key=lambda t: t.get('date', ''), reverse=True)
        recent = []
        for t in sorted_sats[:20]:
            inv = (t.get('total_buy_in', 0) or 0) * (t.get('entries', 1) or 1)
            won = t.get('prize', 0) or 0
            cat = _classify_tournament_category(t.get('name', ''))
            recent.append({
                'tournament_id': t.get('tournament_id', ''),
                'name': t.get('name', ''),
                'date': t.get('date', ''),
                'buy_in': round(inv, 2),
                'prize': round(won, 2),
                'net': round(won - inv, 2),
                'position': t.get('position'),
                'players': t.get('total_players', 0),
                'category': _CATEGORY_LABELS.get(cat, cat),
            })

        return {
            'summary': summary,
            'by_category': categories,
            'cycle': cycle,
            'timeline': timeline,
            'recent_results': recent,
        }
