"""Data access layer for the web UI – reads from analytics.db."""

import json
import os
import sqlite3
from datetime import datetime, timedelta


# ── Health ranges for HUD badge classification (6-max NL) ────────

_HEALTHY_RANGES = {
    'vpip': (22, 30), 'pfr': (17, 25), 'three_bet': (7, 12),
    'fold_to_3bet': (40, 55), 'ats': (30, 45),
    'af': (2.0, 3.5), 'cbet': (60, 80), 'fold_to_cbet': (35, 50),
    'wtsd': (25, 33), 'wsd': (50, 65),
}

_WARNING_RANGES = {
    'vpip': (18, 35), 'pfr': (14, 30), 'three_bet': (5, 15),
    'fold_to_3bet': (35, 65), 'ats': (25, 50),
    'af': (1.5, 4.5), 'cbet': (50, 90), 'fold_to_cbet': (30, 60),
    'wtsd': (22, 38), 'wsd': (45, 70),
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

        # Count leaks across sessions
        sess_list = day.get('sessions') or []
        leak_count = 0
        for sess in sess_list:
            leak_count += len(sess.get('leak_summary') or [])
        day['leak_count'] = leak_count

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


def prepare_session_day(data, date):
    """Enrich analytics data with detail for a specific day.

    Adds: session_day (the day report with enriched sessions).
    Each session gets sparkline SVG points, EV chart SVG points,
    health badges, and best/worst comparison markers.
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

    # Add health badges for day-level stats
    ds = day_report.get('day_stats') or {}
    for s in _STAT_NAMES:
        val = ds.get(s)
        day_report[f'{s}_val'] = val
        day_report[f'{s}_badge'] = _classify_health(s, val)

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

        # Stats with health badges
        stats = s.get('stats') or {}
        for stat in _STAT_NAMES:
            val = stats.get(stat)
            s[f'{stat}_val'] = val
            health = stats.get(f'{stat}_health', '')
            if not health and val is not None:
                health = _classify_health(stat, val)
            s[f'{stat}_badge'] = health

        # Sparkline SVG points (stack evolution)
        sparkline = s.get('sparkline') or []
        if sparkline:
            vals = [p.get('profit', 0) for p in sparkline]
            s['sparkline_points'] = _build_chart_points(vals, width=200, height=40, padding=2)
            s['sparkline_final'] = vals[-1] if vals else 0
        else:
            s['sparkline_points'] = ''
            s['sparkline_final'] = 0

        # EV chart SVG points
        ev = s.get('ev_data')
        if ev and ev.get('chart_data'):
            cd = ev['chart_data']
            real_vals = [p.get('real', 0) for p in cd]
            ev_vals = [p.get('ev', 0) for p in cd]
            all_vals = real_vals + ev_vals
            s['ev_chart'] = {
                'real_points': _build_chart_points(real_vals, width=200, height=60, padding=4),
                'ev_points': _build_chart_points(ev_vals, width=200, height=60, padding=4),
                'y_min': min(all_vals) if all_vals else 0,
                'y_max': max(all_vals) if all_vals else 0,
            }
        else:
            s['ev_chart'] = None

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


def prepare_overview_data(data, period='year', from_date='', to_date=''):
    """Enrich analytics data with overview aggregations.

    Adds: monthly_stats, weekly_stats, overall_row, profit_chart, redline_chart.
    """
    daily_reports = data.get('daily_reports', [])
    filtered = _filter_reports_by_period(daily_reports, period, from_date, to_date)
    data['active_period'] = period
    data['custom_from'] = from_date
    data['custom_to'] = to_date

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
    for s in ['vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats']:
        overall[s] = pf.get(s)
        overall[f'{s}_badge'] = pf.get(f'{s}_badge', '') or pf.get(f'{s}_health', '')

    po = data.get('postflop_overall', {})
    for s in ['af', 'cbet', 'fold_to_cbet', 'wtsd', 'wsd']:
        overall[s] = po.get(s)
        overall[f'{s}_badge'] = po.get(f'{s}_badge', '') or po.get(f'{s}_health', '')

    ev = data.get('allin_ev', {})
    overall['ev_bb100'] = ev.get('bb100_ev')
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

    return data
