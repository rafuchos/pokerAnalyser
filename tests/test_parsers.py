"""Tests for parser modules."""

import unittest
from src.parsers.ggpoker import GGPokerParser
from src.parsers.pokerstars import PokerStarsParser


class TestGGPokerCashParser(unittest.TestCase):
    """Test GGPoker cash hand parsing."""

    def setUp(self):
        self.parser = GGPokerParser()

    def test_parse_single_hand_basic(self):
        """Test parsing a basic GGPoker cash hand."""
        hand_text = (
            "Poker Hand #TM1234567890: Hold'em No Limit ($0.25/$0.50) - "
            "2026/01/15 20:30:00\n"
            "Table 'RushAndCash123' 6-max Seat #1 is the button\n"
            "Seat 1: Player1 ($50.00 in chips)\n"
            "Seat 2: Hero ($50.00 in chips)\n"
            "Seat 3: Player3 ($50.00 in chips)\n"
            "Player1: posts small blind $0.25\n"
            "Hero: posts big blind $0.50\n"
            "*** HOLE CARDS ***\n"
            "Dealt to Hero [Ah Kd]\n"
            "Player3: folds\n"
            "Player1: raises $0.50 to $1.00\n"
            "Hero: calls $0.50\n"
            "*** FLOP *** [2c 7h Td]\n"
            "Player1: checks\n"
            "Hero: checks\n"
            "*** TURN *** [2c 7h Td] [Qs]\n"
            "Player1: checks\n"
            "Hero: checks\n"
            "*** RIVER *** [2c 7h Td Qs] [3d]\n"
            "Player1: checks\n"
            "Hero: checks\n"
            "*** SHOW DOWN ***\n"
            "Hero collected $1.90 from pot\n"
        )

        result = self.parser.parse_single_hand(hand_text)
        self.assertIsNotNone(result)
        self.assertEqual(result.hand_id, 'TM1234567890')
        self.assertEqual(result.platform, 'GGPoker')
        self.assertEqual(result.game_type, 'cash')
        self.assertEqual(result.blinds_sb, 0.25)
        self.assertEqual(result.blinds_bb, 0.50)
        self.assertEqual(result.hero_cards, 'Ah Kd')
        self.assertEqual(result.num_players, 3)
        self.assertAlmostEqual(result.invested, 1.00, places=2)
        self.assertAlmostEqual(result.won, 1.90, places=2)
        self.assertAlmostEqual(result.net, 0.90, places=2)

    def test_parse_hand_no_hero(self):
        """Test parsing a hand where Hero is not present."""
        hand_text = "Some random text without hand header"
        result = self.parser.parse_single_hand(hand_text)
        self.assertIsNone(result)

    def test_parse_tournament_hand(self):
        """Test parsing a GGPoker tournament hand."""
        hand_text = (
            "Poker Hand #TM9999999999: Tournament #123456789, "
            "$15 Bounty Hunters Hold'em No Limit - Level5(100/200) - "
            "2026/02/10 19:00:00\n"
            "Table '123456789 1' 9-max Seat #3 is the button\n"
            "Seat 1: Hero (5000 in chips)\n"
            "Seat 2: Player2 (3000 in chips)\n"
            "*** HOLE CARDS ***\n"
            "Hero: folds\n"
        )

        result = self.parser.parse_tournament_hand(hand_text)
        self.assertIsNotNone(result)
        self.assertEqual(result['hand_id'], 'TM9999999999')
        self.assertEqual(result['tournament_id'], '123456789')
        self.assertEqual(result['stack'], 5000)


class TestGGPokerSummaryParser(unittest.TestCase):
    """Test GGPoker tournament summary parsing."""

    def setUp(self):
        self.parser = GGPokerParser()

    def test_parse_summary_bounty(self):
        """Test parsing a bounty tournament summary."""
        import tempfile
        import os

        content = (
            "Tournament #252416926, $15 Bounty Hunters Holiday Special, Hold'em No Limit\n"
            "Buy-in: $6.8+$1.2+$7\n"
            "3 Players\n"
            "1st : Hero, $20.00\n"
            "Tournament started 2026/01/20 20:00:00\n"
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False,
                                          encoding='utf-8') as f:
            f.write(content)
            tmppath = f.name

        try:
            result = self.parser.parse_summary_file(tmppath)
            self.assertIsNotNone(result)
            self.assertEqual(result.tournament_id, '252416926')
            self.assertEqual(result.platform, 'GGPoker')
            self.assertAlmostEqual(result.buy_in, 6.8, places=1)
            self.assertAlmostEqual(result.rake, 1.2, places=1)
            self.assertAlmostEqual(result.bounty, 7.0, places=1)
            self.assertTrue(result.is_bounty)
            self.assertEqual(result.position, 1)
            self.assertAlmostEqual(result.prize, 20.0, places=2)
        finally:
            os.unlink(tmppath)


class TestPokerStarsParser(unittest.TestCase):
    """Test PokerStars parser."""

    def setUp(self):
        self.parser = PokerStarsParser(hero_name='gangsta221')

    def test_parse_single_hand(self):
        """Test parsing a PokerStars tournament hand."""
        hand_text = (
            "PokerStars Hand #259735656512: Tournament #3974101287, "
            "$7.20+$7.50+$1.80 USD Hold'em No Limit - Level VII (60/120) - "
            "2026/02/15 11:46:00 BRT\n"
            "Table '3974101287 1' 9-max Seat #5 is the button\n"
            "Seat 1: gangsta221 (5000 in chips)\n"
            "Seat 2: Player2 (3000 in chips)\n"
            "*** HOLE CARDS ***\n"
            "gangsta221: folds\n"
        )

        result = self.parser._parse_single_hand(
            hand_text, 'PS3974101287', '[PS] Test'
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['hand_id'], 'PS259735656512')
        self.assertEqual(result['level'], 7)
        self.assertEqual(result['stack'], 5000)


if __name__ == '__main__':
    unittest.main()
