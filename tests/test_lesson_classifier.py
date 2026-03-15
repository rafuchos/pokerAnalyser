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
        """RFI is always marked as executed correctly."""
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


if __name__ == '__main__':
    unittest.main()
