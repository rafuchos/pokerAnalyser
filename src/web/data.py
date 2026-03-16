"""Data access layer for the web UI – reads from analytics.db."""

import json
import os
import sqlite3
from datetime import datetime, timedelta


# ── Health ranges for HUD badge classification (6-max NL) ────────

_HEALTHY_RANGES = {
    'vpip': (22, 30), 'pfr': (17, 25), 'three_bet': (7, 12),
    'fold_to_3bet': (40, 55), 'ats': (30, 45),
    'open_shove': (0, 5), 'rbw': (50, 80),
    'af': (2.0, 3.5), 'cbet': (60, 80), 'fold_to_cbet': (35, 50),
    'wtsd': (25, 33), 'wsd': (50, 65),
    'won_saw_flop': (45, 55), 'bet_river': (30, 50), 'call_river': (25, 40),
    'probe': (30, 50), 'fold_to_probe': (35, 55),
    'bet_vs_missed_cbet': (30, 50), 'xf_oop': (20, 35),
}

_WARNING_RANGES = {
    'vpip': (18, 35), 'pfr': (14, 30), 'three_bet': (5, 15),
    'fold_to_3bet': (35, 65), 'ats': (25, 50),
    'open_shove': (0, 10), 'rbw': (35, 90),
    'af': (1.5, 4.5), 'cbet': (50, 90), 'fold_to_cbet': (30, 60),
    'wtsd': (22, 38), 'wsd': (45, 70),
    'won_saw_flop': (38, 62), 'bet_river': (20, 60), 'call_river': (15, 55),
    'probe': (20, 60), 'fold_to_probe': (25, 65),
    'bet_vs_missed_cbet': (20, 60), 'xf_oop': (10, 45),
}

_STAT_NAMES = [
    'vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats',
    'af', 'cbet', 'fold_to_cbet', 'wtsd', 'wsd',
]


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

        # Hand matrix
        hm_rows = conn.execute(
            "SELECT position, hand_combo, dealt, played, total_net, bb100 "
            "FROM hand_matrix WHERE game_type = ?",
            (game_type,),
        ).fetchall()
        hand_matrix = {}
        for r in hm_rows:
            pos = r['position']
            if pos not in hand_matrix:
                hand_matrix[pos] = {}
            hand_matrix[pos][r['hand_combo']] = {
                'hands': r['dealt'] or 0,
                'played': r['played'] or 0,
                'net': r['total_net'] or 0,
                'bb100': r['bb100'] or 0,
                'frequency': round((r['played'] or 0) / (r['dealt'] or 1) * 100, 1),
            }
        data['hand_matrix'] = hand_matrix

        # Lesson stats
        try:
            ls_rows = conn.execute(
                "SELECT lesson_id, stat_json FROM lesson_stats WHERE game_type = ?",
                (game_type,),
            ).fetchall()
            lesson_stats = {}
            for r in ls_rows:
                lesson_stats[r['lesson_id']] = json.loads(r['stat_json'])
            data['lesson_stats'] = lesson_stats
        except sqlite3.OperationalError:
            data['lesson_stats'] = {}

    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()

    return data


# ── Sessions helpers ─────────────────────────────────────────────


def prepare_sessions_list(data, page=1, per_page=15):
    """Enrich analytics data with paginated session-day list.

    Adds: sessions_days, sessions_page, sessions_total_pages.
    Each day gets aggregated stats with health badges.
    """
    daily_reports = data.get('daily_reports', [])
    sessions_map = data.get('sessions', {})

    # Merge session detail from session_stats into daily reports
    enriched = []
    for report in daily_reports:
        day = dict(report)
        date = day.get('date', '')

        # Compute day-level stats with health badges
        ds = day.get('day_stats') or {}
        for s in _STAT_NAMES:
            val = ds.get(s)
            day[f'{s}_val'] = val
            day[f'{s}_badge'] = _classify_health(s, val)

        # Count leaks across sessions + aggregate daily luck
        sess_list = day.get('sessions') or []
        leak_count = 0
        day_luck = 0.0
        day_has_ev = False
        for sess in sess_list:
            leak_count += len(sess.get('leak_summary') or [])
            ev = sess.get('ev_data') or {}
            if ev.get('total_hands', 0) > 0:
                day_has_ev = True
                day_luck += (ev.get('real_net', 0) or 0) - (ev.get('ev_net', 0) or 0)
        day['leak_count'] = leak_count
        if day_has_ev:
            day['daily_luck'] = round(day_luck, 2)
        else:
            day['daily_luck'] = None

        # Overall health badge for the day
        badges = [day.get(f'{s}_badge') for s in _STAT_NAMES]
        danger_count = badges.count('danger')
        warning_count = badges.count('warning')
        if danger_count >= 3:
            day['health_badge'] = 'danger'
        elif danger_count >= 1 or warning_count >= 3:
            day['health_badge'] = 'warning'
        else:
            day['health_badge'] = 'good'

        enriched.append(day)

    total = len(enriched)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page

    data['sessions_days'] = enriched[start:end]
    data['sessions_page'] = page
    data['sessions_total_pages'] = total_pages
    data['sessions_total_days'] = total
    return data


def _get_global_averages(data):
    """Extract global stat averages from preflop/postflop overall data."""
    pf = data.get('preflop_overall') or {}
    po = data.get('postflop_overall') or {}
    avgs = {}
    for s in _STAT_NAMES:
        val = pf.get(s) if pf.get(s) is not None else po.get(s)
        if val is not None:
            avgs[s] = val
    return avgs


def _compute_session_bb100(sess):
    """Compute bb/100 for a session if blinds_bb available."""
    ev = sess.get('ev_data') or {}
    bb100 = ev.get('bb100_real')
    if bb100 is not None:
        return bb100
    # Fallback: compute from profit / hands if we have a rough BB
    return None


def _compute_win_rate_per_hour(profit, duration_minutes):
    """Compute $/hr win rate."""
    if not duration_minutes or duration_minutes <= 0:
        return None
    return round(profit / (duration_minutes / 60.0), 2)


def _build_session_comparison(enriched_sessions, global_avgs):
    """Build side-by-side comparison table for multi-session days."""
    if len(enriched_sessions) < 2:
        return None
    _COMPARE_STATS = ['vpip', 'pfr', 'three_bet', 'af', 'cbet', 'wtsd', 'wsd']
    rows = []
    for stat in _COMPARE_STATS:
        row = {'stat': stat, 'label': _stat_label(stat), 'values': [], 'global': global_avgs.get(stat)}
        vals = []
        for s in enriched_sessions:
            val = s.get(f'{stat}_val')
            row['values'].append({
                'value': val,
                'badge': s.get(f'{stat}_badge', ''),
            })
            if val is not None:
                vals.append(val)
        # Identify best/worst for highlighting
        if vals:
            h = _HEALTHY_RANGES.get(stat)
            if h:
                mid = (h[0] + h[1]) / 2
                for v in row['values']:
                    if v['value'] is not None:
                        v['deviation'] = abs(v['value'] - mid)
        rows.append(row)
    # Add profit row
    profit_row = {'stat': 'profit', 'label': 'Profit', 'values': [], 'global': None}
    for s in enriched_sessions:
        profit_row['values'].append({'value': s.get('profit', 0), 'badge': ''})
    rows.append(profit_row)
    return rows


