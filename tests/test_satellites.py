"""Tests for US-037: Satellite & Sit-and-Go Analysis.

Covers:
- SpinAnalyzer.get_satellite_analysis() – category classification, summary stats,
  cycle analysis, timeline, recent results
- _classify_tournament_category() – tournament name classification
- _compute_category_stats() – per-category stat computation
- Analytics pipeline: satellite analysis persisted to analytics.db
- Web data layer: prepare_satellites_data() enrichment
- Web routes: /tournament/satellites route and template rendering
- Edge cases: no satellites, single category, empty data
"""

import json
import os
import sqlite3
import tempfile
import unittest

from src.db.schema import init_db
from src.db.repository import Repository
from src.db.analytics_schema import init_analytics_db
from src.analyzers.spin import (
    SpinAnalyzer,
    _classify_tournament_category,
    _compute_category_stats,
    _CATEGORY_LABELS,
)
from src.web.app import create_app
from src.web.data import (
    load_analytics_data,
    prepare_satellites_data,
)


# ── Helpers ──────────────────────────────────────────────────────


def _setup_db():
    """Create an in-memory DB with schema initialized."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Repository(conn)


def _insert_tournament(repo, tournament_id='T100', name='MTT $5.50',
                       date='2026-01-15', buy_in=5.0, rake=0.5,
                       prize=0.0, position=None, entries=1,
                       is_satellite=False, total_players=100):
    """Insert a tournament record."""
    repo.insert_tournament({
        'tournament_id': tournament_id,
        'platform': 'GGPoker',
        'name': name,
        'date': date,
        'buy_in': buy_in,
        'rake': rake,
        'bounty': 0,
        'total_buy_in': buy_in + rake,
        'position': position,
        'prize': prize,
        'bounty_won': 0,
        'total_players': total_players,
        'entries': entries,
        'is_bounty': False,
        'is_satellite': is_satellite,
    })
    # Also insert into tournament_summaries via SQL for SpinAnalyzer.get_stats()
    repo.conn.execute(
        "INSERT OR REPLACE INTO tournament_summaries "
        "(tournament_id, platform, name, date, buy_in, rake, bounty, total_buy_in, "
        "position, prize, bounty_won, total_players, entries, is_bounty, is_satellite) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tournament_id, 'GGPoker', name, date, buy_in, rake, 0, buy_in + rake,
         position, prize, 0, total_players, entries,
         1 if False else 0, 1 if is_satellite else 0),
    )


def _create_analytics_db_with_satellites(path: str):
    """Create an analytics.db with satellite data for web tests."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_analytics_db(conn)

    now = '2026-03-11T12:00:00'

    # Tournament summary (required for overview)
    summary = {
        'total_hands': 500,
        'total_net': 150.0,
        'total_tournaments': 20,
        'total_invested': 100.0,
        'total_days': 5,
    }
    conn.execute(
        "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
        "VALUES (?, ?, ?, ?)",
        ('tournament', 'summary', json.dumps(summary), now),
    )

    # Satellite analysis data
    sat_analysis = {
        'summary': {
            'count': 15,
            'total_invested': 82.50,
            'total_won': 130.00,
            'net': 47.50,
            'total_rake': 7.50,
            'roi': 57.6,
            'itm_count': 5,
            'itm_rate': 33.3,
            'win_count': 4,
            'win_rate': 26.7,
        },
        'by_category': {
            'spin_gold': {
                'category': 'Spin & Gold',
                'count': 10,
                'total_invested': 55.00,
                'total_won': 80.00,
                'net': 25.00,
                'total_rake': 5.00,
                'roi': 45.5,
                'itm_count': 3,
                'itm_rate': 30.0,
                'win_count': 3,
                'win_rate': 30.0,
                'avg_buy_in': 5.50,
                'avg_prize': 8.00,
            },
            'wsop_express': {
                'category': 'WSOP Express',
                'count': 5,
                'total_invested': 27.50,
                'total_won': 50.00,
                'net': 22.50,
                'total_rake': 2.50,
                'roi': 81.8,
                'itm_count': 2,
                'itm_rate': 40.0,
                'win_count': 1,
                'win_rate': 20.0,
                'avg_buy_in': 5.50,
                'avg_prize': 10.00,
            },
        },
        'cycle': {
            'spin_count': 10,
            'spin_invested': 55.00,
            'spin_wins': 3,
            'wsop_count': 5,
            'wsop_prizes': 50.00,
            'tickets_used': 3,
            'extra_cash': 20.00,
            'total_cost': 75.00,
            'net': -25.00,
            'roi': -33.3,
        },
        'timeline': [
            {'date': '2026-01-10', 'count': 3, 'invested': 16.50,
             'won': 20.00, 'net': 3.50, 'cumulative': 3.50},
            {'date': '2026-01-15', 'count': 5, 'invested': 27.50,
             'won': 50.00, 'net': 22.50, 'cumulative': 26.00},
            {'date': '2026-01-20', 'count': 7, 'invested': 38.50,
             'won': 60.00, 'net': 21.50, 'cumulative': 47.50},
        ],
        'recent_results': [
            {
                'tournament_id': 'SAT1',
                'name': 'Spin & Gold $5',
                'date': '2026-01-20',
                'buy_in': 5.50,
                'prize': 10.00,
                'net': 4.50,
                'position': 1,
                'players': 3,
                'category': 'Spin & Gold',
            },
            {
                'tournament_id': 'SAT2',
                'name': 'WSOP Express $10',
                'date': '2026-01-15',
                'buy_in': 5.50,
                'prize': 0.00,
                'net': -5.50,
                'position': 3,
                'players': 100,
                'category': 'WSOP Express',
            },
        ],
    }
    conn.execute(
        "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
        "VALUES (?, ?, ?, ?)",
        ('tournament', 'satellite_analysis', json.dumps(sat_analysis), now),
    )

    conn.commit()
    conn.close()


