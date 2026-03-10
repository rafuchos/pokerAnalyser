"""Tournament routes."""

from flask import Blueprint, render_template, current_app, request

from src.web.data import load_analytics_data, prepare_overview_data

tournament_bp = Blueprint('tournament', __name__)

VALID_TABS = ('overview', 'sessions', 'stats', 'leaks', 'ev', 'range', 'tilt')


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

    if tab == 'overview':
        period = request.args.get('period', 'year')
        from_date = request.args.get('from', '')
        to_date = request.args.get('to', '')
        prepare_overview_data(data, period=period,
                              from_date=from_date, to_date=to_date)

    return render_template(
        f'tournament/{tab}.html',
        active_section='tournament',
        active_tab=tab,
        data=data,
    )
