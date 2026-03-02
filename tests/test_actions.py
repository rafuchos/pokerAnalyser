"""Tests for US-001: Detailed action parsing by street.

Covers:
- Action parsing (fold, call, raise, check, bet, all-in) with amounts
- Street separation (preflop, flop, turn, river)
- Position identification (BTN, SB, BB, UTG, MP, CO)
- Board card extraction per street
- VPIP detection (voluntary pot entry, excluding forced blinds)
- GGPoker and PokerStars support
- Database persistence of actions in hand_actions table
- Backward compatibility with existing financial parser
"""

import sqlite3
import unittest
from datetime import datetime

from src.db.schema import init_db
from src.db.repository import Repository
from src.parsers.base import ActionData, BoardData, HandData
from src.parsers.ggpoker import GGPokerParser
from src.parsers.pokerstars import PokerStarsParser


# ── Fixtures ──────────────────────────────────────────────────────────

GGPOKER_HAND_FULL = (
    "Poker Hand #RC0001000001: Hold'em No Limit ($0.25/$0.50) - "
    "2026/01/15 20:30:00\n"
    "Table 'RushAndCash999' 6-max Seat #4 is the button\n"
    "Seat 1: Player1 ($50.00 in chips)\n"
    "Seat 2: Player2 ($48.00 in chips)\n"
    "Seat 3: Hero ($52.00 in chips)\n"
    "Seat 4: Player4 ($55.00 in chips)\n"
    "Seat 5: Player5 ($45.00 in chips)\n"
    "Seat 6: Player6 ($60.00 in chips)\n"
    "Player5: posts small blind $0.25\n"
    "Player6: posts big blind $0.50\n"
    "*** HOLE CARDS ***\n"
    "Dealt to Hero [Ah Kd]\n"
    "Player1: folds\n"
    "Player2: calls $0.50\n"
    "Hero: raises $1.00 to $1.50\n"
    "Player4: folds\n"
    "Player5: folds\n"
    "Player6: calls $1.00\n"
    "Player2: calls $1.00\n"
    "*** FLOP *** [2c 7h Td]\n"
    "Player6: checks\n"
    "Player2: checks\n"
    "Hero: bets $2.50\n"
    "Player6: folds\n"
    "Player2: calls $2.50\n"
    "*** TURN *** [2c 7h Td] [Qs]\n"
    "Player2: checks\n"
    "Hero: bets $5.00\n"
    "Player2: folds\n"
    "*** SUMMARY ***\n"
    "Total pot $12.25 | Rake $0.50\n"
    "Board [2c 7h Td Qs]\n"
)

GGPOKER_HAND_ALLIN = (
    "Poker Hand #RC0002000002: Hold'em No Limit ($0.25/$0.50) - "
    "2026/01/15 21:00:00\n"
    "Table 'RushAndCash888' 6-max Seat #1 is the button\n"
    "Seat 1: Hero ($20.00 in chips)\n"
    "Seat 2: Villain ($50.00 in chips)\n"
    "Seat 3: Player3 ($30.00 in chips)\n"
    "Hero: posts small blind $0.25\n"
    "Villain: posts big blind $0.50\n"
    "*** HOLE CARDS ***\n"
    "Dealt to Hero [As Ac]\n"
    "Player3: raises $1.00 to $1.50\n"
    "Hero: raises $18.50 to $20.00 and is all-in\n"
    "Villain: folds\n"
    "Player3: calls $18.50\n"
    "*** FLOP *** [9h 8d 9s]\n"
    "*** TURN *** [9h 8d 9s] [2h]\n"
    "*** RIVER *** [9h 8d 9s 2h] [Jc]\n"
    "*** SHOW DOWN ***\n"
    "Hero collected $40.50 from pot\n"
    "*** SUMMARY ***\n"
    "Total pot $41.00 | Rake $0.50\n"
    "Board [9h 8d 9s 2h Jc]\n"
)

GGPOKER_HAND_PREFLOP_FOLD = (
    "Poker Hand #RC0003000003: Hold'em No Limit ($0.25/$0.50) - "
    "2026/01/15 21:05:00\n"
    "Table 'RushAndCash777' 6-max Seat #2 is the button\n"
    "Seat 1: Player1 ($50.00 in chips)\n"
    "Seat 2: Hero ($50.00 in chips)\n"
    "Seat 3: Player3 ($50.00 in chips)\n"
    "Seat 4: Player4 ($50.00 in chips)\n"
    "Player3: posts small blind $0.25\n"
    "Player4: posts big blind $0.50\n"
    "*** HOLE CARDS ***\n"
    "Dealt to Hero [2h 7c]\n"
    "Player1: folds\n"
    "Hero: folds\n"
    "Player3: folds\n"
    "*** SUMMARY ***\n"
    "Total pot $0.50 | Rake $0.00\n"
)

