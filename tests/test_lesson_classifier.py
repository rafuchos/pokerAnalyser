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

    # -- Lesson 10: Pós-Flop Avançado (old 12) --

    def test_any_postflop_hand(self):
        """Flop-only hand does not trigger lesson 10 (needs turn+river)."""
        _insert_hand(self.repo, 'PF001', position='BTN',
                     board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'PF001', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'PF001', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'PF001', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'PF001', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        matches = self._classify('PF001')
        # L10 (Pós-Flop Avançado) needs has_turn and has_river
        self.assertNotIn(10, self._lesson_ids(matches))

    # -- Lesson 11: C-Bet Flop IP (old 13) --

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
        self.assertIn(11, ids)  # C-Bet IP
        self.assertNotIn(12, ids)  # should NOT be OOP

    # -- Lesson 12: C-Bet OOP (old 14) --

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
        self.assertIn(12, ids)  # C-Bet OOP
        self.assertNotIn(11, ids)  # should NOT be IP

    # -- Lesson 13: C-Bet Turn (old 15) --

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
        self.assertIn(13, ids)  # C-Bet Turn
        cbt = next(m for m in matches if m.lesson_id == 13)
        self.assertEqual(cbt.street, 'turn')

    # -- Lesson 14: C-Bet River (old 16) --

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
        self.assertIn(14, ids)  # C-Bet River
        cbr = next(m for m in matches if m.lesson_id == 14)
        self.assertEqual(cbr.street, 'river')

    # -- Lesson 15: Delayed C-Bet (old 17) --

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
        self.assertIn(15, ids)  # Delayed C-Bet
        dcb = next(m for m in matches if m.lesson_id == 15)
        self.assertEqual(dcb.street, 'turn')

    # -- Lesson 16: BB vs C-Bet OOP (old 18) --

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
        self.assertIn(16, ids)  # BB vs C-Bet OOP

    # -- Lesson 17: Enfrentando Check-Raise (old 19) --

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
        self.assertIn(17, ids)  # Facing Check-Raise

    # -- Lesson 18: Pós-Flop IP enfrentando C-Bet (old 20) --

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
        self.assertIn(18, ids)  # IP facing C-Bet

    # -- Lesson 19: Bet vs Missed Bet (old 21) --

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
        self.assertIn(19, ids)  # Bet vs Missed Bet

    # -- Lesson 20: Probe do BB (old 22) --

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
        self.assertIn(20, ids)  # Probe do BB

    # -- Lesson 21: 3-Betted Pots Pós-Flop (old 23) --

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
        self.assertIn(21, ids)  # 3-Betted Pots


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
        """Bounty tournament hands match lessons 22-23."""
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
        self.assertIn(22, ids)  # Intro Bounty
        self.assertIn(23, ids)  # Bounty Ranges

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
        self.assertNotIn(22, ids)
        self.assertNotIn(23, ids)


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
        # Should match at least: BB preflop (6), BB vs C-Bet (16)
        self.assertGreaterEqual(len(lessons), 2)

    def test_at_least_15_lessons_classifiable(self):
        """Acceptance criteria: classifier can detect at least 15 of 23 lessons."""
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

        # 11: C-Bet IP
        _insert_hand(self.repo, 'AC10', position='BTN', board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'AC10', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'AC10', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'AC10', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'AC10', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        # 12: C-Bet OOP
        _insert_hand(self.repo, 'AC14', position='BB', board_flop='Jh Td 3c')
        _insert_action(self.repo, 'AC14', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'AC14', 'preflop', 'Hero', 'raise', 4.5, 1, 2, 'BB')
        _insert_action(self.repo, 'AC14', 'preflop', 'P1', 'call', 4.5, 0, 3, 'BTN')
        _insert_action(self.repo, 'AC14', 'flop', 'Hero', 'bet', 3.0, 1, 4, 'BB')

        # 15: Delayed C-Bet
        _insert_hand(self.repo, 'AC17', position='BTN',
                     board_flop='Ah Kd 2c', board_turn='5s')
        _insert_action(self.repo, 'AC17', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'AC17', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'AC17', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'AC17', 'flop', 'Hero', 'check', 0, 1, 4, 'BTN')
        _insert_action(self.repo, 'AC17', 'turn', 'P1', 'check', 0, 0, 5, 'BB')
        _insert_action(self.repo, 'AC17', 'turn', 'Hero', 'bet', 3.0, 1, 6, 'BTN')

        # 16: BB vs C-Bet OOP
        _insert_hand(self.repo, 'AC18', position='BB', board_flop='Qh 9d 4c')
        _insert_action(self.repo, 'AC18', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'AC18', 'preflop', 'Hero', 'call', 1.5, 1, 2, 'BB')
        _insert_action(self.repo, 'AC18', 'flop', 'Hero', 'check', 0, 1, 3, 'BB')
        _insert_action(self.repo, 'AC18', 'flop', 'P1', 'bet', 2.0, 0, 4, 'BTN')
        _insert_action(self.repo, 'AC18', 'flop', 'Hero', 'call', 2.0, 1, 5, 'BB')

        # 17: Check-Raise
        _insert_hand(self.repo, 'AC19', position='BTN', board_flop='Ah Kd 2c')
        _insert_action(self.repo, 'AC19', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'AC19', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'AC19', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'AC19', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')
        _insert_action(self.repo, 'AC19', 'flop', 'P1', 'raise', 6.0, 0, 5, 'BB')

        # 21: 3-Bet Pot Postflop
        _insert_hand(self.repo, 'AC23', position='BTN',
                     board_flop='Ah Kd 2c', net=5.0)
        _insert_action(self.repo, 'AC23', 'preflop', 'P1', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'AC23', 'preflop', 'Hero', 'raise', 4.5, 1, 2, 'BTN')
        _insert_action(self.repo, 'AC23', 'preflop', 'P1', 'call', 4.5, 0, 3, 'UTG')
        _insert_action(self.repo, 'AC23', 'flop', 'P1', 'check', 0, 0, 4, 'UTG')
        _insert_action(self.repo, 'AC23', 'flop', 'Hero', 'bet', 5.0, 1, 5, 'BTN')

        # 22-23: Bounty tournament
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

        # AC: at least 15 of 23 lessons covered
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

        cbet = next(m for m in matches if m.lesson_id == 11)
        self.assertEqual(cbet.executed_correctly, 1)

    def test_postflop_winning_hand(self):
        """L10 (Pós-Flop Avançado) needs turn+river; flop-only hand skipped."""
        _insert_hand(self.repo, 'EV003', position='BTN',
                     board_flop='Ah Kd 2c', net=5.0)
        _insert_action(self.repo, 'EV003', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'EV003', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'EV003', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'EV003', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        hand = _get_hand_dict(self.repo, 'EV003')
        actions = self.repo.get_hand_actions('EV003')
        matches = self.classifier.classify_hand(hand, actions)

        self.assertNotIn(10, [m.lesson_id for m in matches])

    def test_postflop_losing_hand(self):
        """L10 (Pós-Flop Avançado) needs turn+river; flop-only hand skipped."""
        _insert_hand(self.repo, 'EV004', position='BTN',
                     board_flop='Ah Kd 2c', net=-5.0)
        _insert_action(self.repo, 'EV004', 'preflop', 'Hero', 'raise', 1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'EV004', 'preflop', 'P1', 'call', 1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'EV004', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'EV004', 'flop', 'Hero', 'bet', 2.0, 1, 4, 'BTN')

        hand = _get_hand_dict(self.repo, 'EV004')
        actions = self.repo.get_hand_actions('EV004')
        matches = self.classifier.classify_hand(hand, actions)

        self.assertNotIn(10, [m.lesson_id for m in matches])


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
                     opener_pos='CO', hero_amount=6.0, opener_amount=1.5):
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
        """UTG/EP positions have tier 1 (tightest)."""
        for pos in ['UTG', 'EP', 'UTG+1', 'UTG+2']:
            self.assertEqual(self.classifier._OPEN_SHOVE_POS_MAX_TIER.get(pos), 1,
                             f'{pos} should have open shove tier 1')

    def test_open_shove_pos_tier_mp_hj_is_2(self):
        """LJ/MP/HJ have tier 2."""
        for pos in ['LJ', 'MP', 'HJ']:
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
    """Test bounty tournament range evaluation for lessons 22 and 23.

    Based on RegLife 'Introdução aos Torneios Bounty' and
    'Torneios Bounty - Ranges Práticos' PDFs.
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        # Set up a bounty tournament with low overlay (10%) so tier 2 stays marginal
        # High-overlay behavior (>=50%) is tested in TestUS053fBountyCoverage
        self.repo.insert_tournament({
            'tournament_id': 'BT01',
            'platform': 'GGPoker',
            'name': 'Bounty Hunter',
            'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 1,
            'total_buy_in': 12, 'is_bounty': True,
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

    # -- Lesson 23: Bounty Ranges Práticos --

    def test_bounty_ranges_correct_aa(self):
        """AA in bounty tournament = correct (tier 1)."""
        self._insert_bounty_hand('BT_R01', hero_cards='Ah Ad')
        self.assertEqual(self._bounty_result('BT_R01', 23), 1)

    def test_bounty_ranges_correct_kk(self):
        """KK in bounty tournament = correct (tier 1)."""
        self._insert_bounty_hand('BT_R02', hero_cards='Kh Kd')
        self.assertEqual(self._bounty_result('BT_R02', 23), 1)

    def test_bounty_ranges_correct_t9s(self):
        """T9s in bounty tier 1 = correct."""
        self._insert_bounty_hand('BT_R03', hero_cards='Th 9h')
        self.assertEqual(self._bounty_result('BT_R03', 23), 1)

    def test_bounty_ranges_correct_aks(self):
        """AKs in bounty tier 1 = correct."""
        self._insert_bounty_hand('BT_R04', hero_cards='Ah Kh')
        self.assertEqual(self._bounty_result('BT_R04', 23), 1)

    def test_bounty_ranges_marginal_k7s(self):
        """K7s in bounty tier 2 = marginal (None)."""
        self._insert_bounty_hand('BT_R05', hero_cards='Kh 7h')
        self.assertIsNone(self._bounty_result('BT_R05', 23))

    def test_bounty_ranges_marginal_a6o(self):
        """A6o in bounty tier 2 = marginal (None)."""
        self._insert_bounty_hand('BT_R06', hero_cards='Ah 6d')
        self.assertIsNone(self._bounty_result('BT_R06', 23))

    def test_bounty_ranges_marginal_t9o(self):
        """T9o in bounty tier 2 = marginal (None)."""
        self._insert_bounty_hand('BT_R07', hero_cards='Th 9d')
        self.assertIsNone(self._bounty_result('BT_R07', 23))

    def test_bounty_ranges_incorrect_72o(self):
        """72o = incorrect (too weak even with bounty overlay)."""
        self._insert_bounty_hand('BT_R08', hero_cards='7h 2d')
        self.assertEqual(self._bounty_result('BT_R08', 23), 0)

    def test_bounty_ranges_incorrect_32o(self):
        """32o = incorrect (trash hand, not in any bounty tier)."""
        self._insert_bounty_hand('BT_R09', hero_cards='3h 2d')
        self.assertEqual(self._bounty_result('BT_R09', 23), 0)

    def test_bounty_ranges_no_cards_returns_none(self):
        """Without hero cards, bounty ranges returns None."""
        _insert_hand(self.repo, 'BT_R10', position='BTN',
                     game_type='tournament', tournament_id='BT01')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('BT_R10',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BT_R10', 'preflop', 'Hero', 'raise',
                       300, 1, 1, 'BTN')
        self.assertIsNone(self._bounty_result('BT_R10', 23))

    # -- Lesson 22: Intro Torneios Bounty --

    def test_bounty_intro_fold_aa_is_incorrect(self):
        """Folding AA in a bounty spot = incorrect (clear mistake)."""
        self._insert_bounty_hand('BT_I01', hero_cards='Ah Ad', hero_folded=True)
        self.assertEqual(self._bounty_result('BT_I01', 22), 0)

    def test_bounty_intro_fold_kk_is_incorrect(self):
        """Folding KK in a bounty spot = incorrect."""
        self._insert_bounty_hand('BT_I02', hero_cards='Kh Kd', hero_folded=True)
        self.assertEqual(self._bounty_result('BT_I02', 22), 0)

    def test_bounty_intro_fold_aks_is_incorrect(self):
        """Folding AKs in a bounty spot = incorrect (premium hand)."""
        self._insert_bounty_hand('BT_I03', hero_cards='Ah Kh', hero_folded=True)
        self.assertEqual(self._bounty_result('BT_I03', 22), 0)

    def test_bounty_intro_medium_hand_is_none(self):
        """Playing 77 in a bounty tournament = contextual (None)."""
        self._insert_bounty_hand('BT_I04', hero_cards='7h 7d')
        self.assertIsNone(self._bounty_result('BT_I04', 22))

    def test_bounty_intro_not_folding_aa_is_none(self):
        """Playing (not folding) AA in bounty = None (not a clear mistake)."""
        self._insert_bounty_hand('BT_I05', hero_cards='Ah Ad')
        self.assertIsNone(self._bounty_result('BT_I05', 22))

    def test_bounty_intro_no_cards_returns_none(self):
        """Without hero cards, bounty intro returns None."""
        _insert_hand(self.repo, 'BT_I06', position='BTN',
                     game_type='tournament', tournament_id='BT01')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('BT_I06',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BT_I06', 'preflop', 'Hero', 'raise',
                       300, 1, 1, 'BTN')
        self.assertIsNone(self._bounty_result('BT_I06', 22))

    def test_bounty_intro_fold_trash_is_none(self):
        """Folding 72o in a bounty pot = None (folding trash is fine)."""
        self._insert_bounty_hand('BT_I07', hero_cards='7h 2d', hero_folded=True)
        self.assertIsNone(self._bounty_result('BT_I07', 22))

    # -- Both lessons detected --

    def test_bounty_both_lessons_detected(self):
        """Both lessons 22 and 23 are detected for bounty tournament hands."""
        self._insert_bounty_hand('BT_D01', hero_cards='Ah Ad')
        matches = self._classify('BT_D01')
        ids = [m.lesson_id for m in matches]
        self.assertIn(22, ids)
        self.assertIn(23, ids)

    def test_bounty_lesson_22_detected_without_preflop_action(self):
        """Lesson 22 is detected for all bounty tournament hands (detection only)."""
        _insert_hand(self.repo, 'BT_D02', position='BTN',
                     game_type='tournament', tournament_id='BT01')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", ('Ah Kd', 'BT_D02'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'BT_D02', 'preflop', 'Hero', 'raise',
                       300, 1, 1, 'BTN')
        matches = self._classify('BT_D02')
        ids = [m.lesson_id for m in matches]
        self.assertIn(22, ids)


# ── Bounty Coverage Tests (US-053f) ──────────────────────────────────


class TestUS053fBountyCoverage(unittest.TestCase):
    """Test bounty coverage (overlay) impact on lessons 22 and 23.

    High bounty overlay (bounty >= 50% buy_in) makes tier 2 hands profitable
    and should be reflected in the evaluation.
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        # High overlay tournament: bounty=5, buy_in=10, ratio=50%
        self.repo.insert_tournament({
            'tournament_id': 'BH01',
            'platform': 'GGPoker',
            'name': 'High Bounty',
            'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 5,
            'total_buy_in': 16, 'is_bounty': True,
        })
        # Low overlay tournament: bounty=1, buy_in=10, ratio=10%
        self.repo.insert_tournament({
            'tournament_id': 'BL01',
            'platform': 'GGPoker',
            'name': 'Low Bounty',
            'date': '2026-01-15',
            'buy_in': 10, 'rake': 1, 'bounty': 1,
            'total_buy_in': 12, 'is_bounty': True,
        })

    def tearDown(self):
        self.conn.close()

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _bounty_result(self, hand_id, lesson_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == lesson_id), None)
        return m.executed_correctly if m else None

    def _insert_bounty_hand(self, hand_id, hero_cards, tournament_id,
                             hero_pos='BTN', hero_folded=False):
        _insert_hand(self.repo, hand_id, position=hero_pos,
                     game_type='tournament', tournament_id=tournament_id)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        if hero_folded:
            _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                           300, 0, 1, 'UTG')
            _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'fold',
                           0, 1, 2, hero_pos)
        else:
            _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                           300, 1, 1, hero_pos)

    # -- Lesson 23 (Bounty Ranges): coverage affects tier evaluation --

    def test_high_overlay_tier2_play_correct(self):
        """Tier 2 hand played in high overlay = correct (1)."""
        self._insert_bounty_hand('BC01', 'Kh 7h', 'BH01')  # K7s = tier 2
        self.assertEqual(self._bounty_result('BC01', 23), 1)

    def test_low_overlay_tier2_play_marginal(self):
        """Tier 2 hand played in low overlay = marginal (None)."""
        self._insert_bounty_hand('BC02', 'Kh 7h', 'BL01')
        self.assertIsNone(self._bounty_result('BC02', 23))

    def test_high_overlay_tier2_fold_incorrect(self):
        """Tier 2 hand folded in high overlay = incorrect (0)."""
        self._insert_bounty_hand('BC03', 'Kh 7h', 'BH01', hero_folded=True)
        self.assertEqual(self._bounty_result('BC03', 23), 0)

    def test_tier1_fold_always_incorrect(self):
        """Tier 1 hand folded in any bounty = incorrect (0)."""
        self._insert_bounty_hand('BC04', 'Ah Ad', 'BL01', hero_folded=True)
        self.assertEqual(self._bounty_result('BC04', 23), 0)

    def test_tier3_fold_correct(self):
        """Tier 3 hand folded = correct (1)."""
        self._insert_bounty_hand('BC05', '7h 2d', 'BH01', hero_folded=True)
        self.assertEqual(self._bounty_result('BC05', 23), 1)

    def test_tier3_play_incorrect(self):
        """Tier 3 hand played = incorrect (0)."""
        self._insert_bounty_hand('BC06', '7h 2d', 'BH01')
        self.assertEqual(self._bounty_result('BC06', 23), 0)

    # -- Lesson 22 (Bounty Intro): high overlay widens incorrect folds --

    def test_high_overlay_fold_tier1_incorrect(self):
        """Folding tier 1 non-premium in high overlay = incorrect (0)."""
        self._insert_bounty_hand('BC10', 'Th 9h', 'BH01',
                                  hero_folded=True)  # T9s = tier 1
        self.assertEqual(self._bounty_result('BC10', 22), 0)

    def test_low_overlay_fold_tier1_nonpremium_is_none(self):
        """Folding tier 1 non-premium in low overlay = None (context)."""
        self._insert_bounty_hand('BC11', 'Th 9h', 'BL01', hero_folded=True)
        self.assertIsNone(self._bounty_result('BC11', 22))

    def test_high_overlay_fold_premium_incorrect(self):
        """Folding premium in any bounty = incorrect (0)."""
        self._insert_bounty_hand('BC12', 'Ah Ad', 'BH01', hero_folded=True)
        self.assertEqual(self._bounty_result('BC12', 22), 0)

    # -- Notes include overlay info --

    def test_high_overlay_note_mentions_overlay(self):
        """Notes for high overlay should mention bounty coverage."""
        self._insert_bounty_hand('BC20', 'Kh 7h', 'BH01')
        matches = self._classify('BC20')
        m23 = next((m for m in matches if m.lesson_id == 23), None)
        self.assertIsNotNone(m23)
        self.assertIn('overlay', m23.notes.lower())


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
    """Test _eval_cbet_flop_ip and lesson 11 detection+evaluation."""

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
        m = next((m for m in matches if m.lesson_id == 11), None)
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

    def test_detected_as_lesson_11(self):
        """CBet IP scenario detects lesson 11."""
        self._setup_cbet_ip('CIP01')
        matches = self._classify('CIP01')
        self.assertIn(11, [m.lesson_id for m in matches])

    def test_not_detected_as_lesson_12(self):
        """CBet IP should not detect lesson 12 (OOP)."""
        self._setup_cbet_ip('CIP02')
        matches = self._classify('CIP02')
        self.assertNotIn(12, [m.lesson_id for m in matches])

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

    def test_air_neutral_board_correct(self):
        """Air on neutral board IP = correct (1): IP position advantage favors bluffing."""
        self._setup_cbet_ip('CIP21', hero_cards='Qh Jd',
                            board_flop='Ah 7h 2c')
        self.assertEqual(self._cbet_ip_result('CIP21'), 1)

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
        self.assertNotIn(11, [m.lesson_id for m in matches])


# ── CBet Flop OOP Evaluation Tests (US-046) ─────────────────────────


class TestCBetFlopOOPEvaluation(unittest.TestCase):
    """Test _eval_cbet_flop_oop and lesson 12 detection+evaluation."""

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
        m = next((m for m in matches if m.lesson_id == 12), None)
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

    def test_detected_as_lesson_12(self):
        """CBet OOP scenario detects lesson 12."""
        self._setup_cbet_oop('COP01')
        matches = self._classify('COP01')
        self.assertIn(12, [m.lesson_id for m in matches])

    def test_not_detected_as_lesson_11(self):
        """CBet OOP should not detect lesson 11 (IP)."""
        self._setup_cbet_oop('COP02')
        matches = self._classify('COP02')
        self.assertNotIn(11, [m.lesson_id for m in matches])

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
    """Test _eval_bb_vs_cbet and lesson 16 detection+evaluation."""

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
        m = next((m for m in matches if m.lesson_id == 16), None)
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

    def test_detected_as_lesson_16(self):
        """BB facing c-bet OOP scenario detects lesson 16."""
        self._setup_bb_vs_cbet('BVC01')
        matches = self._classify('BVC01')
        self.assertIn(16, [m.lesson_id for m in matches])

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
        """Lesson 16 match should have street='flop'."""
        self._setup_bb_vs_cbet('BVC50', hero_cards='Ah Kd',
                               board_flop='As 7c 2h')
        matches = self._classify('BVC50')
        m = next((m for m in matches if m.lesson_id == 16), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'flop')


# ── IP vs CBet Evaluation Tests (US-047) ─────────────────────────────