def prepare_session_day(data, date):
    """Enrich analytics data with detail for a specific day.

    Adds: session_day (the day report with enriched sessions).
    Each session gets sparkline SVG points, EV chart SVG points,
    health badges, global comparison, extended stats, and best/worst
    comparison markers.
    """
    daily_reports = data.get('daily_reports', [])
    sessions_map = data.get('sessions', {})

    # Find the report for this date
    day_report = None
    for r in daily_reports:
        if r.get('date') == date:
            day_report = dict(r)
            break
    if not day_report:
        data['session_day'] = None
        return data

    # Global averages for comparison
    global_avgs = _get_global_averages(data)
    day_report['global_avgs'] = global_avgs

    # Add health badges for day-level stats
    ds = day_report.get('day_stats') or {}
    for s in _STAT_NAMES:
        val = ds.get(s)
        day_report[f'{s}_val'] = val
        day_report[f'{s}_badge'] = _classify_health(s, val)

    # Normalize: tournament reports use 'tournaments' key instead of 'sessions'
    if 'sessions' not in day_report and 'tournaments' in day_report:
        tournaments = day_report['tournaments']
        # Map tournament keys to session-compatible keys
        for t in tournaments:
            if isinstance(t, dict):
                if 'profit' not in t and 'net' in t:
                    t['profit'] = t['net']
                if 'session_id' not in t and 'tournament_id' in t:
                    t['session_id'] = t['tournament_id']
        day_report['sessions'] = tournaments

    # Day-level extended stats
    total_hands = day_report.get('hands_count') or day_report.get('total_hands') or 0
    total_net = day_report.get('net', 0) or 0
    total_duration = 0
    for sess in (day_report.get('sessions') or []):
        total_duration += (sess.get('duration_minutes') or 0)
    day_report['total_duration'] = total_duration
    if total_duration >= 60:
        day_report['total_duration_fmt'] = f"{total_duration // 60}h {total_duration % 60}m"
    else:
        day_report['total_duration_fmt'] = f"{total_duration}m"
    day_report['win_rate_hourly'] = _compute_win_rate_per_hour(total_net, total_duration)

    # Enrich each session
    sess_list = day_report.get('sessions') or []
    enriched_sessions = []
    for i, sess in enumerate(sess_list):
        s = dict(sess)
        s['index'] = i + 1

        # Duration formatting
        mins = s.get('duration_minutes') or 0
        if mins >= 60:
            s['duration_fmt'] = f"{mins // 60}h {mins % 60}m"
        else:
            s['duration_fmt'] = f"{mins}m"

        # Time formatting
        start = s.get('start_time', '')
        if len(start) >= 16:
            s['start_fmt'] = start[11:16]
        else:
            s['start_fmt'] = ''
        end = s.get('end_time', '')
        if len(end) >= 16:
            s['end_fmt'] = end[11:16]
        else:
            s['end_fmt'] = ''

        # Stats with health badges + global comparison
        stats = s.get('stats') or {}
        for stat in _STAT_NAMES:
            val = stats.get(stat)
            s[f'{stat}_val'] = val
            health = stats.get(f'{stat}_health', '')
            if not health and val is not None:
                health = _classify_health(stat, val)
            s[f'{stat}_badge'] = health
            # Global comparison arrow
            g = global_avgs.get(stat)
            if val is not None and g is not None:
                diff = val - g
                if abs(diff) < 0.5:
                    s[f'{stat}_vs_global'] = 'same'
                elif diff > 0:
                    s[f'{stat}_vs_global'] = 'up'
                else:
                    s[f'{stat}_vs_global'] = 'down'
            else:
                s[f'{stat}_vs_global'] = ''

        # Win rate $/hr per session
        s['win_rate_hourly'] = _compute_win_rate_per_hour(
            s.get('profit', 0) or 0, mins)

        # bb/100 per session
        s['bb100'] = _compute_session_bb100(s)

        # Positional breakdown (if available)
        pos_data = stats.get('by_position') or s.get('positional') or {}
        if pos_data:
            pos_rows = []
            for pos in ['UTG', 'MP', 'CO', 'BTN', 'SB', 'BB']:
                pd = pos_data.get(pos)
                if pd:
                    pos_rows.append({
                        'position': pos,
                        'vpip': pd.get('vpip'),
                        'pfr': pd.get('pfr'),
                        'hands': pd.get('hands', pd.get('total_hands', 0)),
                        'bb100': pd.get('bb100', pd.get('bb_per_100')),
                    })
            s['positional_breakdown'] = pos_rows
        else:
            s['positional_breakdown'] = []

        # Sparkline SVG points (larger chart: 400x80)
        sparkline = s.get('sparkline') or []
        if sparkline:
            vals = [p.get('profit', 0) for p in sparkline]
            s['sparkline_points'] = _build_chart_points(vals, width=400, height=80, padding=4)
            s['sparkline_final'] = vals[-1] if vals else 0
        else:
            s['sparkline_points'] = ''
            s['sparkline_final'] = 0

        # EV chart SVG points (larger chart: 400x80)
        ev = s.get('ev_data')
        if ev and ev.get('chart_data'):
            cd = ev['chart_data']
            real_vals = [p.get('real', 0) for p in cd]
            ev_vals = [p.get('ev', 0) for p in cd]
            all_vals = real_vals + ev_vals
            s['ev_chart'] = {
                'real_points': _build_chart_points(real_vals, width=400, height=80, padding=4),
                'ev_points': _build_chart_points(ev_vals, width=400, height=80, padding=4),
                'y_min': min(all_vals) if all_vals else 0,
                'y_max': max(all_vals) if all_vals else 0,
            }
        else:
            s['ev_chart'] = None

        # Session Luck Factor card data
        if ev and ev.get('total_hands', 0) > 0:
            luck = (ev.get('real_net', 0) or 0) - (ev.get('ev_net', 0) or 0)
            luck_bb100 = (ev.get('bb100_real', 0) or 0) - (ev.get('bb100_ev', 0) or 0)
            s['luck_factor'] = {
                'real_net': ev.get('real_net', 0) or 0,
                'ev_net': ev.get('ev_net', 0) or 0,
                'luck': round(luck, 2),
                'luck_bb100': round(luck_bb100, 2),
                'allin_hands': ev.get('allin_hands', 0) or 0,
                'total_hands': ev.get('total_hands', 0) or 0,
                'status': 'hot' if luck > 0 else ('cold' if luck < 0 else 'neutral'),
            }
        else:
            s['luck_factor'] = None

        # Extended notable hands (top 5 wins + top 5 losses)
        top_hands = s.get('top_hands') or []
        if top_hands:
            wins = sorted([h for h in top_hands if (h.get('net', 0) or 0) > 0],
                          key=lambda h: h.get('net', 0), reverse=True)[:5]
            losses = sorted([h for h in top_hands if (h.get('net', 0) or 0) < 0],
                            key=lambda h: h.get('net', 0))[:5]
            s['top_wins'] = wins
            s['top_losses'] = losses
        else:
            s['top_wins'] = []
            s['top_losses'] = []

        # Leak count
        s['leak_count'] = len(s.get('leak_summary') or [])

        enriched_sessions.append(s)

    day_report['sessions'] = enriched_sessions

    # Comparison: best/worst session by profit
    if len(enriched_sessions) > 1:
        best_idx = max(range(len(enriched_sessions)),
                       key=lambda i: enriched_sessions[i].get('profit', 0))
        worst_idx = min(range(len(enriched_sessions)),
                        key=lambda i: enriched_sessions[i].get('profit', 0))
        day_report['best_session'] = best_idx
        day_report['worst_session'] = worst_idx
    else:
        day_report['best_session'] = None
        day_report['worst_session'] = None

    # Session-vs-session comparison table
    day_report['session_comparison'] = _build_session_comparison(
        enriched_sessions, global_avgs)

    data['session_day'] = day_report
    return data


# ── Overview helpers ─────────────────────────────────────────────


def _classify_health(stat_name, value):
    """Classify stat value into 'good', 'warning', 'danger', or ''."""
    if value is None:
        return ''
    h = _HEALTHY_RANGES.get(stat_name)
    w = _WARNING_RANGES.get(stat_name)
    if h and h[0] <= value <= h[1]:
        return 'good'
    if w and w[0] <= value <= w[1]:
        return 'warning'
    if h:
        return 'danger'
    return ''


def _aggregate_period(reports):
    """Aggregate daily reports into one stats row using weighted averages."""
    total_hands = 0
    total_net = 0.0
    stat_sums = {s: 0.0 for s in _STAT_NAMES}
    stat_weights = {s: 0 for s in _STAT_NAMES}

    for r in reports:
        hands = r.get('hands_count') or r.get('total_hands') or 0
        total_hands += hands
        total_net += (r.get('net', 0) or 0)

        ds = r.get('day_stats') or {}
        for s in _STAT_NAMES:
            val = ds.get(s)
            if val is not None and hands > 0:
                stat_sums[s] += val * hands
                stat_weights[s] += hands

    result = {'hands': total_hands, 'net': round(total_net, 2), 'days': len(reports)}
    for s in _STAT_NAMES:
        w = stat_weights[s]
        if w > 0:
            v = stat_sums[s] / w
            result[s] = round(v, 2) if s == 'af' else round(v, 1)
            result[f'{s}_badge'] = _classify_health(s, result[s])
        else:
            result[s] = None
            result[f'{s}_badge'] = ''
    return result


def _filter_reports_by_period(reports, period, from_date='', to_date=''):
    """Filter daily reports by time period."""
    if period == 'year' or not period:
        return reports
    if period == 'custom' and from_date and to_date:
        return [r for r in reports if from_date <= r.get('date', '') <= to_date]
    if period == 'custom':
        return reports
    today = datetime.now().date()
    days = {'1m': 30, '3m': 90}.get(period, 0)
    if not days:
        return reports
    cutoff = (today - timedelta(days=days)).strftime('%Y-%m-%d')
    return [r for r in reports if r.get('date', '') >= cutoff]


def _build_chart_points(values, width=700, height=200, padding=40):
    """Convert y-values to SVG polyline coordinates string."""
    if not values:
        return ''
    n = len(values)
    if n == 1:
        return f"{width / 2:.1f},{height / 2:.1f}"
    y_min = min(values)
    y_max = max(values)
    if y_max == y_min:
        y_max = y_min + 1
    chart_w = width - 2 * padding
    chart_h = height - 2 * padding
    pts = []
    for i, v in enumerate(values):
        x = padding + (i / (n - 1)) * chart_w
        y = height - padding - ((v - y_min) / (y_max - y_min)) * chart_h
        pts.append(f"{x:.1f},{y:.1f}")
    return ' '.join(pts)