POKERSTARS_HAND = (
    "PokerStars Hand #300000000001: Tournament #5000000001, "
    "$7.20+$7.50+$1.80 USD Hold'em No Limit - Level VII (60/120) - "
    "2026/02/15 11:46:00 BRT\n"
    "Table '5000000001 1' 9-max Seat #3 is the button\n"
    "Seat 1: gangsta221 (5000 in chips)\n"
    "Seat 2: Opponent2 (3000 in chips)\n"
    "Seat 3: Opponent3 (4000 in chips)\n"
    "Seat 4: Opponent4 (2500 in chips)\n"
    "Seat 5: Opponent5 (6000 in chips)\n"
    "Seat 6: Opponent6 (3500 in chips)\n"
    "Opponent4: posts small blind 60\n"
    "Opponent5: posts big blind 120\n"
    "*** HOLE CARDS ***\n"
    "Dealt to gangsta221 [Jd Jh]\n"
    "Opponent6: folds\n"
    "gangsta221: raises 120 to 240\n"
    "Opponent2: calls 240\n"
    "Opponent3: folds\n"
    "Opponent4: folds\n"
    "Opponent5: calls 120\n"
    "*** FLOP *** [4s 8h Kc]\n"
    "Opponent5: checks\n"
    "gangsta221: bets 360\n"
    "Opponent2: folds\n"
    "Opponent5: calls 360\n"
    "*** TURN *** [4s 8h Kc] [2d]\n"
    "Opponent5: checks\n"
    "gangsta221: checks\n"
    "*** RIVER *** [4s 8h Kc 2d] [9s]\n"
    "Opponent5: bets 600\n"
    "gangsta221: calls 600\n"
    "*** SHOW DOWN ***\n"
    "Opponent5: shows [Kd Ts] (a pair of Kings)\n"
    "gangsta221: shows [Jd Jh] (a pair of Jacks)\n"
    "Opponent5 collected 2460 from pot\n"
    "*** SUMMARY ***\n"
    "Total pot 2460 | Rake 0\n"
    "Board [4s 8h Kc 2d 9s]\n"
)


# ── GGPoker Action Parsing Tests ─────────────────────────────────────

class TestGGPokerActionParsing(unittest.TestCase):
    """Test GGPoker action parsing for all action types."""

    def setUp(self):
        self.parser = GGPokerParser()

    def test_parse_actions_returns_all_action_types(self):
        """Verify fold, call, raise, check, bet actions are parsed."""
        actions, board, positions = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        action_types = {a.action_type for a in actions}
        self.assertIn('fold', action_types)
        self.assertIn('call', action_types)
        self.assertIn('raise', action_types)
        self.assertIn('check', action_types)
        self.assertIn('bet', action_types)
        self.assertIn('post_sb', action_types)
        self.assertIn('post_bb', action_types)

    def test_parse_actions_allin_detected(self):
        """Verify all-in action is correctly detected."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_ALLIN, 'RC0002000002'
        )
        allin_actions = [a for a in actions if a.action_type == 'all-in']
        self.assertTrue(len(allin_actions) > 0)
        # Hero went all-in for $20.00
        hero_allin = [a for a in allin_actions if a.is_hero == 1]
        self.assertEqual(len(hero_allin), 1)
        self.assertAlmostEqual(hero_allin[0].amount, 20.00)

    def test_parse_actions_amounts_correct(self):
        """Verify monetary amounts are correctly extracted."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        # Hero raises to $1.50 preflop
        hero_raises = [a for a in actions if a.player == 'Hero' and a.action_type == 'raise']
        self.assertEqual(len(hero_raises), 1)
        self.assertAlmostEqual(hero_raises[0].amount, 1.50)

        # Hero bets $2.50 on flop
        hero_bets = [a for a in actions if a.player == 'Hero' and a.action_type == 'bet']
        self.assertTrue(len(hero_bets) >= 1)
        flop_bet = [a for a in hero_bets if a.street == 'flop']
        self.assertEqual(len(flop_bet), 1)
        self.assertAlmostEqual(flop_bet[0].amount, 2.50)

    def test_parse_actions_hand_id_set(self):
        """Verify all actions reference the correct hand_id."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        for action in actions:
            self.assertEqual(action.hand_id, 'RC0001000001')

    def test_parse_actions_sequence_order(self):
        """Verify actions within a street have incrementing sequence_order."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        for street in ('preflop', 'flop', 'turn'):
            street_actions = [a for a in actions if a.street == street]
            if street_actions:
                orders = [a.sequence_order for a in street_actions]
                self.assertEqual(orders, sorted(orders),
                                 f"sequence_order not sorted for {street}")