# ── Unit Tests: Classification ───────────────────────────────────


class TestClassifyTournamentCategory(unittest.TestCase):
    """Test _classify_tournament_category() classification logic."""

    def test_spin_gold(self):
        self.assertEqual(_classify_tournament_category('Spin & Gold $5'), 'spin_gold')

    def test_spin_gold_case_insensitive(self):
        self.assertEqual(_classify_tournament_category('SPIN & GOLD $10'), 'spin_gold')

    def test_wsop_express(self):
        self.assertEqual(_classify_tournament_category('WSOP Express $10'), 'wsop_express')

    def test_wsop_express_partial(self):
        self.assertEqual(_classify_tournament_category('sop express sat'), 'wsop_express')

    def test_regular_satellite(self):
        self.assertEqual(_classify_tournament_category('Satellite to Sunday Major'), 'regular_satellite')

    def test_empty_name(self):
        self.assertEqual(_classify_tournament_category(''), 'regular_satellite')

    def test_none_name(self):
        self.assertEqual(_classify_tournament_category(None), 'regular_satellite')


# ── Unit Tests: Category Stats ───────────────────────────────────


class TestComputeCategoryStats(unittest.TestCase):
    """Test _compute_category_stats() computation."""

    def test_empty_list(self):
        result = _compute_category_stats([], 'Test')
        self.assertEqual(result['count'], 0)
        self.assertEqual(result['roi'], 0)
        self.assertEqual(result['category'], 'Test')

    def test_single_tournament(self):
        tournaments = [{
            'total_buy_in': 5.50,
            'entries': 1,
            'rake': 0.50,
            'prize': 10.00,
            'position': 1,
        }]
        result = _compute_category_stats(tournaments, 'Test')
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['total_invested'], 5.50)
        self.assertEqual(result['total_won'], 10.00)
        self.assertEqual(result['net'], 4.50)
        self.assertEqual(result['itm_count'], 1)
        self.assertEqual(result['win_count'], 1)
        self.assertEqual(result['win_rate'], 100.0)
        self.assertGreater(result['roi'], 0)

    def test_multiple_tournaments(self):
        tournaments = [
            {'total_buy_in': 5.50, 'entries': 1, 'rake': 0.50, 'prize': 10.00, 'position': 1},
            {'total_buy_in': 5.50, 'entries': 1, 'rake': 0.50, 'prize': 0.00, 'position': 3},
            {'total_buy_in': 5.50, 'entries': 1, 'rake': 0.50, 'prize': 0.00, 'position': 2},
        ]
        result = _compute_category_stats(tournaments, 'Spins')
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['total_invested'], 16.50)
        self.assertEqual(result['total_won'], 10.00)
        self.assertAlmostEqual(result['net'], -6.50, places=2)
        self.assertEqual(result['itm_count'], 1)
        self.assertAlmostEqual(result['itm_rate'], 33.3, places=1)
        self.assertEqual(result['win_count'], 1)
        self.assertAlmostEqual(result['avg_buy_in'], 5.50, places=2)

    def test_multi_entry_tournament(self):
        tournaments = [
            {'total_buy_in': 5.50, 'entries': 3, 'rake': 0.50, 'prize': 20.00, 'position': 2},
        ]
        result = _compute_category_stats(tournaments, 'Test')
        self.assertEqual(result['total_invested'], 16.50)  # 5.50 * 3
        self.assertEqual(result['total_rake'], 1.50)  # 0.50 * 3


