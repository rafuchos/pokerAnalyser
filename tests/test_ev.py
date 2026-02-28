"""Tests for US-004: EV Analysis & All-In Equity.

Covers:
- Card parsing (parse_card, parse_cards)
- Hand evaluation (_eval_five, evaluate_hand)
- Equity calculation (calculate_equity, _evaluate_showdown)
- EVAnalyzer: get_ev_analysis(), _compute_hand_ev(), _get_board_at_allin()
- Parser: parse_showdown_data()
- Repository: get_allin_hands(), update_hand_showdown()
- Report rendering: _render_ev_analysis(), _render_ev_chart()
- Integration: full pipeline from hand text to EV stats
- Edge cases (no all-in, no showdown, multi-way pots, etc.)
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import HandData
from src.analyzers.ev import (
    EVAnalyzer, RANK_MAP, parse_card, parse_cards,
    evaluate_hand, _eval_five, calculate_equity, _evaluate_showdown,
)
from src.parsers.ggpoker import GGPokerParser


# ── Helpers ──────────────────────────────────────────────────────────

def _make_hand(hand_id, date='2026-01-15', hero_position='CO', **kwargs):
    """Create a HandData with sensible defaults for testing."""
    return HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type='cash',
        date=datetime.fromisoformat(f'{date}T20:00:00') if isinstance(date, str) else date,
        blinds_sb=kwargs.get('blinds_sb', 0.25),
        blinds_bb=kwargs.get('blinds_bb', 0.50),
        hero_cards=kwargs.get('hero_cards', 'Ah Kd'),
        hero_position=hero_position,
        invested=kwargs.get('invested', 1.0),
        won=kwargs.get('won', 0.0),
        net=kwargs.get('net', -1.0),
        rake=0.0,
        table_name='T',
        num_players=kwargs.get('num_players', 6),
    )


def _setup_db():
    """Create an in-memory DB with schema initialized."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Repository(conn)


# ── Card Parsing Tests ───────────────────────────────────────────────

class TestParseCard(unittest.TestCase):
    """Test parse_card() and parse_cards() functions."""

    def test_parse_ace_hearts(self):
        rank, suit = parse_card('Ah')
        self.assertEqual(rank, 14)
        self.assertEqual(suit, 0)  # 'h' is index 0 in 'hdcs'

    def test_parse_two_spades(self):
        rank, suit = parse_card('2s')
        self.assertEqual(rank, 2)
        self.assertEqual(suit, 3)

    def test_parse_ten_clubs(self):
        rank, suit = parse_card('Tc')
        self.assertEqual(rank, 10)
        self.assertEqual(suit, 2)

    def test_parse_king_diamonds(self):
        rank, suit = parse_card('Kd')
        self.assertEqual(rank, 13)
        self.assertEqual(suit, 1)

    def test_parse_cards_two_cards(self):
        cards = parse_cards('Ah Kd')
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0], (14, 0))
        self.assertEqual(cards[1], (13, 1))

    def test_parse_cards_five_cards(self):
        cards = parse_cards('2c 7h Td Qs 3d')
        self.assertEqual(len(cards), 5)

    def test_parse_cards_empty(self):
        self.assertEqual(parse_cards(''), [])
        self.assertEqual(parse_cards(None), [])

    def test_parse_card_invalid(self):
        with self.assertRaises((ValueError, IndexError)):
            parse_card('Xz')

    def test_rank_map_completeness(self):
        """Ensure all standard ranks are mapped."""
        expected_ranks = '23456789TJQKA'
        for r in expected_ranks:
            self.assertIn(r, RANK_MAP)
        self.assertEqual(len(RANK_MAP), 13)


# ── Hand Evaluation Tests ────────────────────────────────────────────

class TestEvalFive(unittest.TestCase):
    """Test 5-card hand evaluation."""

    def _cards(self, s):
        return parse_cards(s)

    def test_high_card(self):
        val = _eval_five(self._cards('2h 5d 7c Ts Kh'))
        self.assertEqual(val[0], 0)

    def test_one_pair(self):
        val = _eval_five(self._cards('Ah Ad 7c 5s 3h'))
        self.assertEqual(val[0], 1)
        self.assertEqual(val[1], 14)  # pair of aces

    def test_two_pair(self):
        val = _eval_five(self._cards('Ah Ad Kh Kd 3c'))
        self.assertEqual(val[0], 2)

    def test_three_of_a_kind(self):
        val = _eval_five(self._cards('Ah Ad Ac 5s 3h'))
        self.assertEqual(val[0], 3)
        self.assertEqual(val[1], 14)

    def test_straight(self):
        val = _eval_five(self._cards('5h 6d 7c 8s 9h'))
        self.assertEqual(val[0], 4)
        self.assertEqual(val[1], 9)

    def test_ace_low_straight(self):
        val = _eval_five(self._cards('Ah 2d 3c 4s 5h'))
        self.assertEqual(val[0], 4)
        self.assertEqual(val[1], 5)

    def test_ace_high_straight(self):
        val = _eval_five(self._cards('Th Jd Qc Ks Ah'))
        self.assertEqual(val[0], 4)
        self.assertEqual(val[1], 14)

    def test_flush(self):
        val = _eval_five(self._cards('2h 5h 7h Th Kh'))
        self.assertEqual(val[0], 5)

    def test_full_house(self):
        val = _eval_five(self._cards('Ah Ad Ac Ks Kd'))
        self.assertEqual(val[0], 6)
        self.assertEqual(val[1], 14)  # trips
        self.assertEqual(val[2], 13)  # pair

    def test_four_of_a_kind(self):
        val = _eval_five(self._cards('Ah Ad Ac As 3h'))
        self.assertEqual(val[0], 7)
        self.assertEqual(val[1], 14)

    def test_straight_flush(self):
        val = _eval_five(self._cards('5h 6h 7h 8h 9h'))
        self.assertEqual(val[0], 8)
        self.assertEqual(val[1], 9)

    def test_royal_flush(self):
        val = _eval_five(self._cards('Th Jh Qh Kh Ah'))
        self.assertEqual(val[0], 8)
        self.assertEqual(val[1], 14)

    def test_hand_ranking_order(self):
        """Higher hands beat lower hands."""
        high_card = _eval_five(self._cards('2h 5d 7c Ts Kh'))
        pair = _eval_five(self._cards('Ah Ad 7c 5s 3h'))
        two_pair = _eval_five(self._cards('Ah Ad Kh Kd 3c'))
        trips = _eval_five(self._cards('Ah Ad Ac 5s 3h'))
        straight = _eval_five(self._cards('5h 6d 7c 8s 9h'))
        flush = _eval_five(self._cards('2h 5h 7h Th Kh'))
        full_house = _eval_five(self._cards('Ah Ad Ac Ks Kd'))
        quads = _eval_five(self._cards('Ah Ad Ac As 3h'))
        sf = _eval_five(self._cards('5h 6h 7h 8h 9h'))

        self.assertLess(high_card, pair)
        self.assertLess(pair, two_pair)
        self.assertLess(two_pair, trips)
        self.assertLess(trips, straight)
        self.assertLess(straight, flush)
        self.assertLess(flush, full_house)
        self.assertLess(full_house, quads)
        self.assertLess(quads, sf)