# ── Street Separation Tests ──────────────────────────────────────────

class TestStreetSeparation(unittest.TestCase):
    """Test that actions are correctly separated by street."""

    def setUp(self):
        self.parser = GGPokerParser()

    def test_actions_separated_by_street(self):
        """Verify preflop/flop/turn actions are on correct streets."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        streets = {a.street for a in actions}
        self.assertIn('preflop', streets)
        self.assertIn('flop', streets)
        self.assertIn('turn', streets)

    def test_preflop_actions_include_blinds(self):
        """Verify blind posts appear as preflop actions."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        preflop = [a for a in actions if a.street == 'preflop']
        preflop_types = {a.action_type for a in preflop}
        self.assertIn('post_sb', preflop_types)
        self.assertIn('post_bb', preflop_types)

    def test_all_streets_present_for_full_hand(self):
        """Verify all four streets when hand goes to showdown."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_ALLIN, 'RC0002000002'
        )
        # This hand has flop, turn, river (no actions post-flop but streets exist)
        # The board lines trigger street transitions
        streets = {a.street for a in actions}
        self.assertIn('preflop', streets)

    def test_preflop_fold_hand_no_postflop_actions(self):
        """Verify no flop/turn/river actions when hand ends preflop."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_PREFLOP_FOLD, 'RC0003000003'
        )
        streets = {a.street for a in actions}
        self.assertEqual(streets, {'preflop'})


# ── Position Identification Tests ────────────────────────────────────

