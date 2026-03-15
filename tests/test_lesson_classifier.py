"""Tests for Lesson Classifier Engine (US-039).

Covers: LessonClassifier detection rules, LessonMatch dataclass,
bulk classification pipeline, CLI command, and schema extensions.
"""

import json
import sqlite3
import subprocess
import sys
import unittest

from src.db.schema import init_db
from src.db.repository import Repository
from src.db.seed_lessons import REGLIFE_LESSONS
from src.parsers.base import ActionData, HandData
from src.analyzers.lesson_classifier import LessonClassifier, LessonMatch


# ── Test Helpers ─────────────────────────────────────────────────────


def _make_hand(hand_id, position='BTN', game_type='cash', hero_cards='Ah Kd',
               blinds_bb=0.50, hero_stack=50.0, board_flop=None,
               board_turn=None, board_river=None, tournament_id=None,
               num_players=6, net=0.0):
    """Create a HandData for testing."""
    h = HandData(
        hand_id=hand_id,
        platform='GGPoker',
        game_type=game_type,
        date='2026-01-15T20:00:00',
        blinds_sb=blinds_bb / 2,
        blinds_bb=blinds_bb,
        hero_cards=hero_cards,
        hero_position=position,
        invested=1.0,
        won=1.0 + net,
        net=net,
        rake=0.0,
        table_name='TestTable',
        num_players=num_players,
    )
    h.tournament_id = tournament_id
    h.hero_stack = hero_stack
    return h


def _insert_hand(repo, hand_id, position='BTN', game_type='cash',
                 board_flop=None, board_turn=None, board_river=None,
                 hero_stack=50.0, blinds_bb=0.50, tournament_id=None,
                 num_players=6, net=0.0):
    """Insert a hand with optional board cards."""
    hand = _make_hand(hand_id, position=position, game_type=game_type,
                      hero_stack=hero_stack, blinds_bb=blinds_bb,
                      tournament_id=tournament_id, num_players=num_players,
                      net=net)
    repo.insert_hand(hand)
    # Update board and net via direct SQL
    repo.conn.execute(
        "UPDATE hands SET board_flop=?, board_turn=?, board_river=?, net=? "
        "WHERE hand_id=?",
        (board_flop, board_turn, board_river, net, hand_id)
    )
    repo.conn.commit()
    return hand


def _insert_action(repo, hand_id, street, player, action_type, amount=0,
                   is_hero=0, seq=0, position=''):
    """Insert a single action."""
    repo.conn.execute(
        "INSERT INTO hand_actions (hand_id, street, player, action_type, "
        "amount, is_hero, sequence_order, position) VALUES (?,?,?,?,?,?,?,?)",
        (hand_id, street, player, action_type, amount, is_hero, seq, position)
    )
    repo.conn.commit()


def _get_hand_dict(repo, hand_id):
    """Read hand as dict from DB."""
    row = repo.conn.execute(
        "SELECT * FROM hands WHERE hand_id=?", (hand_id,)
    ).fetchone()
    return dict(row) if row else None


# ── LessonMatch Dataclass Tests ──────────────────────────────────────


class TestLessonMatch(unittest.TestCase):
    """Test LessonMatch dataclass."""

    def test_create_basic(self):
        m = LessonMatch(hand_id='H1', lesson_id=1, street='preflop',
                        executed_correctly=1)
        self.assertEqual(m.hand_id, 'H1')
        self.assertEqual(m.lesson_id, 1)
        self.assertEqual(m.street, 'preflop')
        self.assertEqual(m.executed_correctly, 1)
        self.assertEqual(m.confidence, 1.0)
        self.assertEqual(m.notes, '')

    def test_defaults(self):
        m = LessonMatch(hand_id='H2', lesson_id=2, street=None,
                        executed_correctly=None)
        self.assertIsNone(m.street)
        self.assertIsNone(m.executed_correctly)
        self.assertEqual(m.confidence, 1.0)

    def test_custom_confidence(self):
        m = LessonMatch(hand_id='H3', lesson_id=3, street='flop',
                        executed_correctly=0, confidence=0.5, notes='test')
        self.assertEqual(m.confidence, 0.5)
        self.assertEqual(m.notes, 'test')


# ── Schema Extension Tests ───────────────────────────────────────────


class TestHandLessonsSchema(unittest.TestCase):
    """Test hand_lessons table has new columns."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_hand_lessons_has_street_column(self):
        cols = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(hand_lessons)").fetchall()}
        self.assertIn('street', cols)

    def test_hand_lessons_has_executed_correctly_column(self):
        cols = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(hand_lessons)").fetchall()}
        self.assertIn('executed_correctly', cols)

    def test_hand_lessons_has_confidence_column(self):
        cols = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(hand_lessons)").fetchall()}
        self.assertIn('confidence', cols)

    def test_link_with_new_columns(self):
        repo = Repository(self.conn)
        hand = _make_hand('SCHEMA001')
        repo.insert_hand(hand)
        row_id = repo.link_hand_to_lesson(
            'SCHEMA001', 1, street='preflop',
            executed_correctly=1, confidence=0.9, notes='test')
        self.assertGreater(row_id, 0)

        row = self.conn.execute(
            "SELECT * FROM hand_lessons WHERE id=?", (row_id,)
        ).fetchone()
        self.assertEqual(row['street'], 'preflop')
        self.assertEqual(row['executed_correctly'], 1)
        self.assertAlmostEqual(row['confidence'], 0.9)


# ── Repository Extension Tests ───────────────────────────────────────


class TestRepositoryExtensions(unittest.TestCase):
    """Test new repository methods for classification."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_bulk_link_hand_lessons(self):
        hand = _make_hand('BULK001')
        self.repo.insert_hand(hand)
        links = [
            ('BULK001', 1, 'preflop', 1, 1.0, 'note1'),
            ('BULK001', 2, 'flop', 0, 0.8, 'note2'),
        ]
        count = self.repo.bulk_link_hand_lessons(links)
        self.assertEqual(count, 2)
        lessons = self.repo.get_lessons_for_hand('BULK001')
        self.assertEqual(len(lessons), 2)

    def test_clear_hand_lessons(self):
        hand = _make_hand('CLEAR001')
        self.repo.insert_hand(hand)
        self.repo.link_hand_to_lesson('CLEAR001', 1)
        self.repo.link_hand_to_lesson('CLEAR001', 2)
        self.assertEqual(self.repo.get_lesson_hand_count(1), 1)

        cleared = self.repo.clear_hand_lessons()
        self.assertEqual(cleared, 2)
        self.assertEqual(self.repo.get_lesson_hand_count(1), 0)

    def test_get_all_hands_for_classification(self):
        hand1 = _make_hand('CLASS001')
        hand2 = _make_hand('CLASS002')
        self.repo.insert_hand(hand1)
        self.repo.insert_hand(hand2)
        hands = self.repo.get_all_hands_for_classification()
        self.assertEqual(len(hands), 2)
        self.assertIn('hand_id', hands[0])
        self.assertIn('hero_position', hands[0])
        self.assertIn('hero_stack', hands[0])

    def test_get_all_actions_for_classification(self):
        hand = _make_hand('ACT001')
        self.repo.insert_hand(hand)
        _insert_action(self.repo, 'ACT001', 'preflop', 'Hero', 'raise',
                       1.5, is_hero=1, seq=1, position='BTN')
        _insert_action(self.repo, 'ACT001', 'preflop', 'Villain', 'call',
                       1.5, is_hero=0, seq=2, position='BB')

        actions = self.repo.get_all_actions_for_classification()
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]['hand_id'], 'ACT001')


# ── Preflop Detection Tests ──────────────────────────────────────────


