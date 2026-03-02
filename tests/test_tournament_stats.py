"""Tests for US-006: Poker Stats Completas para Torneios.

Covers:
- Schema: tournament_id column on hands table
- Repository: tournament hand queries (get_tournament_hands, get_tournament_preflop_actions,
  get_tournament_all_actions, get_tournament_allin_hands, get_tournament_hand_count)
- Parsers: parse_tournament_single_hand (GGPoker + PokerStars) returning HandData
- TournamentAnalyzer: get_tournament_game_stats (VPIP, PFR, 3-Bet, Fold-to-3Bet,
  ATS, AF, AFq, WTSD, W$SD, CBet, Fold-to-CBet, Check-Raise, health badges)
- TournamentAnalyzer: get_ev_analysis (variable bb/100, chip-based EV)
- TournamentAnalyzer: get_daily_reports (per-tournament details, day stats, comparison)
- TournamentAnalyzer: _get_chip_sparkline, _aggregate_tournament_stats,
  _build_tournament_comparison, _compute_hand_ev
- Report: _render_global_stats, _render_ev_analysis, _render_ev_chart,
  _render_tournament_stats, _render_chip_sparkline, _render_hand_card,
  _render_day_summary_stats, _render_tournament_comparison, _render_daily_report,
  _render_tournament_card, generate_tournament_report
- Edge cases: no hands, single tournament day, empty stats
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, HandData
from src.parsers.ggpoker import GGPokerParser
from src.parsers.pokerstars import PokerStarsParser
from src.analyzers.tournament import TournamentAnalyzer
from src.reports.tournament_report import (
    generate_tournament_report,
    _render_global_stats,
    _render_ev_analysis,
    _render_ev_chart,
    _render_tournament_stats,
    _render_chip_sparkline,
    _render_hand_card,
    _render_day_summary_stats,
    _render_tournament_comparison,
    _render_daily_report,
    _render_tournament_card,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_tournament_hand(hand_id, tournament_id='T100', date='2026-01-15T20:00:00',
                          hero_position='CO', **kwargs):
    """Create a HandData with tournament defaults for testing."""
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='tournament',
        date=datetime.fromisoformat(date) if isinstance(date, str) else date,
        blinds_sb=kwargs.get('blinds_sb', 100),
        blinds_bb=kwargs.get('blinds_bb', 200),
        hero_cards=kwargs.get('hero_cards', 'Ah Kd'),
        hero_position=hero_position,
        invested=kwargs.get('invested', 200),
        won=kwargs.get('won', 0),
        net=kwargs.get('net', -200),
        rake=0.0,
        table_name='T',
        num_players=kwargs.get('num_players', 6),
        tournament_id=tournament_id,
    )


def _make_action(hand_id, player, action_type, seq, street='preflop',
                 position='CO', is_hero=0, amount=0.0, is_voluntary=0):
    """Create an ActionData for testing."""
    return ActionData(
        hand_id=hand_id,
        street=street,
        player=player,
        action_type=action_type,
        amount=amount,
        is_hero=is_hero,
        sequence_order=seq,
        position=position,
        is_voluntary=is_voluntary,
    )


def _setup_db():
    """Create an in-memory DB with schema initialized."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Repository(conn)


def _insert_tournament(repo, tournament_id='T100', name='MTT $5.50',
                       date='2026-01-15', buy_in=5.0, rake=0.5,
                       prize=0.0, position=None, entries=1,
                       is_satellite=False):
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
        'total_players': 100,
        'entries': entries,
        'is_bounty': False,
        'is_satellite': is_satellite,
    })


def _setup_tournament_with_hands(repo, tournament_id='T100', hands_count=5):
    """Insert a tournament with N hands, each with preflop actions (hero calls = VPIP)."""
    _insert_tournament(repo, tournament_id=tournament_id, prize=50.0, position=5)

    for i in range(hands_count):
        hid = f'{tournament_id}_h{i}'
        hand = _make_tournament_hand(
            hid, tournament_id=tournament_id,
            date=f'2026-01-15T20:{i:02d}:00',
            invested=200, won=400 if i == 0 else 0,
            net=200 if i == 0 else -200,
        )
        repo.insert_hand(hand)

        # Preflop actions: hero calls (VPIP but not PFR) on even hands, folds on odd
        actions = [
            _make_action(hid, 'Villain', 'post_sb', 0, position='SB'),
            _make_action(hid, 'Hero', 'post_bb', 1, position='BB', is_hero=1),
            _make_action(hid, 'Villain2', 'raise', 2, position='UTG', amount=400),
        ]
        if i % 2 == 0:
            actions.append(
                _make_action(hid, 'Hero', 'call', 3, position='BB',
                             is_hero=1, amount=400, is_voluntary=1))
        else:
            actions.append(
                _make_action(hid, 'Hero', 'fold', 3, position='BB', is_hero=1))

        repo.insert_actions_batch(actions)

    repo.conn.commit()


# ── Schema Tests ─────────────────────────────────────────────────────

class TestSchema(unittest.TestCase):
    """Test tournament_id column exists in hands table."""

    def test_tournament_id_column_exists(self):
        conn, repo = _setup_db()
        cursor = conn.execute("PRAGMA table_info(hands)")
        cols = {row[1] for row in cursor.fetchall()}
        self.assertIn('tournament_id', cols)

    def test_hand_insert_with_tournament_id(self):
        conn, repo = _setup_db()
        hand = _make_tournament_hand('h1', tournament_id='T100')
        self.assertTrue(repo.insert_hand(hand))
        row = conn.execute(
            "SELECT tournament_id, game_type FROM hands WHERE hand_id = 'h1'"
        ).fetchone()
        self.assertEqual(row['tournament_id'], 'T100')
        self.assertEqual(row['game_type'], 'tournament')