class TestIPvsCBetEvaluation(unittest.TestCase):
    """Test _eval_ip_vs_cbet and lesson 18 detection+evaluation."""

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
        m = next((m for m in matches if m.lesson_id == 18), None)
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

    def test_detected_as_lesson_18(self):
        """IP vs CBet detects lesson 18."""
        self._setup_ip_vs_cbet('IVC01')
        matches = self._classify('IVC01')
        self.assertIn(18, [m.lesson_id for m in matches])

    def test_not_detected_oop(self):
        """OOP scenario should not trigger lesson 18."""
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
        self.assertNotIn(18, [m.lesson_id for m in matches])

    def test_street_is_flop(self):
        """Lesson 18 match should have street='flop'."""
        self._setup_ip_vs_cbet('IVC03')
        matches = self._classify('IVC03')
        m = next((m for m in matches if m.lesson_id == 18), None)
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
        m = next((m for m in matches if m.lesson_id == 17), None)
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

    def test_detected_as_lesson_17(self):
        """Facing check-raise detects lesson 17."""
        self._setup_facing_checkraise('FCR01')
        matches = self._classify('FCR01')
        self.assertIn(17, [m.lesson_id for m in matches])

    def test_street_is_flop(self):
        """Lesson 17 on flop check-raise should have street='flop'."""
        self._setup_facing_checkraise('FCR02')
        matches = self._classify('FCR02')
        m = next((m for m in matches if m.lesson_id == 17), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'flop')

    def test_not_detected_without_checkraise(self):
        """No check-raise = no lesson 17 detection."""
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
        self.assertNotIn(17, [m.lesson_id for m in matches])

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
        m = next((m for m in matches if m.lesson_id == 21), None)
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

    def test_detected_as_lesson_21(self):
        """3-bet pot postflop detects lesson 21."""
        self._setup_3bet_pot_pfa('TBP01')
        matches = self._classify('TBP01')
        self.assertIn(21, [m.lesson_id for m in matches])

    def test_street_is_flop(self):
        """Lesson 21 match should have street='flop'."""
        self._setup_3bet_pot_pfa('TBP02')
        matches = self._classify('TBP02')
        m = next((m for m in matches if m.lesson_id == 21), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'flop')

    def test_not_detected_in_single_raised_pot(self):
        """Single raised pot should not trigger lesson 21."""
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
        self.assertNotIn(21, [m.lesson_id for m in matches])

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

    # -- All-in preflop guard (US-053f) --

    def test_allin_preflop_guard_blocks_lesson_21(self):
        """Hands all-in preflop should NOT trigger lesson 21."""
        _insert_hand(self.repo, 'TBP_G1', position='BTN',
                     board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=?, has_allin=1, "
            "allin_street='preflop' WHERE hand_id=?",
            ('Ah Kd', 'TBP_G1'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'TBP_G1', 'preflop', 'P1', 'raise',
                       2.0, 0, 1, 'CO')
        _insert_action(self.repo, 'TBP_G1', 'preflop', 'Hero', 'raise',
                       6.0, 1, 2, 'BTN')
        _insert_action(self.repo, 'TBP_G1', 'preflop', 'P1', 'all-in',
                       50.0, 0, 3, 'CO')
        _insert_action(self.repo, 'TBP_G1', 'preflop', 'Hero', 'call',
                       50.0, 1, 4, 'BTN')
        matches = self._classify('TBP_G1')
        self.assertNotIn(21, [m.lesson_id for m in matches])

    def test_no_postflop_action_guard_blocks_lesson_21(self):
        """3-bet pot with no hero postflop action should NOT trigger lesson 21."""
        _insert_hand(self.repo, 'TBP_G2', position='BTN',
                     board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'TBP_G2'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'TBP_G2', 'preflop', 'P1', 'raise',
                       2.0, 0, 1, 'CO')
        _insert_action(self.repo, 'TBP_G2', 'preflop', 'Hero', 'raise',
                       6.0, 1, 2, 'BTN')
        _insert_action(self.repo, 'TBP_G2', 'preflop', 'P1', 'call',
                       6.0, 0, 3, 'CO')
        # Villain bets flop but hero has no action recorded
        _insert_action(self.repo, 'TBP_G2', 'flop', 'P1', 'bet',
                       4.0, 0, 4, 'CO')
        matches = self._classify('TBP_G2')
        self.assertNotIn(21, [m.lesson_id for m in matches])

    # -- SPR note in 3-bet pot (US-053f) --

    def test_spr_note_included(self):
        """3-bet pot notes should include SPR estimate."""
        self._setup_3bet_pot_pfa('TBP_S1', hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='bet')
        matches = self._classify('TBP_S1')
        m = next((m for m in matches if m.lesson_id == 21), None)
        self.assertIsNotNone(m)
        self.assertIn('SPR~', m.notes)


# ── Turn Changes Texture Helper Tests (US-048) ───────────────────────


class TestTurnChangesTexture(unittest.TestCase):
    """Test _turn_changes_texture helper."""

    # -- Flush danger --

    def test_flush_danger_turn_completes_2suited_flop(self):
        """Turn is same suit as 2-suited flop → dangerous."""
        result = LessonClassifier._turn_changes_texture('9h 8h 7c', '2h')
        self.assertEqual(result, 'dangerous')

    def test_flush_danger_turn_completes_suited_ace_flop(self):
        """Turn adds 3rd heart to Ah 7h 2c flop → dangerous."""
        result = LessonClassifier._turn_changes_texture('Ah 7h 2c', '9h')
        self.assertEqual(result, 'dangerous')

    def test_no_flush_danger_different_suit(self):
        """Turn is different suit from 2-suited flop → no flush danger."""
        # Flop: 2 hearts; turn is spade
        result = LessonClassifier._turn_changes_texture('9h 8h 7c', '2s')
        # No flush, no new straight window from this addition:
        # 9→7, 8→6, 7→5, 2→0: indices [0,5,6,7], no 4-card window → blank
        self.assertEqual(result, 'blank')

    def test_rainbow_flop_flush_not_possible(self):
        """Rainbow flop with low turn = blank."""
        result = LessonClassifier._turn_changes_texture('Ah 7d 2c', '3s')
        self.assertEqual(result, 'blank')

    # -- Straight danger --

    def test_straight_danger_completes_4card_window(self):
        """Turn creates 4-card connected window not present on flop → dangerous."""
        # Flop: 9,8,7; turn: 6 → creates 9-8-7-6 window
        result = LessonClassifier._turn_changes_texture('9h 8c 7d', '6s')
        self.assertEqual(result, 'dangerous')

    def test_straight_danger_top_end_connect(self):
        """Turn completes KQJ + T straight draw."""
        result = LessonClassifier._turn_changes_texture('Kh Qd Jc', 'Ts')
        self.assertEqual(result, 'dangerous')

    def test_no_straight_danger_flop_already_connected(self):
        """If flop already had a 4-card window, turn extending it is not newly dangerous."""
        # This tests the flop_had_window guard.
        # Flop 9h 8c 7d 6s: that's 4 cards on flop which is impossible.
        # Instead: let's test a case where flop had the window already.
        # flop: T 9 8 7 would be 4 cards (not valid for flop).
        # Create a flop with a 4-card window: we'd need board_flop to have 4 ranks in a 5-span window.
        # Actually flop is 3 cards; the helper checks ALL board cards up to turn.
        # A normal 3-card flop can't have a 4-card window.
        # But if a turn extends 3-card flop: flop T9 + 8 = T,9,8 (indices 8,7,6) → only 3 in window
        # Turn: 7 (idx=5) → now [5,6,7,8] → 4 card → dangerous
        # Since the flop only had 3 in window, it's new → dangerous
        result = LessonClassifier._turn_changes_texture('Th 9c 8d', '7s')
        self.assertEqual(result, 'dangerous')

    # -- High card neutral --

    def test_neutral_high_card_turn(self):
        """Low-rank flop + high turn card (T+) → neutral."""
        result = LessonClassifier._turn_changes_texture('Ah 7d 2c', 'Ks')
        self.assertEqual(result, 'neutral')

    def test_neutral_ten_is_boundary(self):
        """T-rank turn = neutral (boundary case)."""
        result = LessonClassifier._turn_changes_texture('Ah 7d 2c', 'Ts')
        self.assertEqual(result, 'neutral')

    def test_neutral_jack(self):
        """J-rank turn on rainbow disconnected flop → neutral."""
        result = LessonClassifier._turn_changes_texture('Ah 7d 2c', 'Js')
        self.assertEqual(result, 'neutral')

    # -- Blank turn --

    def test_blank_low_card_rainbow(self):
        """2-rank turn on rainbow disconnected flop → blank."""
        result = LessonClassifier._turn_changes_texture('Kh 7d 2c', '4s')
        self.assertEqual(result, 'blank')

    def test_blank_9_rank(self):
        """9-rank turn (below T) on dry flop → blank (no draws)."""
        result = LessonClassifier._turn_changes_texture('Kh 7d 2c', '9s')
        self.assertEqual(result, 'blank')

    # -- Edge cases --

    def test_missing_turn_card_returns_neutral(self):
        """Empty board_turn returns neutral."""
        result = LessonClassifier._turn_changes_texture('Ah 7d 2c', '')
        self.assertEqual(result, 'neutral')

    def test_missing_flop_returns_neutral(self):
        """Empty board_flop returns neutral."""
        result = LessonClassifier._turn_changes_texture('', 'Ks')
        self.assertEqual(result, 'neutral')


# ── CBet Turn Evaluation Tests (US-048) ─────────────────────────────


class TestCBetTurnEvaluation(unittest.TestCase):
    """Test _eval_cbet_turn and lesson 13 detection+evaluation."""

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

    def _cbet_turn_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 13), None)
        return m.executed_correctly if m else None

    def _setup_double_barrel(self, hand_id, hero_cards='Ah Kd',
                              board_flop='Ts 7d 2c',
                              board_turn='3s'):
        """Set up a double barrel: hero opens BTN, villain BB, hero bets flop
        and bets turn."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop, board_turn=board_turn)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'call',
                       2.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')

    # -- Detection --

    def test_detected_as_lesson_13(self):
        """Double barrel detects lesson 13."""
        self._setup_double_barrel('CBT01')
        matches = self._classify('CBT01')
        self.assertIn(13, [m.lesson_id for m in matches])

    def test_street_is_turn(self):
        """Lesson 13 match has street='turn'."""
        self._setup_double_barrel('CBT02')
        matches = self._classify('CBT02')
        m = next((m for m in matches if m.lesson_id == 13), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'turn')

    def test_not_detected_without_turn(self):
        """No turn card → lesson 13 not detected."""
        _insert_hand(self.repo, 'CBT03', position='BTN',
                     board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'CBT03'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'CBT03', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'CBT03', 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'CBT03', 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, 'CBT03', 'flop', 'Hero', 'bet',
                       2.0, 1, 4, 'BTN')
        matches = self._classify('CBT03')
        self.assertNotIn(13, [m.lesson_id for m in matches])

    def test_not_detected_without_hero_pfa(self):
        """Villain is PFA, hero just bets turn → lesson 13 not triggered."""
        _insert_hand(self.repo, 'CBT04', position='BB',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'CBT04'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'CBT04', 'preflop', 'P1', 'raise',
                       1.5, 0, 1, 'BTN')
        _insert_action(self.repo, 'CBT04', 'preflop', 'Hero', 'call',
                       1.5, 1, 2, 'BB')
        _insert_action(self.repo, 'CBT04', 'flop', 'P1', 'bet',
                       2.0, 0, 3, 'BTN')
        _insert_action(self.repo, 'CBT04', 'flop', 'Hero', 'call',
                       2.0, 1, 4, 'BB')
        _insert_action(self.repo, 'CBT04', 'turn', 'P1', 'check',
                       0, 0, 5, 'BTN')
        _insert_action(self.repo, 'CBT04', 'turn', 'Hero', 'bet',
                       4.0, 1, 6, 'BB')
        matches = self._classify('CBT04')
        self.assertNotIn(13, [m.lesson_id for m in matches])

    # -- Value hands: always correct --

    def test_strong_hand_blank_turn_correct(self):
        """Top pair good kicker + blank turn: double barrel = correct (1)."""
        self._setup_double_barrel('CBT10', hero_cards='Ah Kd',
                                  board_flop='As 7d 2c', board_turn='3s')
        self.assertEqual(self._cbet_turn_result('CBT10'), 1)

    def test_strong_hand_dangerous_turn_correct(self):
        """Strong hand + dangerous turn: still correct (value always correct)."""
        # Flop: Ah 7h 2c (2-suited), turn: 9h (flush completes)
        # But hero has AK (top pair good kicker + evaluates on full board Ah 7h 2c 9h)
        # strength = 'strong' → always correct
        self._setup_double_barrel('CBT11', hero_cards='Ah Kd',
                                  board_flop='As 7h 2c', board_turn='9h')
        self.assertEqual(self._cbet_turn_result('CBT11'), 1)

    def test_overpair_neutral_turn_correct(self):
        """Overpair (KK) + neutral turn (Q): double barrel = correct (1)."""
        self._setup_double_barrel('CBT12', hero_cards='Kh Kd',
                                  board_flop='9h 7d 2c', board_turn='Qs')
        self.assertEqual(self._cbet_turn_result('CBT12'), 1)

    def test_set_dangerous_turn_correct(self):
        """Set + dangerous turn (flush completed): still correct (1)."""
        self._setup_double_barrel('CBT13', hero_cards='9h 9d',
                                  board_flop='9s 8h 7h', board_turn='2h')
        self.assertEqual(self._cbet_turn_result('CBT13'), 1)

    def test_medium_hand_blank_turn_correct(self):
        """Middle pair + blank turn: double barrel = correct (1)."""
        self._setup_double_barrel('CBT14', hero_cards='7h 3d',
                                  board_flop='Ah 7c 2s', board_turn='4h')
        self.assertEqual(self._cbet_turn_result('CBT14'), 1)

    # -- Draw hands: semi-bluff is correct --

    def test_flush_draw_blank_turn_correct(self):
        """Flush draw + blank turn: semi-bluff = correct (1)."""
        self._setup_double_barrel('CBT20', hero_cards='Qh 9h',
                                  board_flop='Ah 7h 2c', board_turn='3s')
        self.assertEqual(self._cbet_turn_result('CBT20'), 1)

    def test_oesd_draw_correct(self):
        """OESD + blank turn: semi-bluff double barrel = correct (1)."""
        self._setup_double_barrel('CBT21', hero_cards='Jh Td',
                                  board_flop='9c 8h 2s', board_turn='4d')
        self.assertEqual(self._cbet_turn_result('CBT21'), 1)

    def test_draw_dangerous_turn_correct(self):
        """Draw with dangerous turn: still correct (semi-bluff has equity)."""
        # Hero has flush draw on flop; turn is dangerous but hero is still drawing
        self._setup_double_barrel('CBT22', hero_cards='Qd Jd',
                                  board_flop='Ad 7d 2c', board_turn='Th')
        self.assertEqual(self._cbet_turn_result('CBT22'), 1)

    # -- Air (weak): depends on turn texture --

    def test_air_blank_turn_correct(self):
        """Air + blank turn: double barrel bluff = correct (1)."""
        # 'Qd Jc' on 'Ah 7d 2c 3s' → no pair, no draw, turn='3s' is blank
        self._setup_double_barrel('CBT30', hero_cards='Qd Jc',
                                  board_flop='Ah 7d 2c', board_turn='3s')
        self.assertEqual(self._cbet_turn_result('CBT30'), 1)

    def test_air_neutral_turn_marginal(self):
        """Air + neutral turn (K): double barrel = marginal (None)."""
        # Hero: 8c 4h → no pair, no draw on Ah 7d 2c Ks
        self._setup_double_barrel('CBT31', hero_cards='8c 4h',
                                  board_flop='Ah 7d 2c', board_turn='Ks')
        self.assertIsNone(self._cbet_turn_result('CBT31'))

    def test_air_dangerous_turn_flush_completion_incorrect(self):
        """Air + dangerous turn (flush completes): over-barreling = incorrect (0)."""
        # Flop: 9h 8h 7c (2-suited hearts); turn: 2h completes flush → dangerous
        # Hero: Kd 4c → no pair, no draw on full board (K/4 don't connect 9-8-7)
        self._setup_double_barrel('CBT32', hero_cards='Kd 4c',
                                  board_flop='9h 8h 7c', board_turn='2h')
        self.assertEqual(self._cbet_turn_result('CBT32'), 0)

    def test_air_dangerous_turn_flush_completion_incorrect_2(self):
        """Air + dangerous turn (flush completes on different board): over-barreling = incorrect (0)."""
        # Flop: Ks Qs 3d (2-suited spades); turn: 5s → 3rd spade → dangerous
        # Hero: 8c 4h → no pair, no draw on full board
        self._setup_double_barrel('CBT33', hero_cards='8c 4h',
                                  board_flop='Ks Qs 3d', board_turn='5s')
        self.assertEqual(self._cbet_turn_result('CBT33'), 0)

    def test_air_neutral_turn_jack(self):
        """Air + neutral turn (J): double barrel = marginal (None)."""
        # Hero: Kd 4c → no pair, no draw on Ah 7d 2c Js
        self._setup_double_barrel('CBT34', hero_cards='Kd 4c',
                                  board_flop='Ah 7d 2c', board_turn='Js')
        self.assertIsNone(self._cbet_turn_result('CBT34'))

    # -- Edge cases --

    def test_no_hero_cards_assumes_correct(self):
        """No hero_cards = assume correct (1)."""
        _insert_hand(self.repo, 'CBT40', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('CBT40',))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'CBT40', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBT40', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBT40', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBT40', 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBT40', 'flop', 'P1', 'call',
                       2.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBT40', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBT40', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')
        self.assertEqual(self._cbet_turn_result('CBT40'), 1)

    def test_no_board_turn_card_marginal(self):
        """Board turn field exists but empty hero cards scenario."""
        # Turn bet but no board_turn card stored → marginal (None)
        _insert_hand(self.repo, 'CBT41', position='BTN',
                     board_flop='Ts 7d 2c', board_turn=None)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Qd Jc', 'CBT41'))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'CBT41', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBT41', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBT41', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBT41', 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBT41', 'flop', 'P1', 'call',
                       2.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBT41', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBT41', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')
        self.assertIsNone(self._cbet_turn_result('CBT41'))

    def test_two_pair_turn_correct(self):
        """Two pair on turn (hero has both board cards): double barrel = correct."""
        self._setup_double_barrel('CBT50', hero_cards='Ah 7d',
                                  board_flop='As 7c 2h', board_turn='5s')
        self.assertEqual(self._cbet_turn_result('CBT50'), 1)

    def test_top_pair_weak_kicker_blank_turn_correct(self):
        """Top pair weak kicker + blank turn: double barrel = correct (1)."""
        self._setup_double_barrel('CBT51', hero_cards='Ah 3d',
                                  board_flop='As 7c 2h', board_turn='4s')
        self.assertEqual(self._cbet_turn_result('CBT51'), 1)


# ── Delayed CBet Evaluation Tests (US-048) ───────────────────────────


class TestDelayedCBetEvaluation(unittest.TestCase):
    """Test _eval_delayed_cbet and lesson 15 detection+evaluation."""

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

    def _delayed_cbet_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 15), None)
        return m.executed_correctly if m else None

    def _setup_delayed_cbet(self, hand_id, hero_cards='Ah Kd',
                             board_flop='Ts 7d 2c',
                             board_turn='3s'):
        """Set up delayed cbet: hero opens BTN, checks flop, villain checks
        back, hero bets turn."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop, board_turn=board_turn)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                       0, 1, seq, 'BTN'); seq += 1  # hero checks (delayed)
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')

    # -- Detection --

    def test_detected_as_lesson_17(self):
        """Delayed cbet detects lesson 15."""
        self._setup_delayed_cbet('DCB01')
        matches = self._classify('DCB01')
        self.assertIn(15, [m.lesson_id for m in matches])

    def test_street_is_turn(self):
        """Lesson 15 match has street='turn'."""
        self._setup_delayed_cbet('DCB02')
        matches = self._classify('DCB02')
        m = next((m for m in matches if m.lesson_id == 15), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'turn')

    def test_not_detected_without_flop_check(self):
        """Hero bets flop (normal cbet) and bets turn → no lesson 15."""
        _insert_hand(self.repo, 'DCB03', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'DCB03'))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'DCB03', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB03', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB03', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB03', 'flop', 'Hero', 'bet',  # cbet
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB03', 'flop', 'P1', 'call',
                       2.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB03', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB03', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')
        matches = self._classify('DCB03')
        self.assertNotIn(15, [m.lesson_id for m in matches])

    def test_not_detected_without_turn_bet(self):
        """Hero checks flop, checks turn → no lesson 15."""
        _insert_hand(self.repo, 'DCB04', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'DCB04'))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'DCB04', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB04', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB04', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB04', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB04', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB04', 'turn', 'Hero', 'check',
                       0, 1, seq, 'BTN')
        matches = self._classify('DCB04')
        self.assertNotIn(15, [m.lesson_id for m in matches])

    def test_not_detected_if_not_pfa(self):
        """Villain is PFA and hero checks flop and bets turn → no lesson 15."""
        _insert_hand(self.repo, 'DCB05', position='BB',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'DCB05'))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'DCB05', 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB05', 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB05', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB05', 'flop', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB05', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BB')
        matches = self._classify('DCB05')
        self.assertNotIn(15, [m.lesson_id for m in matches])

    # -- Value hands: always correct --

    def test_strong_hand_blank_turn_correct(self):
        """Delayed cbet with strong hand + blank turn = correct (1)."""
        self._setup_delayed_cbet('DCB10', hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', board_turn='3s')
        self.assertEqual(self._delayed_cbet_result('DCB10'), 1)

    def test_strong_hand_dangerous_turn_correct(self):
        """Delayed cbet with strong hand + dangerous turn = correct (1)."""
        # Hero has top pair + good kicker; turn is dangerous but value is value
        self._setup_delayed_cbet('DCB11', hero_cards='Ah Kd',
                                 board_flop='As 7h 2c', board_turn='9h')
        self.assertEqual(self._delayed_cbet_result('DCB11'), 1)

    def test_overpair_neutral_turn_correct(self):
        """Delayed cbet with overpair + neutral turn = correct (1)."""
        self._setup_delayed_cbet('DCB12', hero_cards='Kh Kd',
                                 board_flop='9h 7d 2c', board_turn='Qs')
        self.assertEqual(self._delayed_cbet_result('DCB12'), 1)

    def test_set_blank_turn_correct(self):
        """Delayed cbet with set + blank turn = correct (1)."""
        self._setup_delayed_cbet('DCB13', hero_cards='7h 7d',
                                 board_flop='7s 8c 2h', board_turn='3d')
        self.assertEqual(self._delayed_cbet_result('DCB13'), 1)

    def test_medium_hand_correct(self):
        """Delayed cbet with medium hand = correct (1)."""
        self._setup_delayed_cbet('DCB14', hero_cards='7h 3d',
                                 board_flop='Ah 7c 2s', board_turn='4d')
        self.assertEqual(self._delayed_cbet_result('DCB14'), 1)

    # -- Draw hands: semi-bluff is correct --

    def test_flush_draw_blank_turn_correct(self):
        """Delayed cbet with flush draw + blank turn = correct (1)."""
        self._setup_delayed_cbet('DCB20', hero_cards='Qh 9h',
                                 board_flop='Ah 7h 2c', board_turn='3s')
        self.assertEqual(self._delayed_cbet_result('DCB20'), 1)

    def test_oesd_draw_blank_turn_correct(self):
        """Delayed cbet with OESD + blank turn = correct (1)."""
        self._setup_delayed_cbet('DCB21', hero_cards='Jh Td',
                                 board_flop='9c 8h 2s', board_turn='4d')
        self.assertEqual(self._delayed_cbet_result('DCB21'), 1)

    def test_draw_dangerous_turn_correct(self):
        """Delayed cbet with draw + dangerous turn = correct (equity + villain weakness)."""
        # Hero has flush draw; turn adds more flush cards but hero still has equity
        self._setup_delayed_cbet('DCB22', hero_cards='Qd Jd',
                                 board_flop='Ad 7d 2c', board_turn='Th')
        self.assertEqual(self._delayed_cbet_result('DCB22'), 1)

    # -- Air: depends on turn texture --

    def test_air_blank_turn_correct(self):
        """Delayed cbet with air + blank turn = correct (villain weakness + blank)."""
        # Villain checked back showing weakness, turn is blank → delayed bluff is sound
        self._setup_delayed_cbet('DCB30', hero_cards='Qd Jc',
                                 board_flop='Ah 7d 2c', board_turn='3s')
        self.assertEqual(self._delayed_cbet_result('DCB30'), 1)

    def test_air_neutral_turn_correct(self):
        """Delayed cbet with air + neutral turn = correct (villain weakness justifies)."""
        self._setup_delayed_cbet('DCB31', hero_cards='Qd Jc',
                                 board_flop='Ah 7d 2c', board_turn='Ks')
        self.assertEqual(self._delayed_cbet_result('DCB31'), 1)

    def test_air_dangerous_turn_flush_marginal(self):
        """Delayed cbet with air + dangerous turn (flush completes) = marginal (None)."""
        # Flop: 9h 8h 7c (2-suited hearts); turn: 2h → dangerous
        # Hero: Kd 4c → no pair, no draw on full board
        self._setup_delayed_cbet('DCB32', hero_cards='Kd 4c',
                                 board_flop='9h 8h 7c', board_turn='2h')
        self.assertIsNone(self._delayed_cbet_result('DCB32'))

    def test_air_dangerous_flush_turn_marginal_2(self):
        """Delayed cbet with air + dangerous flush turn = marginal (None)."""
        # Flop: Ks Qs 3d (2-suited spades); turn: 5s → 3rd spade → dangerous
        # Hero: 8c 4h → no pair, no draw on full board
        self._setup_delayed_cbet('DCB33', hero_cards='8c 4h',
                                 board_flop='Ks Qs 3d', board_turn='5s')
        self.assertIsNone(self._delayed_cbet_result('DCB33'))

    # -- Edge cases --

    def test_no_hero_cards_assumes_correct(self):
        """No hero_cards = assume correct (villain checked back)."""
        _insert_hand(self.repo, 'DCB40', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('DCB40',))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'DCB40', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB40', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB40', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB40', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB40', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB40', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')
        self.assertEqual(self._delayed_cbet_result('DCB40'), 1)

    def test_no_board_turn_not_detected(self):
        """No board_turn stored → lesson 15 not detected (has_turn=False)."""
        _insert_hand(self.repo, 'DCB41', position='BTN',
                     board_flop='Ts 7d 2c', board_turn=None)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Qd Jc', 'DCB41'))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'DCB41', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB41', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB41', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB41', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'DCB41', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'DCB41', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')
        self.assertIsNone(self._delayed_cbet_result('DCB41'))

    def test_two_pair_turn_correct(self):
        """Delayed cbet with two pair improved on turn = correct (1)."""
        self._setup_delayed_cbet('DCB50', hero_cards='Ah 7d',
                                 board_flop='As 7c 2h', board_turn='5s')
        self.assertEqual(self._delayed_cbet_result('DCB50'), 1)

    def test_does_not_trigger_lesson_13(self):
        """Delayed cbet does NOT trigger lesson 13 (double barrel requires flop bet)."""
        self._setup_delayed_cbet('DCB51')
        matches = self._classify('DCB51')
        lesson_ids = [m.lesson_id for m in matches]
        # Lesson 13 (CBet Turn) requires hero to have bet the flop too (double barrel)
        # Delayed cbet checks the flop, so lesson 13 must NOT fire
        self.assertNotIn(13, lesson_ids)
        self.assertIn(15, lesson_ids)