class TestEvaluateHand(unittest.TestCase):
    """Test evaluate_hand() with 5-7 cards."""

    def _cards(self, s):
        return parse_cards(s)

    def test_seven_cards_best_hand(self):
        """Best 5-card hand from 7 cards: should find the straight."""
        cards = self._cards('5h 6d 7c 8s 9h 2c 3d')
        val = evaluate_hand(cards)
        self.assertEqual(val[0], 4)  # straight
        self.assertEqual(val[1], 9)

    def test_seven_cards_flush(self):
        """Best 5 out of 7 should find the flush."""
        cards = self._cards('2h 5h 7h Th Kh 3c 8d')
        val = evaluate_hand(cards)
        self.assertEqual(val[0], 5)  # flush

    def test_fewer_than_5_returns_low(self):
        """With fewer than 5 cards, return minimal value."""
        cards = self._cards('Ah Kd')
        val = evaluate_hand(cards)
        self.assertEqual(val, (0,))


# ── Equity Calculation Tests ─────────────────────────────────────────

class TestCalculateEquity(unittest.TestCase):
    """Test calculate_equity() function."""

    def _cards(self, s):
        return parse_cards(s)

    def test_complete_board_hero_wins(self):
        """Hero has flush, opponent has pair on complete board."""
        hero = self._cards('Ah Kh')
        opp = [self._cards('Tc 9c')]
        board = self._cards('2h 5h 7h 3d 8s')
        eq = calculate_equity(hero, opp, board)
        self.assertAlmostEqual(eq, 1.0)

    def test_complete_board_hero_loses(self):
        """Hero has high card, opponent has trips on complete board."""
        hero = self._cards('Ah Kd')
        opp = [self._cards('7c 7d')]
        board = self._cards('7h 2s 5c 9d Ts')
        eq = calculate_equity(hero, opp, board)
        self.assertAlmostEqual(eq, 0.0)

    def test_complete_board_split_pot(self):
        """Same hand for both on complete board = split."""
        hero = self._cards('Ah Kd')
        opp = [self._cards('As Kc')]
        board = self._cards('2h 5d 8c Js Qh')
        eq = calculate_equity(hero, opp, board)
        self.assertAlmostEqual(eq, 0.5)

    def test_preflop_aa_vs_kk(self):
        """AA vs KK preflop should be ~80%+ equity for AA."""
        import random
        hero = self._cards('Ah Ad')
        opp = [self._cards('Kh Kd')]
        eq = calculate_equity(hero, opp, [], simulations=5000,
                              rng=random.Random(42))
        self.assertGreater(eq, 0.70)
        self.assertLess(eq, 0.95)

    def test_with_flop_board(self):
        """Equity with 3-card board uses exact enumeration for 2 remaining."""
        hero = self._cards('Ah Ad')
        opp = [self._cards('Kh Kd')]
        board = self._cards('2c 7s 9h')
        eq = calculate_equity(hero, opp, board)
        self.assertGreater(eq, 0.80)

    def test_with_turn_board(self):
        """Equity with 4-card board uses exact enumeration for 1 remaining."""
        hero = self._cards('Ah Ad')
        opp = [self._cards('Kh Kd')]
        board = self._cards('2c 7s 9h 3d')
        eq = calculate_equity(hero, opp, board)
        self.assertGreater(eq, 0.90)

    def test_multi_way_pot(self):
        """Multi-opponent equity calculation."""
        hero = self._cards('Ah Ad')
        opps = [self._cards('Kh Kd'), self._cards('Qh Qd')]
        board = self._cards('2c 7s 9h 3d Ts')
        eq = calculate_equity(hero, opps, board)
        self.assertAlmostEqual(eq, 1.0)  # AA beats KK and QQ on this board