def prepare_stats_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data for the detailed stats pages.

    Adds: stats_preflop, stats_postflop, stats_positional, stats_stack_depth,
    stats_trends_daily, stats_trends_weekly.
    """
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

    daily_reports = data.get('daily_reports', [])
    filtered = _filter_reports_by_period(daily_reports, period, from_date, to_date)

    # ── Preflop tab data ─────────────────────────────────────────
    pf = data.get('preflop_overall') or {}
    preflop_stats = []
    _PF_STATS = ['vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats', 'open_shove', 'rbw']
    for s in _PF_STATS:
        val = pf.get(s)
        badge = pf.get(f'{s}_badge', '') or pf.get(f'{s}_health', '')
        if not badge and val is not None:
            badge = _classify_health(s, val)
        preflop_stats.append({'name': s, 'label': _stat_label(s), 'value': val, 'badge': badge})
    data['stats_preflop_overall'] = preflop_stats

    # Preflop by position
    positional = data.get('positional') or {}
    preflop_by_pos = []
    for pos in _POSITION_ORDER:
        pd = positional.get(pos)
        if not pd:
            continue
        row = {'position': pos, 'hands': pd.get('total_hands', pd.get('hands', 0))}
        for s in ['vpip', 'pfr', 'three_bet']:
            row[s] = pd.get(s)
            badge = pd.get(f'{s}_health', '')
            if not badge and pd.get(s) is not None:
                badge = _classify_health(s, pd.get(s))
            row[f'{s}_badge'] = badge
        bb = pd.get('bb_per_100', pd.get('bb100', 0)) or 0
        row['bb100'] = bb
        preflop_by_pos.append(row)
    data['stats_preflop_by_pos'] = preflop_by_pos

    # ── Postflop tab data ────────────────────────────────────────
    po = data.get('postflop_overall') or {}
    postflop_stats = []
    _PO_STATS = ['af', 'afq', 'cbet', 'fold_to_cbet', 'wtsd', 'wsd', 'check_raise',
                 'won_saw_flop', 'bet_river', 'call_river', 'probe',
                 'fold_to_probe', 'bet_vs_missed_cbet', 'xf_oop']
    for s in _PO_STATS:
        val = po.get(s)
        badge = po.get(f'{s}_badge', '') or po.get(f'{s}_health', '')
        if not badge and val is not None:
            badge = _classify_health(s, val)
        postflop_stats.append({'name': s, 'label': _stat_label(s), 'value': val, 'badge': badge})
    data['stats_postflop_overall'] = postflop_stats

    # Postflop by street
    by_street = data.get('postflop_by_street') or {}
    postflop_by_street = []
    for street in ['Flop', 'Turn', 'River']:
        sd = by_street.get(street.lower(), by_street.get(street, {}))
        if not sd:
            continue
        row = {'street': street}
        for s in ['af', 'afq', 'cbet', 'check_raise']:
            row[s] = sd.get(s)
        postflop_by_street.append(row)
    data['stats_postflop_by_street'] = postflop_by_street

    # Postflop by week from by_week data
    by_week = data.get('postflop_by_week') or {}
    postflop_weekly = []
    for wk in sorted(by_week.keys()):
        wd = by_week[wk]
        row = {'week': wk}
        for s in ['af', 'cbet', 'wtsd', 'wsd']:
            row[s] = wd.get(s)
        postflop_weekly.append(row)
    data['stats_postflop_weekly'] = postflop_weekly

    # ── Trends (from daily reports) ──────────────────────────────
    sorted_reports = sorted(filtered, key=lambda r: r.get('date', ''))
    daily_trends = []
    for r in sorted_reports:
        ds = r.get('day_stats') or {}
        hands = r.get('hands_count') or r.get('total_hands') or 0
        daily_trends.append({
            'date': r.get('date', ''),
            'hands': hands,
            'vpip': ds.get('vpip'),
            'pfr': ds.get('pfr'),
            'three_bet': ds.get('three_bet'),
            'af': ds.get('af'),
            'cbet': ds.get('cbet'),
            'wtsd': ds.get('wtsd'),
            'wsd': ds.get('wsd'),
        })
    data['stats_daily_trends'] = daily_trends

    # Weekly aggregate trends
    weeks = {}
    for r in sorted_reports:
        d = r.get('date', '')
        try:
            dt = datetime.strptime(d, '%Y-%m-%d')
            iso = dt.isocalendar()
            wk = f"{iso[0]}-W{iso[1]:02d}"
        except (ValueError, IndexError):
            continue
        weeks.setdefault(wk, []).append(r)

    weekly_trends = []
    for wk in sorted(weeks):
        agg = _aggregate_period(weeks[wk])
        agg['period'] = wk
        weekly_trends.append(agg)
    data['stats_weekly_trends'] = weekly_trends

    # ── Positional tab data ──────────────────────────────────────
    pos_full = []
    for pos in _POSITION_ORDER:
        pd = positional.get(pos)
        if not pd:
            continue
        row = {'position': pos, 'hands': pd.get('total_hands', pd.get('hands', 0))}
        for s in ['vpip', 'pfr', 'three_bet', 'af', 'cbet', 'fold_to_cbet', 'wtsd', 'wsd']:
            row[s] = pd.get(s)
            badge = pd.get(f'{s}_health', '')
            if not badge and pd.get(s) is not None:
                badge = _classify_health(s, pd.get(s))
            row[f'{s}_badge'] = badge
        bb = pd.get('bb_per_100', pd.get('bb100', 0)) or 0
        row['bb100'] = bb
        row['net'] = pd.get('net', 0) or 0
        pos_full.append(row)
    data['stats_positional_full'] = pos_full

    # Best/worst positions
    if pos_full:
        best_pos = max(pos_full, key=lambda p: p.get('bb100', 0))
        worst_pos = min(pos_full, key=lambda p: p.get('bb100', 0))
        data['stats_best_position'] = best_pos
        data['stats_worst_position'] = worst_pos
    else:
        data['stats_best_position'] = None
        data['stats_worst_position'] = None

    # Blinds defense (from positional data)
    blinds_defense = data.get('positional_blinds_defense') or {}
    defense_rows = []
    for pos in ['BB', 'SB']:
        bd = blinds_defense.get(pos)
        if not bd:
            # Try to derive from positional_stats
            pd = positional.get(pos, {})
            if pd:
                bd = {
                    'fold_to_steal': pd.get('fold_to_steal'),
                    'three_bet_vs_steal': pd.get('three_bet_vs_steal'),
                    'call_vs_steal': pd.get('call_vs_steal'),
                    'total_opps': pd.get('steal_opps', 0),
                }
        if bd:
            defense_rows.append({'position': pos, **bd})
    data['stats_blinds_defense'] = defense_rows

    # ATS by position
    ats_by_pos = data.get('positional_ats_by_pos') or {}
    ats_rows = []
    for pos in ['CO', 'BTN', 'SB']:
        ad = ats_by_pos.get(pos)
        if not ad:
            pd = positional.get(pos, {})
            if pd and pd.get('ats') is not None:
                ad = {
                    'ats': pd.get('ats'),
                    'ats_opps': pd.get('ats_opps', 0),
                    'ats_count': pd.get('ats_count', 0),
                }
        if ad:
            ats_rows.append({'position': pos, **ad})
    data['stats_ats_by_pos'] = ats_rows

    # Radar chart data (pre-compute SVG coordinates)
    radar_raw = data.get('positional_radar') or {}
    data['stats_radar'] = _build_radar_svg_data(radar_raw)

    # ── Stack Depth tab data ─────────────────────────────────────
    stack_depth = data.get('stack_depth') or {}
    tier_rows = []
    _TIER_LABELS = {
        'deep': '50+ BB', 'medium': '25-50 BB',
        'shallow': '15-25 BB', 'shove': '<15 BB',
    }
    for tier in ['deep', 'medium', 'shallow', 'shove']:
        td = stack_depth.get(tier)
        if not td:
            continue
        row = {
            'tier': tier,
            'label': td.get('label', _TIER_LABELS.get(tier, tier.title())),
            'hands': td.get('total_hands', td.get('hands', 0)),
        }
        for s in ['vpip', 'pfr', 'three_bet', 'af', 'cbet', 'wtsd', 'wsd']:
            row[s] = td.get(s)
            badge = td.get(f'{s}_health', '')
            if not badge and td.get(s) is not None:
                badge = _classify_health(s, td.get(s))
            row[f'{s}_badge'] = badge
        bb = td.get('bb_per_100', td.get('bb100', 0)) or 0
        row['bb100'] = bb
        tier_rows.append(row)
    data['stats_tier_rows'] = tier_rows

    # Cross-table position x tier
    cross_table = data.get('stack_depth_cross_table') or {}
    data['stats_cross_table'] = cross_table

    return data


def _build_radar_svg_data(radar_dict):
    """Pre-compute radar chart SVG points from position→value dict."""
    import math
    if not radar_dict or not isinstance(radar_dict, dict):
        return None
    positions = list(radar_dict.keys())
    n = len(positions)
    if n < 3:
        return None
    cx, cy, r_max = 200, 200, 150
    axes = []
    polygon_pts = []
    for i, pos in enumerate(positions):
        angle = math.radians(i * 360 / n - 90)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        axes.append({
            'label': pos,
            'x1': cx, 'y1': cy,
            'x2': round(cx + r_max * cos_a, 1),
            'y2': round(cy + r_max * sin_a, 1),
            'lx': round(cx + (r_max + 25) * cos_a, 1),
            'ly': round(cy + (r_max + 25) * sin_a, 1),
        })
        val = radar_dict[pos] if isinstance(radar_dict[pos], (int, float)) else 50
        rv = r_max * (val / 100)
        polygon_pts.append(f"{cx + rv * cos_a:.0f},{cy + rv * sin_a:.0f}")
    return {
        'axes': axes,
        'polygon_points': ' '.join(polygon_pts),
        'positions': positions,
    }


_POSITION_ORDER = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']

_HAND_RANKS = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']

_STAT_LABELS = {
    'vpip': 'VPIP', 'pfr': 'PFR', 'three_bet': '3-Bet',
    'fold_to_3bet': 'Fold to 3-Bet', 'ats': 'ATS',
    'open_shove': 'Open Shove', 'rbw': 'RBW',
    'af': 'AF', 'afq': 'AFq', 'cbet': 'CBet',
    'fold_to_cbet': 'Fold to CBet', 'wtsd': 'WTSD',
    'wsd': 'W$SD', 'check_raise': 'Check-Raise',
    'won_saw_flop': 'Won Flop', 'bet_river': 'Bet River',
    'call_river': 'Call River', 'probe': 'Probe Bet',
    'fold_to_probe': 'Fold to Probe', 'bet_vs_missed_cbet': 'Bet vs MCB',
    'xf_oop': 'XF OOP',
}


def _stat_label(name):
    """Get display label for a stat name."""
    return _STAT_LABELS.get(name, name.upper())


def prepare_overview_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data with overview aggregations.

    Adds: monthly_stats, weekly_stats, overall_row, profit_chart, redline_chart.
    """
    daily_reports = data.get('daily_reports', [])
    filtered = _filter_reports_by_period(daily_reports, period, from_date, to_date)
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

    # Compute derived fields for summary if missing (e.g. tournament ROI)
    summary = data.get('summary')
    if summary and 'roi' not in summary:
        invested = summary.get('total_invested', 0) or 0
        net = summary.get('total_net', 0) or 0
        if invested > 0:
            summary['roi'] = round(net / invested * 100, 1)
        else:
            summary['roi'] = 0

    if not filtered:
        data['monthly_stats'] = []
        data['weekly_stats'] = []
        data['profit_chart'] = {}
        data['redline_chart'] = {}
        return data

    sorted_reports = sorted(filtered, key=lambda r: r.get('date', ''))

    # ── Cumulative Profit Chart ─────────────────────────────────
    cum = 0.0
    cum_vals = []
    chart_dates = []
    for r in sorted_reports:
        cum += (r.get('net', 0) or 0)
        cum_vals.append(round(cum, 2))
        chart_dates.append(r.get('date', ''))

    data['profit_chart'] = {
        'points': _build_chart_points(cum_vals),
        'dates': chart_dates,
        'values': cum_vals,
        'y_min': min(cum_vals) if cum_vals else 0,
        'y_max': max(cum_vals) if cum_vals else 0,
        'final': cum_vals[-1] if cum_vals else 0,
    }

    # ── Group by Month ──────────────────────────────────────────
    months = {}
    for r in sorted_reports:
        d = r.get('date', '')
        if len(d) >= 7:
            months.setdefault(d[:7], []).append(r)

    monthly = []
    for mk in sorted(months):
        s = _aggregate_period(months[mk])
        s['period'] = mk
        s['period_label'] = mk
        monthly.append(s)
    data['monthly_stats'] = monthly

    # ── Group by ISO Week ───────────────────────────────────────
    weeks = {}
    for r in sorted_reports:
        d = r.get('date', '')
        try:
            dt = datetime.strptime(d, '%Y-%m-%d')
            iso = dt.isocalendar()
            wk = f"{iso[0]}-W{iso[1]:02d}"
        except (ValueError, IndexError):
            continue
        weeks.setdefault(wk, []).append(r)

    weekly = []
    for wk in sorted(weeks):
        s = _aggregate_period(weeks[wk])
        s['period'] = wk
        s['period_label'] = wk
        weekly.append(s)
    data['weekly_stats'] = weekly

    # ── Overall Row ─────────────────────────────────────────────
    overall = {'period': 'overall', 'period_label': 'Overall'}
    summary = data.get('summary', {})
    overall['hands'] = summary.get('total_hands', 0)
    overall['net'] = summary.get('total_net', 0)
    overall['days'] = summary.get('total_days', 0)

    pf = data.get('preflop_overall', {})
    for s in ['vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats', 'open_shove', 'rbw']:
        overall[s] = pf.get(s)
        overall[f'{s}_badge'] = pf.get(f'{s}_badge', '') or pf.get(f'{s}_health', '')

    po = data.get('postflop_overall', {})
    for s in ['af', 'cbet', 'fold_to_cbet', 'wtsd', 'wsd',
              'won_saw_flop', 'bet_river', 'call_river', 'probe',
              'fold_to_probe', 'bet_vs_missed_cbet', 'xf_oop']:
        overall[s] = po.get(s)
        overall[f'{s}_badge'] = po.get(f'{s}_badge', '') or po.get(f'{s}_health', '')

    ev = data.get('allin_ev', {})
    overall['ev_bb100'] = ev.get('bb100_ev')
    overall['bb100_real'] = ev.get('bb100_real')
    data['overall_row'] = overall

    # ── Red/Blue Line Chart ─────────────────────────────────────
    redline = data.get('redline') or {}
    cum_data = redline.get('cumulative') or []
    if cum_data and isinstance(cum_data, list):
        total_vals = [p.get('total', 0) for p in cum_data]
        sd_vals = [p.get('showdown', 0) for p in cum_data]
        nsd_vals = [p.get('non_showdown', 0) for p in cum_data]
        all_vals = total_vals + sd_vals + nsd_vals
        data['redline_chart'] = {
            'total_points': _build_chart_points(total_vals),
            'showdown_points': _build_chart_points(sd_vals),
            'non_showdown_points': _build_chart_points(nsd_vals),
            'y_min': min(all_vals) if all_vals else 0,
            'y_max': max(all_vals) if all_vals else 0,
        }
    else:
        data['redline_chart'] = {}

    # ── Running Luck Card ───────────────────────────────────────
    ev_data = data.get('allin_ev') or {}
    ev_overall = ev_data.get('overall', ev_data) if isinstance(ev_data, dict) else {}
    total_luck = (ev_overall.get('real_net', 0) or 0) - (ev_overall.get('ev_net', 0) or 0)
    luck_bb100_diff = (ev_overall.get('bb100_real', 0) or 0) - (ev_overall.get('bb100_ev', 0) or 0)
    if ev_overall.get('total_hands', 0) > 0:
        data['running_luck'] = {
            'total_luck': round(total_luck, 2),
            'luck_bb100': round(luck_bb100_diff, 2),
            'status': 'hot' if luck_bb100_diff > 0 else ('cold' if luck_bb100_diff < 0 else 'neutral'),
            'real_net': ev_overall.get('real_net', 0) or 0,
            'ev_net': ev_overall.get('ev_net', 0) or 0,
            'allin_hands': ev_overall.get('allin_hands', 0) or 0,
        }
    else:
        data['running_luck'] = None

    # ── Mini EV Line for Overview ────────────────────────────────
    cum_real = 0.0
    cum_ev = 0.0
    mini_real_vals = []
    mini_ev_vals = []
    has_any_ev = False
    for r in sorted_reports:
        cum_real += (r.get('net', 0) or 0)
        mini_real_vals.append(round(cum_real, 2))
        ev_net = r.get('ev_net')
        # If daily report lacks ev_net, try computing from session-level ev_data
        if ev_net is None:
            for sess in (r.get('sessions') or []):
                sev = sess.get('ev_data') or {}
                if sev.get('ev_net') is not None:
                    if ev_net is None:
                        ev_net = 0.0
                    ev_net += sev['ev_net']
        if ev_net is not None:
            has_any_ev = True
            cum_ev += ev_net
        # When no ev_net, carry forward previous cumulative EV (flat line)
        mini_ev_vals.append(round(cum_ev, 2))
    all_mini = mini_real_vals + mini_ev_vals
    if all_mini and has_any_ev:
        data['overview_ev_chart'] = {
            'real_points': _build_chart_points(mini_real_vals),
            'ev_points': _build_chart_points(mini_ev_vals),
            'y_min': min(all_mini),
            'y_max': max(all_mini),
            'final_real': mini_real_vals[-1] if mini_real_vals else 0,
            'final_ev': mini_ev_vals[-1] if mini_ev_vals else 0,
            'dates': chart_dates,
        }
    else:
        data['overview_ev_chart'] = None

    # ── Leak Summary ─────────────────────────────────────────────
    from src.analyzers.leak_summary import build_leak_summary
    hs = data.get('health_score')
    leaks = data.get('leaks', [])
    # Compute health_score from leaks if not set or zero
    if (hs is None or hs == 0) and leaks:
        total_cost = sum(abs(l.get('cost_bb100', 0) or 0) for l in leaks)
        hs = max(0, min(100, int(100 - total_cost * 5)))
        data['health_score'] = hs
    if hs is not None or leaks:
        data['leak_summary'] = build_leak_summary(hs or 0, leaks)
    else:
        data['leak_summary'] = None

    return data