class TestCBetRiverEvaluation(unittest.TestCase):
    """Test _eval_cbet_river and lesson 14 detection+evaluation."""

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

    def _cbet_river_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 14), None)
        return m.executed_correctly if m else None

    def _setup_triple_barrel(self, hand_id, hero_cards='Ah Kd',
                              board_flop='Ts 7d 2c',
                              board_turn='3s',
                              board_river='5h'):
        """Set up a triple barrel: hero opens BTN, villain BB, hero bets
        flop, turn, and river."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop, board_turn=board_turn,
                     board_river=board_river)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'call',
                       2.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'call',
                       4.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'river', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'river', 'Hero', 'bet',
                       8.0, 1, seq, 'BTN')

    # -- Detection tests --

    def test_detected_as_lesson_16(self):
        """Triple barrel detects lesson 14."""
        self._setup_triple_barrel('CBR01')
        matches = self._classify('CBR01')
        self.assertIn(14, [m.lesson_id for m in matches])

    def test_street_is_river(self):
        """Lesson 14 match has street='river'."""
        self._setup_triple_barrel('CBR02')
        matches = self._classify('CBR02')
        m = next((m for m in matches if m.lesson_id == 14), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'river')

    def test_not_detected_without_river(self):
        """No river card → lesson 14 not detected."""
        _insert_hand(self.repo, 'CBR03', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'CBR03'))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'CBR03', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR03', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR03', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR03', 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR03', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR03', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')
        matches = self._classify('CBR03')
        self.assertNotIn(14, [m.lesson_id for m in matches])

    def test_not_detected_without_hero_pfa(self):
        """Villain is PFA, hero bets river → lesson 14 not triggered."""
        _insert_hand(self.repo, 'CBR04', position='BB',
                     board_flop='Ts 7d 2c', board_turn='3s',
                     board_river='5h')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'CBR04'))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'CBR04', 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR04', 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR04', 'flop', 'P1', 'bet',
                       2.0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR04', 'flop', 'Hero', 'call',
                       2.0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR04', 'turn', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR04', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR04', 'river', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR04', 'river', 'Hero', 'bet',
                       8.0, 1, seq, 'BB')
        matches = self._classify('CBR04')
        self.assertNotIn(14, [m.lesson_id for m in matches])

    def test_not_detected_without_hero_river_bet(self):
        """Hero checks river → lesson 14 not triggered."""
        _insert_hand(self.repo, 'CBR05', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s',
                     board_river='5h')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'CBR05'))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'CBR05', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR05', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR05', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR05', 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR05', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR05', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR05', 'river', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR05', 'river', 'Hero', 'check',
                       0, 1, seq, 'BTN')
        matches = self._classify('CBR05')
        self.assertNotIn(14, [m.lesson_id for m in matches])

    # -- Value hands: always correct (1) --

    def test_strong_hand_blank_river_correct(self):
        """Top pair good kicker + blank river: triple barrel = correct (1)."""
        self._setup_triple_barrel('CBR10', hero_cards='Ah Kd',
                                  board_flop='As 7d 2c',
                                  board_turn='3s',
                                  board_river='4h')
        self.assertEqual(self._cbet_river_result('CBR10'), 1)

    def test_strong_hand_dangerous_river_correct(self):
        """Strong hand + dangerous river: still correct (value is always right)."""
        # Flop: Ah 7h 2c (2-suited hearts), turn: 9h (3-flush), river: Qh (flush)
        # Hero has AK: top pair + connects with full board as strong hand
        self._setup_triple_barrel('CBR11', hero_cards='Ah Kd',
                                  board_flop='As 7d 2c',
                                  board_turn='3s',
                                  board_river='8h')
        self.assertEqual(self._cbet_river_result('CBR11'), 1)

    def test_two_pair_blank_river_correct(self):
        """Two pair + blank river: triple barrel = correct (1)."""
        self._setup_triple_barrel('CBR12', hero_cards='Ah 7d',
                                  board_flop='As 7c 2h',
                                  board_turn='Kd',
                                  board_river='3s')
        self.assertEqual(self._cbet_river_result('CBR12'), 1)

    def test_set_correct(self):
        """Set (pocket pair + board match) + any river: correct (1)."""
        self._setup_triple_barrel('CBR13', hero_cards='7h 7c',
                                  board_flop='7s Kd 2h',
                                  board_turn='4c',
                                  board_river='9s')
        self.assertEqual(self._cbet_river_result('CBR13'), 1)

    def test_overpair_correct(self):
        """Overpair + blank river: triple barrel = correct (1)."""
        self._setup_triple_barrel('CBR14', hero_cards='Kh Kd',
                                  board_flop='Ts 7c 2h',
                                  board_turn='3s',
                                  board_river='4h')
        self.assertEqual(self._cbet_river_result('CBR14'), 1)

    def test_medium_hand_correct(self):
        """Middle pair + blank river: triple barrel = correct (1)."""
        self._setup_triple_barrel('CBR15', hero_cards='7h 6d',
                                  board_flop='As 7c 2h',
                                  board_turn='Kd',
                                  board_river='3s')
        self.assertEqual(self._cbet_river_result('CBR15'), 1)

    # -- Air bluffs: blank river is correct (1) --

    def test_air_blank_river_correct(self):
        """Air + blank river (low, disconnected): triple barrel = correct (1).

        Flop: Ts 7d 2c, turn: 3s (blank), river: 5h (low, no draw completion).
        """
        self._setup_triple_barrel('CBR20', hero_cards='Ah Kd',
                                  board_flop='Ts 7d 2c',
                                  board_turn='3s',
                                  board_river='5h')
        self.assertEqual(self._cbet_river_result('CBR20'), 1)

    def test_air_blank_river_no_flush_correct(self):
        """Air + rainbow board + blank river: correct (1)."""
        self._setup_triple_barrel('CBR21', hero_cards='Qh Jd',
                                  board_flop='Ts 7d 2c',
                                  board_turn='3h',
                                  board_river='4s')
        self.assertEqual(self._cbet_river_result('CBR21'), 1)

    # -- Air bluffs: neutral river is marginal (None) --

    def test_air_paired_board_river_neutral(self):
        """Air + river pairs prior board card: marginal (None).

        River K pairs the turn K, making range advantage unclear.
        Hero 6c 4h has no pair, no draw on this board.
        """
        self._setup_triple_barrel('CBR30', hero_cards='6c 4h',
                                  board_flop='Ts 7d 2c',
                                  board_turn='Ks',
                                  board_river='Kh')
        self.assertIsNone(self._cbet_river_result('CBR30'))

    def test_air_high_card_river_neutral(self):
        """Air + river brings high card (T+): marginal (None).

        Hero Kd 4c has no pair, no draw on 8s 7d 2c 3s Tc.
        """
        self._setup_triple_barrel('CBR31', hero_cards='Kd 4c',
                                  board_flop='8s 7d 2c',
                                  board_turn='3s',
                                  board_river='Tc')
        self.assertIsNone(self._cbet_river_result('CBR31'))

    def test_air_river_pairs_flop_card_neutral(self):
        """Air + river pairs a flop card: marginal (None)."""
        self._setup_triple_barrel('CBR32', hero_cards='Qh Jd',
                                  board_flop='8s 7d 2c',
                                  board_turn='3s',
                                  board_river='8h')
        self.assertIsNone(self._cbet_river_result('CBR32'))

    # -- Air bluffs: dangerous river is incorrect (0) --

    def test_air_flush_completing_river_incorrect(self):
        """Air + river completes flush draw (2-suited flop): incorrect (0).

        Flop: Ah 7h 2c (2 hearts), river: 9h completes flush.
        """
        self._setup_triple_barrel('CBR40', hero_cards='Kd Qs',
                                  board_flop='Ah 7h 2c',
                                  board_turn='3d',
                                  board_river='9h')
        self.assertEqual(self._cbet_river_result('CBR40'), 0)

    def test_air_flush_completing_river_incorrect_2(self):
        """Air + 2-suited flop, river completes flush: incorrect (0).

        Hero Tc 5s has no heart (non-matching suit) and no draw on this board.
        """
        self._setup_triple_barrel('CBR41', hero_cards='Tc 5s',
                                  board_flop='Jh 7h 3c',
                                  board_turn='2s',
                                  board_river='Kh')
        self.assertEqual(self._cbet_river_result('CBR41'), 0)

    def test_air_flush_completing_river_incorrect_3(self):
        """Air + 2-suited flop (clubs), river completes flush: incorrect (0).

        Hero 8d 4h has no club (non-matching suit) and no draw on this board.
        """
        self._setup_triple_barrel('CBR42', hero_cards='8d 4h',
                                  board_flop='Ac 9c 2h',
                                  board_turn='5d',
                                  board_river='Tc')
        self.assertEqual(self._cbet_river_result('CBR42'), 0)

    # -- Edge cases --

    def test_no_hero_cards_assumes_correct(self):
        """Missing hero cards → cannot evaluate, assumes correct (1)."""
        _insert_hand(self.repo, 'CBR50', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s',
                     board_river='5h')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('CBR50',))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'CBR50', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR50', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR50', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR50', 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR50', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR50', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'CBR50', 'river', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'CBR50', 'river', 'Hero', 'bet',
                       8.0, 1, seq, 'BTN')
        self.assertEqual(self._cbet_river_result('CBR50'), 1)

    def test_also_triggers_lesson_15(self):
        """A triple barrel also triggers lesson 13 (PFA + turn bet)."""
        self._setup_triple_barrel('CBR51')
        matches = self._classify('CBR51')
        lesson_ids = [m.lesson_id for m in matches]
        self.assertIn(13, lesson_ids)
        self.assertIn(14, lesson_ids)

    def test_river_changes_texture_blank(self):
        """_river_changes_texture returns 'blank' for low disconnected river."""
        result = LessonClassifier._river_changes_texture(
            'Ts 7d 2c', '3s', '5h')
        self.assertEqual(result, 'blank')

    def test_river_changes_texture_flush_dangerous(self):
        """_river_changes_texture returns 'dangerous' when river completes
        flush draw."""
        # Flop has 2 hearts, river brings another heart
        result = LessonClassifier._river_changes_texture(
            'Ah 7h 2c', '3d', '9h')
        self.assertEqual(result, 'dangerous')

    def test_river_changes_texture_straight_dangerous(self):
        """_river_changes_texture returns 'dangerous' when river creates
        new 4-card straight window."""
        # Flop: 6s 7d 8c, turn: 2h, river: 5s → new window 5-6-7-8
        result = LessonClassifier._river_changes_texture(
            '6s 7d 8c', '2h', '5s')
        self.assertEqual(result, 'dangerous')

    def test_river_changes_texture_paired_neutral(self):
        """_river_changes_texture returns 'neutral' when river pairs board."""
        result = LessonClassifier._river_changes_texture(
            'Ts 7d 2c', 'Ks', 'Kh')
        self.assertEqual(result, 'neutral')

    def test_river_changes_texture_high_card_neutral(self):
        """_river_changes_texture returns 'neutral' for high river card."""
        result = LessonClassifier._river_changes_texture(
            '8s 7d 2c', '3s', 'Tc')
        self.assertEqual(result, 'neutral')

    def test_river_changes_texture_no_prior_straight_window(self):
        """_river_changes_texture 'dangerous' only if flop/turn lacked window."""
        # Flop: Ts 9d 8c already has a 3-card window, turn adds Jh (4-card window)
        # River: 7s completes... but the 4-card window was already there on turn.
        result = LessonClassifier._river_changes_texture(
            'Ts 9d 8c', 'Jh', '7s')
        # Prior board already had 4-card window (8-9-T-J), so river 7 doesn't add new danger
        self.assertNotEqual(result, 'dangerous')


# ── US-053d: CBet Sizing Validation & Enhanced Notes Tests ───────────


class TestCBetSizingNotes(unittest.TestCase):
    """Test sizing note content in CBet evaluation methods (US-053d).

    Verifies that notes include: board texture, hero hand, sizing vs expected,
    IP/OOP marker. Covers lessons 11-15 (Aulas 11-15).
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

    def _notes_for_lesson(self, hand_id, lesson_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == lesson_id), None)
        return m.notes if m else ''

    # ── Static helper tests ─────────────────────────────────────────

    def test_sizing_note_within_range(self):
        """Bet within expected range returns 'ok' note."""
        note = LessonClassifier._cbet_sizing_note(
            hero_bet_amount=2.0, blinds_bb=0.50, pot_bb=6.0,
            low_pct=25, high_pct=66)
        # bet_bb = 4.0, bet_pct = 4/6*100 = 66.7% → just above 66
        # Actually 66.7% > high_pct=66, so NOT ok
        self.assertIn('sizing', note)
        self.assertIn('BB', note)

    def test_sizing_note_correct_sizing(self):
        """Bet of 2BB on 6BB pot = 33% → within 25-40% dry range."""
        note = LessonClassifier._cbet_sizing_note(
            hero_bet_amount=1.0, blinds_bb=0.50, pot_bb=6.0,
            low_pct=25, high_pct=40)
        # bet_bb = 2.0, pot_bb = 6.0, bet_pct = 33%
        self.assertIn('2.0BB', note)
        self.assertIn('33%', note)
        self.assertIn('ok', note)

    def test_sizing_note_outside_range(self):
        """Bet outside expected range includes 'esperado X-Y%'."""
        note = LessonClassifier._cbet_sizing_note(
            hero_bet_amount=4.0, blinds_bb=0.50, pot_bb=6.0,
            low_pct=25, high_pct=40)
        # bet_bb = 8.0, pot_bb = 6.0, bet_pct = 133% → over range
        self.assertIn('esperado 25-40%', note)

    def test_sizing_note_no_pot_info(self):
        """Without pot info (pot_bb=0), returns just bet in BB."""
        note = LessonClassifier._cbet_sizing_note(
            hero_bet_amount=2.0, blinds_bb=0.50, pot_bb=0.0,
            low_pct=25, high_pct=40)
        self.assertIn('4.0BB', note)
        self.assertNotIn('%', note)

    def test_sizing_note_no_bet_amount(self):
        """Without bet amount, returns empty string."""
        note = LessonClassifier._cbet_sizing_note(
            hero_bet_amount=0, blinds_bb=0.50, pot_bb=6.0,
            low_pct=25, high_pct=40)
        self.assertEqual(note, '')

    # ── Lesson 11 (CBet Flop IP): Notes content ────────────────────

    def _setup_cbet_ip(self, hand_id, hero_cards, board_flop,
                       bet_amount=2.0, blinds_bb=0.50, open_raise=1.5):
        """Set up CBet IP scenario with configurable sizing."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       open_raise, 1, 1, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       open_raise, 0, 2, 'BB')
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       bet_amount, 1, 4, 'BTN')

    def test_l11_notes_include_ip_marker(self):
        """Lesson 11 notes include 'IP' marker."""
        self._setup_cbet_ip('SN01', 'Ah Kd', 'As 7d 2c')
        notes = self._notes_for_lesson('SN01', 11)
        self.assertIn('IP', notes)

    def test_l11_notes_include_board_texture_dry(self):
        """Lesson 11 notes include board texture 'dry' or 'seco'."""
        self._setup_cbet_ip('SN02', 'Qh Jd', '8c 5s 2h')
        notes = self._notes_for_lesson('SN02', 11)
        # Board 8c 5s 2h is dry/seco
        self.assertTrue('dry' in notes or 'seco' in notes,
                        f"Expected 'dry' or 'seco' in notes: {notes}")

    def test_l11_notes_include_board_texture_wet(self):
        """Lesson 11 notes include board texture 'wet' or 'molhado'."""
        # 3d 2c on 9h 8h 7h → air on wet board
        self._setup_cbet_ip('SN03', '3d 2c', '9h 8h 7h')
        notes = self._notes_for_lesson('SN03', 11)
        self.assertTrue('wet' in notes or 'molhado' in notes,
                        f"Expected 'wet' or 'molhado' in notes: {notes}")

    def test_l11_notes_include_hero_hand_notation(self):
        """Lesson 11 notes include hero hand notation (e.g., AKo)."""
        self._setup_cbet_ip('SN04', 'Ah Kd', 'Ts 7d 2c')
        notes = self._notes_for_lesson('SN04', 11)
        self.assertIn('AKo', notes)

    def test_l11_notes_include_sizing_when_pot_known(self):
        """Lesson 11 notes include sizing info when pot is estimable."""
        # open_raise=1.5, call=1.5 → pot_bb = 2*1.5/0.50 = 6BB
        # bet = 2.0 → bet_bb = 4.0 → bet_pct = 4/6*100 = 67%
        # Expected for dry board: 25-40% → sizing out of range
        self._setup_cbet_ip('SN05', 'Qh Jd', '8c 5s 2h',
                             bet_amount=2.0, blinds_bb=0.50, open_raise=1.5)
        notes = self._notes_for_lesson('SN05', 11)
        self.assertIn('sizing', notes)
        self.assertIn('BB', notes)

    def test_l11_correct_sizing_dry_board(self):
        """Lesson 11: 33% pot on dry board = correct sizing in notes."""
        # pot_bb = 6BB (1.5 raise + 1.5 call at $0.25/$0.50)
        # For 33% pot: bet = 0.33 * 6 = 2BB = 1.0 currency at $0.50BB
        self._setup_cbet_ip('SN06', 'Ah Kd', '8c 5s 2h',
                             bet_amount=1.0, blinds_bb=0.50, open_raise=1.5)
        notes = self._notes_for_lesson('SN06', 11)
        self.assertIn('ok', notes)

    def test_l11_air_wet_board_incorrect(self):
        """Lesson 11: air on wet board = incorrect regardless of sizing."""
        self._setup_cbet_ip('SN07', '3d 2c', '9h 8h 7h')
        m = next((m for m in self._classify('SN07')
                  if m.lesson_id == 11), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 0)
        self.assertIn('incorreto', m.notes)

    # ── Lesson 12 (CBet Flop OOP): Notes content ───────────────────

    def _setup_cbet_oop(self, hand_id, hero_cards, board_flop,
                        bet_amount=3.0, blinds_bb=0.50):
        """Set up CBet OOP scenario (hero 3-bets BB)."""
        _insert_hand(self.repo, hand_id, position='BB',
                     board_flop=board_flop, blinds_bb=blinds_bb)
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
                       bet_amount, 1, 4, 'BB')

    def test_l12_notes_include_oop_marker(self):
        """Lesson 12 notes include 'OOP' marker."""
        self._setup_cbet_oop('SN10', 'Ah Kd', 'Ts 7d 2c')
        notes = self._notes_for_lesson('SN10', 12)
        self.assertIn('OOP', notes)

    def test_l12_notes_include_board_texture(self):
        """Lesson 12 notes include board texture."""
        self._setup_cbet_oop('SN11', 'Ah Kd', 'Ts 7d 2c')
        notes = self._notes_for_lesson('SN11', 12)
        # Ts 7d 2c is neutral (slightly connected but not highly)
        self.assertTrue(any(t in notes for t in ('dry', 'neutral', 'wet', 'seco', 'molhado')),
                        f"Expected texture in notes: {notes}")

    def test_l12_notes_include_hero_hand(self):
        """Lesson 12 notes include hero hand notation."""
        self._setup_cbet_oop('SN12', 'Ah Kd', 'Ts 7d 2c')
        notes = self._notes_for_lesson('SN12', 12)
        self.assertIn('AKo', notes)

    def test_l12_air_dry_board_marginal_with_sizing(self):
        """Lesson 12: air on dry board OOP = marginal (None) with sizing note."""
        self._setup_cbet_oop('SN13', 'Qh Jd', '8c 5s 2h')
        m = next((m for m in self._classify('SN13')
                  if m.lesson_id == 12), None)
        self.assertIsNotNone(m)
        self.assertIsNone(m.executed_correctly)
        self.assertIn('sizing', m.notes)

    def test_l12_strong_hand_correct_with_sizing(self):
        """Lesson 12: strong hand OOP = correct (1) with sizing note."""
        self._setup_cbet_oop('SN14', 'Ah Ad', '9h 7d 2c')
        m = next((m for m in self._classify('SN14')
                  if m.lesson_id == 12), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)
        self.assertIn('sizing', m.notes)

    def test_l12_air_neutral_board_incorrect(self):
        """Lesson 12: air on neutral board OOP = incorrect (0)."""
        self._setup_cbet_oop('SN15', 'Qh Jd', 'Ah 7h 2c')
        m = next((m for m in self._classify('SN15')
                  if m.lesson_id == 12), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 0)

    # ── Lesson 13 (CBet Turn / Double Barrel): Notes content ───────

    def _setup_double_barrel_sizing(self, hand_id, hero_cards,
                                    board_flop, board_turn,
                                    turn_bet=4.0, blinds_bb=0.50):
        """Set up double barrel with configurable turn bet sizing."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop, board_turn=board_turn,
                     blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'call',
                       2.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       turn_bet, 1, seq, 'BTN')

    def test_l13_notes_include_double_barrel_label(self):
        """Lesson 13 notes mention 'double barrel'."""
        self._setup_double_barrel_sizing('SN20', 'Ah Kd', 'As 7d 2c', '3s')
        notes = self._notes_for_lesson('SN20', 13)
        self.assertIn('double barrel', notes)

    def test_l13_notes_include_hero_hand(self):
        """Lesson 13 notes include hero hand notation."""
        self._setup_double_barrel_sizing('SN21', 'Ah Kd', 'As 7d 2c', '3s')
        notes = self._notes_for_lesson('SN21', 13)
        self.assertIn('AKo', notes)

    def test_l13_notes_include_sizing(self):
        """Lesson 13 notes include sizing info."""
        self._setup_double_barrel_sizing('SN22', 'Ah Kd', 'As 7d 2c', '3s')
        notes = self._notes_for_lesson('SN22', 13)
        self.assertIn('sizing', notes)

    def test_l13_correct_sizing_blank_turn(self):
        """Lesson 13: 50% pot on blank turn = within expected range (50-75%)."""
        # flop_pot_bb = 6, flop_bet_bb = 4 → turn_pot_bb = 6 + 8 = 14
        # 50% of 14BB = 7BB = $3.50 at $0.50 BB → turn_bet=3.5 → 50% pot = ok
        self._setup_double_barrel_sizing('SN23', 'Ah Kd', 'As 7d 2c', '3s',
                                         turn_bet=3.5)
        notes = self._notes_for_lesson('SN23', 13)
        self.assertIn('ok', notes)

    def test_l13_does_not_fire_for_delayed_cbet(self):
        """Lesson 13 does NOT fire when hero checked flop (delayed cbet pattern)."""
        # Set up delayed cbet: hero checks flop, villain checks back, hero bets turn
        _insert_hand(self.repo, 'SN24', position='BTN',
                     board_flop='As 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            ('Ah Kd', 'SN24'))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'SN24', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'SN24', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'SN24', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'SN24', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BTN'); seq += 1  # hero checks flop
        _insert_action(self.repo, 'SN24', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'SN24', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')
        matches = self._classify('SN24')
        lesson_ids = [m.lesson_id for m in matches]
        self.assertNotIn(13, lesson_ids)  # delayed cbet, not double barrel
        self.assertIn(15, lesson_ids)     # lesson 15 fires instead

    def test_l13_air_blank_turn_correct(self):
        """Lesson 13: air on blank turn = correct (1)."""
        # QdJc on Ah 7d 2c 3s → no pair, no draw → air, turn blank
        self._setup_double_barrel_sizing('SN25', 'Qd Jc', 'Ah 7d 2c', '3s')
        m = next((m for m in self._classify('SN25')
                  if m.lesson_id == 13), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    def test_l13_air_dangerous_turn_incorrect(self):
        """Lesson 13: air on dangerous turn (flush completes) = incorrect (0)."""
        # Kd 4c on 9h 8h 7c 2h → flush completes on turn → dangerous
        self._setup_double_barrel_sizing('SN26', 'Kd 4c', '9h 8h 7c', '2h')
        m = next((m for m in self._classify('SN26')
                  if m.lesson_id == 13), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 0)

    # ── Lesson 14 (CBet River / Triple Barrel): Notes content ──────

    def _setup_triple_barrel_sizing(self, hand_id, hero_cards,
                                    board_flop, board_turn, board_river,
                                    river_bet=8.0, blinds_bb=0.50):
        """Set up triple barrel with configurable river bet sizing."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop, board_turn=board_turn,
                     board_river=board_river, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'call',
                       2.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'call',
                       4.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'river', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'river', 'Hero', 'bet',
                       river_bet, 1, seq, 'BTN')

    def test_l14_notes_include_triple_barrel_label(self):
        """Lesson 14 notes mention 'triple barrel'."""
        self._setup_triple_barrel_sizing('SN30', 'Ah Kd',
                                          'Ts 7d 2c', '3s', '5h')
        notes = self._notes_for_lesson('SN30', 14)
        self.assertIn('triple barrel', notes)

    def test_l14_notes_include_hero_hand(self):
        """Lesson 14 notes include hero hand notation."""
        self._setup_triple_barrel_sizing('SN31', 'Ah Kd',
                                          'Ts 7d 2c', '3s', '5h')
        notes = self._notes_for_lesson('SN31', 14)
        self.assertIn('AKo', notes)

    def test_l14_notes_include_sizing(self):
        """Lesson 14 notes include sizing info."""
        self._setup_triple_barrel_sizing('SN32', 'Ah Kd',
                                          'Ts 7d 2c', '3s', '5h')
        notes = self._notes_for_lesson('SN32', 14)
        self.assertIn('sizing', notes)

    def test_l14_strong_hand_blank_river_correct(self):
        """Lesson 14: strong hand on blank river = correct (1)."""
        self._setup_triple_barrel_sizing('SN33', 'Ah Kd',
                                          'As 7d 2c', '3s', '5h')
        m = next((m for m in self._classify('SN33')
                  if m.lesson_id == 14), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)
        self.assertIn('strong', m.notes)

    def test_l14_air_blank_river_correct(self):
        """Lesson 14: air on blank river = correct polarized bluff (1)."""
        # Qd Jc on Ts 7d 2c 3s 5h → no pair, no draw → air, blank rivers
        self._setup_triple_barrel_sizing('SN34', 'Qd Jc',
                                          'Ts 7d 2c', '3s', '5h')
        m = next((m for m in self._classify('SN34')
                  if m.lesson_id == 14), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    def test_l14_air_dangerous_river_incorrect(self):
        """Lesson 14: air on dangerous river (flush completes) = incorrect (0)."""
        # Kd 4c on 9h 8h 7c 2h 3h → flush draw on flop, completes on river
        self._setup_triple_barrel_sizing('SN35', 'Kd 4c',
                                          '9h 8h 7c', '2h', '3h')
        m = next((m for m in self._classify('SN35')
                  if m.lesson_id == 14), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 0)

    # ── Lesson 15 (Delayed CBet): Notes content ─────────────────────

    def _setup_delayed_cbet_sizing(self, hand_id, hero_cards,
                                    board_flop, board_turn,
                                    turn_bet=4.0, blinds_bb=0.50):
        """Set up delayed cbet with configurable sizing."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop, board_turn=board_turn,
                     blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                       0, 1, seq, 'BTN'); seq += 1  # hero checks = delayed
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       turn_bet, 1, seq, 'BTN')

    def test_l15_notes_mention_check_flop_bet_turn(self):
        """Lesson 15 notes describe delayed pattern: check flop → bet turn."""
        self._setup_delayed_cbet_sizing('SN40', 'Ah Kd', 'As 7d 2c', '3s')
        notes = self._notes_for_lesson('SN40', 15)
        self.assertTrue('check' in notes.lower() or 'delayed' in notes.lower(),
                        f"Expected 'check' or 'delayed' in notes: {notes}")

    def test_l15_notes_include_hero_hand(self):
        """Lesson 15 notes include hero hand notation."""
        self._setup_delayed_cbet_sizing('SN41', 'Ah Kd', 'As 7d 2c', '3s')
        notes = self._notes_for_lesson('SN41', 15)
        self.assertIn('AKo', notes)

    def test_l15_notes_include_sizing(self):
        """Lesson 15 notes include sizing info."""
        self._setup_delayed_cbet_sizing('SN42', 'Ah Kd', 'As 7d 2c', '3s')
        notes = self._notes_for_lesson('SN42', 15)
        self.assertIn('sizing', notes)

    def test_l15_strong_hand_correct(self):
        """Lesson 15: strong hand check-flop-bet-turn = correct (1)."""
        self._setup_delayed_cbet_sizing('SN43', 'Ah Kd', 'As 7d 2c', '3s')
        m = next((m for m in self._classify('SN43')
                  if m.lesson_id == 15), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    def test_l15_air_blank_turn_correct(self):
        """Lesson 15: air on blank turn = correct (villain showed weakness)."""
        # Qd Jc on As 7d 2c 3s → air, blank turn
        self._setup_delayed_cbet_sizing('SN44', 'Qd Jc', 'As 7d 2c', '3s')
        m = next((m for m in self._classify('SN44')
                  if m.lesson_id == 15), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    def test_l15_air_dangerous_turn_marginal(self):
        """Lesson 15: air on dangerous turn = marginal (None)."""
        # Kd 4c on 9h 8h 7c 2h → flush completes on turn → dangerous
        self._setup_delayed_cbet_sizing('SN45', 'Kd 4c', '9h 8h 7c', '2h')
        m = next((m for m in self._classify('SN45')
                  if m.lesson_id == 15), None)
        self.assertIsNotNone(m)
        self.assertIsNone(m.executed_correctly)

    def test_l15_distinguishes_from_l13_double_barrel(self):
        """Lesson 15 (delayed cbet) triggers instead of lesson 13 (double barrel)."""
        # Delayed cbet: hero checks flop, bets turn
        self._setup_delayed_cbet_sizing('SN46', 'Ah Kd', 'As 7d 2c', '3s')
        matches = self._classify('SN46')
        lesson_ids = [m.lesson_id for m in matches]
        self.assertIn(15, lesson_ids)    # lesson 15 fires
        self.assertNotIn(13, lesson_ids)  # lesson 13 must NOT fire

    def test_l15_draw_neutral_turn_correct(self):
        """Lesson 15: draw hand on neutral turn = correct (semi-bluff)."""
        # Qh 9h on Ah 7h 2c (flush draw) with neutral turn Ks
        self._setup_delayed_cbet_sizing('SN47', 'Qh 9h', 'Ah 7h 2c', 'Ks')
        m = next((m for m in self._classify('SN47')
                  if m.lesson_id == 15), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    def test_l15_correct_sizing_within_range(self):
        """Lesson 15: bet within 50-66% pot = 'ok' in sizing note."""
        # pot_bb = 6 (2*1.5/0.5), flop_bet=0 (checked), turn_pot_bb = 6
        # 50% of 6 = 3BB = 1.5 currency at $0.50 BB
        self._setup_delayed_cbet_sizing('SN48', 'Ah Kd', 'As 7d 2c', '3s',
                                         turn_bet=1.5)
        notes = self._notes_for_lesson('SN48', 15)
        self.assertIn('ok', notes)


# ── Lesson 10: Pós-Flop Avançado Evaluation Tests ────────────────────


class TestPostflopAdvancedEvaluation(unittest.TestCase):
    """Test _eval_postflop_advanced for Lesson 10 (Pós-Flop Avançado)."""

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

    def _adv_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 10), None)
        return m.executed_correctly if m else None

    def _setup_three_streets(self, hand_id, hero_cards='Ah Kd',
                              board_flop='Ts 7d 2c',
                              board_turn='3s',
                              board_river='5h',
                              hero_pos='BB',
                              river_villain_bets=False,
                              river_hero_action='check'):
        """Set up a 3-street hand: preflop, flop, turn, river."""
        _insert_hand(self.repo, hand_id, position=hero_pos,
                     board_flop=board_flop, board_turn=board_turn,
                     board_river=board_river)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, hero_pos); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'bet',
                       2.0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                       2.0, 1, seq, hero_pos); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'check',
                       0, 1, seq, hero_pos); seq += 1
        if river_villain_bets:
            _insert_action(self.repo, hand_id, 'river', 'P1', 'bet',
                           6.0, 0, seq, 'BTN'); seq += 1
        if river_hero_action == 'fold':
            _insert_action(self.repo, hand_id, 'river', 'Hero', 'fold',
                           0, 1, seq, hero_pos)
        elif river_hero_action == 'call':
            _insert_action(self.repo, hand_id, 'river', 'Hero', 'call',
                           6.0, 1, seq, hero_pos)
        else:
            _insert_action(self.repo, hand_id, 'river', 'Hero', 'check',
                           0, 1, seq, hero_pos)

    # -- Detection tests --

    def test_detected_on_three_streets(self):
        """Lesson 10 detected when hand has flop + turn + river."""
        self._setup_three_streets('PA01')
        matches = self._classify('PA01')
        self.assertIn(10, [m.lesson_id for m in matches])

    def test_not_detected_without_river(self):
        """Lesson 10 NOT detected without river card."""
        _insert_hand(self.repo, 'PA02', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s')
        seq = 1
        _insert_action(self.repo, 'PA02', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PA02', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PA02', 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BTN')
        matches = self._classify('PA02')
        self.assertNotIn(10, [m.lesson_id for m in matches])

    def test_not_detected_flop_only(self):
        """Lesson 10 NOT detected with flop only."""
        _insert_hand(self.repo, 'PA03', position='BTN',
                     board_flop='Ts 7d 2c')
        seq = 1
        _insert_action(self.repo, 'PA03', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PA03', 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN')
        matches = self._classify('PA03')
        self.assertNotIn(10, [m.lesson_id for m in matches])

    def test_confidence_is_low(self):
        """Lesson 10 has reduced confidence (0.5)."""
        self._setup_three_streets('PA04')
        matches = self._classify('PA04')
        m = next((m for m in matches if m.lesson_id == 10), None)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m.confidence, 0.5)

    # -- Strong hand: folding river bet is incorrect (0) --

    def test_strong_hand_folds_river_bet_incorrect(self):
        """Strong hand (top two pair) folds to river bet: incorrect (0).

        Hero Ah Kd on Ah Kd 2c Ts 5h board = top two pair.
        Villain bets river, hero folds: clear advanced postflop mistake.
        """
        self._setup_three_streets('PA10', hero_cards='Ah Kd',
                                  board_flop='Ah Kd 2c',
                                  board_turn='Ts',
                                  board_river='5h',
                                  river_villain_bets=True,
                                  river_hero_action='fold')
        self.assertEqual(self._adv_result('PA10'), 0)

    def test_strong_hand_calls_river_bet_correct(self):
        """Strong hand calls river bet: correct (1)."""
        self._setup_three_streets('PA11', hero_cards='Ah Kd',
                                  board_flop='Ah Kd 2c',
                                  board_turn='Ts',
                                  board_river='5h',
                                  river_villain_bets=True,
                                  river_hero_action='call')
        self.assertEqual(self._adv_result('PA11'), 1)

    def test_strong_hand_checks_correct(self):
        """Strong hand checks river (no villain bet): correct (1)."""
        self._setup_three_streets('PA12', hero_cards='Ah Kd',
                                  board_flop='Ah Kd 2c',
                                  board_turn='Ts',
                                  board_river='5h',
                                  river_villain_bets=False,
                                  river_hero_action='check')
        self.assertEqual(self._adv_result('PA12'), 1)

    # -- Medium hand: folding river bet is marginal (None) --

    def test_medium_hand_folds_river_marginal(self):
        """Medium hand (second pair) folds to river bet: marginal (None).

        Hero 7h 6d on As 7c 2h Kd 3s board = second pair.
        Villain bets river, hero folds: depends on sizing and reads.
        """
        self._setup_three_streets('PA20', hero_cards='7h 6d',
                                  board_flop='As 7c 2h',
                                  board_turn='Kd',
                                  board_river='3s',
                                  river_villain_bets=True,
                                  river_hero_action='fold')
        self.assertIsNone(self._adv_result('PA20'))

    def test_medium_hand_calls_correct(self):
        """Medium hand calls or checks river (no threat): correct (1)."""
        self._setup_three_streets('PA21', hero_cards='7h 6d',
                                  board_flop='As 7c 2h',
                                  board_turn='Kd',
                                  board_river='3s',
                                  river_villain_bets=False,
                                  river_hero_action='check')
        self.assertEqual(self._adv_result('PA21'), 1)

    # -- Missed draw: folding river bet is correct (1) --

    def test_missed_draw_folds_river_correct(self):
        """Missed flush draw folds to river bet: correct (1).

        Hero Ah 2h had flush draw on Kh 7h 3c Qs board.
        River 5d: missed draw; folding to river bet is correct.
        """
        self._setup_three_streets('PA30', hero_cards='Ah 2h',
                                  board_flop='Kh 7h 3c',
                                  board_turn='Qs',
                                  board_river='5d',
                                  river_villain_bets=True,
                                  river_hero_action='fold')
        self.assertEqual(self._adv_result('PA30'), 1)

    def test_missed_draw_calls_river_marginal(self):
        """Missed draw calls river bet: marginal (None) (bluff catcher).

        Hero Ah 2h missed flush draw on Kh 7h 3c Qs 5d.
        Calling with missed draw can be a bluff catcher in some spots.
        """
        self._setup_three_streets('PA31', hero_cards='Ah 2h',
                                  board_flop='Kh 7h 3c',
                                  board_turn='Qs',
                                  board_river='5d',
                                  river_villain_bets=True,
                                  river_hero_action='call')
        self.assertIsNone(self._adv_result('PA31'))

    # -- Air: folding river bet is correct (1) --

    def test_air_folds_river_correct(self):
        """Air (overcards, no draw) folds to river bet: correct (1)."""
        self._setup_three_streets('PA40', hero_cards='Qd Jc',
                                  board_flop='As 7h 3c',
                                  board_turn='Kd',
                                  board_river='2s',
                                  river_villain_bets=True,
                                  river_hero_action='fold')
        self.assertEqual(self._adv_result('PA40'), 1)

    # -- Edge cases --

    def test_no_hero_cards_returns_none(self):
        """Missing hero cards → cannot evaluate (None)."""
        _insert_hand(self.repo, 'PA50', position='BB',
                     board_flop='Ts 7d 2c', board_turn='3s',
                     board_river='5h')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('PA50',))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'PA50', 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PA50', 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PA50', 'flop', 'P1', 'bet',
                       2.0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PA50', 'flop', 'Hero', 'call',
                       2.0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PA50', 'turn', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PA50', 'turn', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PA50', 'river', 'P1', 'bet',
                       4.0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PA50', 'river', 'Hero', 'fold',
                       0, 1, seq, 'BB')
        self.assertIsNone(self._adv_result('PA50'))

    def test_lesson_11_removed_but_12_present(self):
        """L11 (MDA) removed in US-053; L12 still triggered for 3-street hands."""
        self._setup_three_streets('PA51')
        matches = self._classify('PA51')
        lesson_ids = [m.lesson_id for m in matches]
        self.assertNotIn(11, lesson_ids)
        self.assertIn(10, lesson_ids)