class TestEvaluateShowdown(unittest.TestCase):
    """Test _evaluate_showdown() function."""

    def _cards(self, s):
        return parse_cards(s)

    def test_hero_wins(self):
        hero = self._cards('Ah Ad')
        opp = [self._cards('Kh Kd')]
        board = self._cards('2c 7s 9h 3d Ts')
        result = _evaluate_showdown(hero, opp, board)
        self.assertEqual(result, 1.0)

    def test_hero_loses(self):
        hero = self._cards('Kh Kd')
        opp = [self._cards('Ah Ad')]
        board = self._cards('2c 7s 9h 3d Ts')
        result = _evaluate_showdown(hero, opp, board)
        self.assertEqual(result, 0.0)

    def test_hero_ties(self):
        hero = self._cards('Ah Kd')
        opp = [self._cards('As Kc')]
        board = self._cards('2c 7s 9h 3d Ts')
        result = _evaluate_showdown(hero, opp, board)
        self.assertEqual(result, 0.5)

    def test_no_opponents(self):
        hero = self._cards('Ah Kd')
        board = self._cards('2c 7s 9h 3d Ts')
        result = _evaluate_showdown(hero, [], board)
        self.assertEqual(result, 1.0)


# ── Parser: parse_showdown_data Tests ────────────────────────────────

class TestParseShowdownData(unittest.TestCase):
    """Test GGPokerParser.parse_showdown_data()."""

    def setUp(self):
        self.parser = GGPokerParser()

    def test_allin_with_showdown(self):
        """Hand with all-in and showdown reveals opponent cards."""
        hand_text = (
            "Poker Hand #TM001: Hold'em No Limit ($0.25/$0.50) - "
            "2026/01/15 20:30:00\n"
            "Table 'T' 6-max Seat #1 is the button\n"
            "Seat 1: Hero ($50.00 in chips)\n"
            "Seat 2: Villain ($50.00 in chips)\n"
            "Hero: posts small blind $0.25\n"
            "Villain: posts big blind $0.50\n"
            "*** HOLE CARDS ***\n"
            "Dealt to Hero [Ah Kd]\n"
            "Hero: raises $1.00 to $1.50\n"
            "Villain: raises $3.00 to $4.50\n"
            "Hero: raises $45.50 to $50.00 and is all-in\n"
            "Villain: calls $45.50 and is all-in\n"
            "*** FLOP *** [2c 7h Td]\n"
            "*** TURN *** [2c 7h Td] [Qs]\n"
            "*** RIVER *** [2c 7h Td Qs] [3d]\n"
            "*** SHOW DOWN ***\n"
            "Villain: shows [Qh Qd] (a pair of Queens)\n"
            "Hero collected $99.50 from pot\n"
            "*** SUMMARY ***\n"
            "Total pot $100.00 | Rake $0.50\n"
        )
        result = self.parser.parse_showdown_data(hand_text)
        self.assertTrue(result['has_allin'])
        self.assertEqual(result['allin_street'], 'preflop')
        self.assertEqual(result['opponent_cards'], 'Qh Qd')
        self.assertAlmostEqual(result['pot_total'], 100.00)

    def test_no_allin(self):
        """Hand without all-in should return has_allin=False."""
        hand_text = (
            "Poker Hand #TM002: Hold'em No Limit ($0.25/$0.50) - "
            "2026/01/15 20:30:00\n"
            "Table 'T' 6-max Seat #1 is the button\n"
            "Seat 1: Hero ($50.00 in chips)\n"
            "Seat 2: Villain ($50.00 in chips)\n"
            "Hero: posts small blind $0.25\n"
            "Villain: posts big blind $0.50\n"
            "*** HOLE CARDS ***\n"
            "Dealt to Hero [Ah Kd]\n"
            "Hero: raises $1.00 to $1.50\n"
            "Villain: folds\n"
            "Hero collected $1.00 from pot\n"
            "*** SUMMARY ***\n"
            "Total pot $1.00 | Rake $0.00\n"
        )
        result = self.parser.parse_showdown_data(hand_text)
        self.assertFalse(result['has_allin'])
        self.assertIsNone(result['allin_street'])
        self.assertIsNone(result['opponent_cards'])

    def test_allin_on_flop(self):
        """All-in on flop should report 'flop' as allin_street."""
        hand_text = (
            "Poker Hand #TM003: Hold'em No Limit ($0.25/$0.50) - "
            "2026/01/15 20:30:00\n"
            "Table 'T' 6-max Seat #1 is the button\n"
            "Seat 1: Hero ($50.00 in chips)\n"
            "Seat 2: Villain ($50.00 in chips)\n"
            "Hero: posts small blind $0.25\n"
            "Villain: posts big blind $0.50\n"
            "*** HOLE CARDS ***\n"
            "Dealt to Hero [Ah Kd]\n"
            "Hero: raises $1.00 to $1.50\n"
            "Villain: calls $1.00\n"
            "*** FLOP *** [2c 7h Td]\n"
            "Villain: bets $3.00\n"
            "Hero: raises $45.50 to $48.50 and is all-in\n"
            "Villain: calls $45.50 and is all-in\n"
            "*** TURN *** [2c 7h Td] [Qs]\n"
            "*** RIVER *** [2c 7h Td Qs] [3d]\n"
            "*** SHOW DOWN ***\n"
            "Villain: shows [7c 7d] (three of a kind)\n"
            "Villain collected $99.50 from pot\n"
            "*** SUMMARY ***\n"
            "Total pot $100.00 | Rake $0.50\n"
        )
        result = self.parser.parse_showdown_data(hand_text)
        self.assertTrue(result['has_allin'])
        self.assertEqual(result['allin_street'], 'flop')
        self.assertEqual(result['opponent_cards'], '7c 7d')

    def test_multiple_opponents_showdown(self):
        """Multi-way showdown with multiple opponent cards."""
        hand_text = (
            "Poker Hand #TM004: Hold'em No Limit ($0.25/$0.50) - "
            "2026/01/15 20:30:00\n"
            "Table 'T' 6-max Seat #1 is the button\n"
            "Seat 1: Hero ($50.00 in chips)\n"
            "Seat 2: V1 ($50.00 in chips)\n"
            "Seat 3: V2 ($50.00 in chips)\n"
            "Hero: posts small blind $0.25\n"
            "V1: posts big blind $0.50\n"
            "*** HOLE CARDS ***\n"
            "Dealt to Hero [Ah Ad]\n"
            "V2: raises $1.00 to $1.50\n"
            "Hero: raises $48.50 to $50.00 and is all-in\n"
            "V1: calls $49.50 and is all-in\n"
            "V2: calls $48.50 and is all-in\n"
            "*** FLOP *** [2c 7h Td]\n"
            "*** TURN *** [2c 7h Td] [Qs]\n"
            "*** RIVER *** [2c 7h Td Qs] [3d]\n"
            "*** SHOW DOWN ***\n"
            "V1: shows [Kh Kd] (a pair of Kings)\n"
            "V2: shows [Qh Qd] (a pair of Queens)\n"
            "Hero collected $149.50 from pot\n"
            "*** SUMMARY ***\n"
            "Total pot $150.00 | Rake $0.50\n"
        )
        result = self.parser.parse_showdown_data(hand_text)
        self.assertTrue(result['has_allin'])
        self.assertIn('|', result['opponent_cards'])
        parts = result['opponent_cards'].split('|')
        self.assertEqual(len(parts), 2)

    def test_summary_showed_cards(self):
        """Extract cards from SUMMARY section 'showed' format."""
        hand_text = (
            "Poker Hand #TM005: Hold'em No Limit ($0.25/$0.50) - "
            "2026/01/15 20:30:00\n"
            "Table 'T' 6-max Seat #1 is the button\n"
            "Seat 1: Hero ($50.00 in chips)\n"
            "Seat 2: Villain ($50.00 in chips)\n"
            "Hero: posts small blind $0.25\n"
            "Villain: posts big blind $0.50\n"
            "*** HOLE CARDS ***\n"
            "Dealt to Hero [Ah Kd]\n"
            "Hero: raises $49.75 to $50.00 and is all-in\n"
            "Villain: calls $49.50 and is all-in\n"
            "*** FLOP *** [2c 7h Td]\n"
            "*** TURN *** [2c 7h Td] [Qs]\n"
            "*** RIVER *** [2c 7h Td Qs] [3d]\n"
            "*** SUMMARY ***\n"
            "Total pot $100.00 | Rake $0.50\n"
            "Seat 2: Villain showed [Jh Js] and lost\n"
        )
        result = self.parser.parse_showdown_data(hand_text)
        self.assertEqual(result['opponent_cards'], 'Jh Js')