# ── Unit Tests: SpinAnalyzer ─────────────────────────────────────


class TestSpinAnalyzerGetSatelliteAnalysis(unittest.TestCase):
    """Test SpinAnalyzer.get_satellite_analysis()."""

    def test_no_satellites(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100', name='MTT $5',
                           is_satellite=False, buy_in=5.0, rake=0.50)
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_satellite_analysis()
        self.assertEqual(result, {})

    def test_basic_satellite_analysis(self):
        conn, repo = _setup_db()
        # Add Spin & Gold satellite
        _insert_tournament(repo, tournament_id='SG1', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=10.00, position=1, date='2026-01-10')
        # Add WSOP Express
        _insert_tournament(repo, tournament_id='WE1', name='WSOP Express $10',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=25.00, position=5, date='2026-01-15')
        # Add another Spin (no prize)
        _insert_tournament(repo, tournament_id='SG2', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=0.00, position=3, date='2026-01-15')
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_satellite_analysis()

        # Summary
        self.assertIn('summary', result)
        self.assertEqual(result['summary']['count'], 3)
        self.assertGreater(result['summary']['total_won'], 0)

        # Categories
        self.assertIn('by_category', result)
        self.assertIn('spin_gold', result['by_category'])
        self.assertEqual(result['by_category']['spin_gold']['count'], 2)
        self.assertIn('wsop_express', result['by_category'])
        self.assertEqual(result['by_category']['wsop_express']['count'], 1)

        # Cycle
        self.assertIn('cycle', result)
        self.assertEqual(result['cycle']['spin_count'], 2)

        # Timeline
        self.assertIn('timeline', result)
        self.assertGreater(len(result['timeline']), 0)

        # Recent results
        self.assertIn('recent_results', result)
        self.assertEqual(len(result['recent_results']), 3)

    def test_timeline_cumulative(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='SG1', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=10.00, position=1, date='2026-01-10')
        _insert_tournament(repo, tournament_id='SG2', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=0.00, position=3, date='2026-01-15')
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_satellite_analysis()
        timeline = result['timeline']

        self.assertEqual(len(timeline), 2)
        # First day: net = 10 - 5.5 = 4.5
        self.assertAlmostEqual(timeline[0]['net'], 4.50, places=2)
        self.assertAlmostEqual(timeline[0]['cumulative'], 4.50, places=2)
        # Second day: net = 0 - 5.5 = -5.5
        self.assertAlmostEqual(timeline[1]['net'], -5.50, places=2)
        self.assertAlmostEqual(timeline[1]['cumulative'], -1.00, places=2)

    def test_recent_results_order(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='SG1', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=0.00, date='2026-01-10')
        _insert_tournament(repo, tournament_id='SG2', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=10.00, date='2026-01-20')
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_satellite_analysis()
        recent = result['recent_results']

        # Most recent first
        self.assertEqual(recent[0]['date'], '2026-01-20')
        self.assertEqual(recent[1]['date'], '2026-01-10')

    def test_recent_results_max_20(self):
        conn, repo = _setup_db()
        for i in range(25):
            day = f"2026-01-{i + 1:02d}"
            _insert_tournament(repo, tournament_id=f'SG{i}', name='Spin & Gold $5',
                               is_satellite=True, buy_in=5.0, rake=0.50,
                               prize=0.00, date=day)
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_satellite_analysis()
        self.assertEqual(len(result['recent_results']), 20)

    def test_category_labels(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='SG1', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50)
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_satellite_analysis()

        for r in result['recent_results']:
            self.assertEqual(r['category'], 'Spin & Gold')

    def test_cycle_with_spin_and_wsop(self):
        conn, repo = _setup_db()
        # 3 spins, 2 wins
        _insert_tournament(repo, tournament_id='SG1', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=10.00, position=1, date='2026-01-10')
        _insert_tournament(repo, tournament_id='SG2', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=10.00, position=1, date='2026-01-11')
        _insert_tournament(repo, tournament_id='SG3', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=0.00, position=3, date='2026-01-12')
        # 3 WSOP express
        _insert_tournament(repo, tournament_id='WE1', name='WSOP Express $10',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=50.00, position=5, date='2026-01-13')
        _insert_tournament(repo, tournament_id='WE2', name='WSOP Express $10',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=0.00, position=50, date='2026-01-14')
        _insert_tournament(repo, tournament_id='WE3', name='WSOP Express $10',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=0.00, position=30, date='2026-01-15')
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_satellite_analysis()
        cycle = result['cycle']

        self.assertEqual(cycle['spin_count'], 3)
        self.assertEqual(cycle['spin_wins'], 2)
        self.assertEqual(cycle['wsop_count'], 3)
        self.assertEqual(cycle['tickets_used'], 2)
        self.assertAlmostEqual(cycle['extra_cash'], 10.00, places=2)

    def test_summary_roi(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='SG1', name='Spin & Gold $5',
                           is_satellite=True, buy_in=10.0, rake=0.0,
                           prize=20.00, position=1, date='2026-01-10')
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_satellite_analysis()
        summary = result['summary']

        self.assertEqual(summary['total_invested'], 10.0)
        self.assertEqual(summary['total_won'], 20.0)
        self.assertEqual(summary['net'], 10.0)
        self.assertAlmostEqual(summary['roi'], 100.0, places=1)

    def test_regular_satellite_category(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='SAT1', name='Satellite to Main Event',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=22.00, position=1, date='2026-01-10')
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_satellite_analysis()

        self.assertIn('regular_satellite', result['by_category'])
        self.assertEqual(result['by_category']['regular_satellite']['count'], 1)