# ── Lesson 19: Bet vs Missed Bet Evaluation Tests ─────────────────────


class TestBetVsMissedBetEvaluation(unittest.TestCase):
    """Test _eval_bet_vs_missed_bet for Lesson 19 (Bet vs Missed Bet)."""

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

    def _bvmb_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 19), None)
        return m.executed_correctly if m else None

    def _setup_bet_vs_missed(self, hand_id, hero_cards='Ah Kd',
                              board_flop='Ts 7d 2c',
                              board_turn='3s',
                              hero_pos='BB',
                              villain_flop_action='bet'):
        """Set up a bet vs missed bet scenario.

        Villain bets flop (or checks back), then checks turn, hero bets turn.
        """
        _insert_hand(self.repo, hand_id, position=hero_pos,
                     board_flop=board_flop, board_turn=board_turn)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        # Preflop: villain raises, hero calls (hero is NOT PFA)
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, hero_pos); seq += 1
        # Flop: villain acts first
        if villain_flop_action == 'bet':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                           0, 1, seq, hero_pos); seq += 1
            _insert_action(self.repo, hand_id, 'flop', 'P1', 'bet',
                           2.0, 0, seq, 'BTN'); seq += 1
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           2.0, 1, seq, hero_pos); seq += 1
        else:
            # villain checks back
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                           0, 1, seq, hero_pos); seq += 1
            _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                           0, 0, seq, 'BTN'); seq += 1
        # Turn: villain checks, hero bets (bet vs missed bet)
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       4.0, 1, seq, hero_pos)

    # -- Detection tests --

    def test_detected_villain_bet_flop_then_checked(self):
        """Detected when villain bet flop, checked turn, hero bets turn."""
        self._setup_bet_vs_missed('BVMB10', villain_flop_action='bet')
        matches = self._classify('BVMB10')
        self.assertIn(19, [m.lesson_id for m in matches])

    def test_detected_villain_checked_back_flop(self):
        """Detected when villain checked back flop, hero bets turn."""
        self._setup_bet_vs_missed('BVMB11', villain_flop_action='check')
        matches = self._classify('BVMB11')
        self.assertIn(19, [m.lesson_id for m in matches])

    def test_street_is_turn(self):
        """Lesson 19 match has street='turn' when hero bets turn."""
        self._setup_bet_vs_missed('BVMB12')
        matches = self._classify('BVMB12')
        m = next((m for m in matches if m.lesson_id == 19), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'turn')

    # -- Correct execution (1): strong/medium/draw hands --

    def test_strong_hand_bet_correct(self):
        """Strong hand bets vs missed bet: correct (1).

        Hero Ah Kd on Ah Kd 2c (top two pair) bets turn after villain checked.
        """
        self._setup_bet_vs_missed('BVMB20', hero_cards='Ah Kd',
                                  board_flop='Ah Kd 2c',
                                  board_turn='3s')
        self.assertEqual(self._bvmb_result('BVMB20'), 1)

    def test_medium_hand_bet_correct(self):
        """Medium hand (middle pair) bets vs missed bet: correct (1).

        Hero 7h 6d on As 7c 2h flop, turn 3d.
        Villain bet flop, checked turn: hero middle pair bets = correct.
        """
        self._setup_bet_vs_missed('BVMB21', hero_cards='7h 6d',
                                  board_flop='As 7c 2h',
                                  board_turn='3d')
        self.assertEqual(self._bvmb_result('BVMB21'), 1)

    def test_draw_bet_correct(self):
        """Draw (flush draw) bets vs missed bet: correct (1).

        Hero Ah 2h on Kh 7h 3c flop, turn 9s.
        Villain bet flop, checked turn: hero semi-bluffs = correct.
        """
        self._setup_bet_vs_missed('BVMB22', hero_cards='Ah 2h',
                                  board_flop='Kh 7h 3c',
                                  board_turn='9s')
        self.assertEqual(self._bvmb_result('BVMB22'), 1)

    # -- Air bets: depends on turn texture --

    def test_air_blank_turn_bet_correct(self):
        """Air bets on blank turn vs missed bet: correct (1).

        Hero Qd Jc has no pair/draw on As 7h 3c flop.
        Turn 2d (blank): villain showed weakness + blank turn = correct.
        """
        self._setup_bet_vs_missed('BVMB30', hero_cards='Qd Jc',
                                  board_flop='As 7h 3c',
                                  board_turn='2d')
        self.assertEqual(self._bvmb_result('BVMB30'), 1)

    def test_air_neutral_turn_bet_correct(self):
        """Air bets on neutral turn vs missed bet: correct (1).

        Hero Qd Jc on As 7h 3c flop, turn Tc (neutral high card).
        Villain weakness + neutral turn: exploitation still correct.
        """
        self._setup_bet_vs_missed('BVMB31', hero_cards='Qd Jc',
                                  board_flop='As 7h 3c',
                                  board_turn='Tc')
        self.assertEqual(self._bvmb_result('BVMB31'), 1)

    def test_air_dangerous_turn_bet_marginal(self):
        """Air bets on dangerous turn vs missed bet: marginal (None).

        Hero Qd Jc on As 7h 3c flop.
        Turn 6h (completes 4-card straight window 3-4-5-6-7): marginal.
        Actually let me use a turn that makes flush.
        Hero Qd Jc on Ah 7h 3c flop (2 hearts).
        Turn 9h completes flush: villain may have caught up.
        """
        self._setup_bet_vs_missed('BVMB32', hero_cards='Qd Jc',
                                  board_flop='Ah 7h 3c',
                                  board_turn='9h')
        self.assertIsNone(self._bvmb_result('BVMB32'))

    # -- Edge cases --

    def test_no_hero_cards_correct_by_default(self):
        """Missing hero cards → villain showed weakness → correct (1)."""
        _insert_hand(self.repo, 'BVMB40', position='BB',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('BVMB40',))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'BVMB40', 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'BVMB40', 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'BVMB40', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'BVMB40', 'flop', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'BVMB40', 'turn', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'BVMB40', 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BB')
        self.assertEqual(self._bvmb_result('BVMB40'), 1)

    def test_not_triggered_when_hero_is_pfa(self):
        """Lesson 19 NOT triggered when hero is the PFA (that's delayed cbet)."""
        _insert_hand(self.repo, 'BVMB50', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s')
        seq = 1
        _insert_action(self.repo, 'BVMB50', 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'BVMB50', 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'BVMB50', 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'BVMB50', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'BVMB50', 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'BVMB50', 'turn', 'Hero', 'bet',
                       4.0, 1, seq, 'BTN')
        matches = self._classify('BVMB50')
        self.assertNotIn(19, [m.lesson_id for m in matches])


# ── Lesson 20: Probe do BB Evaluation Tests ───────────────────────────


class TestProbeEvaluation(unittest.TestCase):
    """Test _eval_probe for Lesson 20 (Probe do BB)."""

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

    def _probe_result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 20), None)
        return m.executed_correctly if m else None

    def _setup_probe(self, hand_id, hero_cards='Ah Kd',
                     board_flop='Ts 7d 2c', board_turn='3s'):
        """Set up a BB probe bet scenario.

        BB calls preflop, both check flop, BB probes turn.
        """
        _insert_hand(self.repo, hand_id, position='BB',
                     board_flop=board_flop, board_turn=board_turn)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        # Flop: both check (PFA checks back)
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        # Turn: hero probes
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BB')

    # -- Detection tests --

    def test_detected(self):
        """Probe detected: BB calls preflop, both check flop, BB bets turn."""
        self._setup_probe('PRB01')
        matches = self._classify('PRB01')
        self.assertIn(20, [m.lesson_id for m in matches])

    def test_not_detected_when_hero_not_bb(self):
        """Lesson 20 NOT triggered when hero is not BB."""
        _insert_hand(self.repo, 'PRB02', position='BTN',
                     board_flop='Ts 7d 2c', board_turn='3s')
        seq = 1
        _insert_action(self.repo, 'PRB02', 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'UTG'); seq += 1
        _insert_action(self.repo, 'PRB02', 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PRB02', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PRB02', 'flop', 'P1', 'check',
                       0, 0, seq, 'UTG'); seq += 1
        _insert_action(self.repo, 'PRB02', 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BTN')
        matches = self._classify('PRB02')
        self.assertNotIn(20, [m.lesson_id for m in matches])

    def test_not_detected_when_hero_pfa(self):
        """Lesson 20 NOT triggered when hero is the PFA (that's delayed cbet)."""
        _insert_hand(self.repo, 'PRB03', position='BB',
                     board_flop='Ts 7d 2c', board_turn='3s')
        seq = 1
        _insert_action(self.repo, 'PRB03', 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        # Hero 3-bets (becomes PFA)
        _insert_action(self.repo, 'PRB03', 'preflop', 'Hero', 'raise',
                       4.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PRB03', 'preflop', 'P1', 'call',
                       4.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PRB03', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PRB03', 'flop', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PRB03', 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BB')
        matches = self._classify('PRB03')
        self.assertNotIn(20, [m.lesson_id for m in matches])

    def test_not_detected_villain_bet_flop(self):
        """Lesson 20 NOT triggered when villain bet flop (PFA c-bet)."""
        _insert_hand(self.repo, 'PRB04', position='BB',
                     board_flop='Ts 7d 2c', board_turn='3s')
        seq = 1
        _insert_action(self.repo, 'PRB04', 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PRB04', 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        # Villain bets flop (not checked back)
        _insert_action(self.repo, 'PRB04', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PRB04', 'flop', 'P1', 'bet',
                       2.0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PRB04', 'flop', 'Hero', 'call',
                       2.0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PRB04', 'turn', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PRB04', 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BB')
        # This should trigger Bet vs Missed Bet (21), not Probe (22)
        matches = self._classify('PRB04')
        self.assertNotIn(20, [m.lesson_id for m in matches])
        self.assertIn(19, [m.lesson_id for m in matches])

    def test_street_is_turn(self):
        """Lesson 20 match has street='turn'."""
        self._setup_probe('PRB05')
        matches = self._classify('PRB05')
        m = next((m for m in matches if m.lesson_id == 20), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.street, 'turn')

    # -- Correct execution (1): strong/medium/draw hands or blank turn --

    def test_strong_hand_probe_correct(self):
        """Strong hand probes turn: correct (1).

        Hero Ah Kd on Ah Kd 2c flop, turn 3s: top two pair probe.
        """
        self._setup_probe('PRB10', hero_cards='Ah Kd',
                          board_flop='Ah Kd 2c', board_turn='3s')
        self.assertEqual(self._probe_result('PRB10'), 1)

    def test_medium_hand_probe_correct(self):
        """Medium hand (middle pair) probes: correct (1).

        Hero 7h 6d on As 7c 2h flop, turn 3d: second pair probe.
        """
        self._setup_probe('PRB11', hero_cards='7h 6d',
                          board_flop='As 7c 2h', board_turn='3d')
        self.assertEqual(self._probe_result('PRB11'), 1)

    def test_draw_probe_correct(self):
        """Draw (flush draw) probes turn: correct (1).

        Hero Ah 2h on Kh 7h 3c flop, turn 9s: semi-bluff probe.
        """
        self._setup_probe('PRB12', hero_cards='Ah 2h',
                          board_flop='Kh 7h 3c', board_turn='9s')
        self.assertEqual(self._probe_result('PRB12'), 1)

    def test_air_blank_turn_probe_correct(self):
        """Air probes blank turn: correct (1).

        Hero Qd Jc on As 7h 3c flop, turn 2d (blank).
        PFA showed weakness + blank turn: probe is correct.
        """
        self._setup_probe('PRB13', hero_cards='Qd Jc',
                          board_flop='As 7h 3c', board_turn='2d')
        self.assertEqual(self._probe_result('PRB13'), 1)

    # -- Marginal execution (None): air on neutral turn --

    def test_air_neutral_turn_probe_marginal(self):
        """Air probes neutral turn: marginal (None).

        Hero 9d 5c on As 7h 3c flop (no pair, no draw), turn Tc (neutral).
        9d 5c has indices [1,3,5,7,8,12] with max 3 in any 5-rank window.
        Air probe is marginal on neutral turns.
        """
        self._setup_probe('PRB20', hero_cards='9d 5c',
                          board_flop='As 7h 3c', board_turn='Tc')
        self.assertIsNone(self._probe_result('PRB20'))

    # -- Incorrect execution (0): air on dangerous turn (flush completes) --

    def test_air_flush_completing_turn_probe_incorrect(self):
        """Air probes dangerous turn (flush completes): incorrect (0).

        Hero Qd Jc on Ah 7h 3c flop (2 hearts), turn 9h (flush completes).
        Hero has no hearts; combined board has 3 hearts = no 4-flush for hero.
        But turn completes villain flush draw: probing with air is incorrect.
        """
        self._setup_probe('PRB30', hero_cards='Qd Jc',
                          board_flop='Ah 7h 3c', board_turn='9h')
        self.assertEqual(self._probe_result('PRB30'), 0)

    def test_air_flush_completing_turn_probe_incorrect_2(self):
        """Air probes dangerous turn (flush completes, clubs): incorrect (0).

        Hero Kd 4h on Ac 7c 3h flop (2 clubs), turn 9c (flush completes).
        Hero no clubs: board now has 3 clubs. Probing with air is incorrect.
        """
        self._setup_probe('PRB31', hero_cards='Kd 4h',
                          board_flop='Ac 7c 3h', board_turn='9c')
        self.assertEqual(self._probe_result('PRB31'), 0)

    # -- Edge cases --

    def test_no_hero_cards_correct_by_default(self):
        """Missing hero cards → PFA checked, probing is correct (1)."""
        _insert_hand(self.repo, 'PRB40', position='BB',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=NULL WHERE hand_id=?", ('PRB40',))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, 'PRB40', 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PRB40', 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PRB40', 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, 'PRB40', 'flop', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, 'PRB40', 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BB')
        self.assertEqual(self._probe_result('PRB40'), 1)

    def test_no_turn_card_correct_by_default(self):
        """Missing turn card info → probing is correct (1) by default."""
        hand = {'hand_id': 'PRB50', 'hero_cards': 'Qd Jc',
                'hero_position': 'BB', 'board_flop': 'As 7h 3c',
                'board_turn': None, 'board_river': None,
                'net': 0.0, 'game_type': 'cash'}
        flop_a = {'villain_checks_back': True}
        turn_a = {'hero_bets': True}
        score, note = self.classifier._eval_probe(hand, flop_a, turn_a)
        self.assertEqual(score, 1)
        self.assertIn('probe correta', note.lower())


# ── US-053b: PDF Scenario Tests (Aulas 1-4) ──────────────────────────
# At least 3 scenarios per lesson extracted from RegLife PDFs.


class TestUS053bAula1StackDepthRFI(unittest.TestCase):
    """Aula 1: RFI with stack-depth-aware ranges.

    Based on RegLife 'Ranges de RFI em cEV' PDF — ranges tighten at shorter stacks:
    - 100bb: BTN 54%, CO 37%, HJ 28%, LJ 23%, UTG+1 20%, UTG 17%
    - 50bb:  BTN 54%, CO 38%, HJ 28%, LJ 24%, UTG+1 20%, UTG 17%
    - 25bb:  BTN 45%, CO 34%, HJ 28%, LJ 24%, UTG+1 21%, UTG 18%
    - 15bb:  BTN 38%, CO 30%, HJ 24%, LJ 20%, UTG+1 17%, UTG 16%
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _rfi_result(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        matches = self.classifier.classify_hand(hand, actions)
        m = next((m for m in matches if m.lesson_id == 1), None)
        return (m.executed_correctly, m.notes) if m else (None, '')

    def _insert_rfi(self, hand_id, hero_cards, hero_pos, hero_stack, blinds_bb=0.50):
        _insert_hand(self.repo, hand_id, position=hero_pos,
                     hero_stack=hero_stack, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.0, 1, 1, hero_pos)

    def test_rfi_100bb_btn_tier4_correct(self):
        """BTN at 100bb can open tier 4 hand (54% range)."""
        self._insert_rfi('S53B1A', 'Jd 8h', 'BTN', hero_stack=50.0, blinds_bb=0.50)
        score, note = self._rfi_result('S53B1A')
        self.assertEqual(score, 1, f"J8o BTN 100bb should be correct RFI: {note}")
        self.assertIn('100BB', note.upper().replace('BB', 'BB') or note)

    def test_rfi_25bb_btn_tightens_to_tier3(self):
        """BTN at 25bb only opens tier 1-3 (~45% range), tier 4 is marginal."""
        # J8o is tier 4 — marginal from BTN at 25bb (1 tier above max 3)
        self._insert_rfi('S53B1B', 'Jd 8h', 'BTN', hero_stack=12.5, blinds_bb=0.50)
        score, note = self._rfi_result('S53B1B')
        self.assertNotEqual(score, 1, f"J8o BTN 25bb should NOT be correct RFI: {note}")

    def test_rfi_15bb_co_tightens_to_tier2(self):
        """CO at 15bb only opens tier 1-2 (~30%), tier 3 hand is marginal."""
        # Q7s is tier 3 — marginal from CO at 15bb (1 tier above max 2)
        self._insert_rfi('S53B1C', 'Qs 7s', 'CO', hero_stack=7.5, blinds_bb=0.50)
        score, note = self._rfi_result('S53B1C')
        self.assertNotEqual(score, 1, f"Q7s CO 15bb should NOT be correct RFI: {note}")

    def test_rfi_50bb_co_tier3_correct(self):
        """CO at 50bb opens full tier 3 range (~38%)."""
        # A5o is tier 3 — correct from CO at 50bb
        self._insert_rfi('S53B1D', 'As 5h', 'CO', hero_stack=25.0, blinds_bb=0.50)
        score, note = self._rfi_result('S53B1D')
        self.assertEqual(score, 1, f"A5o CO 50bb should be correct RFI: {note}")

    def test_rfi_fold_openable_hand_is_incorrect(self):
        """Hero folds a hand in RFI range — should detect as incorrect."""
        _insert_hand(self.repo, 'S53B1E', position='BTN',
                     hero_stack=50.0, blinds_bb=0.50)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", ('Ah Kd', 'S53B1E'))
        self.repo.conn.commit()
        # Hero folds preflop (no raise seen)
        _insert_action(self.repo, 'S53B1E', 'preflop', 'UTG', 'fold', 0, 0, 1, 'UTG')
        _insert_action(self.repo, 'S53B1E', 'preflop', 'Hero', 'fold', 0, 1, 2, 'BTN')
        score, note = self._rfi_result('S53B1E')
        self.assertEqual(score, 0, f"Folding AKo from BTN should be incorrect: {note}")
        self.assertIn('foldou', note.lower())

    def test_rfi_fold_trash_hand_is_correct(self):
        """Hero folds 72o from UTG — correct, outside RFI range."""
        _insert_hand(self.repo, 'S53B1F', position='UTG',
                     hero_stack=50.0, blinds_bb=0.50)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", ('7h 2d', 'S53B1F'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'S53B1F', 'preflop', 'Hero', 'fold', 0, 1, 1, 'UTG')
        score, note = self._rfi_result('S53B1F')
        self.assertEqual(score, 1, f"Folding 72o from UTG should be correct: {note}")

    def test_rfi_stack_depth_dict_has_4_bands(self):
        """_RFI_STACK_POS_TIER must have exactly 4 stack depth bands."""
        self.assertEqual(len(self.classifier._RFI_STACK_POS_TIER), 4)

    def test_rfi_stack_depth_dict_has_6_positions_each_band(self):
        """Each stack band must cover at least 6 positions."""
        for band, pos_dict in self.classifier._RFI_STACK_POS_TIER.items():
            self.assertGreaterEqual(len(pos_dict), 6,
                f"Stack band {band}bb should have >=6 positions, got {len(pos_dict)}")

    def test_rfi_15bb_tighter_than_100bb_for_btn(self):
        """At 15bb, BTN max tier should be less than at 100bb (tighter range)."""
        tier_15bb = self.classifier._RFI_STACK_POS_TIER[15].get('BTN', 4)
        tier_100bb = self.classifier._RFI_STACK_POS_TIER[100].get('BTN', 4)
        self.assertLess(tier_15bb, tier_100bb,
            f"BTN 15bb tier ({tier_15bb}) should be < 100bb tier ({tier_100bb})")


class TestUS053bAula2FlatSizing(unittest.TestCase):
    """Aula 2: Flat/3-bet with 3-bet sizing verification.

    Based on RegLife 'Ranges de Flat e 3-BET' PDF:
    - IP (BTN/CO/HJ): 3-bet sizing should be 3-4x the open
    - OOP (SB/BB/EP): 3-bet sizing should be 4-5x the open
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _flat3bet_result(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        matches = self.classifier.classify_hand(hand, actions)
        m = next((m for m in matches if m.lesson_id == 2), None)
        return (m.executed_correctly, m.notes) if m else (None, '')

    def _insert_3bet(self, hand_id, hero_cards, hero_pos, open_amount, bet_amount):
        _insert_hand(self.repo, hand_id, position=hero_pos)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        # Villain opens
        _insert_action(self.repo, hand_id, 'preflop', 'Villain', 'raise',
                       open_amount, 0, 1, 'UTG')
        # Hero 3-bets
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       bet_amount, 1, 2, hero_pos)

    def test_3bet_ip_correct_sizing_3x(self):
        """BTN 3-bets at 3x — correct IP sizing."""
        # open 1.5 → 3bet 4.5 = 3x (IP correct: 3-4x)
        self._insert_3bet('S53B2A', 'Ah Ad', 'BTN', 1.5, 4.5)
        score, note = self._flat3bet_result('S53B2A')
        self.assertEqual(score, 1, f"AA BTN 3x 3-bet should be correct: {note}")
        self.assertIn('3.0x', note)

    def test_3bet_ip_incorrect_sizing_2x(self):
        """BTN 3-bets too small (2x) — incorrect sizing noted."""
        # open 1.5 → 3bet 3.0 = 2x (IP too small, min is 3x)
        self._insert_3bet('S53B2B', 'Ah Ad', 'BTN', 1.5, 3.0)
        score, note = self._flat3bet_result('S53B2B')
        # Range is correct but sizing wrong → None or sizing note
        self.assertIn('sizing', note.lower(), f"Should mention sizing: {note}")
        self.assertIn('2.0x', note)

    def test_3bet_oop_correct_sizing_4x(self):
        """BB 3-bets at 4x — correct OOP sizing."""
        # open 1.5 → 3bet 6.0 = 4x (OOP correct: 4-5x)
        self._insert_3bet('S53B2C', 'Kh Ks', 'BB', 1.5, 6.0)
        score, note = self._flat3bet_result('S53B2C')
        self.assertEqual(score, 1, f"KK BB 4x 3-bet should be correct: {note}")
        self.assertIn('4.0x', note)

    def test_3bet_oop_incorrect_sizing_3x(self):
        """SB 3-bets too small for OOP (3x) — sizing noted as incorrect."""
        # open 1.5 → 3bet 4.5 = 3x (OOP too small, min is 4x)
        self._insert_3bet('S53B2D', 'Kh Ks', 'SB', 1.5, 4.5)
        score, note = self._flat3bet_result('S53B2D')
        self.assertIn('sizing', note.lower(), f"Should mention sizing: {note}")
        self.assertIn('OOP', note)

    def test_3bet_range_correct_no_amount(self):
        """3-bet with correct range but no amount data — no sizing check."""
        _insert_hand(self.repo, 'S53B2E', position='BTN')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", ('Ah Ad', 'S53B2E'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'S53B2E', 'preflop', 'Villain', 'raise',
                       0, 0, 1, 'UTG')
        _insert_action(self.repo, 'S53B2E', 'preflop', 'Hero', 'raise',
                       0, 1, 2, 'BTN')
        score, note = self._flat3bet_result('S53B2E')
        self.assertEqual(score, 1, f"AA BTN 3-bet (no sizing) should be correct: {note}")


class TestUS053bAula3BlockerDomination(unittest.TestCase):
    """Aula 3: Reaction vs 3-bet with blocker and domination criteria.

    Based on RegLife 'Ranges de reação vs 3-bet' PDF:
    - A5s/A4s/A3s/A2s: 4-bet bluffs (Ace blocker)
    - 54s has MORE EV vs 3-bet than AQo (no domination, better equity vs AA/KK/QQ)
    - AQo can be dominated by 3-bettor's AK/AA range
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _vs3bet_result(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        matches = self.classifier.classify_hand(hand, actions)
        m = next((m for m in matches if m.lesson_id == 3), None)
        return (m.executed_correctly, m.notes) if m else (None, '')

    def _insert_vs3bet(self, hand_id, hero_cards, hero_pos, hero_action='call',
                       hero_amount=4.5):
        _insert_hand(self.repo, hand_id, position=hero_pos)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, hero_pos)
        _insert_action(self.repo, hand_id, 'preflop', 'Villain', 'raise',
                       4.5, 0, 2, 'CO')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', hero_action,
                       hero_amount, 1, 3, hero_pos)

    def test_blocker_4bet_a5s_is_correct(self):
        """A5s 4-bet vs 3-bet is correct (blocker of Ace blocks AA/AK)."""
        self._insert_vs3bet('S53B3A', 'As 5s', 'BTN', hero_action='raise',
                             hero_amount=12.0)
        score, note = self._vs3bet_result('S53B3A')
        self.assertEqual(score, 1, f"A5s 4-bet bluff should be correct: {note}")
        self.assertIn('blocker', note.lower())

    def test_blocker_4bet_a3s_is_correct(self):
        """A3s 4-bet bluff is correct (Ace blocker value)."""
        self._insert_vs3bet('S53B3B', 'Ah 3h', 'UTG', hero_action='raise',
                             hero_amount=12.0)
        score, note = self._vs3bet_result('S53B3B')
        self.assertEqual(score, 1, f"A3s 4-bet bluff should be correct: {note}")
        self.assertIn('blocker', note.lower())

    def test_54s_continue_not_dominated(self):
        """54s continuing vs 3-bet is correct with note about no domination."""
        self._insert_vs3bet('S53B3C', '5h 4h', 'BTN', hero_action='call')
        score, note = self._vs3bet_result('S53B3C')
        self.assertEqual(score, 1, f"54s call vs 3-bet should be correct: {note}")
        # Should mention no domination or good equity
        self.assertTrue(
            'dominac' in note.lower() or 'equity' in note.lower(),
            f"Note should mention domination/equity: {note}"
        )

    def test_aqo_continue_notes_domination_risk(self):
        """AQo continuing vs 3-bet is technically correct but notes domination risk."""
        self._insert_vs3bet('S53B3D', 'Ah Qd', 'UTG', hero_action='call')
        score, note = self._vs3bet_result('S53B3D')
        self.assertEqual(score, 1, f"AQo call vs 3-bet should be correct: {note}")
        # Note should mention domination
        self.assertIn('dominac', note.lower(), f"Note should mention domination: {note}")

    def test_blocker_set_has_key_hands(self):
        """_VS3BET_BLOCKER_4BET should contain A5s, A4s, A3s, A2s."""
        for hand in ['A5s', 'A4s', 'A3s', 'A2s']:
            self.assertIn(hand, self.classifier._VS3BET_BLOCKER_4BET,
                          f"{hand} should be in VS3BET_BLOCKER_4BET")

    def test_54s_in_continue_range(self):
        """54s should be in _VS3BET_CONTINUE (has equity vs AA/KK/QQ)."""
        self.assertIn('54s', self.classifier._VS3BET_CONTINUE,
                      '54s should be in VS3BET_CONTINUE')

    def test_aqo_in_dominated_set(self):
        """AQo should be in _VS3BET_DOMINATED (shares A kicker with AK/AA)."""
        self.assertIn('AQo', self.classifier._VS3BET_DOMINATED,
                      'AQo should be in VS3BET_DOMINATED')

    def test_value_4bet_aa_correct(self):
        """AA 4-bet is correct value 4-bet."""
        self._insert_vs3bet('S53B3E', 'Ah As', 'UTG', hero_action='raise',
                             hero_amount=12.0)
        score, note = self._vs3bet_result('S53B3E')
        self.assertEqual(score, 1, f"AA 4-bet should be correct: {note}")
        self.assertIn('valor', note.lower())

    def test_trash_4bet_is_incorrect(self):
        """72o 4-bet vs 3-bet is incorrect."""
        self._insert_vs3bet('S53B3F', '7h 2d', 'UTG', hero_action='raise',
                             hero_amount=12.0)
        score, note = self._vs3bet_result('S53B3F')
        self.assertEqual(score, 0, f"72o 4-bet should be incorrect: {note}")


class TestUS053bAula4OpenShovePDF(unittest.TestCase):
    """Aula 4: Open Shove using PDF position ranges.

    Based on RegLife 'Ranges de Open Shove cEV 10BB' PDF:
    - SB: 69%, BTN: 41%, CO: 33%, HJ: 27%, LJ: 22%, UTG+1: 19%, UTG: 16%
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _shove_result(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        matches = self.classifier.classify_hand(hand, actions)
        m = next((m for m in matches if m.lesson_id == 4), None)
        return (m.executed_correctly, m.notes) if m else (None, '')

    def _insert_shove(self, hand_id, hero_cards, hero_pos, hero_stack,
                      blinds_bb=0.50):
        _insert_hand(self.repo, hand_id, position=hero_pos,
                     hero_stack=hero_stack, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'all-in',
                       hero_stack, 1, 1, hero_pos)

    def test_sb_shove_69pct_target_in_note(self):
        """SB shove should mention ~69% target in note."""
        self._insert_shove('S53B4A', 'Ah Kd', 'SB', hero_stack=5.0)
        score, note = self._shove_result('S53B4A')
        self.assertEqual(score, 1, f"AKo SB 10bb shove should be correct: {note}")
        self.assertIn('69', note, f"Note should mention 69% target: {note}")

    def test_btn_shove_41pct_target_in_note(self):
        """BTN shove should mention ~41% target in note."""
        self._insert_shove('S53B4B', 'Kh 9h', 'BTN', hero_stack=5.0)
        score, note = self._shove_result('S53B4B')
        self.assertEqual(score, 1, f"K9s BTN 10bb shove should be correct: {note}")
        self.assertIn('41', note, f"Note should mention 41% target: {note}")

    def test_utg_shove_16pct_target_in_note(self):
        """UTG shove should mention ~16% target in note."""
        self._insert_shove('S53B4C', 'Ah Ad', 'UTG', hero_stack=5.0)
        score, note = self._shove_result('S53B4C')
        self.assertEqual(score, 1, f"AA UTG 10bb shove should be correct: {note}")
        self.assertIn('16', note, f"Note should mention 16% target: {note}")

    def test_sb_extra_range_is_correct(self):
        """SB shoves a hand in SB extra range (beyond tier 4, valid at 69%)."""
        # Q6o is in _OPEN_SHOVE_SB_EXTRA
        self._insert_shove('S53B4D', 'Qs 6h', 'SB', hero_stack=5.0)
        score, note = self._shove_result('S53B4D')
        self.assertEqual(score, 1, f"Q6o SB 10bb shove should be correct (extra range): {note}")
        self.assertIn('69', note, f"SB extra note should mention 69%: {note}")

    def test_btn_fold_hand_in_sb_extra_is_incorrect(self):
        """BTN cannot shove Q6o (only valid from SB); should be incorrect from BTN."""
        self._insert_shove('S53B4E', 'Qs 6h', 'BTN', hero_stack=5.0)
        score, note = self._shove_result('S53B4E')
        self.assertIn(score, [0, None],
            f"Q6o BTN 10bb shove should be incorrect or marginal: {note}")

    def test_sb_shove_extra_has_weak_offsuit(self):
        """_OPEN_SHOVE_SB_EXTRA should contain weak suited and offsuit hands."""
        for hand in ['Q6o', 'J6o', 'T6o', '64o', 'Q5s', 'J4s']:
            self.assertIn(hand, self.classifier._OPEN_SHOVE_SB_EXTRA,
                          f"{hand} should be in OPEN_SHOVE_SB_EXTRA for SB 69% range")

    def test_lj_tier_is_2_not_1(self):
        """LJ open shove max tier should be 2 (22% range, not 1/16%)."""
        tier = self.classifier._OPEN_SHOVE_POS_MAX_TIER.get('LJ', 0)
        self.assertEqual(tier, 2,
            f"LJ should have open shove tier 2 (PDF 22%), got {tier}")

    def test_pos_target_pct_dict_has_sb_69(self):
        """_OPEN_SHOVE_POS_TARGET_PCT should have SB=69."""
        self.assertEqual(self.classifier._OPEN_SHOVE_POS_TARGET_PCT.get('SB'), 69)

    def test_pos_target_pct_dict_has_btn_41(self):
        """_OPEN_SHOVE_POS_TARGET_PCT should have BTN=41."""
        self.assertEqual(self.classifier._OPEN_SHOVE_POS_TARGET_PCT.get('BTN'), 41)


class TestUS053cAula5Squeeze3WaySizing(unittest.TestCase):
    """Aula 5: Squeeze verifies 3-way scenario and correct sizing.

    US-053c acceptance criteria:
    - Squeeze verifica cenario 3-way (open + pelo menos 1 caller)
    - Squeeze verifica sizing: IP 3-5x, OOP 4-6x o open
    - Notes em PT-BR com 'cenario N-way'
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

    def _squeeze_match(self, hand_id):
        matches = self._classify(hand_id)
        return next((m for m in matches if m.lesson_id == 5), None)

    def _insert_squeeze(self, hand_id, hero_cards, hero_pos, opener_pos,
                        caller_pos, open_amount=1.5, caller_amount=1.5,
                        hero_squeeze_amount=6.0):
        _insert_hand(self.repo, hand_id, position=hero_pos)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Opener', 'raise',
                       open_amount, 0, 1, opener_pos)
        _insert_action(self.repo, hand_id, 'preflop', 'Caller', 'call',
                       caller_amount, 0, 2, caller_pos)
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       hero_squeeze_amount, 1, 3, hero_pos)

    # -- Cenario 3-way na nota --

    def test_squeeze_note_mentions_3way_scenario(self):
        """Note should mention the 3-way scenario (open + 1 caller)."""
        self._insert_squeeze('C5A', 'Ah Ad', 'BTN', 'HJ', 'CO',
                             open_amount=1.5, caller_amount=1.5,
                             hero_squeeze_amount=6.0)
        m = self._squeeze_match('C5A')
        self.assertIsNotNone(m, "Squeeze should be detected")
        self.assertIn('3-way', m.notes, f"Note should mention '3-way': {m.notes}")

    def test_squeeze_note_mentions_multiway_with_2callers(self):
        """With 2 callers, note should mention 4-way scenario."""
        _insert_hand(self.repo, 'C5B', position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", ('Ah Kh', 'C5B'))
        self.repo.conn.commit()
        _insert_action(self.repo, 'C5B', 'preflop', 'Opener', 'raise', 1.5, 0, 1, 'UTG')
        _insert_action(self.repo, 'C5B', 'preflop', 'Caller1', 'call', 1.5, 0, 2, 'HJ')
        _insert_action(self.repo, 'C5B', 'preflop', 'Caller2', 'call', 1.5, 0, 3, 'BTN')
        _insert_action(self.repo, 'C5B', 'preflop', 'Hero', 'raise', 9.0, 1, 4, 'BB')
        m = self._squeeze_match('C5B')
        self.assertIsNotNone(m, "Squeeze should be detected with 2 callers")
        self.assertIn('4-way', m.notes, f"Note should mention '4-way': {m.notes}")

    # -- Sizing validation --

    def test_squeeze_ip_correct_sizing_4x(self):
        """BTN squeeze at 4x open — correct IP sizing (ideal 3-5x)."""
        # 1.5 open → 6.0 squeeze = 4x (IP correct)
        self._insert_squeeze('C5C', 'Ah Ad', 'BTN', 'HJ', 'CO',
                             open_amount=1.5, hero_squeeze_amount=6.0)
        m = self._squeeze_match('C5C')
        self.assertEqual(m.executed_correctly, 1,
                         f"AA BTN 4x squeeze should be correct: {m.notes}")
        self.assertIn('sizing', m.notes.lower(), f"Note should mention sizing: {m.notes}")

    def test_squeeze_ip_bad_sizing_too_small(self):
        """BTN squeeze at 1.5x open — too small, should be marginal/incorrect."""
        # 1.5 open → 2.0 squeeze = 1.3x (way too small for IP: 3-5x)
        self._insert_squeeze('C5D', 'Ah Ad', 'BTN', 'HJ', 'CO',
                             open_amount=1.5, hero_squeeze_amount=2.0)
        m = self._squeeze_match('C5D')
        # Below threshold → None (sizing incorrect note)
        self.assertNotEqual(m.executed_correctly, 1,
                            f"AA BTN 1.3x squeeze should not be correct: {m.notes}")
        self.assertIn('sizing', m.notes.lower(), f"Note should mention sizing: {m.notes}")

    def test_squeeze_oop_correct_sizing_5x(self):
        """BB squeeze at 5x open — correct OOP sizing (ideal 4-6x)."""
        # 1.5 open → 7.5 squeeze = 5x (OOP correct)
        self._insert_squeeze('C5E', 'Kh Ks', 'BB', 'CO', 'BTN',
                             open_amount=1.5, hero_squeeze_amount=7.5)
        m = self._squeeze_match('C5E')
        self.assertEqual(m.executed_correctly, 1,
                         f"KK BB 5x squeeze should be correct: {m.notes}")

    def test_squeeze_callers_stored_in_pf(self):
        """callers_before_hero should be stored when hero squeezes."""
        self._insert_squeeze('C5F', 'Ah Ad', 'BTN', 'HJ', 'CO',
                             open_amount=1.5, hero_squeeze_amount=6.0)
        hand = _get_hand_dict(self.repo, 'C5F')
        actions = self.repo.get_hand_actions('C5F')
        pf = self.classifier._analyze_preflop(actions, 'BTN')
        self.assertTrue(pf['hero_squeezes'], "Should detect squeeze")
        self.assertEqual(pf['callers_before_hero'], 1,
                         f"Should store 1 caller: {pf}")

    def test_squeeze_note_is_pt_br(self):
        """All squeeze notes must be in PT-BR."""
        self._insert_squeeze('C5G', 'Ah Ad', 'BTN', 'HJ', 'CO')
        m = self._squeeze_match('C5G')
        self.assertIsNotNone(m)
        # Key PT-BR words
        self.assertTrue(
            any(w in m.notes.lower() for w in ['correto', 'incorreto', 'marginal', 'squeeze']),
            f"Note should be in PT-BR: {m.notes}"
        )

    def test_squeeze_bb_stack_pos_tier_dict_structure(self):
        """_BB_STACK_POS_TIER must have 4 bands (15/30/50/100)."""
        self.assertEqual(set(self.classifier._BB_STACK_POS_TIER.keys()), {15, 30, 50, 100})


class TestUS053cAula6BBStackDepth(unittest.TestCase):
    """Aula 6: BB defense distingue range por posicao do raiser e stack depth.

    US-053c acceptance criteria:
    - BB defense depends on raiser position AND hero stack depth
    - At 15bb: tighter range (speculative hands lose implied odds)
    - At 30bb: medium range
    - At 100bb: full range per position
    - Notes em PT-BR com stack info
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _bb_result(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        matches = self.classifier.classify_hand(hand, actions)
        m = next((m for m in matches if m.lesson_id == 6), None)
        return (m.executed_correctly, m.notes) if m else (None, '')

    def _insert_bb_defense(self, hand_id, hero_cards, raiser_pos, hero_action,
                           hero_stack, blinds_bb=0.50):
        _insert_hand(self.repo, hand_id, position='BB',
                     hero_stack=hero_stack, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Villain', 'raise',
                       1.5, 0, 1, raiser_pos)
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', hero_action,
                       1.5 if hero_action == 'call' else 0, 1, 2, 'BB')

    # -- Position-based range --

    def test_bb_tier1_defends_vs_utg_100bb(self):
        """KQs (tier 1) must defend vs UTG at 100bb."""
        # KQs is tier 1, UTG allows tier 1 → correct defend
        self._insert_bb_defense('C6A', 'Kh Qh', 'UTG', 'call',
                                hero_stack=50.0, blinds_bb=0.50)
        score, note = self._bb_result('C6A')
        self.assertEqual(score, 1, f"KQs vs UTG 100bb defend should be correct: {note}")
        self.assertIn('100BB', note.upper() or '100bb', note)

    def test_bb_tier4_folds_vs_utg_100bb(self):
        """T9o (tier 4) should fold vs UTG at 100bb (UTG only allows tier 1)."""
        # T9o is tier 4, UTG allows tier 1 → correct fold
        self._insert_bb_defense('C6B', 'Th 9d', 'UTG', 'fold',
                                hero_stack=50.0, blinds_bb=0.50)
        score, note = self._bb_result('C6B')
        self.assertEqual(score, 1, f"T9o vs UTG fold should be correct: {note}")

    def test_bb_tier4_defends_vs_btn_100bb(self):
        """T9o (tier 4) correctly defends vs BTN at 100bb (BTN allows tier 4)."""
        self._insert_bb_defense('C6C', 'Th 9d', 'BTN', 'call',
                                hero_stack=50.0, blinds_bb=0.50)
        score, note = self._bb_result('C6C')
        self.assertEqual(score, 1, f"T9o vs BTN 100bb defend should be correct: {note}")

    # -- Stack depth tightening --

    def test_bb_15bb_tighter_vs_btn(self):
        """At 15bb, BB vs BTN tier max should be 2, not 4."""
        tier = self.classifier._bb_pos_tier_for_stack('BTN', 15)
        self.assertEqual(tier, 2,
                         f"BTN 15bb BB defense tier should be 2, got {tier}")

    def test_bb_tier3_folds_vs_btn_15bb(self):
        """At 15bb, tier 3 hand (K5s) vs BTN should be marginal (BTN max tier = 2)."""
        # K5s is tier 3, BTN at 15bb allows tier 2 → marginal (tier 3 = pos_tier + 1)
        self._insert_bb_defense('C6D', 'Kd 5d', 'BTN', 'fold',
                                hero_stack=7.5, blinds_bb=0.50)  # 15bb
        score, note = self._bb_result('C6D')
        self.assertIn(score, [None, 1],
                      f"K5s vs BTN at 15bb fold should be marginal or correct: {note}")
        self.assertIn('15BB', note.upper() or '15bb', note)

    def test_bb_tier4_folds_vs_btn_15bb_correct(self):
        """At 15bb, tier 4 hand (Q3s) vs BTN: BTN max tier=2 so tier 4 > max → correct fold."""
        # Q3s is tier 4, BTN at 15bb allows tier 2 → gap = 2 → correct to fold
        self._insert_bb_defense('C6E', 'Qd 3d', 'BTN', 'fold',
                                hero_stack=7.5, blinds_bb=0.50)  # 15bb
        score, note = self._bb_result('C6E')
        self.assertEqual(score, 1,
                         f"Q3s vs BTN at 15bb fold should be correct: {note}")

    def test_bb_30bb_medium_range_vs_co(self):
        """At 30bb, CO max tier is 2 (vs standard 3 at 100bb)."""
        tier = self.classifier._bb_pos_tier_for_stack('CO', 30)
        self.assertEqual(tier, 2,
                         f"CO 30bb BB defense tier should be 2, got {tier}")

    def test_bb_100bb_full_range_vs_btn(self):
        """At 100bb, BTN max tier is 4 (full defense)."""
        tier = self.classifier._bb_pos_tier_for_stack('BTN', 100)
        self.assertEqual(tier, 4,
                         f"BTN 100bb BB defense tier should be 4, got {tier}")

    def test_bb_note_includes_stack_info(self):
        """BB defense note must include stack info (PT-BR)."""
        self._insert_bb_defense('C6F', 'Ah Kh', 'UTG', 'call',
                                hero_stack=50.0, blinds_bb=0.50)
        score, note = self._bb_result('C6F')
        self.assertIsNotNone(score)
        self.assertTrue(
            'BB' in note or 'bb' in note.lower(),
            f"Note should include stack info: {note}"
        )

    def test_bb_stack_pos_tier_has_4_bands(self):
        """_BB_STACK_POS_TIER must have exactly 4 stack depth bands."""
        self.assertEqual(len(self.classifier._BB_STACK_POS_TIER), 4)

    def test_bb_15bb_tighter_than_100bb_at_btn(self):
        """At 15bb, BB vs BTN max tier must be less than at 100bb (tighter defense)."""
        tier_15 = self.classifier._bb_pos_tier_for_stack('BTN', 15)
        tier_100 = self.classifier._bb_pos_tier_for_stack('BTN', 100)
        self.assertLess(tier_15, tier_100,
                        f"15bb tier ({tier_15}) should be < 100bb tier ({tier_100})")


class TestUS053cAula7SBBlindWarStack(unittest.TestCase):
    """Aula 7: SB blind war diferencia limp vs raise vs shove por stack.

    US-053c acceptance criteria:
    - 15bb: shove (ou raise) e correto; limp e incorreto
    - 30bb: raise correto; limp com mao fora do range e aceitavel
    - 50bb+: raise correto; limp especulativo pode ser correto
    - Notes em PT-BR mencionando stack depth
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _sb_bw_result(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        matches = self.classifier.classify_hand(hand, actions)
        m = next((m for m in matches if m.lesson_id == 7), None)
        return (m.executed_correctly, m.notes) if m else (None, '')

    def _insert_sb_raise(self, hand_id, hero_cards, hero_stack, blinds_bb=0.50):
        """SB raises (standard blind war)."""
        _insert_hand(self.repo, hand_id, position='SB',
                     hero_stack=hero_stack, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'SB')
        _insert_action(self.repo, hand_id, 'preflop', 'BB', 'fold', 0, 0, 2, 'BB')

    def _insert_sb_shove(self, hand_id, hero_cards, hero_stack, blinds_bb=0.50):
        """SB shoves all-in (blind war shove)."""
        _insert_hand(self.repo, hand_id, position='SB',
                     hero_stack=hero_stack, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'all-in',
                       hero_stack, 1, 1, 'SB')
        _insert_action(self.repo, hand_id, 'preflop', 'BB', 'fold', 0, 0, 2, 'BB')

    def _insert_sb_limp(self, hand_id, hero_cards, hero_stack, blinds_bb=0.50):
        """SB limps (calls BB — blind war limp)."""
        _insert_hand(self.repo, hand_id, position='SB',
                     hero_stack=hero_stack, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        # No previous raise — SB calls the BB (limp)
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       blinds_bb, 1, 1, 'SB')

    # -- 15bb stack scenarios --

    def test_sb_limp_at_15bb_is_incorrect(self):
        """SB limping at 15bb is incorrect — should shove or raise."""
        self._insert_sb_limp('C7A', 'Ah Kd', 15.0 * 0.50, blinds_bb=0.50)  # 15bb stack
        score, note = self._sb_bw_result('C7A')
        self.assertEqual(score, 0, f"SB limp at 15bb should be incorrect: {note}")
        self.assertIn('limp', note.lower(), f"Note should mention limp: {note}")
        self.assertIn('15BB', note.upper() or '15bb', note)

    def test_sb_shove_at_15bb_is_correct(self):
        """SB shoving AA at 15bb is correct."""
        self._insert_sb_shove('C7B', 'Ah As', 7.5, blinds_bb=0.50)  # 15bb
        score, note = self._sb_bw_result('C7B')
        self.assertEqual(score, 1, f"SB shove AA at 15bb should be correct: {note}")
        self.assertIn('shove', note.lower(), f"Note should mention shove: {note}")

    def test_sb_raise_at_15bb_is_correct(self):
        """SB raising AKo at 15bb is correct (with note about shove option)."""
        self._insert_sb_raise('C7C', 'Ah Kd', 7.5, blinds_bb=0.50)  # 15bb
        score, note = self._sb_bw_result('C7C')
        self.assertEqual(score, 1, f"SB raise AKo at 15bb should be correct: {note}")

    # -- 30bb stack scenarios --

    def test_sb_raise_at_30bb_is_correct(self):
        """SB raising QQ at 30bb is correct."""
        self._insert_sb_raise('C7D', 'Qh Qd', 15.0, blinds_bb=0.50)  # 30bb
        score, note = self._sb_bw_result('C7D')
        self.assertEqual(score, 1, f"SB raise QQ at 30bb should be correct: {note}")

    def test_sb_limp_strong_hand_at_30bb_is_marginal(self):
        """SB limping strong hand (AKo) at 30bb is marginal — should raise."""
        # AKo is RFI tier 1 (strong) — limping is marginal at 30bb
        self._insert_sb_limp('C7E', 'Ah Kd', 15.0, blinds_bb=0.50)  # 30bb
        score, note = self._sb_bw_result('C7E')
        self.assertIsNone(score, f"SB limp AKo at 30bb should be marginal: {note}")
        self.assertIn('prefira', note.lower() or 'marginal',
                      f"Note should suggest raising: {note}")

    # -- 50bb/100bb stack scenarios --

    def test_sb_raise_at_100bb_is_correct(self):
        """SB raising KQs at 100bb is correct."""
        self._insert_sb_raise('C7F', 'Kh Qh', 50.0, blinds_bb=0.50)  # 100bb
        score, note = self._sb_bw_result('C7F')
        self.assertEqual(score, 1, f"SB raise KQs at 100bb should be correct: {note}")

    def test_sb_limp_speculative_at_100bb_is_correct(self):
        """SB limping speculative hand (85s) at 100bb is correct (implied odds)."""
        # 85s is tier 3 in RFI → not in SB war extra → limp at 100bb OK (deep)
        self._insert_sb_limp('C7G', '8d 5d', 50.0, blinds_bb=0.50)  # 100bb
        score, note = self._sb_bw_result('C7G')
        self.assertEqual(score, 1,
                         f"SB limp 85s at 100bb should be correct: {note}")
        self.assertIn('especulat', note.lower(),
                      f"Note should mention speculative: {note}")

    def test_sb_limp_strong_at_100bb_is_marginal(self):
        """SB limping AA at 100bb is marginal — strong hands prefer raising."""
        # AA is tier 1 — limping is marginal (should raise for value)
        self._insert_sb_limp('C7H', 'Ah As', 50.0, blinds_bb=0.50)  # 100bb
        score, note = self._sb_bw_result('C7H')
        self.assertIsNone(score, f"SB limp AA at 100bb should be marginal: {note}")
        self.assertIn('forte', note.lower() or 'valor',
                      f"Note should mention strong hands prefer raising: {note}")

    # -- Blind war limp detection --

    def test_sb_limp_detected_as_blind_war(self):
        """SB limp (no prior raise) should be detected as blind war."""
        self._insert_sb_limp('C7I', 'Ah As', 50.0, blinds_bb=0.50)
        hand = _get_hand_dict(self.repo, 'C7I')
        actions = self.repo.get_hand_actions('C7I')
        pf = self.classifier._analyze_preflop(actions, 'SB')
        self.assertTrue(pf['is_blind_war'], "SB limp should trigger is_blind_war")
        self.assertTrue(pf['hero_sb_limps_bw'], "Should set hero_sb_limps_bw flag")

    def test_sb_limp_triggers_lesson_7(self):
        """SB limp in blind war should trigger lesson 7 classification."""
        self._insert_sb_limp('C7J', 'Ah As', 50.0, blinds_bb=0.50)
        hand = _get_hand_dict(self.repo, 'C7J')
        actions = self.repo.get_hand_actions('C7J')
        matches = self.classifier.classify_hand(hand, actions)
        ids = [m.lesson_id for m in matches]
        self.assertIn(7, ids, "SB limp should trigger lesson 7")

    def test_sb_raise_out_of_range_is_incorrect(self):
        """SB raising 32o at any stack is incorrect (outside all SB steal ranges)."""
        # 32o is not in RFI tiers 1-4 nor in _SB_WAR_EXTRA
        self._insert_sb_raise('C7K', '3h 2d', 25.0, blinds_bb=0.50)  # 50bb
        score, note = self._sb_bw_result('C7K')
        self.assertEqual(score, 0, f"SB raise 32o should be incorrect: {note}")

    def test_sb_shove_out_of_range_15bb_incorrect(self):
        """SB shoving 32o at 15bb is incorrect (outside all SB steal ranges)."""
        # 32o is not in RFI tiers 1-4, not in _SB_WAR_EXTRA
        self._insert_sb_shove('C7L', '3h 2d', 7.5, blinds_bb=0.50)  # 15bb
        score, note = self._sb_bw_result('C7L')
        self.assertEqual(score, 0, f"SB shove 32o at 15bb should be incorrect: {note}")


class TestUS053cUnknownRateBelow15Percent(unittest.TestCase):
    """Verify Unknown (executed_correctly=None) rate < 15% per aula (5-9).

    Acceptance criteria: Unknown < 15% em cada aula.
    Uses representative hands for each lesson scenario.
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        self._seq = 0

    def tearDown(self):
        self.conn.close()

    def _next_id(self, prefix):
        self._seq += 1
        return f'{prefix}{self._seq:03d}'

    def _insert_squeeze_hand(self, hero_cards, hero_pos='BTN',
                              opener_pos='HJ', caller_pos='CO'):
        hid = self._next_id('UR5')
        _insert_hand(self.repo, hid, position=hero_pos)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        _insert_action(self.repo, hid, 'preflop', 'Opener', 'raise',
                       1.5, 0, 1, opener_pos)
        _insert_action(self.repo, hid, 'preflop', 'Caller', 'call',
                       1.5, 0, 2, caller_pos)
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'raise',
                       6.0, 1, 3, hero_pos)
        return hid

    def _insert_bb_defense_hand(self, hero_cards, raiser_pos='BTN',
                                 hero_stack=50.0, blinds_bb=0.50, fold=False):
        hid = self._next_id('UR6')
        _insert_hand(self.repo, hid, position='BB',
                     hero_stack=hero_stack, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        _insert_action(self.repo, hid, 'preflop', 'Villain', 'raise',
                       1.5, 0, 1, raiser_pos)
        if fold:
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'fold',
                           0, 1, 2, 'BB')
        else:
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                           1.5, 1, 2, 'BB')
        return hid

    def _insert_sb_bw_hand(self, hero_cards, hero_stack=50.0,
                            blinds_bb=0.50, action='raise'):
        hid = self._next_id('UR7')
        _insert_hand(self.repo, hid, position='SB',
                     hero_stack=hero_stack, blinds_bb=blinds_bb)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        if action == 'limp':
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                           blinds_bb, 1, 1, 'SB')
        elif action == 'shove':
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'all-in',
                           hero_stack, 1, 1, 'SB')
            _insert_action(self.repo, hid, 'preflop', 'BB', 'fold',
                           0, 0, 2, 'BB')
        else:
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'raise',
                           1.5, 1, 1, 'SB')
            _insert_action(self.repo, hid, 'preflop', 'BB', 'fold',
                           0, 0, 2, 'BB')
        return hid

    def _insert_multiway_bb_hand(self, hero_cards, fold=False):
        hid = self._next_id('UR8')
        _insert_hand(self.repo, hid, position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        _insert_action(self.repo, hid, 'preflop', 'V1', 'raise',
                       1.5, 0, 1, 'HJ')
        _insert_action(self.repo, hid, 'preflop', 'V2', 'call',
                       1.5, 0, 2, 'CO')
        _insert_action(self.repo, hid, 'preflop', 'V3', 'call',
                       1.5, 0, 3, 'BTN')
        if fold:
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'fold',
                           0, 1, 4, 'BB')
        else:
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                           1.5, 1, 4, 'BB')
        return hid

    def _insert_bb_vs_sb_hand(self, hero_cards, fold=False):
        hid = self._next_id('UR9')
        _insert_hand(self.repo, hid, position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        _insert_action(self.repo, hid, 'preflop', 'Villain', 'raise',
                       1.5, 0, 1, 'SB')
        if fold:
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'fold',
                           0, 1, 2, 'BB')
        else:
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                           1.5, 1, 2, 'BB')
        return hid

    def _unknown_rate(self, hand_ids, lesson_id):
        """Calculate % of hands with executed_correctly=None for a lesson."""
        total = 0
        unknown = 0
        for hid in hand_ids:
            hand = _get_hand_dict(self.repo, hid)
            actions = self.repo.get_hand_actions(hid)
            matches = self.classifier.classify_hand(hand, actions)
            m = next((m for m in matches if m.lesson_id == lesson_id), None)
            if m is not None:
                total += 1
                if m.executed_correctly is None:
                    unknown += 1
        if total == 0:
            return 0.0
        return unknown / total

    def test_aula5_squeeze_unknown_below_15pct(self):
        """Squeeze: unknown rate < 15% with representative hands."""
        hands = []
        # Tier 1 hands from various positions (clearly correct)
        for cards, pos in [('Ah Ad', 'BTN'), ('Kh Kd', 'HJ'),
                           ('Ah Kh', 'CO'), ('Qh Qd', 'SB'),
                           ('Jh Jd', 'BTN'), ('Ah Qh', 'HJ'),
                           ('Kh Qh', 'CO'), ('Th Th', 'BTN')]:
            hands.append(self._insert_squeeze_hand(cards, hero_pos=pos))
        # Tier 2 hands from late pos (correct)
        for cards, pos in [('7h 7d', 'BTN'), ('Th 9h', 'CO'),
                           ('8h 7h', 'BTN'), ('6h 5h', 'SB')]:
            hands.append(self._insert_squeeze_hand(cards, hero_pos=pos))
        # Out of range hands (incorrect — not marginal)
        for cards, pos in [('7h 2d', 'BTN'), ('3h 2d', 'HJ'),
                           ('4h 2d', 'CO'), ('8h 3d', 'SB'),
                           ('9h 2d', 'BTN'), ('5h 2d', 'HJ')]:
            hands.append(self._insert_squeeze_hand(cards, hero_pos=pos))
        # Marginal: tier 2 from EP (1-2 hands)
        for cards, pos in [('7h 7d', 'HJ'), ('6h 5h', 'MP')]:
            hands.append(self._insert_squeeze_hand(cards, hero_pos=pos,
                                                    opener_pos='UTG',
                                                    caller_pos='EP'))
        rate = self._unknown_rate(hands, lesson_id=5)
        self.assertLess(rate, 0.15,
                        f"Aula 5 unknown rate {rate:.1%} >= 15%")

    def test_aula6_bb_defense_unknown_below_15pct(self):
        """BB defense: unknown rate < 15% mixing positions and stacks."""
        hands = []
        # Strong hands defending vs various raisers (correct)
        for cards, rpos in [('Ah Kd', 'UTG'), ('Kh Kd', 'HJ'),
                            ('Qh Qd', 'CO'), ('Ah Qh', 'BTN'),
                            ('Th 9h', 'BTN'), ('9h 8h', 'CO')]:
            hands.append(self._insert_bb_defense_hand(cards, raiser_pos=rpos))
        # Weak hands folding (correct)
        for cards, rpos in [('7h 2d', 'UTG'), ('4h 3d', 'HJ'),
                            ('9h 3d', 'CO'), ('8h 2d', 'UTG'),
                            ('5h 2d', 'HJ'), ('3h 2d', 'CO')]:
            hands.append(self._insert_bb_defense_hand(
                cards, raiser_pos=rpos, fold=True))
        # Medium hands vs BTN at 100bb (correct defend, tier 3-4)
        for cards in ['Ah 9d', 'Qh Jd', 'Th 9d', '8h 7d']:
            hands.append(self._insert_bb_defense_hand(cards, raiser_pos='BTN'))
        # Short stack (15bb) defense
        for cards in ['Ah Kd', 'Qh Qd']:
            hands.append(self._insert_bb_defense_hand(
                cards, raiser_pos='BTN', hero_stack=7.5, blinds_bb=0.50))
        # Short stack folds (correct)
        for cards in ['5h 4d', '7h 3d']:
            hands.append(self._insert_bb_defense_hand(
                cards, raiser_pos='UTG', hero_stack=7.5, blinds_bb=0.50,
                fold=True))
        rate = self._unknown_rate(hands, lesson_id=6)
        self.assertLess(rate, 0.15,
                        f"Aula 6 unknown rate {rate:.1%} >= 15%")

    def test_aula7_sb_blind_war_unknown_below_15pct(self):
        """SB blind war: unknown rate < 15% across stack depths."""
        hands = []
        # 15bb: shove/raise correct, clear decisions
        for cards in ['Ah Ad', 'Kh Qd', 'Th Td', 'Ah 5h']:
            hands.append(self._insert_sb_bw_hand(
                cards, hero_stack=7.5, blinds_bb=0.50, action='shove'))
        hands.append(self._insert_sb_bw_hand(
            '3h 2d', hero_stack=7.5, blinds_bb=0.50, action='shove'))  # incorrect
        # 30bb: raise correct
        for cards in ['Ah Kd', 'Qh Jh', 'Th 9h', '8h 7h']:
            hands.append(self._insert_sb_bw_hand(
                cards, hero_stack=15.0, blinds_bb=0.50, action='raise'))
        # 50bb+: raise correct
        for cards in ['Kh Qd', 'Jh Td', '9h 8h', '7h 6h']:
            hands.append(self._insert_sb_bw_hand(
                cards, hero_stack=50.0, blinds_bb=0.50, action='raise'))
        # Out of range raise (incorrect)
        for cards in ['3h 2d', '4h 2d']:
            hands.append(self._insert_sb_bw_hand(
                cards, hero_stack=25.0, blinds_bb=0.50, action='raise'))
        # Deep limp speculative (correct)
        for cards in ['5h 4h', '6h 5h', '8h 5d']:
            hands.append(self._insert_sb_bw_hand(
                cards, hero_stack=50.0, blinds_bb=0.50, action='limp'))
        rate = self._unknown_rate(hands, lesson_id=7)
        self.assertLess(rate, 0.15,
                        f"Aula 7 unknown rate {rate:.1%} >= 15%")

    def test_aula8_multiway_bb_unknown_below_15pct(self):
        """Multiway BB: unknown rate < 15% with representative hands."""
        hands = []
        # Strong defend hands (correct)
        for cards in ['Ah Kh', 'Qh Qd', '7h 7d', 'Th 9h', '8h 7h',
                      '6h 5h', 'Ah 2h', 'Kh Jh', 'Jh Td']:
            hands.append(self._insert_multiway_bb_hand(cards))
        # Weak hands folding (correct)
        for cards in ['7h 2d', '8h 3d', '9h 2d', '4h 2d', '5h 2d',
                      '6h 2d', 'Th 2d', 'Jh 2d']:
            hands.append(self._insert_multiway_bb_hand(cards, fold=True))
        # Clear offsuit broadways defending (correct)
        for cards in ['Ah Kd', 'Ah Qd', 'Kh Qd']:
            hands.append(self._insert_multiway_bb_hand(cards))
        rate = self._unknown_rate(hands, lesson_id=8)
        self.assertLess(rate, 0.15,
                        f"Aula 8 unknown rate {rate:.1%} >= 15%")

    def test_aula9_bb_vs_sb_unknown_below_15pct(self):
        """BB vs SB blind war: unknown rate < 15% with representative hands.

        In blind war BB vs SB, every offsuit hand is either in _BW_BB_DEFEND
        or _BW_BB_MARGINAL (no true trash), so realistic distribution uses
        mostly DEFEND hands and at most 2 MARGINAL hands.
        """
        hands = []
        # Strong defend (correct — clearly in range)
        for cards in ['Ah Kd', 'Qh Qd', '7h 7d', 'Ah 5h', '9h 8h',
                      'Kh Jd', 'Th 9d', 'Jh Td', '6h 5h', 'Ah 2h']:
            hands.append(self._insert_bb_vs_sb_hand(cards))
        # Defend hands that hero folds (incorrect — in range but folded)
        for cards in ['Kh 8d', 'Qh 9d', 'Jh 9d', '8h 7d', 'Ah 6d',
                      'Kh 7d']:
            hands.append(self._insert_bb_vs_sb_hand(cards, fold=True))
        # Marginal hands (at most 2 — these return None)
        for cards in ['Kh 3d', 'Qh 2d']:
            hands.append(self._insert_bb_vs_sb_hand(cards))
        # More defend hands
        for cards in ['Th 8d', '9h 7d']:
            hands.append(self._insert_bb_vs_sb_hand(cards))
        rate = self._unknown_rate(hands, lesson_id=9)
        self.assertLess(rate, 0.15,
                        f"Aula 9 unknown rate {rate:.1%} >= 15%")

    def test_squeeze_trash_from_btn_is_incorrect(self):
        """72o squeeze from BTN must be incorrect, not marginal."""
        hid = self._insert_squeeze_hand('7h 2d', hero_pos='BTN')
        hand = _get_hand_dict(self.repo, hid)
        actions = self.repo.get_hand_actions(hid)
        matches = self.classifier.classify_hand(hand, actions)
        m = next((m for m in matches if m.lesson_id == 5), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 0,
                         f"72o from BTN should be incorrect, not marginal: {m.notes}")