# ── Leaks helpers ────────────────────────────────────────────


def prepare_leaks_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data for the leaks page.

    Adds: health_score_val, health_score_class, top_leaks, study_spots,
    leaks_by_category, period_comparison.
    """
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

    leaks = data.get('leaks', [])

    # Health score
    hs = data.get('health_score')
    if hs is None and leaks:
        total_cost = sum(abs(l.get('cost_bb100', 0)) for l in leaks)
        hs = max(0, min(100, int(100 - total_cost * 5)))
    elif hs is None:
        hs = 100
    data['health_score_val'] = int(hs)
    if hs >= 70:
        data['health_score_class'] = 'good'
    elif hs >= 40:
        data['health_score_class'] = 'warning'
    else:
        data['health_score_class'] = 'danger'

    # Top 5 leaks sorted by cost
    sorted_leaks = sorted(leaks, key=lambda l: abs(l.get('cost_bb100', 0)), reverse=True)
    data['top_leaks'] = sorted_leaks[:5]

    # Study spots (leaks with suggestions, prioritized by cost)
    data['study_spots'] = [l for l in sorted_leaks if l.get('suggestion')][:5]

    # Group leaks by category
    cats = {}
    for l in leaks:
        cat = l.get('category', 'Other')
        cats.setdefault(cat, []).append(l)
    data['leaks_by_category'] = cats

    # Period comparison: current vs previous period stats
    daily_reports = data.get('daily_reports', [])
    filtered = _filter_reports_by_period(daily_reports, period, from_date, to_date)
    current_agg = _aggregate_period(filtered) if filtered else {}

    remaining = [r for r in daily_reports if r not in filtered]
    prev_agg = _aggregate_period(remaining) if remaining else {}

    comparison = []
    for s in ['vpip', 'pfr', 'three_bet', 'af', 'cbet', 'wtsd', 'wsd']:
        cur = current_agg.get(s)
        prev = prev_agg.get(s)
        diff = None
        if cur is not None and prev is not None:
            diff = round(cur - prev, 2)
        comparison.append({
            'stat': s, 'label': _stat_label(s),
            'current': cur, 'previous': prev, 'diff': diff,
            'current_badge': current_agg.get(f'{s}_badge', ''),
            'previous_badge': prev_agg.get(f'{s}_badge', ''),
        })
    data['period_comparison'] = comparison
    data['period_current_hands'] = current_agg.get('hands', 0)
    data['period_previous_hands'] = prev_agg.get('hands', 0)

    return data


# ── EV helpers ───────────────────────────────────────────────


def prepare_ev_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data for the EV analysis page.

    Adds: ev_summary, ev_chart, decision_ev_data, redline_chart, ev_bb_comparison.
    """
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

    raw_ev = data.get('allin_ev') or {}
    # Flatten 'overall' sub-dict to top level for template access
    ev = dict(raw_ev.get('overall', raw_ev))
    ev['by_stakes'] = raw_ev.get('by_stakes', {})
    ev['allin_count'] = ev.get('allin_hands', 0)
    data['ev_summary'] = ev

    # Build cumulative EV vs Real line chart from daily reports
    daily_reports = data.get('daily_reports', [])
    filtered = _filter_reports_by_period(daily_reports, period, from_date, to_date)
    sorted_reports = sorted(filtered, key=lambda r: r.get('date', ''))

    cum_real = 0.0
    real_vals = []
    chart_dates = []
    for r in sorted_reports:
        cum_real += (r.get('net', 0) or 0)
        real_vals.append(round(cum_real, 2))
        chart_dates.append(r.get('date', ''))

    cum_ev = 0.0
    ev_vals = []
    has_any_ev = False
    for r in sorted_reports:
        ev_net = r.get('ev_net')
        # If daily report lacks ev_net, try computing from session-level ev_data
        if ev_net is None:
            for sess in (r.get('sessions') or []):
                sev = sess.get('ev_data') or {}
                if sev.get('ev_net') is not None:
                    if ev_net is None:
                        ev_net = 0.0
                    ev_net += sev['ev_net']
        if ev_net is not None:
            has_any_ev = True
            cum_ev += ev_net
        # When no ev_net, carry forward previous cumulative EV (flat line)
        ev_vals.append(round(cum_ev, 2))

    all_vals = real_vals + ev_vals
    if all_vals and has_any_ev:
        data['ev_chart'] = {
            'real_points': _build_chart_points(real_vals),
            'ev_points': _build_chart_points(ev_vals),
            'dates': chart_dates,
            'y_min': min(all_vals),
            'y_max': max(all_vals),
            'final_real': real_vals[-1] if real_vals else 0,
            'final_ev': ev_vals[-1] if ev_vals else 0,
        }
    else:
        # Fallback: use pre-computed chart_data from allin_ev analyzer
        chart_data = raw_ev.get('chart_data', [])
        if chart_data:
            r_vals = [pt.get('real', 0) for pt in chart_data]
            e_vals = [pt.get('ev', 0) for pt in chart_data]
            all_v = r_vals + e_vals
            data['ev_chart'] = {
                'real_points': _build_chart_points(r_vals),
                'ev_points': _build_chart_points(e_vals),
                'dates': [str(pt.get('hand', '')) for pt in chart_data],
                'y_min': min(all_v) if all_v else 0,
                'y_max': max(all_v) if all_v else 0,
                'final_real': r_vals[-1] if r_vals else 0,
                'final_ev': e_vals[-1] if e_vals else 0,
            }
        else:
            data['ev_chart'] = {}

    # Decision EV by street — flatten nested dict into list for template
    raw_dev = data.get('decision_ev') or {}
    dev_by_street = raw_dev.get('by_street', {})
    if isinstance(dev_by_street, list):
        flat_rows = dev_by_street
    elif isinstance(dev_by_street, dict):
        flat_rows = []
        for street, decisions in dev_by_street.items():
            if isinstance(decisions, dict):
                for decision, stats in decisions.items():
                    if isinstance(stats, dict):
                        flat_rows.append({
                            'street': street,
                            'decision': decision,
                            'count': stats.get('count', 0),
                            'total_net': stats.get('total_net', 0),
                            'avg_net': stats.get('avg_net', 0),
                        })
    else:
        flat_rows = []
    raw_dev['by_street'] = flat_rows
    data['decision_ev_data'] = raw_dev

    # bb/100 comparison
    data['ev_bb_comparison'] = {
        'real': ev.get('bb100_real', 0) or 0,
        'ev': ev.get('bb100_ev', 0) or 0,
        'diff': round((ev.get('bb100_real', 0) or 0) - (ev.get('bb100_ev', 0) or 0), 2),
    }

    # Red/Blue line chart
    redline = data.get('redline') or {}
    cum_data = redline.get('cumulative') or []
    if cum_data and isinstance(cum_data, list):
        total_vals = [p.get('total', 0) for p in cum_data]
        sd_vals = [p.get('showdown', 0) for p in cum_data]
        nsd_vals = [p.get('non_showdown', 0) for p in cum_data]
        all_v = total_vals + sd_vals + nsd_vals
        data['ev_redline_chart'] = {
            'total_points': _build_chart_points(total_vals),
            'showdown_points': _build_chart_points(sd_vals),
            'non_showdown_points': _build_chart_points(nsd_vals),
            'y_min': min(all_v) if all_v else 0,
            'y_max': max(all_v) if all_v else 0,
        }
    else:
        data['ev_redline_chart'] = {}

    # ── EV Per Session Table ─────────────────────────────────────
    ev_sessions = []
    cum_luck = 0.0
    luck_trend_vals = []
    luck_trend_dates = []
    for r in sorted_reports:
        date = r.get('date', '')
        sess_list = r.get('sessions') or []
        day_luck = 0.0
        day_has_ev = False
        day_hands = r.get('hands_count') or r.get('total_hands') or 0
        day_allin = 0
        day_real = r.get('net', 0) or 0
        day_ev = 0.0
        for sess in sess_list:
            sev = sess.get('ev_data') or {}
            if sev.get('total_hands', 0) > 0:
                day_has_ev = True
                s_luck = (sev.get('real_net', 0) or 0) - (sev.get('ev_net', 0) or 0)
                day_luck += s_luck
                day_allin += sev.get('allin_hands', 0) or 0
                day_ev += sev.get('ev_net', 0) or 0
        if not day_has_ev:
            day_ev = day_real
        cum_luck += day_luck
        luck_trend_vals.append(round(cum_luck, 2))
        luck_trend_dates.append(date)
        if day_has_ev:
            ev_sessions.append({
                'date': date,
                'hands': day_hands,
                'allins': day_allin,
                'real_net': round(day_real, 2),
                'ev_net': round(day_ev, 2),
                'luck': round(day_luck, 2),
                'luck_bb100': None,
            })
    data['ev_sessions_table'] = ev_sessions

    # ── Luck Over Time Chart ─────────────────────────────────────
    if luck_trend_vals and any(v != 0 for v in luck_trend_vals):
        data['luck_trend_chart'] = {
            'points': _build_chart_points(luck_trend_vals),
            'dates': luck_trend_dates,
            'y_min': min(luck_trend_vals),
            'y_max': max(luck_trend_vals),
            'final': luck_trend_vals[-1] if luck_trend_vals else 0,
        }
    else:
        data['luck_trend_chart'] = None

    return data


