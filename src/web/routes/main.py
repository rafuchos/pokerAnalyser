"""Main routes (index redirect + hand replayer)."""

from flask import Blueprint, current_app, redirect, render_template, request, url_for

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Redirect to cash overview as default landing page."""
    return redirect(url_for('cash.sub_tab', tab='overview'))


@main_bp.route('/hand/<hand_id>')
def hand_replayer(hand_id):
    """Render the step-by-step hand replayer for a given hand."""
    from src.web.data import prepare_hand_replayer
    poker_db_path = current_app.config.get('POKER_DB_PATH', '')
    lesson_id = request.args.get('lesson', type=int)
    game_type = request.args.get('game_type', 'cash')

    data = prepare_hand_replayer(hand_id, poker_db_path, lesson_id=lesson_id)

    return render_template(
        'hand_replayer.html',
        active_section=game_type,
        active_tab='sessions',
        data=data,
        hand_id=hand_id,
        game_type=game_type,
        lesson_id=lesson_id,
    )