# ── Repository Tests ─────────────────────────────────────────────────

class TestRepositoryShowdown(unittest.TestCase):
    """Test repository methods for showdown/all-in data."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_update_hand_showdown(self):
        """Test update_hand_showdown persists data correctly."""
        hand = _make_hand('H001')
        self.repo.insert_hand(hand)
        self.repo.update_hand_showdown(
            'H001', pot_total=100.0, opponent_cards='Qh Qd',
            has_allin=True, allin_street='preflop')
        self.conn.commit()

        row = self.conn.execute(
            "SELECT * FROM hands WHERE hand_id = 'H001'"
        ).fetchone()
        self.assertAlmostEqual(row['pot_total'], 100.0)
        self.assertEqual(row['opponent_cards'], 'Qh Qd')
        self.assertEqual(row['has_allin'], 1)
        self.assertEqual(row['allin_street'], 'preflop')

    def test_get_allin_hands_filters_correctly(self):
        """get_allin_hands returns only hands with allin+showdown."""
        # Hand 1: all-in with showdown
        h1 = _make_hand('H001', hero_cards='Ah Ad')
        self.repo.insert_hand(h1)
        self.repo.update_hand_showdown(
            'H001', pot_total=100.0, opponent_cards='Kh Kd',
            has_allin=True, allin_street='preflop')

        # Hand 2: all-in without showdown (no opponent cards)
        h2 = _make_hand('H002', hero_cards='Qh Qd')
        self.repo.insert_hand(h2)
        self.repo.update_hand_showdown(
            'H002', pot_total=50.0, has_allin=True, allin_street='flop')

        # Hand 3: no all-in
        h3 = _make_hand('H003', hero_cards='Jh Jd')
        self.repo.insert_hand(h3)

        self.conn.commit()
        allin_hands = self.repo.get_allin_hands()
        self.assertEqual(len(allin_hands), 1)
        self.assertEqual(allin_hands[0]['hand_id'], 'H001')

    def test_get_allin_hands_filters_by_year(self):
        """get_allin_hands filters by year correctly."""
        h1 = _make_hand('H001', date='2026-01-15', hero_cards='Ah Ad')
        self.repo.insert_hand(h1)
        self.repo.update_hand_showdown(
            'H001', pot_total=100.0, opponent_cards='Kh Kd',
            has_allin=True, allin_street='preflop')

        h2 = _make_hand('H002', date='2025-06-15', hero_cards='Qh Qd')
        self.repo.insert_hand(h2)
        self.repo.update_hand_showdown(
            'H002', pot_total=50.0, opponent_cards='Jh Jd',
            has_allin=True, allin_street='flop')
        self.conn.commit()

        result_2026 = self.repo.get_allin_hands('2026')
        self.assertEqual(len(result_2026), 1)
        self.assertEqual(result_2026[0]['hand_id'], 'H001')

    def test_get_allin_hands_excludes_no_hero_cards(self):
        """get_allin_hands excludes hands where hero_cards is NULL."""
        h1 = _make_hand('H001', hero_cards=None)
        self.repo.insert_hand(h1)
        self.repo.update_hand_showdown(
            'H001', pot_total=100.0, opponent_cards='Kh Kd',
            has_allin=True, allin_street='preflop')
        self.conn.commit()

        result = self.repo.get_allin_hands()
        self.assertEqual(len(result), 0)


# ── EVAnalyzer Tests ─────────────────────────────────────────────────

class TestEVAnalyzerComputeHandEV(unittest.TestCase):
    """Test EVAnalyzer._compute_hand_ev()."""

    def setUp(self):
        self.conn, self.repo = _setup_db()
        self.analyzer = EVAnalyzer(self.repo)

    def test_hero_wins_with_better_hand(self):
        """Hero has AA vs KK on a clean board → equity ~95%+."""
        hand = {
            'hero_cards': 'Ah Ad',
            'opponent_cards': 'Kh Kd',
            'pot_total': 100.0,
            'invested': 50.0,
            'net': 50.0,
            'allin_street': 'river',
            'board_flop': '2c 7s 9h',
            'board_turn': '3d',
            'board_river': 'Ts',
        }
        result = self.analyzer._compute_hand_ev(hand)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['equity'], 1.0)
        self.assertAlmostEqual(result['ev_net'], 50.0)

    def test_hero_loses_returns_low_equity(self):
        """Hero has high card vs trips → equity ≈ 0 on river."""
        hand = {
            'hero_cards': 'Ah Kd',
            'opponent_cards': '7c 7d',
            'pot_total': 100.0,
            'invested': 50.0,
            'net': -50.0,
            'allin_street': 'river',
            'board_flop': '7h 2s 5c',
            'board_turn': '9d',
            'board_river': 'Ts',
        }
        result = self.analyzer._compute_hand_ev(hand)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['equity'], 0.0)
        self.assertAlmostEqual(result['ev_net'], -50.0)

    def test_missing_hero_cards(self):
        """Should return None if hero_cards is missing."""
        hand = {'hero_cards': None, 'opponent_cards': 'Kh Kd',
                'pot_total': 100.0, 'invested': 50.0, 'net': 50.0}
        self.assertIsNone(self.analyzer._compute_hand_ev(hand))

    def test_missing_opponent_cards(self):
        """Should return None if opponent_cards is missing."""
        hand = {'hero_cards': 'Ah Ad', 'opponent_cards': None,
                'pot_total': 100.0, 'invested': 50.0, 'net': 50.0}
        self.assertIsNone(self.analyzer._compute_hand_ev(hand))

    def test_preflop_allin(self):
        """Preflop all-in should use empty board for equity calc."""
        hand = {
            'hero_cards': 'Ah Ad',
            'opponent_cards': 'Kh Kd',
            'pot_total': 100.0,
            'invested': 50.0,
            'net': 50.0,
            'allin_street': 'preflop',
            'board_flop': '2c 7s 9h',
            'board_turn': '3d',
            'board_river': 'Ts',
        }
        result = self.analyzer._compute_hand_ev(hand)
        self.assertIsNotNone(result)
        self.assertGreater(result['equity'], 0.70)
        self.assertLess(result['equity'], 0.95)

    def test_multi_opponent_cards(self):
        """Pipe-separated opponent cards should be parsed for multi-way."""
        hand = {
            'hero_cards': 'Ah Ad',
            'opponent_cards': 'Kh Kd|Qh Qd',
            'pot_total': 150.0,
            'invested': 50.0,
            'net': 100.0,
            'allin_street': 'river',
            'board_flop': '2c 7s 9h',
            'board_turn': '3d',
            'board_river': 'Ts',
        }
        result = self.analyzer._compute_hand_ev(hand)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['equity'], 1.0)


class TestGetBoardAtAllin(unittest.TestCase):
    """Test EVAnalyzer._get_board_at_allin() static method."""

    def test_preflop_allin_empty_board(self):
        hand = {'allin_street': 'preflop', 'board_flop': '2c 7h Td',
                'board_turn': 'Qs', 'board_river': '3d'}
        board = EVAnalyzer._get_board_at_allin(hand)
        self.assertEqual(len(board), 0)

    def test_flop_allin_has_flop_only(self):
        hand = {'allin_street': 'flop', 'board_flop': '2c 7h Td',
                'board_turn': 'Qs', 'board_river': '3d'}
        board = EVAnalyzer._get_board_at_allin(hand)
        self.assertEqual(len(board), 3)

    def test_turn_allin_has_flop_and_turn(self):
        hand = {'allin_street': 'turn', 'board_flop': '2c 7h Td',
                'board_turn': 'Qs', 'board_river': '3d'}
        board = EVAnalyzer._get_board_at_allin(hand)
        self.assertEqual(len(board), 4)

    def test_river_allin_has_full_board(self):
        hand = {'allin_street': 'river', 'board_flop': '2c 7h Td',
                'board_turn': 'Qs', 'board_river': '3d'}
        board = EVAnalyzer._get_board_at_allin(hand)
        self.assertEqual(len(board), 5)

    def test_missing_board_data(self):
        hand = {'allin_street': 'flop', 'board_flop': None,
                'board_turn': None, 'board_river': None}
        board = EVAnalyzer._get_board_at_allin(hand)
        self.assertEqual(len(board), 0)


class TestEVAnalyzerGetEVAnalysis(unittest.TestCase):
    """Test full get_ev_analysis() integration."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_empty_database(self):
        """No hands → empty result."""
        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_ev_analysis()
        self.assertEqual(result['overall']['total_hands'], 0)
        self.assertEqual(result['overall']['allin_hands'], 0)
        self.assertEqual(result['by_stakes'], {})
        self.assertEqual(result['chart_data'], [])

    def test_hands_without_allins(self):
        """All hands without all-in → EV line matches real line."""
        for i in range(5):
            h = _make_hand(f'H{i:03d}', net=1.0, invested=1.0, won=2.0)
            self.repo.insert_hand(h)
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_ev_analysis()
        self.assertEqual(result['overall']['total_hands'], 5)
        self.assertEqual(result['overall']['allin_hands'], 0)
        self.assertAlmostEqual(result['overall']['real_net'], 5.0)
        self.assertAlmostEqual(result['overall']['ev_net'], 5.0)
        self.assertAlmostEqual(result['overall']['luck_factor'], 0.0)

    def test_with_allin_hand(self):
        """Hand with all-in and showdown is included in EV analysis."""
        # Non-allin hand
        h1 = _make_hand('H001', net=2.0, invested=1.0, won=3.0)
        self.repo.insert_hand(h1)

        # All-in hand: hero has AA vs KK, won the pot
        h2 = _make_hand('H002', net=50.0, invested=50.0, won=100.0,
                         hero_cards='Ah Ad')
        self.repo.insert_hand(h2)
        self.repo.update_hand_board('H002', '2c 7s 9h', '3d', 'Ts')
        self.repo.update_hand_showdown(
            'H002', pot_total=100.0, opponent_cards='Kh Kd',
            has_allin=True, allin_street='river')
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_ev_analysis()
        self.assertEqual(result['overall']['total_hands'], 2)
        self.assertEqual(result['overall']['allin_hands'], 1)
        self.assertAlmostEqual(result['overall']['real_net'], 52.0)

    def test_stakes_breakdown(self):
        """Different stakes should be separated in by_stakes."""
        h1 = _make_hand('H001', blinds_sb=0.25, blinds_bb=0.50,
                         net=1.0, invested=1.0, won=2.0)
        h2 = _make_hand('H002', blinds_sb=0.50, blinds_bb=1.00,
                         net=-2.0, invested=2.0, won=0.0)
        self.repo.insert_hand(h1)
        self.repo.insert_hand(h2)
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_ev_analysis()
        self.assertIn('$0.25/$0.50', result['by_stakes'])
        self.assertIn('$0.50/$1.00', result['by_stakes'])

    def test_chart_data_has_correct_length(self):
        """Chart data should have one entry per hand."""
        for i in range(10):
            h = _make_hand(f'H{i:03d}', net=1.0, invested=1.0, won=2.0)
            self.repo.insert_hand(h)
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_ev_analysis()
        self.assertEqual(len(result['chart_data']), 10)
        self.assertEqual(result['chart_data'][0]['hand'], 1)
        self.assertEqual(result['chart_data'][-1]['hand'], 10)

    def test_chart_data_cumulative(self):
        """Chart data real values should be cumulative."""
        for i in range(3):
            h = _make_hand(f'H{i:03d}', net=2.0, invested=1.0, won=3.0)
            self.repo.insert_hand(h)
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_ev_analysis()
        self.assertAlmostEqual(result['chart_data'][0]['real'], 2.0)
        self.assertAlmostEqual(result['chart_data'][1]['real'], 4.0)
        self.assertAlmostEqual(result['chart_data'][2]['real'], 6.0)

    def test_bb100_calculation(self):
        """bb/100 should be calculated correctly."""
        for i in range(100):
            h = _make_hand(f'H{i:03d}', net=0.50, invested=1.0, won=1.50,
                           blinds_bb=0.50)
            self.repo.insert_hand(h)
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_ev_analysis()
        # 100 hands, each +0.50, BB=0.50 → 50bb total / 100 hands * 100 = 100 bb/100
        self.assertAlmostEqual(result['overall']['bb100_real'], 100.0, places=1)

    def test_luck_factor_positive(self):
        """Luck factor positive when real > EV."""
        # Hero AA vs KK, hero wins 50.0 actual
        h1 = _make_hand('H001', net=50.0, invested=50.0, won=100.0,
                         hero_cards='Ah Ad')
        self.repo.insert_hand(h1)
        self.repo.update_hand_board('H001', '2c 7s 9h', '3d', 'Ts')
        self.repo.update_hand_showdown(
            'H001', pot_total=100.0, opponent_cards='Kh Kd',
            has_allin=True, allin_street='river')
        self.conn.commit()

        analyzer = EVAnalyzer(self.repo)
        result = analyzer.get_ev_analysis()
        # AA has 100% equity on this board, so EV = 100*1.0 - 50 = 50
        # Real = 50, luck = 50 - 50 = 0
        self.assertAlmostEqual(result['overall']['luck_factor'], 0.0)