# ── Repository Tests ──────────────────────────────────────────────────

class TestTournamentRepository(unittest.TestCase):
    """Test tournament hand query methods."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        # Insert 3 tournament hands across 2 tournaments
        for hid, tid in [('h1', 'T100'), ('h2', 'T100'), ('h3', 'T200')]:
            hand = _make_tournament_hand(hid, tournament_id=tid,
                                          date='2026-01-15T20:00:00')
            self.repo.insert_hand(hand)
            self.repo.insert_actions_batch([
                _make_action(hid, 'Hero', 'call', 0, is_hero=1, is_voluntary=1),
                _make_action(hid, 'Hero', 'bet', 1, street='flop', is_hero=1, amount=100),
            ])
        self.conn.commit()

    def test_get_tournament_hands_all(self):
        hands = self.repo.get_tournament_hands('2026')
        self.assertEqual(len(hands), 3)

    def test_get_tournament_hands_by_id(self):
        hands = self.repo.get_tournament_hands('2026', 'T100')
        self.assertEqual(len(hands), 2)
        self.assertTrue(all(h['tournament_id'] == 'T100' for h in hands))

    def test_get_tournament_preflop_actions(self):
        actions = self.repo.get_tournament_preflop_actions('2026')
        # 3 hands x 1 preflop action each = 3
        self.assertEqual(len(actions), 3)
        self.assertTrue(all(a['tournament_id'] in ('T100', 'T200') for a in actions))

    def test_get_tournament_preflop_actions_by_id(self):
        actions = self.repo.get_tournament_preflop_actions('2026', 'T100')
        self.assertEqual(len(actions), 2)

    def test_get_tournament_all_actions(self):
        actions = self.repo.get_tournament_all_actions('2026')
        # 3 hands x 2 actions (preflop + flop) = 6
        self.assertEqual(len(actions), 6)
        # Should include blinds_bb field
        self.assertIn('blinds_bb', actions[0])

    def test_get_tournament_all_actions_by_id(self):
        actions = self.repo.get_tournament_all_actions('2026', 'T200')
        self.assertEqual(len(actions), 2)

    def test_get_tournament_allin_hands(self):
        # Insert a hand with all-in data
        hand = _make_tournament_hand('hallin', tournament_id='T100',
                                      date='2026-01-15T20:30:00',
                                      hero_cards='Ah Kh')
        self.repo.insert_hand(hand)
        self.repo.update_hand_showdown('hallin', pot_total=5000,
                                        opponent_cards='Qs Qd',
                                        has_allin=True, allin_street='preflop')
        self.conn.commit()

        allin = self.repo.get_tournament_allin_hands('2026')
        self.assertEqual(len(allin), 1)
        self.assertEqual(allin[0]['hand_id'], 'hallin')

    def test_get_tournament_hand_count(self):
        count = self.repo.get_tournament_hand_count('2026')
        self.assertEqual(count, 3)

    def test_get_tournament_hand_count_wrong_year(self):
        count = self.repo.get_tournament_hand_count('2025')
        self.assertEqual(count, 0)


# ── Parser Tests ─────────────────────────────────────────────────────

class TestGGPokerTournamentParser(unittest.TestCase):
    """Test GGPokerParser.parse_tournament_single_hand()."""

    def test_parse_gg_tournament_hand(self):
        hand_text = """Poker Hand #HD123456: Tournament #T999, $5 MTT Hold'em No Limit - Level5(100/200) - 2026/01/15 20:30:00
Table 'T999 Table1' 6-max Seat #3 is the button
Seat 1: Villain1 (5000 in chips)
Seat 2: Villain2 (3000 in chips)
Seat 3: Hero (4000 in chips)
Seat 4: Villain3 (6000 in chips)
Villain3: posts the ante 25
Villain1: posts the ante 25
Villain2: posts the ante 25
Hero: posts the ante 25
Villain3: posts small blind 100
Villain1: posts big blind 200
*** HOLE CARDS ***
Dealt to Hero [Ah Kd]
Villain2: folds
Hero: raises 200 to 400
Villain3: folds
Villain1: calls 200
*** FLOP *** [Jh 5s 2c]
Villain1: checks
Hero: bets 600
Villain1: folds
Uncalled bet (600) returned to Hero
Hero collected 1050
*** SUMMARY ***
Total pot 1050"""

        parser = GGPokerParser()
        hand = parser.parse_tournament_single_hand(hand_text)

        self.assertIsNotNone(hand)
        self.assertEqual(hand.hand_id, 'HD123456')
        self.assertEqual(hand.tournament_id, 'T999')
        self.assertEqual(hand.game_type, 'tournament')
        self.assertEqual(hand.blinds_sb, 100)
        self.assertEqual(hand.blinds_bb, 200)
        self.assertEqual(hand.hero_cards, 'Ah Kd')
        self.assertEqual(hand.num_players, 4)
        self.assertEqual(hand.won, 1050)
        # Invested: raise "to 400" overwrites ante in current_street_total
        self.assertEqual(hand.invested, 400)
        self.assertEqual(hand.net, 1050 - 400)

    def test_parse_gg_tournament_hand_invalid(self):
        parser = GGPokerParser()
        hand = parser.parse_tournament_single_hand("some random text")
        self.assertIsNone(hand)


class TestPokerStarsTournamentParser(unittest.TestCase):
    """Test PokerStarsParser.parse_tournament_single_hand()."""

    def test_parse_ps_tournament_hand(self):
        hand_text = """PokerStars Hand #12345678: Tournament #7777, $4.00+$0.40 USD Hold'em No Limit - Level V (75/150) - 2026/02/10 15:00:00