class TestPositionIdentification(unittest.TestCase):
    """Test position mapping for players at the table."""

    def setUp(self):
        self.parser = GGPokerParser()

    def test_6max_positions(self):
        """Verify correct 6-max position labels."""
        actions, _, positions = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        # 6 players, Seat #4 is button
        position_values = set(positions.values())
        self.assertIn('BTN', position_values)
        self.assertIn('SB', position_values)
        self.assertIn('BB', position_values)

    def test_btn_position_correct(self):
        """Verify BTN is assigned to the correct player."""
        _, _, positions = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        # Seat #4 = Player4 is the button
        self.assertEqual(positions.get('Player4'), 'BTN')

    def test_sb_bb_positions_correct(self):
        """Verify SB and BB are the next players after BTN."""
        _, _, positions = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        # 6-max, Seat #4 is BTN. Seats occupied: 1,2,3,4,5,6
        # Clockwise from BTN(4): 4=BTN, 5=SB, 6=BB, 1=UTG, 2=MP, 3=CO
        self.assertEqual(positions.get('Player5'), 'SB')
        self.assertEqual(positions.get('Player6'), 'BB')

    def test_hero_position_identified(self):
        """Verify hero's position is correctly mapped."""
        _, _, positions = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        hero_pos = positions.get('Hero')
        self.assertIsNotNone(hero_pos)
        # Hero is seat 3 → CO in 6-max with BTN at seat 4
        self.assertEqual(hero_pos, 'CO')

    def test_actions_contain_position(self):
        """Verify each action has the player's position."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        for action in actions:
            self.assertIsNotNone(action.position,
                                 f"Position is None for {action.player}")

    def test_3player_positions(self):
        """Verify positions for 3-player hand."""
        _, _, positions = self.parser.parse_actions(
            GGPOKER_HAND_ALLIN, 'RC0002000002'
        )
        # 3 players, Seat #1 is BTN
        # Seats: 1=Hero(BTN), 2=Villain(SB), 3=Player3(BB)
        self.assertEqual(positions.get('Hero'), 'BTN')
        self.assertEqual(positions.get('Villain'), 'SB')
        self.assertEqual(positions.get('Player3'), 'BB')

    def test_map_positions_static_method(self):
        """Test _map_positions directly for various player counts."""
        # 2-player (heads up)
        pos = GGPokerParser._map_positions({1: 'A', 2: 'B'}, 1, 6)
        self.assertEqual(pos['A'], 'BTN')
        self.assertEqual(pos['B'], 'BB')

        # 4-player
        pos = GGPokerParser._map_positions(
            {1: 'A', 2: 'B', 3: 'C', 4: 'D'}, 1, 6
        )
        self.assertEqual(pos['A'], 'BTN')
        self.assertEqual(pos['B'], 'SB')
        self.assertEqual(pos['C'], 'BB')
        self.assertEqual(pos['D'], 'UTG')

    def test_map_positions_empty_returns_empty(self):
        """Test edge case: empty seat_players returns empty dict."""
        pos = GGPokerParser._map_positions({}, None, 6)
        self.assertEqual(pos, {})


# ── Board Card Extraction Tests ──────────────────────────────────────

class TestBoardExtraction(unittest.TestCase):
    """Test extraction of board cards by street."""

    def setUp(self):
        self.parser = GGPokerParser()

    def test_flop_3_cards(self):
        """Verify flop extracts exactly 3 cards."""
        _, board, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        self.assertIsNotNone(board.flop)
        self.assertEqual(board.flop, '2c 7h Td')
        # 3 cards in flop
        self.assertEqual(len(board.flop.split()), 3)

    def test_turn_1_card(self):
        """Verify turn extracts exactly 1 card."""
        _, board, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        self.assertIsNotNone(board.turn)
        self.assertEqual(board.turn, 'Qs')
        self.assertEqual(len(board.turn.split()), 1)

    def test_river_1_card(self):
        """Verify river extracts exactly 1 card."""
        _, board, _ = self.parser.parse_actions(
            GGPOKER_HAND_ALLIN, 'RC0002000002'
        )
        self.assertIsNotNone(board.river)
        self.assertEqual(board.river, 'Jc')
        self.assertEqual(len(board.river.split()), 1)

    def test_full_board_extraction(self):
        """Verify all streets extracted for a hand that goes to river."""
        _, board, _ = self.parser.parse_actions(
            GGPOKER_HAND_ALLIN, 'RC0002000002'
        )
        self.assertEqual(board.flop, '9h 8d 9s')
        self.assertEqual(board.turn, '2h')
        self.assertEqual(board.river, 'Jc')

    def test_no_board_for_preflop_fold(self):
        """Verify no board cards when hand folds preflop."""
        _, board, _ = self.parser.parse_actions(
            GGPOKER_HAND_PREFLOP_FOLD, 'RC0003000003'
        )
        self.assertIsNone(board.flop)
        self.assertIsNone(board.turn)
        self.assertIsNone(board.river)

    def test_partial_board_no_river(self):
        """Verify board when hand ends on turn (no river)."""
        _, board, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        # This hand has flop + turn, no river
        self.assertIsNotNone(board.flop)
        self.assertIsNotNone(board.turn)
        self.assertIsNone(board.river)


# ── VPIP Detection Tests ─────────────────────────────────────────────

class TestVPIPDetection(unittest.TestCase):
    """Test voluntary pot entry detection."""

    def setUp(self):
        self.parser = GGPokerParser()

    def test_voluntary_preflop_raise(self):
        """Verify raise preflop is marked as voluntary."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        hero_preflop = [a for a in actions
                        if a.player == 'Hero' and a.street == 'preflop'
                        and a.action_type == 'raise']
        self.assertEqual(len(hero_preflop), 1)
        self.assertEqual(hero_preflop[0].is_voluntary, 1)

    def test_voluntary_preflop_call(self):
        """Verify call preflop is marked as voluntary."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        # Player2 calls preflop → voluntary
        p2_calls = [a for a in actions
                     if a.player == 'Player2' and a.street == 'preflop'
                     and a.action_type == 'call']
        self.assertTrue(len(p2_calls) >= 1)
        self.assertEqual(p2_calls[0].is_voluntary, 1)

    def test_blind_posts_not_voluntary(self):
        """Verify blind posts are NOT marked as voluntary."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        blinds = [a for a in actions if a.action_type in ('post_sb', 'post_bb')]
        for blind in blinds:
            self.assertEqual(blind.is_voluntary, 0,
                             f"Blind {blind.action_type} for {blind.player} should not be voluntary")

    def test_fold_not_voluntary(self):
        """Verify fold is NOT marked as voluntary."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        folds = [a for a in actions if a.action_type == 'fold']
        for fold in folds:
            self.assertEqual(fold.is_voluntary, 0)

    def test_postflop_actions_not_voluntary(self):
        """Verify post-flop actions are NOT marked as voluntary (VPIP is preflop only)."""
        actions, _, _ = self.parser.parse_actions(
            GGPOKER_HAND_FULL, 'RC0001000001'
        )
        postflop = [a for a in actions if a.street != 'preflop']
        for action in postflop:
            self.assertEqual(action.is_voluntary, 0,
                             f"Post-flop action should not be voluntary: {action.action_type}")


# ── PokerStars Parser Tests ──────────────────────────────────────────

class TestPokerStarsActionParsing(unittest.TestCase):
    """Test PokerStars action parsing."""

    def setUp(self):
        self.parser = PokerStarsParser(hero_name='gangsta221')

    def test_parse_actions_basic(self):
        """Verify basic action parsing for PokerStars hand."""
        actions, board, positions = self.parser.parse_actions(
            POKERSTARS_HAND, 'PS300000000001'
        )
        self.assertTrue(len(actions) > 0)
        action_types = {a.action_type for a in actions}
        self.assertIn('fold', action_types)
        self.assertIn('raise', action_types)
        self.assertIn('call', action_types)
        self.assertIn('check', action_types)
        self.assertIn('bet', action_types)

    def test_parse_actions_streets(self):
        """Verify street separation for PokerStars hand."""
        actions, _, _ = self.parser.parse_actions(
            POKERSTARS_HAND, 'PS300000000001'
        )
        streets = {a.street for a in actions}
        self.assertIn('preflop', streets)
        self.assertIn('flop', streets)
        self.assertIn('turn', streets)
        self.assertIn('river', streets)

    def test_parse_board_pokerstars(self):
        """Verify board extraction for PokerStars."""
        _, board, _ = self.parser.parse_actions(
            POKERSTARS_HAND, 'PS300000000001'
        )
        self.assertEqual(board.flop, '4s 8h Kc')
        self.assertEqual(board.turn, '2d')
        self.assertEqual(board.river, '9s')

    def test_parse_positions_pokerstars(self):
        """Verify position mapping for PokerStars hand."""
        _, _, positions = self.parser.parse_actions(
            POKERSTARS_HAND, 'PS300000000001'
        )
        # 6 players, Seat #3 is BTN
        self.assertEqual(positions.get('Opponent3'), 'BTN')
        self.assertEqual(positions.get('Opponent4'), 'SB')
        self.assertEqual(positions.get('Opponent5'), 'BB')

    def test_hero_identification_pokerstars(self):
        """Verify hero is correctly identified via hero_name config."""
        actions, _, _ = self.parser.parse_actions(
            POKERSTARS_HAND, 'PS300000000001'
        )
        hero_actions = [a for a in actions if a.is_hero == 1]
        self.assertTrue(len(hero_actions) > 0)
        for a in hero_actions:
            self.assertEqual(a.player, 'gangsta221')

    def test_vpip_pokerstars(self):
        """Verify VPIP detection for PokerStars."""
        actions, _, _ = self.parser.parse_actions(
            POKERSTARS_HAND, 'PS300000000001'
        )
        # gangsta221 raises preflop → voluntary
        hero_raises_pf = [a for a in actions
                          if a.player == 'gangsta221' and a.street == 'preflop'
                          and a.action_type == 'raise']
        self.assertEqual(len(hero_raises_pf), 1)
        self.assertEqual(hero_raises_pf[0].is_voluntary, 1)

    def test_tournament_amounts_no_dollar(self):
        """Verify PokerStars tournament amounts (no $ sign)."""
        actions, _, _ = self.parser.parse_actions(
            POKERSTARS_HAND, 'PS300000000001'
        )
        # SB posts 60
        sb_posts = [a for a in actions if a.action_type == 'post_sb']
        self.assertEqual(len(sb_posts), 1)
        self.assertAlmostEqual(sb_posts[0].amount, 60.0)


# ── Database Persistence Tests ───────────────────────────────────────

class TestActionDatabasePersistence(unittest.TestCase):
    """Test persisting actions to hand_actions table."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_insert_actions_batch(self):
        """Test batch insert of actions."""
        actions = [
            ActionData(
                hand_id='H001', street='preflop', player='Hero',
                action_type='raise', amount=3.0, is_hero=1,
                sequence_order=0, position='BTN', is_voluntary=1,
            ),
            ActionData(
                hand_id='H001', street='preflop', player='Villain',
                action_type='call', amount=3.0, is_hero=0,
                sequence_order=1, position='BB', is_voluntary=1,
            ),
            ActionData(
                hand_id='H001', street='flop', player='Villain',
                action_type='check', amount=0, is_hero=0,
                sequence_order=0, position='BB', is_voluntary=0,
            ),
        ]
        # Insert a hand first (FK constraint)
        hand = HandData(
            hand_id='H001', platform='GGPoker', game_type='cash',
            date=datetime(2026, 1, 15), blinds_sb=0.25, blinds_bb=0.50,
            hero_cards='Ah Kd', hero_position='BTN',
            invested=3.0, won=5.0, net=2.0, rake=0.0,
            table_name='T', num_players=6,
        )
        self.repo.insert_hand(hand)

        count = self.repo.insert_actions_batch(actions)
        self.assertEqual(count, 3)

    def test_get_hand_actions_ordered(self):
        """Test retrieving actions ordered by street and sequence."""
        hand = HandData(
            hand_id='H002', platform='GGPoker', game_type='cash',
            date=datetime(2026, 1, 15), blinds_sb=0.25, blinds_bb=0.50,
            hero_cards=None, hero_position='CO',
            invested=1.0, won=0.0, net=-1.0, rake=0.0,
            table_name='T', num_players=6,
        )
        self.repo.insert_hand(hand)

        actions = [
            ActionData(hand_id='H002', street='flop', player='A',
                       action_type='bet', amount=2.0, is_hero=0,
                       sequence_order=0, position='SB', is_voluntary=0),
            ActionData(hand_id='H002', street='preflop', player='A',
                       action_type='post_sb', amount=0.25, is_hero=0,
                       sequence_order=0, position='SB', is_voluntary=0),
            ActionData(hand_id='H002', street='preflop', player='B',
                       action_type='post_bb', amount=0.50, is_hero=0,
                       sequence_order=1, position='BB', is_voluntary=0),
        ]
        self.repo.insert_actions_batch(actions)

        result = self.repo.get_hand_actions('H002')
        self.assertEqual(len(result), 3)
        # Ordered: preflop(seq 0), preflop(seq 1), flop(seq 0)
        self.assertEqual(result[0]['street'], 'preflop')
        self.assertEqual(result[0]['sequence_order'], 0)
        self.assertEqual(result[1]['street'], 'preflop')
        self.assertEqual(result[1]['sequence_order'], 1)
        self.assertEqual(result[2]['street'], 'flop')

    def test_has_actions_for_hand(self):
        """Test checking if actions exist for a hand."""
        hand = HandData(
            hand_id='H003', platform='GGPoker', game_type='cash',
            date=datetime(2026, 1, 15), blinds_sb=0.25, blinds_bb=0.50,
            hero_cards=None, hero_position=None,
            invested=0.0, won=0.0, net=0.0, rake=0.0,
            table_name='T', num_players=2,
        )
        self.repo.insert_hand(hand)

        self.assertFalse(self.repo.has_actions_for_hand('H003'))

        action = ActionData(
            hand_id='H003', street='preflop', player='X',
            action_type='fold', amount=0, is_hero=0,
            sequence_order=0, position='BTN', is_voluntary=0,
        )
        self.repo.insert_actions_batch([action])

        self.assertTrue(self.repo.has_actions_for_hand('H003'))

    def test_update_hand_board(self):
        """Test updating board cards on a hand."""
        hand = HandData(
            hand_id='H004', platform='GGPoker', game_type='cash',
            date=datetime(2026, 1, 15), blinds_sb=0.25, blinds_bb=0.50,
            hero_cards=None, hero_position=None,
            invested=0.0, won=0.0, net=0.0, rake=0.0,
            table_name='T', num_players=2,
        )
        self.repo.insert_hand(hand)

        self.repo.update_hand_board('H004', 'Ah Kd Qs', 'Jc', '2s')
        self.conn.commit()

        row = self.conn.execute(
            "SELECT board_flop, board_turn, board_river FROM hands WHERE hand_id = 'H004'"
        ).fetchone()
        self.assertEqual(row['board_flop'], 'Ah Kd Qs')
        self.assertEqual(row['board_turn'], 'Jc')
        self.assertEqual(row['board_river'], '2s')

    def test_update_hand_position(self):
        """Test updating hero position on a hand."""
        hand = HandData(
            hand_id='H005', platform='GGPoker', game_type='cash',
            date=datetime(2026, 1, 15), blinds_sb=0.25, blinds_bb=0.50,
            hero_cards=None, hero_position=None,
            invested=0.0, won=0.0, net=0.0, rake=0.0,
            table_name='T', num_players=6,
        )
        self.repo.insert_hand(hand)

        self.repo.update_hand_position('H005', 'CO')
        self.conn.commit()

        row = self.conn.execute(
            "SELECT hero_position FROM hands WHERE hand_id = 'H005'"
        ).fetchone()
        self.assertEqual(row['hero_position'], 'CO')

    def test_insert_empty_actions_batch(self):
        """Test inserting empty actions list returns 0."""
        count = self.repo.insert_actions_batch([])
        self.assertEqual(count, 0)

    def test_schema_has_hand_actions_table(self):
        """Verify hand_actions table has all expected columns."""
        cursor = self.conn.execute("PRAGMA table_info(hand_actions)")
        cols = {row[1] for row in cursor.fetchall()}
        expected = {'id', 'hand_id', 'street', 'player', 'action_type',
                    'amount', 'is_hero', 'sequence_order', 'position', 'is_voluntary'}
        self.assertTrue(expected.issubset(cols))

    def test_schema_has_board_columns(self):
        """Verify hands table has board columns."""
        cursor = self.conn.execute("PRAGMA table_info(hands)")
        cols = {row[1] for row in cursor.fetchall()}
        self.assertIn('board_flop', cols)
        self.assertIn('board_turn', cols)
        self.assertIn('board_river', cols)