class TestWeightedAvgBB(unittest.TestCase):
    """Test EVAnalyzer._weighted_avg_bb()."""

    def test_single_stake(self):
        hands = [{'blinds_bb': 0.50}, {'blinds_bb': 0.50}, {'blinds_bb': 0.50}]
        result = EVAnalyzer._weighted_avg_bb(hands)
        self.assertAlmostEqual(result, 0.50)

    def test_mixed_stakes(self):
        hands = [{'blinds_bb': 0.50}, {'blinds_bb': 1.00}]
        result = EVAnalyzer._weighted_avg_bb(hands)
        self.assertAlmostEqual(result, 0.75)

    def test_empty_hands(self):
        result = EVAnalyzer._weighted_avg_bb([])
        self.assertAlmostEqual(result, 0.5)

    def test_none_bb_uses_default(self):
        hands = [{'blinds_bb': None}]
        result = EVAnalyzer._weighted_avg_bb(hands)
        self.assertAlmostEqual(result, 0.5)


class TestDownsample(unittest.TestCase):
    """Test EVAnalyzer._downsample()."""

    def test_short_data_unchanged(self):
        data = [{'hand': i} for i in range(10)]
        result = EVAnalyzer._downsample(data, 100)
        self.assertEqual(len(result), 10)

    def test_long_data_downsampled(self):
        data = [{'hand': i} for i in range(1000)]
        result = EVAnalyzer._downsample(data, 50)
        self.assertEqual(len(result), 50)
        self.assertEqual(result[0]['hand'], 0)  # first preserved
        self.assertEqual(result[-1]['hand'], 999)  # last preserved