# ── Range helpers ────────────────────────────────────────────


def _build_range_matrix(raw_matrix):
    """Build a 13×13 matrix from a raw hand-combo dict.

    Returns (matrix_rows, net_min, net_max) where net_min/max are used for
    heatmap gradient scaling.
    """
    net_min = 0.0
    net_max = 0.0
    matrix_rows = []
    for r in range(13):
        row = []
        for c in range(13):
            if r == c:
                hand = _HAND_RANKS[r] + _HAND_RANKS[c]
                hand_type = 'pair'
            elif r < c:
                hand = _HAND_RANKS[r] + _HAND_RANKS[c] + 's'
                hand_type = 'suited'
            else:
                hand = _HAND_RANKS[c] + _HAND_RANKS[r] + 'o'
                hand_type = 'offsuit'
            cell_data = raw_matrix.get(hand, {})
            if isinstance(cell_data, dict):
                freq = cell_data.get('frequency', 0)
                net = cell_data.get('net', 0)
                hands_count = cell_data.get('hands', 0)
                played = cell_data.get('played', 0)
                bb100 = cell_data.get('bb100', cell_data.get('win_rate', 0))
                action = cell_data.get('action_breakdown', {})
                if isinstance(action, str):
                    try:
                        import json as _json
                        action = _json.loads(action)
                    except (ValueError, TypeError):
                        action = {}
            else:
                freq = cell_data if isinstance(cell_data, (int, float)) else 0
                net = 0
                hands_count = 0
                played = 0
                bb100 = 0
                action = {}
            dealt = cell_data.get('dealt', hands_count) if isinstance(cell_data, dict) else hands_count
            freq_pct = round(played / dealt * 100, 1) if dealt > 0 else freq
            open_raise = action.get('open_raise', 0) if isinstance(action, dict) else 0
            call = action.get('call', 0) if isinstance(action, dict) else 0
            three_bet = action.get('three_bet', 0) if isinstance(action, dict) else 0
            if hands_count > 0:
                if net < net_min:
                    net_min = net
                if net > net_max:
                    net_max = net
            row.append({
                'hand': hand, 'type': hand_type,
                'freq': freq, 'freq_pct': freq_pct, 'net': net,
                'hands': hands_count, 'dealt': dealt, 'played': played,
                'bb100': bb100,
                'open_raise': open_raise, 'call': call, 'three_bet': three_bet,
            })
        matrix_rows.append(row)
    return matrix_rows, net_min, net_max