# ── Unit Tests: Original get_stats ───────────────────────────────


class TestSpinAnalyzerGetStats(unittest.TestCase):
    """Test backward compatibility of SpinAnalyzer.get_stats()."""

    def test_empty(self):
        conn, repo = _setup_db()
        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_stats()

        self.assertEqual(result['spin']['count'], 0)
        self.assertEqual(result['wsop']['count'], 0)
        self.assertEqual(result['cycle']['roi'], 0)

    def test_spin_stats(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='SG1', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=10.00, position=1)
        repo.conn.commit()

        analyzer = SpinAnalyzer(repo)
        result = analyzer.get_stats()
        self.assertEqual(result['spin']['count'], 1)
        self.assertEqual(result['spin']['wins'], 1)


# ── Web Data Layer Tests ─────────────────────────────────────────


class TestPrepareSatellitesData(unittest.TestCase):
    """Test prepare_satellites_data() enrichment."""

    def test_empty_data(self):
        data = {}
        result = prepare_satellites_data(data)
        self.assertNotIn('sat_summary', result)
        self.assertEqual(result.get('active_period'), 'year')

    def test_no_satellite_analysis(self):
        data = {'summary': {'total_hands': 100}}
        result = prepare_satellites_data(data)
        self.assertNotIn('sat_summary', result)

    def test_with_satellite_data(self):
        data = {
            'satellite_analysis': {
                'summary': {'count': 10, 'net': 50.0},
                'by_category': {'spin_gold': {'category': 'Spin & Gold', 'count': 5}},
                'cycle': {'spin_count': 5, 'spin_wins': 2},
                'timeline': [
                    {'date': '2026-01-10', 'cumulative': 10.0},
                    {'date': '2026-01-15', 'cumulative': 25.0},
                ],
                'recent_results': [
                    {'tournament_id': 'SG1', 'name': 'Spin & Gold', 'net': 5.0},
                ],
            },
        }
        result = prepare_satellites_data(data)

        self.assertEqual(result['sat_summary']['count'], 10)
        self.assertIn('spin_gold', result['sat_categories'])
        self.assertEqual(result['sat_cycle']['spin_count'], 5)
        self.assertEqual(len(result['sat_recent']), 1)

    def test_chart_built(self):
        data = {
            'satellite_analysis': {
                'summary': {'count': 5},
                'by_category': {},
                'cycle': {},
                'timeline': [
                    {'date': '2026-01-10', 'cumulative': 10.0},
                    {'date': '2026-01-15', 'cumulative': -5.0},
                ],
                'recent_results': [],
            },
        }
        result = prepare_satellites_data(data)
        chart = result.get('sat_chart', {})

        self.assertIn('points', chart)
        self.assertEqual(chart['y_min'], -5.0)
        self.assertEqual(chart['y_max'], 10.0)
        self.assertEqual(chart['final'], -5.0)
        self.assertEqual(len(chart['dates']), 2)

    def test_empty_timeline(self):
        data = {
            'satellite_analysis': {
                'summary': {'count': 0},
                'by_category': {},
                'cycle': {},
                'timeline': [],
                'recent_results': [],
            },
        }
        result = prepare_satellites_data(data)
        self.assertEqual(result['sat_chart'], {})
        self.assertEqual(result['sat_timeline'], [])

    def test_period_passed_through(self):
        data = {'satellite_analysis': {'summary': {'count': 1}, 'by_category': {},
                                        'cycle': {}, 'timeline': [], 'recent_results': []}}
        result = prepare_satellites_data(data, period='3m', from_date='2026-01-01', to_date='2026-03-31')
        self.assertEqual(result['active_period'], '3m')
        self.assertEqual(result['custom_from'], '2026-01-01')
        self.assertEqual(result['custom_to'], '2026-03-31')