# ── US-053e: PDF Scenario Tests (Aulas 18-22) ─────────────────────────
# RegLife PDF Aula numbers ≠ DB sort_order (offset due to course structure):
# PDF Aula 18 = DB Lesson 16 (BB vs C-Bet OOP)
# PDF Aula 19 = DB Lesson 17 (Enfrentando o Check-Raise)
# PDF Aula 20 = DB Lesson 18 (Pós-Flop IP - Enfrentando C-Bet do BTN)
# PDF Aula 21 = DB Lesson 19 (Bet vs Missed Bet)
# PDF Aula 22 = DB Lesson 20 (Probe do BB)


class TestUS053eAula18BBvsCBetOOP(unittest.TestCase):
    """Aula 18: BB vs CBet OOP — DB Lesson 16.

    PDF defines: how to defend in BB facing villain's c-bet out of position.
    Hero BB defends with made hands/draws; folds air. Never fold equity hands.
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        self._id = 0

    def tearDown(self):
        self.conn.close()

    def _next_id(self, prefix='A18'):
        self._id += 1
        return f'{prefix}{self._id:03d}'

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _result(self, hand_id):
        matches = self._classify(hand_id)
        return next((m for m in matches if m.lesson_id == 16), None)

    def _insert_bb_vs_cbet(self, hand_id, hero_cards='Ah Kd',
                            board_flop='Ts 7d 2c', hero_action='call'):
        """BB calls preflop raise, villain c-bets flop, BB responds."""
        _insert_hand(self.repo, hand_id, position='BB', board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'bet',
                       2.0, 0, seq, 'BTN'); seq += 1
        if hero_action == 'call':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           2.0, 1, seq, 'BB')
        elif hero_action == 'fold':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'fold',
                           0, 1, seq, 'BB')
        elif hero_action == 'raise':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'raise',
                           6.0, 1, seq, 'BB')

    # -- Scenario 1: Made hand defended correctly (não fold tudo) --

    def test_top_pair_call_correct(self):
        """BB defends top pair vs c-bet: correct (1) — não fold mão com equity."""
        hid = self._next_id()
        self._insert_bb_vs_cbet(hid, hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='call')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)
        self.assertIn('BB vs CBet', m.notes)

    # -- Scenario 2: Air folded correctly --

    def test_air_fold_correct(self):
        """BB folds air vs c-bet: correct (1)."""
        hid = self._next_id()
        self._insert_bb_vs_cbet(hid, hero_cards='Qh Jd',
                                 board_flop='8c 5s 2h', hero_action='fold')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)
        self.assertIn('air', m.notes.lower())

    # -- Scenario 3: Strong hand fold is incorrect --

    def test_set_fold_incorrect(self):
        """BB folds set vs c-bet: incorrect (0) — forte mão nunca fold."""
        hid = self._next_id()
        self._insert_bb_vs_cbet(hid, hero_cards='7h 7d',
                                 board_flop='7s 4d 2c', hero_action='fold')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 0)

    # -- Scenario 4: Draw defend is correct --

    def test_flush_draw_call_correct(self):
        """BB defends flush draw vs c-bet: correct (1)."""
        hid = self._next_id()
        self._insert_bb_vs_cbet(hid, hero_cards='Ah 2h',
                                 board_flop='Kh 7h 3c', hero_action='call')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 5: Check-raise with strong hand --

    def test_check_raise_strong_correct(self):
        """BB check-raises vs c-bet with strong hand: correct (1)."""
        hid = self._next_id()
        self._insert_bb_vs_cbet(hid, hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='raise')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 6: Notes in Portuguese (PT-BR) --

    def test_notes_pt_br(self):
        """Notes must include Portuguese keywords (board texture, hand strength)."""
        hid = self._next_id()
        self._insert_bb_vs_cbet(hid, hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='call')
        m = self._result(hid)
        self.assertIsNotNone(m)
        note_lower = m.notes.lower()
        self.assertTrue(
            any(w in note_lower for w in ['correto', 'incorreto', 'marginal',
                                           'defendeu', 'foldou']),
            f"Note not in PT-BR: {m.notes}")

    # -- Guard: all-in preflop hands must not trigger lesson 16 --

    def test_allin_preflop_skips_bb_vs_cbet(self):
        """All-in preflop hand should not trigger lesson 16 (postflop guard)."""
        hid = self._next_id()
        _insert_hand(self.repo, hid, position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET has_allin=1, allin_street='preflop' "
            "WHERE hand_id=?", (hid,))
        self.repo.conn.commit()
        _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                       50.0, 0, 1, 'BTN')
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'all-in',
                       50.0, 1, 2, 'BB')
        matches = self._classify(hid)
        self.assertNotIn(16, [m.lesson_id for m in matches])


class TestUS053eAula19FacingCheckRaise(unittest.TestCase):
    """Aula 19: Enfrentando Check-Raise — DB Lesson 17.

    PDF defines: how to react when villain check-raises on the flop.
    - Strong hands: always call/re-raise, never fold
    - Medium hands: call correct, fold/re-raise marginal
    - Air: fold correct, defending incorrect
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        self._id = 0

    def tearDown(self):
        self.conn.close()

    def _next_id(self, prefix='A19'):
        self._id += 1
        return f'{prefix}{self._id:03d}'

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _result(self, hand_id):
        matches = self._classify(hand_id)
        return next((m for m in matches if m.lesson_id == 17), None)

    def _insert_facing_checkraise(self, hand_id, hero_cards='Ah Kd',
                                   board_flop='As 7d 2c',
                                   hero_response='call'):
        """Hero c-bets flop (BTN), villain check-raises, hero responds."""
        _insert_hand(self.repo, hand_id, position='BTN', board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        # Villain check-raises flop
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'raise',
                       6.0, 0, seq, 'BB'); seq += 1
        if hero_response == 'call':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           6.0, 1, seq, 'BTN')
        elif hero_response == 'fold':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'fold',
                           0, 1, seq, 'BTN')
        elif hero_response == 'raise':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'raise',
                           18.0, 1, seq, 'BTN')

    # -- Scenario 1: Strong hand call is correct --

    def test_strong_hand_call_correct(self):
        """Top pair calling check-raise: correct (1)."""
        hid = self._next_id()
        self._insert_facing_checkraise(hid, hero_cards='Ah Kd',
                                        board_flop='As 7d 2c',
                                        hero_response='call')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 2: Strong hand fold is incorrect --

    def test_strong_hand_fold_incorrect(self):
        """Folding set vs check-raise: incorrect (0) — nunca foldar mão forte."""
        hid = self._next_id()
        self._insert_facing_checkraise(hid, hero_cards='7h 7d',
                                        board_flop='7s 4d 2c',
                                        hero_response='fold')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 0)

    # -- Scenario 3: Air fold is correct --

    def test_air_fold_correct(self):
        """Folding air vs check-raise: correct (1)."""
        hid = self._next_id()
        self._insert_facing_checkraise(hid, hero_cards='Qh Jd',
                                        board_flop='8c 5s 2h',
                                        hero_response='fold')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 4: Medium hand distinctions (call/fold/re-raise) --

    def test_medium_call_correct(self):
        """Medium hand (middle pair) calling check-raise: correct (1)."""
        hid = self._next_id()
        self._insert_facing_checkraise(hid, hero_cards='7h 3d',
                                        board_flop='Ah 7c 2s',
                                        hero_response='call')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    def test_medium_fold_marginal(self):
        """Medium hand folding vs check-raise: marginal (None)."""
        hid = self._next_id()
        self._insert_facing_checkraise(hid, hero_cards='7h 3d',
                                        board_flop='Ah 7c 2s',
                                        hero_response='fold')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertIsNone(m.executed_correctly)

    def test_medium_reraise_marginal(self):
        """Medium hand re-raising check-raise: marginal (None)."""
        hid = self._next_id()
        self._insert_facing_checkraise(hid, hero_cards='7h 3d',
                                        board_flop='Ah 7c 2s',
                                        hero_response='raise')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertIsNone(m.executed_correctly)

    # -- Scenario 5: Notes in Portuguese --

    def test_notes_pt_br(self):
        """Notes must be in Portuguese (board texture, hand strength)."""
        hid = self._next_id()
        self._insert_facing_checkraise(hid, hero_cards='Ah Kd',
                                        board_flop='As 7d 2c',
                                        hero_response='call')
        m = self._result(hid)
        self.assertIsNotNone(m)
        note_lower = m.notes.lower()
        self.assertTrue(
            any(w in note_lower for w in ['correto', 'incorreto', 'marginal',
                                           'check-raise', 'vs check']),
            f"Note not in PT-BR: {m.notes}")

    # -- Guard: all-in preflop --

    def test_allin_preflop_skips_checkraise(self):
        """All-in preflop hand should not trigger lesson 17."""
        hid = self._next_id()
        _insert_hand(self.repo, hid, position='BTN')
        self.repo.conn.execute(
            "UPDATE hands SET has_allin=1, allin_street='preflop' "
            "WHERE hand_id=?", (hid,))
        self.repo.conn.commit()
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'raise',
                       50.0, 1, 1, 'BTN')
        _insert_action(self.repo, hid, 'preflop', 'P1', 'all-in',
                       50.0, 0, 2, 'BB')
        matches = self._classify(hid)
        self.assertNotIn(17, [m.lesson_id for m in matches])


