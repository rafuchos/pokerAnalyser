"""Flask application factory for Poker Analyzer web UI."""

import os

from flask import Flask


def create_app(analytics_db_path: str = 'analytics.db',
               poker_db_path: str = None,
               debug: bool = False) -> Flask:
    """Create and configure the Flask application.

    Args:
        analytics_db_path: Path to analytics.db (read-only).
        poker_db_path: Path to poker.db (source DB for lesson drill-down).
        debug: Enable Flask debug mode for hot reload.
    """
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), 'static'),
    )
    app.config['DEBUG'] = debug
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['ANALYTICS_DB_PATH'] = analytics_db_path
    app.config['POKER_DB_PATH'] = poker_db_path or ''

    from src.web.routes.main import main_bp
    from src.web.routes.cash import cash_bp
    from src.web.routes.tournament import tournament_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(cash_bp, url_prefix='/cash')
    app.register_blueprint(tournament_bp, url_prefix='/tournament')

    @app.context_processor
    def inject_globals():
        return {
            'app_title': 'Poker Analyzer',
            'sub_tabs': [
                ('overview', 'Overview'),
                ('sessions', 'Sessions'),
                ('stats', 'Stats'),
                ('leaks', 'Leaks'),
                ('ev', 'EV Analysis'),
                ('range', 'Range'),
                ('tilt', 'Tilt'),
                ('sizing', 'Sizing'),
                ('lessons', 'Aulas'),
                ('satellites', 'Satellites'),
            ],
        }

    return app
