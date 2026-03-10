"""Main routes (index redirect)."""

from flask import Blueprint, redirect, url_for

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Redirect to cash overview as default landing page."""
    return redirect(url_for('cash.sub_tab', tab='overview'))
