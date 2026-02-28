"""Database CRUD operations."""

import sqlite3
from datetime import datetime
from typing import Optional

from src.parsers.base import ActionData, HandData, TournamentSummaryData


class Repository:
    """CRUD operations for poker database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ── Imported Files ───────────────────────────────────────────────

    def is_file_imported(self, file_path: str, file_hash: str) -> bool:
        """Check if a file has already been imported with the same hash."""
        row = self.conn.execute(
            "SELECT file_hash FROM imported_files WHERE file_path = ?",
            (file_path,)
        ).fetchone()
        if row is None:
            return False
        return row['file_hash'] == file_hash

    def mark_file_imported(self, file_path: str, file_hash: str, records_count: int):
        """Mark a file as imported."""
        self.conn.execute(
            "INSERT OR REPLACE INTO imported_files (file_path, file_hash, imported_at, records_count) "
            "VALUES (?, ?, ?, ?)",
            (file_path, file_hash, datetime.now().isoformat(), records_count)
        )
        self.conn.commit()

    # ── Hands ────────────────────────────────────────────────────────

    def insert_hand(self, hand: HandData) -> bool:
        """Insert a hand, returning True if inserted (not duplicate)."""
        try:
            self.conn.execute(
                "INSERT INTO hands (hand_id, platform, game_type, date, blinds_sb, blinds_bb, "
                "hero_cards, hero_position, invested, won, net, rake, table_name, num_players) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    hand.hand_id, hand.platform, hand.game_type,
                    hand.date.isoformat() if isinstance(hand.date, datetime) else hand.date,
                    hand.blinds_sb, hand.blinds_bb, hand.hero_cards, hand.hero_position,
                    hand.invested, hand.won, hand.net, hand.rake,
                    hand.table_name, hand.num_players,
                )
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def insert_hands_batch(self, hands: list[HandData]) -> int:
        """Insert multiple hands, returning count of inserted."""
        inserted = 0
        for hand in hands:
            if self.insert_hand(hand):
                inserted += 1
        self.conn.commit()
        return inserted

    # ── Hand Actions ────────────────────────────────────────────────

    def insert_actions_batch(self, actions: list[ActionData]) -> int:
        """Insert multiple hand actions, returning count inserted."""
        if not actions:
            return 0
        self.conn.executemany(
            "INSERT INTO hand_actions (hand_id, street, player, action_type, amount, "
            "is_hero, sequence_order, position, is_voluntary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (a.hand_id, a.street, a.player, a.action_type, a.amount or 0,
                 a.is_hero or 0, a.sequence_order or 0, a.position, a.is_voluntary or 0)
                for a in actions
            ]
        )
        self.conn.commit()
        return len(actions)

    def update_hand_board(self, hand_id: str, board_flop: str = None,
                          board_turn: str = None, board_river: str = None):
        """Update board cards for a hand."""
        self.conn.execute(
            "UPDATE hands SET board_flop = ?, board_turn = ?, board_river = ? "
            "WHERE hand_id = ?",
            (board_flop, board_turn, board_river, hand_id)
        )

    def update_hand_position(self, hand_id: str, hero_position: str):
        """Update hero position for a hand."""
        self.conn.execute(
            "UPDATE hands SET hero_position = ? WHERE hand_id = ?",
            (hero_position, hand_id)
        )

    def get_hand_actions(self, hand_id: str) -> list[dict]:
        """Get all actions for a hand, ordered by street and sequence."""
        rows = self.conn.execute(
            "SELECT * FROM hand_actions WHERE hand_id = ? "
            "ORDER BY CASE street "
            "  WHEN 'preflop' THEN 1 WHEN 'flop' THEN 2 "
            "  WHEN 'turn' THEN 3 WHEN 'river' THEN 4 END, "
            "sequence_order",
            (hand_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def has_actions_for_hand(self, hand_id: str) -> bool:
        """Check if actions already exist for a hand."""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM hand_actions WHERE hand_id = ?",
            (hand_id,)
        ).fetchone()
        return row['cnt'] > 0

    # ── Sessions ─────────────────────────────────────────────────────

    def insert_session(self, session: dict) -> int:
        """Insert a session and return the session_id."""
        cursor = self.conn.execute(
            "INSERT INTO sessions (platform, date, buy_in, cash_out, profit, "
            "hands_count, min_stack, start_time, end_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.get('platform', 'GGPoker'),
                session['start_time'].strftime('%Y-%m-%d') if isinstance(session['start_time'], datetime) else session['start_time'],
                session.get('buy_in', 0),
                session.get('cash_out', 0),
                session.get('profit', 0),
                session.get('hands_count', 0),
                session.get('min_stack', 0),
                session['start_time'].isoformat() if isinstance(session['start_time'], datetime) else session['start_time'],
                session['end_time'].isoformat() if isinstance(session['end_time'], datetime) else session['end_time'],
            )
        )
        self.conn.commit()
        return cursor.lastrowid

    def clear_sessions(self):
        """Clear all sessions (for re-computation)."""
        self.conn.execute("DELETE FROM sessions")
        self.conn.commit()

    # ── Tournaments ──────────────────────────────────────────────────

    def insert_tournament(self, t: dict) -> bool:
        """Insert a tournament, returning True if inserted."""
        try:
            self.conn.execute(
                "INSERT INTO tournaments (tournament_id, platform, name, date, buy_in, rake, "
                "bounty, total_buy_in, position, prize, bounty_won, total_players, entries, "
                "is_bounty, is_satellite) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    t['tournament_id'], t.get('platform', 'GGPoker'), t.get('name', ''),
                    t['date'].isoformat() if isinstance(t.get('date'), datetime) else t.get('date', ''),
                    t.get('buy_in', 0), t.get('rake', 0), t.get('bounty', 0),
                    t.get('total_buy_in', 0), t.get('position'),
                    t.get('prize', 0), t.get('bounty_won', 0),
                    t.get('total_players', 0), t.get('entries', 1),
                    1 if t.get('is_bounty') else 0,
                    1 if t.get('is_satellite') else 0,
                )
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def insert_tournament_summary(self, ts: TournamentSummaryData) -> bool:
        """Insert a tournament summary."""
        try:
            self.conn.execute(
                "INSERT INTO tournament_summaries (tournament_id, platform, name, date, buy_in, "
                "rake, bounty, total_buy_in, position, prize, bounty_won, total_players, "
                "entries, is_bounty, is_satellite) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts.tournament_id, ts.platform, ts.name,
                    ts.date.isoformat() if isinstance(ts.date, datetime) else ts.date,
                    ts.buy_in, ts.rake, ts.bounty, ts.total_buy_in,
                    ts.position, ts.prize, ts.bounty_won, ts.total_players,
                    ts.entries,
                    1 if ts.is_bounty else 0,
                    1 if ts.is_satellite else 0,
                )
            )
            return True
        except sqlite3.IntegrityError:
            return False

    # ── Queries for Reports ──────────────────────────────────────────

    def get_cash_hands(self, year: Optional[str] = None) -> list[dict]:
        """Get all cash hands, optionally filtered by year."""
        query = "SELECT * FROM hands WHERE game_type = 'cash'"
        params = []
        if year:
            query += " AND date LIKE ?"
            params.append(f"{year}%")
        query += " ORDER BY date"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_sessions(self, year: Optional[str] = None) -> list[dict]:
        """Get all sessions, optionally filtered by year."""
        query = "SELECT * FROM sessions"
        params = []
        if year:
            query += " WHERE date LIKE ?"
            params.append(f"{year}%")
        query += " ORDER BY start_time"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_tournaments(self, year: Optional[str] = None,
                        exclude_satellites: bool = False) -> list[dict]:
        """Get tournaments."""
        query = "SELECT * FROM tournaments"
        conditions = []
        params = []
        if year:
            conditions.append("date LIKE ?")
            params.append(f"{year}%")
        if exclude_satellites:
            conditions.append("is_satellite = 0")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY date"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_tournament_summaries(self) -> dict:
        """Get all tournament summaries indexed by tournament_id."""
        rows = self.conn.execute("SELECT * FROM tournament_summaries").fetchall()
        return {r['tournament_id']: dict(r) for r in rows}

    def get_cash_daily_stats(self, year: Optional[str] = None) -> list[dict]:
        """Get aggregated daily cash stats."""
        query = """
            SELECT
                substr(date, 1, 10) as day,
                COUNT(*) as hands,
                SUM(CASE WHEN net > 0 THEN net ELSE 0 END) as total_won,
                SUM(CASE WHEN net < 0 THEN ABS(net) ELSE 0 END) as total_lost,
                SUM(net) as net,
                MAX(net) as biggest_win_net,
                MIN(net) as biggest_loss_net
            FROM hands
            WHERE game_type = 'cash'
        """
        params = []
        if year:
            query += " AND date LIKE ?"
            params.append(f"{year}%")
        query += " GROUP BY day ORDER BY day DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_cash_hands_for_day(self, day: str) -> list[dict]:
        """Get all cash hands for a specific day."""
        rows = self.conn.execute(
            "SELECT * FROM hands WHERE game_type = 'cash' AND date LIKE ? ORDER BY date",
            (f"{day}%",)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_sessions_for_day(self, day: str) -> list[dict]:
        """Get sessions for a specific day."""
        rows = self.conn.execute(
            "SELECT * FROM sessions WHERE date = ? ORDER BY start_time",
            (day,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_tournaments_for_day(self, day: str,
                                exclude_satellites: bool = False) -> list[dict]:
        """Get tournaments for a specific day."""
        query = "SELECT * FROM tournaments WHERE date LIKE ?"
        params = [f"{day}%"]
        if exclude_satellites:
            query += " AND is_satellite = 0"
        query += " ORDER BY date"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_cash_stats_summary(self, year: Optional[str] = None) -> dict:
        """Get overall cash game statistics."""
        query = """
            SELECT
                COUNT(*) as total_hands,
                SUM(net) as total_net,
                SUM(CASE WHEN net > 0 THEN net ELSE 0 END) as total_won,
                SUM(CASE WHEN net < 0 THEN ABS(net) ELSE 0 END) as total_lost,
                MAX(net) as biggest_win,
                MIN(net) as biggest_loss
            FROM hands
            WHERE game_type = 'cash'
        """
        params = []
        if year:
            query += " AND date LIKE ?"
            params.append(f"{year}%")
        row = self.conn.execute(query, params).fetchone()
        return dict(row) if row else {}

    def get_tournament_stats_summary(self, year: Optional[str] = None) -> dict:
        """Get overall tournament statistics."""
        query = """
            SELECT
                COUNT(*) as total_tournaments,
                SUM(total_buy_in * entries) as total_invested,
                SUM(prize) as total_won,
                SUM(prize - total_buy_in * entries) as total_net,
                SUM(entries) as total_entries,
                SUM(entries - 1) as total_rebuys,
                SUM(rake * entries) as total_rake
            FROM tournaments
            WHERE is_satellite = 0
        """
        params = []
        if year:
            query += " AND date LIKE ?"
            params.append(f"{year}%")
        row = self.conn.execute(query, params).fetchone()
        return dict(row) if row else {}

    # ── Preflop Stats Queries ─────────────────────────────────────

    def get_preflop_action_sequences(self, year: Optional[str] = None) -> list[dict]:
        """Get all preflop actions for cash hands, ordered by hand and sequence.

        Joins with hands table to include hero_position and date info.
        Used by CashAnalyzer to compute VPIP, PFR, 3-Bet%, Fold-to-3-Bet%, ATS%.
        """
        query = """
            SELECT ha.hand_id, ha.player, ha.action_type, ha.amount,
                   ha.is_hero, ha.sequence_order, ha.position, ha.is_voluntary,
                   h.hero_position, substr(h.date, 1, 10) as day
            FROM hand_actions ha
            JOIN hands h ON ha.hand_id = h.hand_id
            WHERE ha.street = 'preflop' AND h.game_type = 'cash'
        """
        params = []
        if year:
            query += " AND h.date LIKE ?"
            params.append(f"{year}%")
        query += " ORDER BY ha.hand_id, ha.sequence_order"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_imported_files_count(self) -> int:
        """Get count of imported files."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM imported_files").fetchone()
        return row['cnt']

    def get_hands_count(self) -> int:
        """Get total number of hands."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM hands").fetchone()
        return row['cnt']

    def get_tournaments_count(self) -> int:
        """Get total number of tournaments."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM tournaments").fetchone()
        return row['cnt']