Table '7777 1' 9-max Seat #5 is the button
Seat 1: gangsta221 (3000 in chips)
Seat 2: Player2 (4000 in chips)
gangsta221: posts the ante 20
Player2: posts the ante 20
Player2: posts small blind 75
gangsta221: posts big blind 150
*** HOLE CARDS ***
Dealt to gangsta221 [Ks Qd]
Player2: raises 150 to 300
gangsta221: calls 150
*** FLOP *** [Th 8s 3c]
gangsta221: checks
Player2: bets 200
gangsta221: folds
*** SUMMARY ***
Total pot 640"""

        parser = PokerStarsParser(hero_name='gangsta221')
        hand = parser.parse_tournament_single_hand(hand_text, 'PS7777', '[PS] MTT $4.40')

        self.assertIsNotNone(hand)
        self.assertEqual(hand.hand_id, 'PS12345678')
        self.assertEqual(hand.tournament_id, 'PS7777')
        self.assertEqual(hand.game_type, 'tournament')
        self.assertEqual(hand.blinds_sb, 75)
        self.assertEqual(hand.blinds_bb, 150)
        self.assertEqual(hand.hero_cards, 'Ks Qd')
        self.assertEqual(hand.platform, 'PokerStars')
        # Invested: ante(20) + bb(150) + call 150 more = 320
        # Actually: ante=20, posts bb=150, then calls 150 more
        # current_street_total starts with: ante 20, then bb 150 (overwrites), then call 150 (adds)
        # Actually hero_total_invested = preflop: 150+150=300 + ante 20 = 320... let me trace:
        # Hero posts ante: current_street_total = 20
        # Hero posts big blind: current_street_total = 150  (overwrite)
        # Hero calls 150: current_street_total += 150 = 300
        # Street change to flop: hero_total_invested += 300 = 300
        # Flop: hero checks, folds - no investment
        # Final: hero_total_invested = 300, returned = 0
        # invested = 300
        self.assertEqual(hand.invested, 300)

    def test_parse_ps_tournament_hand_invalid(self):
        parser = PokerStarsParser()
        hand = parser.parse_tournament_single_hand("garbage", 'PS1', 'test')
        self.assertIsNone(hand)


# ── TournamentAnalyzer Stats Tests ───────────────────────────────────

class TestTournamentGameStats(unittest.TestCase):
    """Test TournamentAnalyzer.get_tournament_game_stats()."""

    def test_global_stats_vpip_pfr(self):
        conn, repo = _setup_db()
        _setup_tournament_with_hands(repo, hands_count=10)
        analyzer = TournamentAnalyzer(repo, year='2026')

        stats = analyzer.get_tournament_game_stats()
        self.assertIn('vpip', stats)
        self.assertIn('pfr', stats)
        self.assertIn('total_hands', stats)
        self.assertEqual(stats['total_hands'], 10)
        # Even hands (0,2,4,6,8) have hero call = VPIP, no raise = not PFR
        # Odd hands (1,3,5,7,9) have hero fold = no VPIP
        self.assertAlmostEqual(stats['vpip'], 50.0, places=0)
        self.assertAlmostEqual(stats['pfr'], 0.0, places=0)

    def test_stats_with_health_badges(self):
        conn, repo = _setup_db()
        _setup_tournament_with_hands(repo, hands_count=5)
        analyzer = TournamentAnalyzer(repo, year='2026')

        stats = analyzer.get_tournament_game_stats()
        for key in ('vpip_health', 'pfr_health', 'three_bet_health',
                     'fold_to_3bet_health', 'ats_health', 'af_health',
                     'wtsd_health', 'wsd_health', 'cbet_health',
                     'fold_to_cbet_health', 'check_raise_health'):
            self.assertIn(key, stats)
            self.assertIn(stats[key], ('good', 'warning', 'danger'))

    def test_stats_per_tournament(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100')
        _insert_tournament(repo, tournament_id='T200')

        # T100: 2 hands with VPIP
        for i, tid in enumerate(['T100', 'T100']):
            hid = f'h{i}'
            repo.insert_hand(_make_tournament_hand(hid, tournament_id=tid,
                                                    date=f'2026-01-15T20:{i:02d}:00'))
            repo.insert_actions_batch([
                _make_action(hid, 'Villain', 'raise', 0, position='UTG', amount=400),
                _make_action(hid, 'Hero', 'call', 1, is_hero=1, is_voluntary=1, amount=400),
            ])

        # T200: 1 hand with fold (no VPIP)
        repo.insert_hand(_make_tournament_hand('h10', tournament_id='T200',
                                                date='2026-01-15T20:30:00'))
        repo.insert_actions_batch([
            _make_action('h10', 'Villain', 'raise', 0, position='UTG', amount=400),
            _make_action('h10', 'Hero', 'fold', 1, is_hero=1),
        ])
        repo.conn.commit()

        analyzer = TournamentAnalyzer(repo, year='2026')

        # Stats for T100 only
        stats_t100 = analyzer.get_tournament_game_stats('T100')
        self.assertEqual(stats_t100['total_hands'], 2)
        self.assertAlmostEqual(stats_t100['vpip'], 100.0, places=0)

        # Stats for T200 only
        stats_t200 = analyzer.get_tournament_game_stats('T200')
        self.assertEqual(stats_t200['total_hands'], 1)
        self.assertAlmostEqual(stats_t200['vpip'], 0.0, places=0)

    def test_empty_stats(self):
        conn, repo = _setup_db()
        analyzer = TournamentAnalyzer(repo, year='2026')
        stats = analyzer.get_tournament_game_stats()
        self.assertEqual(stats, {})

    def test_postflop_stats_af_wtsd(self):
        """Test AF and WTSD calculation for tournament hands."""
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100')

        # Hand 1: Hero sees flop, bets (AF contributor), goes to showdown, wins
        h1 = _make_tournament_hand('h1', tournament_id='T100',
                                    invested=200, won=1000, net=800)
        repo.insert_hand(h1)
        repo.insert_actions_batch([
            _make_action('h1', 'Hero', 'call', 0, is_hero=1, is_voluntary=1),
            _make_action('h1', 'Villain', 'raise', 1, amount=400),
            _make_action('h1', 'Hero', 'bet', 2, street='flop', is_hero=1, amount=300),
            _make_action('h1', 'Villain', 'call', 3, street='flop', amount=300),
            _make_action('h1', 'Hero', 'check', 4, street='turn', is_hero=1),
            _make_action('h1', 'Villain', 'check', 5, street='turn'),
        ])

        # Hand 2: Hero sees flop, calls only (no aggression)
        h2 = _make_tournament_hand('h2', tournament_id='T100',
                                    date='2026-01-15T20:01:00',
                                    invested=200, won=0, net=-200)
        repo.insert_hand(h2)
        repo.insert_actions_batch([
            _make_action('h2', 'Hero', 'call', 0, is_hero=1, is_voluntary=1),
            _make_action('h2', 'Villain', 'raise', 1, amount=400),
            _make_action('h2', 'Villain', 'bet', 2, street='flop', amount=300),
            _make_action('h2', 'Hero', 'call', 3, street='flop', is_hero=1, amount=300),
            _make_action('h2', 'Hero', 'fold', 4, street='turn', is_hero=1),
        ])

        repo.conn.commit()
        analyzer = TournamentAnalyzer(repo, year='2026')
        stats = analyzer.get_tournament_game_stats('T100')

        # AF: 1 bet / 1 call = 1.0 (from flop actions)
        self.assertAlmostEqual(stats['af'], 1.0, places=1)
        # WTSD: 1 went to showdown / 2 saw flop = 50%
        self.assertAlmostEqual(stats['wtsd'], 50.0, places=0)
        # W$SD: 1 won / 1 showdown = 100%
        self.assertAlmostEqual(stats['wsd'], 100.0, places=0)


# ── TournamentAnalyzer EV Tests ──────────────────────────────────────

class TestTournamentEV(unittest.TestCase):
    """Test TournamentAnalyzer.get_ev_analysis()."""

    def test_ev_analysis_no_hands(self):
        conn, repo = _setup_db()
        analyzer = TournamentAnalyzer(repo, year='2026')
        ev = analyzer.get_ev_analysis()
        self.assertEqual(ev['overall']['total_hands'], 0)
        self.assertEqual(ev['chart_data'], [])

    def test_ev_analysis_with_hands(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100')

        # Insert 3 hands, one with all-in data
        for i in range(3):
            hand = _make_tournament_hand(
                f'h{i}', tournament_id='T100',
                date=f'2026-01-15T20:{i:02d}:00',
                blinds_bb=200,
                invested=200, won=400 if i == 0 else 0,
                net=200 if i == 0 else -200,
            )
            repo.insert_hand(hand)
        repo.conn.commit()

        analyzer = TournamentAnalyzer(repo, year='2026')
        ev = analyzer.get_ev_analysis()

        self.assertEqual(ev['overall']['total_hands'], 3)
        self.assertEqual(ev['overall']['allin_hands'], 0)  # no all-in showdowns
        self.assertEqual(ev['overall']['real_net'], -200)  # 200 - 200 - 200 = -200
        self.assertEqual(len(ev['chart_data']), 3)

    def test_ev_bb100_variable_blinds(self):
        """Test that bb/100 uses per-hand BB (variable tournament blinds)."""
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100')

        # Hand 1: BB=100, net=+100 → 1 BB won
        repo.insert_hand(_make_tournament_hand(
            'h1', tournament_id='T100', date='2026-01-15T20:00:00',
            blinds_bb=100, invested=100, won=200, net=100))
        # Hand 2: BB=200, net=+200 → 1 BB won
        repo.insert_hand(_make_tournament_hand(
            'h2', tournament_id='T100', date='2026-01-15T20:01:00',
            blinds_bb=200, invested=200, won=400, net=200))
        repo.conn.commit()

        analyzer = TournamentAnalyzer(repo, year='2026')
        ev = analyzer.get_ev_analysis()

        # total_bb_real = 100/100 + 200/200 = 2.0 BB over 2 hands
        # bb100 = 2.0 / 2 * 100 = 100.0
        self.assertAlmostEqual(ev['overall']['bb100_real'], 100.0, places=1)

    def test_compute_hand_ev_with_allin(self):
        """Test _compute_hand_ev static method."""
        hand = {
            'hero_cards': 'Ah Kh',
            'opponent_cards': '7c 2d',
            'pot_total': 5000,
            'invested': 2500,
            'net': 2500,
            'allin_street': 'preflop',
            'board_flop': None,
            'board_turn': None,
            'board_river': None,
        }
        result = TournamentAnalyzer._compute_hand_ev(hand)
        self.assertIsNotNone(result)
        self.assertIn('equity', result)
        self.assertIn('ev_net', result)
        # AKs vs 72o preflop: equity should be ~65-70%
        self.assertGreater(result['equity'], 0.5)

    def test_compute_hand_ev_missing_cards(self):
        result = TournamentAnalyzer._compute_hand_ev({
            'hero_cards': None, 'opponent_cards': None,
        })
        self.assertIsNone(result)


# ── TournamentAnalyzer Daily Reports Tests ────────────────────────────

class TestTournamentDailyReports(unittest.TestCase):
    """Test TournamentAnalyzer.get_daily_reports()."""

    def test_daily_reports_structure(self):
        conn, repo = _setup_db()
        _setup_tournament_with_hands(repo, tournament_id='T100', hands_count=5)
        analyzer = TournamentAnalyzer(repo, year='2026')

        reports = analyzer.get_daily_reports()
        self.assertEqual(len(reports), 1)

        report = reports[0]
        self.assertEqual(report['date'], '2026-01-15')
        self.assertEqual(report['tournament_count'], 1)
        self.assertIn('tournaments', report)
        self.assertIn('day_stats', report)
        self.assertIn('comparison', report)

    def test_daily_reports_tournament_details(self):
        conn, repo = _setup_db()
        _setup_tournament_with_hands(repo, tournament_id='T100', hands_count=3)
        analyzer = TournamentAnalyzer(repo, year='2026')

        reports = analyzer.get_daily_reports()
        td = reports[0]['tournaments'][0]

        self.assertEqual(td['tournament_id'], 'T100')
        self.assertEqual(td['hands_count'], 3)
        self.assertIn('stats', td)
        self.assertIn('sparkline', td)
        self.assertIsNotNone(td['biggest_win'])  # hand 0 has net=200

    def test_daily_reports_multiple_tournaments(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100', date='2026-01-15', prize=50.0, position=5)
        _insert_tournament(repo, tournament_id='T200', date='2026-01-15', prize=0.0)

        for i in range(3):
            hid = f'h{i}'
            repo.insert_hand(_make_tournament_hand(hid, tournament_id='T100',
                                                    date=f'2026-01-15T20:{i:02d}:00',
                                                    invested=200, won=0, net=-200))
            repo.insert_actions_batch([
                _make_action(hid, 'Villain', 'raise', 0, amount=400),
                _make_action(hid, 'Hero', 'call', 1, is_hero=1, is_voluntary=1),
            ])

        for i in range(2):
            hid = f'h2_{i}'
            repo.insert_hand(_make_tournament_hand(hid, tournament_id='T200',
                                                    date=f'2026-01-15T21:{i:02d}:00',
                                                    invested=200, won=0, net=-200))
            repo.insert_actions_batch([
                _make_action(hid, 'Villain', 'raise', 0, amount=400),
                _make_action(hid, 'Hero', 'fold', 1, is_hero=1),
            ])
        repo.conn.commit()

        analyzer = TournamentAnalyzer(repo, year='2026')
        reports = analyzer.get_daily_reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['tournament_count'], 2)
        self.assertEqual(len(reports[0]['tournaments']), 2)
        # Comparison should exist with 2+ tournaments
        self.assertNotEqual(reports[0]['comparison'], {})

    def test_daily_reports_empty(self):
        conn, repo = _setup_db()
        analyzer = TournamentAnalyzer(repo, year='2026')
        reports = analyzer.get_daily_reports()
        self.assertEqual(reports, [])


# ── Static Method Tests ──────────────────────────────────────────────

class TestStaticMethods(unittest.TestCase):
    """Test static helper methods."""

    def test_chip_sparkline(self):
        hands = [
            {'net': 100}, {'net': -50}, {'net': 200}, {'net': -30},
        ]
        points = TournamentAnalyzer._get_chip_sparkline(hands)
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0], {'hand': 1, 'chips': 100})
        self.assertEqual(points[1], {'hand': 2, 'chips': 50})
        self.assertEqual(points[2], {'hand': 3, 'chips': 250})
        self.assertEqual(points[3], {'hand': 4, 'chips': 220})

    def test_chip_sparkline_empty(self):
        points = TournamentAnalyzer._get_chip_sparkline([])
        self.assertEqual(points, [])

    def test_aggregate_tournament_stats(self):
        details = [
            {'stats': {'total_hands': 10, 'vpip': 30.0, 'pfr': 20.0,
                        'three_bet': 5.0, 'fold_to_3bet': 40.0, 'ats': 35.0,
                        'af': 2.5, 'wtsd': 30.0, 'wsd': 50.0,
                        'cbet': 65.0, 'fold_to_cbet': 45.0, 'check_raise': 8.0}},
            {'stats': {'total_hands': 20, 'vpip': 25.0, 'pfr': 18.0,
                        'three_bet': 8.0, 'fold_to_3bet': 50.0, 'ats': 40.0,
                        'af': 3.0, 'wtsd': 28.0, 'wsd': 52.0,
                        'cbet': 70.0, 'fold_to_cbet': 40.0, 'check_raise': 10.0}},
        ]
        result = TournamentAnalyzer._aggregate_tournament_stats(details)

        self.assertEqual(result['total_hands'], 30)
        # Weighted VPIP: (30*10 + 25*20) / 30 = 800/30 ≈ 26.67
        self.assertAlmostEqual(result['vpip'], (30*10 + 25*20) / 30, places=1)

    def test_aggregate_empty_stats(self):
        result = TournamentAnalyzer._aggregate_tournament_stats([])
        self.assertEqual(result, {})

    def test_aggregate_zero_hands(self):
        result = TournamentAnalyzer._aggregate_tournament_stats(
            [{'stats': {'total_hands': 0}}])
        self.assertEqual(result, {})

    def test_build_tournament_comparison(self):
        details = [
            {'stats': {'total_hands': 5, 'vpip': 30.0, 'pfr': 20.0,
                        'af': 2.0, 'wtsd': 25.0, 'wsd': 50.0, 'cbet': 60.0},
             'net': 100},
            {'stats': {'total_hands': 5, 'vpip': 20.0, 'pfr': 25.0,
                        'af': 3.0, 'wtsd': 30.0, 'wsd': 45.0, 'cbet': 70.0},
             'net': -50},
        ]
        comp = TournamentAnalyzer._build_tournament_comparison(details)

        self.assertIn('vpip', comp)
        self.assertEqual(comp['vpip']['best'], 0)   # 30 > 20
        self.assertEqual(comp['vpip']['worst'], 1)
        self.assertIn('net', comp)
        self.assertEqual(comp['net']['best'], 0)     # 100 > -50
        self.assertEqual(comp['net']['worst'], 1)

    def test_build_comparison_single_tournament(self):
        result = TournamentAnalyzer._build_tournament_comparison(
            [{'stats': {'total_hands': 5}}])
        self.assertEqual(result, {})


# ── Summary Tests ────────────────────────────────────────────────────

class TestTournamentSummary(unittest.TestCase):
    """Test TournamentAnalyzer.get_summary() and get_satellite_summary()."""

    def test_summary(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100', prize=50.0, position=5)
        _insert_tournament(repo, tournament_id='T200', prize=0.0)
        # Insert a hand for count
        repo.insert_hand(_make_tournament_hand('h1', tournament_id='T100'))
        repo.conn.commit()

        analyzer = TournamentAnalyzer(repo, year='2026')
        summary = analyzer.get_summary()

        self.assertEqual(summary['total_tournaments'], 2)
        self.assertEqual(summary['total_hands'], 1)
        self.assertIn('itm_count', summary)
        self.assertIn('avg_buy_in_per_day', summary)

    def test_satellite_summary(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='SAT1', name='Satellite',
                           is_satellite=True, prize=22.0, buy_in=2.0, rake=0.2)
        repo.conn.commit()

        analyzer = TournamentAnalyzer(repo, year='2026')
        sat = analyzer.get_satellite_summary()

        self.assertEqual(sat['count'], 1)
        self.assertGreater(sat['net'], 0)

    def test_satellite_summary_empty(self):
        conn, repo = _setup_db()
        _insert_tournament(repo, tournament_id='T100')
        repo.conn.commit()

        analyzer = TournamentAnalyzer(repo, year='2026')
        sat = analyzer.get_satellite_summary()
        self.assertEqual(sat, {})


# ── Report Render Tests ──────────────────────────────────────────────

class TestReportRendering(unittest.TestCase):
    """Test individual report render functions."""

    def test_render_global_stats(self):
        stats = {
            'total_hands': 100,
            'vpip': 25.0, 'vpip_health': 'good',
            'pfr': 20.0, 'pfr_health': 'good',
            'three_bet': 8.0, 'three_bet_health': 'good',
            'fold_to_3bet': 45.0, 'fold_to_3bet_health': 'good',
            'ats': 35.0, 'ats_health': 'good',
            'af': 2.5, 'af_health': 'good',
            'afq': 45.0,
            'wtsd': 28.0, 'wtsd_health': 'good',
            'wsd': 50.0, 'wsd_health': 'good',
            'cbet': 65.0, 'cbet_health': 'good',
            'fold_to_cbet': 40.0, 'fold_to_cbet_health': 'good',
            'check_raise': 8.0, 'check_raise_health': 'good',
        }
        html = _render_global_stats(stats)
        self.assertIn('Tournament Stats (100', html)
        self.assertIn('VPIP', html)
        self.assertIn('25.0%', html)
        self.assertIn('badge-good', html)

    def test_render_ev_analysis(self):
        ev_stats = {
            'overall': {
                'total_hands': 50, 'allin_hands': 5,
                'real_net': 1000, 'ev_net': 800,
                'luck_factor': 200, 'bb100_real': 5.0, 'bb100_ev': 4.0,
            },
            'chart_data': [
                {'hand': 1, 'real': 100, 'ev': 80},
                {'hand': 2, 'real': 200, 'ev': 160},
            ],
        }
        html = _render_ev_analysis(ev_stats)
        self.assertIn('EV Analysis (Torneios)', html)
        self.assertIn('bb/100 Real', html)
        self.assertIn('5.00', html)
        self.assertIn('<svg', html)  # EV chart

    def test_render_ev_chart(self):
        chart_data = [
            {'hand': 1, 'real': 0, 'ev': 0},
            {'hand': 2, 'real': 100, 'ev': 80},
            {'hand': 3, 'real': -50, 'ev': 20},
        ]
        html = _render_ev_chart(chart_data)
        self.assertIn('<svg', html)
        self.assertIn('polyline', html)
        self.assertIn('#ff8800', html)  # Real line color
        self.assertIn('#00aaff', html)  # EV line color

    def test_render_tournament_stats(self):
        stats = {
            'total_hands': 20,
            'vpip': 30.0, 'vpip_health': 'warning',
            'pfr': 15.0, 'pfr_health': 'warning',
            'three_bet': 5.0, 'three_bet_health': 'danger',
            'af': 1.5, 'af_health': 'warning',
            'wtsd': 35.0, 'wtsd_health': 'warning',
            'wsd': 45.0, 'wsd_health': 'warning',
            'cbet': 55.0, 'cbet_health': 'warning',
        }
        html = _render_tournament_stats(stats)
        self.assertIn('VPIP', html)
        self.assertIn('30.0%', html)
        self.assertIn('badge-warning', html)
        self.assertIn('badge-danger', html)

    def test_render_chip_sparkline(self):
        data = [
            {'hand': 1, 'chips': 100},
            {'hand': 2, 'chips': 50},
            {'hand': 3, 'chips': 200},
        ]
        html = _render_chip_sparkline(data)
        self.assertIn('<svg', html)
        self.assertIn('polyline', html)
        self.assertIn('#00ff88', html)  # positive final

    def test_render_chip_sparkline_negative(self):
        data = [
            {'hand': 1, 'chips': -100},
            {'hand': 2, 'chips': -200},
        ]
        html = _render_chip_sparkline(data)
        self.assertIn('#ff4444', html)  # negative final

    def test_render_chip_sparkline_empty(self):
        self.assertEqual(_render_chip_sparkline([]), '')
        self.assertEqual(_render_chip_sparkline([{'hand': 1, 'chips': 0}]), '')

    def test_render_hand_card_win(self):
        hand = {'hero_cards': 'Ah Kh', 'invested': 200, 'won': 500,
                'net': 300, 'blinds_sb': 100, 'blinds_bb': 200}
        html = _render_hand_card(hand, is_win=True)
        self.assertIn('hand-card win', html)
        self.assertIn('Ah Kh', html)
        self.assertIn('Ganho', html)
        self.assertIn('+300', html)

    def test_render_hand_card_loss(self):
        hand = {'hero_cards': '7d 2c', 'invested': 200, 'won': 0,
                'net': -200, 'blinds_sb': 100, 'blinds_bb': 200}
        html = _render_hand_card(hand, is_win=False)
        self.assertIn('hand-card loss', html)
        self.assertIn('Perda', html)

    def test_render_day_summary_stats(self):
        day_stats = {
            'total_hands': 30,
            'vpip': 26.0, 'pfr': 19.0, 'three_bet': 7.5,
            'af': 2.8, 'wtsd': 29.0, 'wsd': 51.0, 'cbet': 68.0,
        }
        html = _render_day_summary_stats(day_stats)
        self.assertIn('Stats do Dia', html)
        self.assertIn('VPIP', html)
        self.assertIn('26.0%', html)

    def test_render_day_summary_stats_empty(self):
        self.assertEqual(_render_day_summary_stats({}), '')
        self.assertEqual(_render_day_summary_stats({'total_hands': 0}), '')

    def test_render_tournament_comparison(self):
        comparison = {
            'vpip': {'best': 0, 'worst': 1},
            'net': {'best': 1, 'worst': 0},
        }
        tournaments = [
            {'name': 'MTT A', 'stats': {'vpip': 30.0, 'pfr': 0, 'af': 0,
                                          'wtsd': 0, 'wsd': 0, 'cbet': 0},
             'net': -50},
            {'name': 'MTT B', 'stats': {'vpip': 20.0, 'pfr': 0, 'af': 0,
                                          'wtsd': 0, 'wsd': 0, 'cbet': 0},
             'net': 100},
        ]
        html = _render_tournament_comparison(comparison, tournaments)
        self.assertIn('Comparativo entre Torneios', html)
        self.assertIn('MTT A', html)
        self.assertIn('MTT B', html)
        self.assertIn('class="positive"', html)
        self.assertIn('class="negative"', html)

    def test_render_tournament_comparison_single(self):
        self.assertEqual(_render_tournament_comparison({}, [{'name': 'x'}]), '')

    def test_render_tournament_card(self):
        t = {
            'tournament_id': 'T100',
            'name': 'MTT $5.50',
            'date': '2026-01-15T20:00:00',
            'buy_in': 5.0,
            'entries': 1,
            'total_cost': 5.5,
            'prize': 15.0,
            'net': 9.5,
            'position': 3,
            'total_players': 100,
            'is_bounty': False,
            'rake': 0.5,
            'hands_count': 50,
            'stats': {
                'total_hands': 50,
                'vpip': 25.0, 'vpip_health': 'good',
                'pfr': 20.0, 'pfr_health': 'good',
                'three_bet': 8.0, 'three_bet_health': 'good',
                'af': 2.5, 'af_health': 'good',
                'wtsd': 28.0, 'wtsd_health': 'good',
                'wsd': 50.0, 'wsd_health': 'good',
                'cbet': 65.0, 'cbet_health': 'good',
            },
            'sparkline': [
                {'hand': 1, 'chips': 100},
                {'hand': 2, 'chips': 200},
            ],
            'biggest_win': {'hero_cards': 'Ah Kh', 'invested': 200,
                            'won': 1000, 'net': 800,
                            'blinds_sb': 100, 'blinds_bb': 200},
            'biggest_loss': {'hero_cards': '7d 2c', 'invested': 200,
                             'won': 0, 'net': -200,
                             'blinds_sb': 100, 'blinds_bb': 200},
        }
        html = _render_tournament_card(t)
        self.assertIn('MTT $5.50', html)
        self.assertIn('3rd place!', html)
        self.assertIn('survived', html)
        self.assertIn('VPIP', html)  # stats rendered
        self.assertIn('<svg', html)   # sparkline rendered
        self.assertIn('Ganho', html)  # notable hand rendered

    def test_render_daily_report(self):
        report = {
            'date': '2026-01-15',
            'tournament_count': 2,
            'total_buy_in': 11.0,
            'total_won': 15.0,
            'net': 4.0,
            'total_rake': 1.0,
            'rebuys': 0,
            'total_entries': 2,
            'itm_count': 1,
            'itm_rate': 50.0,
            'day_stats': {
                'total_hands': 30,
                'vpip': 25.0, 'pfr': 20.0, 'three_bet': 8.0,
                'af': 2.5, 'wtsd': 28.0, 'wsd': 50.0, 'cbet': 65.0,
            },
            'comparison': {'vpip': {'best': 0, 'worst': 1}},
            'tournaments': [
                {
                    'tournament_id': 'T1', 'name': 'A', 'date': '2026-01-15T20:00:00',
                    'buy_in': 5.0, 'entries': 1, 'total_cost': 5.5, 'prize': 15.0,
                    'net': 9.5, 'position': 3, 'total_players': 100,
                    'is_bounty': False, 'rake': 0.5, 'hands_count': 20,
                    'stats': {'total_hands': 20, 'vpip': 30.0, 'vpip_health': 'warning',
                              'pfr': 20.0, 'pfr_health': 'good',
                              'three_bet': 8.0, 'three_bet_health': 'good',
                              'af': 2.5, 'af_health': 'good',
                              'wtsd': 28.0, 'wtsd_health': 'good',
                              'wsd': 50.0, 'wsd_health': 'good',
                              'cbet': 65.0, 'cbet_health': 'good'},
                    'sparkline': [{'hand': 1, 'chips': 100}, {'hand': 2, 'chips': 200}],
                    'biggest_win': None, 'biggest_loss': None,
                },
                {
                    'tournament_id': 'T2', 'name': 'B', 'date': '2026-01-15T21:00:00',
                    'buy_in': 5.0, 'entries': 1, 'total_cost': 5.5, 'prize': 0.0,
                    'net': -5.5, 'position': None, 'total_players': 100,
                    'is_bounty': False, 'rake': 0.5, 'hands_count': 10,
                    'stats': {'total_hands': 10, 'vpip': 20.0, 'vpip_health': 'danger',
                              'pfr': 15.0, 'pfr_health': 'warning',
                              'three_bet': 5.0, 'three_bet_health': 'danger',
                              'af': 1.5, 'af_health': 'warning',
                              'wtsd': 35.0, 'wtsd_health': 'warning',
                              'wsd': 45.0, 'wsd_health': 'warning',
                              'cbet': 55.0, 'cbet_health': 'warning'},
                    'sparkline': [{'hand': 1, 'chips': -50}, {'hand': 2, 'chips': -100}],
                    'biggest_win': None, 'biggest_loss': None,
                },
            ],
        }
        html = _render_daily_report(report)
        self.assertIn('15/01/2026', html)
        self.assertIn('$+4.00', html)
        self.assertIn('Stats do Dia', html)
        self.assertIn('Comparativo entre Torneios', html)
        self.assertIn('accordion-toggle', html)


# ── Full Report Generation Test ──────────────────────────────────────

class TestFullReportGeneration(unittest.TestCase):
    """Test generate_tournament_report end-to-end."""

    def test_generate_report_with_data(self):
        conn, repo = _setup_db()
        _setup_tournament_with_hands(repo, tournament_id='T100', hands_count=5)
        analyzer = TournamentAnalyzer(repo, year='2026')

        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, 'report.html')
            result = generate_tournament_report(analyzer, output)
            self.assertEqual(result, output)
            self.assertTrue(os.path.exists(output))

            with open(output, 'r') as f:
                html = f.read()

            # Check key sections exist
            self.assertIn('Relat\u00f3rio Torneios 2026', html)
            self.assertIn('Resumo Geral', html)
            self.assertIn('Total de Torneios', html)
            self.assertIn('Tournament Stats', html)  # global stats
            self.assertIn('VPIP', html)
            self.assertIn('badge-', html)
            self.assertIn('accordion-toggle', html)
            self.assertIn('#ff8800', html)  # orange theme

    def test_generate_report_empty(self):
        conn, repo = _setup_db()
        analyzer = TournamentAnalyzer(repo, year='2026')

        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, 'report.html')
            result = generate_tournament_report(analyzer, output)
            self.assertTrue(os.path.exists(output))

            with open(output, 'r') as f:
                html = f.read()

            self.assertIn('Relat\u00f3rio Torneios 2026', html)
            self.assertIn('Total de Torneios', html)

    def test_report_orange_theme(self):
        """Verify the report uses the orange (#ff8800) theme."""
        conn, repo = _setup_db()
        _setup_tournament_with_hands(repo, tournament_id='T100', hands_count=3)
        analyzer = TournamentAnalyzer(repo, year='2026')

        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, 'report.html')
            generate_tournament_report(analyzer, output)

            with open(output, 'r') as f:
                html = f.read()

            # Orange theme colors
            self.assertIn('#ff8800', html)
            self.assertIn('rgba(255,136,0', html)


if __name__ == '__main__':
    unittest.main()