# ── Report Rendering Tests ───────────────────────────────────────────

class TestRenderEVAnalysis(unittest.TestCase):
    """Test report rendering for EV analysis section."""

    def setUp(self):
        self.conn, self.repo = _setup_db()

    def test_ev_section_in_report(self):
        """EV analysis section appears in HTML report when allin hands exist."""
        from src.analyzers.cash import CashAnalyzer
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os

        # Insert hands with all-in and showdown
        h1 = _make_hand('H001', net=1.0, invested=1.0, won=2.0,
                         hero_cards='Ah Ad')
        self.repo.insert_hand(h1)
        self.repo.update_hand_board('H001', '2c 7s 9h', '3d', 'Ts')
        self.repo.update_hand_showdown(
            'H001', pot_total=4.0, opponent_cards='Kh Kd',
            has_allin=True, allin_street='river')
        self.conn.commit()

        cash_analyzer = CashAnalyzer(self.repo)
        ev_analyzer = EVAnalyzer(self.repo)

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            tmpfile = f.name

        try:
            generate_cash_report(cash_analyzer, tmpfile, ev_analyzer=ev_analyzer)
            with open(tmpfile, 'r', encoding='utf-8') as f:
                html = f.read()
            self.assertIn('EV Analysis', html)
            self.assertIn('All-in Hands', html)
            self.assertIn('bb/100 Real', html)
            self.assertIn('bb/100 EV-Adjusted', html)
            self.assertIn('Luck Factor', html)
        finally:
            os.unlink(tmpfile)

    def test_no_ev_section_without_allins(self):
        """EV section should NOT appear when there are no all-in hands."""
        from src.analyzers.cash import CashAnalyzer
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os

        h1 = _make_hand('H001', net=1.0, invested=1.0, won=2.0)
        self.repo.insert_hand(h1)
        self.conn.commit()

        cash_analyzer = CashAnalyzer(self.repo)
        ev_analyzer = EVAnalyzer(self.repo)

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            tmpfile = f.name

        try:
            generate_cash_report(cash_analyzer, tmpfile, ev_analyzer=ev_analyzer)
            with open(tmpfile, 'r', encoding='utf-8') as f:
                html = f.read()
            self.assertNotIn('EV Analysis', html)
        finally:
            os.unlink(tmpfile)

    def test_stakes_table_in_report(self):
        """Stakes breakdown table appears when allin hands have different stakes."""
        from src.analyzers.cash import CashAnalyzer
        from src.reports.cash_report import generate_cash_report
        import tempfile
        import os

        h1 = _make_hand('H001', net=50.0, invested=50.0, won=100.0,
                         hero_cards='Ah Ad', blinds_sb=0.25, blinds_bb=0.50)
        self.repo.insert_hand(h1)
        self.repo.update_hand_board('H001', '2c 7s 9h', '3d', 'Ts')
        self.repo.update_hand_showdown(
            'H001', pot_total=100.0, opponent_cards='Kh Kd',
            has_allin=True, allin_street='river')
        self.conn.commit()

        cash_analyzer = CashAnalyzer(self.repo)
        ev_analyzer = EVAnalyzer(self.repo)

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            tmpfile = f.name

        try:
            generate_cash_report(cash_analyzer, tmpfile, ev_analyzer=ev_analyzer)
            with open(tmpfile, 'r', encoding='utf-8') as f:
                html = f.read()
            self.assertIn('Breakdown por Stakes', html)
            self.assertIn('$0.25/$0.50', html)
        finally:
            os.unlink(tmpfile)


