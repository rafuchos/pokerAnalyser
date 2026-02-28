"""Spin & Gold cycle analysis module.

Reads from database and computes Spin & Gold + WSOP Express statistics.
"""

from collections import defaultdict

from src.db.repository import Repository


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