def _compute_heatmap_intensity(net, net_min, net_max):
    """Return heatmap intensity 0.0–1.0 and color (green/red) for a net value."""
    if net > 0 and net_max > 0:
        intensity = min(net / net_max, 1.0)
        return intensity, 'green'
    elif net < 0 and net_min < 0:
        intensity = min(abs(net) / abs(net_min), 1.0)
        return intensity, 'red'
    return 0.0, 'neutral'


def _apply_heatmap_styles(matrix_rows, net_min, net_max):
    """Add heatmap_bg inline style to each cell in the matrix."""
    for row in matrix_rows:
        for cell in row:
            intensity, color = _compute_heatmap_intensity(
                cell['net'], net_min, net_max)
            if color == 'green' and intensity > 0:
                alpha = round(0.1 + intensity * 0.35, 3)
                cell['heatmap_bg'] = f'rgba(63,185,80,{alpha})'
            elif color == 'red' and intensity > 0:
                alpha = round(0.1 + intensity * 0.35, 3)
                cell['heatmap_bg'] = f'rgba(248,81,73,{alpha})'
            else:
                cell['heatmap_bg'] = ''
            cell['heatmap_intensity'] = round(intensity, 3)


def prepare_range_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data for the range analysis page.

    Adds: range_positions, hand_ranks, range_matrices, range_net_bounds,
    top_profitable, top_deficit.
    """
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

    positional = data.get('positional') or {}
    hand_matrix_all = data.get('hand_matrix') or {}

    positions = []
    for pos in _POSITION_ORDER:
        if pos in positional:
            positions.append(pos)

    # Build Overall aggregate from all position data
    overall_raw = {}
    for pos in positions:
        pos_data = positional.get(pos, {})
        raw = pos_data.get('hand_matrix') or hand_matrix_all.get(pos, {})
        if not isinstance(raw, dict):
            continue
        for combo, stats in raw.items():
            if not isinstance(stats, dict):
                continue
            if combo not in overall_raw:
                overall_raw[combo] = {
                    'hands': 0, 'played': 0, 'dealt': 0, 'net': 0.0,
                    'frequency': 0, 'open_raise': 0, 'call': 0, 'three_bet': 0,
                }
            overall_raw[combo]['hands'] += stats.get('hands', 0)
            overall_raw[combo]['played'] += stats.get('played', 0)
            overall_raw[combo]['dealt'] += stats.get('dealt', stats.get('hands', 0))
            overall_raw[combo]['net'] += stats.get('net', 0)
            ab = stats.get('action_breakdown', {})
            if isinstance(ab, str):
                try:
                    import json as _json
                    ab = _json.loads(ab)
                except (ValueError, TypeError):
                    ab = {}
            if isinstance(ab, dict):
                overall_raw[combo]['open_raise'] += ab.get('open_raise', 0)
                overall_raw[combo]['call'] += ab.get('call', 0)
                overall_raw[combo]['three_bet'] += ab.get('three_bet', 0)
    # Finalize overall aggregate fields
    for combo, stats in overall_raw.items():
        d = stats.get('dealt', 0)
        p = stats.get('played', 0)
        stats['frequency'] = round(p / d * 100, 1) if d > 0 else 0
        stats['bb100'] = round(stats['net'] / stats['hands'] * 100, 1) if stats['hands'] > 0 else 0
        stats['action_breakdown'] = {
            'open_raise': stats.pop('open_raise', 0),
            'call': stats.pop('call', 0),
            'three_bet': stats.pop('three_bet', 0),
        }

    # Insert Overall as first tab when there are position-level matrices
    if positions:
        positions = ['Overall'] + positions
    else:
        positions = ['Overall']
    data['range_positions'] = positions
    data['hand_ranks'] = _HAND_RANKS

    matrices = {}
    global_net_min = 0.0
    global_net_max = 0.0
    for pos in positions:
        if pos == 'Overall':
            raw_matrix = overall_raw
        else:
            pos_data = positional.get(pos, {})
            raw_matrix = pos_data.get('hand_matrix') or hand_matrix_all.get(pos, {})
        matrix_rows, nmin, nmax = _build_range_matrix(raw_matrix)
        if nmin < global_net_min:
            global_net_min = nmin
        if nmax > global_net_max:
            global_net_max = nmax
        matrices[pos] = matrix_rows

    # Apply heatmap intensity styles using global bounds
    for pos in positions:
        _apply_heatmap_styles(matrices[pos], global_net_min, global_net_max)

    data['range_matrices'] = matrices
    data['range_net_bounds'] = {'min': global_net_min, 'max': global_net_max}

    # Top 10 profitable and deficit hands — aggregate from hand_matrix across positions
    hand_stats = data.get('hand_stats') or data.get('hand_performance') or {}
    if not hand_stats and hand_matrix_all:
        # Aggregate combos across all positions
        combo_totals = {}
        for pos, combos in hand_matrix_all.items():
            if not isinstance(combos, dict):
                continue
            for combo, stats in combos.items():
                if not isinstance(stats, dict):
                    continue
                if combo not in combo_totals:
                    combo_totals[combo] = {'hand': combo, 'hands': 0, 'played': 0, 'net': 0.0, 'bb100': 0.0}
                combo_totals[combo]['hands'] += stats.get('hands', 0)
                combo_totals[combo]['played'] += stats.get('played', 0)
                combo_totals[combo]['net'] += stats.get('net', 0)
        # Recalculate bb100 from aggregate
        for c in combo_totals.values():
            if c['hands'] > 0:
                c['bb100'] = round(c['net'] / c['hands'] * 100, 1)
        hand_stats = list(combo_totals.values())

    if isinstance(hand_stats, list):
        sorted_by_net = sorted(hand_stats, key=lambda h: h.get('net', 0), reverse=True)
        data['top_profitable'] = sorted_by_net[:10]
        data['top_deficit'] = sorted(hand_stats, key=lambda h: h.get('net', 0))[:10]
    elif isinstance(hand_stats, dict) and hand_stats:
        items = [{'hand': k, **v} if isinstance(v, dict) else {'hand': k, 'net': v}
                 for k, v in hand_stats.items()]
        sorted_by_net = sorted(items, key=lambda h: h.get('net', 0), reverse=True)
        data['top_profitable'] = sorted_by_net[:10]
        data['top_deficit'] = sorted(items, key=lambda h: h.get('net', 0))[:10]
    else:
        data['top_profitable'] = []
        data['top_deficit'] = []

    return data


# ── Tilt helpers ─────────────────────────────────────────────


def prepare_tilt_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data for the tilt analysis page.

    Adds: tilt_sessions, tilt_heatmap, tilt_duration, tilt_post_bad_beat,
    tilt_recommendation, tilt_session_summary.
    """
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

    tilt = data.get('tilt', {})

    session_tilt = tilt.get('session_tilt', {})

    # Normalize session_tilt list: map analyzer keys to template keys
    if isinstance(session_tilt, list):
        normalized = []
        total = len(session_tilt)
        tilt_count = 0
        total_cost = 0.0
        for s in session_tilt:
            row = dict(s)
            # Map analyzer keys to template-expected keys
            if 'date' not in row and 'session_date' in row:
                row['date'] = row['session_date']
            if 'cost_bb' not in row and 'tilt_cost_bb' in row:
                row['cost_bb'] = row['tilt_cost_bb']
            if 'trigger' not in row:
                signals = row.get('tilt_signals', [])
                if isinstance(signals, list) and signals:
                    row['trigger'] = ', '.join(str(sig) for sig in signals)
                elif row.get('reason'):
                    row['trigger'] = row['reason']
                else:
                    row['trigger'] = ''
            if 'session' not in row and 'session_id' not in row:
                row['session'] = row.get('date', '')
            if row.get('severity') in ('warning', 'danger'):
                tilt_count += 1
                total_cost += abs(row.get('cost_bb', 0) or 0)
            normalized.append(row)
        data['tilt_sessions'] = normalized
        data['tilt_session_summary'] = {
            'total_sessions': total,
            'tilt_sessions': tilt_count,
            'tilt_pct': round(tilt_count / total * 100, 1) if total > 0 else 0,
            'tilt_cost': round(total_cost, 2),
        }
    elif isinstance(session_tilt, dict):
        data['tilt_sessions'] = session_tilt
        data['tilt_session_summary'] = session_tilt
    else:
        data['tilt_sessions'] = []
        data['tilt_session_summary'] = {}

    # Hourly heatmap (24h)
    hourly = tilt.get('hourly', {})
    # Handle both dict-of-hours and list-of-hours formats
    by_hour = hourly.get('by_hour', {})
    hourly_list = hourly.get('hourly', [])
    # If by_hour is empty, try building from list format
    if not by_hour and isinstance(hourly_list, list):
        for item in hourly_list:
            if isinstance(item, dict) and 'hour' in item:
                by_hour[str(item['hour'])] = item
    heatmap = []
    for h in range(24):
        hk = str(h)
        hd = by_hour.get(hk, by_hour.get(h, {}))
        if isinstance(hd, dict):
            bb100 = hd.get('bb100', hd.get('win_rate_bb100', 0)) or 0
            hands = hd.get('hands', 0) or 0
        else:
            bb100 = 0
            hands = 0
        heatmap.append({
            'hour': h, 'label': f'{h:02d}:00',
            'bb100': round(bb100, 1), 'hands': int(hands),
        })

    active_cells = [c for c in heatmap if c['hands'] > 0]
    if active_cells:
        bb_vals = [c['bb100'] for c in active_cells]
        bb_min = min(bb_vals)
        bb_max = max(bb_vals)
    else:
        bb_min = bb_max = 0

    for c in heatmap:
        if c['hands'] == 0:
            c['intensity'] = 'none'
        elif bb_max == bb_min:
            c['intensity'] = 'neutral'
        elif c['bb100'] >= 0:
            norm = c['bb100'] / bb_max if bb_max > 0 else 0
            c['intensity'] = 'hot' if norm >= 0.6 else ('warm' if norm >= 0.3 else 'neutral')
        else:
            norm = c['bb100'] / bb_min if bb_min < 0 else 0
            c['intensity'] = 'cold' if norm >= 0.6 else ('cool' if norm >= 0.3 else 'neutral')

    data['tilt_heatmap'] = heatmap

    # Duration analysis — try both key names
    duration = tilt.get('duration_analysis') or tilt.get('duration', {})
    if isinstance(duration, dict):
        # Normalize: ensure 'by_duration' key exists for the template
        buckets = duration.get('by_duration') or duration.get('buckets', [])
        if isinstance(buckets, list):
            for b in buckets:
                if isinstance(b, dict):
                    # Normalize keys: 'win_rate_bb100' -> 'bb100', 'avg_profit'
                    if 'bb100' not in b and 'win_rate_bb100' in b:
                        b['bb100'] = b['win_rate_bb100']
                    if 'avg_profit' not in b and 'net' in b and 'count' not in b:
                        b['avg_profit'] = b['net']
                    if 'count' not in b:
                        b['count'] = b.get('sessions', b.get('hands', 0))
            duration['by_duration'] = buckets
    data['tilt_duration'] = duration

    # Post-bad-beat — normalize keys
    pbb = tilt.get('post_bad_beat', {})
    if isinstance(pbb, dict):
        if 'bad_beats' not in pbb and 'bad_beat_count' in pbb:
            pbb['bad_beats'] = pbb['bad_beat_count']
        if 'tilt_after_bb' not in pbb and 'post_bb_tilt_count' in pbb:
            pbb['tilt_after_bb'] = pbb['post_bb_tilt_count']
        if 'avg_loss_after' not in pbb and 'degradation_bb100' in pbb:
            pbb['avg_loss_after'] = pbb['degradation_bb100']
        if 'recovery_rate' not in pbb:
            bb = pbb.get('bad_beats', 0) or 0
            tilt_after = pbb.get('tilt_after_bb', 0) or 0
            if bb > 0:
                pbb['recovery_rate'] = round((1 - tilt_after / bb) * 100, 1)
    data['tilt_post_bad_beat'] = pbb

    # Recommendation — normalize keys
    rec = tilt.get('recommendation', {})
    if isinstance(rec, dict):
        if 'ideal_duration' not in rec and 'best_bucket' in rec:
            rec['ideal_duration'] = rec['best_bucket']
        if 'message' not in rec and 'text' in rec:
            rec['message'] = rec['text']
    data['tilt_recommendation'] = rec

    return data