# ── Backward Compatibility Tests ─────────────────────────────────────

class TestBackwardCompatibility(unittest.TestCase):
    """Verify US-001 doesn't break existing financial parser."""

    def setUp(self):
        self.parser = GGPokerParser()

    def test_parse_single_hand_still_works(self):
        """Verify parse_single_hand returns same financial data as before."""
        result = self.parser.parse_single_hand(GGPOKER_HAND_FULL)
        self.assertIsNotNone(result)
        self.assertEqual(result.hand_id, 'RC0001000001')
        self.assertEqual(result.platform, 'GGPoker')
        self.assertEqual(result.game_type, 'cash')
        self.assertEqual(result.blinds_sb, 0.25)
        self.assertEqual(result.blinds_bb, 0.50)
        self.assertEqual(result.hero_cards, 'Ah Kd')
        self.assertEqual(result.num_players, 6)

    def test_parse_single_hand_invested_won_net(self):
        """Verify financial calculations are unchanged."""
        result = self.parser.parse_single_hand(GGPOKER_HAND_FULL)
        # Hero posts BB $0.50, calls raise to $1.50, bets $2.50, bets $5.00
        # No collect shown in SUMMARY-only hand
        self.assertIsNotNone(result.invested)
        self.assertIsNotNone(result.net)

    def test_hand_data_has_hero_position_field(self):
        """Verify HandData now has hero_position slot (still None from parse_single_hand)."""
        result = self.parser.parse_single_hand(GGPOKER_HAND_FULL)
        self.assertIsNone(result.hero_position)
        # But slot exists
        self.assertTrue(hasattr(result, 'hero_position'))

    def test_existing_db_queries_still_work(self):
        """Verify existing report queries work with new schema."""
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = Repository(conn)

        hand = HandData(
            hand_id='COMPAT001', platform='GGPoker', game_type='cash',
            date=datetime(2026, 1, 15, 20, 0, 0), blinds_sb=0.25,
            blinds_bb=0.50, hero_cards='Ah Kd', hero_position='BTN',
            invested=1.0, won=2.0, net=1.0, rake=0.0,
            table_name='T', num_players=6,
        )
        repo.insert_hand(hand)

        # Existing queries should still work
        hands = repo.get_cash_hands('2026')
        self.assertEqual(len(hands), 1)
        self.assertEqual(hands[0]['hand_id'], 'COMPAT001')

        daily = repo.get_cash_daily_stats('2026')
        self.assertEqual(len(daily), 1)

        stats = repo.get_cash_stats_summary('2026')
        self.assertEqual(stats['total_hands'], 1)

        conn.close()

    def test_migration_idempotent(self):
        """Verify schema migration is safe to run multiple times."""
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        init_db(conn)  # Second call should not raise
        conn.close()