class TestPreflopDetection(unittest.TestCase):
    """Test preflop lesson classification rules."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _lesson_ids(self, matches):
        """Get sort_order values from matches."""
        return [m.lesson_id for m in matches]

    # -- Lesson 1: RFI --

    def test_rfi_from_btn(self):
        """Hero opens from BTN = RFI."""
        _insert_hand(self.repo, 'RFI001', position='BTN')
        _insert_action(self.repo, 'RFI001', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'RFI001', 'preflop', 'P2', 'fold', 0, 0, 2, 'MP')
        _insert_action(self.repo, 'RFI001', 'preflop', 'P3', 'fold', 0, 0, 3, 'CO')
        _insert_action(self.repo, 'RFI001', 'preflop', 'Hero', 'raise', 1.5, 1, 4, 'BTN')
        _insert_action(self.repo, 'RFI001', 'preflop', 'P4', 'fold', 0, 0, 5, 'SB')
        _insert_action(self.repo, 'RFI001', 'preflop', 'P5', 'call', 1.5, 0, 6, 'BB')

        matches = self._classify('RFI001')
        ids = self._lesson_ids(matches)
        self.assertIn(1, ids)  # RFI
        rfi = next(m for m in matches if m.lesson_id == 1)
        self.assertEqual(rfi.street, 'preflop')
        self.assertEqual(rfi.executed_correctly, 1)

    def test_rfi_from_utg(self):
        """Hero opens from UTG = RFI."""
        _insert_hand(self.repo, 'RFI002', position='UTG')
        _insert_action(self.repo, 'RFI002', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'UTG')
        _insert_action(self.repo, 'RFI002', 'preflop', 'P1', 'fold', 0, 0, 2, 'MP')

        matches = self._classify('RFI002')
        self.assertIn(1, self._lesson_ids(matches))

    # -- Lesson 2: Flat / 3-Bet --

    def test_flat_call(self):
        """Hero calls an open raise = Flat."""
        _insert_hand(self.repo, 'FLAT001', position='BTN')
        _insert_action(self.repo, 'FLAT001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'FLAT001', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BTN')

        matches = self._classify('FLAT001')
        self.assertIn(2, self._lesson_ids(matches))

    def test_3bet(self):
        """Hero 3-bets an open raise."""
        _insert_hand(self.repo, '3BET001', position='BTN')
        _insert_action(self.repo, '3BET001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, '3BET001', 'preflop', 'Hero', 'raise', 4.5, 1, 2, 'BTN')

        matches = self._classify('3BET001')
        ids = self._lesson_ids(matches)
        self.assertIn(2, ids)  # Flat/3-Bet lesson

    # -- Lesson 3: Reaction vs 3-Bet --

    def test_reaction_vs_3bet(self):
        """Hero opens, gets 3-bet, reacts."""
        _insert_hand(self.repo, 'R3B001', position='CO')
        _insert_action(self.repo, 'R3B001', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'R3B001', 'preflop', 'Hero', 'raise', 1.5, 1, 2, 'CO')
        _insert_action(self.repo, 'R3B001', 'preflop', 'P2', 'raise', 4.5, 0, 3, 'BTN')
        _insert_action(self.repo, 'R3B001', 'preflop', 'P3', 'fold', 0, 0, 4, 'SB')
        _insert_action(self.repo, 'R3B001', 'preflop', 'P4', 'fold', 0, 0, 5, 'BB')
        _insert_action(self.repo, 'R3B001', 'preflop', 'Hero', 'call', 4.5, 1, 6, 'CO')

        matches = self._classify('R3B001')
        ids = self._lesson_ids(matches)
        self.assertIn(1, ids)  # RFI
        self.assertIn(3, ids)  # Reaction vs 3-Bet

    # -- Lesson 4: Open Shove cEV 10BB --

    def test_open_shove_10bb(self):
        """Hero open shoves with 8BB stack."""
        _insert_hand(self.repo, 'SHOVE001', position='BTN', game_type='tournament',
                     hero_stack=4.0, blinds_bb=0.50)
        _insert_action(self.repo, 'SHOVE001', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'SHOVE001', 'preflop', 'Hero', 'all-in', 4.0, 1, 2, 'BTN')

        matches = self._classify('SHOVE001')
        ids = self._lesson_ids(matches)
        self.assertIn(4, ids)  # Open Shove cEV 10BB
        shove = next(m for m in matches if m.lesson_id == 4)
        self.assertEqual(shove.executed_correctly, 1)

    # -- Lesson 5: Squeeze --

    def test_squeeze(self):
        """Hero squeezes after open + call."""
        _insert_hand(self.repo, 'SQZ001', position='CO')
        _insert_action(self.repo, 'SQZ001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'SQZ001', 'preflop', 'P2', 'call', 1.5, 0, 2, 'MP')
        _insert_action(self.repo, 'SQZ001', 'preflop', 'Hero', 'raise', 6.0, 1, 3, 'CO')

        matches = self._classify('SQZ001')
        ids = self._lesson_ids(matches)
        self.assertIn(5, ids)  # Squeeze

    # -- Lesson 6: BB Pré-Flop --

    def test_bb_preflop(self):
        """Hero is BB and acts preflop."""
        _insert_hand(self.repo, 'BB001', position='BB')
        _insert_action(self.repo, 'BB001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'BB001', 'preflop', 'P2', 'fold', 0, 0, 2, 'SB')
        _insert_action(self.repo, 'BB001', 'preflop', 'Hero', 'call', 1.5, 1, 3, 'BB')

        matches = self._classify('BB001')
        ids = self._lesson_ids(matches)
        self.assertIn(6, ids)  # BB Pré-Flop

    # -- Lesson 7: Blind War SB vs BB --

    def test_sb_vs_bb_blind_war(self):
        """SB opens, all others fold = blind war."""
        _insert_hand(self.repo, 'BW001', position='SB')
        _insert_action(self.repo, 'BW001', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'BW001', 'preflop', 'P2', 'fold', 0, 0, 2, 'MP')
        _insert_action(self.repo, 'BW001', 'preflop', 'P3', 'fold', 0, 0, 3, 'CO')
        _insert_action(self.repo, 'BW001', 'preflop', 'P4', 'fold', 0, 0, 4, 'BTN')
        _insert_action(self.repo, 'BW001', 'preflop', 'Hero', 'raise', 1.5, 1, 5, 'SB')
        _insert_action(self.repo, 'BW001', 'preflop', 'P5', 'call', 1.5, 0, 6, 'BB')

        matches = self._classify('BW001')
        ids = self._lesson_ids(matches)
        self.assertIn(7, ids)  # SB vs BB

    # -- Lesson 8: Multiway BB --

    def test_multiway_bb(self):
        """BB defends in multiway pot."""
        _insert_hand(self.repo, 'MW001', position='BB')
        _insert_action(self.repo, 'MW001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'MW001', 'preflop', 'P2', 'call', 1.5, 0, 2, 'MP')
        _insert_action(self.repo, 'MW001', 'preflop', 'P3', 'call', 1.5, 0, 3, 'BTN')
        _insert_action(self.repo, 'MW001', 'preflop', 'P4', 'fold', 0, 0, 4, 'SB')
        _insert_action(self.repo, 'MW001', 'preflop', 'Hero', 'call', 1.5, 1, 5, 'BB')

        matches = self._classify('MW001')
        ids = self._lesson_ids(matches)
        self.assertIn(8, ids)  # Multiway BB

    # -- Lesson 9: Blind War BB vs SB --

    def test_bb_vs_sb_blind_war(self):
        """BB faces SB steal in blind war."""
        _insert_hand(self.repo, 'BW002', position='BB')
        _insert_action(self.repo, 'BW002', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'BW002', 'preflop', 'P2', 'fold', 0, 0, 2, 'MP')
        _insert_action(self.repo, 'BW002', 'preflop', 'P3', 'fold', 0, 0, 3, 'CO')
        _insert_action(self.repo, 'BW002', 'preflop', 'P4', 'fold', 0, 0, 4, 'BTN')
        _insert_action(self.repo, 'BW002', 'preflop', 'P5', 'raise', 1.5, 0, 5, 'SB')
        _insert_action(self.repo, 'BW002', 'preflop', 'Hero', 'call', 1.5, 1, 6, 'BB')

        matches = self._classify('BW002')
        ids = self._lesson_ids(matches)
        self.assertIn(9, ids)  # BB vs SB


# ── Postflop Detection Tests ────────────────────────────────────────


class TestPostflopDetection(unittest.TestCase):
    """Test postflop lesson classification rules."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _lesson_ids(self, matches):
        return [m.lesson_id for m in matches]

    # -- Lesson 10: Intro Pós-Flop --

    def test_any_postflop_hand(self):
        """Any hand with flop = lesson 10."""
        _insert_hand(self.repo, 'PF001', position='BTN',
                     board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'PF001', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'PF001', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'PF001', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'PF001', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        matches = self._classify('PF001')
        self.assertIn(10, self._lesson_ids(matches))

    # -- Lesson 13: C-Bet Flop IP --

    def test_cbet_flop_ip(self):
        """PFA bets flop in position = C-Bet IP."""
        _insert_hand(self.repo, 'CBIP001', position='BTN',
                     board_flop='Ah Kd 2c')
        # Preflop: hero opens
        _insert_action(self.repo, 'CBIP001', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'CBIP001', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        # Flop: villain checks, hero bets
        _insert_action(self.repo, 'CBIP001', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'CBIP001', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        matches = self._classify('CBIP001')
        ids = self._lesson_ids(matches)
        self.assertIn(13, ids)  # C-Bet IP
        self.assertNotIn(14, ids)  # should NOT be OOP

    # -- Lesson 14: C-Bet OOP --

    def test_cbet_flop_oop(self):
        """PFA bets flop out of position = C-Bet OOP."""
        _insert_hand(self.repo, 'CBOOP001', position='BB',
                     board_flop='Ah Kd 2c')
        # Preflop: hero 3-bets from BB
        _insert_action(self.repo, 'CBOOP001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'CBOOP001', 'preflop', 'Hero', 'raise', 4.5, 1, 2, 'BB')
        _insert_action(self.repo, 'CBOOP001', 'preflop', 'P1', 'call', 4.5, 0, 3, 'BTN')
        # Flop: hero bets OOP
        _insert_action(self.repo, 'CBOOP001', 'flop', 'Hero', 'bet', 3.0, 1, 4, 'BB')
        _insert_action(self.repo, 'CBOOP001', 'flop', 'P1', 'call', 3.0, 0, 5, 'BTN')

        matches = self._classify('CBOOP001')
        ids = self._lesson_ids(matches)
        self.assertIn(14, ids)  # C-Bet OOP
        self.assertNotIn(13, ids)  # should NOT be IP

    # -- Lesson 15: C-Bet Turn --

    def test_cbet_turn(self):
        """PFA bets turn = C-Bet Turn."""
        _insert_hand(self.repo, 'CBT001', position='BTN',
                     board_flop='Ah Kd 2c', board_turn='5s')
        _insert_action(self.repo, 'CBT001', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'CBT001', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'CBT001', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'CBT001', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')
        _insert_action(self.repo, 'CBT001', 'flop', 'P1', 'call', 2.0, 0, 5, 'BB')
        _insert_action(self.repo, 'CBT001', 'turn', 'P1', 'check', 0, 0, 6, 'BB')
        _insert_action(self.repo, 'CBT001', 'turn', 'Hero', 'bet', 5.0, 1, 7, 'BTN')

        matches = self._classify('CBT001')
        ids = self._lesson_ids(matches)
        self.assertIn(15, ids)  # C-Bet Turn
        cbt = next(m for m in matches if m.lesson_id == 15)
        self.assertEqual(cbt.street, 'turn')

    # -- Lesson 16: C-Bet River --

    def test_cbet_river(self):
        """PFA bets river = C-Bet River."""
        _insert_hand(self.repo, 'CBR001', position='BTN',
                     board_flop='Ah Kd 2c', board_turn='5s', board_river='Jh')
        _insert_action(self.repo, 'CBR001', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'CBR001', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'CBR001', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'CBR001', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')
        _insert_action(self.repo, 'CBR001', 'flop', 'P1', 'call', 2.0, 0, 5, 'BB')
        _insert_action(self.repo, 'CBR001', 'turn', 'P1', 'check', 0, 0, 6, 'BB')
        _insert_action(self.repo, 'CBR001', 'turn', 'Hero', 'bet', 5.0, 1, 7, 'BTN')
        _insert_action(self.repo, 'CBR001', 'turn', 'P1', 'call', 5.0, 0, 8, 'BB')
        _insert_action(self.repo, 'CBR001', 'river', 'P1', 'check', 0, 0, 9, 'BB')
        _insert_action(self.repo, 'CBR001', 'river', 'Hero', 'bet', 10.0, 1, 10, 'BTN')

        matches = self._classify('CBR001')
        ids = self._lesson_ids(matches)
        self.assertIn(16, ids)  # C-Bet River
        cbr = next(m for m in matches if m.lesson_id == 16)
        self.assertEqual(cbr.street, 'river')

    # -- Lesson 17: Delayed C-Bet --

    def test_delayed_cbet(self):
        """PFA checks flop, bets turn = Delayed C-Bet."""
        _insert_hand(self.repo, 'DCB001', position='BTN',
                     board_flop='Ah Kd 2c', board_turn='5s')
        _insert_action(self.repo, 'DCB001', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'DCB001', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        # Flop: hero checks back
        _insert_action(self.repo, 'DCB001', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'DCB001', 'flop', 'Hero', 'check', 0, 1, 4, 'BTN')
        # Turn: hero bets (delayed c-bet)
        _insert_action(self.repo, 'DCB001', 'turn', 'P1', 'check', 0, 0, 5, 'BB')
        _insert_action(self.repo, 'DCB001', 'turn', 'Hero', 'bet', 3.0, 1, 6, 'BTN')

        matches = self._classify('DCB001')
        ids = self._lesson_ids(matches)
        self.assertIn(17, ids)  # Delayed C-Bet
        dcb = next(m for m in matches if m.lesson_id == 17)
        self.assertEqual(dcb.street, 'turn')

    # -- Lesson 18: BB vs C-Bet OOP --

    def test_bb_vs_cbet_oop(self):
        """BB faces c-bet OOP."""
        _insert_hand(self.repo, 'BBCB001', position='BB',
                     board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'BBCB001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'BBCB001', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')
        # Flop: hero checks, villain bets
        _insert_action(self.repo, 'BBCB001', 'flop', 'Hero', 'check', 0, 1, 3, 'BB')
        _insert_action(self.repo, 'BBCB001', 'flop', 'P1', 'bet', 2.0, 0, 4, 'BTN')
        _insert_action(self.repo, 'BBCB001', 'flop', 'Hero', 'call', 2.0, 1, 5, 'BB')

        matches = self._classify('BBCB001')
        ids = self._lesson_ids(matches)
        self.assertIn(18, ids)  # BB vs C-Bet OOP

    # -- Lesson 19: Enfrentando Check-Raise --

    def test_facing_checkraise(self):
        """Hero bets, gets check-raised."""
        _insert_hand(self.repo, 'CR001', position='BTN',
                     board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'CR001', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'CR001', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'CR001', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'CR001', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')
        _insert_action(self.repo, 'CR001', 'flop', 'P1', 'raise', 6.0, 0, 5, 'BB')

        matches = self._classify('CR001')
        ids = self._lesson_ids(matches)
        self.assertIn(19, ids)  # Facing Check-Raise

    # -- Lesson 20: Pós-Flop IP enfrentando C-Bet --

    def test_ip_facing_cbet(self):
        """Hero IP faces c-bet from villain."""
        _insert_hand(self.repo, 'IPCB001', position='BTN',
                     board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'IPCB001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'MP')
        _insert_action(self.repo, 'IPCB001', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BTN')
        # Flop: villain bets (c-bet), hero calls
        _insert_action(self.repo, 'IPCB001', 'flop', 'P1', 'bet', 2.0, 0, 3, 'MP')
        _insert_action(self.repo, 'IPCB001', 'flop', 'Hero', 'call', 2.0, 1, 4, 'BTN')

        matches = self._classify('IPCB001')
        ids = self._lesson_ids(matches)
        self.assertIn(20, ids)  # IP facing C-Bet

    # -- Lesson 21: Bet vs Missed Bet --

    def test_bet_vs_missed_bet(self):
        """Villain was aggressor, checks back, hero bets turn."""
        _insert_hand(self.repo, 'BVMB001', position='BB',
                     board_flop='Ah Kd 2c', board_turn='5s')
        # Preflop: villain opens, hero calls
        _insert_action(self.repo, 'BVMB001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'BVMB001', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')
        # Flop: villain bets, hero calls
        _insert_action(self.repo, 'BVMB001', 'flop', 'Hero', 'check', 0, 1, 3, 'BB')
        _insert_action(self.repo, 'BVMB001', 'flop', 'P1', 'bet', 2.0, 0, 4, 'BTN')
        _insert_action(self.repo, 'BVMB001', 'flop', 'Hero', 'call', 2.0, 1, 5, 'BB')
        # Turn: villain checks, hero bets (bet vs missed bet)
        _insert_action(self.repo, 'BVMB001', 'turn', 'Hero', 'bet', 4.0, 1, 6, 'BB')

        matches = self._classify('BVMB001')
        ids = self._lesson_ids(matches)
        self.assertIn(21, ids)  # Bet vs Missed Bet

    # -- Lesson 22: Probe do BB --

    def test_probe_bb(self):
        """BB probes turn after PFA checks flop."""
        _insert_hand(self.repo, 'PROBE001', position='BB',
                     board_flop='Ah Kd 2c', board_turn='5s')
        _insert_action(self.repo, 'PROBE001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'PROBE001', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')
        # Flop: both check
        _insert_action(self.repo, 'PROBE001', 'flop', 'Hero', 'check', 0, 1, 3, 'BB')
        _insert_action(self.repo, 'PROBE001', 'flop', 'P1', 'check', 0, 0, 4, 'BTN')
        # Turn: hero probes
        _insert_action(self.repo, 'PROBE001', 'turn', 'Hero', 'bet', 3.0, 1, 5, 'BB')

        matches = self._classify('PROBE001')
        ids = self._lesson_ids(matches)
        self.assertIn(22, ids)  # Probe do BB

    # -- Lesson 23: 3-Betted Pots Pós-Flop --

    def test_3bet_pot_postflop(self):
        """Postflop in 3-bet pot."""
        _insert_hand(self.repo, '3BP001', position='BTN',
                     board_flop='Ah Kd 2c', net=5.0)
        _insert_action(self.repo, '3BP001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, '3BP001', 'preflop', 'Hero', 'raise', 4.5, 1, 2, 'BTN')
        _insert_action(self.repo, '3BP001', 'preflop', 'P1', 'call', 4.5, 0, 3, 'UTG')
        # Flop
        _insert_action(self.repo, '3BP001', 'flop', 'P1', 'check', 0, 0, 4, 'UTG')
        _insert_action(self.repo, '3BP001', 'flop', 'Hero', 'bet', 5.0, 1, 5, 'BTN')

        matches = self._classify('3BP001')
        ids = self._lesson_ids(matches)
        self.assertIn(23, ids)  # 3-Betted Pots


# ── Tournament Detection Tests ──────────────────────────────────────


class TestTournamentDetection(unittest.TestCase):
    """Test tournament lesson classification."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def test_bounty_tournament_lessons(self):
        """Bounty tournament hands match lessons 24-25."""
        # Insert tournament
        self.repo.insert_tournament({
            'tournament_id': 'T001',
            'platform': 'GGPoker',
            'name': 'Bounty Hunter',
            'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 5,
            'total_buy_in': 16, 'is_bounty': True,
        })
        _insert_hand(self.repo, 'BOUNT001', position='BTN',
                     game_type='tournament', tournament_id='T001')
        _insert_action(self.repo, 'BOUNT001', 'preflop', 'Hero', 'raise',
                       300, 1, 1, 'BTN')
        _insert_action(self.repo, 'BOUNT001', 'preflop', 'P1', 'fold',
                       0, 0, 2, 'BB')

        hand = _get_hand_dict(self.repo, 'BOUNT001')
        actions = self.repo.get_hand_actions('BOUNT001')
        matches = self.classifier.classify_hand(hand, actions)
        ids = [m.lesson_id for m in matches]
        self.assertIn(24, ids)  # Intro Bounty
        self.assertIn(25, ids)  # Bounty Ranges

    def test_non_bounty_tournament(self):
        """Non-bounty tournament should NOT match bounty lessons."""
        self.repo.insert_tournament({
            'tournament_id': 'T002',
            'platform': 'GGPoker',
            'name': 'Regular MTT',
            'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 0,
            'total_buy_in': 11, 'is_bounty': False,
        })
        _insert_hand(self.repo, 'NONB001', position='BTN',
                     game_type='tournament', tournament_id='T002')
        _insert_action(self.repo, 'NONB001', 'preflop', 'Hero', 'raise',
                       300, 1, 1, 'BTN')

        hand = _get_hand_dict(self.repo, 'NONB001')
        actions = self.repo.get_hand_actions('NONB001')
        matches = self.classifier.classify_hand(hand, actions)
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(24, ids)
        self.assertNotIn(25, ids)


# ── Pipeline / Bulk Classification Tests ─────────────────────────────


class TestClassifyPipeline(unittest.TestCase):
    """Test the full classify_all pipeline."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_classify_all_empty_db(self):
        """classify_all on empty DB returns zeros."""
        classifier = LessonClassifier(self.repo)
        result = classifier.classify_all()
        self.assertEqual(result['total_hands'], 0)
        self.assertEqual(result['classified_hands'], 0)
        self.assertEqual(result['total_links'], 0)

    def test_classify_all_with_hands(self):
        """classify_all classifies hands and persists results."""
        # RFI hand
        _insert_hand(self.repo, 'PIPE001', position='BTN')
        _insert_action(self.repo, 'PIPE001', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'PIPE001', 'preflop', 'Hero', 'raise', 1.5, 1, 2, 'BTN')
        _insert_action(self.repo, 'PIPE001', 'preflop', 'P2', 'fold', 0, 0, 3, 'BB')

        # Postflop hand
        _insert_hand(self.repo, 'PIPE002', position='BTN',
                     board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'PIPE002', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'PIPE002', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'PIPE002', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'PIPE002', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        classifier = LessonClassifier(self.repo)
        result = classifier.classify_all()

        self.assertEqual(result['total_hands'], 2)
        self.assertGreaterEqual(result['classified_hands'], 2)
        self.assertGreater(result['total_links'], 0)
        self.assertGreaterEqual(result['lessons_matched'], 2)

        # Verify persistence
        lessons_pipe001 = self.repo.get_lessons_for_hand('PIPE001')
        self.assertGreater(len(lessons_pipe001), 0)

    def test_classify_all_clears_previous(self):
        """classify_all clears previous classifications."""
        _insert_hand(self.repo, 'CLR001', position='BTN')
        _insert_action(self.repo, 'CLR001', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')

        # Manual link
        self.repo.link_hand_to_lesson('CLR001', 1, notes='manual')

        classifier = LessonClassifier(self.repo)
        classifier.classify_all()

        # The manual link should be gone, replaced by classifier links
        lessons = self.repo.get_lessons_for_hand('CLR001')
        for l in lessons:
            self.assertNotEqual(l.get('lesson_notes'), 'manual')

    def test_classify_multiple_lessons_per_hand(self):
        """A single hand can match multiple lessons."""
        # Hand: BB calls open, faces c-bet, reaches turn
        _insert_hand(self.repo, 'MULTI001', position='BB',
                     board_flop='Ah Kd 2c', board_turn='5s')
        _insert_action(self.repo, 'MULTI001', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'MULTI001', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')
        _insert_action(self.repo, 'MULTI001', 'flop', 'Hero', 'check', 0, 1, 3, 'BB')
        _insert_action(self.repo, 'MULTI001', 'flop', 'P1', 'bet', 2.0, 0, 4, 'BTN')
        _insert_action(self.repo, 'MULTI001', 'flop', 'Hero', 'call', 2.0, 1, 5, 'BB')
        _insert_action(self.repo, 'MULTI001', 'turn', 'Hero', 'check', 0, 1, 6, 'BB')
        _insert_action(self.repo, 'MULTI001', 'turn', 'P1', 'check', 0, 0, 7, 'BTN')

        classifier = LessonClassifier(self.repo)
        result = classifier.classify_all()

        lessons = self.repo.get_lessons_for_hand('MULTI001')
        # Should match at least: BB preflop (6), intro postflop (10),
        # MDA (11), BB vs C-Bet (18)
        self.assertGreaterEqual(len(lessons), 3)

    def test_at_least_15_lessons_classifiable(self):
        """Acceptance criteria: classifier can detect at least 15 of 25 lessons."""
        # Create diverse hands to trigger different lessons

        # 1: RFI
        _insert_hand(self.repo, 'AC01', position='CO')
        _insert_action(self.repo, 'AC01', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'AC01', 'preflop', 'Hero', 'raise', 1.5, 1, 2, 'CO')

        # 2: Flat
        _insert_hand(self.repo, 'AC02', position='BTN')
        _insert_action(self.repo, 'AC02', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'AC02', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BTN')

        # 3: Reaction vs 3-Bet
        _insert_hand(self.repo, 'AC03', position='CO')
        _insert_action(self.repo, 'AC03', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'CO')
        _insert_action(self.repo, 'AC03', 'preflop', 'P1', 'raise', 4.5, 0, 2, 'BTN')
        _insert_action(self.repo, 'AC03', 'preflop', 'Hero', 'call', 4.5, 1, 3, 'CO')

        # 4: Open Shove 10BB
        _insert_hand(self.repo, 'AC04', position='BTN', hero_stack=4.0, blinds_bb=0.50)
        _insert_action(self.repo, 'AC04', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'AC04', 'preflop', 'Hero', 'all-in', 4.0, 1, 2, 'BTN')

        # 5: Squeeze
        _insert_hand(self.repo, 'AC05', position='CO')
        _insert_action(self.repo, 'AC05', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'AC05', 'preflop', 'P2', 'call', 1.5, 0, 2, 'MP')
        _insert_action(self.repo, 'AC05', 'preflop', 'Hero', 'raise', 6.0, 1, 3, 'CO')

        # 6: BB Pré-Flop
        _insert_hand(self.repo, 'AC06', position='BB')
        _insert_action(self.repo, 'AC06', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'AC06', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')

        # 7: SB vs BB blind war
        _insert_hand(self.repo, 'AC07', position='SB')
        _insert_action(self.repo, 'AC07', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'AC07', 'preflop', 'P2', 'fold', 0, 0, 2, 'MP')
        _insert_action(self.repo, 'AC07', 'preflop', 'P3', 'fold', 0, 0, 3, 'CO')
        _insert_action(self.repo, 'AC07', 'preflop', 'P4', 'fold', 0, 0, 4, 'BTN')
        _insert_action(self.repo, 'AC07', 'preflop', 'Hero', 'raise', 1.5, 1, 5, 'SB')
        _insert_action(self.repo, 'AC07', 'preflop', 'P5', 'call', 1.5, 0, 6, 'BB')

        # 8: Multiway BB
        _insert_hand(self.repo, 'AC08', position='BB')
        _insert_action(self.repo, 'AC08', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'AC08', 'preflop', 'P2', 'call', 1.5, 0, 2, 'MP')
        _insert_action(self.repo, 'AC08', 'preflop', 'P3', 'call', 1.5, 0, 3, 'BTN')
        _insert_action(self.repo, 'AC08', 'preflop', 'Hero', 'call', 1.5, 1, 4, 'BB')

        # 9: BB vs SB blind war
        _insert_hand(self.repo, 'AC09', position='BB')
        _insert_action(self.repo, 'AC09', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'AC09', 'preflop', 'P2', 'fold', 0, 0, 2, 'MP')
        _insert_action(self.repo, 'AC09', 'preflop', 'P3', 'fold', 0, 0, 3, 'CO')
        _insert_action(self.repo, 'AC09', 'preflop', 'P4', 'fold', 0, 0, 4, 'BTN')
        _insert_action(self.repo, 'AC09', 'preflop', 'P5', 'raise', 1.5, 0, 5, 'SB')
        _insert_action(self.repo, 'AC09', 'preflop', 'Hero', 'call', 1.5, 1, 6, 'BB')

        # 10+13: C-Bet IP (also triggers intro postflop)
        _insert_hand(self.repo, 'AC10', position='BTN', board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'AC10', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'AC10', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'AC10', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'AC10', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        # 14: C-Bet OOP
        _insert_hand(self.repo, 'AC14', position='BB', board_flop='Jh Td 3c')
        _insert_action(self.repo, 'AC14', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'AC14', 'preflop', 'Hero', 'raise', 4.5, 1, 2, 'BB')
        _insert_action(self.repo, 'AC14', 'preflop', 'P1', 'call', 4.5, 0, 3, 'BTN')
        _insert_action(self.repo, 'AC14', 'flop', 'Hero', 'bet', 3.0, 1, 4, 'BB')

        # 17: Delayed C-Bet
        _insert_hand(self.repo, 'AC17', position='BTN',
                     board_flop='Ah Kd 2c', board_turn='5s')
        _insert_action(self.repo, 'AC17', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'AC17', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'AC17', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'AC17', 'flop', 'Hero', 'check', 0, 1, 4, 'BTN')
        _insert_action(self.repo, 'AC17', 'turn', 'P1', 'check', 0, 0, 5, 'BB')
        _insert_action(self.repo, 'AC17', 'turn', 'Hero', 'bet', 3.0, 1, 6, 'BTN')

        # 18: BB vs C-Bet OOP
        _insert_hand(self.repo, 'AC18', position='BB', board_flop='Qh 9d 4c')
        _insert_action(self.repo, 'AC18', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'AC18', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')
        _insert_action(self.repo, 'AC18', 'flop', 'Hero', 'check', 0, 1, 3, 'BB')
        _insert_action(self.repo, 'AC18', 'flop', 'P1', 'bet', 2.0, 0, 4, 'BTN')
        _insert_action(self.repo, 'AC18', 'flop', 'Hero', 'call', 2.0, 1, 5, 'BB')

        # 19: Check-Raise
        _insert_hand(self.repo, 'AC19', position='BTN', board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'AC19', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'AC19', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'AC19', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'AC19', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')
        _insert_action(self.repo, 'AC19', 'flop', 'P1', 'raise', 6.0, 0, 5, 'BB')

        # 23: 3-Bet Pot Postflop
        _insert_hand(self.repo, 'AC23', position='BTN',
                     board_flop='Ah Kd 2c', net=5.0)
        _insert_action(self.repo, 'AC23', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'AC23', 'preflop', 'Hero', 'raise', 4.5, 1, 2, 'BTN')
        _insert_action(self.repo, 'AC23', 'preflop', 'P1', 'call', 4.5, 0, 3, 'UTG')
        _insert_action(self.repo, 'AC23', 'flop', 'P1', 'check', 0, 0, 4, 'UTG')
        _insert_action(self.repo, 'AC23', 'flop', 'Hero', 'bet', 5.0, 1, 5, 'BTN')

        # 24-25: Bounty tournament
        self.repo.insert_tournament({
            'tournament_id': 'TBNTY',
            'platform': 'GGPoker',
            'name': 'Bounty',
            'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 5,
            'total_buy_in': 16, 'is_bounty': True,
        })
        _insert_hand(self.repo, 'AC24', position='BTN',
                     game_type='tournament', tournament_id='TBNTY')
        _insert_action(self.repo, 'AC24', 'preflop', 'Hero', 'raise', 300, 1, 1, 'BTN')
        _insert_action(self.repo, 'AC24', 'preflop', 'P1', 'fold', 0, 0, 2, 'BB')

        classifier = LessonClassifier(self.repo)
        result = classifier.classify_all()

        # AC: at least 15 of 25 lessons covered
        self.assertGreaterEqual(result['lessons_matched'], 15,
                                f"Expected >=15 lessons matched, got {result['lessons_matched']}")


# ── Execution Evaluation Tests ───────────────────────────────────────


class TestExecutionEvaluation(unittest.TestCase):
    """Test executed_correctly evaluation per lesson."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def test_rfi_executed_correctly(self):
        """RFI with strong hand from BTN and standard sizing is correct."""
        _insert_hand(self.repo, 'EV001', position='BTN')
        _insert_action(self.repo, 'EV001', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')

        hand = _get_hand_dict(self.repo, 'EV001')
        actions = self.repo.get_hand_actions('EV001')
        matches = self.classifier.classify_hand(hand, actions)

        rfi = next(m for m in matches if m.lesson_id == 1)
        self.assertEqual(rfi.executed_correctly, 1)

    def test_cbet_ip_executed_correctly(self):
        """C-Bet IP execution."""
        _insert_hand(self.repo, 'EV002', position='BTN',
                     board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'EV002', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'EV002', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'EV002', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'EV002', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        hand = _get_hand_dict(self.repo, 'EV002')
        actions = self.repo.get_hand_actions('EV002')
        matches = self.classifier.classify_hand(hand, actions)

        cbet = next(m for m in matches if m.lesson_id == 13)
        self.assertEqual(cbet.executed_correctly, 1)

    def test_postflop_winning_hand(self):
        """Intro postflop with winning hand."""
        _insert_hand(self.repo, 'EV003', position='BTN',
                     board_flop='Ah Kd 2c', net=5.0)
        _insert_action(self.repo, 'EV003', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'EV003', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'EV003', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'EV003', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        hand = _get_hand_dict(self.repo, 'EV003')
        actions = self.repo.get_hand_actions('EV003')
        matches = self.classifier.classify_hand(hand, actions)

        intro = next(m for m in matches if m.lesson_id == 10)
        self.assertEqual(intro.executed_correctly, 1)

    def test_postflop_losing_hand(self):
        """Intro postflop with losing hand."""
        _insert_hand(self.repo, 'EV004', position='BTN',
                     board_flop='Ah Kd 2c', net=-5.0)
        _insert_action(self.repo, 'EV004', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'EV004', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'EV004', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'EV004', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        hand = _get_hand_dict(self.repo, 'EV004')
        actions = self.repo.get_hand_actions('EV004')
        matches = self.classifier.classify_hand(hand, actions)

        intro = next(m for m in matches if m.lesson_id == 10)
        self.assertEqual(intro.executed_correctly, 0)


# ── CLI Tests ────────────────────────────────────────────────────────


class TestClassifyCLI(unittest.TestCase):
    """Test classify CLI command."""

    def test_classify_help(self):
        result = subprocess.run(
            [sys.executable, 'main.py', 'classify', '--help'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('classify', result.stdout.lower())

    def test_classify_command_runs(self):
        result = subprocess.run(
            [sys.executable, 'main.py', '--db', '/tmp/test_classify_cli.db',
             'classify', '--force'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Lesson Classifier', result.stdout)
        self.assertIn('Total hands', result.stdout)
        self.assertIn('Classified hands', result.stdout)
        self.assertIn('Lessons matched', result.stdout)

    def test_classify_appears_in_help(self):
        result = subprocess.run(
            [sys.executable, 'main.py', '--help'],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('classify', result.stdout)


# ── Schema Migration Tests ───────────────────────────────────────────


class TestHandLessonsMigration(unittest.TestCase):
    """Test migration adds new columns to existing hand_lessons table."""

    def test_migration_adds_columns(self):
        """Old DB with hand_lessons but no new columns gets migrated."""
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row

        # Create old schema without new columns
        conn.executescript("""
            CREATE TABLE hands (
                hand_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                game_type TEXT NOT NULL,
                date TEXT NOT NULL,
                blinds_sb REAL, blinds_bb REAL,
                hero_cards TEXT, hero_position TEXT,
                invested REAL DEFAULT 0, won REAL DEFAULT 0,
                net REAL DEFAULT 0, rake REAL DEFAULT 0,
                table_name TEXT, num_players INTEGER,
                board_flop TEXT, board_turn TEXT, board_river TEXT,
                pot_total REAL, opponent_cards TEXT,
                has_allin INTEGER DEFAULT 0, allin_street TEXT,
                tournament_id TEXT, hero_stack REAL
            );
            CREATE TABLE hand_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hand_id TEXT NOT NULL, street TEXT NOT NULL,
                player TEXT NOT NULL, action_type TEXT NOT NULL,
                amount REAL DEFAULT 0, is_hero INTEGER DEFAULT 0,
                sequence_order INTEGER DEFAULT 0, position TEXT,
                is_voluntary INTEGER DEFAULT 0
            );
            CREATE TABLE sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT, date TEXT NOT NULL,
                buy_in REAL DEFAULT 0, cash_out REAL DEFAULT 0,
                profit REAL DEFAULT 0, hands_count INTEGER DEFAULT 0,
                min_stack REAL DEFAULT 0, start_time TEXT, end_time TEXT
            );
            CREATE TABLE tournaments (
                tournament_id TEXT PRIMARY KEY, platform TEXT NOT NULL,
                name TEXT, date TEXT, buy_in REAL DEFAULT 0,
                rake REAL DEFAULT 0, bounty REAL DEFAULT 0,
                total_buy_in REAL DEFAULT 0, position INTEGER,
                prize REAL DEFAULT 0, bounty_won REAL DEFAULT 0,
                total_players INTEGER DEFAULT 0, entries INTEGER DEFAULT 1,
                is_bounty INTEGER DEFAULT 0, is_satellite INTEGER DEFAULT 0
            );
            CREATE TABLE tournament_summaries (
                tournament_id TEXT PRIMARY KEY, platform TEXT NOT NULL,
                name TEXT, date TEXT, buy_in REAL DEFAULT 0,
                rake REAL DEFAULT 0, bounty REAL DEFAULT 0,
                total_buy_in REAL DEFAULT 0, position INTEGER,
                prize REAL DEFAULT 0, bounty_won REAL DEFAULT 0,
                total_players INTEGER DEFAULT 0, entries INTEGER DEFAULT 1,
                is_bounty INTEGER DEFAULT 0, is_satellite INTEGER DEFAULT 0
            );
            CREATE TABLE imported_files (
                file_path TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                records_count INTEGER DEFAULT 0
            );
            CREATE TABLE lessons (
                lesson_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL, category TEXT NOT NULL,
                subcategory TEXT NOT NULL, pdf_filename TEXT,
                description TEXT, sort_order INTEGER DEFAULT 0
            );
            CREATE TABLE hand_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hand_id TEXT NOT NULL, lesson_id INTEGER NOT NULL,
                notes TEXT, created_at TEXT NOT NULL
            );
        """)
        conn.commit()

        # Verify no new columns yet
        old_cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(hand_lessons)").fetchall()}
        self.assertNotIn('street', old_cols)

        # Run init_db (should migrate)
        init_db(conn)

        new_cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(hand_lessons)").fetchall()}
        self.assertIn('street', new_cols)
        self.assertIn('executed_correctly', new_cols)
        self.assertIn('confidence', new_cols)

        conn.close()


# ── RFI Range Evaluation Tests (US-040) ──────────────────────────────


class TestRFIRangeEvaluation(unittest.TestCase):
    """Test RFI evaluation with position-based ranges and sizing rules.

    Based on RegLife 'Ranges de RFI em cEV' PDF:
    - Positions: EP(UTG/UTG+1) ~17%, MP(LJ/HJ) ~28%, CO ~37%, BTN ~54%
    - Sizing: 2-2.5BB (tournament) / up to 3BB (cash)
    - Hand strength tiers mapped to position groups
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _rfi_result(self, hand_id):
        """Get executed_correctly for lesson 1 (RFI)."""
        matches = self._classify(hand_id)
        rfi = next((m for m in matches if m.lesson_id == 1), None)
        return rfi.executed_correctly if rfi else None

    # -- Hand notation parsing --

    def test_hand_notation_offsuit(self):
        n = self.classifier._hand_notation('Ah Kd')
        self.assertEqual(n, 'AKo')

    def test_hand_notation_suited(self):
        n = self.classifier._hand_notation('Ah Kh')
        self.assertEqual(n, 'AKs')

    def test_hand_notation_pair(self):
        n = self.classifier._hand_notation('As Ad')
        self.assertEqual(n, 'AA')

    def test_hand_notation_reversed_order(self):
        n = self.classifier._hand_notation('Kd Ah')
        self.assertEqual(n, 'AKo')

    def test_hand_notation_low_cards(self):
        n = self.classifier._hand_notation('7h 2d')
        self.assertEqual(n, '72o')

    def test_hand_notation_ten(self):
        n = self.classifier._hand_notation('Th 9h')
        self.assertEqual(n, 'T9s')

    def test_hand_notation_empty(self):
        self.assertIsNone(self.classifier._hand_notation(''))
        self.assertIsNone(self.classifier._hand_notation(None))

    # -- Hand tier assignment --

    def test_tier1_premium(self):
        """AA, AKs, AKo are tier 1 (EP range)."""
        self.assertEqual(self.classifier._rfi_hand_tier('AA'), 1)
        self.assertEqual(self.classifier._rfi_hand_tier('AKs'), 1)
        self.assertEqual(self.classifier._rfi_hand_tier('AKo'), 1)
        self.assertEqual(self.classifier._rfi_hand_tier('77'), 1)
        self.assertEqual(self.classifier._rfi_hand_tier('T9s'), 1)

    def test_tier2_mp(self):
        """66, A9o, KQo are tier 2 (MP range)."""
        self.assertEqual(self.classifier._rfi_hand_tier('66'), 2)
        self.assertEqual(self.classifier._rfi_hand_tier('A9o'), 2)
        self.assertEqual(self.classifier._rfi_hand_tier('KQo'), 2)
        self.assertEqual(self.classifier._rfi_hand_tier('JTo'), 2)

    def test_tier3_co(self):
        """44, A8o, K9o are tier 3 (CO range)."""
        self.assertEqual(self.classifier._rfi_hand_tier('44'), 3)
        self.assertEqual(self.classifier._rfi_hand_tier('A8o'), 3)
        self.assertEqual(self.classifier._rfi_hand_tier('K9o'), 3)
        self.assertEqual(self.classifier._rfi_hand_tier('Q2s'), 3)

    def test_tier4_btn(self):
        """K2o, 87o, Q8o are tier 4 (BTN range)."""
        self.assertEqual(self.classifier._rfi_hand_tier('K2o'), 4)
        self.assertEqual(self.classifier._rfi_hand_tier('87o'), 4)
        self.assertEqual(self.classifier._rfi_hand_tier('Q8o'), 4)
        self.assertEqual(self.classifier._rfi_hand_tier('T2s'), 4)

    def test_tier5_trash(self):
        """Weak hands like Q5o, J6o, 83o are tier 5 (should not RFI)."""
        self.assertEqual(self.classifier._rfi_hand_tier('Q5o'), 5)
        self.assertEqual(self.classifier._rfi_hand_tier('J6o'), 5)
        self.assertEqual(self.classifier._rfi_hand_tier('83o'), 5)

    # -- Correct RFI: hand in range + good sizing --

    def test_rfi_correct_premium_from_utg(self):
        """AKo from UTG with 2.5x sizing = correct."""
        _insert_hand(self.repo, 'RFIC01', position='UTG')
        # hero_cards defaults to 'Ah Kd' = AKo (tier 1)
        _insert_action(self.repo, 'RFIC01', 'preflop', 'Hero', 'raise',
                       1.25, 1, 1, 'UTG')  # 1.25/0.50 = 2.5BB
        self.assertEqual(self._rfi_result('RFIC01'), 1)

    def test_rfi_correct_suited_connector_from_utg(self):
        """T9s from UTG with proper sizing = correct (tier 1 hand)."""
        _insert_hand(self.repo, 'RFIC02', position='UTG',
                     hero_stack=50.0, blinds_bb=0.50)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards='Th 9h' WHERE hand_id='RFIC02'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFIC02', 'preflop', 'Hero', 'raise',
                       1.0, 1, 1, 'UTG')  # 2.0BB
        self.assertEqual(self._rfi_result('RFIC02'), 1)

    def test_rfi_correct_medium_hand_from_hj(self):
        """A9o from HJ = correct (tier 2 hand, HJ accepts tier 1-2)."""
        _insert_hand(self.repo, 'RFIC03', position='HJ')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards='As 9d' WHERE hand_id='RFIC03'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFIC03', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'RFIC03', 'preflop', 'Hero', 'raise',
                       1.0, 1, 2, 'HJ')  # 2.0BB
        self.assertEqual(self._rfi_result('RFIC03'), 1)

    def test_rfi_correct_wide_hand_from_btn(self):
        """K7o from BTN = correct (tier 4 hand, BTN accepts tier 1-4)."""
        _insert_hand(self.repo, 'RFIC04', position='BTN')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards='Kh 7d' WHERE hand_id='RFIC04'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFIC04', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'RFIC04', 'preflop', 'Hero', 'raise',
                       1.25, 1, 2, 'BTN')  # 2.5BB
        self.assertEqual(self._rfi_result('RFIC04'), 1)

    def test_rfi_correct_co_range(self):
        """A8o from CO = correct (tier 3 hand, CO accepts tier 1-3)."""
        _insert_hand(self.repo, 'RFIC05', position='CO')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards='Ah 8d' WHERE hand_id='RFIC05'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFIC05', 'preflop', 'Hero', 'raise',
                       1.0, 1, 1, 'CO')
        self.assertEqual(self._rfi_result('RFIC05'), 1)

    # -- Incorrect RFI: hand too weak for position --

    def test_rfi_incorrect_trash_from_utg(self):
        """72o from UTG = incorrect (tier 5, way too weak)."""
        _insert_hand(self.repo, 'RFII01', position='UTG')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards='7h 2d' WHERE hand_id='RFII01'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFII01', 'preflop', 'Hero', 'raise',
                       1.0, 1, 1, 'UTG')
        self.assertEqual(self._rfi_result('RFII01'), 0)

    def test_rfi_incorrect_co_hand_from_utg(self):
        """K9o from UTG = incorrect (tier 3, UTG only accepts tier 1)."""
        _insert_hand(self.repo, 'RFII02', position='UTG')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards='Kh 9d' WHERE hand_id='RFII02'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFII02', 'preflop', 'Hero', 'raise',
                       1.0, 1, 1, 'UTG')
        self.assertEqual(self._rfi_result('RFII02'), 0)

    def test_rfi_incorrect_btn_hand_from_hj(self):
        """K2o from HJ = incorrect (tier 4, HJ only accepts tier 1-2)."""
        _insert_hand(self.repo, 'RFII03', position='HJ')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards='Kh 2d' WHERE hand_id='RFII03'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFII03', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'RFII03', 'preflop', 'Hero', 'raise',
                       1.0, 1, 2, 'HJ')
        self.assertEqual(self._rfi_result('RFII03'), 0)

    # -- Marginal RFI: hand one tier above position max --

    def test_rfi_marginal_mp_hand_from_utg(self):
        """A9o from UTG = marginal (tier 2, UTG accepts tier 1 only)."""
        _insert_hand(self.repo, 'RFIM01', position='UTG')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards='As 9d' WHERE hand_id='RFIM01'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFIM01', 'preflop', 'Hero', 'raise',
                       1.0, 1, 1, 'UTG')
        self.assertIsNone(self._rfi_result('RFIM01'))

    def test_rfi_marginal_co_hand_from_hj(self):
        """A8o from HJ = marginal (tier 3, HJ accepts tier 1-2)."""
        _insert_hand(self.repo, 'RFIM02', position='HJ')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards='Ah 8d' WHERE hand_id='RFIM02'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFIM02', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'RFIM02', 'preflop', 'Hero', 'raise',
                       1.0, 1, 2, 'HJ')
        self.assertIsNone(self._rfi_result('RFIM02'))

    # -- Sizing evaluation --

    def test_rfi_wrong_sizing_good_hand(self):
        """AKo from BTN but 4x sizing = partial (None)."""
        _insert_hand(self.repo, 'RFIS01', position='BTN')
        _insert_action(self.repo, 'RFIS01', 'preflop', 'Hero', 'raise',
                       2.0, 1, 1, 'BTN')  # 2.0/0.50 = 4.0BB → too high
        self.assertIsNone(self._rfi_result('RFIS01'))

    def test_rfi_correct_sizing_2bb(self):
        """2.0BB sizing is within acceptable range."""
        _insert_hand(self.repo, 'RFIS02', position='BTN')
        _insert_action(self.repo, 'RFIS02', 'preflop', 'Hero', 'raise',
                       1.0, 1, 1, 'BTN')  # 1.0/0.50 = 2.0BB
        self.assertEqual(self._rfi_result('RFIS02'), 1)

    def test_rfi_correct_sizing_3bb(self):
        """3.0BB sizing is within acceptable range (cash game standard)."""
        _insert_hand(self.repo, 'RFIS03', position='BTN')
        _insert_action(self.repo, 'RFIS03', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')  # 1.5/0.50 = 3.0BB
        self.assertEqual(self._rfi_result('RFIS03'), 1)

    def test_rfi_minraise_wrong_sizing(self):
        """Minraise (1.5BB) is below acceptable range."""
        _insert_hand(self.repo, 'RFIS04', position='BTN', blinds_bb=1.0)
        _insert_action(self.repo, 'RFIS04', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')  # 1.5/1.0 = 1.5BB → too low
        # Hand is AKo (tier 1) but sizing wrong → None
        self.assertIsNone(self._rfi_result('RFIS04'))

    # -- No hero cards available --

    def test_rfi_no_cards_good_sizing(self):
        """Without hero_cards, good sizing → correct."""
        _insert_hand(self.repo, 'RFIN01', position='BTN')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id='RFIN01'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFIN01', 'preflop', 'Hero', 'raise',
                       1.25, 1, 1, 'BTN')  # 2.5BB
        self.assertEqual(self._rfi_result('RFIN01'), 1)

    def test_rfi_no_cards_bad_sizing(self):
        """Without hero_cards, bad sizing → partial (None)."""
        _insert_hand(self.repo, 'RFIN02', position='BTN')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id='RFIN02'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'RFIN02', 'preflop', 'Hero', 'raise',
                       2.5, 1, 1, 'BTN')  # 5.0BB → too high
        self.assertIsNone(self._rfi_result('RFIN02'))

    # -- Position-specific range tests from PDF --

    def test_rfi_pairs_ep_range(self):
        """77+ are in EP range (tier 1), 66 is tier 2."""
        for pair in ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77']:
            self.assertIn(pair, self.classifier._RFI_TIER1, f'{pair} should be tier 1')
        self.assertIn('66', self.classifier._RFI_TIER2)
        self.assertIn('55', self.classifier._RFI_TIER2)

    def test_rfi_broadways_in_ranges(self):
        """All broadway suited hands are in EP range."""
        for hand in ['AKs', 'AQs', 'AJs', 'ATs', 'KQs', 'KJs', 'KTs',
                     'QJs', 'QTs', 'JTs']:
            self.assertIn(hand, self.classifier._RFI_TIER1,
                          f'{hand} should be tier 1')

    def test_rfi_btn_range_is_widest(self):
        """BTN range includes all 4 tiers covering majority of hand types."""
        total = (len(self.classifier._RFI_TIER1) +
                 len(self.classifier._RFI_TIER2) +
                 len(self.classifier._RFI_TIER3) +
                 len(self.classifier._RFI_TIER4))
        # ~54% of combos maps to ~80% of hand types since offsuit
        # hands (12 combos each) in tier 5 inflate combo count
        self.assertGreater(total, 100)
        self.assertLess(total, 160)

    def test_rfi_each_position_classifies(self):
        """RFI from each position with appropriate hands classifies correctly."""
        positions = [
            ('UTG', 'As Kd', 1.0),   # AKo tier 1, 2.0BB
            ('LJ', 'As 9d', 1.0),    # A9o tier 2, 2.0BB
            ('CO', 'Ah 8d', 1.0),    # A8o tier 3, 2.0BB
            ('BTN', 'Kh 7d', 1.0),   # K7o tier 4, 2.0BB
        ]
        for pos, cards, amount in positions:
            hid = f'RFIP_{pos}'
            _insert_hand(self.repo, hid, position=pos)
            self.repo.conn.execute(
                "UPDATE hands SET hero_cards=? WHERE hand_id=?", (cards, hid))
            self.repo.conn.commit()
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'raise',
                           amount, 1, 1, pos)
            result = self._rfi_result(hid)
            self.assertEqual(result, 1, f'RFI {cards} from {pos} should be correct')


# ── Multiway BB Defense Evaluation Tests (US-041) ────────────────────


class TestMultiwayBBEvaluation(unittest.TestCase):
    """Test multiway BB defense evaluation with hand-based classification.

    Based on RegLife 'Defesa Multiway do Big Blind Pré-Flop':
    - Strong hands (pairs, suited, strong offsuit): always defend
    - Trash offsuit (no pair, no suit, poor connectivity): fold
    - Marginal hands: context-dependent
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _mwbb_result(self, hand_id):
        """Get executed_correctly for lesson 8 (Multiway BB)."""
        matches = self._classify(hand_id)
        mwbb = next((m for m in matches if m.lesson_id == 8), None)
        return mwbb.executed_correctly if mwbb else None

    def _insert_multiway_hand(self, hand_id, hero_cards='Ah Kd', hero_action='check',
                              hero_amount=0, num_limpers=3):
        """Insert a BB hand with multiple callers (limped multiway)."""
        _insert_hand(self.repo, hand_id, position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        # Insert limpers (callers before BB)
        for i in range(num_limpers):
            _insert_action(self.repo, hand_id, 'preflop', f'P{i+1}', 'call',
                           0.5, 0, i + 1, f'P{i+1}')
        # Insert hero action
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', hero_action,
                       hero_amount, 1, num_limpers + 1, 'BB')

    # -- Hand set membership tests --

    def test_mwbb_defend_set_has_all_pairs(self):
        """All pairs should be in the defend set."""
        for pair in ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77',
                     '66', '55', '44', '33', '22']:
            self.assertIn(pair, self.classifier._MWBB_DEFEND,
                          f'{pair} should be in MWBB_DEFEND')

    def test_mwbb_defend_set_has_suited_aces(self):
        """All suited aces should be in the defend set."""
        for hand in ['AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s',
                     'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s']:
            self.assertIn(hand, self.classifier._MWBB_DEFEND,
                          f'{hand} should be in MWBB_DEFEND')

    def test_mwbb_defend_set_has_suited_connectors(self):
        """Key suited connectors should be in the defend set."""
        for hand in ['T9s', '98s', '87s', '76s', '65s', '54s']:
            self.assertIn(hand, self.classifier._MWBB_DEFEND,
                          f'{hand} should be in MWBB_DEFEND')

    def test_mwbb_marginal_set_has_weak_suited(self):
        """Weak suited hands should be marginal."""
        for hand in ['K2s', 'Q2s', 'J2s', 'T2s', '92s']:
            self.assertIn(hand, self.classifier._MWBB_MARGINAL,
                          f'{hand} should be in MWBB_MARGINAL')

    def test_mwbb_trash_not_in_defend_or_marginal(self):
        """Trash hands like 72o, 83o should not be in defend or marginal sets."""
        trash_hands = ['72o', '83o', '94o', 'K2o', 'Q2o', 'J2o', 'T2o']
        for hand in trash_hands:
            self.assertNotIn(hand, self.classifier._MWBB_DEFEND,
                             f'{hand} should NOT be in MWBB_DEFEND')
            self.assertNotIn(hand, self.classifier._MWBB_MARGINAL,
                             f'{hand} should NOT be in MWBB_MARGINAL')

    # -- Correct defense: strong hands --

    def test_mwbb_correct_defend_pair(self):
        """Calling with a pair in multiway BB = correct."""
        self._insert_multiway_hand('MWBB01', hero_cards='7h 7d', hero_action='check')
        self.assertEqual(self._mwbb_result('MWBB01'), 1)

    def test_mwbb_correct_defend_suited_connector(self):
        """Calling with a suited connector in multiway BB = correct."""
        self._insert_multiway_hand('MWBB02', hero_cards='Th 9h', hero_action='check')
        self.assertEqual(self._mwbb_result('MWBB02'), 1)

    def test_mwbb_correct_defend_suited_ace(self):
        """Calling with a suited ace in multiway BB = correct."""
        self._insert_multiway_hand('MWBB03', hero_cards='Ah 5h', hero_action='check')
        self.assertEqual(self._mwbb_result('MWBB03'), 1)

    def test_mwbb_correct_defend_premium_offsuit(self):
        """Calling with AKo or AQo in multiway BB = correct."""
        self._insert_multiway_hand('MWBB04', hero_cards='Ah Kd', hero_action='check')
        self.assertEqual(self._mwbb_result('MWBB04'), 1)

    def test_mwbb_correct_defend_small_pair(self):
        """Calling with 22 in multiway BB = correct (set mining)."""
        self._insert_multiway_hand('MWBB05', hero_cards='2h 2d', hero_action='check')
        self.assertEqual(self._mwbb_result('MWBB05'), 1)

    def test_mwbb_correct_defend_suited_king(self):
        """Calling with K7s in multiway BB = correct (suited, flush potential)."""
        self._insert_multiway_hand('MWBB06', hero_cards='Kh 7h', hero_action='check')
        self.assertEqual(self._mwbb_result('MWBB06'), 1)

    # -- Correct fold: trash hands --

    def test_mwbb_correct_fold_trash(self):
        """Folding 72o in multiway BB = correct."""
        self._insert_multiway_hand('MWBB10', hero_cards='7h 2d', hero_action='fold')
        self.assertEqual(self._mwbb_result('MWBB10'), 1)

    def test_mwbb_correct_fold_disconnected_offsuit(self):
        """Folding K2o in multiway BB = correct (trash hand)."""
        self._insert_multiway_hand('MWBB11', hero_cards='Kh 2d', hero_action='fold')
        self.assertEqual(self._mwbb_result('MWBB11'), 1)

    def test_mwbb_correct_fold_q2o(self):
        """Folding Q2o in multiway BB = correct (trash hand)."""
        self._insert_multiway_hand('MWBB12', hero_cards='Qh 2d', hero_action='fold')
        self.assertEqual(self._mwbb_result('MWBB12'), 1)

    # -- Incorrect defense: trash hands called --

    def test_mwbb_incorrect_defend_trash(self):
        """Calling with 72o in multiway BB = incorrect."""
        self._insert_multiway_hand('MWBB20', hero_cards='7h 2d', hero_action='check')
        self.assertEqual(self._mwbb_result('MWBB20'), 0)

    def test_mwbb_incorrect_defend_disconnected_offsuit(self):
        """Calling with 83o in multiway BB = incorrect."""
        self._insert_multiway_hand('MWBB21', hero_cards='8h 3d', hero_action='check')
        self.assertEqual(self._mwbb_result('MWBB21'), 0)

    def test_mwbb_incorrect_defend_k2o(self):
        """Calling with K2o in multiway BB = incorrect (trash)."""
        self._insert_multiway_hand('MWBB22', hero_cards='Kh 2d', hero_action='check')
        self.assertEqual(self._mwbb_result('MWBB22'), 0)

    # -- Incorrect fold: strong hands folded --

    def test_mwbb_incorrect_fold_pair(self):
        """Folding 77 from BB in multiway = incorrect."""
        self._insert_multiway_hand('MWBB30', hero_cards='7h 7d', hero_action='fold')
        self.assertEqual(self._mwbb_result('MWBB30'), 0)

    def test_mwbb_incorrect_fold_suited_connector(self):
        """Folding T9s from BB in multiway = incorrect."""
        self._insert_multiway_hand('MWBB31', hero_cards='Th 9h', hero_action='fold')
        self.assertEqual(self._mwbb_result('MWBB31'), 0)

    def test_mwbb_incorrect_fold_suited_ace(self):
        """Folding A5s from BB in multiway = incorrect (great implied odds)."""
        self._insert_multiway_hand('MWBB32', hero_cards='Ah 5h', hero_action='fold')
        self.assertEqual(self._mwbb_result('MWBB32'), 0)

    def test_mwbb_incorrect_fold_premium(self):
        """Folding AA from BB in multiway = incorrect."""
        self._insert_multiway_hand('MWBB33', hero_cards='Ah Ad', hero_action='fold')
        self.assertEqual(self._mwbb_result('MWBB33'), 0)

    # -- Marginal hands --

    def test_mwbb_marginal_weak_suited(self):
        """K2s from BB multiway = marginal (suit potential but weak)."""
        self._insert_multiway_hand('MWBB40', hero_cards='Kh 2h', hero_action='check')
        self.assertIsNone(self._mwbb_result('MWBB40'))

    def test_mwbb_marginal_medium_offsuit(self):
        """QJo from BB multiway = marginal (decent hand but context matters)."""
        self._insert_multiway_hand('MWBB41', hero_cards='Qh Jd', hero_action='check')
        self.assertIsNone(self._mwbb_result('MWBB41'))

    def test_mwbb_marginal_a9o(self):
        """A9o from BB multiway = marginal."""
        self._insert_multiway_hand('MWBB42', hero_cards='Ah 9d', hero_action='check')
        self.assertIsNone(self._mwbb_result('MWBB42'))

    def test_mwbb_marginal_fold_medium_offsuit(self):
        """Folding T9o from BB in multiway = marginal (borderline hand)."""
        self._insert_multiway_hand('MWBB43', hero_cards='Th 9d', hero_action='fold')
        self.assertIsNone(self._mwbb_result('MWBB43'))

    # -- Missing card info --

    def test_mwbb_no_cards_returns_none(self):
        """Without hero cards, evaluation is unknown (None)."""
        _insert_hand(self.repo, 'MWBB50', position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id='MWBB50'")
        self.repo.conn.commit()
        for i in range(3):
            _insert_action(self.repo, 'MWBB50', 'preflop', f'P{i+1}', 'call',
                           0.5, 0, i + 1, f'P{i+1}')
        _insert_action(self.repo, 'MWBB50', 'preflop', 'Hero', 'check', 0, 1, 4, 'BB')
        self.assertIsNone(self._mwbb_result('MWBB50'))

    # -- Detection condition: must be BB in multiway --

    def test_mwbb_not_triggered_from_btn(self):
        """Lesson 8 should not trigger when hero is BTN (not BB)."""
        _insert_hand(self.repo, 'MWBB60', position='BTN')
        for i in range(3):
            _insert_action(self.repo, 'MWBB60', 'preflop', f'P{i+1}', 'call',
                           0.5, 0, i + 1, f'P{i+1}')
        _insert_action(self.repo, 'MWBB60', 'preflop', 'Hero', 'call', 0.5, 1, 4, 'BTN')
        matches = self._classify('MWBB60')
        mwbb = next((m for m in matches if m.lesson_id == 8), None)
        self.assertIsNone(mwbb, 'Lesson 8 should not fire for non-BB positions')

    def test_mwbb_not_triggered_when_heads_up(self):
        """Lesson 8 should not trigger in a heads-up (non-multiway) pot."""
        _insert_hand(self.repo, 'MWBB61', position='BB')
        # Only one opponent raises (2 players total, not multiway)
        _insert_action(self.repo, 'MWBB61', 'preflop', 'P1', 'raise', 1.0, 0, 1, 'BTN')
        _insert_action(self.repo, 'MWBB61', 'preflop', 'Hero', 'call', 1.0, 1, 2, 'BB')
        matches = self._classify('MWBB61')
        mwbb = next((m for m in matches if m.lesson_id == 8), None)
        self.assertIsNone(mwbb, 'Lesson 8 should not fire in heads-up pot')

    def test_mwbb_triggered_on_fold_with_strong_hand(self):
        """Lesson 8 fires even when hero folds from BB in multiway."""
        self._insert_multiway_hand('MWBB62', hero_cards='Ah Ad', hero_action='fold')
        matches = self._classify('MWBB62')
        mwbb = next((m for m in matches if m.lesson_id == 8), None)
        self.assertIsNotNone(mwbb, 'Lesson 8 should fire even on fold in multiway')
        self.assertEqual(mwbb.executed_correctly, 0, 'Folding AA multiway = incorrect')


if __name__ == '__main__':
    unittest.main()
