"""Cash game routes."""

from flask import Blueprint, render_template, current_app, request

from src.web.data import load_analytics_data, prepare_overview_data

cash_bp = Blueprint('cash', __name__)

VALID_TABS = ('overview', 'sessions', 'stats', 'leaks', 'ev', 'range', 'tilt')


@cash_bp.route('/')
def cash_index():
    """Redirect to overview."""
    from flask import redirect, url_for
    return redirect(url_for('cash.sub_tab', tab='overview'))


@cash_bp.route('/<tab>')
def sub_tab(tab):
    """Render a cash sub-tab page."""
    if tab not in VALID_TABS:
        tab = 'overview'

    db_path = current_app.config['ANALYTICS_DB_PATH']
    data = load_analytics_data(db_path, 'cash')

    if tab == 'overview':
        period = request.args.get('period', 'year')
        from_date = request.args.get('from', '')
        to_date = request.args.get('to', '')
        prepare_overview_data(data, period=period,
                              from_date=from_date, to_date=to_date)

    return render_template(
        f'cash/{tab}.html',
        active_section='cash',
        active_tab=tab,
        data=data,
    )