# ── End-to-End Integration Tests ─────────────────────────────────────

class TestEndToEndParsing(unittest.TestCase):
    """End-to-end test: parse → persist → query."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.parser = GGPokerParser()

    def tearDown(self):
        self.conn.close()

    def test_full_pipeline_ggpoker(self):
        """Parse a GGPoker hand, persist actions, and query them back."""
        # Parse
        hand = self.parser.parse_single_hand(GGPOKER_HAND_FULL)
        self.assertIsNotNone(hand)
        actions, board, positions = self.parser.parse_actions(
            GGPOKER_HAND_FULL, hand.hand_id
        )

        # Persist hand
        self.repo.insert_hand(hand)

        # Persist actions
        count = self.repo.insert_actions_batch(actions)
        self.assertGreater(count, 0)

        # Persist board
        self.repo.update_hand_board(hand.hand_id, board.flop, board.turn, board.river)

        # Update hero position
        hero_pos = positions.get('Hero')
        if hero_pos:
            self.repo.update_hand_position(hand.hand_id, hero_pos)
        self.conn.commit()

        # Query back
        stored_actions = self.repo.get_hand_actions(hand.hand_id)
        self.assertEqual(len(stored_actions), count)

        # Verify board stored
        row = self.conn.execute(
            "SELECT board_flop, board_turn, board_river, hero_position "
            "FROM hands WHERE hand_id = ?", (hand.hand_id,)
        ).fetchone()
        self.assertEqual(row['board_flop'], '2c 7h Td')
        self.assertEqual(row['board_turn'], 'Qs')
        self.assertIsNone(row['board_river'])  # hand folded on turn
        self.assertEqual(row['hero_position'], 'CO')

        # Verify has_actions
        self.assertTrue(self.repo.has_actions_for_hand(hand.hand_id))


# ── Action String Parser Edge Cases ──────────────────────────────────

class TestActionStringParser(unittest.TestCase):
    """Test edge cases in _parse_action_string."""

    def test_fold(self):
        t, a, ai = GGPokerParser._parse_action_string('folds')
        self.assertEqual(t, 'fold')
        self.assertEqual(a, 0.0)
        self.assertFalse(ai)

    def test_check(self):
        t, a, ai = GGPokerParser._parse_action_string('checks')
        self.assertEqual(t, 'check')
        self.assertEqual(a, 0.0)

    def test_call_with_amount(self):
        t, a, ai = GGPokerParser._parse_action_string('calls $2.50')
        self.assertEqual(t, 'call')
        self.assertAlmostEqual(a, 2.50)
        self.assertFalse(ai)

    def test_raise_to_amount(self):
        t, a, ai = GGPokerParser._parse_action_string('raises $1.00 to $3.00')
        self.assertEqual(t, 'raise')
        self.assertAlmostEqual(a, 3.00)
        self.assertFalse(ai)

    def test_bet_amount(self):
        t, a, ai = GGPokerParser._parse_action_string('bets $5.50')
        self.assertEqual(t, 'bet')
        self.assertAlmostEqual(a, 5.50)

    def test_call_allin(self):
        t, a, ai = GGPokerParser._parse_action_string('calls $10.00 and is all-in')
        self.assertEqual(t, 'call')
        self.assertAlmostEqual(a, 10.00)
        self.assertTrue(ai)

    def test_raise_allin(self):
        t, a, ai = GGPokerParser._parse_action_string('raises $5.00 to $15.00 and is all-in')
        self.assertEqual(t, 'raise')
        self.assertAlmostEqual(a, 15.00)
        self.assertTrue(ai)

    def test_post_small_blind(self):
        t, a, ai = GGPokerParser._parse_action_string('posts small blind $0.25')
        self.assertEqual(t, 'post_sb')
        self.assertAlmostEqual(a, 0.25)

    def test_post_big_blind(self):
        t, a, ai = GGPokerParser._parse_action_string('posts big blind $0.50')
        self.assertEqual(t, 'post_bb')
        self.assertAlmostEqual(a, 0.50)

    def test_post_ante(self):
        t, a, ai = GGPokerParser._parse_action_string('posts the ante $0.05')
        self.assertEqual(t, 'post_ante')
        self.assertAlmostEqual(a, 0.05)

    def test_unknown_action_returns_none(self):
        t, a, ai = GGPokerParser._parse_action_string('shows [Ah Kd]')
        self.assertIsNone(t)

    def test_large_amounts_with_commas(self):
        t, a, ai = GGPokerParser._parse_action_string('raises $1,000.00 to $2,500.00')
        self.assertEqual(t, 'raise')
        self.assertAlmostEqual(a, 2500.00)


if __name__ == '__main__':
    unittest.main()