# ── Web Route Tests ──────────────────────────────────────────────


class TestSatellitesRoute(unittest.TestCase):
    """Test the /tournament/satellites route."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db_with_satellites(self.db_path)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def test_satellites_route_200(self):
        resp = self.client.get('/tournament/satellites')
        self.assertEqual(resp.status_code, 200)

    def test_satellites_template_renders_summary(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('Satellites & Spin Analysis', html)
        self.assertIn('Total Satellites', html)
        self.assertIn('Net Profit', html)
        self.assertIn('ROI', html)

    def test_satellites_template_renders_category_breakdown(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('Breakdown by Category', html)
        self.assertIn('Spin &amp; Gold', html)
        self.assertIn('WSOP Express', html)

    def test_satellites_template_renders_cycle(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('Spin &amp; Gold', html)
        self.assertIn('Spins Played', html)
        self.assertIn('Tickets Won', html)
        self.assertIn('Cycle Net', html)

    def test_satellites_template_renders_chart(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('Satellite Profit Over Time', html)
        self.assertIn('<svg', html)
        self.assertIn('polyline', html)

    def test_satellites_template_renders_timeline(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('Daily Satellite Results', html)
        self.assertIn('2026-01-10', html)
        self.assertIn('Cumulative', html)

    def test_satellites_template_renders_recent(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('Recent Satellite Results', html)
        self.assertIn('Spin &amp; Gold $5', html)

    def test_satellites_in_valid_tabs(self):
        from src.web.routes.tournament import VALID_TABS
        self.assertIn('satellites', VALID_TABS)

    def test_satellites_tab_in_navigation(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('Satellites', html)


class TestSatellitesRouteEmpty(unittest.TestCase):
    """Test satellites route with no satellite data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        # Create analytics DB without satellite data
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        init_analytics_db(conn)
        conn.commit()
        conn.close()
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def test_empty_state_rendered(self):
        resp = self.client.get('/tournament/satellites')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('No satellite data available', html)
        self.assertIn('python main.py analyze', html)


# ── Integration: Analytics Pipeline ──────────────────────────────