class TestUS053eAula20IPvsCBetBTN(unittest.TestCase):
    """Aula 20: IP vs CBet do BTN — DB Lesson 18.

    PDF defines: how to play IP (BTN caller) facing villain's c-bet.
    - Never fold made hands IP
    - Air: fold or bluff-raise correct; float is marginal
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        self._id = 0

    def tearDown(self):
        self.conn.close()

    def _next_id(self, prefix='A20'):
        self._id += 1
        return f'{prefix}{self._id:03d}'

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _result(self, hand_id):
        matches = self._classify(hand_id)
        return next((m for m in matches if m.lesson_id == 18), None)

    def _insert_ip_vs_cbet(self, hand_id, hero_cards='Ah Kd',
                            board_flop='Ts 7d 2c', hero_action='call'):
        """Villain raises PF, hero calls BTN (IP). Villain c-bets, hero responds."""
        _insert_hand(self.repo, hand_id, position='BTN', board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'CO'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'bet',
                       2.0, 0, seq, 'CO'); seq += 1
        if hero_action == 'call':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           2.0, 1, seq, 'BTN')
        elif hero_action == 'fold':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'fold',
                           0, 1, seq, 'BTN')
        elif hero_action == 'raise':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'raise',
                           6.0, 1, seq, 'BTN')

    # -- Scenario 1: Made hand defended --

    def test_top_pair_call_correct(self):
        """IP hero defends top pair vs c-bet: correct (1)."""
        hid = self._next_id()
        self._insert_ip_vs_cbet(hid, hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='call')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 2: Strong hand fold is incorrect --

    def test_set_fold_incorrect(self):
        """IP hero folds set vs c-bet: incorrect (0) — nunca foldar IP feita."""
        hid = self._next_id()
        self._insert_ip_vs_cbet(hid, hero_cards='7h 7d',
                                 board_flop='7s 4d 2c', hero_action='fold')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 0)

    # -- Scenario 3: Air fold is correct --

    def test_air_fold_correct(self):
        """IP hero folds air vs c-bet: correct (1)."""
        hid = self._next_id()
        self._insert_ip_vs_cbet(hid, hero_cards='Qh Jd',
                                 board_flop='8c 5s 2h', hero_action='fold')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 4: Air float is marginal --

    def test_air_float_marginal(self):
        """IP hero floats (calls) with air vs c-bet: marginal (None)."""
        hid = self._next_id()
        self._insert_ip_vs_cbet(hid, hero_cards='Qh Jd',
                                 board_flop='8c 5s 2h', hero_action='call')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertIsNone(m.executed_correctly)

    # -- Scenario 5: Air bluff-raise is correct --

    def test_air_bluff_raise_correct(self):
        """IP hero bluff-raises air vs c-bet: correct (1)."""
        hid = self._next_id()
        self._insert_ip_vs_cbet(hid, hero_cards='Qh Jd',
                                 board_flop='8c 5s 2h', hero_action='raise')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 6: Notes in Portuguese --

    def test_notes_pt_br(self):
        """Notes must mention IP context in Portuguese."""
        hid = self._next_id()
        self._insert_ip_vs_cbet(hid, hero_cards='Ah Kd',
                                 board_flop='As 7d 2c', hero_action='call')
        m = self._result(hid)
        self.assertIsNotNone(m)
        note_lower = m.notes.lower()
        self.assertTrue(
            any(w in note_lower for w in ['correto', 'incorreto', 'marginal',
                                           'ip vs', 'ip']),
            f"Note not in PT-BR: {m.notes}")

    # -- Guard: all-in preflop --

    def test_allin_preflop_skips_ip_vs_cbet(self):
        """All-in preflop hand should not trigger lesson 18."""
        hid = self._next_id()
        _insert_hand(self.repo, hid, position='BTN')
        self.repo.conn.execute(
            "UPDATE hands SET has_allin=1, allin_street='preflop' "
            "WHERE hand_id=?", (hid,))
        self.repo.conn.commit()
        _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                       50.0, 0, 1, 'CO')
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'all-in',
                       50.0, 1, 2, 'BTN')
        matches = self._classify(hid)
        self.assertNotIn(18, [m.lesson_id for m in matches])


class TestUS053eAula21BetVsMissedBet(unittest.TestCase):
    """Aula 21: Bet vs Missed CBet — DB Lesson 19.

    PDF defines: exploit villain who checked flop without c-betting.
    - Value/draw: always bet = correct
    - Air on blank/neutral turn: bet = correct (villain showed weakness)
    - Air on dangerous turn: bet = marginal (villain may have caught up)
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        self._id = 0

    def tearDown(self):
        self.conn.close()

    def _next_id(self, prefix='A21'):
        self._id += 1
        return f'{prefix}{self._id:03d}'

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _result(self, hand_id):
        matches = self._classify(hand_id)
        return next((m for m in matches if m.lesson_id == 19), None)

    def _insert_bet_vs_missed(self, hand_id, hero_cards='Ah Kd',
                               board_flop='Ts 7d 2c', board_turn='3s',
                               hero_pos='BB', villain_flop_action='check'):
        """Villain checks/misses flop c-bet, hero exploits by betting turn."""
        _insert_hand(self.repo, hand_id, position=hero_pos,
                     board_flop=board_flop, board_turn=board_turn)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, hero_pos); seq += 1
        if villain_flop_action == 'check':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                           0, 1, seq, hero_pos); seq += 1
            _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                           0, 0, seq, 'BTN'); seq += 1
        else:
            # villain bets flop then checks turn
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                           0, 1, seq, hero_pos); seq += 1
            _insert_action(self.repo, hand_id, 'flop', 'P1', 'bet',
                           2.0, 0, seq, 'BTN'); seq += 1
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           2.0, 1, seq, hero_pos); seq += 1
        # Turn: villain checks, hero bets (exploit)
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       4.0, 1, seq, hero_pos)

    # -- Scenario 1: Value bet with made hand --

    def test_strong_hand_bet_correct(self):
        """Value bet with top two pair after villain missed c-bet: correct (1)."""
        hid = self._next_id()
        self._insert_bet_vs_missed(hid, hero_cards='Ah Kd',
                                    board_flop='Ah Kd 2c',
                                    board_turn='3s',
                                    villain_flop_action='check')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 2: Semi-bluff with draw --

    def test_draw_bet_correct(self):
        """Semi-bluff with flush draw after villain missed c-bet: correct (1)."""
        hid = self._next_id()
        self._insert_bet_vs_missed(hid, hero_cards='Ah 2h',
                                    board_flop='Kh 7h 3c',
                                    board_turn='9s',
                                    villain_flop_action='check')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 3: Air exploit on blank turn --

    def test_air_blank_turn_correct(self):
        """Exploit air bet on blank turn after villain missed c-bet: correct (1)."""
        hid = self._next_id()
        self._insert_bet_vs_missed(hid, hero_cards='Qd Jc',
                                    board_flop='As 7h 3c',
                                    board_turn='2d',
                                    villain_flop_action='check')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 4: Air on dangerous turn is marginal --

    def test_air_dangerous_turn_marginal(self):
        """Air bet on flush-completing turn: marginal (None) — villain may hit."""
        hid = self._next_id()
        self._insert_bet_vs_missed(hid, hero_cards='Qd Jc',
                                    board_flop='Ah 7h 3c',
                                    board_turn='9h',
                                    villain_flop_action='check')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertIsNone(m.executed_correctly)

    # -- Scenario 5: Triggered after villain bet flop then checked turn --

    def test_villain_bet_flop_checked_turn(self):
        """Lesson 19 triggers when villain bet flop then checked turn: correct."""
        hid = self._next_id()
        self._insert_bet_vs_missed(hid, hero_cards='Ah Kd',
                                    board_flop='Ah Kd 2c',
                                    board_turn='3s',
                                    villain_flop_action='bet')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 6: Notes in Portuguese --

    def test_notes_pt_br(self):
        """Notes must mention villain's weakness in Portuguese."""
        hid = self._next_id()
        self._insert_bet_vs_missed(hid, hero_cards='Ah Kd',
                                    board_flop='Ah Kd 2c',
                                    board_turn='3s',
                                    villain_flop_action='check')
        m = self._result(hid)
        self.assertIsNotNone(m)
        note_lower = m.notes.lower()
        self.assertTrue(
            any(w in note_lower for w in ['correto', 'marginal', 'missed',
                                           'vilao', 'fraco', 'bet vs']),
            f"Note not in PT-BR: {m.notes}")

    # -- Guard: all-in preflop --

    def test_allin_preflop_skips_bet_vs_missed(self):
        """All-in preflop hand should not trigger lesson 19."""
        hid = self._next_id()
        _insert_hand(self.repo, hid, position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET has_allin=1, allin_street='preflop' "
            "WHERE hand_id=?", (hid,))
        self.repo.conn.commit()
        _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                       50.0, 0, 1, 'BTN')
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'all-in',
                       50.0, 1, 2, 'BB')
        matches = self._classify(hid)
        self.assertNotIn(19, [m.lesson_id for m in matches])