class TestRenderEVChart(unittest.TestCase):
    """Test SVG chart rendering."""

    def test_chart_renders_svg(self):
        from src.reports.cash_report import _render_ev_chart
        chart_data = [
            {'hand': 1, 'real': 0.0, 'ev': 0.0},
            {'hand': 2, 'real': 5.0, 'ev': 3.0},
            {'hand': 3, 'real': 10.0, 'ev': 8.0},
        ]
        svg = _render_ev_chart(chart_data)
        self.assertIn('<svg', svg)
        self.assertIn('polyline', svg)
        self.assertIn('Real', svg)
        self.assertIn('EV-Adjusted', svg)

    def test_chart_with_negative_values(self):
        from src.reports.cash_report import _render_ev_chart
        chart_data = [
            {'hand': 1, 'real': 0.0, 'ev': 0.0},
            {'hand': 2, 'real': -5.0, 'ev': -2.0},
            {'hand': 3, 'real': -10.0, 'ev': -3.0},
        ]
        svg = _render_ev_chart(chart_data)
        self.assertIn('<svg', svg)

    def test_chart_with_single_data_point_skipped(self):
        """Chart needs >= 2 points; condition is in report renderer."""
        from src.reports.cash_report import _render_ev_chart
        # This should still work for 2 points
        chart_data = [
            {'hand': 1, 'real': 0.0, 'ev': 0.0},
            {'hand': 2, 'real': 5.0, 'ev': 3.0},
        ]
        svg = _render_ev_chart(chart_data)
        self.assertIn('<svg', svg)