# ── Sizing helpers ───────────────────────────────────────────


def prepare_sizing_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data for the sizing page.

    Adds: pot_types, sizing_preflop, sizing_postflop, sizing_by_street.
    """
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

    bs = data.get('bet_sizing') or {}

    # pot_types may be a dict keyed by type name — flatten into list for template
    _POT_TYPE_LABELS = {
        'limped': 'Limped', 'srp': 'Single Raised',
        '3bet': '3-Bet', '4bet_plus': '4-Bet+',
    }
    raw_pt = bs.get('pot_types', [])
    if isinstance(raw_pt, dict):
        pot_list = []
        for pt_name, pt_data in raw_pt.items():
            if isinstance(pt_data, dict):
                row = {
                    'label': _POT_TYPE_LABELS.get(pt_name, pt_name),
                    'count': pt_data.get('hands', 0) or 0,
                    'win_rate': pt_data.get('wsd', pt_data.get('win_pct', 0)) or 0,
                    'net': pt_data.get('net', pt_data.get('total_net', 0)) or 0,
                    'bb100': pt_data.get('win_rate_bb100', 0) or 0,
                    'af': pt_data.get('af', 0) or 0,
                    'cbet': pt_data.get('cbet', 0) or 0,
                    'health': pt_data.get('health', ''),
                }
                pot_list.append(row)
        total_count = sum(r.get('count', 0) or 0 for r in pot_list)
        for r in pot_list:
            cnt = r.get('count', 0) or 0
            r['pct'] = round(cnt / total_count * 100, 1) if total_count > 0 else 0
        raw_pt = pot_list
    data['pot_types'] = raw_pt

    # Preflop/postflop sizing — compute pct if missing
    preflop_sizing = bs.get('preflop_sizing', [])
    if isinstance(preflop_sizing, list) and preflop_sizing:
        total = sum(b.get('count', 0) or 0 for b in preflop_sizing)
        for b in preflop_sizing:
            if not b.get('pct') and total > 0:
                b['pct'] = round((b.get('count', 0) or 0) / total * 100, 1)
    data['sizing_preflop'] = preflop_sizing

    postflop_sizing = bs.get('postflop_sizing', [])
    if isinstance(postflop_sizing, list) and postflop_sizing:
        total = sum(b.get('count', 0) or 0 for b in postflop_sizing)
        for b in postflop_sizing:
            if not b.get('pct') and total > 0:
                b['pct'] = round((b.get('count', 0) or 0) / total * 100, 1)
    data['sizing_postflop'] = postflop_sizing

    # By street sizing — also compute pct per street if missing
    by_street = bs.get('by_street', {})
    if isinstance(by_street, dict):
        for street, street_data in by_street.items():
            if isinstance(street_data, list):
                total = sum(b.get('count', 0) or 0 for b in street_data)
                for b in street_data:
                    if not b.get('pct') and total > 0:
                        b['pct'] = round((b.get('count', 0) or 0) / total * 100, 1)
    data['sizing_by_street'] = by_street

    return data


# ── Satellites / Spin helpers ───────────────────────────────────


def prepare_satellites_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data for the satellites page.

    Adds: sat_summary, sat_categories, sat_cycle, sat_timeline,
    sat_recent, sat_chart.
    """
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

    sat = data.get('satellite_analysis') or {}
    if not sat:
        return data

    data['sat_summary'] = sat.get('summary', {})
    data['sat_categories'] = sat.get('by_category', {})
    data['sat_cycle'] = sat.get('cycle', {})
    data['sat_recent'] = sat.get('recent_results', [])

    # Build timeline chart
    timeline = sat.get('timeline', [])
    if timeline:
        cum_vals = [t.get('cumulative', 0) for t in timeline]
        dates = [t.get('date', '') for t in timeline]
        data['sat_chart'] = {
            'points': _build_chart_points(cum_vals),
            'dates': dates,
            'y_min': min(cum_vals) if cum_vals else 0,
            'y_max': max(cum_vals) if cum_vals else 0,
            'final': cum_vals[-1] if cum_vals else 0,
        }
        data['sat_timeline'] = timeline
    else:
        data['sat_chart'] = {}
        data['sat_timeline'] = []

    return data


# ── Lessons helpers ──────────────────────────────────────────────