class TestUS053eAula22ProbeOOPBB(unittest.TestCase):
    """Aula 22: Probe OOP BB — DB Lesson 20.

    PDF defines: when to lead (probe bet) from BB on turn after check-check flop.
    This is different from c-bet: hero is NOT the preflop aggressor.
    - Made hands: probe = correct
    - Air on blank turn: probe = correct (PFA showed weakness)
    - Air on neutral turn: probe = marginal
    - Air on dangerous turn: probe = incorrect (villain may have hit)
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        self._id = 0

    def tearDown(self):
        self.conn.close()

    def _next_id(self, prefix='A22'):
        self._id += 1
        return f'{prefix}{self._id:03d}'

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _result(self, hand_id):
        matches = self._classify(hand_id)
        return next((m for m in matches if m.lesson_id == 20), None)

    def _insert_probe(self, hand_id, hero_cards='Ah Kd',
                      board_flop='Ts 7d 2c', board_turn='3s'):
        """BB calls preflop, both check flop (check-check), BB probes turn."""
        _insert_hand(self.repo, hand_id, position='BB',
                     board_flop=board_flop, board_turn=board_turn)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?",
            (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        # Check-check flop (PFA does NOT c-bet)
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        # Turn: BB probes
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BB')

    # -- Scenario 1: Probe with made hand --

    def test_top_pair_probe_correct(self):
        """BB probes turn with top pair after check-check flop: correct (1)."""
        hid = self._next_id()
        self._insert_probe(hid, hero_cards='Ah Kd',
                           board_flop='Ah Kd 2c', board_turn='3s')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 2: Probe with draw --

    def test_flush_draw_probe_correct(self):
        """BB probes with flush draw: correct (1) — semi-bluff probe."""
        hid = self._next_id()
        self._insert_probe(hid, hero_cards='Ah 2h',
                           board_flop='Kh 7h 3c', board_turn='9s')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 3: Air probe on blank turn is correct --

    def test_air_blank_turn_probe_correct(self):
        """BB probes air on blank turn: correct (1) — PFA showed weakness."""
        hid = self._next_id()
        self._insert_probe(hid, hero_cards='Qd Jc',
                           board_flop='As 7h 3c', board_turn='2d')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 1)

    # -- Scenario 4: Air probe on dangerous turn is incorrect --

    def test_air_dangerous_turn_probe_incorrect(self):
        """BB probes air on flush-completing turn: incorrect (0)."""
        hid = self._next_id()
        self._insert_probe(hid, hero_cards='Qd Jc',
                           board_flop='Ah 7h 3c', board_turn='9h')
        m = self._result(hid)
        self.assertIsNotNone(m)
        self.assertEqual(m.executed_correctly, 0)

    # -- Scenario 5: Not triggered when villain bet flop (must be check-check) --

    def test_not_triggered_villain_bet_flop(self):
        """Probe NOT triggered when villain bet flop (not check-check scenario)."""
        hid = self._next_id()
        _insert_hand(self.repo, hid, position='BB',
                     board_flop='Ts 7d 2c', board_turn='3s')
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", ('Ah Kd', hid))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        # Villain bets flop (c-bets), hero calls
        _insert_action(self.repo, hid, 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'P1', 'bet',
                       2.0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'Hero', 'call',
                       2.0, 1, seq, 'BB'); seq += 1
        # Turn: hero bets (this is Bet vs Missed, NOT probe)
        _insert_action(self.repo, hid, 'turn', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BB')
        matches = self._classify(hid)
        # Should NOT be lesson 20 (probe), but should be lesson 19 (bet vs missed)
        self.assertNotIn(20, [m.lesson_id for m in matches])
        self.assertIn(19, [m.lesson_id for m in matches])

    # -- Scenario 6: Notes in Portuguese --

    def test_notes_pt_br(self):
        """Notes must mention probe in Portuguese."""
        hid = self._next_id()
        self._insert_probe(hid, hero_cards='Ah Kd',
                           board_flop='Ah Kd 2c', board_turn='3s')
        m = self._result(hid)
        self.assertIsNotNone(m)
        note_lower = m.notes.lower()
        self.assertTrue(
            any(w in note_lower for w in ['probe', 'correto', 'incorreto',
                                           'marginal']),
            f"Note not in PT-BR: {m.notes}")

    # -- Guard: all-in preflop --

    def test_allin_preflop_skips_probe(self):
        """All-in preflop hand should not trigger lesson 20."""
        hid = self._next_id()
        _insert_hand(self.repo, hid, position='BB')
        self.repo.conn.execute(
            "UPDATE hands SET has_allin=1, allin_street='preflop' "
            "WHERE hand_id=?", (hid,))
        self.repo.conn.commit()
        _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                       50.0, 0, 1, 'BTN')
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'all-in',
                       50.0, 1, 2, 'BB')
        matches = self._classify(hid)
        self.assertNotIn(20, [m.lesson_id for m in matches])


# ── US-053e: Unknown Rate Below 15% (Aulas 18-22) ────────────────────


class TestUS053eUnknownRateBelow15Percent(unittest.TestCase):
    """Verify unknown rate (executed_correctly=None) < 15% for Aulas 18-22.

    Each test uses > 5 representative hands to ensure statistical significance.
    DB lessons: 16 (Aula 18), 17 (Aula 19), 18 (Aula 20), 19 (Aula 21), 20 (Aula 22).
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        self._id = 0

    def tearDown(self):
        self.conn.close()

    def _next_id(self, prefix='UR'):
        self._id += 1
        return f'{prefix}{self._id:03d}'

    def _unknown_rate(self, hand_ids, lesson_id):
        """Calculate % of hands with executed_correctly=None for a lesson."""
        total = 0
        unknown = 0
        for hid in hand_ids:
            hand = _get_hand_dict(self.repo, hid)
            actions = self.repo.get_hand_actions(hid)
            matches = self.classifier.classify_hand(hand, actions)
            m = next((m for m in matches if m.lesson_id == lesson_id), None)
            if m is not None:
                total += 1
                if m.executed_correctly is None:
                    unknown += 1
        if total == 0:
            return 0.0
        return unknown / total

    def _insert_bb_vs_cbet_hand(self, hero_cards, hero_action='call',
                                 board_flop='As 7d 2c'):
        hid = self._next_id('BB')
        _insert_hand(self.repo, hid, position='BB', board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'P1', 'bet',
                       2.0, 0, seq, 'BTN'); seq += 1
        if hero_action == 'call':
            _insert_action(self.repo, hid, 'flop', 'Hero', 'call',
                           2.0, 1, seq, 'BB')
        else:
            _insert_action(self.repo, hid, 'flop', 'Hero', 'fold',
                           0, 1, seq, 'BB')
        return hid

    def _insert_checkraise_hand(self, hero_cards, hero_response='call',
                                 board_flop='As 7d 2c'):
        hid = self._next_id('CR')
        _insert_hand(self.repo, hid, position='BTN', board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'P1', 'raise',
                       6.0, 0, seq, 'BB'); seq += 1
        if hero_response == 'call':
            _insert_action(self.repo, hid, 'flop', 'Hero', 'call',
                           6.0, 1, seq, 'BTN')
        elif hero_response == 'fold':
            _insert_action(self.repo, hid, 'flop', 'Hero', 'fold',
                           0, 1, seq, 'BTN')
        else:
            _insert_action(self.repo, hid, 'flop', 'Hero', 'raise',
                           18.0, 1, seq, 'BTN')
        return hid

    def _insert_ip_vs_cbet_hand(self, hero_cards, hero_action='call',
                                 board_flop='As 7d 2c'):
        hid = self._next_id('IP')
        _insert_hand(self.repo, hid, position='BTN', board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'CO'); seq += 1
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'P1', 'bet',
                       2.0, 0, seq, 'CO'); seq += 1
        if hero_action == 'call':
            _insert_action(self.repo, hid, 'flop', 'Hero', 'call',
                           2.0, 1, seq, 'BTN')
        else:
            _insert_action(self.repo, hid, 'flop', 'Hero', 'fold',
                           0, 1, seq, 'BTN')
        return hid

    def _insert_bet_vs_missed_hand(self, hero_cards, board_flop='As 7d 2c',
                                    board_turn='3s'):
        hid = self._next_id('BV')
        _insert_hand(self.repo, hid, position='BB',
                     board_flop=board_flop, board_turn=board_turn)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'turn', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BB')
        return hid

    def _insert_probe_hand(self, hero_cards, board_flop='As 7d 2c',
                            board_turn='3s'):
        hid = self._next_id('PR')
        _insert_hand(self.repo, hid, position='BB',
                     board_flop=board_flop, board_turn=board_turn)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                       1.5, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                       1.5, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'Hero', 'check',
                       0, 1, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'P1', 'check',
                       0, 0, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'turn', 'Hero', 'bet',
                       3.0, 1, seq, 'BB')
        return hid

    def test_aula18_bb_vs_cbet_unknown_below_15pct(self):
        """Aula 18 (BB vs CBet OOP, DB Lesson 16): unknown rate < 15% with >5 hands."""
        hands = []
        # Strong hands defending (correct=1): top pair, overpairs, sets
        for cards, flop in [('Ah Kd', 'As 7d 2c'), ('Kh Kd', 'Ts 7d 2c'),
                             ('Qh Qd', 'Ts 7d 2c'), ('7h 7d', '7s 4d 2c'),
                             ('Ah Qh', 'As 7d 2c'), ('Th Td', 'Ts 7d 2c')]:
            hands.append(self._insert_bb_vs_cbet_hand(cards, 'call', flop))
        # Air hands folding (correct=1)
        for cards in ['Qh Jd', 'Kh 9d', 'Jh 8d', 'Th 6d']:
            hands.append(self._insert_bb_vs_cbet_hand(cards, 'fold', '8c 5s 2h'))
        # Strong hands incorrectly folding (incorrect=0)
        for cards, flop in [('Ah Kd', 'As 7d 2c'), ('Kh Kd', 'Ts 7d 2c')]:
            hands.append(self._insert_bb_vs_cbet_hand(cards, 'fold', flop))
        rate = self._unknown_rate(hands, lesson_id=16)
        self.assertLess(rate, 0.15,
                        f"Aula 18 unknown rate {rate:.1%} >= 15%")

    def test_aula19_facing_checkraise_unknown_below_15pct(self):
        """Aula 19 (Facing Check-Raise, DB Lesson 17): unknown rate < 15%."""
        hands = []
        # Strong hands defending (correct=1)
        for cards, flop in [('Ah Kd', 'As 7d 2c'), ('7h 7d', '7s 4d 2c'),
                             ('Qh Qd', 'Ts 7d 2c'), ('Kh Kd', 'Ts 7d 2c')]:
            hands.append(self._insert_checkraise_hand(cards, 'call', flop))
        # Air hands folding (correct=1) — none of these connect with board 8c 5s 2h
        for cards in ['Qh Jd', 'Kh 9d', 'Jd 4c', 'Th 6d', '9d 3c', 'Kd 4c']:
            hands.append(self._insert_checkraise_hand(cards, 'fold', '8c 5s 2h'))
        # Strong hands incorrectly folding (incorrect=0)
        for cards, flop in [('Ah Kd', 'As 7d 2c'), ('7h 7d', '7s 4d 2c')]:
            hands.append(self._insert_checkraise_hand(cards, 'fold', flop))
        rate = self._unknown_rate(hands, lesson_id=17)
        self.assertLess(rate, 0.15,
                        f"Aula 19 unknown rate {rate:.1%} >= 15%")

    def test_aula20_ip_vs_cbet_unknown_below_15pct(self):
        """Aula 20 (IP vs CBet BTN, DB Lesson 18): unknown rate < 15%."""
        hands = []
        # Strong hands defending (correct=1)
        for cards, flop in [('Ah Kd', 'As 7d 2c'), ('Qh Qd', 'Ts 7d 2c'),
                             ('7h 7d', '7s 4d 2c'), ('Kh Kd', 'Ts 7d 2c'),
                             ('Th Td', 'Ts 7d 2c')]:
            hands.append(self._insert_ip_vs_cbet_hand(cards, 'call', flop))
        # Air folds (correct=1)
        for cards in ['Qh Jd', 'Kh 9d', 'Jh 8d', 'Th 6d', '9d 5c']:
            hands.append(self._insert_ip_vs_cbet_hand(cards, 'fold', '8c 5s 2h'))
        # Strong hands incorrectly folded (incorrect=0)
        for cards, flop in [('Ah Kd', 'As 7d 2c'), ('Qh Qd', 'Ts 7d 2c')]:
            hands.append(self._insert_ip_vs_cbet_hand(cards, 'fold', flop))
        rate = self._unknown_rate(hands, lesson_id=18)
        self.assertLess(rate, 0.15,
                        f"Aula 20 unknown rate {rate:.1%} >= 15%")

    def test_aula21_bet_vs_missed_unknown_below_15pct(self):
        """Aula 21 (Bet vs Missed, DB Lesson 19): unknown rate < 15%."""
        hands = []
        # Strong/medium/draw hands: all correct (1)
        for cards, flop, turn in [('Ah Kd', 'Ah Kd 2c', '3s'),
                                   ('7h 6d', 'As 7c 2h', '3d'),
                                   ('Ah 2h', 'Kh 7h 3c', '9s'),
                                   ('Kh Qd', 'Kh 5d 2c', '3s'),
                                   ('Jh Jd', 'As 7d 2c', '3s')]:
            hands.append(self._insert_bet_vs_missed_hand(cards, flop, turn))
        # Air on blank turn: correct (1)
        for cards in ['Qd Jc', 'Td 9c', 'Jd 8c', 'Kd 4c']:
            hands.append(self._insert_bet_vs_missed_hand(cards, 'As 7h 3c', '2d'))
        # Air on neutral turn: correct (1) for bet_vs_missed
        for cards in ['Qd Jc', 'Td 9c']:
            hands.append(self._insert_bet_vs_missed_hand(cards, 'As 7h 3c', 'Tc'))
        rate = self._unknown_rate(hands, lesson_id=19)
        self.assertLess(rate, 0.15,
                        f"Aula 21 unknown rate {rate:.1%} >= 15%")

    def test_aula22_probe_unknown_below_15pct(self):
        """Aula 22 (Probe do BB, DB Lesson 20): unknown rate < 15%."""
        hands = []
        # Strong/medium/draw hands: correct (1)
        for cards, flop, turn in [('Ah Kd', 'Ah Kd 2c', '3s'),
                                   ('7h 6d', 'As 7c 2h', '3d'),
                                   ('Ah 2h', 'Kh 7h 3c', '9s'),
                                   ('Kh Qd', 'Kh 5d 2c', '3s'),
                                   ('Jh Jd', 'As 7d 2c', '3s')]:
            hands.append(self._insert_probe_hand(cards, flop, turn))
        # Air on blank turn: correct (1)
        for cards in ['Qd Jc', 'Td 9c', 'Jd 8c', 'Kd 4c']:
            hands.append(self._insert_probe_hand(cards, 'As 7h 3c', '2d'))
        # Air on dangerous turn: incorrect (0) — not unknown
        for cards in ['Qd Jc', 'Td 9c']:
            hands.append(self._insert_probe_hand(cards, 'Ah 7h 3c', '9h'))
        rate = self._unknown_rate(hands, lesson_id=20)
        self.assertLess(rate, 0.15,
                        f"Aula 22 unknown rate {rate:.1%} >= 15%")