# ── Integration Tests ────────────────────────────────────────────────

class TestEVIntegration(unittest.TestCase):
    """Full integration test: parser → DB → analyzer → report."""

    def test_full_pipeline_allin_hand(self):
        """Parse hand text → store → analyze → verify EV calculation."""
        parser = GGPokerParser()
        conn, repo = _setup_db()

        hand_text = (
            "Poker Hand #TM999: Hold'em No Limit ($0.25/$0.50) - "
            "2026/01/15 20:30:00\n"
            "Table 'RushAndCash' 6-max Seat #1 is the button\n"
            "Seat 1: Player1 ($50.00 in chips)\n"
            "Seat 2: Hero ($50.00 in chips)\n"
            "Seat 3: Villain ($50.00 in chips)\n"
            "Player1: posts small blind $0.25\n"
            "Hero: posts big blind $0.50\n"
            "*** HOLE CARDS ***\n"
            "Dealt to Hero [Ah Ad]\n"
            "Villain: raises $1.00 to $1.50\n"
            "Player1: folds\n"
            "Hero: raises $3.00 to $4.50\n"
            "Villain: raises $45.50 to $50.00 and is all-in\n"
            "Hero: calls $45.50 and is all-in\n"
            "*** FLOP *** [2c 7h Td]\n"
            "*** TURN *** [2c 7h Td] [Qs]\n"
            "*** RIVER *** [2c 7h Td Qs] [3d]\n"
            "*** SHOW DOWN ***\n"
            "Villain: shows [Kh Kd] (a pair of Kings)\n"
            "Hero collected $99.50 from pot\n"
            "*** SUMMARY ***\n"
            "Total pot $100.00 | Rake $0.50\n"
            "Seat 2: Hero (big blind) showed [Ah Ad] and won ($99.50)\n"
            "Seat 3: Villain showed [Kh Kd] and lost\n"
        )

        # Parse
        hand = parser.parse_single_hand(hand_text)
        self.assertIsNotNone(hand)

        showdown = parser.parse_showdown_data(hand_text)
        actions, board, positions = parser.parse_actions(hand_text, hand.hand_id)

        # Store
        repo.insert_hand(hand)
        repo.insert_actions_batch(actions)
        if board.flop or board.turn or board.river:
            repo.update_hand_board(hand.hand_id, board.flop, board.turn, board.river)
        hero_pos = positions.get('Hero')
        if hero_pos:
            repo.update_hand_position(hand.hand_id, hero_pos)
        if showdown.get('pot_total') or showdown.get('has_allin'):
            repo.update_hand_showdown(
                hand.hand_id,
                pot_total=showdown.get('pot_total'),
                opponent_cards=showdown.get('opponent_cards'),
                has_allin=showdown.get('has_allin', False),
                allin_street=showdown.get('allin_street'),
            )
        conn.commit()

        # Analyze
        analyzer = EVAnalyzer(repo)
        result = analyzer.get_ev_analysis()

        self.assertEqual(result['overall']['total_hands'], 1)
        self.assertEqual(result['overall']['allin_hands'], 1)
        self.assertIn('$0.25/$0.50', result['by_stakes'])

    def test_mixed_hands_ev_analysis(self):
        """Mix of allin and non-allin hands produces correct aggregates."""
        conn, repo = _setup_db()

        # 3 normal hands
        for i in range(3):
            h = _make_hand(f'N{i:03d}', net=1.0, invested=1.0, won=2.0)
            repo.insert_hand(h)

        # 2 all-in hands
        for i in range(2):
            h = _make_hand(f'A{i:03d}', net=10.0, invested=10.0, won=20.0,
                           hero_cards='Ah Ad')
            repo.insert_hand(h)
            repo.update_hand_board(f'A{i:03d}', '2c 7s 9h', '3d', 'Ts')
            repo.update_hand_showdown(
                f'A{i:03d}', pot_total=20.0, opponent_cards='Kh Kd',
                has_allin=True, allin_street='river')
        conn.commit()

        analyzer = EVAnalyzer(repo)
        result = analyzer.get_ev_analysis()

        self.assertEqual(result['overall']['total_hands'], 5)
        self.assertEqual(result['overall']['allin_hands'], 2)
        # Real net = 3*1.0 + 2*10.0 = 23.0
        self.assertAlmostEqual(result['overall']['real_net'], 23.0)
        self.assertEqual(len(result['chart_data']), 5)


if __name__ == '__main__':
    unittest.main()
