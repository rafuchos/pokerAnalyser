"""CRUD operations for the analytics database (analytics.db)."""

import json
import sqlite3
from datetime import datetime


class AnalyticsRepository:
    """Read/write pre-processed analysis results in analytics.db."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ── Meta ──────────────────────────────────────────────────────

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM analytics_meta WHERE key = ?", (key,)
        ).fetchone()
        return row['value'] if row else None

    def set_meta(self, key: str, value: str):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO analytics_meta (key, value, updated_at) "
            "VALUES (?, ?, ?)",
            (key, value, now),
        )
        self.conn.commit()

    # ── Clear helpers ─────────────────────────────────────────────

    def clear_game_type(self, game_type: str):
        """Delete all analysis rows for a game type (before re-running)."""
        tables = [
            'global_stats', 'session_stats', 'daily_stats',
            'positional_stats', 'stack_depth_stats', 'leak_analysis',
            'tilt_analysis', 'ev_analysis', 'bet_sizing_stats',
            'hand_matrix', 'redline_blueline',
        ]
        for table in tables:
            self.conn.execute(
                f"DELETE FROM {table} WHERE game_type = ?", (game_type,)
            )
        self.conn.commit()

    # ── Global Stats ──────────────────────────────────────────────

    def insert_global_stat(self, game_type: str, stat_name: str,
                           stat_value: float | None = None,
                           stat_json: dict | None = None):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO global_stats (game_type, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (game_type, stat_name, stat_value,
             json.dumps(stat_json) if stat_json is not None else None, now),
        )

    def get_global_stats(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT stat_name, stat_value, stat_json FROM global_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {
                'stat_name': r['stat_name'],
                'stat_value': r['stat_value'],
                'stat_json': json.loads(r['stat_json']) if r['stat_json'] else None,
            }
            for r in rows
        ]

    # ── Session Stats ─────────────────────────────────────────────

    def insert_session_stat(self, game_type: str, session_key: str,
                            stat_name: str, stat_value: float | None = None,
                            stat_json: dict | None = None):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO session_stats (game_type, session_key, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (game_type, session_key, stat_name, stat_value,
             json.dumps(stat_json) if stat_json is not None else None, now),
        )

    def get_session_stats(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT session_key, stat_name, stat_value, stat_json "
            "FROM session_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {
                'session_key': r['session_key'],
                'stat_name': r['stat_name'],
                'stat_value': r['stat_value'],
                'stat_json': json.loads(r['stat_json']) if r['stat_json'] else None,
            }
            for r in rows
        ]

    # ── Daily Stats ───────────────────────────────────────────────

    def insert_daily_stat(self, game_type: str, day: str, stat_name: str,
                          stat_value: float | None = None,
                          stat_json: dict | None = None):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO daily_stats (game_type, day, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (game_type, day, stat_name, stat_value,
             json.dumps(stat_json) if stat_json is not None else None, now),
        )

    def get_daily_stats(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT day, stat_name, stat_value, stat_json "
            "FROM daily_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {
                'day': r['day'],
                'stat_name': r['stat_name'],
                'stat_value': r['stat_value'],
                'stat_json': json.loads(r['stat_json']) if r['stat_json'] else None,
            }
            for r in rows
        ]

    # ── Positional Stats ──────────────────────────────────────────

    def insert_positional_stat(self, game_type: str, position: str,
                               stat_name: str, stat_value: float | None = None,
                               stat_json: dict | None = None):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO positional_stats (game_type, position, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (game_type, position, stat_name, stat_value,
             json.dumps(stat_json) if stat_json is not None else None, now),
        )

    def get_positional_stats(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT position, stat_name, stat_value, stat_json "
            "FROM positional_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {
                'position': r['position'],
                'stat_name': r['stat_name'],
                'stat_value': r['stat_value'],
                'stat_json': json.loads(r['stat_json']) if r['stat_json'] else None,
            }
            for r in rows
        ]

    # ── Stack Depth Stats ─────────────────────────────────────────

    def insert_stack_depth_stat(self, game_type: str, tier: str,
                                stat_name: str, stat_value: float | None = None,
                                stat_json: dict | None = None):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO stack_depth_stats (game_type, tier, stat_name, stat_value, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (game_type, tier, stat_name, stat_value,
             json.dumps(stat_json) if stat_json is not None else None, now),
        )

    def get_stack_depth_stats(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tier, stat_name, stat_value, stat_json "
            "FROM stack_depth_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {
                'tier': r['tier'],
                'stat_name': r['stat_name'],
                'stat_value': r['stat_value'],
                'stat_json': json.loads(r['stat_json']) if r['stat_json'] else None,
            }
            for r in rows
        ]

    # ── Leak Analysis ─────────────────────────────────────────────

    def insert_leak(self, game_type: str, leak_name: str, category: str,
                    stat_name: str, current_value: float,
                    healthy_low: float, healthy_high: float,
                    cost_bb100: float, direction: str,
                    suggestion: str, position: str = ''):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO leak_analysis "
            "(game_type, leak_name, category, stat_name, current_value, "
            "healthy_low, healthy_high, cost_bb100, direction, suggestion, position, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (game_type, leak_name, category, stat_name, current_value,
             healthy_low, healthy_high, cost_bb100, direction, suggestion,
             position, now),
        )

    def get_leak_analysis(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT leak_name, category, stat_name, current_value, "
            "healthy_low, healthy_high, cost_bb100, direction, suggestion, position "
            "FROM leak_analysis WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Tilt Analysis ─────────────────────────────────────────────

    def insert_tilt_analysis(self, game_type: str, analysis_key: str,
                             data: dict):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO tilt_analysis (game_type, analysis_key, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (game_type, analysis_key, json.dumps(data), now),
        )

    def get_tilt_analysis(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT analysis_key, stat_json FROM tilt_analysis WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {'analysis_key': r['analysis_key'],
             'data': json.loads(r['stat_json'])}
            for r in rows
        ]

    # ── EV Analysis ───────────────────────────────────────────────

    def insert_ev_analysis(self, game_type: str, analysis_type: str,
                           data: dict):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO ev_analysis (game_type, analysis_type, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (game_type, analysis_type, json.dumps(data), now),
        )

    def get_ev_analysis(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT analysis_type, stat_json FROM ev_analysis WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {'analysis_type': r['analysis_type'],
             'data': json.loads(r['stat_json'])}
            for r in rows
        ]

    # ── Bet Sizing ────────────────────────────────────────────────

    def insert_bet_sizing(self, game_type: str, sizing_key: str, data: dict):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO bet_sizing_stats (game_type, sizing_key, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (game_type, sizing_key, json.dumps(data), now),
        )

    def get_bet_sizing(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT sizing_key, stat_json FROM bet_sizing_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {'sizing_key': r['sizing_key'],
             'data': json.loads(r['stat_json'])}
            for r in rows
        ]

    # ── Hand Matrix ───────────────────────────────────────────────

    def insert_hand_matrix_entry(self, game_type: str, position: str,
                                 hand_combo: str, dealt: int, played: int,
                                 total_net: float, bb100: float,
                                 action_breakdown: dict | None = None):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO hand_matrix "
            "(game_type, position, hand_combo, dealt, played, total_net, bb100, action_breakdown, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (game_type, position, hand_combo, dealt, played, total_net, bb100,
             json.dumps(action_breakdown) if action_breakdown else None, now),
        )

    def get_hand_matrix(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT position, hand_combo, dealt, played, total_net, bb100, action_breakdown "
            "FROM hand_matrix WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {
                'position': r['position'],
                'hand_combo': r['hand_combo'],
                'dealt': r['dealt'],
                'played': r['played'],
                'total_net': r['total_net'],
                'bb100': r['bb100'],
                'action_breakdown': json.loads(r['action_breakdown']) if r['action_breakdown'] else None,
            }
            for r in rows
        ]

    # ── Red Line / Blue Line ──────────────────────────────────────

    def insert_redline_blueline(self, game_type: str, data_key: str,
                                data: dict):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO redline_blueline (game_type, data_key, stat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (game_type, data_key, json.dumps(data), now),
        )

    def get_redline_blueline(self, game_type: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT data_key, stat_json FROM redline_blueline WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        return [
            {'data_key': r['data_key'],
             'data': json.loads(r['stat_json'])}
            for r in rows
        ]

    # ── Commit helper ─────────────────────────────────────────────

    def commit(self):
        self.conn.commit()
