"""Tournament routes."""

from flask import Blueprint, render_template, current_app, request

from src.web.data import (
    load_analytics_data,
    prepare_overview_data,
    prepare_sessions_list,
    prepare_session_day,
    prepare_stats_data,
    prepare_leaks_data,
    prepare_ev_data,
    prepare_range_data,
    prepare_tilt_data,
    prepare_sizing_data,
    prepare_lessons_data,
    prepare_satellites_data,
)

tournament_bp = Blueprint('tournament', __name__)

VALID_TABS = ('overview', 'sessions', 'stats', 'leaks', 'ev', 'range', 'tilt', 'sizing', 'lessons', 'satellites')


@tournament_bp.route('/')
def tournament_index():
    """Redirect to overview."""
    from flask import redirect, url_for
    return redirect(url_for('tournament.sub_tab', tab='overview'))


@tournament_bp.route('/<tab>')
def sub_tab(tab):
    """Render a tournament sub-tab page."""
    if tab not in VALID_TABS:
        tab = 'overview'

    db_path = current_app.config['ANALYTICS_DB_PATH']
    data = load_analytics_data(db_path, 'tournament')

    period = request.args.get('period', 'year')
    from_date = request.args.get('from', '')
    to_date = request.args.get('to', '')

    if tab == 'overview':
        prepare_overview_data(data, period=period,
                              from_date=from_date, to_date=to_date)
    elif tab == 'sessions':
        page = request.args.get('page', 1, type=int)
        prepare_sessions_list(data, page=page)
    elif tab == 'stats':
        prepare_stats_data(data, period=period,
                           from_date=from_date, to_date=to_date)
        data['stats_sub'] = request.args.get('sub', 'preflop')
    elif tab == 'leaks':
        prepare_leaks_data(data, period=period,
                           from_date=from_date, to_date=to_date)
    elif tab == 'ev':
        prepare_ev_data(data, period=period,
                        from_date=from_date, to_date=to_date)
    elif tab == 'range':
        prepare_range_data(data, period=period,
                           from_date=from_date, to_date=to_date)
        data['range_active_pos'] = request.args.get('pos', '')
    elif tab == 'tilt':
        prepare_tilt_data(data, period=period,
                          from_date=from_date, to_date=to_date)
    elif tab == 'sizing':
        prepare_sizing_data(data, period=period,
                            from_date=from_date, to_date=to_date)
    elif tab == 'lessons':
        prepare_lessons_data(data, period=period,
                             from_date=from_date, to_date=to_date)
    elif tab == 'satellites':
        prepare_satellites_data(data, period=period,
                                from_date=from_date, to_date=to_date)

    return render_template(
        f'tournament/{tab}.html',
        active_section='tournament',
        active_tab=tab,
        data=data,
    )


@tournament_bp.route('/sessions/<date>')
def session_day(date):
    """Render drill-down for a specific session day."""
    db_path = current_app.config['ANALYTICS_DB_PATH']
    data = load_analytics_data(db_path, 'tournament')
    prepare_session_day(data, date)

    return render_template(
        'tournament/session_day.html',
        active_section='tournament',
        active_tab='sessions',
        data=data,
        day_date=date,
    )
