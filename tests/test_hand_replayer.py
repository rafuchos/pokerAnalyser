"""Tests for US-055: Hand Replayer."""

import json
import os
import sqlite3
import tempfile
import unittest

from src.web.app import create_app
from src.web.data import prepare_hand_replayer, _build_replay_steps
from src.db.schema import init_db


# ── Helpers ───────────────────────────────────────────────────────


def _make_poker_db(path: str) -> None:
    """Create a minimal poker.db with one hand and actions."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Insert a cash hand
    conn.execute(
        "INSERT INTO hands (hand_id, platform, game_type, date, "
        "blinds_sb, blinds_bb, hero_cards, hero_position, "
        "invested, won, net, rake, table_name, num_players, "
        "board_flop, board_turn, board_river, pot_total, "
        "opponent_cards, has_allin) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            'TEST001', 'GGPoker', 'cash', '2026-03-16T18:00:00',
            0.25, 0.50, 'Ah Kd', 'BTN',
            5.50, 15.00, 9.50, 0.25, 'Table1', 6,
            'Ac 2h 7d', 'Ks', '3c', 17.50,
            'Qh Qd', 0,
        ),
    )

    # Insert actions: preflop
    actions = [
        # (hand_id, street, player, action_type, amount, is_hero, seq, position, is_voluntary)
        ('TEST001', 'preflop', 'Player1', 'post_sb', 0.25, 0, 0, 'SB', 0),
        ('TEST001', 'preflop', 'Hero',    'post_bb', 0.50, 1, 1, 'BB', 0),
        ('TEST001', 'preflop', 'Player3', 'raise',   2.00, 0, 2, 'UTG', 1),
        ('TEST001', 'preflop', 'Player4', 'fold',    0.00, 0, 3, 'MP', 0),
        ('TEST001', 'preflop', 'Player5', 'fold',    0.00, 0, 4, 'CO', 0),
        ('TEST001', 'preflop', 'Hero',    'raise',   6.00, 1, 5, 'BTN', 1),
        ('TEST001', 'preflop', 'Player1', 'fold',    0.00, 0, 6, 'SB', 0),
        ('TEST001', 'preflop', 'Hero',    'fold',    0.00, 1, 7, 'BB', 0),
        # Oops – let's make it a call instead so we get a flop
    ]
    conn.executemany(
        "INSERT INTO hand_actions (hand_id, street, player, action_type, amount, "
        "is_hero, sequence_order, position, is_voluntary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        actions,
    )

    # Postflop actions
    postflop_actions = [
        ('TEST001', 'flop', 'Player3', 'check',  0.00, 0, 0, 'UTG', 0),
        ('TEST001', 'flop', 'Hero',    'bet',     4.00, 1, 1, 'BTN', 0),
        ('TEST001', 'flop', 'Player3', 'call',    4.00, 0, 2, 'UTG', 0),
        ('TEST001', 'turn', 'Player3', 'check',   0.00, 0, 0, 'UTG', 0),
        ('TEST001', 'turn', 'Hero',    'bet',     8.00, 1, 1, 'BTN', 0),
        ('TEST001', 'turn', 'Player3', 'fold',    0.00, 0, 2, 'UTG', 0),
    ]
    conn.executemany(
        "INSERT INTO hand_actions (hand_id, street, player, action_type, amount, "
        "is_hero, sequence_order, position, is_voluntary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        postflop_actions,
    )

    # Insert a second hand (tournament) for cross-type testing
    conn.execute(
        "INSERT INTO hands (hand_id, platform, game_type, date, "
        "blinds_sb, blinds_bb, hero_cards, hero_position, "
        "invested, won, net, rake, table_name, num_players) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            'TOURN001', 'GGPoker', 'tournament', '2026-03-16T19:00:00',
            100, 200, '5c 5d', 'CO',
            400, 0, -400, 0, 'Final Table', 6,
        ),
    )
    conn.execute(
        "INSERT INTO hand_actions (hand_id, street, player, action_type, amount, "
        "is_hero, sequence_order, position, is_voluntary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ('TOURN001', 'preflop', 'Hero', 'raise', 600, 1, 0, 'CO', 1),
    )

    # Insert lesson + hand_lessons for lesson query test
    conn.execute(
        "INSERT INTO lessons (lesson_id, title, category, subcategory, sort_order) "
        "VALUES (?, ?, ?, ?, ?)",
        (99, 'Test Lesson', 'Preflop', 'RFI', 1),
    )
    from datetime import datetime
    conn.execute(
        "INSERT INTO hand_lessons (hand_id, lesson_id, street, executed_correctly, "
        "confidence, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ('TEST001', 99, 'preflop', 1, 1.0, 'Good raise!', datetime.now().isoformat()),
    )

    conn.commit()
    conn.close()


# ── Unit Tests: _build_replay_steps ──────────────────────────────

class TestBuildReplaySteps(unittest.TestCase):

    def _actions(self, specs):
        """Helper to build action dicts from minimal specs."""
        result = []
        for i, (street, player, atype, amount, is_hero, position) in enumerate(specs):
            result.append({
                'street': street,
                'player': player,
                'action_type': atype,
                'amount': amount,
                'is_hero': is_hero,
                'position': position,
                'sequence_order': i,
            })
        return result

    def test_empty_actions(self):
        steps = _build_replay_steps([])
        self.assertEqual(steps, [])

    def test_step_count_matches_actions(self):
        actions = self._actions([
            ('preflop', 'SB', 'post_sb', 0.25, 0, 'SB'),
            ('preflop', 'BB', 'post_bb', 0.50, 1, 'BB'),
            ('preflop', 'UTG', 'fold', 0.0, 0, 'UTG'),
        ])
        steps = _build_replay_steps(actions)
        self.assertEqual(len(steps), 3)

    def test_step_fields(self):
        actions = self._actions([
            ('preflop', 'Hero', 'post_bb', 0.50, 1, 'BB'),
        ])
        steps = _build_replay_steps(actions)
        s = steps[0]
        self.assertEqual(s['idx'], 0)
        self.assertEqual(s['street'], 'preflop')
        self.assertEqual(s['player'], 'Hero')
        self.assertEqual(s['action_type'], 'post_bb')
        self.assertEqual(s['amount'], 0.50)
        self.assertTrue(s['is_hero'])
        self.assertEqual(s['position'], 'BB')
        self.assertIn('pot_before', s)
        self.assertIn('pot_after', s)

    def test_pot_accumulates_posts(self):
        actions = self._actions([
            ('preflop', 'SB', 'post_sb', 0.25, 0, 'SB'),
            ('preflop', 'BB', 'post_bb', 0.50, 1, 'BB'),
        ])
        steps = _build_replay_steps(actions)
        self.assertAlmostEqual(steps[0]['pot_after'], 0.25)
        self.assertAlmostEqual(steps[1]['pot_after'], 0.75)

    def test_pot_call_adds_directly(self):
        actions = self._actions([
            ('preflop', 'SB', 'post_sb', 0.25, 0, 'SB'),
            ('preflop', 'BB', 'post_bb', 0.50, 1, 'BB'),
            ('preflop', 'UTG', 'raise', 2.00, 0, 'UTG'),
            ('preflop', 'BTN', 'call', 2.00, 1, 'BTN'),
        ])
        steps = _build_replay_steps(actions)
        # After SB(0.25) + BB(0.50) + UTG raise to 2.0 (delta=2.0) + BTN call 2.0
        self.assertAlmostEqual(steps[0]['pot_after'], 0.25)
        self.assertAlmostEqual(steps[1]['pot_after'], 0.75)
        self.assertAlmostEqual(steps[2]['pot_after'], 2.75)   # 0.75 + 2.0
        self.assertAlmostEqual(steps[3]['pot_after'], 4.75)   # 2.75 + 2.0

    def test_raise_computes_delta(self):
        """Raise to X should add (X - prev_investment) to pot."""
        actions = self._actions([
            ('preflop', 'BB', 'post_bb', 0.50, 0, 'BB'),
            ('preflop', 'BB', 'raise', 3.00, 0, 'BB'),  # BB 3-bets; already invested 0.50, delta=2.50
        ])
        steps = _build_replay_steps(actions)
        self.assertAlmostEqual(steps[0]['pot_after'], 0.50)
        self.assertAlmostEqual(steps[1]['pot_after'], 3.00)   # 0.50 + 2.50

    def test_fold_and_check_add_zero(self):
        actions = self._actions([
            ('preflop', 'SB', 'post_sb', 0.25, 0, 'SB'),
            ('preflop', 'UTG', 'fold', 0.0, 0, 'UTG'),
            ('flop', 'Hero', 'check', 0.0, 1, 'BTN'),
        ])
        steps = _build_replay_steps(actions)
        self.assertAlmostEqual(steps[1]['pot_after'], 0.25)
        self.assertAlmostEqual(steps[2]['pot_after'], 0.25)

    def test_street_reset_investments(self):
        """Investments reset each street so raise-delta is correct."""
        actions = self._actions([
            ('preflop', 'SB', 'post_sb', 0.25, 0, 'SB'),
            ('preflop', 'BB', 'post_bb', 0.50, 0, 'BB'),
            ('flop', 'SB', 'bet', 1.00, 0, 'SB'),       # new street, SB prev=0
        ])
        steps = _build_replay_steps(actions)
        self.assertAlmostEqual(steps[2]['pot_after'], 0.75 + 1.0)  # preflop pot + flop bet

    def test_allin_adds_amount(self):
        actions = self._actions([
            ('preflop', 'BB', 'post_bb', 0.50, 0, 'BB'),
            ('preflop', 'Hero', 'all-in', 50.0, 1, 'BTN'),
        ])
        steps = _build_replay_steps(actions)
        self.assertAlmostEqual(steps[1]['pot_after'], 50.50)

    def test_step_indices_sequential(self):
        actions = self._actions([
            ('preflop', 'SB', 'fold', 0, 0, 'SB'),
            ('preflop', 'BB', 'fold', 0, 0, 'BB'),
            ('preflop', 'UTG', 'fold', 0, 0, 'UTG'),
        ])
        steps = _build_replay_steps(actions)
        for i, s in enumerate(steps):
            self.assertEqual(s['idx'], i)

    def test_hero_flag_correct(self):
        actions = self._actions([
            ('preflop', 'Player1', 'fold', 0, 0, 'UTG'),
            ('preflop', 'Hero', 'raise', 2.0, 1, 'BTN'),
        ])
        steps = _build_replay_steps(actions)
        self.assertFalse(steps[0]['is_hero'])
        self.assertTrue(steps[1]['is_hero'])

    def test_multiple_streets_in_order(self):
        actions = self._actions([
            ('preflop', 'SB', 'post_sb', 0.25, 0, 'SB'),
            ('flop', 'Hero', 'bet', 2.0, 1, 'BTN'),
            ('turn', 'SB', 'check', 0.0, 0, 'SB'),
            ('river', 'Hero', 'bet', 5.0, 1, 'BTN'),
        ])
        steps = _build_replay_steps(actions)
        streets = [s['street'] for s in steps]
        self.assertEqual(streets, ['preflop', 'flop', 'turn', 'river'])


# ── Unit Tests: prepare_hand_replayer ────────────────────────────

class TestPrepareHandReplayer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'poker.db')
        _make_poker_db(self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_db_returns_empty(self):
        result = prepare_hand_replayer('TEST001', '/nonexistent/path.db')
        self.assertIsNone(result['hand'])
        self.assertEqual(result['steps'], [])
        self.assertEqual(result['positions'], [])

    def test_missing_hand_returns_empty(self):
        result = prepare_hand_replayer('NOTEXIST', self.db_path)
        self.assertIsNone(result['hand'])
        self.assertEqual(result['steps'], [])

    def test_returns_hand_metadata(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        hand = result['hand']
        self.assertIsNotNone(hand)
        self.assertEqual(hand['hand_id'], 'TEST001')
        self.assertEqual(hand['game_type'], 'cash')
        self.assertAlmostEqual(hand['blinds_sb'], 0.25)
        self.assertAlmostEqual(hand['blinds_bb'], 0.50)
        self.assertEqual(hand['hero_cards'], 'Ah Kd')
        self.assertEqual(hand['hero_position'], 'BTN')
        self.assertAlmostEqual(hand['net'], 9.50)
        self.assertEqual(hand['board_flop'], 'Ac 2h 7d')
        self.assertEqual(hand['board_turn'], 'Ks')
        self.assertEqual(hand['board_river'], '3c')
        self.assertEqual(hand['opponent_cards'], 'Qh Qd')

    def test_returns_steps(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        self.assertGreater(len(result['steps']), 0)

    def test_steps_have_required_fields(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        for step in result['steps']:
            self.assertIn('idx', step)
            self.assertIn('street', step)
            self.assertIn('player', step)
            self.assertIn('action_type', step)
            self.assertIn('amount', step)
            self.assertIn('is_hero', step)
            self.assertIn('position', step)
            self.assertIn('pot_before', step)
            self.assertIn('pot_after', step)

    def test_steps_ordered_by_street(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        from src.web.data import _STREET_ORDER
        streets = [s['street'] for s in result['steps']]
        street_nums = [_STREET_ORDER.get(s, 99) for s in streets]
        self.assertEqual(street_nums, sorted(street_nums))

    def test_positions_canonical_order(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        positions = result['positions']
        self.assertIsInstance(positions, list)
        self.assertGreater(len(positions), 0)
        # BTN should appear (hero position)
        self.assertIn('BTN', positions)
        # Canonical order: UTG before BTN
        if 'UTG' in positions:
            self.assertLess(positions.index('UTG'), positions.index('BTN'))

    def test_no_lesson_notes_by_default(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        self.assertIsNone(result['lesson_notes'])
        self.assertIsNone(result['lesson_id'])

    def test_lesson_notes_fetched_with_lesson_id(self):
        result = prepare_hand_replayer('TEST001', self.db_path, lesson_id=99)
        self.assertEqual(result['lesson_id'], 99)
        notes = result['lesson_notes']
        self.assertIsNotNone(notes)
        self.assertEqual(notes['title'], 'Test Lesson')
        self.assertEqual(notes['category'], 'Preflop')
        self.assertEqual(notes['executed_correctly'], 1)
        self.assertEqual(notes['notes'], 'Good raise!')

    def test_lesson_notes_none_for_unknown_lesson(self):
        result = prepare_hand_replayer('TEST001', self.db_path, lesson_id=999)
        self.assertIsNone(result['lesson_notes'])

    def test_tournament_hand(self):
        result = prepare_hand_replayer('TOURN001', self.db_path)
        hand = result['hand']
        self.assertIsNotNone(hand)
        self.assertEqual(hand['game_type'], 'tournament')
        self.assertEqual(hand['hero_cards'], '5c 5d')

    def test_steps_preflop_before_flop(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        streets = [s['street'] for s in result['steps']]
        # preflop steps should come before flop steps
        if 'preflop' in streets and 'flop' in streets:
            last_preflop = max(i for i, s in enumerate(streets) if s == 'preflop')
            first_flop = min(i for i, s in enumerate(streets) if s == 'flop')
            self.assertLess(last_preflop, first_flop)

    def test_pot_starts_at_zero(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        steps = result['steps']
        self.assertAlmostEqual(steps[0]['pot_before'], 0.0)

    def test_pot_non_negative_throughout(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        for step in result['steps']:
            self.assertGreaterEqual(step['pot_after'], 0.0)

    def test_hero_steps_flagged(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        hero_steps = [s for s in result['steps'] if s['is_hero']]
        self.assertGreater(len(hero_steps), 0)

    def test_result_dict_keys(self):
        result = prepare_hand_replayer('TEST001', self.db_path)
        self.assertIn('hand', result)
        self.assertIn('steps', result)
        self.assertIn('positions', result)
        self.assertIn('lesson_notes', result)
        self.assertIn('lesson_id', result)


# ── Flask Route Tests ─────────────────────────────────────────────

class TestHandReplayerRoute(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.poker_db = os.path.join(self.tmpdir, 'poker.db')
        self.analytics_db = os.path.join(self.tmpdir, 'analytics.db')
        _make_poker_db(self.poker_db)

        # Create minimal analytics.db
        from src.db.analytics_schema import init_analytics_db
        conn = sqlite3.connect(self.analytics_db)
        init_analytics_db(conn)
        conn.close()

        self.app = create_app(
            analytics_db_path=self.analytics_db,
            poker_db_path=self.poker_db,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_route_exists_returns_200(self):
        resp = self.client.get('/hand/TEST001')
        self.assertEqual(resp.status_code, 200)

    def test_route_for_unknown_hand_returns_200_with_not_found(self):
        resp = self.client.get('/hand/NOTEXIST')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'not found', resp.data.lower())

    def test_route_contains_hand_id(self):
        resp = self.client.get('/hand/TEST001')
        self.assertIn(b'TEST001', resp.data)

    def test_route_shows_blinds(self):
        resp = self.client.get('/hand/TEST001')
        # Blinds 0.25/0.50 should appear
        self.assertIn(b'0.25', resp.data)
        self.assertIn(b'0.5', resp.data)

    def test_route_shows_hero_cards(self):
        resp = self.client.get('/hand/TEST001')
        # Hero cards Ah Kd
        self.assertIn(b'Ah', resp.data)

    def test_route_with_game_type_tournament(self):
        resp = self.client.get('/hand/TOURN001?game_type=tournament')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'TOURN001', resp.data)

    def test_route_with_lesson_param(self):
        resp = self.client.get('/hand/TEST001?lesson=99')
        self.assertEqual(resp.status_code, 200)
        # Should show lesson title
        self.assertIn(b'Test Lesson', resp.data)

    def test_route_shows_board_cards(self):
        resp = self.client.get('/hand/TEST001')
        # Board flop: Ac 2h 7d
        self.assertIn(b'Ac', resp.data)

    def test_route_shows_net_result(self):
        resp = self.client.get('/hand/TEST001')
        # Net +9.50
        self.assertIn(b'+9.50', resp.data)

    def test_route_contains_replayer_controls(self):
        resp = self.client.get('/hand/TEST001')
        data = resp.data.decode('utf-8')
        # Should have prev/next buttons
        self.assertIn('btn-prev', data)
        self.assertIn('btn-next', data)

    def test_route_contains_step_slider(self):
        resp = self.client.get('/hand/TEST001')
        self.assertIn(b'step-slider', resp.data)

    def test_route_contains_js_replayer(self):
        resp = self.client.get('/hand/TEST001')
        data = resp.data.decode('utf-8')
        self.assertIn('goToStep', data)
        self.assertIn('replayerPrev', data)
        self.assertIn('replayerNext', data)

    def test_route_contains_keyboard_listener(self):
        resp = self.client.get('/hand/TEST001')
        data = resp.data.decode('utf-8')
        self.assertIn('ArrowLeft', data)
        self.assertIn('ArrowRight', data)

    def test_route_contains_board_area(self):
        resp = self.client.get('/hand/TEST001')
        self.assertIn(b'board-cards', resp.data)
        self.assertIn(b'pot-display', resp.data)

    def test_route_contains_timeline(self):
        resp = self.client.get('/hand/TEST001')
        self.assertIn(b'action-timeline', resp.data)

    def test_route_contains_step_data_json(self):
        resp = self.client.get('/hand/TEST001')
        data = resp.data.decode('utf-8')
        # JSON data block embedded in template
        self.assertIn('replayer-data', data)
        self.assertIn('application/json', data)

    def test_route_json_data_valid(self):
        resp = self.client.get('/hand/TEST001')
        data = resp.data.decode('utf-8')
        # Extract JSON from script tag
        import re
        m = re.search(
            r'<script[^>]*id="replayer-data"[^>]*>([\s\S]*?)</script>',
            data,
        )
        self.assertIsNotNone(m, "Could not find replayer-data script tag")
        payload = json.loads(m.group(1).strip())
        self.assertIn('steps', payload)
        self.assertIn('hand', payload)
        self.assertIsInstance(payload['steps'], list)
        self.assertGreater(len(payload['steps']), 0)

    def test_route_contains_suit_symbols(self):
        resp = self.client.get('/hand/TEST001')
        data = resp.data.decode('utf-8')
        # Suit symbols should appear in rendered cards
        # At least one of ♠♥♦♣
        suits_present = any(s in data for s in ['♠', '♥', '♦', '♣'])
        self.assertTrue(suits_present, "No suit symbols found in rendered cards")

    def test_route_hero_highlighted(self):
        resp = self.client.get('/hand/TEST001')
        # Hero seat should have hero-cards class
        self.assertIn(b'hero-cards', resp.data)

    def test_route_villain_cards_hidden(self):
        resp = self.client.get('/hand/TEST001')
        # Villain cards should have card-back initially hidden
        self.assertIn(b'card-back', resp.data)
        self.assertIn(b'villain-cards', resp.data)

    def test_route_street_tabs_present(self):
        resp = self.client.get('/hand/TEST001')
        data = resp.data.decode('utf-8')
        self.assertIn('stab-preflop', data)
        # Flop tab should be present (hand has board_flop)
        self.assertIn('stab-flop', data)

    def test_route_shows_pot_display(self):
        resp = self.client.get('/hand/TEST001')
        self.assertIn(b'pot-display', resp.data)
        self.assertIn(b'pot-value', resp.data)

    def test_route_back_link_present(self):
        resp = self.client.get('/hand/TEST001')
        self.assertIn(b'back-link', resp.data)

    def test_route_no_poker_db_shows_empty(self):
        app2 = create_app(
            analytics_db_path=self.analytics_db,
            poker_db_path='',
        )
        client2 = app2.test_client()
        resp = client2.get('/hand/TEST001')
        self.assertEqual(resp.status_code, 200)
        # Shows empty state (hand not found)
        self.assertIn(b'not found', resp.data.lower())

    def test_session_day_links_to_replayer(self):
        """session_day.html hand rows should contain replayer links."""
        from src.db.analytics_schema import init_analytics_db
        tmpdir2 = tempfile.mkdtemp()
        analytics_db2 = os.path.join(tmpdir2, 'analytics.db')
        conn = sqlite3.connect(analytics_db2)
        init_analytics_db(conn)

        now = '2026-03-16T00:00:00'
        summary = {'total_hands': 100, 'total_net': 50.0, 'total_days': 1}
        conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ('cash', 'summary', json.dumps(summary), now),
        )
        # Add daily_report so prepare_session_day finds data for the template
        daily = {
            'date': '2026-03-16',
            'net': 9.50,
            'total_hands': 14,
            'hands_count': 14,
            'num_sessions': 1,
            'day_stats': {},
            'sessions': [{
                'session_id': 's1',
                'start_time': '2026-03-16T18:00:00',
                'end_time': '2026-03-16T20:00:00',
                'duration_minutes': 120,
                'buy_in': 50.0,
                'cash_out': 59.50,
                'profit': 9.50,
                'hands_count': 14,
                'stats': {},
                'sparkline': [],
                'biggest_win': None,
                'biggest_loss': None,
                'ev_data': None,
                'leak_summary': [],
            }],
            'comparison': {},
        }
        conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ('cash', '2026-03-16', 'daily_report', json.dumps(daily), now),
        )
        conn.commit()
        conn.close()

        app3 = create_app(
            analytics_db_path=analytics_db2,
            poker_db_path=self.poker_db,
        )
        client3 = app3.test_client()
        resp = client3.get('/cash/sessions/2026-03-16')
        self.assertEqual(resp.status_code, 200)
        data = resp.data.decode('utf-8')
        # hand_replayer route should be referenced in the Hand Analyzer tab
        self.assertIn('/hand/', data)

        import shutil
        shutil.rmtree(tmpdir2, ignore_errors=True)


# ── Template Rendering Tests ──────────────────────────────────────

class TestHandReplayerTemplate(unittest.TestCase):
    """Focused tests on template content for various hand states."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.poker_db = os.path.join(self.tmpdir, 'poker.db')
        self.analytics_db = os.path.join(self.tmpdir, 'analytics.db')
        _make_poker_db(self.poker_db)

        from src.db.analytics_schema import init_analytics_db
        conn = sqlite3.connect(self.analytics_db)
        init_analytics_db(conn)
        conn.close()

        self.app = create_app(
            analytics_db_path=self.analytics_db,
            poker_db_path=self.poker_db,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_meta_shows_date(self):
        resp = self.client.get('/hand/TEST001')
        self.assertIn(b'2026-03-16', resp.data)

    def test_meta_shows_game_type(self):
        resp = self.client.get('/hand/TEST001')
        self.assertIn(b'Cash', resp.data)

    def test_lesson_note_executed_correctly_badge(self):
        resp = self.client.get('/hand/TEST001?lesson=99')
        data = resp.data.decode('utf-8')
        # executed_correctly=1 → badge-good
        self.assertIn('badge-good', data)
        self.assertIn('Correto', data)

    def test_no_lesson_notes_section_without_param(self):
        resp = self.client.get('/hand/TEST001')
        # The lesson notes div should NOT be present without ?lesson=
        self.assertNotIn(b'class="replayer-lesson-notes"', resp.data)

    def test_lesson_notes_section_with_param(self):
        resp = self.client.get('/hand/TEST001?lesson=99')
        # The lesson notes div SHOULD be present with ?lesson=99
        self.assertIn(b'class="replayer-lesson-notes"', resp.data)

    def test_dark_theme_css_in_style_block(self):
        resp = self.client.get('/hand/TEST001')
        data = resp.data.decode('utf-8')
        self.assertIn('replayer-layout', data)
        self.assertIn('poker-table', data)

    def test_result_net_positive_class(self):
        resp = self.client.get('/hand/TEST001')
        data = resp.data.decode('utf-8')
        self.assertIn('result-positive', data)

    def test_board_cards_empty_for_preflop_only(self):
        """Tournament hand with no board should not show board cards."""
        resp = self.client.get('/hand/TOURN001')
        data = resp.data.decode('utf-8')
        # No flop tab since no board_flop
        self.assertNotIn('stab-flop', data)

    def test_controls_present_when_steps_exist(self):
        resp = self.client.get('/hand/TEST001')
        self.assertIn(b'replayer-controls', resp.data)

    def test_empty_state_when_no_actions(self):
        """A hand with no actions should show empty state."""
        # Insert a hand with no actions
        conn = sqlite3.connect(self.poker_db)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO hands (hand_id, platform, game_type, date, "
            "blinds_sb, blinds_bb, hero_cards, hero_position, "
            "invested, won, net, rake) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ('NOACT001', 'GGPoker', 'cash', '2026-03-16T00:00:00',
             0.25, 0.50, 'Ah Kd', 'BTN', 1.0, 0.0, -1.0, 0.0),
        )
        conn.commit()
        conn.close()

        resp = self.client.get('/hand/NOACT001')
        data = resp.data.decode('utf-8')
        self.assertIn('No action data', data)


if __name__ == '__main__':
    unittest.main()