def prepare_lessons_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data for the lessons dashboard page.

    Adds: lesson_summary, lessons_list, lessons_by_category,
    lessons_errors_only, lessons_study_suggestions.
    """
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

    lesson_stats = data.get('lesson_stats', {})
    lesson_summary = data.get('lesson_summary') or {}

    # Overview cards
    data['lesson_total'] = lesson_summary.get('total_lessons', 23)
    data['lesson_classified_hands'] = lesson_summary.get('total_hands', 0)
    data['lesson_global_accuracy'] = lesson_summary.get('global_accuracy')
    data['lesson_mastered'] = lesson_summary.get('mastered', 0)
    data['lesson_learning'] = lesson_summary.get('learning', 0)
    data['lesson_needs_work'] = lesson_summary.get('needs_work', 0)
    data['lesson_with_data'] = lesson_summary.get('total_lessons_with_data', 0)

    # Per-lesson list sorted by accuracy (worst first for study prioritization)
    lessons_list = sorted(
        lesson_stats.values(),
        key=lambda l: (
            0 if l.get('accuracy') is None else 1,
            l.get('accuracy', 100),
        ),
    )
    data['lessons_list'] = lessons_list

    # Group by category
    by_category = lesson_summary.get('by_category', {})
    cat_list = []
    for cat_name in ('Preflop', 'Postflop', 'Torneios'):
        cat_data = by_category.get(cat_name)
        if cat_data:
            cat_list.append({
                'name': cat_name,
                'total': cat_data.get('total', 0),
                'correct': cat_data.get('correct', 0),
                'incorrect': cat_data.get('incorrect', 0),
                'accuracy': cat_data.get('accuracy'),
            })
    data['lessons_by_category'] = cat_list

    # Category accuracy chart data (bar chart)
    cat_chart = []
    for c in cat_list:
        acc = c.get('accuracy')
        if acc is not None:
            cat_chart.append({'name': c['name'], 'accuracy': acc})
    data['lessons_cat_chart'] = cat_chart

    # Errors-only filter: lessons with error_rate > 0
    errors_only = [l for l in lessons_list
                   if l.get('incorrect', 0) > 0]
    data['lessons_errors_only'] = errors_only

    # Study suggestions: lessons with worst accuracy (needs_work + learning)
    study = [l for l in lessons_list
             if l.get('mastery') in ('needs_work', 'learning')
             and l.get('accuracy') is not None]
    data['lessons_study_suggestions'] = study[:5]

    # Mastery distribution for progress bar
    total_with_data = data['lesson_with_data']
    if total_with_data > 0:
        data['mastery_pct'] = round(data['lesson_mastered'] / total_with_data * 100, 1)
    else:
        data['mastery_pct'] = 0

    return data


# ── Session Lesson Tab helpers ────────────────────────────────────


def prepare_session_day_lessons(data, date, game_type, poker_db_path):
    """Load per-day lesson performance from the main poker DB.

    Queries hands JOIN hand_lessons JOIN lessons filtered by date and
    game_type, then aggregates per-lesson stats with urgency ranking.

    Adds: data['session_day_lessons'] = {
        'summary': {total_hands, correct, incorrect, accuracy},
        'lessons': [{lesson_id, title, category, total_hands, correct,
                     incorrect, accuracy, mastery, global_accuracy,
                     vs_global, urgency, hands: [...]}, ...]
    } or None if no data available.
    """
    if not poker_db_path or not os.path.exists(poker_db_path):
        data['session_day_lessons'] = None
        return data

    try:
        conn = sqlite3.connect(poker_db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT
                l.lesson_id, l.title, l.category,
                h.hand_id, h.hero_cards, h.hero_position, h.net, h.date,
                hl.executed_correctly, hl.street
            FROM hands h
            JOIN hand_lessons hl ON h.hand_id = hl.hand_id
            JOIN lessons l ON hl.lesson_id = l.lesson_id
            WHERE h.game_type = ?
              AND substr(h.date, 1, 10) = ?
            ORDER BY l.lesson_id
        """, (game_type, date)).fetchall()
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        data['session_day_lessons'] = None
        return data

    if not rows:
        data['session_day_lessons'] = None
        return data

    # Aggregate per lesson
    lesson_map = {}
    for row in rows:
        lid = row['lesson_id']
        if lid not in lesson_map:
            lesson_map[lid] = {
                'lesson_id': lid,
                'title': row['title'],
                'category': row['category'],
                'correct': 0,
                'incorrect': 0,
                'unknown': 0,
                'total_hands': 0,
                'hands': [],
            }
        ec = row['executed_correctly']
        lesson_map[lid]['total_hands'] += 1
        if ec == 1:
            lesson_map[lid]['correct'] += 1
        elif ec == 0:
            lesson_map[lid]['incorrect'] += 1
        else:
            lesson_map[lid]['unknown'] += 1
        lesson_map[lid]['hands'].append({
            'hand_id': row['hand_id'],
            'hero_cards': row['hero_cards'] or '',
            'hero_position': row['hero_position'] or '',
            'net': row['net'] or 0.0,
            'executed_correctly': ec,
            'street': row['street'] or '',
            'date': row['date'] or '',
        })

    # Global lesson stats for comparison
    global_lesson_stats = data.get('lesson_stats', {})

    # Build enriched lesson list
    lesson_list = []
    for lesson in lesson_map.values():
        correct = lesson['correct']
        incorrect = lesson['incorrect']
        known = correct + incorrect
        accuracy = round(correct / known * 100, 1) if known > 0 else None

        global_stat = global_lesson_stats.get(lesson['lesson_id'])
        global_accuracy = global_stat.get('accuracy') if global_stat else None
        mastery = global_stat.get('mastery', 'no_data') if global_stat else 'no_data'

        if accuracy is not None and global_accuracy is not None:
            diff = accuracy - global_accuracy
            vs_global = 'same' if abs(diff) < 5.0 else ('better' if diff > 0 else 'worse')
        else:
            vs_global = ''

        # Urgency: incorrect hands weighted by error rate (worst accuracy + most errors)
        urgency = incorrect * (1.0 - accuracy / 100.0) if accuracy is not None else float(incorrect)

        lesson_list.append({
            **lesson,
            'accuracy': accuracy,
            'mastery': mastery,
            'global_accuracy': global_accuracy,
            'vs_global': vs_global,
            'urgency': urgency,
        })

    # Sort by urgency descending, then total_hands descending
    lesson_list.sort(key=lambda l: (-l['urgency'], -l['total_hands']))

    # Day-level summary
    total_hands = sum(l['total_hands'] for l in lesson_list)
    total_correct = sum(l['correct'] for l in lesson_list)
    total_incorrect = sum(l['incorrect'] for l in lesson_list)
    known = total_correct + total_incorrect
    summary_accuracy = round(total_correct / known * 100, 1) if known > 0 else None

    data['session_day_lessons'] = {
        'summary': {
            'total_hands': total_hands,
            'correct': total_correct,
            'incorrect': total_incorrect,
            'accuracy': summary_accuracy,
        },
        'lessons': lesson_list,
    }
    return data


# ── Hand Replayer ─────────────────────────────────────────────────

_STREET_ORDER = {'preflop': 0, 'flop': 1, 'turn': 2, 'river': 3}
_POT_ACTION_TYPES = {'post_sb', 'post_bb', 'post_ante', 'bet', 'call', 'all-in'}


def _build_replay_steps(actions: list[dict]) -> list[dict]:
    """Build step-by-step replay from ordered hand actions.

    Each step represents one player action, with running pot and
    visible board cards computed progressively.
    """
    steps = []
    pot = 0.0
    # Per-player investment in current street (for raise delta calculation)
    street_investments: dict[str, float] = {}
    current_street = None

    for action in actions:
        street = action.get('street', 'preflop')
        if street != current_street:
            current_street = street
            street_investments = {}

        player = action.get('player', '')
        atype = action.get('action_type', '')
        amount = float(action.get('amount') or 0)

        # Calculate pot delta
        if atype in _POT_ACTION_TYPES:
            delta = amount
            street_investments[player] = street_investments.get(player, 0) + amount
        elif atype == 'raise':
            prev = street_investments.get(player, 0)
            delta = max(0.0, amount - prev)
            street_investments[player] = amount
        else:
            delta = 0.0

        pot_before = pot
        pot = round(pot + delta, 2)

        steps.append({
            'idx': len(steps),
            'street': street,
            'player': player,
            'action_type': atype,
            'amount': amount,
            'is_hero': bool(action.get('is_hero')),
            'position': action.get('position') or '',
            'pot_before': round(pot_before, 2),
            'pot_after': pot,
        })

    return steps


def prepare_hand_replayer(hand_id: str, poker_db_path: str,
                          lesson_id: int = None) -> dict:
    """Load hand data for the step-by-step replayer from poker.db.

    Returns a dict with:
      - hand:          hand metadata (or None if not found)
      - steps:         list of replay steps built from hand_actions
      - positions:     unique positions seen in hand (canonical order)
      - lesson_notes:  lesson notes/title if lesson_id provided, else None
      - lesson_id:     echo of the requested lesson_id
    """
    result: dict = {
        'hand': None,
        'steps': [],
        'positions': [],
        'lesson_notes': None,
        'lesson_id': lesson_id,
    }

    if not poker_db_path or not os.path.exists(poker_db_path):
        return result

    try:
        conn = sqlite3.connect(poker_db_path)
        conn.row_factory = sqlite3.Row

        # Fetch hand metadata
        row = conn.execute(
            "SELECT * FROM hands WHERE hand_id = ?", (hand_id,)
        ).fetchone()
        if row is None:
            conn.close()
            return result

        hand = dict(row)

        # Fetch ordered actions
        action_rows = conn.execute(
            "SELECT * FROM hand_actions WHERE hand_id = ? "
            "ORDER BY CASE street "
            "  WHEN 'preflop' THEN 1 WHEN 'flop' THEN 2 "
            "  WHEN 'turn' THEN 3 WHEN 'river' THEN 4 END, "
            "sequence_order",
            (hand_id,),
        ).fetchall()
        actions = [dict(r) for r in action_rows]

        # Fetch lesson notes if requested
        lesson_notes = None
        if lesson_id is not None:
            lesson_row = conn.execute(
                "SELECT l.title, l.category, l.description, "
                "hl.executed_correctly, hl.street, hl.notes "
                "FROM lessons l "
                "LEFT JOIN hand_lessons hl "
                "  ON l.lesson_id = hl.lesson_id AND hl.hand_id = ? "
                "WHERE l.lesson_id = ?",
                (hand_id, lesson_id),
            ).fetchone()
            if lesson_row:
                lesson_notes = dict(lesson_row)

        conn.close()

        # Build steps
        steps = _build_replay_steps(actions)

        # Canonical position order for table layout
        _POS_ORDER = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']
        seen_positions = []
        for step in steps:
            pos = step['position']
            if pos and pos not in seen_positions:
                seen_positions.append(pos)
        # Sort by canonical order (unknown positions appended)
        def _pos_key(p):
            try:
                return _POS_ORDER.index(p)
            except ValueError:
                return len(_POS_ORDER)
        seen_positions.sort(key=_pos_key)

        result['hand'] = hand
        result['steps'] = steps
        result['positions'] = seen_positions
        result['lesson_notes'] = lesson_notes

    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass

    return result
