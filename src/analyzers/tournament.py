"""Tournament analysis module.

Reads from database and computes statistics for reports.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from src.db.repository import Repository


class TournamentAnalyzer:
    """Analyze tournament data from the database."""

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
                'tournaments': day_tournaments,
            })

        return reports

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

        return {
            'total_tournaments': total_tournaments,
            'total_invested': total_invested,
            'total_won': total_won,
            'total_net': total_net,
            'total_entries': total_entries,
            'total_rebuys': total_rebuys,
            'total_rake': total_rake,
            'total_days': total_days,
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
