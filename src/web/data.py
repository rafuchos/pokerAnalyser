"""Data access layer for the web UI – reads from analytics.db."""

import json
import os
import sqlite3


def load_analytics_data(db_path: str, game_type: str) -> dict:
    """Load all pre-processed analytics for a game type.

    Args:
        db_path: Path to analytics.db.
        game_type: 'cash' or 'tournament'.

    Returns a dict with keys matching the analytics tables.
    """
    if not os.path.exists(db_path):
        return {}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    data = {}

    try:
        # Global stats
        rows = conn.execute(
            "SELECT stat_name, stat_value, stat_json FROM global_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        for r in rows:
            val = json.loads(r['stat_json']) if r['stat_json'] else r['stat_value']
            data[r['stat_name']] = val

        # Daily stats
        daily_rows = conn.execute(
            "SELECT day, stat_name, stat_json FROM daily_stats WHERE game_type = ? ORDER BY day DESC",
            (game_type,),
        ).fetchall()
        daily_reports = []
        for r in daily_rows:
            if r['stat_name'] == 'daily_report' and r['stat_json']:
                daily_reports.append(json.loads(r['stat_json']))
        data['daily_reports'] = daily_reports

        # Session stats
        session_rows = conn.execute(
            "SELECT session_key, stat_name, stat_json FROM session_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        sessions = {}
        for r in session_rows:
            if r['stat_json']:
                sessions[r['session_key']] = json.loads(r['stat_json'])
        data['sessions'] = sessions

        # Positional stats
        pos_rows = conn.execute(
            "SELECT position, stat_json FROM positional_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        positional = {}
        for r in pos_rows:
            if r['stat_json']:
                positional[r['position']] = json.loads(r['stat_json'])
        data['positional'] = positional

        # Stack depth stats
        sd_rows = conn.execute(
            "SELECT tier, stat_json FROM stack_depth_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        stack_depth = {}
        for r in sd_rows:
            if r['stat_json']:
                stack_depth[r['tier']] = json.loads(r['stat_json'])
        data['stack_depth'] = stack_depth

        # Leaks
        leak_rows = conn.execute(
            "SELECT leak_name, category, stat_name, current_value, "
            "healthy_low, healthy_high, cost_bb100, direction, suggestion, position "
            "FROM leak_analysis WHERE game_type = ? ORDER BY cost_bb100 DESC",
            (game_type,),
        ).fetchall()
        data['leaks'] = [dict(r) for r in leak_rows]

        # Tilt analysis
        tilt_rows = conn.execute(
            "SELECT analysis_key, stat_json FROM tilt_analysis WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        tilt = {}
        for r in tilt_rows:
            tilt[r['analysis_key']] = json.loads(r['stat_json'])
        data['tilt'] = tilt

        # EV analysis
        ev_rows = conn.execute(
            "SELECT analysis_type, stat_json FROM ev_analysis WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        for r in ev_rows:
            data[r['analysis_type']] = json.loads(r['stat_json'])

        # Bet sizing
        sizing_rows = conn.execute(
            "SELECT sizing_key, stat_json FROM bet_sizing_stats WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        for r in sizing_rows:
            data['bet_sizing'] = json.loads(r['stat_json'])

        # Redline/Blueline
        rl_rows = conn.execute(
            "SELECT data_key, stat_json FROM redline_blueline WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        for r in rl_rows:
            data['redline'] = json.loads(r['stat_json'])

    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()

    return data