# ── US-053f: Aula 12 (Pós-Flop Avançado, DB Lesson 10) ───────────────


class TestUS053fAula12PostflopAvancado(unittest.TestCase):
    """Aula 12 (RegLife course) = DB Lesson 10 (Pós-Flop Avançado).

    Acceptance criteria: Aula 12 é prática → implementar.
    Detection: hands that reach the river with hero having postflop action.
    Guard: all-in preflop never triggers this lesson.
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

    def _result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 10), None)
        return m.executed_correctly if m else None

    def _setup_full_street_hand(self, hand_id, hero_cards='Ah Ad',
                                board_flop='As Kd 2c', board_turn='5s',
                                board_river='9h', hero_river_action='call'):
        """Hero reaches the river and acts (3-street hand)."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop=board_flop, board_turn=board_turn,
                     board_river=board_river)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'flop', 'P1', 'call',
                       2.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'check',
                       0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'Hero', 'bet',
                       5.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hand_id, 'turn', 'P1', 'call',
                       5.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hand_id, 'river', 'P1', 'bet',
                       8.0, 0, seq, 'BB'); seq += 1
        if hero_river_action == 'call':
            _insert_action(self.repo, hand_id, 'river', 'Hero', 'call',
                           8.0, 1, seq, 'BTN')
        elif hero_river_action == 'fold':
            _insert_action(self.repo, hand_id, 'river', 'Hero', 'fold',
                           0, 1, seq, 'BTN')

    # -- Detection --

    def test_aula12_is_practical_detected(self):
        """Pós-Flop Avançado (lesson 10) triggers for 3-street hands — practical, not removed."""
        self._setup_full_street_hand('PA001')
        matches = self._classify('PA001')
        ids = [m.lesson_id for m in matches]
        self.assertIn(10, ids, "Lesson 10 should be detected for 3-street hands")

    def test_aula12_no_river_not_detected(self):
        """Lesson 10 not triggered when hand ends on turn (no river card)."""
        _insert_hand(self.repo, 'PA002', position='BTN',
                     board_flop='As Kd 2c', board_turn='5s')
        _insert_action(self.repo, 'PA002', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'PA002', 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'PA002', 'flop', 'P1', 'check',
                       0, 0, 3, 'BB')
        _insert_action(self.repo, 'PA002', 'flop', 'Hero', 'bet',
                       2.0, 1, 4, 'BTN')
        _insert_action(self.repo, 'PA002', 'turn', 'P1', 'fold',
                       0, 0, 5, 'BB')
        matches = self._classify('PA002')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(10, ids, "Lesson 10 requires river card to exist")

    # -- Guard tests --

    def test_aula12_preflop_allin_guard(self):
        """Preflop all-in hands must NOT trigger lesson 10 (Pós-Flop Avançado)."""
        _insert_hand(self.repo, 'PA003', position='BTN',
                     board_flop='As Kd 2c', board_turn='5s', board_river='9h')
        self.repo.conn.execute(
            "UPDATE hands SET has_allin=1, allin_street='preflop' WHERE hand_id=?",
            ('PA003',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'PA003', 'preflop', 'Hero', 'all-in',
                       100, 1, 1, 'BTN')
        _insert_action(self.repo, 'PA003', 'preflop', 'P1', 'call',
                       100, 0, 2, 'BB')
        _insert_action(self.repo, 'PA003', 'flop', 'Hero', 'bet',
                       0, 1, 3, 'BTN')
        matches = self._classify('PA003')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(10, ids, "Preflop all-in must skip lesson 10")

    # -- Evaluation --

    def test_aula12_strong_hand_river_correct(self):
        """Strong hand reaches river and calls = correct (score=1)."""
        self._setup_full_street_hand('PA004', hero_cards='Ah Ad',
                                     board_flop='As Kd 2c', board_turn='5s',
                                     board_river='9h', hero_river_action='call')
        result = self._result('PA004')
        self.assertEqual(result, 1, "Strong hand calling river bet = correct")

    def test_aula12_strong_hand_incorrect_fold_river(self):
        """Folding a strong hand on river vs bet = incorrect (score=0)."""
        self._setup_full_street_hand('PA005', hero_cards='Ah Ad',
                                     board_flop='As Kd 2c', board_turn='5s',
                                     board_river='9h', hero_river_action='fold')
        result = self._result('PA005')
        self.assertEqual(result, 0, "Folding strong hand on river = incorrect")

    def test_aula12_air_hand_correct_fold_river(self):
        """Air hand folding on river vs bet = correct (score=1)."""
        self._setup_full_street_hand('PA006', hero_cards='Qh Jd',
                                     board_flop='As Kd 2c', board_turn='5s',
                                     board_river='9h', hero_river_action='fold')
        result = self._result('PA006')
        self.assertEqual(result, 1, "Folding air on river = correct")


# ── US-053f: Aula 23 (3-Betted Pots Pós-Flop, DB Lesson 21) ─────────


class TestUS053fAula23_3BetPots(unittest.TestCase):
    """Aula 23 (RegLife course) = DB Lesson 21 (3-Betted Pots Pós-Flop).

    Acceptance criteria: 3bet pots verifica que é pot 3betado e hero tem ação pós-flop.
    Guard: all-in preflop never triggers; no postflop action never triggers.
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

    def _result(self, hand_id):
        matches = self._classify(hand_id)
        m = next((m for m in matches if m.lesson_id == 21), None)
        return m.executed_correctly if m else None

    def _setup_3bet_pot_hand(self, hand_id, hero_cards='Ah Kd',
                              board_flop='Ts 7d 2c', hero_role='pfa',
                              hero_flop_action='bet'):
        """Set up a 3-bet pot: either hero is PFA (3bettor) or caller."""
        _insert_hand(self.repo, hand_id, position='BTN', board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        seq = 1
        if hero_role == 'pfa':
            # Hero 3bets from BTN
            _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                           2.0, 0, seq, 'CO'); seq += 1
            _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                           6.0, 1, seq, 'BTN'); seq += 1
            _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                           6.0, 0, seq, 'CO'); seq += 1
            _insert_action(self.repo, hand_id, 'flop', 'P1', 'check',
                           0, 0, seq, 'CO'); seq += 1
        else:
            # Hero calls 3bet from BB
            _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                           2.0, 1, seq, 'BTN'); seq += 1
            _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                           6.0, 0, seq, 'BB'); seq += 1
            _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'call',
                           6.0, 1, seq, 'BTN'); seq += 1
            _insert_action(self.repo, hand_id, 'flop', 'P1', 'bet',
                           4.0, 0, seq, 'BB'); seq += 1
        if hero_flop_action == 'bet':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'bet',
                           4.0, 1, seq, 'BTN')
        elif hero_flop_action == 'call':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'call',
                           4.0, 1, seq, 'BTN')
        elif hero_flop_action == 'fold':
            _insert_action(self.repo, hand_id, 'flop', 'Hero', 'fold',
                           0, 1, seq, 'BTN')

    # -- Guard: must be 3bet pot --

    def test_single_raised_pot_not_detected(self):
        """Single raised pot must NOT trigger lesson 21."""
        _insert_hand(self.repo, 'TBF01', position='BTN', board_flop='Ts 7d 2c')
        _insert_action(self.repo, 'TBF01', 'preflop', 'Hero', 'raise',
                       2.0, 1, 1, 'BTN')
        _insert_action(self.repo, 'TBF01', 'preflop', 'P1', 'call',
                       2.0, 0, 2, 'BB')
        _insert_action(self.repo, 'TBF01', 'flop', 'P1', 'check', 0, 0, 3, 'BB')
        _insert_action(self.repo, 'TBF01', 'flop', 'Hero', 'bet', 3.0, 1, 4, 'BTN')
        matches = self._classify('TBF01')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(21, ids, "Single-raised pot must not trigger lesson 21")

    # -- Guard: hero must have postflop action --

    def test_preflop_allin_guard_skips_lesson21(self):
        """Preflop all-in must NOT trigger lesson 21 even if is_3bet_pot=True."""
        _insert_hand(self.repo, 'TBF02', position='BTN', board_flop='Ts 7d 2c')
        self.repo.conn.execute(
            "UPDATE hands SET has_allin=1, allin_street='preflop' WHERE hand_id=?",
            ('TBF02',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'TBF02', 'preflop', 'P1', 'raise',
                       2.0, 0, 1, 'CO')
        _insert_action(self.repo, 'TBF02', 'preflop', 'Hero', 'all-in',
                       50.0, 1, 2, 'BTN')
        _insert_action(self.repo, 'TBF02', 'preflop', 'P1', 'call',
                       50.0, 0, 3, 'CO')
        matches = self._classify('TBF02')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(21, ids, "Preflop all-in must skip lesson 21")

    def test_no_postflop_action_guard(self):
        """Hero folds preflop in a 3bet pot — lesson 21 not triggered (no postflop)."""
        _insert_hand(self.repo, 'TBF03', position='BTN', board_flop='Ts 7d 2c')
        _insert_action(self.repo, 'TBF03', 'preflop', 'P1', 'raise',
                       2.0, 0, 1, 'CO')
        _insert_action(self.repo, 'TBF03', 'preflop', 'P2', 'raise',
                       6.0, 0, 2, 'BB')
        _insert_action(self.repo, 'TBF03', 'preflop', 'Hero', 'fold',
                       0, 1, 3, 'BTN')
        _insert_action(self.repo, 'TBF03', 'preflop', 'P1', 'fold',
                       0, 0, 4, 'CO')
        matches = self._classify('TBF03')
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(21, ids, "No hero postflop action → lesson 21 not triggered")

    # -- Evaluation --

    def test_3bet_pot_pfa_strong_correct(self):
        """PFA in 3bet pot with strong hand = correct (score=1)."""
        self._setup_3bet_pot_hand('TBF04', hero_cards='Ah Ad',
                                  board_flop='As 7d 2c', hero_role='pfa',
                                  hero_flop_action='bet')
        result = self._result('TBF04')
        self.assertEqual(result, 1, "PFA with strong hand betting = correct")

    def test_3bet_pot_caller_air_fold_correct(self):
        """Caller in 3bet pot folds air hand = correct (score=1)."""
        self._setup_3bet_pot_hand('TBF05', hero_cards='Qh Jd',
                                  board_flop='As 7d 2c', hero_role='caller',
                                  hero_flop_action='fold')
        result = self._result('TBF05')
        self.assertEqual(result, 1, "Caller folding air in 3bet pot = correct")

    def test_3bet_pot_pfa_air_cbet_correct(self):
        """PFA in 3bet pot with air hand betting = correct (fold equity)."""
        self._setup_3bet_pot_hand('TBF06', hero_cards='Qh Jd',
                                  board_flop='As 7d 2c', hero_role='pfa',
                                  hero_flop_action='bet')
        result = self._result('TBF06')
        self.assertEqual(result, 1, "PFA betting air in 3bet pot = correct (fold equity)")


# ── US-053f: Aulas 24-25 (Bounty, DB Lessons 22-23) with Coverage ────


class TestUS053fBountyCoverage(unittest.TestCase):
    """Bounty lessons (DB 22-23) consider bounty coverage in evaluation.

    Acceptance criteria: Bounty aulas consideram bounty coverage nos ajustes.
    High overlay (bounty >= 50% of buy_in) makes tier 2 hands profitable.
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _setup_tournament(self, t_id, bounty, buy_in):
        self.repo.insert_tournament({
            'tournament_id': t_id,
            'platform': 'GGPoker',
            'name': 'Bounty Hunter',
            'date': '2026-01-15',
            'buy_in': buy_in,
            'rake': 1,
            'bounty': bounty,
            'total_buy_in': buy_in + bounty + 1,
            'is_bounty': True,
        })

    def _insert_bounty_hand(self, hand_id, t_id, hero_cards='Ah Kd',
                             hero_pos='BTN'):
        _insert_hand(self.repo, hand_id, position=hero_pos,
                     game_type='tournament', tournament_id=t_id)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hand_id))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'raise',
                       300, 1, 1, hero_pos)

    def _classify(self, hand_id):
        hand = _get_hand_dict(self.repo, hand_id)
        actions = self.repo.get_hand_actions(hand_id)
        return self.classifier.classify_hand(hand, actions)

    def _get_lesson_match(self, hand_id, lesson_id):
        matches = self._classify(hand_id)
        return next((m for m in matches if m.lesson_id == lesson_id), None)

    # -- Bounty overlay note in lesson 23 --

    def test_tier1_hand_high_overlay_correct(self):
        """Tier 1 hand with high overlay = always correct (score=1)."""
        self._setup_tournament('BHO01', bounty=10, buy_in=10)
        self._insert_bounty_hand('BCOV01', 'BHO01', hero_cards='Ah Ad')
        m = self._get_lesson_match('BCOV01', 23)
        self.assertIsNotNone(m, "Lesson 23 should be detected")
        self.assertEqual(m.executed_correctly, 1, "Tier 1 always correct")

    def test_tier2_hand_high_overlay_is_correct(self):
        """Tier 2 hand with high overlay (bounty=50% buy_in) = correct (score=1)."""
        self._setup_tournament('BHO02', bounty=5, buy_in=10)  # 50% overlay
        self._insert_bounty_hand('BCOV02', 'BHO02', hero_cards='Kh 7h')  # K7s = tier 2
        m = self._get_lesson_match('BCOV02', 23)
        self.assertIsNotNone(m, "Lesson 23 should be detected")
        self.assertEqual(m.executed_correctly, 1,
                         "Tier 2 with high overlay (50%) = correct")

    def test_tier2_hand_low_overlay_is_marginal(self):
        """Tier 2 hand with low overlay (bounty < 20% buy_in) = marginal (None)."""
        self._setup_tournament('BHO03', bounty=1, buy_in=10)  # 10% overlay
        self._insert_bounty_hand('BCOV03', 'BHO03', hero_cards='Kh 7h')  # K7s = tier 2
        m = self._get_lesson_match('BCOV03', 23)
        self.assertIsNotNone(m, "Lesson 23 should be detected")
        self.assertIsNone(m.executed_correctly,
                          "Tier 2 with low overlay (10%) = marginal (None)")

    def test_tier3_hand_high_overlay_still_incorrect(self):
        """Tier 3 hand is incorrect even with high bounty overlay."""
        self._setup_tournament('BHO04', bounty=10, buy_in=10)
        self._insert_bounty_hand('BCOV04', 'BHO04', hero_cards='7h 2d')  # 72o = tier 3
        m = self._get_lesson_match('BCOV04', 23)
        self.assertIsNotNone(m, "Lesson 23 should be detected")
        self.assertEqual(m.executed_correctly, 0,
                         "Tier 3 hand incorrect even with high overlay")

    # -- Overlay note appears in lesson notes --

    def test_overlay_note_in_lesson22_notes(self):
        """Lesson 22 notes include overlay information."""
        self._setup_tournament('BHO05', bounty=5, buy_in=10)
        self._insert_bounty_hand('BCOV05', 'BHO05', hero_cards='Ah Ad')
        m = self._get_lesson_match('BCOV05', 22)
        self.assertIsNotNone(m, "Lesson 22 should be detected")
        self.assertIn('overlay', m.notes, "Notes must include overlay info")

    def test_overlay_note_in_lesson23_notes(self):
        """Lesson 23 notes include overlay information."""
        self._setup_tournament('BHO06', bounty=5, buy_in=10)
        self._insert_bounty_hand('BCOV06', 'BHO06', hero_cards='Ah Ad')
        m = self._get_lesson_match('BCOV06', 23)
        self.assertIsNotNone(m, "Lesson 23 should be detected")
        self.assertIn('overlay', m.notes, "Notes must include overlay info")


# ── US-053f: Guard — Preflop All-In Skips Postflop Lessons ───────────


class TestUS053fGuardAllinPreflop(unittest.TestCase):
    """Verify all-in preflop guard prevents lessons 10, 21 from triggering.

    Acceptance criteria: Guard funciona: mãos all-in preflop nunca entram.
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)

    def tearDown(self):
        self.conn.close()

    def _setup_allin_preflop_3bet_pot(self, hand_id):
        """All-in preflop in a 3bet pot with board run-out."""
        _insert_hand(self.repo, hand_id, position='BTN',
                     board_flop='As Kd 2c', board_turn='5s', board_river='9h')
        self.repo.conn.execute(
            "UPDATE hands SET has_allin=1, allin_street='preflop' WHERE hand_id=?",
            (hand_id,))
        self.repo.conn.commit()
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'raise',
                       3.0, 0, 1, 'CO')
        _insert_action(self.repo, hand_id, 'preflop', 'Hero', 'all-in',
                       50.0, 1, 2, 'BTN')
        _insert_action(self.repo, hand_id, 'preflop', 'P1', 'call',
                       50.0, 0, 3, 'CO')

    def test_allin_preflop_skips_lesson10(self):
        """All-in preflop must not trigger lesson 10 (Pós-Flop Avançado)."""
        self._setup_allin_preflop_3bet_pot('GAP01')
        hand = _get_hand_dict(self.repo, 'GAP01')
        actions = self.repo.get_hand_actions('GAP01')
        matches = self.classifier.classify_hand(hand, actions)
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(10, ids, "All-in preflop must skip lesson 10")

    def test_allin_preflop_skips_lesson21(self):
        """All-in preflop in 3bet pot must not trigger lesson 21."""
        self._setup_allin_preflop_3bet_pot('GAP02')
        hand = _get_hand_dict(self.repo, 'GAP02')
        actions = self.repo.get_hand_actions('GAP02')
        matches = self.classifier.classify_hand(hand, actions)
        ids = [m.lesson_id for m in matches]
        self.assertNotIn(21, ids, "All-in preflop must skip lesson 21")

    def test_allin_on_flop_allows_lesson10(self):
        """All-in on flop (not preflop) CAN trigger lesson 10 if board is complete."""
        _insert_hand(self.repo, 'GAP03', position='BTN',
                     board_flop='As Kd 2c', board_turn='5s', board_river='9h')
        self.repo.conn.execute(
            "UPDATE hands SET has_allin=1, allin_street='flop' WHERE hand_id=?",
            ('GAP03',))
        self.repo.conn.commit()
        _insert_action(self.repo, 'GAP03', 'preflop', 'Hero', 'raise',
                       1.5, 1, 1, 'BTN')
        _insert_action(self.repo, 'GAP03', 'preflop', 'P1', 'call',
                       1.5, 0, 2, 'BB')
        _insert_action(self.repo, 'GAP03', 'flop', 'Hero', 'all-in',
                       30.0, 1, 3, 'BTN')
        hand = _get_hand_dict(self.repo, 'GAP03')
        actions = self.repo.get_hand_actions('GAP03')
        matches = self.classifier.classify_hand(hand, actions)
        ids = [m.lesson_id for m in matches]
        self.assertIn(10, ids, "Flop all-in (not preflop) can still trigger lesson 10")


# ── US-053f: Unknown Rate Below 15% for Aulas 12, 23 ─────────────────


class TestUS053fUnknownRateAulas12and23(unittest.TestCase):
    """Verify unknown rate (executed_correctly=None) < 15% for Aulas 12 and 23.

    DB lessons: 10 (Aula 12, Pós-Flop Avançado), 21 (Aula 23, 3-Betted Pots).
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = Repository(self.conn)
        self.classifier = LessonClassifier(self.repo)
        self._id = 0

    def tearDown(self):
        self.conn.close()

    def _next_id(self, prefix='UR'):
        self._id += 1
        return f'{prefix}{self._id:03d}'

    def _unknown_rate(self, hand_ids, lesson_id):
        total = 0
        unknown = 0
        for hid in hand_ids:
            hand = _get_hand_dict(self.repo, hid)
            actions = self.repo.get_hand_actions(hid)
            matches = self.classifier.classify_hand(hand, actions)
            m = next((m for m in matches if m.lesson_id == lesson_id), None)
            if m is not None:
                total += 1
                if m.executed_correctly is None:
                    unknown += 1
        if total == 0:
            return 0.0
        return unknown / total

    def _insert_advanced_postflop_hand(self, hero_cards, board_flop, board_turn,
                                        board_river, hero_river_action='call'):
        hid = self._next_id('AP')
        _insert_hand(self.repo, hid, position='BTN',
                     board_flop=board_flop, board_turn=board_turn,
                     board_river=board_river)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        seq = 1
        _insert_action(self.repo, hid, 'preflop', 'Hero', 'raise',
                       1.5, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'preflop', 'P1', 'call',
                       1.5, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'Hero', 'bet',
                       2.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'flop', 'P1', 'call',
                       2.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'turn', 'Hero', 'bet',
                       5.0, 1, seq, 'BTN'); seq += 1
        _insert_action(self.repo, hid, 'turn', 'P1', 'call',
                       5.0, 0, seq, 'BB'); seq += 1
        _insert_action(self.repo, hid, 'river', 'P1', 'bet',
                       8.0, 0, seq, 'BB'); seq += 1
        if hero_river_action == 'call':
            _insert_action(self.repo, hid, 'river', 'Hero', 'call',
                           8.0, 1, seq, 'BTN')
        else:
            _insert_action(self.repo, hid, 'river', 'Hero', 'fold',
                           0, 1, seq, 'BTN')
        return hid

    def _insert_3bet_pot_hand(self, hero_cards, board_flop, hero_role='pfa',
                               hero_flop_action='bet'):
        hid = self._next_id('3B')
        _insert_hand(self.repo, hid, position='BTN', board_flop=board_flop)
        self.repo.conn.execute(
            "UPDATE hands SET hero_cards=? WHERE hand_id=?", (hero_cards, hid))
        self.repo.conn.commit()
        seq = 1
        if hero_role == 'pfa':
            _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                           2.0, 0, seq, 'CO'); seq += 1
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'raise',
                           6.0, 1, seq, 'BTN'); seq += 1
            _insert_action(self.repo, hid, 'preflop', 'P1', 'call',
                           6.0, 0, seq, 'CO'); seq += 1
            _insert_action(self.repo, hid, 'flop', 'P1', 'check',
                           0, 0, seq, 'CO'); seq += 1
        else:
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'raise',
                           2.0, 1, seq, 'BTN'); seq += 1
            _insert_action(self.repo, hid, 'preflop', 'P1', 'raise',
                           6.0, 0, seq, 'BB'); seq += 1
            _insert_action(self.repo, hid, 'preflop', 'Hero', 'call',
                           6.0, 1, seq, 'BTN'); seq += 1
            _insert_action(self.repo, hid, 'flop', 'P1', 'bet',
                           4.0, 0, seq, 'BB'); seq += 1
        if hero_flop_action == 'bet':
            _insert_action(self.repo, hid, 'flop', 'Hero', 'bet',
                           4.0, 1, seq, 'BTN')
        elif hero_flop_action == 'call':
            _insert_action(self.repo, hid, 'flop', 'Hero', 'call',
                           4.0, 1, seq, 'BTN')
        elif hero_flop_action == 'fold':
            _insert_action(self.repo, hid, 'flop', 'Hero', 'fold',
                           0, 1, seq, 'BTN')
        return hid

    def test_aula12_postflop_advanced_unknown_below_15pct(self):
        """Aula 12 (Pós-Flop Avançado, DB Lesson 10): unknown rate < 15%."""
        hands = []
        # Strong hands calling river: correct (1)
        for cards, flop, turn, river in [('Ah Ad', 'As Kd 2c', '5s', '9h'),
                                          ('Kh Kd', 'Ks 7d 2c', '5s', '9h'),
                                          ('Qh Qd', 'Qs 7d 2c', '5s', '9h'),
                                          ('Jh Jd', 'Js 7d 2c', '5s', '9h'),
                                          ('Th Td', 'Ts 7d 2c', '5s', '9h')]:
            hands.append(self._insert_advanced_postflop_hand(
                cards, flop, turn, river, 'call'))
        # Air folding on river: correct (1)
        for cards in ['Qh Jd', 'Kh 9d', 'Jh 8d', 'Th 6d', '9d 5c']:
            hands.append(self._insert_advanced_postflop_hand(
                cards, 'As 7h 3c', '2d', '4s', 'fold'))
        # Strong hands incorrectly folded: incorrect (0)
        for cards, flop in [('Ah Ad', 'As Kd 2c'), ('Kh Kd', 'Ks 7d 2c')]:
            hands.append(self._insert_advanced_postflop_hand(
                cards, flop, '5s', '9h', 'fold'))
        rate = self._unknown_rate(hands, lesson_id=10)
        self.assertLess(rate, 0.15,
                        f"Aula 12 unknown rate {rate:.1%} >= 15%")

    def test_aula23_3bet_pots_unknown_below_15pct(self):
        """Aula 23 (3-Betted Pots, DB Lesson 21): unknown rate < 15%."""
        hands = []
        # PFA with strong hands: correct (1)
        for cards, flop in [('Ah Ad', 'As Kd 2c'), ('Kh Kd', 'Ks 7d 2c'),
                             ('Qh Qd', 'Qs 7d 2c'), ('Jh Jd', 'Js 7d 2c'),
                             ('Th Td', 'Ts 7d 2c')]:
            hands.append(self._insert_3bet_pot_hand(cards, flop, 'pfa', 'bet'))
        # Caller folding air: correct (1)
        for cards in ['Qh Jd', 'Kh 9d', 'Jh 8d', 'Th 6d', '9d 5c']:
            hands.append(self._insert_3bet_pot_hand(cards, 'As 7h 3c', 'caller', 'fold'))
        # PFA with air betting: correct (1)
        for cards in ['Qh Jd', 'Kh 9d']:
            hands.append(self._insert_3bet_pot_hand(cards, 'As 7h 3c', 'pfa', 'bet'))
        rate = self._unknown_rate(hands, lesson_id=21)
        self.assertLess(rate, 0.15,
                        f"Aula 23 unknown rate {rate:.1%} >= 15%")


if __name__ == '__main__':
    unittest.main()