class TestAnalyticsPipelineSatellites(unittest.TestCase):
    """Test that satellite analysis is persisted via analytics pipeline."""

    def test_satellite_analysis_persisted(self):
        """Verify satellite data flows from SpinAnalyzer through pipeline to analytics DB."""
        tmpdir = tempfile.mkdtemp()
        poker_path = os.path.join(tmpdir, 'poker.db')
        analytics_path = os.path.join(tmpdir, 'analytics.db')

        # Create source DB with satellite tournaments
        conn = sqlite3.connect(poker_path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        _insert_tournament(repo, tournament_id='SG1', name='Spin & Gold $5',
                           is_satellite=True, buy_in=5.0, rake=0.50,
                           prize=10.00, position=1, date='2026-01-10')
        _insert_tournament(repo, tournament_id='T100', name='MTT Regular',
                           is_satellite=False, buy_in=10.0, rake=1.0,
                           prize=0.0, date='2026-01-15')
        conn.commit()
        conn.close()

        # Run analysis
        from src.analytics_pipeline import run_analysis
        result = run_analysis(
            poker_db_path=poker_path,
            analytics_db_path=analytics_path,
            force=True,
            analysis_type='tournament',
            year='2026',
        )

        self.assertTrue(result['tournament_processed'])

        # Verify satellite_analysis was persisted
        aconn = sqlite3.connect(analytics_path)
        aconn.row_factory = sqlite3.Row
        row = aconn.execute(
            "SELECT stat_json FROM global_stats WHERE game_type='tournament' AND stat_name='satellite_analysis'"
        ).fetchone()
        aconn.close()

        self.assertIsNotNone(row)
        sat = json.loads(row['stat_json'])
        self.assertIn('summary', sat)
        self.assertEqual(sat['summary']['count'], 1)

    def test_no_satellites_no_data(self):
        """When no satellites exist, satellite_analysis should still not crash."""
        tmpdir = tempfile.mkdtemp()
        poker_path = os.path.join(tmpdir, 'poker.db')
        analytics_path = os.path.join(tmpdir, 'analytics.db')

        conn = sqlite3.connect(poker_path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        _insert_tournament(repo, tournament_id='T100', name='MTT Regular',
                           is_satellite=False, buy_in=10.0, rake=1.0,
                           prize=0.0, date='2026-01-15')
        conn.commit()
        conn.close()

        from src.analytics_pipeline import run_analysis
        result = run_analysis(
            poker_db_path=poker_path,
            analytics_db_path=analytics_path,
            force=True,
            analysis_type='tournament',
            year='2026',
        )

        self.assertTrue(result['tournament_processed'])

        # satellite_analysis should not exist (empty result = not persisted)
        aconn = sqlite3.connect(analytics_path)
        aconn.row_factory = sqlite3.Row
        row = aconn.execute(
            "SELECT stat_json FROM global_stats WHERE game_type='tournament' AND stat_name='satellite_analysis'"
        ).fetchone()
        aconn.close()
        self.assertIsNone(row)


# ── Load Analytics Tests ─────────────────────────────────────────


class TestLoadAnalyticsSatellites(unittest.TestCase):
    """Test that satellite data is loaded from analytics DB."""

    def test_satellite_analysis_loaded(self):
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, 'analytics.db')
        _create_analytics_db_with_satellites(db_path)

        data = load_analytics_data(db_path, 'tournament')
        self.assertIn('satellite_analysis', data)
        self.assertEqual(data['satellite_analysis']['summary']['count'], 15)

    def test_prepare_and_render(self):
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, 'analytics.db')
        _create_analytics_db_with_satellites(db_path)

        data = load_analytics_data(db_path, 'tournament')
        prepare_satellites_data(data)

        self.assertEqual(data['sat_summary']['count'], 15)
        self.assertIn('spin_gold', data['sat_categories'])
        self.assertGreater(len(data['sat_timeline']), 0)
        self.assertGreater(len(data['sat_recent']), 0)


# ── Template CSS/HTML Structure Tests ────────────────────────────


class TestSatellitesTemplateStructure(unittest.TestCase):
    """Verify key HTML structure elements in satellites template."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'analytics.db')
        _create_analytics_db_with_satellites(self.db_path)
        self.app = create_app(analytics_db_path=self.db_path)
        self.client = self.app.test_client()

    def test_stats_grid_present(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('stats-grid', html)

    def test_stat_cards_present(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('stat-card', html)
        self.assertIn('stat-value', html)

    def test_data_table_present(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('data-table', html)

    def test_chart_container_present(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('chart-container', html)

    def test_positive_negative_classes(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        # At least one positive or negative class should be present
        self.assertTrue('positive' in html or 'negative' in html)

    def test_table_responsive(self):
        resp = self.client.get('/tournament/satellites')
        html = resp.data.decode()
        self.assertIn('table-responsive', html)


# ── Category Labels Tests ────────────────────────────────────────


class TestCategoryLabels(unittest.TestCase):
    """Test _CATEGORY_LABELS dict."""

    def test_all_categories_have_labels(self):
        for key in ['spin_gold', 'wsop_express', 'regular_satellite']:
            self.assertIn(key, _CATEGORY_LABELS)

    def test_label_values(self):
        self.assertEqual(_CATEGORY_LABELS['spin_gold'], 'Spin & Gold')
        self.assertEqual(_CATEGORY_LABELS['wsop_express'], 'WSOP Express')
        self.assertEqual(_CATEGORY_LABELS['regular_satellite'], 'Other Satellites')


if __name__ == '__main__':
    unittest.main()
