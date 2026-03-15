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


# ── BB Pre-Flop Evaluation Tests (US-042) ────────────────────────────


class TestBBPreflopEvaluation(unittest.TestCase):
    """Test BB preflop evaluation with hand-based classification.

    Based on RegLife 'Jogando no Big Blind - Pré-Flop':
    - Strong hands: always defend (call or 3-bet) from BB
    - Trash hands: fold vs any raise
    - Marginal hands: context-dependent (opener position)
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

    def _bb_result(self, hand_id):
        """Get executed_correctly for lesson 6 (BB Pre-Flop)."""
        matches = self._classify(hand_id)
        bb = next((m for m in matches if m.lesson_id == 6), None)
        return bb.executed_correctly if bb else None

    def _insert_bb_vs_raise(self, hand_id, hero_cards='Ah Kd', hero_action='call',
                             hero_amount=1.5, opener_pos='BTN', opener_amount=1.5):
        """Insert a BB hand facing a single raise from another player."""
        _insert_hand(self.repo, hand_id, position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Villain', 'raise',
                       opener_amount, 0, 1, opener_pos)
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', hero_action,
                       hero_amount, 1, 2, 'BB')

    def _insert_bb_limped(self, hand_id, hero_cards='Ah Kd', hero_action='check',
                          num_limpers=2):
        """Insert a BB hand in a limped pot (no raise, BB gets free flop)."""
        _insert_hand(self.repo, hand_id, position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        for i in range(num_limpers):
            _insert_action(self.repo, hand_id, 'preflop', f'P{i+1}', 'call',
                           0.5, 0, i + 1, f'P{i+1}')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', hero_action,
                       0, 1, num_limpers + 1, 'BB')

    # -- Hand tier set membership tests --

    def test_bb_tier1_has_premium_pairs(self):
        """Tier 1 should include 77+ (always defend vs any opener)."""
        for pair in ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77']:
            self.assertIn(pair, self.classifier._BB_TIER1,
                          f'{pair} should be in BB_TIER1')

    def test_bb_tier1_has_all_suited_aces(self):
        """All suited aces should be in tier 1 (nut flush draws are always valuable)."""
        for hand in ['AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s',
                     'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s']:
            self.assertIn(hand, self.classifier._BB_TIER1,
                          f'{hand} should be in BB_TIER1')

    def test_bb_tier1_has_strong_suited_connectors(self):
        """Key suited connectors should be in tier 1."""
        for hand in ['T9s', '98s', '87s', '76s', '65s', '54s']:
            self.assertIn(hand, self.classifier._BB_TIER1,
                          f'{hand} should be in BB_TIER1')

    def test_bb_tier1_has_strong_offsuit(self):
        """AKo, AQo, AJo, KQo are always defend vs any opener."""
        for hand in ['AKo', 'AQo', 'AJo', 'KQo']:
            self.assertIn(hand, self.classifier._BB_TIER1,
                          f'{hand} should be in BB_TIER1')

    def test_bb_tier2_has_small_pairs(self):
        """Small pairs (66-22) should be tier 2 (defend vs MP+)."""
        for pair in ['66', '55', '44', '33', '22']:
            self.assertIn(pair, self.classifier._BB_TIER2,
                          f'{pair} should be in BB_TIER2')

    def test_bb_tier2_has_medium_offsuit_broadways(self):
        """ATo, KJo, KTo are tier 2 (defend vs MP+)."""
        for hand in ['ATo', 'KJo', 'KTo']:
            self.assertIn(hand, self.classifier._BB_TIER2,
                          f'{hand} should be in BB_TIER2')

    def test_bb_tier3_has_weak_suited_kings(self):
        """K5s-K2s should be tier 3 (defend vs CO+)."""
        for hand in ['K5s', 'K4s', 'K3s', 'K2s']:
            self.assertIn(hand, self.classifier._BB_TIER3,
                          f'{hand} should be in BB_TIER3')

    def test_bb_tier4_has_medium_offsuit_connected(self):
        """T9o, 98o, 87o should be tier 4 (defend vs BTN/SB only)."""
        for hand in ['T9o', '98o', '87o']:
            self.assertIn(hand, self.classifier._BB_TIER4,
                          f'{hand} should be in BB_TIER4')

    def test_bb_trash_not_in_any_tier(self):
        """Disconnected trash hands should not be in any tier."""
        trash_hands = ['72o', '83o', '94o', 'K2o', 'Q2o', 'J2o', 'T2o']
        for hand in trash_hands:
            self.assertNotIn(hand, self.classifier._BB_TIER1,
                             f'{hand} should NOT be in BB_TIER1')
            self.assertNotIn(hand, self.classifier._BB_TIER2,
                             f'{hand} should NOT be in BB_TIER2')
            self.assertNotIn(hand, self.classifier._BB_TIER3,
                             f'{hand} should NOT be in BB_TIER3')
            self.assertNotIn(hand, self.classifier._BB_TIER4,
                             f'{hand} should NOT be in BB_TIER4')

    def test_bb_pos_defend_tier_utg_is_1(self):
        """UTG opener → BB uses tier 1 (tightest defense)."""
        self.assertEqual(self.classifier._BB_POS_DEFEND_TIER.get('UTG'), 1)

    def test_bb_pos_defend_tier_mp_is_2(self):
        """MP/HJ opener → BB uses tier 2 defense."""
        self.assertEqual(self.classifier._BB_POS_DEFEND_TIER.get('MP'), 2)
        self.assertEqual(self.classifier._BB_POS_DEFEND_TIER.get('HJ'), 2)

    def test_bb_pos_defend_tier_co_is_3(self):
        """CO opener → BB uses tier 3 defense."""
        self.assertEqual(self.classifier._BB_POS_DEFEND_TIER.get('CO'), 3)

    def test_bb_pos_defend_tier_btn_is_4(self):
        """BTN opener → BB uses tier 4 (widest defense)."""
        self.assertEqual(self.classifier._BB_POS_DEFEND_TIER.get('BTN'), 4)

    # -- _bb_hand_tier() helper tests --

    def test_bb_hand_tier_pair_77(self):
        """77 is tier 1."""
        self.assertEqual(self.classifier._bb_hand_tier('77'), 1)

    def test_bb_hand_tier_small_pair(self):
        """22 is tier 2."""
        self.assertEqual(self.classifier._bb_hand_tier('22'), 2)

    def test_bb_hand_tier_suited_ace(self):
        """A5s is tier 1."""
        self.assertEqual(self.classifier._bb_hand_tier('A5s'), 1)

    def test_bb_hand_tier_trash(self):
        """72o is tier 5 (trash)."""
        self.assertEqual(self.classifier._bb_hand_tier('72o'), 5)

    def test_bb_hand_tier_weak_king_suited(self):
        """K2s is tier 3."""
        self.assertEqual(self.classifier._bb_hand_tier('K2s'), 3)

    # -- Correct defense: strong hands defended --

    def test_bb_correct_defend_premium_vs_btn(self):
        """Calling with AKo vs BTN raise = correct."""
        self._insert_bb_vs_raise('BBPF01', hero_cards='Ah Kd',
                                  hero_action='call', opener_pos='BTN')
        self.assertEqual(self._bb_result('BBPF01'), 1)

    def test_bb_correct_defend_pair_vs_utg(self):
        """Calling with 99 vs UTG raise = correct (tier 1 pair)."""
        self._insert_bb_vs_raise('BBPF02', hero_cards='9h 9d',
                                  hero_action='call', opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF02'), 1)

    def test_bb_correct_defend_suited_ace_vs_utg(self):
        """Calling with A5s vs UTG raise = correct (tier 1 hand)."""
        self._insert_bb_vs_raise('BBPF03', hero_cards='Ah 5h',
                                  hero_action='call', opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF03'), 1)

    def test_bb_correct_defend_suited_connector_vs_btn(self):
        """Calling with 76s vs BTN raise = correct (tier 1)."""
        self._insert_bb_vs_raise('BBPF04', hero_cards='7h 6h',
                                  hero_action='call', opener_pos='BTN')
        self.assertEqual(self._bb_result('BBPF04'), 1)

    def test_bb_correct_defend_small_pair_vs_mp(self):
        """Calling with 33 vs MP raise = correct (tier 2 vs tier 2 opener)."""
        self._insert_bb_vs_raise('BBPF05', hero_cards='3h 3d',
                                  hero_action='call', opener_pos='MP')
        self.assertEqual(self._bb_result('BBPF05'), 1)

    def test_bb_correct_defend_tier2_hand_vs_hj(self):
        """Calling with 22 vs HJ raise = correct (tier 2 vs tier 2)."""
        self._insert_bb_vs_raise('BBPF06', hero_cards='2h 2d',
                                  hero_action='call', opener_pos='HJ')
        self.assertEqual(self._bb_result('BBPF06'), 1)

    def test_bb_correct_defend_tier3_hand_vs_co(self):
        """Calling with K2s vs CO raise = correct (tier 3 vs tier 3)."""
        self._insert_bb_vs_raise('BBPF07', hero_cards='Kh 2h',
                                  hero_action='call', opener_pos='CO')
        self.assertEqual(self._bb_result('BBPF07'), 1)

    def test_bb_correct_defend_tier4_hand_vs_btn(self):
        """Calling with A7o vs BTN raise = correct (tier 4 vs tier 4)."""
        self._insert_bb_vs_raise('BBPF08', hero_cards='Ah 7d',
                                  hero_action='call', opener_pos='BTN')
        self.assertEqual(self._bb_result('BBPF08'), 1)

    def test_bb_correct_defend_3bet_with_strong_hand(self):
        """3-betting with AA vs BTN raise = correct."""
        self._insert_bb_vs_raise('BBPF09', hero_cards='Ah Ad',
                                  hero_action='raise', opener_pos='BTN')
        self.assertEqual(self._bb_result('BBPF09'), 1)

    # -- Correct fold: trash hands vs raises --

    def test_bb_correct_fold_trash_vs_utg(self):
        """Folding 72o vs UTG raise = correct (trash hand)."""
        self._insert_bb_vs_raise('BBPF10', hero_cards='7h 2d',
                                  hero_action='fold', hero_amount=0, opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF10'), 1)

    def test_bb_correct_fold_trash_vs_btn(self):
        """Folding 83o vs BTN raise = correct (trash even vs wide opener)."""
        self._insert_bb_vs_raise('BBPF11', hero_cards='8h 3d',
                                  hero_action='fold', hero_amount=0, opener_pos='BTN')
        self.assertEqual(self._bb_result('BBPF11'), 1)

    def test_bb_correct_fold_tier5_vs_mp(self):
        """Folding K2o vs MP raise = correct (tier 5 trash)."""
        self._insert_bb_vs_raise('BBPF12', hero_cards='Kh 2d',
                                  hero_action='fold', hero_amount=0, opener_pos='MP')
        self.assertEqual(self._bb_result('BBPF12'), 1)

    def test_bb_correct_fold_tier4_hand_vs_utg(self):
        """Folding T9o vs UTG raise = correct (tier 4 vs tier 1 opener)."""
        self._insert_bb_vs_raise('BBPF13', hero_cards='Th 9d',
                                  hero_action='fold', hero_amount=0, opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF13'), 1)

    # -- Incorrect fold: strong hands folded --

    def test_bb_incorrect_fold_premium_vs_btn(self):
        """Folding AQo from BB vs BTN raise = incorrect."""
        self._insert_bb_vs_raise('BBPF20', hero_cards='Ah Qd',
                                  hero_action='fold', hero_amount=0, opener_pos='BTN')
        self.assertEqual(self._bb_result('BBPF20'), 0)

    def test_bb_incorrect_fold_pair_vs_mp(self):
        """Folding 55 from BB vs MP raise = incorrect (tier 2 vs tier 2 opener)."""
        self._insert_bb_vs_raise('BBPF21', hero_cards='5h 5d',
                                  hero_action='fold', hero_amount=0, opener_pos='MP')
        self.assertEqual(self._bb_result('BBPF21'), 0)

    def test_bb_incorrect_fold_suited_ace_vs_utg(self):
        """Folding A7s from BB vs UTG raise = incorrect (tier 1 hand)."""
        self._insert_bb_vs_raise('BBPF22', hero_cards='Ah 7h',
                                  hero_action='fold', hero_amount=0, opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF22'), 0)

    def test_bb_incorrect_fold_suited_connector_vs_btn(self):
        """Folding T9s from BB vs BTN raise = incorrect."""
        self._insert_bb_vs_raise('BBPF23', hero_cards='Th 9h',
                                  hero_action='fold', hero_amount=0, opener_pos='BTN')
        self.assertEqual(self._bb_result('BBPF23'), 0)

    def test_bb_incorrect_fold_premium_vs_utg(self):
        """Folding KQs from BB vs UTG raise = incorrect (tier 1)."""
        self._insert_bb_vs_raise('BBPF24', hero_cards='Kh Qh',
                                  hero_action='fold', hero_amount=0, opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF24'), 0)

    # -- Incorrect defense: trash hands defended --

    def test_bb_incorrect_defend_trash_vs_utg(self):
        """Calling with 83o vs UTG raise = incorrect."""
        self._insert_bb_vs_raise('BBPF30', hero_cards='8h 3d',
                                  hero_action='call', opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF30'), 0)

    def test_bb_incorrect_defend_trash_vs_mp(self):
        """Calling with 72o vs MP raise = incorrect."""
        self._insert_bb_vs_raise('BBPF31', hero_cards='7h 2d',
                                  hero_action='call', opener_pos='MP')
        self.assertEqual(self._bb_result('BBPF31'), 0)

    def test_bb_incorrect_defend_tier4_vs_utg(self):
        """Calling with T9o vs UTG raise = incorrect (tier 4 vs tier 1 opener)."""
        self._insert_bb_vs_raise('BBPF32', hero_cards='Th 9d',
                                  hero_action='call', opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF32'), 0)

    def test_bb_incorrect_defend_tier3_vs_utg(self):
        """Calling with JTo vs UTG raise = incorrect (tier 3 vs tier 1 opener)."""
        self._insert_bb_vs_raise('BBPF33', hero_cards='Jh Td',
                                  hero_action='call', opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF33'), 0)

    # -- Marginal hands: one tier above opener max --

    def test_bb_marginal_tier2_hand_vs_utg(self):
        """66 is tier 2; vs UTG (tier 1 opener) = marginal."""
        self._insert_bb_vs_raise('BBPF40', hero_cards='6h 6d',
                                  hero_action='call', opener_pos='UTG')
        self.assertIsNone(self._bb_result('BBPF40'))

    def test_bb_marginal_tier3_hand_vs_mp(self):
        """K2s is tier 3; vs MP (tier 2 opener) = marginal."""
        self._insert_bb_vs_raise('BBPF41', hero_cards='Kh 2h',
                                  hero_action='call', opener_pos='MP')
        self.assertIsNone(self._bb_result('BBPF41'))

    def test_bb_marginal_tier4_hand_vs_co(self):
        """Q5s is tier 4; vs CO (tier 3 opener) = marginal."""
        self._insert_bb_vs_raise('BBPF42', hero_cards='Qh 5h',
                                  hero_action='call', opener_pos='CO')
        self.assertIsNone(self._bb_result('BBPF42'))

    def test_bb_marginal_fold_tier2_vs_utg(self):
        """Folding 22 vs UTG = marginal (tier 2 vs tier 1 opener)."""
        self._insert_bb_vs_raise('BBPF43', hero_cards='2h 2d',
                                  hero_action='fold', hero_amount=0, opener_pos='UTG')
        self.assertIsNone(self._bb_result('BBPF43'))

    def test_bb_marginal_tier2_vs_ep(self):
        """ATo is tier 2; vs EP (tier 1 opener) = marginal."""
        self._insert_bb_vs_raise('BBPF44', hero_cards='Ah Td',
                                  hero_action='call', opener_pos='EP')
        self.assertIsNone(self._bb_result('BBPF44'))

    # -- Limped pot: BB gets free flop --

    def test_bb_limped_pot_check_is_correct(self):
        """BB checking in limped pot = correct (free flop)."""
        self._insert_bb_limped('BBPF50', hero_cards='7h 2d', hero_action='check')
        self.assertEqual(self._bb_result('BBPF50'), 1)

    def test_bb_limped_pot_premium_check_correct(self):
        """BB checking with AA in limped pot = correct."""
        self._insert_bb_limped('BBPF51', hero_cards='Ah Ad', hero_action='check')
        self.assertEqual(self._bb_result('BBPF51'), 1)

    def test_bb_limped_pot_trash_check_correct(self):
        """BB checking with 72o in limped pot = correct (no raise to fold to)."""
        self._insert_bb_limped('BBPF52', hero_cards='7h 2d', hero_action='check')
        self.assertEqual(self._bb_result('BBPF52'), 1)

    # -- No hero cards: evaluation not possible --

    def test_bb_no_cards_returns_none(self):
        """Without hero cards, evaluation is unknown (None)."""
        _insert_hand(self.repo, 'BBPF60', position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id='BBPF60'")
        self.repo.conn.commit()
        _insert_action(self.repo, 'BBPF60', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'BBPF60', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')
        self.assertIsNone(self._bb_result('BBPF60'))

    # -- Detection: lesson 6 trigger conditions --

    def test_bb_lesson_fires_for_bb_vs_raise(self):
        """Lesson 6 triggers for any BB hand with preflop actions."""
        _insert_hand(self.repo, 'BBPF80', position='BB')
        _insert_action(self.repo, 'BBPF80', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'BBPF80', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')
        matches = self._classify('BBPF80')
        bb_match = next((m for m in matches if m.lesson_id == 6), None)
        self.assertIsNotNone(bb_match, 'Lesson 6 should fire for BB hands')

    def test_bb_lesson_does_not_fire_for_non_bb(self):
        """Lesson 6 should not fire when hero is not in BB."""
        _insert_hand(self.repo, 'BBPF81', position='BTN')
        _insert_action(self.repo, 'BBPF81', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        matches = self._classify('BBPF81')
        bb_match = next((m for m in matches if m.lesson_id == 6), None)
        self.assertIsNone(bb_match, 'Lesson 6 should not fire for non-BB position')

    def test_bb_lesson_fires_even_on_fold(self):
        """Lesson 6 fires even when hero folds from BB (to detect incorrect folds)."""
        self._insert_bb_vs_raise('BBPF82', hero_cards='Ah Ad',
                                  hero_action='fold', hero_amount=0, opener_pos='BTN')
        matches = self._classify('BBPF82')
        bb_match = next((m for m in matches if m.lesson_id == 6), None)
        self.assertIsNotNone(bb_match, 'Lesson 6 should fire even on fold')
        self.assertEqual(bb_match.executed_correctly, 0, 'Folding AA from BB = incorrect')

    # -- Position coverage: all opener positions --

    def test_bb_each_position_strong_hand_defends(self):
        """With AA (tier 1), defending vs any opener is always correct."""
        positions = ['UTG', 'EP', 'LJ', 'MP', 'HJ', 'CO', 'BTN', 'SB']
        for i, pos in enumerate(positions):
            hid = f'BBPOS_{i}'
            self._insert_bb_vs_raise(hid, hero_cards='Ah Ad',
                                      hero_action='call', opener_pos=pos)
            result = self._bb_result(hid)
            self.assertEqual(result, 1, f'Defending AA vs {pos} should be correct')

    def test_bb_tier4_hand_only_correct_vs_btn_sb(self):
        """T9o (tier 4) is correct to defend vs BTN/SB, incorrect vs UTG."""
        # vs BTN: tier 4 hand vs tier 4 opener → correct
        self._insert_bb_vs_raise('BBPF90', hero_cards='Th 9d',
                                  hero_action='call', opener_pos='BTN')
        self.assertEqual(self._bb_result('BBPF90'), 1)
        # vs UTG: tier 4 vs tier 1 → too weak, incorrect
        self._insert_bb_vs_raise('BBPF91', hero_cards='Th 9d',
                                  hero_action='call', opener_pos='UTG')
        self.assertEqual(self._bb_result('BBPF91'), 0)


# ── Blind War Evaluation Tests (US-043) ──────────────────────────────


class TestBlindWarEvaluation(unittest.TestCase):
    """Test blind war evaluation for lessons 7 (SB vs BB) and 9 (BB vs SB).

    Based on RegLife 'O Conceito de Blind War - SB vs BB' and 'Blind War BB vs SB':
    - SB should raise wide in blind war, never limp.
    - BB defends wider vs SB than vs any other position.
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

    def _sb_result(self, hand_id):
        """Get executed_correctly for lesson 7 (SB vs BB Blind War)."""
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 7), None)
        return m.executed_correctly if m else None

    def _bb_result(self, hand_id):
        """Get executed_correctly for lesson 9 (BB vs SB Blind War)."""
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 9), None)
        return m.executed_correctly if m else None

    def _insert_sb_war(self, hand_id, hero_cards='Ah Kd', hero_action='raise',
                       hero_amount=1.5):
        """Insert a blind war hand where Hero is SB raising."""
        _insert_hand(self.repo, hand_id, position='SB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        # Others fold before SB
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, hand_id, 'preflop', 'P2', 'fold', 0, 0, 2, 'MP')
        _insert_action(self.repo, hand_id, 'preflop', 'P3', 'fold', 0, 0, 3, 'CO')
        _insert_action(self.repo, hand_id, 'preflop', 'P4', 'fold', 0, 0, 4, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', hero_action,
                       hero_amount, 1, 5, 'SB')
        _insert_action(self.repo, hand_id, 'preflop', 'P5', 'call', 1.5, 0, 6, 'BB')

    def _insert_bb_war(self, hand_id, hero_cards='Ah Kd', hero_action='call',
                       hero_amount=1.5):
        """Insert a blind war hand where Hero is BB facing SB steal."""
        _insert_hand(self.repo, hand_id, position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        # Others fold before SB
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, hand_id, 'preflop', 'P2', 'fold', 0, 0, 2, 'MP')
        _insert_action(self.repo, hand_id, 'preflop', 'P3', 'fold', 0, 0, 3, 'CO')
        _insert_action(self.repo, hand_id, 'preflop', 'P4', 'fold', 0, 0, 4, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'P5', 'raise', 1.5, 0, 5, 'SB')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', hero_action,
                       hero_amount, 1, 6, 'BB')

    # ── Data set membership tests ────────────────────────────────────

    def test_sb_war_extra_exists(self):
        """_SB_WAR_EXTRA data set should be populated."""
        self.assertGreater(len(self.classifier._SB_WAR_EXTRA), 0)

    def test_sb_war_extra_contains_weak_offsuit(self):
        """_SB_WAR_EXTRA includes hands beyond BTN range for SB steal."""
        for hand in ['Q5o', 'J6o', 'T6o', '96o', '85o', '74o', '73o', '72o']:
            self.assertIn(hand, self.classifier._SB_WAR_EXTRA,
                          f'{hand} should be in _SB_WAR_EXTRA')

    def test_bw_bb_defend_exists(self):
        """_BW_BB_DEFEND data set should be populated."""
        self.assertGreater(len(self.classifier._BW_BB_DEFEND), 0)

    def test_bw_bb_defend_covers_all_pairs(self):
        """All pairs should be in _BW_BB_DEFEND (never fold a pair in blind war)."""
        for pair in ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77',
                     '66', '55', '44', '33', '22']:
            self.assertIn(pair, self.classifier._BW_BB_DEFEND,
                          f'{pair} should be in _BW_BB_DEFEND')

    def test_bw_bb_defend_covers_all_suited_aces(self):
        """All suited aces in _BW_BB_DEFEND (flush equity vs wide SB range)."""
        for hand in ['AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s',
                     'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s']:
            self.assertIn(hand, self.classifier._BW_BB_DEFEND,
                          f'{hand} should be in _BW_BB_DEFEND')

    def test_bw_bb_defend_covers_all_offsuit_aces(self):
        """All offsuit aces should be in _BW_BB_DEFEND."""
        for hand in ['AKo', 'AQo', 'AJo', 'ATo', 'A9o', 'A8o',
                     'A7o', 'A6o', 'A5o', 'A4o', 'A3o', 'A2o']:
            self.assertIn(hand, self.classifier._BW_BB_DEFEND,
                          f'{hand} should be in _BW_BB_DEFEND')

    def test_bw_bb_defend_covers_weak_suited_hands(self):
        """Weak suited hands should be in _BW_BB_DEFEND (suit value in BW)."""
        for hand in ['72s', '32s', 'J2s', 'T2s', '62s']:
            self.assertIn(hand, self.classifier._BW_BB_DEFEND,
                          f'{hand} should be in _BW_BB_DEFEND')

    def test_bw_bb_marginal_exists(self):
        """_BW_BB_MARGINAL data set should be populated."""
        self.assertGreater(len(self.classifier._BW_BB_MARGINAL), 0)

    def test_bw_bb_marginal_contains_weak_offsuit(self):
        """_BW_BB_MARGINAL includes borderline offsuit hands."""
        for hand in ['K5o', 'Q5o', 'J7o', 'T7o', '96o', '85o', '74o', '72o', '32o']:
            self.assertIn(hand, self.classifier._BW_BB_MARGINAL,
                          f'{hand} should be in _BW_BB_MARGINAL')

    def test_no_overlap_between_defend_and_marginal(self):
        """_BW_BB_DEFEND and _BW_BB_MARGINAL must not share any hands."""
        overlap = self.classifier._BW_BB_DEFEND & self.classifier._BW_BB_MARGINAL
        self.assertEqual(overlap, set(),
                         f'Overlap between DEFEND and MARGINAL: {overlap}')

    # ── Lesson 7: SB vs BB evaluation tests ─────────────────────────

    def test_sb_raises_tier1_hand_correct(self):
        """SB raising with AA (Tier 1) in blind war = correct."""
        self._insert_sb_war('SBW01', hero_cards='Ah Ad')
        self.assertEqual(self._sb_result('SBW01'), 1)

    def test_sb_raises_tier2_hand_correct(self):
        """SB raising with AJo (Tier 2 area) in blind war = correct."""
        self._insert_sb_war('SBW02', hero_cards='Ah Jd')
        self.assertEqual(self._sb_result('SBW02'), 1)

    def test_sb_raises_tier3_hand_correct(self):
        """SB raising with A8o (Tier 3) in blind war = correct."""
        self._insert_sb_war('SBW03', hero_cards='Ah 8d')
        self.assertEqual(self._sb_result('SBW03'), 1)

    def test_sb_raises_tier4_hand_correct(self):
        """SB raising with T9o (Tier 4, BTN range) in blind war = correct."""
        self._insert_sb_war('SBW04', hero_cards='Th 9d')
        self.assertEqual(self._sb_result('SBW04'), 1)

    def test_sb_raises_sb_extra_q5o_correct(self):
        """SB raising Q5o (in _SB_WAR_EXTRA) = correct steal."""
        self._insert_sb_war('SBW05', hero_cards='Qh 5d')
        self.assertEqual(self._sb_result('SBW05'), 1)

    def test_sb_raises_sb_extra_j6o_correct(self):
        """SB raising J6o (in _SB_WAR_EXTRA) = correct steal."""
        self._insert_sb_war('SBW06', hero_cards='Jh 6d')
        self.assertEqual(self._sb_result('SBW06'), 1)

    def test_sb_raises_sb_extra_72o_correct(self):
        """SB raising 72o (in _SB_WAR_EXTRA) = correct steal."""
        self._insert_sb_war('SBW07', hero_cards='7h 2d')
        self.assertEqual(self._sb_result('SBW07'), 1)

    def test_sb_raises_clear_trash_incorrect(self):
        """SB raising 32o (clear trash, not in any range) = incorrect."""
        self._insert_sb_war('SBW08', hero_cards='3h 2d')
        self.assertEqual(self._sb_result('SBW08'), 0)

    def test_sb_raises_42o_incorrect(self):
        """SB raising 42o (clear trash) = incorrect."""
        self._insert_sb_war('SBW09', hero_cards='4h 2d')
        self.assertEqual(self._sb_result('SBW09'), 0)

    def test_sb_raises_no_cards_correct(self):
        """SB raising without hero cards recorded = correct (can't evaluate)."""
        _insert_hand(self.repo, 'SBW10', position='SB')
        # hero_cards defaults to 'Ah Kd' from _make_hand; override with NULL
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('SBW10',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'SBW10', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'SBW10', 'preflop', 'P2', 'fold', 0, 0, 2, 'BTN')
        _insert_action(self.repo, 'SBW10', 'preflop', 'Hero', 'raise', 1.5, 1, 3, 'SB')
        _insert_action(self.repo, 'SBW10', 'preflop', 'P3', 'call', 1.5, 0, 4, 'BB')
        self.assertEqual(self._sb_result('SBW10'), 1)

    def test_sb_war_fires_for_sb_position(self):
        """Lesson 7 fires when hero is SB and raises in blind war."""
        self._insert_sb_war('SBW11', hero_cards='Ah Kd')
        matches = self._classify('SBW11')
        ids = [m.lesson_id for m in matches]
        self.assertIn(7, ids)

    def test_sb_war_does_not_fire_for_btn(self):
        """Lesson 7 should not fire when hero is BTN (not SB)."""
        _insert_hand(self.repo, 'SBW12', position='BTN')
        _insert_action(self.repo, 'SBW12', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        matches = self._classify('SBW12')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(7, ids)

    def test_sb_war_does_not_fire_when_not_blind_war(self):
        """Lesson 7 should not fire when other players are in the pot."""
        _insert_hand(self.repo, 'SBW13', position='SB')
        _insert_action(self.repo, 'SBW13', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'SBW13', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'SB')
        matches = self._classify('SBW13')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(7, ids)

    def test_sb_raises_suited_hand_tier4_correct(self):
        """SB raising with J7s (suited, in tier 4 via BTN range) = correct."""
        # J7s is not in tier 1-4... let me check. Actually let me use a clearly suited hand.
        # KQs is tier 1, clearly correct.
        self._insert_sb_war('SBW14', hero_cards='Kh Qh')
        self.assertEqual(self._sb_result('SBW14'), 1)

    def test_sb_raises_96o_correct(self):
        """SB raising 96o (in _SB_WAR_EXTRA) = correct steal."""
        self._insert_sb_war('SBW15', hero_cards='9h 6d')
        self.assertEqual(self._sb_result('SBW15'), 1)

    # ── Lesson 9: BB vs SB evaluation tests ─────────────────────────

    def test_bb_defends_premium_pair_correct(self):
        """BB calling AA vs SB steal = correct."""
        self._insert_bb_war('BBW01', hero_cards='Ah Ad')
        self.assertEqual(self._bb_result('BBW01'), 1)

    def test_bb_folds_premium_pair_incorrect(self):
        """BB folding AA vs SB steal = incorrect (should always defend)."""
        self._insert_bb_war('BBW02', hero_cards='Ah Ad', hero_action='fold',
                            hero_amount=0)
        self.assertEqual(self._bb_result('BBW02'), 0)

    def test_bb_defends_suited_connector_correct(self):
        """BB calling 98s vs SB steal = correct (suited hand, always defend)."""
        self._insert_bb_war('BBW03', hero_cards='9h 8h')
        self.assertEqual(self._bb_result('BBW03'), 1)

    def test_bb_folds_suited_connector_incorrect(self):
        """BB folding 87s vs SB steal = incorrect (suited hand should defend)."""
        self._insert_bb_war('BBW04', hero_cards='8h 7h', hero_action='fold',
                            hero_amount=0)
        self.assertEqual(self._bb_result('BBW04'), 0)

    def test_bb_defends_offsuit_ace_correct(self):
        """BB calling A5o vs SB steal = correct (all Ax defend in blind war)."""
        self._insert_bb_war('BBW05', hero_cards='Ah 5d')
        self.assertEqual(self._bb_result('BBW05'), 1)

    def test_bb_folds_offsuit_ace_incorrect(self):
        """BB folding A2o vs SB steal = incorrect (Ax should defend in blind war)."""
        self._insert_bb_war('BBW06', hero_cards='Ah 2d', hero_action='fold',
                            hero_amount=0)
        self.assertEqual(self._bb_result('BBW06'), 0)

    def test_bb_defends_offsuit_broadway_correct(self):
        """BB calling KJo vs SB steal = correct."""
        self._insert_bb_war('BBW07', hero_cards='Kh Jd')
        self.assertEqual(self._bb_result('BBW07'), 1)

    def test_bb_defends_marginal_hand_unknown(self):
        """BB calling Q5o (marginal) vs SB steal = None (borderline)."""
        self._insert_bb_war('BBW08', hero_cards='Qh 5d')
        self.assertIsNone(self._bb_result('BBW08'))

    def test_bb_folds_marginal_hand_unknown(self):
        """BB folding T6o (marginal) vs SB steal = None (borderline)."""
        self._insert_bb_war('BBW09', hero_cards='Th 6d', hero_action='fold',
                            hero_amount=0)
        self.assertIsNone(self._bb_result('BBW09'))

    def test_bb_defends_marginal_72o_unknown(self):
        """BB calling 72o (marginal in blind war) = None."""
        self._insert_bb_war('BBW10', hero_cards='7h 2d')
        self.assertIsNone(self._bb_result('BBW10'))

    def test_bb_no_hero_cards_unknown(self):
        """BB with no hero cards recorded = None (can't evaluate)."""
        _insert_hand(self.repo, 'BBW11', position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('BBW11',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BBW11', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'BBW11', 'preflop', 'P2', 'fold', 0, 0, 2, 'BTN')
        _insert_action(self.repo, 'BBW11', 'preflop', 'P3', 'raise', 1.5, 0, 3, 'SB')
        _insert_action(self.repo, 'BBW11', 'preflop', 'Hero', 'call', 1.5, 1, 4, 'BB')
        self.assertIsNone(self._bb_result('BBW11'))

    def test_bb_war_fires_for_bb_position(self):
        """Lesson 9 fires when hero is BB facing SB steal."""
        self._insert_bb_war('BBW12', hero_cards='Kh Qd')
        matches = self._classify('BBW12')
        ids = [m.lesson_id for m in matches]
        self.assertIn(9, ids)

    def test_bb_war_does_not_fire_for_sb(self):
        """Lesson 9 should not fire when hero is SB (not BB)."""
        self._insert_sb_war('BBW13', hero_cards='Ah Kd')
        matches = self._classify('BBW13')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(9, ids)

    def test_bb_war_does_not_fire_when_not_blind_war(self):
        """Lesson 9 should not fire when opener is not SB (UTG open vs BB)."""
        _insert_hand(self.repo, 'BBW14', position='BB')
        _insert_action(self.repo, 'BBW14', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'BBW14', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')
        matches = self._classify('BBW14')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(9, ids)

    def test_bb_3bets_strong_hand_correct(self):
        """BB 3-betting AA vs SB steal = correct (aggressive defense is also correct)."""
        _insert_hand(self.repo, 'BBW15', position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", ('Ah Ad', 'BBW15'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BBW15', 'preflop', 'P1', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'BBW15', 'preflop', 'P2', 'fold', 0, 0, 2, 'BTN')
        _insert_action(self.repo, 'BBW15', 'preflop', 'P3', 'raise', 1.5, 0, 3, 'SB')
        _insert_action(self.repo, 'BBW15', 'preflop', 'Hero', 'raise', 5.0, 1, 4, 'BB')
        self.assertEqual(self._bb_result('BBW15'), 1)

    def test_bb_war_also_fires_lesson_6(self):
        """In a blind war, BB hands also trigger lesson 6 (BB Pre-Flop)."""
        self._insert_bb_war('BBW16', hero_cards='Ah Kd')
        matches = self._classify('BBW16')
        ids = [m.lesson_id for m in matches]
        self.assertIn(6, ids)  # BB Pre-Flop lesson
        self.assertIn(9, ids)  # BB vs SB Blind War lesson

    def test_sb_war_also_fires_lesson_1(self):
        """SB raising in blind war also triggers lesson 1 (RFI)."""
        self._insert_sb_war('SBW16', hero_cards='Ah Kd')
        matches = self._classify('SBW16')
        ids = [m.lesson_id for m in matches]
        self.assertIn(1, ids)   # RFI lesson
        self.assertIn(7, ids)   # SB vs BB Blind War lesson

    def test_bb_defends_low_pair_correct(self):
        """BB calling 22 vs SB steal = correct (all pairs defend in blind war)."""
        self._insert_bb_war('BBW17', hero_cards='2h 2d')
        self.assertEqual(self._bb_result('BBW17'), 1)

    def test_bb_folds_low_pair_incorrect(self):
        """BB folding 22 vs SB steal = incorrect (pairs should defend)."""
        self._insert_bb_war('BBW18', hero_cards='2h 2d', hero_action='fold',
                            hero_amount=0)
        self.assertEqual(self._bb_result('BBW18'), 0)

    def test_bb_defends_kqo_correct(self):
        """BB calling KQo vs SB steal = correct (strong offsuit broadways defend)."""
        self._insert_bb_war('BBW19', hero_cards='Kh Qd')
        self.assertEqual(self._bb_result('BBW19'), 1)

    def test_bb_defends_76o_correct(self):
        """BB calling 76o vs SB steal = correct (connected hand worth defending)."""
        self._insert_bb_war('BBW20', hero_cards='7h 6d')
        self.assertEqual(self._bb_result('BBW20'), 1)

    def test_sb_raises_t6o_correct(self):
        """SB raising T6o (in _SB_WAR_EXTRA) = correct steal."""
        self._insert_sb_war('SBW17', hero_cards='Th 6d')
        self.assertEqual(self._sb_result('SBW17'), 1)

    def test_sb_raises_93o_correct(self):
        """SB raising 93o (in _SB_WAR_EXTRA) = correct steal."""
        self._insert_sb_war('SBW18', hero_cards='9h 3d')
        self.assertEqual(self._sb_result('SBW18'), 1)

    def test_sb_raises_53o_correct(self):
        """SB raising 53o (in _SB_WAR_EXTRA) = correct steal."""
        self._insert_sb_war('SBW19', hero_cards='5h 3d')
        self.assertEqual(self._sb_result('SBW19'), 1)

    def test_sb_raises_62o_incorrect_if_not_in_range(self):
        """SB raising 62o - not in any range - should be incorrect."""
        # 62o is not in tier 1-4 and not in _SB_WAR_EXTRA
        self.assertNotIn('62o', self.classifier._SB_WAR_EXTRA)
        rfi_tier = self.classifier._rfi_hand_tier('62o')
        self.assertGreater(rfi_tier, 4, '62o should not be in RFI tier 1-4')
        self._insert_sb_war('SBW20', hero_cards='6h 2d')
        self.assertEqual(self._sb_result('SBW20'), 0)


# ── Flat / 3-Bet Evaluation Tests (US-044, Lesson 2) ────────────────


class TestFlat3BetEvaluation(unittest.TestCase):
    """Test flat/3-bet evaluation with position-based range validation.

    Based on RegLife 'Ranges de Flat e 3-BET':
    - Strong hands: in range for position (correct flat or 3-bet)
    - Trash hands: too weak to flat or 3-bet
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

    def _flat3bet_result(self, hand_id):
        """Get executed_correctly for lesson 2 (Flat/3-Bet)."""
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 2), None)
        return m.executed_correctly if m else None

    def _insert_flat(self, hand_id, hero_cards='Ah Kd', hero_pos='BTN',
                     opener_pos='CO', hero_amount=1.5, opener_amount=1.5):
        """Insert a hand where hero flat-calls an open raise."""
        _insert_hand(self.repo, hand_id, position=hero_pos)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Villain', 'raise',
                       opener_amount, 0, 1, opener_pos)
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       hero_amount, 1, 2, hero_pos)

    def _insert_3bet(self, hand_id, hero_cards='Ah Kd', hero_pos='BTN',
                     opener_pos='CO', hero_amount=4.5, opener_amount=1.5):
        """Insert a hand where hero 3-bets an open raise."""
        _insert_hand(self.repo, hand_id, position=hero_pos)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Villain', 'raise',
                       opener_amount, 0, 1, opener_pos)
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       hero_amount, 1, 2, hero_pos)

    # -- Flat range tier membership tests --

    def test_flat_tier1_has_suited_connectors(self):
        """Suited connectors are tier 1 for flatting (good vs EP)."""
        for hand in ['T9s', '98s', '87s', '76s', '65s', '54s']:
            self.assertIn(hand, self.classifier._FLAT_TIER1,
                          f'{hand} should be in FLAT_TIER1')

    def test_flat_tier1_has_premium_pairs(self):
        """Premium pairs for trapping should be tier 1."""
        for pair in ['KK', 'QQ', 'JJ', 'TT', '99', '88', '77']:
            self.assertIn(pair, self.classifier._FLAT_TIER1,
                          f'{pair} should be in FLAT_TIER1')

    def test_flat_tier2_has_small_pairs(self):
        """Small pairs for set mining are tier 2."""
        for pair in ['44', '33', '22']:
            self.assertIn(pair, self.classifier._FLAT_TIER2,
                          f'{pair} should be in FLAT_TIER2')

    def test_flat_tier3_has_offsuit_broadways(self):
        """Offsuit broadways are tier 3 (flat vs CO/BTN)."""
        for hand in ['AQo', 'AJo', 'KQo', 'KJo', 'QJo']:
            self.assertIn(hand, self.classifier._FLAT_TIER3,
                          f'{hand} should be in FLAT_TIER3')

    def test_flat_hand_tier_strong(self):
        """QJs is tier 1 flat."""
        self.assertEqual(self.classifier._flat_hand_tier('QJs'), 1)

    def test_flat_hand_tier_medium(self):
        """22 is tier 2 flat."""
        self.assertEqual(self.classifier._flat_hand_tier('22'), 2)

    def test_flat_hand_tier_wide(self):
        """KJo is tier 3 flat."""
        self.assertEqual(self.classifier._flat_hand_tier('KJo'), 3)

    def test_flat_hand_tier_trash(self):
        """72o is tier 4 (not in any flat range)."""
        self.assertEqual(self.classifier._flat_hand_tier('72o'), 4)

    # -- 3-Bet range tier membership tests --

    def test_3bet_tier1_always(self):
        """AA and AK always 3-bet."""
        for hand in ['AA', 'AKs', 'AKo']:
            self.assertIn(hand, self.classifier._3BET_TIER1,
                          f'{hand} should be in 3BET_TIER1')

    def test_3bet_tier2_strong_premiums(self):
        """KK, QQ, AQs, AQo are tier 2 3-bet."""
        for hand in ['KK', 'QQ', 'AQs', 'AQo']:
            self.assertIn(hand, self.classifier._3BET_TIER2,
                          f'{hand} should be in 3BET_TIER2')

    def test_3bet_tier3_has_blocker_bluffs(self):
        """A5s-A3s are tier 3 blocker bluffs."""
        for hand in ['A5s', 'A4s', 'A3s']:
            self.assertIn(hand, self.classifier._3BET_TIER3,
                          f'{hand} should be in 3BET_TIER3')

    def test_3bet_tier4_wide_bluffs(self):
        """99, 88 are tier 4 3-bet (vs BTN)."""
        for hand in ['99', '88']:
            self.assertIn(hand, self.classifier._3BET_TIER4,
                          f'{hand} should be in 3BET_TIER4')

    def test_3bet_hand_tier_premium(self):
        """AA is tier 1 3-bet."""
        self.assertEqual(self.classifier._3bet_hand_tier('AA'), 1)

    def test_3bet_hand_tier_trash(self):
        """72o is tier 5 (not in any 3-bet range)."""
        self.assertEqual(self.classifier._3bet_hand_tier('72o'), 5)

    # -- Correct flat evaluations --

    def test_flat_correct_suited_connector_from_btn(self):
        """Flatting 87s from BTN vs CO = correct (tier 1 flat)."""
        self._insert_flat('FB01', hero_cards='8h 7h', hero_pos='BTN', opener_pos='CO')
        self.assertEqual(self._flat3bet_result('FB01'), 1)

    def test_flat_correct_pair_from_hj(self):
        """Flatting QQ from HJ vs EP = correct (tier 1 flat)."""
        self._insert_flat('FB02', hero_cards='Qh Qd', hero_pos='HJ', opener_pos='UTG')
        self.assertEqual(self._flat3bet_result('FB02'), 1)

    def test_flat_correct_small_pair_from_hj(self):
        """Flatting 22 from HJ vs MP = correct (tier 2 flat, HJ tier=2)."""
        self._insert_flat('FB03', hero_cards='2h 2d', hero_pos='HJ', opener_pos='MP')
        self.assertEqual(self._flat3bet_result('FB03'), 1)

    def test_flat_correct_broadways_from_btn(self):
        """Flatting AJo from BTN vs CO = correct (tier 3 flat)."""
        self._insert_flat('FB04', hero_cards='Ah Jd', hero_pos='BTN', opener_pos='CO')
        self.assertEqual(self._flat3bet_result('FB04'), 1)

    # -- Incorrect flat evaluations --

    def test_flat_incorrect_trash_from_utg(self):
        """Flatting 72o from any position = incorrect (not in any range)."""
        self._insert_flat('FB05', hero_cards='7h 2d', hero_pos='HJ', opener_pos='UTG')
        self.assertEqual(self._flat3bet_result('FB05'), 0)

    def test_flat_marginal_small_pair_from_utg(self):
        """Flatting 22 from UTG position vs EP = marginal (tier 2 vs tier 1)."""
        self._insert_flat('FB06', hero_cards='2h 2d', hero_pos='UTG', opener_pos='EP')
        self.assertIsNone(self._flat3bet_result('FB06'))

    def test_flat_incorrect_offsuit_broadway_from_ep(self):
        """Flatting KJo from EP vs UTG = incorrect (tier 3 vs tier 1)."""
        self._insert_flat('FB07', hero_cards='Kh Jd', hero_pos='EP', opener_pos='UTG')
        self.assertEqual(self._flat3bet_result('FB07'), 0)

    # -- Correct 3-bet evaluations --

    def test_3bet_correct_aa_from_any_pos(self):
        """3-betting AA from any position = always correct (tier 1)."""
        self._insert_3bet('FB08', hero_cards='Ah Ad', hero_pos='UTG', opener_pos='EP')
        self.assertEqual(self._flat3bet_result('FB08'), 1)

    def test_3bet_correct_kk_from_mp(self):
        """3-betting KK from MP = correct (tier 2 vs tier 2)."""
        self._insert_3bet('FB09', hero_cards='Kh Kd', hero_pos='MP', opener_pos='UTG')
        self.assertEqual(self._flat3bet_result('FB09'), 1)

    def test_3bet_correct_a5s_bluff_from_co(self):
        """3-betting A5s as bluff from CO = correct (tier 3 vs tier 3)."""
        self._insert_3bet('FB10', hero_cards='Ah 5h', hero_pos='CO', opener_pos='HJ')
        self.assertEqual(self._flat3bet_result('FB10'), 1)

    def test_3bet_correct_99_from_btn(self):
        """3-betting 99 from BTN = correct (tier 4 vs tier 4)."""
        self._insert_3bet('FB11', hero_cards='9h 9d', hero_pos='BTN', opener_pos='CO')
        self.assertEqual(self._flat3bet_result('FB11'), 1)

    # -- Incorrect 3-bet evaluations --

    def test_3bet_incorrect_trash_from_utg(self):
        """3-betting 72o = incorrect (not in any 3-bet range)."""
        self._insert_3bet('FB12', hero_cards='7h 2d', hero_pos='UTG', opener_pos='EP')
        self.assertEqual(self._flat3bet_result('FB12'), 0)

    def test_3bet_marginal_jj_from_mp(self):
        """3-betting JJ from MP vs UTG = marginal (tier 3 vs tier 2)."""
        self._insert_3bet('FB13', hero_cards='Jh Jd', hero_pos='MP', opener_pos='UTG')
        self.assertIsNone(self._flat3bet_result('FB13'))

    def test_3bet_incorrect_weak_from_ep(self):
        """3-betting 88 from EP vs UTG = incorrect (tier 4 vs tier 1, gap > 1)."""
        self._insert_3bet('FB14', hero_cards='8h 8d', hero_pos='EP', opener_pos='UTG')
        self.assertEqual(self._flat3bet_result('FB14'), 0)

    # -- No hero cards --

    def test_flat_no_hero_cards_returns_1(self):
        """Without hero cards, flatting returns 1 (action taken)."""
        _insert_hand(self.repo, 'FB15', position='BTN')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('FB15',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'FB15', 'preflop', 'Villain', 'raise',
                       1.5, 0, 1, 'CO')
        _insert_action(self.repo, 'FB15', 'preflop', 'Hero', 'call',
                       1.5, 1, 2, 'BTN')
        self.assertEqual(self._flat3bet_result('FB15'), 1)

    def test_3bet_no_hero_cards_returns_1(self):
        """Without hero cards, 3-betting returns 1 (action taken)."""
        _insert_hand(self.repo, 'FB16', position='BTN')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('FB16',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'FB16', 'preflop', 'Villain', 'raise',
                       1.5, 0, 1, 'CO')
        _insert_action(self.repo, 'FB16', 'preflop', 'Hero', 'raise',
                       4.5, 1, 2, 'BTN')
        self.assertEqual(self._flat3bet_result('FB16'), 1)


# ── Reaction vs 3-Bet Evaluation Tests (US-044, Lesson 3) ─────────


class TestReactionVs3BetEvaluation(unittest.TestCase):
    """Test reaction vs 3-bet evaluation with range-based classification.

    Based on RegLife 'Ranges de reação vs 3-bet':
    - Strong hands: always continue (call or 4-bet)
    - Trash hands: should fold
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

    def _vs3bet_result(self, hand_id):
        """Get executed_correctly for lesson 3 (Reaction vs 3-Bet)."""
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 3), None)
        return m.executed_correctly if m else None

    def _insert_facing_3bet(self, hand_id, hero_cards='Ah Kd', hero_pos='UTG',
                             threebettor_pos='CO', hero_action='call',
                             hero_amount=4.5):
        """Insert a hand where hero opens and faces a 3-bet."""
        _insert_hand(self.repo, hand_id, position=hero_pos)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        # Hero opens
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, hero_pos)
        # Villain 3-bets
        _insert_action(self.repo, hand_id, 'preflop', 'Villain', 'raise',
                       4.5, 0, 2, threebettor_pos)
        # Hero reacts
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', hero_action,
                       hero_amount, 1, 3, hero_pos)

    # -- Range membership tests --

    def test_vs3bet_continue_has_premium_pairs(self):
        """All premium pairs should always continue vs 3-bet."""
        for hand in ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77']:
            self.assertIn(hand, self.classifier._VS3BET_CONTINUE,
                          f'{hand} should be in VS3BET_CONTINUE')

    def test_vs3bet_continue_has_suited_broadways(self):
        """Strong suited broadways should always continue."""
        for hand in ['AKs', 'AQs', 'AJs', 'ATs', 'KQs', 'KJs', 'KTs', 'QJs']:
            self.assertIn(hand, self.classifier._VS3BET_CONTINUE,
                          f'{hand} should be in VS3BET_CONTINUE')

    def test_vs3bet_continue_has_suited_connectors(self):
        """Suited connectors continue for implied odds."""
        for hand in ['T9s', '98s', '87s', '76s', '65s', '54s']:
            self.assertIn(hand, self.classifier._VS3BET_CONTINUE,
                          f'{hand} should be in VS3BET_CONTINUE')

    def test_vs3bet_4bet_has_premiums(self):
        """AA, KK, QQ, AKs should be in 4-bet range."""
        for hand in ['AA', 'KK', 'QQ', 'AKs', 'AKo']:
            self.assertIn(hand, self.classifier._VS3BET_4BET,
                          f'{hand} should be in VS3BET_4BET')

    def test_vs3bet_marginal_has_small_pairs(self):
        """Small pairs (22-44) are marginal vs 3-bet."""
        for hand in ['44', '33', '22']:
            self.assertIn(hand, self.classifier._VS3BET_MARGINAL,
                          f'{hand} should be in VS3BET_MARGINAL')

    def test_vs3bet_marginal_has_suited_aces(self):
        """Suited aces below ATs are marginal."""
        for hand in ['A9s', 'A8s', 'A7s', 'A6s', 'A5s']:
            self.assertIn(hand, self.classifier._VS3BET_MARGINAL,
                          f'{hand} should be in VS3BET_MARGINAL')

    # -- Correct: call/4-bet with strong hand --

    def test_vs3bet_correct_call_aa(self):
        """Calling 3-bet with AA = correct."""
        self._insert_facing_3bet('V3B01', hero_cards='Ah Ad',
                                  hero_action='call')
        self.assertEqual(self._vs3bet_result('V3B01'), 1)

    def test_vs3bet_correct_call_suited_connector(self):
        """Calling 3-bet with 87s = correct (good implied odds)."""
        self._insert_facing_3bet('V3B02', hero_cards='8h 7h',
                                  hero_action='call')
        self.assertEqual(self._vs3bet_result('V3B02'), 1)

    def test_vs3bet_correct_4bet_kk(self):
        """4-betting with KK = correct."""
        self._insert_facing_3bet('V3B03', hero_cards='Kh Kd',
                                  hero_action='raise', hero_amount=12.0)
        self.assertEqual(self._vs3bet_result('V3B03'), 1)

    def test_vs3bet_correct_call_aqo(self):
        """Calling 3-bet with AQo = correct (in continue range)."""
        self._insert_facing_3bet('V3B04', hero_cards='Ah Qd',
                                  hero_action='call')
        self.assertEqual(self._vs3bet_result('V3B04'), 1)

    # -- Incorrect: fold strong hand --

    def test_vs3bet_incorrect_fold_kk(self):
        """Folding KK to 3-bet = incorrect (always continue)."""
        self._insert_facing_3bet('V3B05', hero_cards='Kh Kd',
                                  hero_action='fold', hero_amount=0)
        self.assertEqual(self._vs3bet_result('V3B05'), 0)

    def test_vs3bet_incorrect_fold_t9s(self):
        """Folding T9s to 3-bet = incorrect (should continue for implied odds)."""
        self._insert_facing_3bet('V3B06', hero_cards='Th 9h',
                                  hero_action='fold', hero_amount=0)
        self.assertEqual(self._vs3bet_result('V3B06'), 0)

    def test_vs3bet_incorrect_fold_aks(self):
        """Folding AKs to 3-bet = incorrect."""
        self._insert_facing_3bet('V3B07', hero_cards='Ah Kh',
                                  hero_action='fold', hero_amount=0)
        self.assertEqual(self._vs3bet_result('V3B07'), 0)

    # -- Correct: fold trash --

    def test_vs3bet_correct_fold_trash(self):
        """Folding 72o to 3-bet = correct (trash hand)."""
        self._insert_facing_3bet('V3B08', hero_cards='7h 2d',
                                  hero_action='fold', hero_amount=0)
        self.assertEqual(self._vs3bet_result('V3B08'), 1)

    def test_vs3bet_correct_fold_weak_offsuit(self):
        """Folding T8o to 3-bet = correct (not in any range)."""
        self._insert_facing_3bet('V3B09', hero_cards='Th 8d',
                                  hero_action='fold', hero_amount=0)
        self.assertEqual(self._vs3bet_result('V3B09'), 1)

    # -- Incorrect: call with trash --

    def test_vs3bet_incorrect_call_trash(self):
        """Calling 3-bet with 72o = incorrect (should fold)."""
        self._insert_facing_3bet('V3B10', hero_cards='7h 2d',
                                  hero_action='call')
        self.assertEqual(self._vs3bet_result('V3B10'), 0)

    # -- Marginal hands --

    def test_vs3bet_marginal_fold_small_pair(self):
        """Folding 33 to 3-bet = marginal (context-dependent)."""
        self._insert_facing_3bet('V3B11', hero_cards='3h 3d',
                                  hero_action='fold', hero_amount=0)
        self.assertIsNone(self._vs3bet_result('V3B11'))

    def test_vs3bet_marginal_call_small_pair(self):
        """Calling 3-bet with 33 = marginal (context-dependent)."""
        self._insert_facing_3bet('V3B12', hero_cards='3h 3d',
                                  hero_action='call')
        self.assertIsNone(self._vs3bet_result('V3B12'))

    def test_vs3bet_marginal_suited_ace(self):
        """A6s vs 3-bet is marginal (in marginal set)."""
        self._insert_facing_3bet('V3B13', hero_cards='Ah 6h',
                                  hero_action='call')
        self.assertIsNone(self._vs3bet_result('V3B13'))

    # -- No hero cards --

    def test_vs3bet_no_cards_returns_none(self):
        """Without hero cards, reaction vs 3-bet = None (can't evaluate)."""
        _insert_hand(self.repo, 'V3B14', position='UTG')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('V3B14',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'V3B14', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'UTG')
        _insert_action(self.repo, 'V3B14', 'preflop', 'Villain', 'raise',
                       4.5, 0, 2, 'CO')
        _insert_action(self.repo, 'V3B14', 'preflop', 'Hero', 'call',
                       4.5, 1, 3, 'UTG')
        self.assertIsNone(self._vs3bet_result('V3B14'))


# ── Squeeze Evaluation Tests (US-044, Lesson 5) ─────────────────────


class TestSqueezeEvaluation(unittest.TestCase):
    """Test squeeze evaluation with position-based range validation.

    Based on RegLife 'SQUEEZE':
    - Strong hands: in squeeze range for position (linear top range)
    - Trash hands: too weak to squeeze
    - Marginal hands: between tiers
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

    def _squeeze_result(self, hand_id):
        """Get executed_correctly for lesson 5 (Squeeze)."""
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 5), None)
        return m.executed_correctly if m else None

    def _insert_squeeze(self, hand_id, hero_cards='Ah Kd', hero_pos='BTN',
                        opener_pos='HJ', caller_pos='CO',
                        hero_amount=6.0, opener_amount=1.5, caller_amount=1.5):
        """Insert a hand where hero squeezes after open + call."""
        _insert_hand(self.repo, hand_id, position=hero_pos)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        # Villain opens
        _insert_action(self.repo, hand_id, 'preflop', 'Opener', 'raise',
                       opener_amount, 0, 1, opener_pos)
        # Another villain calls
        _insert_action(self.repo, hand_id, 'preflop', 'Caller', 'call',
                       caller_amount, 0, 2, caller_pos)
        # Hero squeezes (3-bet after a call)
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       hero_amount, 1, 3, hero_pos)

    # -- Squeeze tier membership tests --

    def test_squeeze_tier1_has_premium_pairs(self):
        """AA-88 should be in squeeze tier 1."""
        for pair in ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88']:
            self.assertIn(pair, self.classifier._SQUEEZE_TIER1,
                          f'{pair} should be in SQUEEZE_TIER1')

    def test_squeeze_tier1_has_strong_broadways(self):
        """Strong broadways should be in squeeze tier 1."""
        for hand in ['AKs', 'AQs', 'AJs', 'ATs', 'KQs', 'KJs', 'KTs', 'AKo', 'AQo']:
            self.assertIn(hand, self.classifier._SQUEEZE_TIER1,
                          f'{hand} should be in SQUEEZE_TIER1')

    def test_squeeze_tier2_has_small_pairs(self):
        """Small pairs for wider squeeze from BTN."""
        for pair in ['77', '66', '55', '44', '33', '22']:
            self.assertIn(pair, self.classifier._SQUEEZE_TIER2,
                          f'{pair} should be in SQUEEZE_TIER2')

    def test_squeeze_tier2_has_suited_connectors(self):
        """Suited connectors for IP squeeze."""
        for hand in ['T9s', '98s', '87s', '76s', '65s', '54s']:
            self.assertIn(hand, self.classifier._SQUEEZE_TIER2,
                          f'{hand} should be in SQUEEZE_TIER2')

    def test_squeeze_hand_tier_premium(self):
        """AA is tier 1 squeeze."""
        self.assertEqual(self.classifier._squeeze_hand_tier('AA'), 1)

    def test_squeeze_hand_tier_wide(self):
        """77 is tier 2 squeeze."""
        self.assertEqual(self.classifier._squeeze_hand_tier('77'), 2)

    def test_squeeze_hand_tier_trash(self):
        """72o is tier 3 (not in any squeeze range)."""
        self.assertEqual(self.classifier._squeeze_hand_tier('72o'), 3)

    # -- Correct squeeze evaluations --

    def test_squeeze_correct_aa_from_hj(self):
        """Squeezing AA from HJ = correct (tier 1, HJ tier=1)."""
        self._insert_squeeze('SQ01', hero_cards='Ah Ad', hero_pos='HJ',
                             opener_pos='UTG', caller_pos='MP')
        self.assertEqual(self._squeeze_result('SQ01'), 1)

    def test_squeeze_correct_aks_from_hj(self):
        """Squeezing AKs from HJ = correct (tier 1)."""
        self._insert_squeeze('SQ02', hero_cards='Ah Kh', hero_pos='HJ',
                             opener_pos='UTG', caller_pos='MP')
        self.assertEqual(self._squeeze_result('SQ02'), 1)

    def test_squeeze_correct_77_from_btn(self):
        """Squeezing 77 from BTN = correct (tier 2, BTN tier=2)."""
        self._insert_squeeze('SQ03', hero_cards='7h 7d', hero_pos='BTN',
                             opener_pos='HJ', caller_pos='CO')
        self.assertEqual(self._squeeze_result('SQ03'), 1)

    def test_squeeze_correct_t9s_from_btn(self):
        """Squeezing T9s from BTN = correct (tier 2, BTN tier=2)."""
        self._insert_squeeze('SQ04', hero_cards='Th 9h', hero_pos='BTN',
                             opener_pos='HJ', caller_pos='CO')
        self.assertEqual(self._squeeze_result('SQ04'), 1)

    def test_squeeze_correct_aqo_from_sb(self):
        """Squeezing AQo from SB = correct (tier 1, SB tier=2)."""
        self._insert_squeeze('SQ05', hero_cards='Ah Qd', hero_pos='SB',
                             opener_pos='CO', caller_pos='BTN')
        self.assertEqual(self._squeeze_result('SQ05'), 1)

    # -- Incorrect squeeze evaluations --

    def test_squeeze_incorrect_trash_from_hj(self):
        """Squeezing 72o from HJ = incorrect (tier 3, way outside range)."""
        self._insert_squeeze('SQ06', hero_cards='7h 2d', hero_pos='HJ',
                             opener_pos='UTG', caller_pos='MP')
        self.assertEqual(self._squeeze_result('SQ06'), 0)

    def test_squeeze_incorrect_weak_from_ep(self):
        """Squeezing 65s from UTG (facing open+call) = incorrect (tier 2 vs tier 1)."""
        # 65s is tier 2, UTG pos_tier is 1 → gap = 1 → marginal, not incorrect
        # Actually need something with bigger gap
        self._insert_squeeze('SQ07', hero_cards='7h 2d', hero_pos='UTG',
                             opener_pos='EP', caller_pos='MP')
        self.assertEqual(self._squeeze_result('SQ07'), 0)

    # -- Marginal squeeze evaluations --

    def test_squeeze_marginal_77_from_hj(self):
        """Squeezing 77 from HJ = marginal (tier 2 vs HJ tier=1)."""
        self._insert_squeeze('SQ08', hero_cards='7h 7d', hero_pos='HJ',
                             opener_pos='UTG', caller_pos='MP')
        self.assertIsNone(self._squeeze_result('SQ08'))

    def test_squeeze_marginal_suited_connector_from_hj(self):
        """Squeezing 87s from HJ = marginal (tier 2, one tier wide)."""
        self._insert_squeeze('SQ09', hero_cards='8h 7h', hero_pos='HJ',
                             opener_pos='UTG', caller_pos='MP')
        self.assertIsNone(self._squeeze_result('SQ09'))

    # -- No hero cards --

    def test_squeeze_no_cards_returns_1(self):
        """Without hero cards, squeeze returns 1 (action taken)."""
        _insert_hand(self.repo, 'SQ10', position='BTN')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('SQ10',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'SQ10', 'preflop', 'Opener', 'raise',
                       1.5, 0, 1, 'HJ')
        _insert_action(self.repo, 'SQ10', 'preflop', 'Caller', 'call',
                       1.5, 0, 2, 'CO')
        _insert_action(self.repo, 'SQ10', 'preflop', 'Hero', 'raise',
                       6.0, 1, 3, 'BTN')
        self.assertEqual(self._squeeze_result('SQ10'), 1)

    # -- Position tier mapping tests --

    def test_squeeze_pos_tier_ep_is_1(self):
        """EP positions have squeeze tier 1 (tightest)."""
        for pos in ['UTG', 'EP', 'LJ', 'MP', 'HJ']:
            self.assertEqual(self.classifier._SQUEEZE_POS_MAX_TIER.get(pos), 1,
                             f'{pos} should have squeeze tier 1')

    def test_squeeze_pos_tier_late_is_2(self):
        """Late positions have squeeze tier 2 (wider)."""
        for pos in ['CO', 'BTN', 'SB', 'BB']:
            self.assertEqual(self.classifier._SQUEEZE_POS_MAX_TIER.get(pos), 2,
                             f'{pos} should have squeeze tier 2')


class TestOpenShoveEvaluation(unittest.TestCase):
    """Test open shove evaluation with position-based range validation.

    Based on RegLife 'Ranges de Open Shove cEV 10BB':
    - Tier 1: all pairs + all suited aces + strong broadways (shove from any pos)
    - Tier 2: medium kings, suited connectors (shove from MP+)
    - Tier 3: weak kings, more connectors (shove from CO+)
    - Tier 4: speculative hands (shove from BTN/SB only)
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

    def _shove_result(self, hand_id):
        """Get executed_correctly for lesson 4 (Open Shove cEV 10BB)."""
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 4), None)
        return m.executed_correctly if m else None

    def _insert_shove(self, hand_id, hero_cards='Ah Ad', hero_pos='BTN',
                      hero_stack=4.0, blinds_bb=0.50):
        """Insert a hand where hero open shoves preflop."""
        _insert_hand(self.repo, hand_id, position=hero_pos,
                     hero_stack=hero_stack, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'all-in',
                       hero_stack, 1, 1, hero_pos)

    # -- Tier membership tests --

    def test_open_shove_tier1_has_all_pairs(self):
        """All pairs 22+ should be in open shove tier 1."""
        for pair in ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77',
                     '66', '55', '44', '33', '22']:
            self.assertIn(pair, self.classifier._OPEN_SHOVE_TIER1,
                          f'{pair} should be in OPEN_SHOVE_TIER1')

    def test_open_shove_tier1_has_all_suited_aces(self):
        """All suited aces should be in tier 1."""
        for hand in ['AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s',
                     'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s']:
            self.assertIn(hand, self.classifier._OPEN_SHOVE_TIER1,
                          f'{hand} should be in OPEN_SHOVE_TIER1')

    def test_open_shove_tier1_has_strong_offsuit(self):
        """Strong offsuit hands (AKo, AQo, AJo, ATo) in tier 1."""
        for hand in ['AKo', 'AQo', 'AJo', 'ATo']:
            self.assertIn(hand, self.classifier._OPEN_SHOVE_TIER1,
                          f'{hand} should be in OPEN_SHOVE_TIER1')

    def test_open_shove_tier2_has_medium_kings(self):
        """Medium suited kings (K9s-K5s) in tier 2."""
        for hand in ['K9s', 'K8s', 'K7s', 'K6s', 'K5s']:
            self.assertIn(hand, self.classifier._OPEN_SHOVE_TIER2,
                          f'{hand} should be in OPEN_SHOVE_TIER2')

    def test_open_shove_tier2_has_suited_broadways(self):
        """Suited broadways (QJs, QTs, JTs, T9s) in tier 2."""
        for hand in ['QJs', 'QTs', 'JTs', 'T9s', '98s', '87s']:
            self.assertIn(hand, self.classifier._OPEN_SHOVE_TIER2,
                          f'{hand} should be in OPEN_SHOVE_TIER2')

    def test_open_shove_tier3_has_weak_kings(self):
        """Weak suited kings (K4s-K2s) in tier 3."""
        for hand in ['K4s', 'K3s', 'K2s']:
            self.assertIn(hand, self.classifier._OPEN_SHOVE_TIER3,
                          f'{hand} should be in OPEN_SHOVE_TIER3')

    def test_open_shove_tier4_has_speculative(self):
        """Speculative hands only valid from BTN/SB in tier 4."""
        for hand in ['Q7s', 'Q6s', 'T9o', '98o', 'J8o']:
            self.assertIn(hand, self.classifier._OPEN_SHOVE_TIER4,
                          f'{hand} should be in OPEN_SHOVE_TIER4')

    # -- Hand tier classification tests --

    def test_open_shove_hand_tier_premium_pair(self):
        """AA is tier 1."""
        self.assertEqual(self.classifier._open_shove_hand_tier('AA'), 1)

    def test_open_shove_hand_tier_small_pair(self):
        """22 is tier 1 (all pairs in tier 1)."""
        self.assertEqual(self.classifier._open_shove_hand_tier('22'), 1)

    def test_open_shove_hand_tier_suited_ace(self):
        """A5s is tier 1."""
        self.assertEqual(self.classifier._open_shove_hand_tier('A5s'), 1)

    def test_open_shove_hand_tier_medium_king(self):
        """K8s is tier 2."""
        self.assertEqual(self.classifier._open_shove_hand_tier('K8s'), 2)

    def test_open_shove_hand_tier_weak_king(self):
        """K3s is tier 3."""
        self.assertEqual(self.classifier._open_shove_hand_tier('K3s'), 3)

    def test_open_shove_hand_tier_speculative(self):
        """Q7s is tier 4."""
        self.assertEqual(self.classifier._open_shove_hand_tier('Q7s'), 4)

    def test_open_shove_hand_tier_trash(self):
        """72o is tier 5 (not in any open shove range)."""
        self.assertEqual(self.classifier._open_shove_hand_tier('72o'), 5)

    # -- Position tier mapping tests --

    def test_open_shove_pos_tier_utg_is_1(self):
        """UTG/EP/LJ positions have tier 1 (tightest)."""
        for pos in ['UTG', 'EP', 'UTG+1', 'UTG+2', 'LJ']:
            self.assertEqual(self.classifier._OPEN_SHOVE_POS_MAX_TIER.get(pos), 1,
                             f'{pos} should have open shove tier 1')

    def test_open_shove_pos_tier_mp_hj_is_2(self):
        """MP/HJ have tier 2."""
        for pos in ['MP', 'HJ']:
            self.assertEqual(self.classifier._OPEN_SHOVE_POS_MAX_TIER.get(pos), 2,
                             f'{pos} should have open shove tier 2')

    def test_open_shove_pos_tier_co_is_3(self):
        """CO has tier 3."""
        self.assertEqual(self.classifier._OPEN_SHOVE_POS_MAX_TIER.get('CO'), 3)

    def test_open_shove_pos_tier_btn_sb_is_4(self):
        """BTN/SB have tier 4 (widest)."""
        for pos in ['BTN', 'SB']:
            self.assertEqual(self.classifier._OPEN_SHOVE_POS_MAX_TIER.get(pos), 4,
                             f'{pos} should have open shove tier 4')

    # -- Correct shove evaluations --

    def test_open_shove_correct_aa_utg_8bb(self):
        """Shoving AA from UTG at 8BB = correct (tier 1 ≤ pos_tier 1)."""
        self._insert_shove('OS01', hero_cards='Ah Ad', hero_pos='UTG',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS01'), 1)

    def test_open_shove_correct_22_utg_8bb(self):
        """Shoving 22 from UTG at 8BB = correct (all pairs in tier 1)."""
        self._insert_shove('OS02', hero_cards='2h 2d', hero_pos='UTG',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS02'), 1)

    def test_open_shove_correct_a5s_mp_9bb(self):
        """Shoving A5s from MP at 9BB = correct (tier 1 ≤ pos_tier 2)."""
        self._insert_shove('OS03', hero_cards='Ah 5h', hero_pos='MP',
                           hero_stack=4.5, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS03'), 1)

    def test_open_shove_correct_k9s_mp_8bb(self):
        """Shoving K9s from MP at 8BB = correct (tier 2 ≤ pos_tier 2)."""
        self._insert_shove('OS04', hero_cards='Kh 9h', hero_pos='MP',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS04'), 1)

    def test_open_shove_correct_k3s_co_7bb(self):
        """Shoving K3s from CO at 7BB = correct (tier 3 ≤ pos_tier 3)."""
        self._insert_shove('OS05', hero_cards='Kh 3h', hero_pos='CO',
                           hero_stack=3.5, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS05'), 1)

    def test_open_shove_correct_q7s_btn_8bb(self):
        """Shoving Q7s from BTN at 8BB = correct (tier 4 ≤ pos_tier 4)."""
        self._insert_shove('OS06', hero_cards='Qh 7h', hero_pos='BTN',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS06'), 1)

    def test_open_shove_correct_t9o_sb_9bb(self):
        """Shoving T9o from SB at 9BB = correct (tier 4 ≤ pos_tier 4)."""
        self._insert_shove('OS07', hero_cards='Th 9d', hero_pos='SB',
                           hero_stack=4.5, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS07'), 1)

    # -- Incorrect shove evaluations (gap > 1 tier) --

    def test_open_shove_incorrect_72o_utg(self):
        """Shoving 72o from UTG = incorrect (tier 5, gap > 1 from pos_tier 1)."""
        self._insert_shove('OS08', hero_cards='7h 2d', hero_pos='UTG',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS08'), 0)

    def test_open_shove_incorrect_k3s_utg(self):
        """Shoving K3s from UTG = incorrect (tier 3 vs pos_tier 1, gap = 2)."""
        self._insert_shove('OS09', hero_cards='Kh 3h', hero_pos='UTG',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS09'), 0)

    def test_open_shove_incorrect_q7s_mp(self):
        """Shoving Q7s from MP = incorrect (tier 4 vs pos_tier 2, gap = 2)."""
        self._insert_shove('OS10', hero_cards='Qh 7h', hero_pos='MP',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS10'), 0)

    def test_open_shove_incorrect_j8s_utg(self):
        """Shoving J8s from UTG = incorrect (tier 3 vs pos_tier 1, gap = 2)."""
        self._insert_shove('OS11', hero_cards='Jh 8h', hero_pos='UTG',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertEqual(self._shove_result('OS11'), 0)

    # -- Marginal shove evaluations (gap = 1 tier) --

    def test_open_shove_marginal_k9s_utg(self):
        """Shoving K9s from UTG = marginal (tier 2 = pos_tier 1 + 1)."""
        self._insert_shove('OS12', hero_cards='Kh 9h', hero_pos='UTG',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertIsNone(self._shove_result('OS12'))

    def test_open_shove_marginal_q9s_utg(self):
        """Shoving Q9s from UTG = marginal (tier 2 = pos_tier 1 + 1)."""
        self._insert_shove('OS13', hero_cards='Qh 9h', hero_pos='UTG',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertIsNone(self._shove_result('OS13'))

    def test_open_shove_marginal_k3s_mp(self):
        """Shoving K3s from MP = marginal (tier 3 = pos_tier 2 + 1)."""
        self._insert_shove('OS14', hero_cards='Kh 3h', hero_pos='MP',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertIsNone(self._shove_result('OS14'))

    def test_open_shove_marginal_q7s_co(self):
        """Shoving Q7s from CO = marginal (tier 4 = pos_tier 3 + 1)."""
        self._insert_shove('OS15', hero_cards='Qh 7h', hero_pos='CO',
                           hero_stack=4.0, blinds_bb=0.50)
        self.assertIsNone(self._shove_result('OS15'))

    # -- Stack depth tests --

    def test_open_shove_stack_10_to_12bb_is_marginal(self):
        """Open shove at 11BB is detected but evaluation is marginal (stack too deep)."""
        self._insert_shove('OS16', hero_cards='Ah Ad', hero_pos='BTN',
                           hero_stack=5.5, blinds_bb=0.50)  # 11BB
        self.assertIsNone(self._shove_result('OS16'))

    def test_open_shove_not_detected_above_12bb(self):
        """Open shove at 15BB is not detected as lesson 4 (too deep)."""
        _insert_hand(self.repo, 'OS17', position='BTN',
                     hero_stack=7.5, blinds_bb=0.50)  # 15BB
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", ('Ah Ad', 'OS17'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'OS17', 'preflop', 'Hero', 'all-in',
                       7.5, 1, 1, 'BTN')
        matches = self._classify('OS17')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(4, ids)

    def test_open_shove_no_cards_returns_1(self):
        """Without hero cards, open shove returns 1 (action taken, assume correct)."""
        _insert_hand(self.repo, 'OS18', position='BTN',
                     hero_stack=4.0, blinds_bb=0.50)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('OS18',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'OS18', 'preflop', 'Hero', 'all-in',
                       4.0, 1, 1, 'BTN')
        self.assertEqual(self._shove_result('OS18'), 1)

    def test_open_shove_exact_10bb_is_evaluated(self):
        """Stack at exactly 10BB (not marginal) uses hand range evaluation."""
        self._insert_shove('OS19', hero_cards='Ah Ad', hero_pos='BTN',
                           hero_stack=5.0, blinds_bb=0.50)  # exactly 10BB
        self.assertEqual(self._shove_result('OS19'), 1)


class TestBountyEvaluation(unittest.TestCase):
    """Test bounty tournament range evaluation for lessons 24 and 25.

    Based on RegLife 'Introdução aos Torneios Bounty' and
    'Torneios Bounty - Ranges Práticos' PDFs.
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        # Set up a bounty tournament
        self.repo.insert_tournament({
            'tournament_id': 'BT01',
            'platform': 'GGPoker',
            'name': 'Bounty Hunter',
            'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 5,
            'total_buy_in': 16, 'is_bounty': True,
        })

    def tearDown(self):
        self.conn.close()

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _bounty_result(self, hand_id, lesson_id):
        """Get executed_correctly for a given bounty lesson."""
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == lesson_id), None)
        return m.executed_correctly if m else None

    def _insert_bounty_hand(self, hand_id, hero_cards='Ah Kd', hero_pos='BTN',
                             action='raise', hero_folded=False):
        """Insert a bounty tournament hand with hero action."""
        _insert_hand(self.repo, hand_id, position=hero_pos,
                     game_type='tournament', tournament_id='BT01')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        if hero_folded:
            _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                           300, 0, 1, 'UTG')
            _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'fold',
                           0, 1, 2, hero_pos)
        else:
            _insert_action(self.repo, hand_id, 'preflop', 'Hero', action,
                           300, 1, 1, hero_pos)

    # -- Bounty tier membership tests --

    def test_bounty_tier1_has_all_pairs(self):
        """All pairs 22+ in bounty tier 1."""
        for pair in ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77',
                     '66', '55', '44', '33', '22']:
            self.assertIn(pair, self.classifier._BOUNTY_TIER1,
                          f'{pair} should be in BOUNTY_TIER1')

    def test_bounty_tier1_has_all_suited_aces(self):
        """All suited aces in bounty tier 1."""
        for hand in ['AKs', 'AQs', 'AJs', 'ATs', 'A5s', 'A2s']:
            self.assertIn(hand, self.classifier._BOUNTY_TIER1,
                          f'{hand} should be in BOUNTY_TIER1')

    def test_bounty_tier1_has_suited_connectors(self):
        """Strong suited connectors in bounty tier 1."""
        for hand in ['T9s', 'T8s', '98s', '87s', '76s']:
            self.assertIn(hand, self.classifier._BOUNTY_TIER1,
                          f'{hand} should be in BOUNTY_TIER1')

    def test_bounty_tier2_has_medium_kings(self):
        """Medium suited kings in bounty tier 2."""
        for hand in ['K7s', 'K6s', 'K5s']:
            self.assertIn(hand, self.classifier._BOUNTY_TIER2,
                          f'{hand} should be in BOUNTY_TIER2')

    def test_bounty_tier2_has_medium_offsuit(self):
        """Medium offsuit hands in bounty tier 2."""
        for hand in ['T9o', '98o', '87o', 'A6o', 'K9o']:
            self.assertIn(hand, self.classifier._BOUNTY_TIER2,
                          f'{hand} should be in BOUNTY_TIER2')

    # -- Bounty hand tier helper tests --

    def test_bounty_hand_tier_premium_pair(self):
        """AA is bounty tier 1."""
        self.assertEqual(self.classifier._bounty_hand_tier('AA'), 1)

    def test_bounty_hand_tier_suited_connector(self):
        """T9s is bounty tier 1."""
        self.assertEqual(self.classifier._bounty_hand_tier('T9s'), 1)

    def test_bounty_hand_tier_medium_king(self):
        """K7s is bounty tier 2."""
        self.assertEqual(self.classifier._bounty_hand_tier('K7s'), 2)

    def test_bounty_hand_tier_offsuit_medium(self):
        """T9o is bounty tier 2."""
        self.assertEqual(self.classifier._bounty_hand_tier('T9o'), 2)

    def test_bounty_hand_tier_trash(self):
        """72o is bounty tier 3 (not in any bounty range)."""
        self.assertEqual(self.classifier._bounty_hand_tier('72o'), 3)

    # -- Lesson 25: Bounty Ranges Práticos --

    def test_bounty_ranges_correct_aa(self):
        """AA in bounty tournament = correct (tier 1)."""
        self._insert_bounty_hand('BT_R01', hero_cards='Ah Ad')
        self.assertEqual(self._bounty_result('BT_R01', 25), 1)

    def test_bounty_ranges_correct_kk(self):
        """KK in bounty tournament = correct (tier 1)."""
        self._insert_bounty_hand('BT_R02', hero_cards='Kh Kd')
        self.assertEqual(self._bounty_result('BT_R02', 25), 1)

    def test_bounty_ranges_correct_t9s(self):
        """T9s in bounty tier 1 = correct."""
        self._insert_bounty_hand('BT_R03', hero_cards='Th 9h')
        self.assertEqual(self._bounty_result('BT_R03', 25), 1)

    def test_bounty_ranges_correct_aks(self):
        """AKs in bounty tier 1 = correct."""
        self._insert_bounty_hand('BT_R04', hero_cards='Ah Kh')
        self.assertEqual(self._bounty_result('BT_R04', 25), 1)

    def test_bounty_ranges_marginal_k7s(self):
        """K7s in bounty tier 2 = marginal (None)."""
        self._insert_bounty_hand('BT_R05', hero_cards='Kh 7h')
        self.assertIsNone(self._bounty_result('BT_R05', 25))

    def test_bounty_ranges_marginal_a6o(self):
        """A6o in bounty tier 2 = marginal (None)."""
        self._insert_bounty_hand('BT_R06', hero_cards='Ah 6d')
        self.assertIsNone(self._bounty_result('BT_R06', 25))

    def test_bounty_ranges_marginal_t9o(self):
        """T9o in bounty tier 2 = marginal (None)."""
        self._insert_bounty_hand('BT_R07', hero_cards='Th 9d')
        self.assertIsNone(self._bounty_result('BT_R07', 25))

    def test_bounty_ranges_incorrect_72o(self):
        """72o = incorrect (too weak even with bounty overlay)."""
        self._insert_bounty_hand('BT_R08', hero_cards='7h 2d')
        self.assertEqual(self._bounty_result('BT_R08', 25), 0)

    def test_bounty_ranges_incorrect_32o(self):
        """32o = incorrect (trash hand, not in any bounty tier)."""
        self._insert_bounty_hand('BT_R09', hero_cards='3h 2d')
        self.assertEqual(self._bounty_result('BT_R09', 25), 0)

    def test_bounty_ranges_no_cards_returns_none(self):
        """Without hero cards, bounty ranges returns None."""
        _insert_hand(self.repo, 'BT_R10', position='BTN',
                     game_type='tournament', tournament_id='BT01')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('BT_R10',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BT_R10', 'preflop', 'Hero', 'raise',
                       300, 1, 1, 'BTN')
        self.assertIsNone(self._bounty_result('BT_R10', 25))

    # -- Lesson 24: Intro Torneios Bounty --

    def test_bounty_intro_fold_aa_is_incorrect(self):
        """Folding AA in a bounty spot = incorrect (clear mistake)."""
        self._insert_bounty_hand('BT_I01', hero_cards='Ah Ad', hero_folded=True)
        self.assertEqual(self._bounty_result('BT_I01', 24), 0)

    def test_bounty_intro_fold_kk_is_incorrect(self):
        """Folding KK in a bounty spot = incorrect."""
        self._insert_bounty_hand('BT_I02', hero_cards='Kh Kd', hero_folded=True)
        self.assertEqual(self._bounty_result('BT_I02', 24), 0)

    def test_bounty_intro_fold_aks_is_incorrect(self):
        """Folding AKs in a bounty spot = incorrect (premium hand)."""
        self._insert_bounty_hand('BT_I03', hero_cards='Ah Kh', hero_folded=True)
        self.assertEqual(self._bounty_result('BT_I03', 24), 0)

    def test_bounty_intro_medium_hand_is_none(self):
        """Playing 77 in a bounty tournament = contextual (None)."""
        self._insert_bounty_hand('BT_I04', hero_cards='7h 7d')
        self.assertIsNone(self._bounty_result('BT_I04', 24))

    def test_bounty_intro_not_folding_aa_is_none(self):
        """Playing (not folding) AA in bounty = None (not a clear mistake)."""
        self._insert_bounty_hand('BT_I05', hero_cards='Ah Ad')
        self.assertIsNone(self._bounty_result('BT_I05', 24))

    def test_bounty_intro_no_cards_returns_none(self):
        """Without hero cards, bounty intro returns None."""
        _insert_hand(self.repo, 'BT_I06', position='BTN',
                     game_type='tournament', tournament_id='BT01')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('BT_I06',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BT_I06', 'preflop', 'Hero', 'raise',
                       300, 1, 1, 'BTN')
        self.assertIsNone(self._bounty_result('BT_I06', 24))

    def test_bounty_intro_fold_trash_is_none(self):
        """Folding 72o in a bounty pot = None (folding trash is fine)."""
        self._insert_bounty_hand('BT_I07', hero_cards='7h 2d', hero_folded=True)
        self.assertIsNone(self._bounty_result('BT_I07', 24))

    # -- Both lessons detected --

    def test_bounty_both_lessons_detected(self):
        """Both lessons 24 and 25 are detected for bounty tournament hands."""
        self._insert_bounty_hand('BT_D01', hero_cards='Ah Ad')
        matches = self._classify('BT_D01')
        ids = [m.lesson_id for m in matches]
        self.assertIn(24, ids)
        self.assertIn(25, ids)

    def test_bounty_lesson_24_detected_without_preflop_action(self):
        """Lesson 24 is detected for all bounty tournament hands (detection only)."""
        _insert_hand(self.repo, 'BT_D02', position='BTN',
                     game_type='tournament', tournament_id='BT01')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", ('Ah Kd', 'BT_D02'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BT_D02', 'preflop', 'Hero', 'raise',
                       300, 1, 1, 'BTN')
        matches = self._classify('BT_D02')
        ids = [m.lesson_id for m in matches]
        self.assertIn(24, ids)


# ── Board Analysis Helpers Tests (US-046) ────────────────────────────


class TestBoardAnalysisHelpers(unittest.TestCase):
    """Test _parse_cards, _board_texture, _hand_connects_board."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    # -- _parse_cards --

    def test_parse_cards_basic(self):
        result = LessonClassifier._parse_cards('Ah Kd 2c')
        self.assertEqual(result, [('A', 'h'), ('K', 'd'), ('2', 'c')])

    def test_parse_cards_empty(self):
        self.assertEqual(LessonClassifier._parse_cards(''), [])
        self.assertEqual(LessonClassifier._parse_cards(None), [])

    def test_parse_cards_two_cards(self):
        result = LessonClassifier._parse_cards('Ts Jh')
        self.assertEqual(result, [('T', 's'), ('J', 'h')])

    # -- _board_texture --

    def test_texture_dry_rainbow_disconnected(self):
        """Rainbow + disconnected = dry (e.g. K72 rainbow)."""
        self.assertEqual(LessonClassifier._board_texture('Kh 7d 2c'), 'dry')

    def test_texture_dry_rainbow_spread(self):
        """A82 rainbow = dry."""
        self.assertEqual(LessonClassifier._board_texture('Ah 8d 2c'), 'dry')

    def test_texture_wet_suited_connected(self):
        """Two suited + connected = wet (e.g. 9h 8h 7c)."""
        self.assertEqual(LessonClassifier._board_texture('9h 8h 7c'), 'wet')

    def test_texture_wet_monotone(self):
        """Monotone = wet (all same suit counts as 2+ suited + connected)."""
        result = LessonClassifier._board_texture('Ah Kh Qh')
        # Monotone: 3 same suit (≥2), span=2 (A=12, K=11, Q=10) ≤ 4
        self.assertEqual(result, 'wet')

    def test_texture_neutral_suited_only(self):
        """Two suited but disconnected = neutral."""
        self.assertEqual(LessonClassifier._board_texture('Ah 7h 2c'), 'neutral')

    def test_texture_neutral_connected_only(self):
        """Connected but rainbow = neutral."""
        self.assertEqual(LessonClassifier._board_texture('9h 8d 7c'), 'neutral')

    def test_texture_incomplete_board(self):
        """Less than 3 cards = neutral fallback."""
        self.assertEqual(LessonClassifier._board_texture('Ah Kd'), 'neutral')

    # -- _hand_connects_board --

    def test_connects_set(self):
        """Pocket pair hitting the board = strong (set)."""
        result = LessonClassifier._hand_connects_board('Kh Kd', 'Ks 7d 2c')
        self.assertEqual(result, 'strong')

    def test_connects_overpair(self):
        """Pocket pair above all board cards = strong."""
        result = LessonClassifier._hand_connects_board('Ah Ad', '9h 7d 2c')
        self.assertEqual(result, 'strong')

    def test_connects_underpair(self):
        """Pocket pair below board top card = medium."""
        result = LessonClassifier._hand_connects_board('5h 5d', 'Ah 7d 2c')
        self.assertEqual(result, 'medium')

    def test_connects_two_pair(self):
        """Both hero cards hit board = strong."""
        result = LessonClassifier._hand_connects_board('Ah 7d', 'As 7c 2h')
        self.assertEqual(result, 'strong')

    def test_connects_top_pair_good_kicker(self):
        """Top pair + J+ kicker = strong."""
        result = LessonClassifier._hand_connects_board('Ah Kd', 'As 7c 2h')
        self.assertEqual(result, 'strong')

    def test_connects_top_pair_weak_kicker(self):
        """Top pair + weak kicker = medium."""
        result = LessonClassifier._hand_connects_board('Ah 3d', 'As 7c 2h')
        self.assertEqual(result, 'medium')

    def test_connects_middle_pair(self):
        """Hitting middle card = medium."""
        result = LessonClassifier._hand_connects_board('7h 3d', 'Ah 7c 2s')
        self.assertEqual(result, 'medium')

    def test_connects_flush_draw(self):
        """4 cards same suit = draw."""
        result = LessonClassifier._hand_connects_board('Qh 9h', 'Ah 7h 2c')
        self.assertEqual(result, 'draw')

    def test_connects_oesd(self):
        """Open-ended straight draw = draw."""
        result = LessonClassifier._hand_connects_board('Jh Td', '9c 8h 2s')
        self.assertEqual(result, 'draw')

    def test_connects_weak(self):
        """No pair, no draw = weak."""
        result = LessonClassifier._hand_connects_board('Qh Jd', '8c 5h 2s')
        self.assertEqual(result, 'weak')

    def test_connects_no_cards(self):
        """Missing cards returns None."""
        self.assertIsNone(LessonClassifier._hand_connects_board('', 'Ah Kd 2c'))
        self.assertIsNone(LessonClassifier._hand_connects_board('Ah Kd', ''))


# ── CBet Flop IP Evaluation Tests (US-046) ──────────────────────────


class TestCBetFlopIPEvaluation(unittest.TestCase):
    """Test _eval_cbet_flop_ip and lesson 13 detection+evaluation."""

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

    def _cbet_ip_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 13), None)
        return m.executed_correctly if m else None

    def _setup_cbet_ip(self, hand_id, hero_cards='Ah Kd',
                       board_flop='Ts 7d 2c'):
        """Set up a c-bet IP scenario: hero opens BTN, villain calls BB."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       2.0, 1, 4, 'BTN')

    # -- Detection --

    def test_detected_as_lesson_13(self):
        """CBet IP scenario detects lesson 13."""
        self._setup_cbet_ip('CIP01')
        matches = self._classify('CIP01')
        self.assertIn(13, [m.lesson_id for m in matches])

    def test_not_detected_as_lesson_14(self):
        """CBet IP should not detect lesson 14 (OOP)."""
        self._setup_cbet_ip('CIP02')
        matches = self._classify('CIP02')
        self.assertNotIn(14, [m.lesson_id for m in matches])

    # -- Value hands: correct on any texture --

    def test_strong_hand_dry_board_correct(self):
        """Top pair good kicker on dry board = correct (1)."""
        self._setup_cbet_ip('CIP10', hero_cards='Ah Kd',
                            board_flop='As 7d 2c')
        self.assertEqual(self._cbet_ip_result('CIP10'), 1)

    def test_strong_hand_wet_board_correct(self):
        """Set on wet board = correct (1)."""
        self._setup_cbet_ip('CIP11', hero_cards='9h 9d',
                            board_flop='9s 8h 7h')
        self.assertEqual(self._cbet_ip_result('CIP11'), 1)

    def test_medium_hand_neutral_board_correct(self):
        """Middle pair on neutral board = correct (1)."""
        self._setup_cbet_ip('CIP12', hero_cards='7h 3d',
                            board_flop='Ah 7c 2s')
        self.assertEqual(self._cbet_ip_result('CIP12'), 1)

    def test_draw_wet_board_correct(self):
        """Flush draw on wet board = correct (semi-bluff)."""
        self._setup_cbet_ip('CIP13', hero_cards='Qh 9h',
                            board_flop='Ah 7h 2c')
        self.assertEqual(self._cbet_ip_result('CIP13'), 1)

    # -- Air on different textures --

    def test_air_dry_board_correct(self):
        """Air on dry board IP = correct (bluffing dry boards is fine IP)."""
        self._setup_cbet_ip('CIP20', hero_cards='Qh Jd',
                            board_flop='8c 5s 2h')
        self.assertEqual(self._cbet_ip_result('CIP20'), 1)

    def test_air_neutral_board_marginal(self):
        """Air on neutral board IP = marginal (None)."""
        self._setup_cbet_ip('CIP21', hero_cards='Qh Jd',
                            board_flop='Ah 7h 2c')
        self.assertIsNone(self._cbet_ip_result('CIP21'))

    def test_air_wet_board_incorrect(self):
        """Air on wet board IP = incorrect (over-bluffing)."""
        # 3d 2c has no pair/draw connection to 9h 8h 7h
        self._setup_cbet_ip('CIP22', hero_cards='3d 2c',
                            board_flop='9h 8h 7h')
        self.assertEqual(self._cbet_ip_result('CIP22'), 0)

    # -- Edge cases --

    def test_no_hero_cards_assumes_correct(self):
        """No hero_cards available = assume correct (1)."""
        _insert_hand(self.repo, 'CIP30', position='BTN',
                     board_flop='Ah Kd 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('CIP30',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'CIP30', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'CIP30', 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'CIP30', 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, 'CIP30', 'flop', 'Hero', 'bet',
                       2.0, 1, 4, 'BTN')
        self.assertEqual(self._cbet_ip_result('CIP30'), 1)

    def test_no_board_flop_not_detected(self):
        """Without board_flop, classify_hand skips postflop analysis."""
        _insert_hand(self.repo, 'CIP31', position='BTN',
                     board_flop='Ah Kd 2c')
        self.repo.conn.execute(
            "UPDATE hands SET board_flop=NULL WHERE hand_id=?", ('CIP31',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'CIP31', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'CIP31', 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'CIP31', 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, 'CIP31', 'flop', 'Hero', 'bet',
                       2.0, 1, 4, 'BTN')
        # No board_flop → postflop is skipped entirely
        matches = self._classify('CIP31')
        self.assertNotIn(13, [m.lesson_id for m in matches])


# ── CBet Flop OOP Evaluation Tests (US-046) ─────────────────────────


class TestCBetFlopOOPEvaluation(unittest.TestCase):
    """Test _eval_cbet_flop_oop and lesson 14 detection+evaluation."""

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

    def _cbet_oop_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 14), None)
        return m.executed_correctly if m else None

    def _setup_cbet_oop(self, hand_id, hero_cards='Ah Kd',
                        board_flop='Ts 7d 2c'):
        """Set up c-bet OOP: hero 3-bets from BB, villain calls BTN."""
        _insert_hand(self.repo, hand_id, position='BB',
                     board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       4.5, 1, 2, 'BB')
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       4.5, 0, 3, 'BTN')
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       3.0, 1, 4, 'BB')
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'call',
                       3.0, 0, 5, 'BTN')

    # -- Detection --

    def test_detected_as_lesson_14(self):
        """CBet OOP scenario detects lesson 14."""
        self._setup_cbet_oop('COP01')
        matches = self._classify('COP01')
        self.assertIn(14, [m.lesson_id for m in matches])

    def test_not_detected_as_lesson_13(self):
        """CBet OOP should not detect lesson 13 (IP)."""
        self._setup_cbet_oop('COP02')
        matches = self._classify('COP02')
        self.assertNotIn(13, [m.lesson_id for m in matches])

    # -- Value hands: correct --

    def test_strong_hand_correct(self):
        """Overpair OOP = correct (1)."""
        self._setup_cbet_oop('COP10', hero_cards='Ah Ad',
                             board_flop='9h 7d 2c')
        self.assertEqual(self._cbet_oop_result('COP10'), 1)

    def test_medium_hand_correct(self):
        """Top pair weak kicker OOP = correct (1)."""
        self._setup_cbet_oop('COP11', hero_cards='Ah 3d',
                             board_flop='As 7c 2h')
        self.assertEqual(self._cbet_oop_result('COP11'), 1)

    def test_draw_correct(self):
        """Flush draw OOP = correct (semi-bluff)."""
        self._setup_cbet_oop('COP12', hero_cards='Qh 9h',
                             board_flop='Ah 7h 2c')
        self.assertEqual(self._cbet_oop_result('COP12'), 1)

    # -- Air on different textures --

    def test_air_dry_board_marginal(self):
        """Air on dry board OOP = marginal (None)."""
        self._setup_cbet_oop('COP20', hero_cards='Qh Jd',
                             board_flop='8c 5s 2h')
        self.assertIsNone(self._cbet_oop_result('COP20'))

    def test_air_neutral_board_incorrect(self):
        """Air on neutral board OOP = incorrect (0)."""
        self._setup_cbet_oop('COP21', hero_cards='Qh Jd',
                             board_flop='Ah 7h 2c')
        self.assertEqual(self._cbet_oop_result('COP21'), 0)

    def test_air_wet_board_incorrect(self):
        """Air on wet board OOP = incorrect (0)."""
        # 3d 2c has no pair/draw connection to 9h 8h 7h
        self._setup_cbet_oop('COP22', hero_cards='3d 2c',
                             board_flop='9h 8h 7h')
        self.assertEqual(self._cbet_oop_result('COP22'), 0)

    # -- Edge cases --

    def test_no_hero_cards_assumes_correct(self):
        """No hero_cards = assume correct (1)."""
        _insert_hand(self.repo, 'COP30', position='BB',
                     board_flop='Ah Kd 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('COP30',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'COP30', 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'COP30', 'preflop', 'Hero', 'raise',
                       4.5, 1, 2, 'BB')
        _insert_action(self.repo, 'COP30', 'preflop', 'P1', 'call',
                       4.5, 0, 3, 'BTN')
        _insert_action(self.repo, 'COP30', 'flop', 'Hero', 'bet',
                       3.0, 1, 4, 'BB')
        _insert_action(self.repo, 'COP30', 'flop', 'P1', 'call',
                       3.0, 0, 5, 'BTN')
        self.assertEqual(self._cbet_oop_result('COP30'), 1)


# ── BB vs CBet OOP Evaluation Tests (US-046) ────────────────────────


class TestBBvsCBetOOPEvaluation(unittest.TestCase):
    """Test _eval_bb_vs_cbet and lesson 18 detection+evaluation."""

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

    def _bb_vs_cbet_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 18), None)
        return m.executed_correctly if m else None

    def _setup_bb_vs_cbet(self, hand_id, hero_cards='Ah Kd',
                          board_flop='Ts 7d 2c', hero_action='call'):
        """Set up BB vs cbet OOP: villain opens BTN, hero calls BB,
        villain cbets flop, hero responds."""
        _insert_hand(self.repo, hand_id, position='BB',
                     board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       1.5, 1, 2, 'BB')
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                       0, 1, 3, 'BB')
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'bet',
                       2.0, 0, 4, 'BTN')
        if hero_action == 'call':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           2.0, 1, 5, 'BB')
        elif hero_action == 'raise':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'raise',
                           6.0, 1, 5, 'BB')
        elif hero_action == 'fold':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'fold',
                           0, 1, 5, 'BB')

    # -- Detection --

    def test_detected_as_lesson_18(self):
        """BB facing c-bet OOP scenario detects lesson 18."""
        self._setup_bb_vs_cbet('BVC01')
        matches = self._classify('BVC01')
        self.assertIn(18, [m.lesson_id for m in matches])

    # -- Strong hand: defend correct, fold incorrect --

    def test_strong_hand_call_correct(self):
        """Strong hand (top pair good kicker) calling = correct (1)."""
        self._setup_bb_vs_cbet('BVC10', hero_cards='Ah Kd',
                               board_flop='As 7c 2h', hero_action='call')
        self.assertEqual(self._bb_vs_cbet_result('BVC10'), 1)

    def test_strong_hand_raise_correct(self):
        """Strong hand (set) raising = correct (1)."""
        self._setup_bb_vs_cbet('BVC11', hero_cards='7h 7d',
                               board_flop='7s 9c 2h', hero_action='raise')
        self.assertEqual(self._bb_vs_cbet_result('BVC11'), 1)

    def test_strong_hand_fold_incorrect(self):
        """Strong hand folding to c-bet = incorrect (0)."""
        self._setup_bb_vs_cbet('BVC12', hero_cards='Ah Kd',
                               board_flop='As 7c 2h', hero_action='fold')
        self.assertEqual(self._bb_vs_cbet_result('BVC12'), 0)

    # -- Medium hand: defend correct, fold incorrect --

    def test_medium_hand_call_correct(self):
        """Medium hand (middle pair) calling = correct (1)."""
        self._setup_bb_vs_cbet('BVC13', hero_cards='7h 3d',
                               board_flop='Ah 7c 2s', hero_action='call')
        self.assertEqual(self._bb_vs_cbet_result('BVC13'), 1)

    def test_medium_hand_fold_incorrect(self):
        """Medium hand folding = incorrect (0)."""
        self._setup_bb_vs_cbet('BVC14', hero_cards='7h 3d',
                               board_flop='Ah 7c 2s', hero_action='fold')
        self.assertEqual(self._bb_vs_cbet_result('BVC14'), 0)

    # -- Draw: defend correct, fold marginal --

    def test_draw_call_correct(self):
        """Draw (flush draw) calling = correct (1)."""
        self._setup_bb_vs_cbet('BVC20', hero_cards='Qh 9h',
                               board_flop='Ah 7h 2c', hero_action='call')
        self.assertEqual(self._bb_vs_cbet_result('BVC20'), 1)

    def test_draw_raise_correct(self):
        """Draw raising (semi-bluff) = correct (1)."""
        self._setup_bb_vs_cbet('BVC21', hero_cards='Qh 9h',
                               board_flop='Ah 7h 2c', hero_action='raise')
        self.assertEqual(self._bb_vs_cbet_result('BVC21'), 1)

    def test_draw_fold_marginal(self):
        """Draw folding = marginal (None) - sizing dependent."""
        self._setup_bb_vs_cbet('BVC22', hero_cards='Qh 9h',
                               board_flop='Ah 7h 2c', hero_action='fold')
        self.assertIsNone(self._bb_vs_cbet_result('BVC22'))

    # -- Weak/air: fold correct, defend incorrect --

    def test_air_fold_correct(self):
        """Air folding to c-bet = correct (1)."""
        self._setup_bb_vs_cbet('BVC30', hero_cards='Qh Jd',
                               board_flop='8c 5s 2h', hero_action='fold')
        self.assertEqual(self._bb_vs_cbet_result('BVC30'), 1)

    def test_air_call_incorrect(self):
        """Air calling c-bet = incorrect (0)."""
        self._setup_bb_vs_cbet('BVC31', hero_cards='Qh Jd',
                               board_flop='8c 5s 2h', hero_action='call')
        self.assertEqual(self._bb_vs_cbet_result('BVC31'), 0)

    def test_air_raise_incorrect(self):
        """Air raising c-bet = incorrect (0)."""
        self._setup_bb_vs_cbet('BVC32', hero_cards='Qh Jd',
                               board_flop='8c 5s 2h', hero_action='raise')
        self.assertEqual(self._bb_vs_cbet_result('BVC32'), 0)

    # -- Edge cases --

    def test_no_hero_cards_fold_marginal(self):
        """No hero_cards + fold = marginal (None)."""
        _insert_hand(self.repo, 'BVC40', position='BB',
                     board_flop='Ah Kd 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('BVC40',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BVC40', 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'BVC40', 'preflop', 'Hero', 'call',
                       1.5, 1, 2, 'BB')
        _insert_action(self.repo, 'BVC40', 'flop', 'Hero', 'check',
                       0, 1, 3, 'BB')
        _insert_action(self.repo, 'BVC40', 'flop', 'P1', 'bet',
                       2.0, 0, 4, 'BTN')
        _insert_action(self.repo, 'BVC40', 'flop', 'Hero', 'fold',
                       0, 1, 5, 'BB')
        self.assertIsNone(self._bb_vs_cbet_result('BVC40'))

    def test_no_hero_cards_call_correct(self):
        """No hero_cards + call = correct (1)."""
        _insert_hand(self.repo, 'BVC41', position='BB',
                     board_flop='Ah Kd 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('BVC41',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BVC41', 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'BVC41', 'preflop', 'Hero', 'call',
                       1.5, 1, 2, 'BB')
        _insert_action(self.repo, 'BVC41', 'flop', 'Hero', 'check',
                       0, 1, 3, 'BB')
        _insert_action(self.repo, 'BVC41', 'flop', 'P1', 'bet',
                       2.0, 0, 4, 'BTN')
        _insert_action(self.repo, 'BVC41', 'flop', 'Hero', 'call',
                       2.0, 1, 5, 'BB')
        self.assertEqual(self._bb_vs_cbet_result('BVC41'), 1)

    def test_street_is_flop(self):
        """Lesson 18 match should have street='flop'."""
        self._setup_bb_vs_cbet('BVC50', hero_cards='Ah Kd',
                               board_flop='As 7c 2h')
        matches = self._classify('BVC50')
        m = next((m for m in matches if m.lesson_id == 18), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'flop')


# ── IP vs CBet Evaluation Tests (US-047) ─────────────────────────────


class TestIPvsCBetEvaluation(unittest.TestCase):
    """Test _eval_ip_vs_cbet and lesson 20 detection+evaluation."""

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

    def _ip_vs_cbet_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 20), None)
        return m.executed_correctly if m else None

    def _setup_ip_vs_cbet(self, hand_id, hero_cards='Ah Kd',
                          board_flop='Ts 7d 2c', hero_action='call'):
        """Set up IP-vs-CBet scenario: villain raises PF, hero calls BTN.
        Villain c-bets flop, hero responds (call/fold/raise).
        """
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'CO')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       1.5, 1, 2, 'BTN')
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'bet',
                       2.0, 0, 3, 'CO')
        if hero_action == 'call':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           2.0, 1, 4, 'BTN')
        elif hero_action == 'fold':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'fold',
                           0, 1, 4, 'BTN')
        elif hero_action == 'raise':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'raise',
                           6.0, 1, 4, 'BTN')

    # -- Detection --

    def test_detected_as_lesson_20(self):
        """IP vs CBet detects lesson 20."""
        self._setup_ip_vs_cbet('IVC01')
        matches = self._classify('IVC01')
        self.assertIn(20, [m.lesson_id for m in matches])

    def test_not_detected_oop(self):
        """OOP scenario should not trigger lesson 20."""
        _insert_hand(self.repo, 'IVC02', position='BB', board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'IVC02'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'IVC02', 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'IVC02', 'preflop', 'Hero', 'call',
                       1.5, 1, 2, 'BB')
        _insert_action(self.repo, 'IVC02', 'flop', 'Hero', 'check',
                       0, 1, 3, 'BB')
        _insert_action(self.repo, 'IVC02', 'flop', 'P1', 'bet',
                       2.0, 0, 4, 'BTN')
        _insert_action(self.repo, 'IVC02', 'flop', 'Hero', 'call',
                       2.0, 1, 5, 'BB')
        matches = self._classify('IVC02')
        self.assertNotIn(20, [m.lesson_id for m in matches])

    def test_street_is_flop(self):
        """Lesson 20 match should have street='flop'."""
        self._setup_ip_vs_cbet('IVC03')
        matches = self._classify('IVC03')
        m = next((m for m in matches if m.lesson_id == 20), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'flop')

    # -- Strong/medium hand: defend is correct, fold is wrong --

    def test_strong_hand_call_correct(self):
        """Strong hand calling c-bet IP = correct (1)."""
        self._setup_ip_vs_cbet('IVC10', hero_cards='Ah Kd',
                               board_flop='As 7d 2c', hero_action='call')
        self.assertEqual(self._ip_vs_cbet_result('IVC10'), 1)

    def test_strong_hand_raise_correct(self):
        """Strong hand raising c-bet IP = correct (1)."""
        self._setup_ip_vs_cbet('IVC11', hero_cards='Ah Kd',
                               board_flop='As 7d 2c', hero_action='raise')
        self.assertEqual(self._ip_vs_cbet_result('IVC11'), 1)

    def test_strong_hand_fold_incorrect(self):
        """Strong hand folding c-bet IP = incorrect (0)."""
        self._setup_ip_vs_cbet('IVC12', hero_cards='Ah Kd',
                               board_flop='As 7d 2c', hero_action='fold')
        self.assertEqual(self._ip_vs_cbet_result('IVC12'), 0)

    def test_medium_hand_call_correct(self):
        """Medium hand (middle pair) calling IP = correct (1)."""
        self._setup_ip_vs_cbet('IVC13', hero_cards='7h 3d',
                               board_flop='Ah 7c 2s', hero_action='call')
        self.assertEqual(self._ip_vs_cbet_result('IVC13'), 1)

    def test_medium_hand_fold_incorrect(self):
        """Medium hand folding c-bet IP = incorrect (0)."""
        self._setup_ip_vs_cbet('IVC14', hero_cards='7h 3d',
                               board_flop='Ah 7c 2s', hero_action='fold')
        self.assertEqual(self._ip_vs_cbet_result('IVC14'), 0)

    # -- Draw: defend is correct, fold is marginal --

    def test_draw_call_correct(self):
        """Flush draw calling c-bet IP = correct (1)."""
        self._setup_ip_vs_cbet('IVC20', hero_cards='Qh 9h',
                               board_flop='Ah 7h 2c', hero_action='call')
        self.assertEqual(self._ip_vs_cbet_result('IVC20'), 1)

    def test_draw_raise_correct(self):
        """Flush draw raising (semi-bluff) IP = correct (1)."""
        self._setup_ip_vs_cbet('IVC21', hero_cards='Qh 9h',
                               board_flop='Ah 7h 2c', hero_action='raise')
        self.assertEqual(self._ip_vs_cbet_result('IVC21'), 1)

    def test_draw_fold_marginal(self):
        """Flush draw folding c-bet IP = marginal (None)."""
        self._setup_ip_vs_cbet('IVC22', hero_cards='Qh 9h',
                               board_flop='Ah 7h 2c', hero_action='fold')
        self.assertIsNone(self._ip_vs_cbet_result('IVC22'))

    # -- Air: fold/raise ok, float marginal --

    def test_air_fold_correct(self):
        """Air folding c-bet IP = correct (1)."""
        self._setup_ip_vs_cbet('IVC30', hero_cards='Qh Jd',
                               board_flop='8c 5s 2h', hero_action='fold')
        self.assertEqual(self._ip_vs_cbet_result('IVC30'), 1)

    def test_air_raise_correct(self):
        """Air raising (bluff-raise) c-bet IP = correct (1)."""
        self._setup_ip_vs_cbet('IVC31', hero_cards='Qh Jd',
                               board_flop='8c 5s 2h', hero_action='raise')
        self.assertEqual(self._ip_vs_cbet_result('IVC31'), 1)

    def test_air_call_marginal(self):
        """Air floating (calling) c-bet IP = marginal (None)."""
        self._setup_ip_vs_cbet('IVC32', hero_cards='Qh Jd',
                               board_flop='8c 5s 2h', hero_action='call')
        self.assertIsNone(self._ip_vs_cbet_result('IVC32'))

    # -- Edge cases --

    def test_no_hero_cards_fold_marginal(self):
        """No hero_cards + fold = marginal (None)."""
        _insert_hand(self.repo, 'IVC40', position='BTN',
                     board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('IVC40',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'IVC40', 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'CO')
        _insert_action(self.repo, 'IVC40', 'preflop', 'Hero', 'call',
                       1.5, 1, 2, 'BTN')
        _insert_action(self.repo, 'IVC40', 'flop', 'P1', 'bet',
                       2.0, 0, 3, 'CO')
        _insert_action(self.repo, 'IVC40', 'flop', 'Hero', 'fold',
                       0, 1, 4, 'BTN')
        self.assertIsNone(self._ip_vs_cbet_result('IVC40'))

    def test_no_hero_cards_call_correct(self):
        """No hero_cards + call = correct (1)."""
        _insert_hand(self.repo, 'IVC41', position='BTN',
                     board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('IVC41',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'IVC41', 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'CO')
        _insert_action(self.repo, 'IVC41', 'preflop', 'Hero', 'call',
                       1.5, 1, 2, 'BTN')
        _insert_action(self.repo, 'IVC41', 'flop', 'P1', 'bet',
                       2.0, 0, 3, 'CO')
        _insert_action(self.repo, 'IVC41', 'flop', 'Hero', 'call',
                       2.0, 1, 4, 'BTN')
        self.assertEqual(self._ip_vs_cbet_result('IVC41'), 1)

    def test_set_on_wet_board_call_correct(self):
        """Set IP calling c-bet on wet board = correct (1)."""
        self._setup_ip_vs_cbet('IVC50', hero_cards='9h 9d',
                               board_flop='9s 8h 7h', hero_action='call')
        self.assertEqual(self._ip_vs_cbet_result('IVC50'), 1)

    def test_overpair_call_correct(self):
        """Overpair IP calling c-bet = correct (1)."""
        self._setup_ip_vs_cbet('IVC51', hero_cards='Qh Qd',
                               board_flop='Ts 7d 2c', hero_action='call')
        self.assertEqual(self._ip_vs_cbet_result('IVC51'), 1)


# ── Facing Check-Raise Evaluation Tests (US-047) ─────────────────────


class TestFacingCheckRaiseEvaluation(unittest.TestCase):
    """Test _eval_facing_checkraise and lesson 19 detection+evaluation."""

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

    def _cr_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 19), None)
        return m.executed_correctly if m else None

    def _setup_facing_checkraise(self, hand_id, hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='call'):
        """Hero bets flop IP, villain check-raises, hero responds."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       2.0, 1, 4, 'BTN')
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'raise',
                       6.0, 0, 5, 'BB')
        if hero_action == 'call':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           6.0, 1, 6, 'BTN')
        elif hero_action == 'fold':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'fold',
                           0, 1, 6, 'BTN')
        elif hero_action == 'raise':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'raise',
                           18.0, 1, 6, 'BTN')

    # -- Detection --

    def test_detected_as_lesson_19(self):
        """Facing check-raise detects lesson 19."""
        self._setup_facing_checkraise('FCR01')
        matches = self._classify('FCR01')
        self.assertIn(19, [m.lesson_id for m in matches])

    def test_street_is_flop(self):
        """Lesson 19 on flop check-raise should have street='flop'."""
        self._setup_facing_checkraise('FCR02')
        matches = self._classify('FCR02')
        m = next((m for m in matches if m.lesson_id == 19), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'flop')

    def test_not_detected_without_checkraise(self):
        """No check-raise = no lesson 19 detection."""
        _insert_hand(self.repo, 'FCR03', position='BTN',
                     board_flop='As 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'FCR03'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'FCR03', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'FCR03', 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'FCR03', 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, 'FCR03', 'flop', 'Hero', 'bet',
                       2.0, 1, 4, 'BTN')
        _insert_action(self.repo, 'FCR03', 'flop', 'P1', 'call',
                       2.0, 0, 5, 'BB')
        matches = self._classify('FCR03')
        self.assertNotIn(19, [m.lesson_id for m in matches])

    # -- Strong hand: must defend, fold is wrong --

    def test_strong_hand_call_correct(self):
        """Strong hand calling check-raise = correct (1)."""
        self._setup_facing_checkraise('FCR10', hero_cards='Ah Kd',
                                      board_flop='As 7d 2c', hero_action='call')
        self.assertEqual(self._cr_result('FCR10'), 1)

    def test_strong_hand_reraise_correct(self):
        """Strong hand re-raising vs check-raise = correct (1)."""
        self._setup_facing_checkraise('FCR11', hero_cards='Ah Kd',
                                      board_flop='As 7d 2c', hero_action='raise')
        self.assertEqual(self._cr_result('FCR11'), 1)

    def test_strong_hand_fold_incorrect(self):
        """Strong hand folding vs check-raise = incorrect (0)."""
        self._setup_facing_checkraise('FCR12', hero_cards='Ah Kd',
                                      board_flop='As 7d 2c', hero_action='fold')
        self.assertEqual(self._cr_result('FCR12'), 0)

    def test_set_fold_incorrect(self):
        """Set folding vs check-raise = incorrect (0)."""
        self._setup_facing_checkraise('FCR13', hero_cards='7h 7d',
                                      board_flop='7s 4c 2h', hero_action='fold')
        self.assertEqual(self._cr_result('FCR13'), 0)

    # -- Medium hand: call is correct, fold is marginal --

    def test_medium_hand_call_correct(self):
        """Middle pair calling check-raise = correct (1)."""
        self._setup_facing_checkraise('FCR20', hero_cards='7h 3d',
                                      board_flop='Ah 7c 2s', hero_action='call')
        self.assertEqual(self._cr_result('FCR20'), 1)

    def test_medium_hand_fold_marginal(self):
        """Medium hand folding vs check-raise = marginal (None)."""
        self._setup_facing_checkraise('FCR21', hero_cards='7h 3d',
                                      board_flop='Ah 7c 2s', hero_action='fold')
        self.assertIsNone(self._cr_result('FCR21'))

    def test_medium_hand_reraise_marginal(self):
        """Medium hand re-raising vs check-raise = marginal (None)."""
        self._setup_facing_checkraise('FCR22', hero_cards='7h 3d',
                                      board_flop='Ah 7c 2s', hero_action='raise')
        self.assertIsNone(self._cr_result('FCR22'))

    # -- Draw: defend is correct, fold is marginal --

    def test_draw_call_correct(self):
        """Flush draw calling check-raise = correct (1)."""
        self._setup_facing_checkraise('FCR30', hero_cards='Qh 9h',
                                      board_flop='Ah 7h 2c', hero_action='call')
        self.assertEqual(self._cr_result('FCR30'), 1)

    def test_draw_reraise_correct(self):
        """Flush draw re-raising (semi-bluff) vs check-raise = correct (1)."""
        self._setup_facing_checkraise('FCR31', hero_cards='Qh 9h',
                                      board_flop='Ah 7h 2c', hero_action='raise')
        self.assertEqual(self._cr_result('FCR31'), 1)

    def test_draw_fold_marginal(self):
        """Flush draw folding vs check-raise = marginal (None)."""
        self._setup_facing_checkraise('FCR32', hero_cards='Qh 9h',
                                      board_flop='Ah 7h 2c', hero_action='fold')
        self.assertIsNone(self._cr_result('FCR32'))

    # -- Air: fold is correct, defend is wrong --

    def test_air_fold_correct(self):
        """Air folding vs check-raise = correct (1)."""
        self._setup_facing_checkraise('FCR40', hero_cards='Qh Jd',
                                      board_flop='8c 5s 2h', hero_action='fold')
        self.assertEqual(self._cr_result('FCR40'), 1)

    def test_air_call_incorrect(self):
        """Air calling check-raise = incorrect (0)."""
        self._setup_facing_checkraise('FCR41', hero_cards='Qh Jd',
                                      board_flop='8c 5s 2h', hero_action='call')
        self.assertEqual(self._cr_result('FCR41'), 0)

    def test_air_reraise_incorrect(self):
        """Air re-raising vs check-raise = incorrect (0)."""
        self._setup_facing_checkraise('FCR42', hero_cards='Qh Jd',
                                      board_flop='8c 5s 2h', hero_action='raise')
        self.assertEqual(self._cr_result('FCR42'), 0)

    # -- Edge cases --

    def test_no_hero_cards_fold_marginal(self):
        """No hero_cards + fold vs check-raise = marginal (None)."""
        _insert_hand(self.repo, 'FCR50', position='BTN',
                     board_flop='As 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('FCR50',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'FCR50', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'FCR50', 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'FCR50', 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, 'FCR50', 'flop', 'Hero', 'bet',
                       2.0, 1, 4, 'BTN')
        _insert_action(self.repo, 'FCR50', 'flop', 'P1', 'raise',
                       6.0, 0, 5, 'BB')
        _insert_action(self.repo, 'FCR50', 'flop', 'Hero', 'fold',
                       0, 1, 6, 'BTN')
        self.assertIsNone(self._cr_result('FCR50'))

    def test_no_hero_cards_call_correct(self):
        """No hero_cards + call vs check-raise = correct (1)."""
        _insert_hand(self.repo, 'FCR51', position='BTN',
                     board_flop='As 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('FCR51',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'FCR51', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'FCR51', 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'FCR51', 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, 'FCR51', 'flop', 'Hero', 'bet',
                       2.0, 1, 4, 'BTN')
        _insert_action(self.repo, 'FCR51', 'flop', 'P1', 'raise',
                       6.0, 0, 5, 'BB')
        _insert_action(self.repo, 'FCR51', 'flop', 'Hero', 'call',
                       6.0, 1, 6, 'BTN')
        self.assertEqual(self._cr_result('FCR51'), 1)


# ── 3-Bet Pots Postflop Evaluation Tests (US-047) ────────────────────


class Test3BetPotPostflopEvaluation(unittest.TestCase):
    """Test _eval_3bet_pot_postflop and lesson 23 detection+evaluation."""

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

    def _3bet_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 23), None)
        return m.executed_correctly if m else None

    def _setup_3bet_pot_pfa(self, hand_id, hero_cards='Ah Kd',
                            board_flop='Ts 7d 2c', hero_action='bet'):
        """Hero 3-bets PF (is PFA), villain calls, hero acts postflop."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       2.0, 0, 1, 'CO')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       6.0, 1, 2, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       6.0, 0, 3, 'CO')
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, 4, 'CO')
        if hero_action == 'bet':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                           4.0, 1, 5, 'BTN')
        elif hero_action == 'check':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                           0, 1, 5, 'BTN')
        elif hero_action == 'fold':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'fold',
                           0, 1, 5, 'BTN')

    def _setup_3bet_pot_caller(self, hand_id, hero_cards='Ah Kd',
                               board_flop='Ts 7d 2c', hero_action='call'):
        """Hero calls a 3-bet (not PFA), villain c-bets, hero responds."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       2.0, 1, 1, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       6.0, 0, 2, 'BB')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       6.0, 1, 3, 'BTN')
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'bet',
                       4.0, 0, 4, 'BB')
        if hero_action == 'call':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           4.0, 1, 5, 'BTN')
        elif hero_action == 'fold':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'fold',
                           0, 1, 5, 'BTN')
        elif hero_action == 'raise':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'raise',
                           12.0, 1, 5, 'BTN')

    # -- Detection --

    def test_detected_as_lesson_23(self):
        """3-bet pot postflop detects lesson 23."""
        self._setup_3bet_pot_pfa('TBP01')
        matches = self._classify('TBP01')
        self.assertIn(23, [m.lesson_id for m in matches])

    def test_street_is_flop(self):
        """Lesson 23 match should have street='flop'."""
        self._setup_3bet_pot_pfa('TBP02')
        matches = self._classify('TBP02')
        m = next((m for m in matches if m.lesson_id == 23), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'flop')

    def test_not_detected_in_single_raised_pot(self):
        """Single raised pot should not trigger lesson 23."""
        _insert_hand(self.repo, 'TBP03', position='BTN',
                     board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'TBP03'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'TBP03', 'preflop', 'P1', 'raise',
                       2.0, 0, 1, 'CO')
        _insert_action(self.repo, 'TBP03', 'preflop', 'Hero', 'call',
                       2.0, 1, 2, 'BTN')
        _insert_action(self.repo, 'TBP03', 'flop', 'P1', 'bet',
                       2.0, 0, 3, 'CO')
        _insert_action(self.repo, 'TBP03', 'flop', 'Hero', 'call',
                       2.0, 1, 4, 'BTN')
        matches = self._classify('TBP03')
        self.assertNotIn(23, [m.lesson_id for m in matches])

    # -- PFA: strong/medium hands --

    def test_pfa_strong_bet_correct(self):
        """PFA with strong hand c-betting 3-bet pot = correct (1)."""
        self._setup_3bet_pot_pfa('TBP10', hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='bet')
        self.assertEqual(self._3bet_result('TBP10'), 1)

    def test_pfa_strong_check_correct(self):
        """PFA with strong hand checking 3-bet pot = correct (1)."""
        self._setup_3bet_pot_pfa('TBP11', hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='check')
        self.assertEqual(self._3bet_result('TBP11'), 1)

    def test_pfa_strong_fold_incorrect(self):
        """PFA with strong hand folding 3-bet pot = incorrect (0)."""
        self._setup_3bet_pot_pfa('TBP12', hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='fold')
        self.assertEqual(self._3bet_result('TBP12'), 0)

    def test_pfa_medium_hand_bet_correct(self):
        """PFA with medium hand c-betting = correct (1)."""
        self._setup_3bet_pot_pfa('TBP13', hero_cards='7h 3d',
                                 board_flop='Ah 7c 2s', hero_action='bet')
        self.assertEqual(self._3bet_result('TBP13'), 1)

    def test_pfa_medium_hand_fold_incorrect(self):
        """PFA with medium hand folding 3-bet pot = incorrect (0)."""
        self._setup_3bet_pot_pfa('TBP14', hero_cards='7h 3d',
                                 board_flop='Ah 7c 2s', hero_action='fold')
        self.assertEqual(self._3bet_result('TBP14'), 0)

    # -- PFA: draw hands --

    def test_pfa_draw_bet_correct(self):
        """PFA with draw (semi-bluff c-bet) 3-bet pot = correct (1)."""
        self._setup_3bet_pot_pfa('TBP20', hero_cards='Qh 9h',
                                 board_flop='Ah 7h 2c', hero_action='bet')
        self.assertEqual(self._3bet_result('TBP20'), 1)

    def test_pfa_draw_fold_marginal(self):
        """PFA with draw folding 3-bet pot = marginal (None)."""
        self._setup_3bet_pot_pfa('TBP21', hero_cards='Qh 9h',
                                 board_flop='Ah 7h 2c', hero_action='fold')
        self.assertIsNone(self._3bet_result('TBP21'))

    # -- PFA: air --

    def test_pfa_air_bet_correct(self):
        """PFA c-betting air in 3-bet pot = correct (1)."""
        self._setup_3bet_pot_pfa('TBP30', hero_cards='Qh Jd',
                                 board_flop='8c 5s 2h', hero_action='bet')
        self.assertEqual(self._3bet_result('TBP30'), 1)

    def test_pfa_air_check_marginal(self):
        """PFA checking air in 3-bet pot = marginal (None)."""
        self._setup_3bet_pot_pfa('TBP31', hero_cards='Qh Jd',
                                 board_flop='8c 5s 2h', hero_action='check')
        self.assertIsNone(self._3bet_result('TBP31'))

    # -- Caller: strong/medium hands --

    def test_caller_strong_call_correct(self):
        """Caller with strong hand facing c-bet 3-bet pot = correct (1)."""
        self._setup_3bet_pot_caller('TBP40', hero_cards='Ah Kd',
                                    board_flop='As 7d 2c', hero_action='call')
        self.assertEqual(self._3bet_result('TBP40'), 1)

    def test_caller_strong_fold_incorrect(self):
        """Caller folding strong hand vs c-bet 3-bet pot = incorrect (0)."""
        self._setup_3bet_pot_caller('TBP41', hero_cards='Ah Kd',
                                    board_flop='As 7d 2c', hero_action='fold')
        self.assertEqual(self._3bet_result('TBP41'), 0)

    def test_caller_medium_call_correct(self):
        """Caller with medium hand calling c-bet 3-bet pot = correct (1)."""
        self._setup_3bet_pot_caller('TBP42', hero_cards='7h 3d',
                                    board_flop='Ah 7c 2s', hero_action='call')
        self.assertEqual(self._3bet_result('TBP42'), 1)

    # -- Caller: air --

    def test_caller_air_fold_correct(self):
        """Caller folding air vs c-bet in 3-bet pot = correct (1)."""
        self._setup_3bet_pot_caller('TBP50', hero_cards='Qh Jd',
                                    board_flop='8c 5s 2h', hero_action='fold')
        self.assertEqual(self._3bet_result('TBP50'), 1)

    def test_caller_air_raise_incorrect(self):
        """Caller raising with air vs c-bet in 3-bet pot = incorrect (0)."""
        self._setup_3bet_pot_caller('TBP51', hero_cards='Qh Jd',
                                    board_flop='8c 5s 2h', hero_action='raise')
        self.assertEqual(self._3bet_result('TBP51'), 0)

    def test_caller_air_call_marginal(self):
        """Caller floating (calling) with air in 3-bet pot = marginal (None)."""
        self._setup_3bet_pot_caller('TBP52', hero_cards='Qh Jd',
                                    board_flop='8c 5s 2h', hero_action='call')
        self.assertIsNone(self._3bet_result('TBP52'))

    # -- Edge cases --

    def test_no_hero_cards_fold_marginal(self):
        """No hero_cards + fold in 3-bet pot = marginal (None)."""
        _insert_hand(self.repo, 'TBP60', position='BTN',
                     board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('TBP60',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'TBP60', 'preflop', 'P1', 'raise',
                       2.0, 0, 1, 'CO')
        _insert_action(self.repo, 'TBP60', 'preflop', 'Hero', 'raise',
                       6.0, 1, 2, 'BTN')
        _insert_action(self.repo, 'TBP60', 'preflop', 'P1', 'call',
                       6.0, 0, 3, 'CO')
        _insert_action(self.repo, 'TBP60', 'flop', 'P1', 'check',
                       0, 0, 4, 'CO')
        _insert_action(self.repo, 'TBP60', 'flop', 'Hero', 'fold',
                       0, 1, 5, 'BTN')
        self.assertIsNone(self._3bet_result('TBP60'))

    def test_no_hero_cards_bet_correct(self):
        """No hero_cards + bet in 3-bet pot = correct (1)."""
        _insert_hand(self.repo, 'TBP61', position='BTN',
                     board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('TBP61',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'TBP61', 'preflop', 'P1', 'raise',
                       2.0, 0, 1, 'CO')
        _insert_action(self.repo, 'TBP61', 'preflop', 'Hero', 'raise',
                       6.0, 1, 2, 'BTN')
        _insert_action(self.repo, 'TBP61', 'preflop', 'P1', 'call',
                       6.0, 0, 3, 'CO')
        _insert_action(self.repo, 'TBP61', 'flop', 'P1', 'check',
                       0, 0, 4, 'CO')
        _insert_action(self.repo, 'TBP61', 'flop', 'Hero', 'bet',
                       4.0, 1, 5, 'BTN')
        self.assertEqual(self._3bet_result('TBP61'), 1)

    def test_set_in_3bet_pot_correct(self):
        """Set in 3-bet pot (c-bet) = correct (1)."""
        self._setup_3bet_pot_pfa('TBP70', hero_cards='9h 9d',
                                 board_flop='9s 8h 7h', hero_action='bet')
        self.assertEqual(self._3bet_result('TBP70'), 1)

    def test_overpair_caller_correct(self):
        """Overpair calling c-bet in 3-bet pot = correct (1)."""
        self._setup_3bet_pot_caller('TBP71', hero_cards='Qh Qd',
                                    board_flop='Ts 7d 2c', hero_action='call')
        self.assertEqual(self._3bet_result('TBP71'), 1)


if __name__ == '__main__':
    unittest.main()
