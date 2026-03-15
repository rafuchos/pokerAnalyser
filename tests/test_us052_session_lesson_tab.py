"""Tests for US-052: Session Lesson Tab – Hand Analyzer por Sessão."""

import json
import os
import sqlite3
import tempfile
import unittest

from src.web.app import create_app
from src.web.data import prepare_session_day_lessons
from src.db.analytics_schema import init_analytics_db
from src.db.schema import init_db
from src.db.seed_lessons import seed_lessons


# ── Fixtures ─────────────────────────────────────────────────────


def _make_poker_db(path: str, game_type: str = 'cash', date: str = '2026-01-15'):
    """Create a source poker.db with hands, lessons, and hand_lessons."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    seed_lessons(conn)

    hands = [
        ('h1', game_type, f'{date}T10:00:00', 'BTN', 'Ah Kd', 5.0, 10.0, 5.0),
        ('h2', game_type, f'{date}T10:05:00', 'CO', 'Ks Qd', 3.0, 0.0, -3.0),
        ('h3', game_type, f'{date}T10:10:00', 'UTG', 'Ts Td', 2.0, 4.0, 2.0),
        ('h4', game_type, f'{date}T10:15:00', 'BB', '9s 8s', 1.0, 0.0, -1.0),
    ]
    for hand_id, gt, dt, pos, cards, inv, won, net in hands:
        conn.execute("""
            INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb,
                               blinds_bb, hero_cards, hero_position,
                               invested, won, net, rake, table_name, num_players)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (hand_id, 'GGPoker', gt, dt, 0.25, 0.50, cards, pos,
              inv, won, net, 0.0, 'T1', 6))

    # Link hands to lessons: lesson_id 1 (RFI) for h1, h2, h3
    # lesson_id 14 (C-Bet OOP) for h3, h4
    hand_lessons = [
        ('h1', 1, 'preflop', 1),   # RFI - correct
        ('h2', 1, 'preflop', 0),   # RFI - incorrect
        ('h3', 1, 'preflop', 1),   # RFI - correct
        ('h3', 14, 'flop', 0),     # C-Bet OOP - incorrect
        ('h4', 14, 'flop', 0),     # C-Bet OOP - incorrect
    ]
    for hand_id, lesson_id, street, ec in hand_lessons:
        conn.execute("""
            INSERT INTO hand_lessons (hand_id, lesson_id, street,
                                      executed_correctly, confidence, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (hand_id, lesson_id, street, ec, 1.0, '', '2026-01-15'))

    conn.commit()
    conn.close()


def _make_analytics_db(path: str, game_type: str = 'cash'):
    """Create minimal analytics.db with lesson_stats and a daily report."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_analytics_db(conn)
    now = '2026-03-15T12:00:00'

    # Global lesson stats for comparison
    lesson_stats = [
        {
            'lesson_id': 1, 'title': 'Ranges de RFI em cEV',
            'category': 'Preflop', 'total_hands': 80,
            'correct': 70, 'incorrect': 8, 'accuracy': 89.7,
            'mastery': 'mastered',
        },
        {
            'lesson_id': 14, 'title': 'C-Bet OOP',
            'category': 'Postflop', 'total_hands': 30,
            'correct': 18, 'incorrect': 10, 'accuracy': 64.3,
            'mastery': 'needs_work',
        },
    ]
    for ls in lesson_stats:
        conn.execute(
            "INSERT INTO lesson_stats (game_type, lesson_id, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (game_type, ls['lesson_id'], json.dumps(ls), now),
        )

    # Daily report
    daily = {
        'date': '2026-01-15',
        'net': 3.0,
        'hands_count': 4,
        'num_sessions': 1,
        'day_stats': {'vpip': 25.0, 'pfr': 18.0},
        'sessions': [{
            'session_id': 's1',
            'start_time': '2026-01-15T10:00:00',
            'end_time': '2026-01-15T11:00:00',
            'duration_minutes': 60,
            'profit': 3.0, 'hands_count': 4,
            'stats': {'vpip': 25.0, 'pfr': 18.0},
            'sparkline': [],
            'biggest_win': None, 'biggest_loss': None,
            'ev_data': None, 'leak_summary': [],
        }],
    }
    conn.execute(
        "INSERT INTO daily_stats (game_type, day, stat_name, stat_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (game_type, '2026-01-15', 'daily_report', json.dumps(daily), now),
    )

    conn.commit()
    conn.close()


# ── Unit Tests: prepare_session_day_lessons ───────────────────────


class TestPrepareSessionDayLessons(unittest.TestCase):
    """Test the prepare_session_day_lessons data function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.poker_db = os.path.join(self.tmpdir, 'poker.db')
        _make_poker_db(self.poker_db)
        self.data = {
            'lesson_stats': {
                1: {
                    'lesson_id': 1, 'title': 'Ranges de RFI em cEV',
                    'category': 'Preflop', 'accuracy': 89.7,
                    'mastery': 'mastered',
                },
                14: {
                    'lesson_id': 14, 'title': 'C-Bet OOP',
                    'category': 'Postflop', 'accuracy': 64.3,
                    'mastery': 'needs_work',
                },
            }
        }

    def tearDown(self):
        if os.path.exists(self.poker_db):
            os.unlink(self.poker_db)
        os.rmdir(self.tmpdir)

    def test_returns_none_without_poker_db(self):
        data = {}
        prepare_session_day_lessons(data, '2026-01-15', 'cash', '')
        self.assertIsNone(data['session_day_lessons'])

    def test_returns_none_for_missing_db_file(self):
        data = {}
        prepare_session_day_lessons(data, '2026-01-15', 'cash', '/nonexistent/path.db')
        self.assertIsNone(data['session_day_lessons'])

    def test_returns_none_for_date_with_no_lessons(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2020-01-01', 'cash', self.poker_db)
        self.assertIsNone(data['session_day_lessons'])

    def test_loads_lesson_cards(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        self.assertIsNotNone(data['session_day_lessons'])
        lessons = data['session_day_lessons']['lessons']
        self.assertEqual(len(lessons), 2)

    def test_lesson_ids_present(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lesson_ids = {l['lesson_id'] for l in data['session_day_lessons']['lessons']}
        self.assertIn(1, lesson_ids)
        self.assertIn(14, lesson_ids)

    def test_lesson_counts_correct(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lessons = {l['lesson_id']: l for l in data['session_day_lessons']['lessons']}

        # lesson 1: h1=correct, h2=incorrect, h3=correct → 2 correct, 1 incorrect
        rfi = lessons[1]
        self.assertEqual(rfi['total_hands'], 3)
        self.assertEqual(rfi['correct'], 2)
        self.assertEqual(rfi['incorrect'], 1)

        # lesson 14: h3=incorrect, h4=incorrect → 0 correct, 2 incorrect
        cbet = lessons[14]
        self.assertEqual(cbet['total_hands'], 2)
        self.assertEqual(cbet['correct'], 0)
        self.assertEqual(cbet['incorrect'], 2)

    def test_accuracy_computed(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lessons = {l['lesson_id']: l for l in data['session_day_lessons']['lessons']}

        # lesson 1: 2/3 = 66.7%
        self.assertAlmostEqual(lessons[1]['accuracy'], 66.7, places=1)
        # lesson 14: 0/2 = 0.0%
        self.assertAlmostEqual(lessons[14]['accuracy'], 0.0, places=1)

    def test_global_accuracy_from_lesson_stats(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lessons = {l['lesson_id']: l for l in data['session_day_lessons']['lessons']}
        self.assertAlmostEqual(lessons[1]['global_accuracy'], 89.7, places=1)
        self.assertAlmostEqual(lessons[14]['global_accuracy'], 64.3, places=1)

    def test_mastery_from_lesson_stats(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lessons = {l['lesson_id']: l for l in data['session_day_lessons']['lessons']}
        self.assertEqual(lessons[1]['mastery'], 'mastered')
        self.assertEqual(lessons[14]['mastery'], 'needs_work')

    def test_vs_global_computed(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lessons = {l['lesson_id']: l for l in data['session_day_lessons']['lessons']}
        # lesson 1: session 66.7% vs global 89.7% → worse
        self.assertEqual(lessons[1]['vs_global'], 'worse')
        # lesson 14: session 0% vs global 64.3% → worse
        self.assertEqual(lessons[14]['vs_global'], 'worse')

    def test_urgency_sorted(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lessons = data['session_day_lessons']['lessons']
        # lesson 14: urgency = 2*(1-0) = 2.0 (0% accuracy, 2 errors)
        # lesson 1:  urgency = 1*(1-0.667) = 0.333 (66.7% accuracy, 1 error)
        # lesson 14 should be first
        self.assertEqual(lessons[0]['lesson_id'], 14)
        self.assertEqual(lessons[1]['lesson_id'], 1)

    def test_summary_totals(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        summary = data['session_day_lessons']['summary']
        # 3 hands for lesson 1 + 2 hands for lesson 14 = 5 total
        self.assertEqual(summary['total_hands'], 5)
        # 2 correct (lesson 1) + 0 correct (lesson 14) = 2
        self.assertEqual(summary['correct'], 2)
        # 1 incorrect (lesson 1) + 2 incorrect (lesson 14) = 3
        self.assertEqual(summary['incorrect'], 3)
        # 2/5 = 40%
        self.assertAlmostEqual(summary['accuracy'], 40.0, places=1)

    def test_hands_list_included(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lessons = {l['lesson_id']: l for l in data['session_day_lessons']['lessons']}
        rfi_hands = lessons[1]['hands']
        self.assertEqual(len(rfi_hands), 3)
        hand_ids = {h['hand_id'] for h in rfi_hands}
        self.assertIn('h1', hand_ids)
        self.assertIn('h2', hand_ids)
        self.assertIn('h3', hand_ids)

    def test_hand_fields_present(self):
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        hands = data['session_day_lessons']['lessons'][0]['hands']
        h = hands[0]
        self.assertIn('hand_id', h)
        self.assertIn('hero_cards', h)
        self.assertIn('hero_position', h)
        self.assertIn('net', h)
        self.assertIn('executed_correctly', h)
        self.assertIn('street', h)

    def test_lessons_without_hands_on_date_not_included(self):
        """Lessons that have no hands for the queried date should not appear."""
        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lesson_ids = {l['lesson_id'] for l in data['session_day_lessons']['lessons']}
        # Only lessons 1 and 14 should appear (not all 25 lessons)
        self.assertEqual(len(lesson_ids), 2)

    def test_filters_by_game_type(self):
        """Should only return lessons for the specified game_type."""
        # Add a tournament hand on the same date
        conn = sqlite3.connect(self.poker_db)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb,
                               blinds_bb, hero_cards, hero_position,
                               invested, won, net, rake, table_name, num_players)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('ht1', 'GGPoker', 'tournament', '2026-01-15T10:00:00',
              25, 50, 'Ah Kd', 'BTN', 100, 200, 100, 0, 'T1', 6))
        conn.execute("""
            INSERT INTO hand_lessons (hand_id, lesson_id, street,
                                      executed_correctly, confidence, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ('ht1', 24, 'preflop', 1, 1.0, '', '2026-01-15'))
        conn.commit()
        conn.close()

        data = dict(self.data)
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lesson_ids = {l['lesson_id'] for l in data['session_day_lessons']['lessons']}
        # Tournament lesson (24) should not appear in cash query
        self.assertNotIn(24, lesson_ids)

    def test_no_global_stats_still_works(self):
        """Should work even without global lesson_stats in data."""
        data = {}  # no lesson_stats
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        self.assertIsNotNone(data['session_day_lessons'])
        lessons = data['session_day_lessons']['lessons']
        self.assertGreater(len(lessons), 0)
        # mastery should default to 'no_data'
        for lesson in lessons:
            self.assertEqual(lesson['mastery'], 'no_data')
            self.assertIsNone(lesson['global_accuracy'])

    def test_vs_global_same_when_within_5pct(self):
        """vs_global should be 'same' when accuracy difference < 5%."""
        # Give lesson 1 global accuracy of 67% (close to session 66.7%)
        data = {
            'lesson_stats': {
                1: {'lesson_id': 1, 'accuracy': 67.0, 'mastery': 'learning'},
                14: {'lesson_id': 14, 'accuracy': 64.3, 'mastery': 'needs_work'},
            }
        }
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lessons = {l['lesson_id']: l for l in data['session_day_lessons']['lessons']}
        # 66.7% vs 67.0% → diff = -0.3 → same
        self.assertEqual(lessons[1]['vs_global'], 'same')

    def test_handles_db_error_gracefully(self):
        """Invalid DB path should return None without crashing."""
        data = {}
        # Point to an invalid (non-SQLite) file
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            f.write(b'not a sqlite db')
            bad_path = f.name
        try:
            prepare_session_day_lessons(data, '2026-01-15', 'cash', bad_path)
            self.assertIsNone(data['session_day_lessons'])
        finally:
            os.unlink(bad_path)


# ── Route Tests ──────────────────────────────────────────────────


class TestSessionDayLessonsRoute(unittest.TestCase):
    """Test the session day route with lesson data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analytics_db = os.path.join(self.tmpdir, 'analytics.db')
        self.poker_db = os.path.join(self.tmpdir, 'poker.db')
        _make_analytics_db(self.analytics_db)
        _make_poker_db(self.poker_db)
        self.app = create_app(
            analytics_db_path=self.analytics_db,
            poker_db_path=self.poker_db,
        )
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        for f in [self.analytics_db, self.poker_db]:
            if os.path.exists(f):
                os.unlink(f)
        os.rmdir(self.tmpdir)

    def test_renders_ok(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        self.assertEqual(r.status_code, 200)

    def test_hand_analyzer_tab_visible(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Hand Analyzer', html)

    def test_session_stats_tab_visible(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Session Stats', html)

    def test_tab_toggle_js_present(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('switchSessionTab', html)

    def test_lesson_cards_rendered(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Ranges de RFI em cEV', html)
        self.assertIn('C-Bet OOP', html)

    def test_summary_stats_shown(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Maos Analisadas', html)
        self.assertIn('Corretas', html)
        self.assertIn('Incorretas', html)
        self.assertIn('Acerto Global', html)

    def test_global_comparison_shown(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Global:', html)

    def test_ver_maos_button_present(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Ver mãos', html)

    def test_accuracy_badge_shown(self):
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        # C-Bet OOP: 0.0% accuracy → badge-danger
        self.assertIn('badge-danger', html)

    def test_existing_features_preserved(self):
        """Original session day features still work."""
        r = self.client.get('/cash/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Day Stats', html)
        self.assertIn('Back to Sessions', html)

    def test_no_poker_db_still_renders(self):
        """Should render fine even without poker_db configured."""
        app_no_poker = create_app(analytics_db_path=self.analytics_db)
        client = app_no_poker.test_client()
        r = client.get('/cash/sessions/2026-01-15')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        # Still shows the tab buttons
        self.assertIn('Hand Analyzer', html)
        # But shows empty state for lesson data
        self.assertIn('Nenhuma aula classificada', html)

    def test_empty_date_shows_no_session_data(self):
        """Date with no session data shows the day-level empty state."""
        r = self.client.get('/cash/sessions/2026-02-01')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode()
        self.assertIn('No data found', html)


class TestTournamentSessionDayLessons(unittest.TestCase):
    """Test the tournament session day route with lesson data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analytics_db = os.path.join(self.tmpdir, 'analytics.db')
        self.poker_db = os.path.join(self.tmpdir, 'poker.db')
        _make_analytics_db(self.analytics_db, game_type='tournament')
        _make_poker_db(self.poker_db, game_type='tournament')
        self.app = create_app(
            analytics_db_path=self.analytics_db,
            poker_db_path=self.poker_db,
        )
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        for f in [self.analytics_db, self.poker_db]:
            if os.path.exists(f):
                os.unlink(f)
        os.rmdir(self.tmpdir)

    def test_tournament_session_day_renders(self):
        r = self.client.get('/tournament/sessions/2026-01-15')
        self.assertEqual(r.status_code, 200)

    def test_hand_analyzer_tab_in_tournament(self):
        r = self.client.get('/tournament/sessions/2026-01-15')
        html = r.data.decode()
        self.assertIn('Hand Analyzer', html)

    def test_tournament_lesson_cards_rendered(self):
        r = self.client.get('/tournament/sessions/2026-01-15')
        html = r.data.decode()
        # Should show lessons for tournament hands
        self.assertIn('Ranges de RFI em cEV', html)


# ── CSS Tests ────────────────────────────────────────────────────


class TestLessonAnalyzerCSS(unittest.TestCase):
    """Test CSS includes lesson analyzer styles."""

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_css_has_lac_card(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.lac-card', css)

    def test_css_has_lac_header(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.lac-header', css)

    def test_css_has_lac_title(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.lac-title', css)

    def test_css_has_lac_correct_incorrect(self):
        r = self.client.get('/static/css/style.css')
        css = r.data.decode()
        self.assertIn('.lac-correct', css)
        self.assertIn('.lac-incorrect', css)


# ── Data Function Edge Cases ──────────────────────────────────────


class TestPrepareSessionDayLessonsEdgeCases(unittest.TestCase):
    """Edge cases for prepare_session_day_lessons."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.poker_db = os.path.join(self.tmpdir, 'poker.db')

    def tearDown(self):
        if os.path.exists(self.poker_db):
            os.unlink(self.poker_db)
        os.rmdir(self.tmpdir)

    def test_unknown_executed_correctly_counted_as_unknown(self):
        """Hands with executed_correctly=None should count as unknown."""
        conn = sqlite3.connect(self.poker_db)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        seed_lessons(conn)
        conn.execute("""
            INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb,
                               blinds_bb, hero_cards, hero_position,
                               invested, won, net, rake, table_name, num_players)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('h_unk', 'GGPoker', 'cash', '2026-01-15T10:00:00',
              0.25, 0.50, 'Ah Kd', 'BTN', 5.0, 10.0, 5.0, 0.5, 'T1', 6))
        conn.execute("""
            INSERT INTO hand_lessons (hand_id, lesson_id, street,
                                      executed_correctly, confidence, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ('h_unk', 1, 'preflop', None, 1.0, '', '2026-01-15'))
        conn.commit()
        conn.close()

        data = {}
        prepare_session_day_lessons(data, '2026-01-15', 'cash', self.poker_db)
        lesson = data['session_day_lessons']['lessons'][0]
        self.assertEqual(lesson['unknown'], 1)
        self.assertEqual(lesson['correct'], 0)
        self.assertEqual(lesson['incorrect'], 0)
        # accuracy = None (no known outcomes)
        self.assertIsNone(lesson['accuracy'])

    def test_summary_accuracy_none_when_all_unknown(self):
        """Summary accuracy should be None if all outcomes are unknown."""
        conn = sqlite3.connect(self.poker_db)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        seed_lessons(conn)
        conn.execute("""
            INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb,
                               blinds_bb, hero_cards, hero_position,
                               invested, won, net, rake, table_name, num_players)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('h_unk', 'GGPoker', 'cash', '2026-01-20T10:00:00',
              0.25, 0.50, 'Ah Kd', 'BTN', 5.0, 10.0, 5.0, 0.5, 'T1', 6))
        conn.execute("""
            INSERT INTO hand_lessons (hand_id, lesson_id, street,
                                      executed_correctly, confidence, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ('h_unk', 1, 'preflop', None, 1.0, '', '2026-01-20'))
        conn.commit()
        conn.close()

        data = {}
        prepare_session_day_lessons(data, '2026-01-20', 'cash', self.poker_db)
        summary = data['session_day_lessons']['summary']
        self.assertIsNone(summary['accuracy'])

    def test_better_vs_global_when_session_higher(self):
        """vs_global should be 'better' when session accuracy > global by >5%."""
        conn = sqlite3.connect(self.poker_db)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        seed_lessons(conn)
        # 9 correct out of 10 = 90%
        for i in range(10):
            hid = f'h_better_{i}'
            conn.execute("""
                INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb,
                                   blinds_bb, hero_cards, hero_position,
                                   invested, won, net, rake, table_name, num_players)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (hid, 'GGPoker', 'cash', '2026-02-01T10:00:00',
                  0.25, 0.50, 'Ah Kd', 'BTN', 5.0, 10.0, 5.0, 0.5, 'T1', 6))
            ec = 1 if i < 9 else 0
            conn.execute("""
                INSERT INTO hand_lessons (hand_id, lesson_id, street,
                                          executed_correctly, confidence, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (hid, 1, 'preflop', ec, 1.0, '', '2026-02-01'))
        conn.commit()
        conn.close()

        data = {
            'lesson_stats': {
                1: {'lesson_id': 1, 'accuracy': 70.0, 'mastery': 'learning'},
            }
        }
        prepare_session_day_lessons(data, '2026-02-01', 'cash', self.poker_db)
        lessons = {l['lesson_id']: l for l in data['session_day_lessons']['lessons']}
        # 90% session vs 70% global → 20% diff → better
        self.assertEqual(lessons[1]['vs_global'], 'better')


if __name__ == '__main__':
    unittest.main()
