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
